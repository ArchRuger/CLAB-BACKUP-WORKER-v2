"""Shared Playwright/API helpers for the section-B QA run against the running 1.30.31 manager.

Not a test framework: a thin, reusable layer over the same browser flows the reproduction tools
(`repro_nested_latest.py`, `repro_apply_manifest.py`) already used, so each B-row script stays short.
Every helper drives the real page or issues the same same-origin request the page itself issues; none
of it talks to the Store directly.
"""
import json
import re
import time

BASE = 'http://127.0.0.1:8081'
LAB_ID = '904a35a79dc341ce8a4638f83fc34185'
LAB_NAME = 'restore-square'
FINAL_JOB_STATES = ('synced', 'unchanged', 'committed', 'review_pending', 'push_pending',
                     'export_pending', 'failed', 'capture_incomplete', 'dismissed', 'interrupted')


class Checker:
    def __init__(self):
        self.checks = []
        self.failed = []

    def check(self, name, ok, detail=None):
        print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail and not ok else ''), flush=True)
        self.checks.append({'check': name, 'ok': bool(ok), 'detail': str(detail)[:1200] if detail is not None else None})
        if not ok:
            self.failed.append(name)


def api(page, method, path, body=None):
    """Same-origin fetch from inside the page context (what the page itself would send)."""
    script = """(args) => fetch(args.path, {
        method: args.method,
        headers: args.body !== null ? {'Content-Type': 'application/json'} : undefined,
        body: args.body !== null ? JSON.stringify(args.body) : undefined
    }).then(async r => ({status: r.status, body: await r.json().catch(() => null)}))"""
    return page.evaluate(script, {'path': path, 'method': method, 'body': body})


def open_lab(page, reload=False):
    page.reload() if reload else page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card, #tab-progress', state='visible', timeout=30000)
    if page.locator('article.lab-card').count():
        page.click(f'article.lab-card:has(h3:text-is("{LAB_NAME}")) [data-lab]')
    page.click('#tab-progress')
    page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)


def destination_line(page):
    el = page.locator('#git-save-location .git-destination-line')
    return el.inner_text().replace('\n', ' ').strip() if el.count() else ''


def legacy_notice(page):
    el = page.locator('#git-legacy-notice')
    return el.inner_text().strip() if el.count() else ''


def poll_job(page, job_id, timeout=180):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = api(page, 'GET', f'/api/git/jobs/{job_id}')['body']
        if job.get('status') in FINAL_JOB_STATES:
            break
        time.sleep(2)
    return job


def open_change_folder(page):
    change_folder = page.locator('#git-change-folder')
    if change_folder.count() and change_folder.get_attribute('open') is None:
        page.click('#git-change-folder summary')
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=30000)


def go_to(page, path):
    page.click(f'[data-git-place="{path}"]', timeout=15000)
    page.wait_for_selector('#git-places-panel .git-crumbs [aria-current=page]', timeout=15000)


def click_save_with_retry(page, max_attempts=4, wait_each=45000):
    """Click Save progress; a transient device-read miss is retried, exactly like the reproduction
    tools' own helper. Returns once the review dialog or the job dialog is showing."""
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
        job_text = page.locator('#git-job-dialog').inner_text()
        attempts.append({'attempt': attempt, 'outcome': 'job dialog opened', 'text': job_text[:300]})
        if 'Capture incomplete' in job_text or 'could not be read' in job_text or 'Nothing changed' in job_text:
            attempts.append({'attempt': attempt, 'final_job_text': job_text[:500]})
            return attempts
        raise RuntimeError('Save progress did not open the review dialog: ' + job_text[:500])
    raise RuntimeError('Save progress never reached the review dialog after retries: ' + json.dumps(attempts)[:1000])


def complete_pending_via_recent(page, job_id, timeout=180):
    """A save submitted quietly (checkpoint/baseline dialogs, gitSubmitSave quiet mode) stops at
    review_pending without opening a dialog. Wait for that, then open Recent saves and finish the
    review the same way a student would: Review and upload... -> Upload these changes."""
    job = poll_job(page, job_id, timeout=timeout)
    if not job or job.get('status') != 'review_pending':
        return job
    # The Recent saves list re-renders on a background poll and can race a manual "open" click (it
    # keeps rows that were already open, but a click that lands between two renders can be dropped).
    # Reload once for a clean render, then retry opening the row until its upload button is visible.
    page.reload()
    page.click('#tab-progress')
    page.wait_for_selector('#git-saves-list', timeout=20000)
    row = page.locator(f'#git-saves-list [data-git-job="{job_id}"]')
    upload_button = row.locator('[data-git-job-upload]')
    for _ in range(20):
        page.locator('#git-saves-list').scroll_into_view_if_needed()
        if row.count() and row.get_attribute('open') is None:
            row.locator('summary').click()
        page.wait_for_timeout(500)
        if upload_button.count() and upload_button.is_visible():
            break
    upload_button.click()
    page.wait_for_selector('#git-diff-dialog[open]', timeout=20000)
    _, retry_resp = upload_review(page)
    page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
    final = poll_job(page, job_id, timeout=timeout)
    page.keyboard.press('Escape')
    return final


def upload_review(page, timeout=30000):
    """Click "Upload these changes" in an open review dialog; returns (job_id, retry_response)."""
    with page.expect_response(lambda r: r.request.method == 'POST' and re.search(r'/api/git/jobs/[0-9a-f]+/retry$', r.url), timeout=timeout) as resp_info:
        page.click('#git-review-push')
    retry_resp = resp_info.value.json()
    return retry_resp.get('id'), retry_resp
