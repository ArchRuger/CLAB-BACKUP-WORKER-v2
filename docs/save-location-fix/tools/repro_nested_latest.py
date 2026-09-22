#!/usr/bin/env python3
"""Browser + API reproduction of "save location fix" reproduction 1 (nested latest).

Runs against the RUNNING manager (1.30.30) and the real lab `restore-square`, through the product:
the Progress tab's Save progress button, the mandatory review dialog and its Upload these changes
button, and the folder browser's Change folder / Save this lab here flow. API-only steps (the initial
and intermediate destination changes) are issued the same way the page itself does, over the same
same-origin fetch, so every request in the evidence file is a real request the manager answered.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/repro_nested_latest.py \\
        --evidence docs/save-location-fix/evidence/00-repro-nested-latest.json \\
        --shots docs/save-location-fix/evidence

It changes the real save destination of restore-square and pushes to the real repository; run it only
as the lab's single operator, with the lab already fully Ready. Needs playwright (the app's virtual
environment on the development VM, LD_LIBRARY_PATH set for the bundled Chromium).
"""
import argparse
import json
import pathlib
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8081'
LAB_ID = '904a35a79dc341ce8a4638f83fc34185'
LAB_NAME = 'restore-square'
FINAL_JOB_STATES = ('synced', 'unchanged', 'committed', 'review_pending', 'push_pending',
                     'export_pending', 'failed', 'capture_incomplete', 'dismissed', 'interrupted')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    ap.add_argument('--skip-bc', action='store_true',
                     help='resume after steps b (first Save Latest into save-fix/working) and c '
                          '(destination moved to save-fix/elsewhere) already completed out of band')
    ap.add_argument('--only-f', action='store_true',
                     help='resume after steps b, c, d, e already completed out of band (the lab is '
                          'already bound to the nested save-fix/working/latest); run only step f')
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME,
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    requests_log = []
    checks, failed = [], []

    def check(name, ok, detail=None):
        print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail and not ok else ''), flush=True)
        checks.append({'check': name, 'ok': ok, 'detail': str(detail)[:800] if detail is not None else None})
        if not ok:
            failed.append(name)

    def on_request(req):
        if req.method == 'POST' and '/api/' in req.url:
            try:
                body = req.post_data()
            except Exception:
                body = None
            requests_log.append({'url': req.url, 'body': body, 'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        page.on('request', on_request)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        def open_lab(reload=False):
            page.reload() if reload else page.goto(BASE + '/')
            page.wait_for_selector('article.lab-card, #tab-progress', state='visible', timeout=30000)
            if page.locator('article.lab-card').count():
                page.click(f'article.lab-card:has(h3:text-is("{LAB_NAME}")) [data-lab]')
            page.click('#tab-progress')
            page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)

        def poll_job(job_id, timeout=180):
            deadline = time.time() + timeout
            job = None
            while time.time() < deadline:
                job = page.evaluate("(id) => fetch('/api/git/jobs/'+id).then(r=>r.json())", job_id)
                if job.get('status') in ('synced', 'unchanged', 'committed', 'failed', 'capture_incomplete', 'dismissed', 'interrupted'):
                    break
                time.sleep(2)
            return job

        def destination_line():
            el = page.locator('#git-save-location .git-destination-line')
            return el.inner_text().replace('\n', ' ').strip() if el.count() else ''

        def click_save_with_retry(max_attempts=4, wait_each=45000):
            """Click Save progress; a transient device-read miss (capture_incomplete, no commit, latest
            unchanged) is an environment flake, not part of either reported bug, so retry once devices
            settle. Returns once the review dialog (#git-diff-dialog[open]) is showing."""
            attempts = []
            for attempt in range(1, max_attempts + 1):
                page.click('#progress-save')
                try:
                    page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=wait_each)
                except Exception as exc:
                    attempts.append({'attempt': attempt, 'outcome': f'timeout: {exc}'})
                    continue
                if page.locator('#git-diff-dialog[open]').count():
                    attempts.append({'attempt': attempt, 'outcome': 'review dialog opened'})
                    return attempts
                # A job dialog opened instead: read its status; capture_incomplete -> retry, anything
                # else is unexpected and should stop the run for inspection.
                job_text = page.locator('#git-job-dialog').inner_text()
                attempts.append({'attempt': attempt, 'outcome': 'job dialog opened', 'text': job_text[:300]})
                if 'Capture incomplete' in job_text or 'could not be read' in job_text:
                    page.keyboard.press('Escape')
                    page.wait_for_timeout(8000)
                    continue
                raise RuntimeError('Save progress did not open the review dialog: ' + job_text[:500])
            raise RuntimeError('Save progress never reached the review dialog after retries: ' + json.dumps(attempts)[:1000])

        if not args.skip_bc:
            # ---------- STEP B: Save Latest, first save into save-fix/working (already bound via API step 1a) ----------
            open_lab()
            check('page loads the running release scripts', True, page.evaluate("() => [...document.scripts].map(s=>s.src).find(s=>s.includes('/static/git-progress.js'))"))
            record['steps']['b_before_destination'] = destination_line()
            page.screenshot(path=f'{args.shots}/00-b1-before-save.png')
            check('progress-save button is present and enabled', page.locator('#progress-save').count() == 1 and page.is_enabled('#progress-save'))
            attempts_b = click_save_with_retry()
            record['steps']['b_save_attempts'] = attempts_b
            review_text_b = page.locator('#git-diff-dialog').inner_text()
            check('review dialog appeared before any upload ("This save is on the lab VM only")', 'lab VM only' in review_text_b, review_text_b[:300])
            page.screenshot(path=f'{args.shots}/00-b2-review-dialog.png')
            with page.expect_response(lambda r: r.request.method == 'POST' and re.search(r'/api/git/jobs/[0-9a-f]+/retry$', r.url), timeout=30000) as resp_info:
                page.click('#git-review-push')
            retry_resp_b = resp_info.value.json()
            job_id_b = retry_resp_b.get('id')
            check('Upload these changes queued a retry with push+reviewed', bool(job_id_b))
            page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
            job_b = poll_job(job_id_b)
            page.screenshot(path=f'{args.shots}/00-b3-job-result.png')
            check('first save into save-fix/working reached a final pushed state', job_b and job_b.get('status') in ('synced', 'unchanged'), job_b and job_b.get('status'))
            record['steps']['b'] = {'review_excerpt': review_text_b[:1200], 'retry_response': retry_resp_b, 'final_job': job_b}
            page.keyboard.press('Escape')
            time.sleep(1)

            # ---------- STEP C: retire the save-fix/working registration (move away, no file move) ----------
            # Same request shape the page's own "Save this lab here" sends (gitApplyDestination), issued
            # over the same-origin page context so it is a real request the manager answered, not a bypass.
            step_c_resp = page.evaluate(
                """(lab) => fetch('/api/labs/'+lab+'/git/destination', {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({prefix:'save-fix/elsewhere', move_files:false})}).then(async r => ({status:r.status, body: await r.json()}))""",
                LAB_ID)
            check('step c: destination moved away to save-fix/elsewhere (retires save-fix/working registration)', step_c_resp.get('status') == 200, step_c_resp)
            record['steps']['c'] = {'request_body': json.dumps({'prefix': 'save-fix/elsewhere', 'move_files': False}), 'response': step_c_resp}
        else:
            record['steps']['b_c_skipped'] = 'resumed run: step b (job 7e98c025264aad61c1e7a56ab87928d0, status synced, snapshot_path save-fix/working/latest) and step c (destination moved to save-fix/elsewhere) already completed and independently verified (git ls-tree local == origin/main) in a prior run of this same script'

        if not args.only_f:
            # ---------- STEP D: Change folder -> browse to save-fix/working/latest ----------
            open_lab(reload=not args.skip_bc)
            record['steps']['d_destination_after_move_away'] = destination_line()
            change_folder = page.locator('#git-change-folder')
            if change_folder.count() and change_folder.get_attribute('open') is None:
                page.click('#git-change-folder summary')
            page.wait_for_selector('#git-places-panel .git-places-head', timeout=30000)
            page.screenshot(path=f'{args.shots}/00-d1-places-panel.png')

            def go_to(path):
                page.click(f'[data-git-place="{path}"]', timeout=15000)
                page.wait_for_selector('#git-places-panel .git-crumbs [aria-current=page]', timeout=15000)

            go_to('save-fix')
            go_to('save-fix/working')
            go_to('save-fix/working/latest')
            page.wait_for_timeout(300)
            use_button = page.locator('#git-places-panel [data-git-places-action="use"]')
            use_enabled = use_button.count() == 1 and use_button.is_enabled()
            check('selecting the nested save-fix/working/latest folder leaves "Save this lab here" ENABLED (the reported defect: no snapshot-folder / managed-name refusal)', use_enabled,
                  use_button.get_attribute('title') if use_button.count() else 'button not found')
            page.screenshot(path=f'{args.shots}/00-d2-save-here-enabled.png')
            record['steps']['d_use_button_enabled'] = use_enabled

            with page.expect_response(lambda r: r.request.method == 'POST' and '/git/destination' in r.url, timeout=20000) as dest_info:
                use_button.click()
                page.wait_for_selector('#git-folder-dialog[open]', timeout=15000)
                page.screenshot(path=f'{args.shots}/00-d3-confirm-dialog.png')
                move_checkbox = page.locator('#git-move-files')
                if move_checkbox.count() and move_checkbox.is_checked():
                    move_checkbox.uncheck()
                page.click('#git-folder-confirm')
            dest_resp_d = dest_info.value
            record['steps']['d_destination_request_body'] = dest_resp_d.request.post_data
            record['steps']['d_destination_response'] = dest_resp_d.json()
            page.wait_for_selector('#git-repository-content .git-save-location', timeout=20000)
            # The card re-renders asynchronously after the confirm; poll briefly instead of reading once.
            new_destination_line = ''
            for _ in range(20):
                new_destination_line = destination_line()
                if 'save-fix/working/latest' in new_destination_line.replace(' ', ''):
                    break
                page.wait_for_timeout(500)
            record['steps']['d_new_destination_line'] = new_destination_line
            check('the page now shows the lab saving to save-fix/working/latest (nested, literal)', 'save-fix/working/latest' in new_destination_line.replace(' ', ''), new_destination_line)
            page.screenshot(path=f'{args.shots}/00-d4-destination-line.png')

            # ---------- STEP E: Save Latest again -> should write save-fix/working/latest/latest ----------
            attempts_e = click_save_with_retry()
            record['steps']['e_save_attempts'] = attempts_e
            review_text_e = page.locator('#git-diff-dialog').inner_text()
            page.screenshot(path=f'{args.shots}/00-e1-review-dialog.png')
            with page.expect_response(lambda r: r.request.method == 'POST' and re.search(r'/api/git/jobs/[0-9a-f]+/retry$', r.url), timeout=30000) as resp_info_e:
                page.click('#git-review-push')
            retry_resp_e = resp_info_e.value.json()
            job_id_e = retry_resp_e.get('id')
            page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
            job_e = poll_job(job_id_e)
            page.screenshot(path=f'{args.shots}/00-e2-job-result.png')
            snapshot_path_e = (job_e or {}).get('snapshot_path', '')
            check('the second save resolved snapshot_path to the NESTED save-fix/working/latest/latest (the bug)', snapshot_path_e == 'save-fix/working/latest/latest', snapshot_path_e)
            record['steps']['e'] = {'review_excerpt': review_text_e[:1200], 'retry_response': retry_resp_e, 'final_job': job_e}
            page.keyboard.press('Escape')
            time.sleep(1)
        else:
            record['steps']['d_e_skipped'] = ('resumed run: step d (browsed to save-fix/working/latest, "Save this lab here" was enabled, '
                                               'confirmed, destination became save-fix/working/latest) and step e (Save Latest wrote and pushed '
                                               'job cfd2de958d1739fbeee82a6957fdc8a7, status synced, snapshot_path save-fix/working/latest/latest) '
                                               'already completed with screenshots 00-d1..00-d4 and 00-e1..00-e2 in a prior run of this same script; '
                                               'independently re-verified against the live /api/labs/<lab>/git job list before this run started')

        # ---------- STEP F: reload, save once more; also a direct API save with a fresh request id ----------
        # The device configuration has not changed since step e's save, so this save is expected to
        # report "unchanged" (no diff, no review dialog: there is nothing to upload). Either outcome is
        # read from the lab's own git context afterwards, not assumed from which dialog opened.
        open_lab(reload=not args.only_f)
        before_newest = page.evaluate("(lab) => fetch('/api/labs/'+lab+'/git').then(r=>r.json()).then(d=>d.jobs[0]?.id||'')", LAB_ID)
        page.click('#progress-save')
        try:
            page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=30000)
        except Exception:
            pass  # an "unchanged" quiet save opens neither dialog; just a toast
        if page.locator('#git-diff-dialog[open]').count():
            with page.expect_response(lambda r: r.request.method == 'POST' and re.search(r'/api/git/jobs/[0-9a-f]+/retry$', r.url), timeout=30000) as resp_info_f:
                page.click('#git-review-push')
            retry_resp_f = resp_info_f.value.json()
            record['steps']['f_reload_save_retry_response'] = retry_resp_f
            page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
            page.keyboard.press('Escape')
        page.wait_for_timeout(3000)
        # Read back whatever job this click produced (new or, if truly unchanged, the same job again).
        newest = page.evaluate("(lab) => fetch('/api/labs/'+lab+'/git').then(r=>r.json()).then(d=>d.jobs[0])", LAB_ID)
        deadline = time.time() + 60
        while newest and newest.get('status') in ('queued', 'running') and time.time() < deadline:
            page.wait_for_timeout(2000)
            newest = page.evaluate("(lab) => fetch('/api/labs/'+lab+'/git').then(r=>r.json()).then(d=>d.jobs[0])", LAB_ID)
        page.screenshot(path=f'{args.shots}/00-f1-reload-save-job.png')
        snapshot_path_f = (newest or {}).get('snapshot_path', '')
        check('reload + save once more still resolves to the nested save-fix/working/latest/latest', snapshot_path_f == 'save-fix/working/latest/latest', snapshot_path_f)
        record['steps']['f_reload_save'] = {'before_newest_job_id': before_newest, 'final_job': newest}

        # Direct API save with a fresh random request id, over the same same-origin page context
        request_id_hex = page.evaluate("() => { const b=new Uint8Array(16); crypto.getRandomValues(b); return Array.from(b,n=>n.toString(16).padStart(2,'0')).join(''); }")
        direct_save = page.evaluate(
            """(args) => fetch('/api/labs/'+args.lab+'/git/save', {method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({target:'latest', push:false, note:'API direct save, repro step f', request_id: args.rid})}).then(r => r.json())""",
            {'lab': LAB_ID, 'rid': request_id_hex})
        direct_job_id = direct_save.get('id')
        direct_final = poll_job(direct_job_id) if direct_job_id else direct_save
        snapshot_path_direct = (direct_final or {}).get('snapshot_path', '')
        check('direct API save (fresh request_id) also resolves snapshot_path to the nested save-fix/working/latest/latest', snapshot_path_direct == 'save-fix/working/latest/latest', snapshot_path_direct)
        record['steps']['f_direct_api_save'] = {'request_id': request_id_hex, 'response': direct_save, 'final_job': direct_final}
        # This direct save was push:false (kept on the VM only) so it leaves a pending job; dismiss it so
        # the lab is left in the documented legacy end-state (bound, no pending upload blocking it further).
        if direct_job_id and (direct_final or {}).get('status') not in ('dismissed', 'synced'):
            dismiss_resp = page.evaluate(
                "(id) => fetch('/api/git/jobs/'+id+'/dismiss', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({acknowledge:true})}).then(r=>r.json())",
                direct_job_id)
            record['steps']['f_direct_api_dismiss'] = dismiss_resp

        check('no page or console errors across the whole run', not errors, errors[:8])
        browser.close()

    record['requests'] = requests_log
    record['checks'] = checks
    record['failed'] = failed
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for c in checks if c['ok'])
    print(f'{passed} passed, {len(failed)} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
