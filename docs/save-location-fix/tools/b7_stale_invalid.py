#!/usr/bin/env python3
"""Section B, row B7 (continued): a stale review (commit pinning survives Update from the
repository) and an invalid-commit review (refused with 409 before any device is touched).

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b7_stale_invalid.py \\
        --evidence docs/save-location-fix/evidence/16-b7-stale-invalid.json \\
        --shots docs/save-location-fix/evidence \\
        --second-checkout /path/to/second/checkout
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, go_to, open_change_folder, open_lab

CEOS_NODE_NAME = 'clab-restore-square-ceos'
REPO = pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'


def git(repo, *args):
    r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    ap.add_argument('--second-checkout', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)
    second = pathlib.Path(args.second_checkout)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31',
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    c = Checker()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)

        # ---- open a review on /save-fix/Final and keep it open ----
        open_change_folder(page)
        go_to(page, 'save-fix')
        go_to(page, 'save-fix/Final')
        page.wait_for_timeout(300)
        page.click('#git-places-panel [data-git-places-action="apply"]')
        page.wait_for_selector('#restore-review-dialog[open]', timeout=20000)
        page.wait_for_selector('#restore-review-dialog .restore-targets', timeout=20000)
        review_text_before = page.locator('#restore-review-dialog').inner_text()
        reviewed_commit = ''
        for line in review_text_before.splitlines():
            if line.strip().startswith('Source:'):
                reviewed_commit = line.strip().split('·')[-1].strip()
        record['steps']['reviewed_commit_short'] = reviewed_commit
        record['steps']['review_text_before'] = review_text_before[:600]
        page.screenshot(path=f'{args.shots}/1x-b7-stale-review-open.png')

        # ---- from the second checkout: push a trivial commit changing save-fix/Final/ceos.cfg ----
        git(second, 'fetch', 'origin', '--quiet')
        rc, out, err = git(second, 'pull', '--ff-only', 'origin', 'main')
        record['steps']['second_checkout_pull'] = {'returncode': rc, 'stdout': out[-300:], 'stderr': err[-300:]}
        old_head = git(second, 'rev-parse', 'HEAD')[1]
        cfg_path = second / 'save-fix' / 'Final' / 'ceos.cfg'
        original_text = cfg_path.read_text()
        cfg_path.write_text('! QA stale-review trivial comment\n' + original_text)
        git(second, 'add', 'save-fix/Final/ceos.cfg')
        rc, out, err = git(second, 'commit', '-m', 'QA stale-review test: trivial comment in ceos.cfg')
        record['steps']['second_checkout_commit'] = {'returncode': rc, 'stdout': out[-300:], 'stderr': err[-300:]}
        rc, out, err = git(second, 'push', 'origin', 'main')
        record['steps']['second_checkout_push'] = {'returncode': rc, 'stdout': out[-300:], 'stderr': err[-300:]}
        new_head = git(second, 'rev-parse', 'HEAD')[1]
        record['steps']['old_head'] = old_head
        record['steps']['new_head'] = new_head
        c.check('the second checkout pushed a new commit changing only save-fix/Final/ceos.cfg', rc == 0 and new_head != old_head, (rc, old_head, new_head))

        # ---- Update from the repository, WITHOUT closing the open review ----
        # The restore review is a native <dialog> shown modal (showModal()): it blocks pointer events
        # to the rest of the page by design (the same reason the "More" menu behind it cannot be
        # clicked). "Update from the repository" is issued with the identical same-origin request
        # the page's own #git-update-confirm button sends (POST /labs/<id>/git/update {}) -- the
        # product's real request, not a bypass; only the click on a now-covered button is substituted.
        update_resp_full = api(page, 'POST', f'/api/labs/{LAB_ID}/git/update', {})
        update_resp = update_resp_full['body']
        record['steps']['update_response'] = update_resp_full
        c.check('Update from the repository reached the new commit', update_resp.get('head', '')[:10] == new_head[:10], (update_resp, new_head))

        # The restore review dialog should STILL be open (Update does not close it).
        still_open = page.locator('#restore-review-dialog[open]').count() == 1
        record['steps']['review_still_open_after_update'] = still_open
        c.check('the already-open restore review is still open after Update from the repository', still_open, still_open)

        # ---- uncheck every device except ceos (ceos already matches Final; idempotent), submit ----
        checkboxes = page.locator('#restore-review-dialog input[name="restore-node"]')
        for i in range(checkboxes.count()):
            box = checkboxes.nth(i)
            if box.get_attribute('value') != CEOS_NODE_NAME and box.is_checked():
                box.uncheck()
        page.check('#restore-ack')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/restore'), timeout=20000) as info:
            page.click('#restore-run')
        submit_resp = info.value.json()
        record['steps']['stale_submit_response'] = submit_resp
        job_id = submit_resp.get('id')
        c.check('stale review submitted (job id returned)', bool(job_id), submit_resp)

        deadline = time.time() + 300
        job = None
        while job_id and time.time() < deadline:
            job = api(page, 'GET', f'/api/restore/jobs/{job_id}')['body']
            if job.get('status') not in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'):
                break
            time.sleep(5)
        record['steps']['stale_final_job'] = job
        c.check('stale-review job reached a final status', job and job.get('status') not in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'), job)
        job_source_commit = (job or {}).get('source', {}).get('commit', '')
        record['steps']['job_source_commit'] = job_source_commit
        c.check('the job\'s source commit is the REVIEWED (older) commit, not the new HEAD from Update',
                job_source_commit and job_source_commit != new_head and reviewed_commit.strip() and job_source_commit.startswith(reviewed_commit.strip()),
                (job_source_commit, reviewed_commit, new_head))

        # Compare applied bytes: the reviewed commit's ceos.eoscfg (unaffected by the second checkout's
        # change, which only touched ceos.cfg) is what a byte-exact restore would have used either way.
        rc, eoscfg_at_reviewed, err = git(REPO, 'show', f'{job_source_commit}:save-fix/Final/ceos.eoscfg')
        record['steps']['eoscfg_at_reviewed_commit_len'] = len(eoscfg_at_reviewed)
        rc2, eoscfg_at_new, err2 = git(REPO, 'show', f'{new_head}:save-fix/Final/ceos.eoscfg')
        record['steps']['eoscfg_at_new_commit_len'] = len(eoscfg_at_new)
        c.check('save-fix/Final/ceos.eoscfg content is identical at the reviewed and the new commit (only ceos.cfg changed)',
                eoscfg_at_reviewed == eoscfg_at_new, (len(eoscfg_at_reviewed), len(eoscfg_at_new)))

        c.check('no page or console errors in the stale-review test', not errors, errors[:8])

        # ==== Invalid-commit review: 409 before any device is touched ====
        fake_commit = 'a' * 40
        invalid_body = {'source': {'type': 'folder', 'path': '/save-fix/Final', 'commit': fake_commit},
                         'node_names': [CEOS_NODE_NAME], 'confirm_minutes': 5, 'acknowledge': True,
                         'request_id': 'ab' * 16}
        resp = api(page, 'POST', f'/api/labs/{LAB_ID}/restore', invalid_body)
        record['steps']['invalid_commit_response'] = resp
        c.check('submitting a restore with a commit id not in the branch history is refused with 409',
                resp['status'] == 409, resp)

        c.check('no page or console errors overall', not errors, errors[:8])
        browser.close()

    record['checks'] = c.checks
    record['failed'] = c.failed
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'STALE + INVALID COMMIT: {passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
