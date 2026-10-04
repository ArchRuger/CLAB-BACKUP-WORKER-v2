#!/usr/bin/env python3
"""Reproduce the owner's defect (PROMPT.md 6.1) in a real browser against the dev2 manager.

    ~/pw-venv/bin/python docs/git-redesign/tools/live/repro_first_save.py LAB_ID [OUT_DIR]

Opens the lab's Progress tab (no save location yet, repository registered at its top level), prints what the
folder browser says for the top level and whether "New folder..." is disabled, then starts the first save
into a folder named after the lab and prints the refusal. Writes screenshots to OUT_DIR (default: cwd).
Never works around the refusal; it changes nothing on the VM when the refusal happens.
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('MANAGER', 'http://127.0.0.1:8081')
lab_id = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else '.'
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(f'{BASE}/#lab={lab_id}&view=progress')
    page.wait_for_timeout(4000)
    panel = page.locator('#git-places-panel')
    print('--- Progress tab: save location card')
    print(page.locator('#git-save-location').inner_text(timeout=5000) if page.locator('#git-save-location').count() else '(no card)')
    sel = page.locator('#git-binding-id')
    if sel.count():
        print('--- repository select options:', [o.inner_text() for o in sel.locator('option').all()])
        sel.select_option(index=1 if sel.locator('option').count() > 1 else 0)
        page.wait_for_timeout(2500)
    if panel.count():
        print('--- folder browser panel (top level)')
        print(panel.inner_text())
        new = page.locator('[data-git-places-action="new"]')
        if new.count():
            print('--- New folder button: disabled =', new.first.is_disabled(), '| title =', new.first.get_attribute('title'))
        use = page.locator('[data-git-places-action="use"]')
        if use.count():
            print('--- Choose-this-folder button: disabled =', use.first.is_disabled(), '| title =', use.first.get_attribute('title'))
    page.screenshot(path=os.path.join(out, 'folder-browser-top-level.png'), full_page=True)
    print('--- first save from the header button')
    page.locator('#git-save-progress').click()
    page.wait_for_timeout(2500)
    dialog = page.locator('#git-first-save-dialog')
    if dialog.count():
        print(dialog.inner_text())
        page.fill('#git-first-folder', 'git-redesign')
        page.check('#git-first-ack')
        if page.locator('#git-first-note').count():
            page.fill('#git-first-note', 'first save')
        page.screenshot(path=os.path.join(out, 'first-save-dialog.png'), full_page=True)
        page.locator('#git-first-confirm').click()
        page.wait_for_timeout(5000)
        print('--- after Save: dialog text')
        print(dialog.inner_text())
        for sel_ in ('[role=alert]', '.form-error', '#notice', '.toast'):
            if page.locator(sel_).count():
                print(f'[{sel_}]', ' | '.join(t for t in page.locator(sel_).all_inner_texts() if t.strip()))
        page.screenshot(path=os.path.join(out, 'first-save-refused.png'), full_page=True)
    else:
        print('(no first-save dialog; page text follows)')
        print(page.locator('body').inner_text()[:1500])
    print('--- page errors:', errors)
    browser.close()
