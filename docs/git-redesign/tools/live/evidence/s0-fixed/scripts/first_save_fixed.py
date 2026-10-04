#!/usr/bin/env python3
"""Goal 2 of the 'after the first fix' run: the first save through today's UI, then the review and upload.

    ~/pw-venv/bin/python docs/git-redesign/tools/live/first_save_fixed.py LAB_ID OUT_DIR [FOLDER] [NOTE]

Logs every /api request that changes something (method, path, request body) with its status and a trimmed
answer, then clicks Review and upload and Upload these changes when the job ends in review_pending.
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('MANAGER', 'http://127.0.0.1:8081')
lab_id, out = sys.argv[1], sys.argv[2]
folder = sys.argv[3] if len(sys.argv) > 3 else 'git-redesign'
note = sys.argv[4] if len(sys.argv) > 4 else 'first save of the whole lab'
log = []


def trim(text, limit=700):
    return text if len(text) <= limit else text[:limit] + ' ...[trimmed]'


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.on('response', lambda r: log.append((r.request.method, r.url.replace(BASE, ''), r.request.post_data or '', r.status, trim(r.text() if 'json' in (r.headers.get('content-type') or '') else ''))) if '/api/' in r.url and r.request.method != 'GET' else None)
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(f'{BASE}/#lab={lab_id}')
    page.wait_for_timeout(4000)
    page.screenshot(path=os.path.join(out, 'fs-01-lab.png'), full_page=True)
    page.locator('#git-save-progress').click()
    page.wait_for_timeout(2500)
    dialog = page.locator('#git-first-save-dialog')
    print('--- first-save dialog'); print(dialog.inner_text())
    page.locator('#git-first-save-dialog details summary').click()
    print('--- devices checked:', [c.is_checked() for c in page.locator('[name="git-first-node"]').all()])
    page.fill('#git-first-folder', folder)
    page.check('#git-first-ack')
    page.fill('#git-first-note', note)
    page.screenshot(path=os.path.join(out, 'fs-02-dialog-filled.png'), full_page=True)
    page.locator('#git-first-confirm').click()
    page.wait_for_timeout(1500)
    for i in range(60):
        page.wait_for_timeout(2000)
        if page.locator('#git-diff-dialog').count() and page.locator('#git-diff-dialog').is_visible():
            break
    print('--- after Save: first-save dialog visible =', dialog.count() and dialog.is_visible())
    for sel in ('[role=alert]', '.form-error'):
        if page.locator(sel).count():
            print(f'[{sel}]', ' | '.join(t for t in page.locator(sel).all_inner_texts() if t.strip()))
    page.screenshot(path=os.path.join(out, 'fs-03-after-save.png'), full_page=True)
    review = page.locator('#git-diff-dialog')
    if review.count() and review.is_visible():
        print('--- review dialog (head)'); print(trim(review.inner_text(), 1800))
        page.screenshot(path=os.path.join(out, 'fs-04-review.png'), full_page=True)
        page.locator('#git-review-push').click()
        page.wait_for_timeout(15000)
        page.screenshot(path=os.path.join(out, 'fs-05-after-upload.png'), full_page=True)
        print('--- after upload, page text (head)'); print(trim(page.locator('body').inner_text(), 1200))
    else:
        print('(no review dialog)'); print(trim(page.locator('body').inner_text(), 2000))
    print('--- page errors:', errors)
    print('--- API log (mutating requests)')
    for m, u, body, st, ans in log:
        print(m, u, trim(body, 300), '->', st, ans)
    browser.close()
