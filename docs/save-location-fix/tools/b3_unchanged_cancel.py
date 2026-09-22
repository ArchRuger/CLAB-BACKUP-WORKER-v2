#!/usr/bin/env python3
"""Section B, row B3: unchanged save, cancelled review, then completed from Recent saves.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b3_unchanged_cancel.py \\
        --evidence docs/save-location-fix/evidence/12-b3-unchanged-cancel.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, open_lab, poll_job

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


def git_rev(ref='HEAD'):
    return subprocess.run(['git', '-C', str(REPO), 'rev-parse', ref], capture_output=True, text=True, check=True).stdout.strip()


def git_fetch():
    subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', '--quiet'], check=True)


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

        # ---- Part 1: save without any device change -> expect "unchanged" ----
        open_lab(page)
        git_fetch()
        head_before_unchanged = git_rev('HEAD')
        before_newest = api(page, 'GET', f'/api/labs/{LAB_ID}/git')['body']['jobs'][0]['id'] if api(page, 'GET', f'/api/labs/{LAB_ID}/git')['body']['jobs'] else ''
        page.click('#progress-save')
        try:
            page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=30000)
        except Exception:
            pass
        dialog_opened = 'diff' if page.locator('#git-diff-dialog[open]').count() else ('job' if page.locator('#git-job-dialog[open]').count() else 'none')
        dialog_text = ''
        if dialog_opened == 'job':
            dialog_text = page.locator('#git-job-dialog').inner_text()
            page.screenshot(path=f'{args.shots}/1x-b3-unchanged.png')
            page.keyboard.press('Escape')
        elif dialog_opened == 'diff':
            dialog_text = page.locator('#git-diff-dialog').inner_text()
            page.screenshot(path=f'{args.shots}/1x-b3-unchanged.png')
            page.keyboard.press('Escape')
        page.wait_for_timeout(2000)
        jobs = api(page, 'GET', f'/api/labs/{LAB_ID}/git')['body']['jobs']
        newest = jobs[0] if jobs else None
        record['steps']['unchanged'] = {'dialog_opened': dialog_opened, 'dialog_text': dialog_text[:400], 'before_newest_job_id': before_newest, 'newest_job': newest}
        head_after_unchanged = git_rev('HEAD')
        c.check('unchanged save: newest job status is "unchanged" or no new job/dialog appeared',
                (newest and newest.get('status') == 'unchanged') or newest.get('id') == before_newest or dialog_opened == 'none',
                record['steps']['unchanged'])
        c.check('unchanged save produced no new local commit', head_before_unchanged == head_after_unchanged, (head_before_unchanged, head_after_unchanged))

        # ---- Part 2: make a real change, save, CANCEL the review ----
        ceos_change('QA-B3-cancelled-review')
        git_fetch()
        origin_before_cancel = git_rev('origin/main')
        local_before_cancel = git_rev('HEAD')
        page.click('#progress-save')
        page.wait_for_selector('#git-diff-dialog[open]', timeout=45000)
        review_text = page.locator('#git-diff-dialog').inner_text()
        page.screenshot(path=f'{args.shots}/1x-b3-review-before-cancel.png')
        page.click('#git-review-cancel')
        page.wait_for_timeout(2000)
        jobs2 = api(page, 'GET', f'/api/labs/{LAB_ID}/git')['body']['jobs']
        cancelled_job = jobs2[0] if jobs2 else None
        record['steps']['cancelled'] = {'review_excerpt': review_text[:600], 'job_after_cancel': cancelled_job}
        c.check('cancelled review: job status is review_pending (or committed, not pushed)',
                cancelled_job and cancelled_job.get('status') in ('review_pending', 'committed') and not cancelled_job.get('pushed'),
                cancelled_job)
        git_fetch()
        origin_after_cancel = git_rev('origin/main')
        record['steps']['cancelled']['origin_before'] = origin_before_cancel
        record['steps']['cancelled']['origin_after'] = origin_after_cancel
        c.check('origin/main unchanged after cancelling the review (nothing pushed)', origin_before_cancel == origin_after_cancel, (origin_before_cancel, origin_after_cancel))
        local_after_cancel = git_rev('HEAD')
        record['steps']['cancelled']['local_after'] = local_after_cancel
        c.check('local checkout HAS the new commit (saved on the VM) even though it was not pushed',
                local_after_cancel != local_before_cancel, (local_before_cancel, local_after_cancel))

        # ---- Part 3: complete it from Recent saves (Review and upload...) ----
        page.locator('#git-saves-list').scroll_into_view_if_needed()
        row = page.locator(f'#git-saves-list [data-git-job="{cancelled_job["id"]}"]') if cancelled_job else page.locator('#git-saves-list .git-saved-job').first
        if row.get_attribute('open') is None:
            row.locator('summary').click()
        page.wait_for_timeout(300)
        upload_button = row.locator('[data-git-job-upload]')
        upload_label = upload_button.inner_text() if upload_button.count() else None
        record['steps']['recent_saves_upload_button_label'] = upload_label
        page.screenshot(path=f'{args.shots}/1x-b3-recent-saves-row.png')
        c.check('Recent saves row for the pending job offers "Review and upload…"', upload_label and 'Review and upload' in upload_label, upload_label)
        upload_button.click()
        page.wait_for_selector('#git-diff-dialog[open]', timeout=20000)
        page.screenshot(path=f'{args.shots}/1x-b3-review-from-recent.png')
        with page.expect_response(lambda r: r.request.method == 'POST' and '/retry' in r.url, timeout=30000) as resp_info:
            page.click('#git-review-push')
        retry_resp = resp_info.value.json()
        job_id = retry_resp.get('id')
        page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
        final_job = poll_job(page, job_id)
        record['steps']['completed_from_recent'] = {'retry_response': retry_resp, 'final_job': final_job}
        c.check('completing from Recent saves pushes the commit (synced)', final_job and final_job.get('status') == 'synced', final_job)
        page.keyboard.press('Escape')

        c.check('no page or console errors', not errors, errors[:8])
        browser.close()

    git_fetch()
    origin_final = git_rev('origin/main')
    local_final = git_rev('HEAD')
    record['steps']['final_git'] = {'local': local_final, 'origin': origin_final, 'in_sync': local_final == origin_final}
    c.check('local HEAD == origin/main after the completed upload', local_final == origin_final, (local_final, origin_final))

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
