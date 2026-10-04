#!/usr/bin/env python3
"""Goal 4: the folder browser (Progress > Change folder...) and New folder... against today's UI.

    ~/pw-venv/bin/python docs/git-redesign/tools/live/folder_browser_fixed.py LAB_ID OUT_DIR
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('MANAGER', 'http://127.0.0.1:8081')
lab_id, out = sys.argv[1], sys.argv[2]
log = []


def state(page, label):
    panel = page.locator('#git-places-panel')
    print(f'=== {label}')
    print(panel.inner_text())
    for action in ('new', 'use'):
        b = page.locator(f'[data-git-places-action="{action}"]')
        if b.count():
            print(f'[{action}] disabled={b.first.is_disabled()} title={b.first.get_attribute("title")!r}')
    print('lab-tagged rows:', [r.inner_text().replace('\n', ' ') for r in page.locator('tr.row.folder').all() if 'Lab folder' in r.inner_text() or 'saves here' in r.inner_text() or 'This lab' in r.inner_text()])


def new_folder(page, name, parent_label):
    page.locator('[data-git-places-action="new"]').first.click()
    page.wait_for_timeout(800)
    dlg = page.locator('#git-new-folder-dialog')
    print(f'--- New folder dialog ({parent_label}):', dlg.inner_text().replace('\n', ' | ')[:500])
    page.fill('#git-new-folder-name', name)
    use = page.locator('#git-new-folder-use')
    if use.count() and use.is_checked():
        use.uncheck()
    page.wait_for_timeout(300)
    page.locator('#git-new-folder-confirm').click()
    page.wait_for_timeout(3500)
    visible = dlg.count() and dlg.is_visible()
    print('--- after confirm: dialog still open =', bool(visible))
    for sel in ('#git-new-folder-dialog [role=alert]', '#git-new-folder-dialog .form-error'):
        if page.locator(sel).count() and page.locator(sel).first.inner_text().strip():
            print('REFUSAL:', page.locator(sel).first.inner_text())
    return bool(visible)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('response', lambda r: log.append((r.request.method, r.url.replace(BASE, ''), r.request.post_data or '', r.status, r.text()[:200])) if '/api/' in r.url and r.request.method != 'GET' else None)
    page.goto(f'{BASE}/#lab={lab_id}&view=progress')
    page.wait_for_timeout(4000)
    summ = page.locator('#git-change-folder > summary')
    if page.locator('#git-change-folder:not([open])').count():
        summ.click()
        page.wait_for_timeout(2500)
    page.screenshot(path=os.path.join(out, 'fb-00-progress.png'), full_page=True)
    # top level
    page.locator('#git-places-panel nav.git-crumbs button').first.click()
    page.wait_for_timeout(800)
    state(page, 'top level of the repository')
    page.screenshot(path=os.path.join(out, 'fb-01-top-level.png'), full_page=True)
    # lab's own folder
    page.locator('#git-places-panel tr.row.folder[data-git-place="git-redesign"]').first.click()
    page.wait_for_timeout(800)
    state(page, "the lab's own folder git-redesign")
    page.screenshot(path=os.path.join(out, 'fb-02-lab-folder.png'), full_page=True)
    # creating folders
    page.locator('#git-places-panel nav.git-crumbs button').first.click()
    page.wait_for_timeout(500)
    if page.locator('#git-places-panel tr.row.folder[data-git-place="scratch-a"]').count():
        print('(scratch-a already listed; not created again)')
    else:
        new_folder(page, 'scratch-a', 'top level')
    state(page, 'after creating scratch-a')
    page.screenshot(path=os.path.join(out, 'fb-03-scratch-a.png'), full_page=True)
    page.locator('#git-places-panel nav.git-crumbs button').first.click()
    page.wait_for_timeout(600)
    def goto(path):
        page.locator('#git-places-panel nav.git-crumbs button').first.click()
        page.wait_for_timeout(500)
        built = ''
        for part in path.split('/'):
            built = (built + '/' + part).strip('/')
            page.locator(f'#git-places-panel tr.row.folder[data-git-place="{built}"]').first.click()
            page.wait_for_timeout(600)

    def ensure(parent, name):
        goto(parent)
        full = parent + '/' + name
        if page.locator(f'#git-places-panel tr.row.folder[data-git-place="{full}"]').count():
            print(f'({full} already listed; not created again)')
            return
        new_folder(page, name, 'inside ' + parent)
        state(page, 'after creating ' + full)

    ensure('git-redesign', 'notes')
    ensure('git-redesign/notes', 'deep')
    page.screenshot(path=os.path.join(out, 'fb-04-deep.png'), full_page=True)
    print('--- API log')
    for m, u, body, st, ans in log:
        print(m, u, body[:200], '->', st, ans)
    browser.close()
