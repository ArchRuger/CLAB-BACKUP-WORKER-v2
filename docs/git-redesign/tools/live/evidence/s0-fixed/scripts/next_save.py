#!/usr/bin/env python3
"""A later save of a lab that already has a save location, through today's UI, then review and upload.

    ~/pw-venv/bin/python docs/git-redesign/tools/live/next_save.py LAB_ID OUT_DIR PREFIX NOTE

Header Save progress, the label dialog, then Review and upload. Prints the mutating API calls (trimmed) and
the review's file headings only (no configuration text).
"""
import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('MANAGER', 'http://127.0.0.1:8081')
lab_id, out, prefix, note = sys.argv[1:5]
log = []
trim = lambda t, n=400: t if len(t) <= n else t[:n] + ' ...[trimmed]'
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    page.on('response', lambda r: log.append((r.request.method, r.url.replace(BASE, ''), r.request.post_data or '', r.status, r.text() if 'json' in (r.headers.get('content-type') or '') else '')) if '/api/' in r.url and r.request.method != 'GET' else None)
    page.goto(f'{BASE}/#lab={lab_id}')
    page.wait_for_timeout(4000)
    page.locator('#git-save-progress').click()
    page.wait_for_timeout(1500)
    page.fill('#git-label-input', note)
    page.screenshot(path=os.path.join(out, f'{prefix}-1-label.png'))
    page.locator('#git-label-confirm').click()
    for _ in range(60):
        page.wait_for_timeout(2000)
        if page.locator('#git-diff-dialog').count() and page.locator('#git-diff-dialog').is_visible():
            break
    review = page.locator('#git-diff-dialog')
    if review.count() and review.is_visible():
        text = review.inner_text()
        print('--- review: destination and changed files')
        print(' | '.join(re.findall(r'^(?:[\w./-]+) (?:added|changed|removed|modified)\s*$', text, re.M)) or '(headings not matched)')
        print(re.findall(r'[\w./-]+\s+(?:added|changed|removed|modified)\n\n[^\n]*', text))
        page.screenshot(path=os.path.join(out, f'{prefix}-2-review.png'))
        page.locator('#git-review-push').click()
        page.wait_for_timeout(15000)
        page.screenshot(path=os.path.join(out, f'{prefix}-3-uploaded.png'))
    else:
        print('(no review dialog)'); print(trim(page.locator('body').inner_text(), 1500))
    print('--- API log')
    for m, u, body, st, ans in log:
        print(m, u, trim(body, 250), '->', st, trim(re.sub(r'"(before|after)":"(?:[^"\\]|\\.)*"', r'"\1":"<omitted>"', ans), 350))
    browser.close()
