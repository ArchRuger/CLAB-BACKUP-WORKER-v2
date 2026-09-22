#!/usr/bin/env python3
"""Section C, row C8: invalid sources and a stale review refused before any device is touched.

1. save-fix/Bad -- manifest.json is literally invalid JSON.
2. save-fix/Missing -- valid JSON, but the manifest's restore_artifact for ceos (ceos.eoscfg) is
   missing from the folder (copied from Final, that one file deleted).
3. A restore submitted with a commit id not in the branch history -> 409 (direct API, like B7).
4. A stale review: open the review on /save-fix/Final, push a trivial byte change to it from the
   second checkout, submit -- the job must use the REVIEWED commit, not the new HEAD.

For 1 and 2: what the folder browser offers, what the review dialog says (client-side preflight,
opened automatically when the dialog appears), and proof no device was contacted (the restore_jobs
list is compared before/after; a request that fails this early never reaches preflight's live SSH
probe -- see restore.py resolve_source()/decoded_snapshot(), which raises before any node candidate
is built when the manifest cannot be parsed or a referenced file is absent).

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/c8_rejections.py \\
        --secondary /path/to/scratch/CLAB-MNGR-DEV-LLM-secondary \\
        --evidence docs/save-location-fix/evidence/28-c8-rejections.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import c_lib  # noqa: E402
from c_lib import BASE, LAB_ID, LAB_NAME, Checker, api, go_to, open_change_folder, open_lab  # noqa: E402

CEOS_NODE_NAME = 'clab-restore-square-ceos'
REPO = pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'


def restore_job_ids():
    import urllib.request
    with urllib.request.urlopen(f'{BASE}/api/state', timeout=20) as r:
        state = json.load(r)
    return {j['id'] for j in state.get('restore_jobs', [])}


def seed_bad_and_missing(secondary):
    c_lib.git(secondary, 'fetch', 'origin', '--quiet')
    c_lib.git(secondary, 'reset', '--hard', 'origin/main', '--quiet')
    import shutil
    # save-fix/Bad: invalid JSON manifest, no device files needed (the folder browser only checks
    # for a file literally named manifest.json; the parse failure happens at preflight time).
    bad_dir = secondary / 'save-fix' / 'Bad'
    if (secondary / 'save-fix' / 'Bad').exists():
        c_lib.git(secondary, 'rm', '-r', '--quiet', 'save-fix/Bad')
        shutil.rmtree(bad_dir, ignore_errors=True)
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / 'manifest.json').write_text('{ this is not valid JSON ]\n')
    c_lib.git(secondary, 'add', 'save-fix/Bad')
    c_lib.git(secondary, 'commit', '--quiet', '-m', 'section C: save-fix/Bad -- invalid JSON manifest.json (C8)')

    # save-fix/Missing: copy Final's real files, then delete the restore_artifact the manifest
    # references for ceos (ceos.eoscfg) -- the manifest itself stays valid JSON.
    final_dir = secondary / 'save-fix' / 'Final'
    missing_dir = secondary / 'save-fix' / 'Missing'
    if missing_dir.exists():
        tracked = c_lib.git(secondary, 'ls-files', '--', 'save-fix/Missing')[1]
        if tracked:
            c_lib.git(secondary, 'rm', '-r', '--quiet', 'save-fix/Missing')
        shutil.rmtree(missing_dir, ignore_errors=True)
    missing_dir.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((final_dir / 'manifest.json').read_text())
    removed_artifact = None
    for entry in manifest.get('files', []):
        if entry.get('node') == CEOS_NODE_NAME and entry.get('restore_artifact'):
            removed_artifact = entry['restore_artifact']
    for item in final_dir.iterdir():
        if item.is_file() and item.name != removed_artifact:
            shutil.copy2(item, missing_dir / item.name)
    c_lib.git(secondary, 'add', 'save-fix/Missing')
    c_lib.git(secondary, 'commit', '--quiet', '-m', f'section C: save-fix/Missing -- manifest references '
              f'absent {removed_artifact} (C8)')
    c_lib.git(secondary, 'push', '--quiet', 'origin', 'main')
    return removed_artifact, c_lib.git_rev(secondary)


def probe_folder(page, path, record_key, record, c, expect_apply_offered=True):
    open_change_folder(page)
    acc = []
    for part in path.split('/'):
        acc.append(part)
        go_to(page, '/'.join(acc))
    page.wait_for_timeout(300)
    listing = page.locator('#git-places-panel').inner_text()
    apply_btn = page.locator('#git-places-panel [data-git-places-action="apply"]')
    record['steps'][record_key + '_listing'] = listing[:500]
    record['steps'][record_key + '_apply_button_count'] = apply_btn.count()
    before_jobs = restore_job_ids()
    dialog_text = None
    http_statuses = []

    def on_response(resp):
        if '/restore/preflight' in resp.url or resp.url.endswith('/restore'):
            http_statuses.append((resp.url, resp.status))

    page.on('response', on_response)
    if apply_btn.count():
        apply_btn.click()
        page.wait_for_selector('#restore-review-dialog[open]', timeout=20000)
        page.wait_for_timeout(2000)
        dialog_text = page.locator('#restore-review-dialog').inner_text()
        record['steps'][record_key + '_dialog_text'] = dialog_text[:800]
        has_targets = page.locator('#restore-review-dialog .restore-targets').count() > 0
        record['steps'][record_key + '_targets_rendered'] = has_targets
        c.check(f'{record_key}: {path} review refuses before any node is offered (no .restore-targets)',
                not has_targets, dialog_text[:300] if dialog_text else None)
        page.click('[data-op-close]') if page.locator('[data-op-close]').count() else page.keyboard.press('Escape')
        page.wait_for_timeout(500)
    page.remove_listener('response', on_response)
    record['steps'][record_key + '_http_statuses'] = http_statuses
    after_jobs = restore_job_ids()
    record['steps'][record_key + '_restore_jobs_before'] = len(before_jobs)
    record['steps'][record_key + '_restore_jobs_after'] = len(after_jobs)
    c.check(f'{record_key}: no new restore job was created (no device contacted)', after_jobs == before_jobs,
            (len(before_jobs), len(after_jobs)))
    details = page.locator('#git-change-folder')
    if details.count() and details.get_attribute('open') is not None:
        page.click('#git-change-folder summary')
    return dialog_text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secondary', required=True)
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)
    secondary = pathlib.Path(args.secondary)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31 (3dfc4912c163)',
              'started_utc': c_lib.stamp(), 'steps': {}}
    c = Checker()

    removed_artifact, seed_commit = seed_bad_and_missing(secondary)
    record['removed_artifact'] = removed_artifact
    record['seed_commit'] = seed_commit

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)

        # ---- Update from the repository to discover Bad and Missing ----
        page.click('#progress-more-button')
        page.wait_for_selector('#progress-more-menu:not([hidden])', timeout=10000)
        page.click('[data-git-action="update"]')
        page.wait_for_selector('#git-update-dialog[open]', timeout=15000)
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/git/update'), timeout=20000) as info:
            page.click('#git-update-confirm')
        update_resp = info.value.json()
        record['steps']['update_response'] = update_resp
        c.check('Update from the repository reached the seed commit', update_resp.get('head', '')[:10] == seed_commit[:10], (update_resp, seed_commit))
        page.wait_for_timeout(500)
        if page.locator('#git-update-dialog[open]').count():
            page.keyboard.press('Escape')

        # ---- save-fix/Bad: invalid JSON manifest ----
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)
        page.click('#git-open-settings')
        page.wait_for_selector('#git-binding-form', timeout=20000)
        probe_folder(page, 'save-fix/Bad', 'bad', record, c)
        page.screenshot(path=f'{args.shots}/28-c8-bad.png')

        # ---- save-fix/Missing: manifest references an absent file ----
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)
        page.click('#git-open-settings')
        page.wait_for_selector('#git-binding-form', timeout=20000)
        probe_folder(page, 'save-fix/Missing', 'missing', record, c)
        page.screenshot(path=f'{args.shots}/28-c8-missing.png')

        # ---- invalid commit id (not in the branch history) -> 409, direct API, before any device ----
        before_jobs_invalid = restore_job_ids()
        fake_commit = 'a' * 40
        invalid_body = {'source': {'type': 'folder', 'path': '/save-fix/Final', 'commit': fake_commit},
                         'node_names': [CEOS_NODE_NAME], 'confirm_minutes': 5, 'acknowledge': True,
                         'request_id': 'c8' + 'b' * 30}
        resp = api(page, 'POST', f'/api/labs/{LAB_ID}/restore', invalid_body)
        record['steps']['invalid_commit_response'] = resp
        c.check('a restore with a commit id not in the branch history is refused with 409',
                resp['status'] == 409, resp)
        after_jobs_invalid = restore_job_ids()
        c.check('invalid-commit request created no restore job (no device contacted)',
                after_jobs_invalid == before_jobs_invalid, (len(before_jobs_invalid), len(after_jobs_invalid)))

        # ---- stale review: open on /save-fix/Final, push a byte change from the second checkout,
        # confirm -- the job must use the REVIEWED commit ----
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
        page.screenshot(path=f'{args.shots}/28-c8-stale-review-open.png')

        c_lib.git(secondary, 'fetch', 'origin', '--quiet')
        c_lib.git(secondary, 'reset', '--hard', 'origin/main', '--quiet')
        old_head = c_lib.git_rev(secondary)
        cfg_path = secondary / 'save-fix' / 'Final' / 'ceos.cfg'
        original_text = cfg_path.read_bytes()
        cfg_path.write_bytes(b'! QA C8 stale-review trivial comment\n' + original_text)
        c_lib.git(secondary, 'add', 'save-fix/Final/ceos.cfg')
        c_lib.git(secondary, 'commit', '--quiet', '-m', 'QA C8 stale-review test: trivial comment in ceos.cfg')
        c_lib.git(secondary, 'push', '--quiet', 'origin', 'main')
        new_head = c_lib.git_rev(secondary)
        record['steps']['old_head'] = old_head
        record['steps']['new_head'] = new_head
        c.check('second checkout pushed a new commit changing only save-fix/Final/ceos.cfg', new_head != old_head, (old_head, new_head))

        update_resp2 = api(page, 'POST', f'/api/labs/{LAB_ID}/git/update', {})['body']
        record['steps']['update_response_2'] = update_resp2
        c.check('Update from the repository reached the new commit (review dialog stays open, unaffected)',
                update_resp2.get('head', '')[:10] == new_head[:10], (update_resp2, new_head))
        still_open = page.locator('#restore-review-dialog[open]').count() == 1
        record['steps']['review_still_open_after_update'] = still_open
        c.check('the already-open review is still open after Update from the repository', still_open, still_open)

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
            time.sleep(4)
        record['steps']['stale_final_job'] = job
        c.check('stale-review job reached a final status', job and job.get('status') not in
                ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'), job)
        job_source_commit = (job or {}).get('source', {}).get('commit', '')
        record['steps']['job_source_commit'] = job_source_commit
        c.check("the job's source commit is the REVIEWED (older) commit, not the new HEAD from Update",
                job_source_commit and job_source_commit != new_head and reviewed_commit and job_source_commit.startswith(reviewed_commit),
                (job_source_commit, reviewed_commit, new_head))

        c.check('no page or console errors across C8', not errors, errors[:10])
        browser.close()

    record['classify_end'] = c_lib.classify_all(['ceos'])
    record['checks'] = c.checks
    record['failed'] = c.failed
    record['finished_utc'] = c_lib.stamp()
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'{passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
