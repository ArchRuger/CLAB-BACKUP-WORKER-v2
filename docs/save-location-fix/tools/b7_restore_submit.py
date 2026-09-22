#!/usr/bin/env python3
"""Section B, row B7 (continued): the ONE real restore -- save-fix/Final on ceos only, via the folder
browser's Apply to running lab..., after drifting ceos to configuration B. Readback happens outside
this script (docs/multi-platform-restore/tools/readback.py), independent of the manager.

While the job runs, reopens the dialog from the lab banner and refreshes the page; verifies status
afterwards.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b7_restore_submit.py \\
        --evidence docs/save-location-fix/evidence/16-b7-restore-submit.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, go_to, open_change_folder, open_lab

CEOS_NODE_NAME = 'clab-restore-square-ceos'


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
        open_change_folder(page)
        go_to(page, 'save-fix')
        go_to(page, 'save-fix/Final')
        page.wait_for_timeout(300)
        page.click('#git-places-panel [data-git-places-action="apply"]')
        page.wait_for_selector('#restore-review-dialog[open]', timeout=20000)
        page.wait_for_selector('#restore-review-dialog .restore-targets', timeout=20000)

        dialog_text = page.locator('#restore-review-dialog').inner_text()
        record['steps']['review_text'] = dialog_text[:1200]
        page.screenshot(path=f'{args.shots}/1x-b7-real-restore-review.png')

        # Uncheck every device except ceos.
        checkboxes = page.locator('#restore-review-dialog input[name="restore-node"]')
        for i in range(checkboxes.count()):
            box = checkboxes.nth(i)
            if box.get_attribute('value') != CEOS_NODE_NAME and box.is_checked():
                box.uncheck()
        checked_values = [checkboxes.nth(i).get_attribute('value') for i in range(checkboxes.count()) if checkboxes.nth(i).is_checked()]
        record['steps']['checked_devices_before_submit'] = checked_values
        c.check('only ceos is checked before submitting the real restore', checked_values == [CEOS_NODE_NAME], checked_values)

        page.check('#restore-ack')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/restore'), timeout=20000) as info:
            page.click('#restore-run')
        submit_resp = info.value.json()
        record['steps']['submit_response'] = submit_resp
        c.check('restore submitted (job id returned)', bool(submit_resp.get('id')), submit_resp)
        job_id = submit_resp['id']

        page.wait_for_selector('#restore-job-dialog[open]', timeout=20000)
        page.screenshot(path=f'{args.shots}/1x-b7-restore-running.png')

        # While it runs: reopen the dialog from the lab banner, and refresh the page.
        page.keyboard.press('Escape')
        page.wait_for_timeout(1000)
        banner_btn = page.locator('#banner-restore')
        banner_visible = banner_btn.count() and banner_btn.is_visible()
        record['steps']['banner_restore_visible_while_running'] = banner_visible
        if banner_visible:
            banner_btn.click()
            page.wait_for_selector('#restore-job-dialog[open]', timeout=20000)
            reopened_text = page.locator('#restore-job-dialog').inner_text()
            record['steps']['reopened_from_banner_text'] = reopened_text[:500]
            page.screenshot(path=f'{args.shots}/1x-b7-restore-reopened-from-banner.png')
            page.keyboard.press('Escape')
        c.check('the running restore is reachable from the lab banner (View progress/Details)', banner_visible, banner_visible)

        page.reload()
        page.click('#tab-progress') if page.locator('#tab-progress').count() else None
        page.wait_for_timeout(1000)
        record['steps']['page_reload_ok'] = True

        # Poll to completion via the API (equivalent to what the page's own watch does).
        deadline = time.time() + 480
        job = None
        while time.time() < deadline:
            job = api(page, 'GET', f'/api/restore/jobs/{job_id}')['body']
            if job.get('status') not in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'):
                break
            time.sleep(5)
        record['steps']['final_job'] = job
        c.check('restore job reached a final status', job and job.get('status') not in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying'), job)
        c.check('restore job succeeded', job and job.get('status') == 'succeeded', job)

        # Confirm the status afterward through the page too.
        open_lab(page)
        details_btn = page.locator('#git-last-restore-open')
        if details_btn.count():
            details_btn.click()
            page.wait_for_selector('#restore-job-dialog[open]', timeout=20000)
            after_text = page.locator('#restore-job-dialog').inner_text()
            record['steps']['page_shows_restore_status_after'] = after_text[:600]
            page.screenshot(path=f'{args.shots}/1x-b7-restore-final-status.png')
            page.keyboard.press('Escape')

        c.check('no page or console errors', not errors, errors[:8])
        browser.close()

    record['checks'] = c.checks
    record['failed'] = c.failed
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'RESTORE SUBMIT: {passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
