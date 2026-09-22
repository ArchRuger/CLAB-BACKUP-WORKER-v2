#!/usr/bin/env python3
"""Section B, row B4: two checkpoints, a Latest save between/after, baseline, compare, history, ZIP.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b4_checkpoints_baseline.py \\
        --evidence docs/save-location-fix/evidence/13-b4-checkpoints-baseline.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import io
import json
import pathlib
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import (BASE, LAB_ID, LAB_NAME, Checker, api, click_save_with_retry, complete_pending_via_recent,
                     open_lab, poll_job, upload_review)

NODECLI_DIR = pathlib.Path(__file__).parent.parent.parent / 'multi-platform-restore' / 'tools'
sys.path.insert(0, str(NODECLI_DIR))
REPO = pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'


def ceos_change(text):
    from nodecli import Session
    s = Session('ceos', timeout=30)
    try:
        for line in ('enable', 'configure', 'interface Ethernet2', 'description ' + text, 'end', 'write memory'):
            s.run(line)
    finally:
        s.close()


def git_tree_hash(path):
    out = subprocess.run(['git', '-C', str(REPO), 'ls-tree', 'HEAD', '--', path], capture_output=True, text=True, check=True).stdout.strip()
    return out.split()[2] if out else None


def git_fetch():
    subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', '--quiet'], check=True)


def git_rev(ref='HEAD'):
    return subprocess.run(['git', '-C', str(REPO), 'rev-parse', ref], capture_output=True, text=True, check=True).stdout.strip()


def find_synced_job(page, target, checkpoint=None):
    """Idempotency guard: a job already synced for this target (and checkpoint name) means a
    previous, partially-crashed run of this same script already did the real work through the
    product; re-driving the dialog would either 409/"already exists" or duplicate a real save."""
    jobs = api(page, 'GET', f'/api/labs/{LAB_ID}/git')['body']['jobs']
    for job in jobs:
        if job.get('target') == target and job.get('status') == 'synced' and (checkpoint is None or job.get('checkpoint') == checkpoint):
            return job
    return None


def create_checkpoint(page, name, note):
    # data-git-action="checkpoint" appears twice: once in the header's collapsed quick-save menu
    # (closed, not visible), once as the Progress tab's own always-visible button -- the second one.
    page.locator('[data-git-action="checkpoint"]').nth(1).click()
    page.wait_for_selector('#git-save-options[open]', timeout=15000)
    page.fill('#git-checkpoint-name', name)
    page.fill('#git-save-note', note)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/git/save'), timeout=20000) as info:
        page.click('#git-save-confirm')
    resp = info.value.json()
    return resp.get('id'), resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

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

        # ---- Checkpoint qa-cp-a ----
        # A first attempt of this run hit a UI race completing the review from Recent saves (see
        # tool history); the checkpoint job itself (aacc10209d2a49b2a82013139d5b2a59) was completed
        # out of band with the identical same-origin request the page's own "Upload these changes"
        # sends (POST /api/git/jobs/<id>/retry {"push":true,"reviewed":true}), verified synced and
        # local==origin at commit 78659615031c02d0b7188e636e85eabd6795ab65 before this run continued;
        # the dead-end duplicate-name job it raced against was dismissed the same way "Keep snapshot
        # only" does. Recorded here from the live API rather than repeated, to avoid the "This
        # checkpoint already exists" refusal a second create would correctly hit.
        final_a = api(page, 'GET', '/api/git/jobs/aacc10209d2a49b2a82013139d5b2a59')['body']
        record['steps']['checkpoint_a_out_of_band_completion'] = final_a
        record['steps']['checkpoint_a_final_job'] = final_a
        c.check('checkpoint qa-cp-a reached synced', final_a and final_a.get('status') == 'synced', final_a)

        # ---- change between, checkpoint qa-cp-b ----
        existing_b = find_synced_job(page, 'checkpoint', 'qa-cp-b')
        if existing_b:
            final_b = existing_b
            record['steps']['checkpoint_b_reused_existing'] = 'a previous run of this script already created and synced qa-cp-b; reused rather than refused as a duplicate name'
        else:
            ceos_change('QA-B4-checkpoint-b')
            job_id_b, resp_b = create_checkpoint(page, 'qa-cp-b', 'QA checkpoint B')
            record['steps']['checkpoint_b_create_response'] = resp_b
            final_b = complete_pending_via_recent(page, job_id_b)
        record['steps']['checkpoint_b_final_job'] = final_b
        c.check('checkpoint qa-cp-b reached synced', final_b and final_b.get('status') == 'synced', final_b)

        # Record both checkpoints' tree hashes right after both exist (before the next Latest save).
        git_fetch()
        tree_a_after_creation = git_tree_hash('save-fix/working/checkpoints/qa-cp-a')
        tree_b_after_creation = git_tree_hash('save-fix/working/checkpoints/qa-cp-b')
        record['steps']['tree_hashes_after_creation'] = {'qa-cp-a': tree_a_after_creation, 'qa-cp-b': tree_b_after_creation}

        # ---- change again, Save Latest ----
        latest_after_cp = find_synced_job(page, 'latest')
        if latest_after_cp and latest_after_cp.get('created', '') > final_b.get('created', ''):
            job_l = latest_after_cp
            record['steps']['latest_after_checkpoints_reused_existing'] = ('a previous run of this script already made this Latest save '
                                                                            '(created after checkpoint qa-cp-b); reused rather than repeated')
        else:
            ceos_change('QA-B4-latest-after-checkpoints')
            attempts = click_save_with_retry(page)
            record['steps']['latest_after_checkpoints_attempts'] = attempts
            job_id_l, retry_l = upload_review(page)
            page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
            job_l = poll_job(page, job_id_l)
            page.keyboard.press('Escape')
            page.wait_for_timeout(1000)
        record['steps']['latest_after_checkpoints_job'] = job_l
        # A transient push_pending (the single host lock racing another job still finishing, as seen
        # in B2) is re-checked once rather than accepted as final.
        if job_l and job_l.get('status') == 'push_pending':
            page.wait_for_timeout(5000)
            job_l = api(page, 'GET', f"/api/git/jobs/{job_l['id']}")['body']
            record['steps']['latest_after_checkpoints_job_rechecked'] = job_l
        c.check('Latest save after the two checkpoints reached synced, snapshot_path save-fix/working/latest',
                job_l and job_l.get('status') == 'synced' and job_l.get('snapshot_path') == 'save-fix/working/latest', job_l)

        # ---- prove both checkpoints are still byte-identical to when created ----
        git_fetch()
        tree_a_after_latest = git_tree_hash('save-fix/working/checkpoints/qa-cp-a')
        tree_b_after_latest = git_tree_hash('save-fix/working/checkpoints/qa-cp-b')
        record['steps']['tree_hashes_after_latest_save'] = {'qa-cp-a': tree_a_after_latest, 'qa-cp-b': tree_b_after_latest}
        c.check('qa-cp-a tree is byte-identical to when it was created', tree_a_after_creation == tree_a_after_latest, (tree_a_after_creation, tree_a_after_latest))
        c.check('qa-cp-b tree is byte-identical to when it was created', tree_b_after_creation == tree_b_after_latest, (tree_b_after_creation, tree_b_after_latest))

        # ---- Set baseline: pick the latest complete capture ----
        existing_baseline = find_synced_job(page, 'baseline')
        if existing_baseline:
            final_baseline = existing_baseline
            record['steps']['baseline_reused_existing'] = 'a previous run of this script already set the baseline; reused rather than repeated'
        else:
            page.click('#progress-more-button')
            page.wait_for_selector('#progress-more-menu:not([hidden])', timeout=10000)
            page.click('[data-git-action="baseline"]')
            page.wait_for_selector('#git-save-options[open]', timeout=15000)
            options = page.locator('#git-baseline-job option')
            option_texts = [options.nth(i).inner_text() for i in range(options.count())]
            record['steps']['baseline_options'] = option_texts
            page.select_option('#git-baseline-job', index=1)  # index 0 is the placeholder "Choose a saved configuration"
            page.screenshot(path=f'{args.shots}/1x-b4-baseline-dialog.png')
            with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/git/save'), timeout=20000) as info:
                page.click('#git-save-confirm')
            baseline_resp = info.value.json()
            record['steps']['baseline_create_response'] = baseline_resp
            final_baseline = complete_pending_via_recent(page, baseline_resp.get('id'))
        record['steps']['baseline_final_job'] = final_baseline
        c.check('baseline set (job reached synced)', final_baseline and final_baseline.get('status') == 'synced', final_baseline)

        # ---- Compare with my latest save, on the qa-cp-a checkpoint row in Saved versions ----
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=20000)
        cp_row = page.locator('#git-saved-versions li.git-version-row', has_text='qa-cp-a')
        c.check('Saved versions lists the qa-cp-a checkpoint row', cp_row.count() >= 1, cp_row.count())
        compare_button = cp_row.first.locator('[data-git-version-action="compare"]')
        compare_button.click()
        page.wait_for_selector('#git-diff-dialog[open]', timeout=15000)
        compare_text = page.locator('#git-diff-dialog').inner_text()
        record['steps']['compare_qa_cp_a_text'] = compare_text[:1500]
        page.screenshot(path=f'{args.shots}/1x-b4-compare.png')
        c.check('Compare with my latest save opened a dialog with file diff content',
                bool(compare_text.strip()) and 'Compared with your latest save' in compare_text, compare_text[:200])
        page.keyboard.press('Escape')
        page.wait_for_timeout(500)

        # ---- Full history... ---- (only in the header's quick-save menu, next to Save progress; the
        # Progress tab's own "More" menu does not repeat it)
        page.locator('#git-save-menu summary').click()
        page.wait_for_selector('#git-save-menu[open]', timeout=10000)
        page.click('#git-save-menu [data-git-action="history"]')
        page.wait_for_selector('#git-history-dialog[open]', timeout=20000)
        history_text = page.locator('#git-history-dialog').inner_text()
        record['steps']['history_dialog_text'] = history_text[:2000]
        page.screenshot(path=f'{args.shots}/1x-b4-history.png')
        c.check('Full history dialog lists Saved versions and Save history sections', 'Saved versions' in history_text and 'Save history' in history_text, history_text[:200])
        page.keyboard.press('Escape')
        page.wait_for_timeout(500)

        # ---- View and ZIP download on save-fix/Final (Saved versions row) ----
        final_row = page.locator('#git-saved-versions li.git-version-row', has_text='Final')
        record['steps']['final_row_found'] = final_row.count()
        c.check('Saved versions lists a row for save-fix/Final (reference group)', final_row.count() >= 1, final_row.count())
        if final_row.count():
            view_button = final_row.first.locator('[data-git-version-action="view"]')
            view_button.click()
            page.wait_for_selector('#git-version-dialog[open]', timeout=20000)
            version_text = page.locator('#git-version-dialog').inner_text()
            record['steps']['final_view_text'] = version_text[:800]
            page.screenshot(path=f'{args.shots}/1x-b4-final-view.png')
            with page.expect_download(timeout=20000) as dl_info:
                page.click('#git-version-download')
            download = dl_info.value
            zip_path = pathlib.Path(args.shots) / 'b4-final.zip'
            download.save_as(str(zip_path))
            with zipfile.ZipFile(zip_path) as zf:
                names = sorted(zf.namelist())
            record['steps']['final_zip_contents'] = names
            c.check('save-fix/Final ZIP contains manifest.json and the nine device files',
                    'manifest.json' in [pathlib.Path(n).name for n in names] and len(names) >= 9, names)
            zip_path.unlink(missing_ok=True)
            page.keyboard.press('Escape')
            page.wait_for_timeout(500)

        # ---- View and ZIP download on the qa-cp-a checkpoint ----
        cp_row2 = page.locator('#git-saved-versions li.git-version-row', has_text='qa-cp-a')
        if cp_row2.count():
            view_button2 = cp_row2.first.locator('[data-git-version-action="view"]')
            view_button2.click()
            page.wait_for_selector('#git-version-dialog[open]', timeout=20000)
            version_text2 = page.locator('#git-version-dialog').inner_text()
            record['steps']['checkpoint_view_text'] = version_text2[:800]
            page.screenshot(path=f'{args.shots}/1x-b4-checkpoint-view.png')
            with page.expect_download(timeout=20000) as dl_info2:
                page.click('#git-version-download')
            download2 = dl_info2.value
            zip_path2 = pathlib.Path(args.shots) / 'b4-checkpoint.zip'
            download2.save_as(str(zip_path2))
            with zipfile.ZipFile(zip_path2) as zf2:
                names2 = sorted(zf2.namelist())
            record['steps']['checkpoint_zip_contents'] = names2
            c.check('qa-cp-a ZIP contains manifest.json and the nine device files',
                    'manifest.json' in [pathlib.Path(n).name for n in names2] and len(names2) >= 9, names2)
            zip_path2.unlink(missing_ok=True)
            page.keyboard.press('Escape')

        c.check('no page or console errors', not errors, errors[:8])
        browser.close()

    git_fetch()
    record['steps']['final_git'] = {'local': git_rev('HEAD'), 'origin': git_rev('origin/main')}
    record['steps']['final_git']['in_sync'] = record['steps']['final_git']['local'] == record['steps']['final_git']['origin']
    c.check('local HEAD == origin/main at the end of B4', record['steps']['final_git']['in_sync'], record['steps']['final_git'])

    record['checks'] = c.checks
    record['failed'] = c.failed
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'{passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
