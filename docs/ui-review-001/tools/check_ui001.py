#!/usr/bin/env python3
"""UI-001 browser check: the labs the VM reports live under Manager > Labs found on the VM.

Runs against the fixture manager (docs/redesign/tools/fixture_manager.py). It changes fixture state
(old-lab stops being hidden), so use a scratch FIXTURE_DATA directory.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui001.py
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    check('Home has no discovered section', page.evaluate('() => !document.getElementById("home-discovered") && !/Also running on the VM/.test(document.body.innerText)'))
    page.click('#manager-button')
    page.click('#manager-vm-labs')
    page.wait_for_selector('#vm-labs-dialog[open]')
    # The dialog stays open, and keeps its focus, across a background poll
    page.focus('#discovered-labs [data-setup-name="extra-lab"]')
    time.sleep(5)
    check('dialog and focus survive a poll', page.evaluate('() => document.getElementById("vm-labs-dialog").open && document.activeElement?.dataset?.setupName === "extra-lab"'))
    page.click('#discovered-labs [data-setup-name="extra-lab"]')
    # The fixture VM has no files for extra-lab, so the preview is refused and the manual import opens
    # with the reason; a VM with the files answers with the confirmation instead. Both sit above this dialog.
    page.wait_for_selector('#auto-import-dialog[open], #setup-dialog[open]', timeout=15000)
    if page.evaluate('() => document.getElementById("auto-import-dialog").open'):
        check('Add to My labs opens the confirmation with the files', 'extra-lab' in page.inner_text('#auto-import-title'))
        shot, close = 'ui001-import-confirmation.png', '#auto-import-dialog .dialog-actions [data-dismiss]'
    else:
        check('a refused preview opens the manual import with the reason', 'Automatic import:' in page.inner_text('#setup-form .form-error'))
        shot, close = 'ui001-import-refused.png', '#setup-dialog .dialog-head [data-dismiss]'
    if OUT:
        page.screenshot(path=os.path.join(OUT, shot))
    page.click(close)
    labs_before = page.evaluate('() => fetch("/api/state").then(r => r.json()).then(s => s.labs.map(l => l.name))')
    check('cancelling the confirmation imports nothing', 'extra-lab' not in labs_before, labs_before)
    page.click('#excluded-labs [data-clear-exclusion="old-lab"]')
    page.wait_for_selector('#exclusion-menu[open]')
    page.click('#clear-exclusion')
    page.wait_for_function('() => !document.querySelector("#excluded-labs [data-clear-exclusion]")', timeout=15000)
    state = page.evaluate('() => fetch("/api/state").then(r => r.json())')
    check('Stop hiding clears the exclusion and imports nothing', state['discovery'].get('ignored_labs') == [] and 'old-lab' not in [l['name'] for l in state['labs']], state['discovery'].get('ignored_labs'))
    page.keyboard.press('Escape')
    check('Escape closes the dialog', page.evaluate('() => !document.getElementById("vm-labs-dialog").open'))
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
