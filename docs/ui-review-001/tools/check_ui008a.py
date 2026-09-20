#!/usr/bin/env python3
"""UI-008 (part 1) browser check: a folder made in the folder browser does not disappear.

Runs against the fixture manager, whose scripted Git helper retires registrations and refuses
overlapping lab folders like app/host_git.py. It changes where the fixture lab saves; use a scratch
FIXTURE_DATA directory.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui008a.py
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
HOME = os.environ.get('CLAB_FOLDER', 'labs/BGP/work')   # where the fixture lab saves
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def shot(page, name):
    if OUT:
        page.locator('#git-save-location').screenshot(path=os.path.join(OUT, name + '.png'))


def open_progress(page):
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card, #lab-content:not([hidden])')
    if page.is_visible('article.lab-card'):
        page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.click('#tab-progress')
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=20000)


OUTLINE = '() => [...document.querySelectorAll("#git-places-panel .git-outline summary")].map(s => s.dataset.gitPlace)'
DESTINATION = '() => document.querySelector("#git-save-location .git-destination-line").innerText.replace(/\\s+/g, " ")'


def new_folder(page, parent, name, use):
    page.click(f'#git-places-panel .git-outline summary[data-git-place="{parent}"]')
    page.click('[data-git-places-action="new"]')
    page.wait_for_selector('#git-new-folder-dialog[open]')
    page.fill('#git-new-folder-name', name)
    if page.is_checked('#git-new-folder-use') != use:
        page.click('#git-new-folder-use')
    if use and page.query_selector('#git-new-folder-move') and page.is_checked('#git-new-folder-move'):
        page.click('#git-new-folder-move')
    page.click('#git-new-folder-confirm')


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1366, 'height': 900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    open_progress(page)
    working, solution = HOME + '/working', HOME + '/solution'
    before = page.evaluate(DESTINATION)

    # 1. Create "working" beneath the folder the lab saves to, without moving the lab there
    new_folder(page, HOME, 'working', use=False)
    page.wait_for_function('(p) => !!document.querySelector(`#git-places-panel .git-outline summary[data-git-place="${p}"]`)', arg=working, timeout=20000)
    check('the new folder appears at once under its parent', working in page.evaluate(OUTLINE))
    check('it is selected and can be chosen as the destination', page.evaluate('() => document.querySelector("#git-places-panel .git-crumbs [aria-current=page]").textContent') == 'working' and page.is_enabled('[data-git-places-action="use"]'))
    check('it is described truthfully as empty and not in the repository yet', 'appears in the repository with the first save' in page.inner_text('#git-places-panel .git-listing'))
    check('creating it did not change where the lab saves', page.evaluate(DESTINATION) == before, page.evaluate(DESTINATION))
    toast = page.inner_text('#toast')
    check('the message says the lab still saves where it did', 'still saves to ' + HOME in toast, toast)
    shot(page, 'ui008a-created')
    time.sleep(9)
    check('it is still there after two background polls', working in page.evaluate(OUTLINE))
    open_progress(page)
    check('it is still there after reloading the page', working in page.evaluate(OUTLINE))
    page.click('#tab-topology')
    page.click('#tab-progress')
    check('and after leaving and reopening the tab', working in page.evaluate(OUTLINE))

    # 2. A duplicate is refused in the dialog, with no success message
    page.evaluate('() => { document.getElementById("toast").textContent = ""; }')
    new_folder(page, HOME, 'working', use=False)
    page.wait_for_function('() => /already exists/.test(document.querySelector("#git-new-folder-dialog .form-error, #git-new-folder-dialog [role=alert]")?.textContent || "")', timeout=15000)
    check('a duplicate name is refused with the reason', True)
    check('and nothing is reported as created', 'is listed' not in page.inner_text('#toast') and page.evaluate(OUTLINE).count(working) == 1)
    page.click('#git-new-folder-cancel')

    # 3. The lab moves into it, then on to a second new folder: the first one used to vanish here
    page.click(f'#git-places-panel .git-outline summary[data-git-place="{working}"]')
    page.click('[data-git-places-action="use"]')
    page.wait_for_selector('#git-folder-dialog[open]')
    if page.query_selector('#git-move-files') and page.is_checked('#git-move-files'):
        page.click('#git-move-files')
    page.click('#git-folder-confirm')
    page.wait_for_function('(p) => document.querySelector("#git-save-location .git-destination-line").innerText.includes(p)', arg=working, timeout=30000)
    check('Save this lab here moves the lab into the empty folder', True)
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=20000)
    new_folder(page, HOME, 'solution', use=True)
    page.wait_for_function('(p) => document.querySelector("#git-save-location .git-destination-line").innerText.includes(p)', arg=solution, timeout=30000)
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=20000)
    outline = page.evaluate(OUTLINE)
    check('after the lab moved on, the folder it left is still listed (the reported defect)', working in outline and solution in outline, outline)
    registered = page.evaluate('''async () => (await (await fetch('/api/git/repositories')).json()).repositories.map(r => r.prefix)''')
    check('on the VM only the folder in use is registered, as before', working not in registered and solution in registered, registered)
    shot(page, 'ui008a-after-moving-on')
    open_progress(page)
    check('and it is still listed after a reload', working in page.evaluate(OUTLINE))

    # 4. An empty folder nobody uses can be removed from the list
    page.click(f'#git-places-panel .git-outline summary[data-git-place="{working}"]')
    page.click('[data-git-places-action="forget"]')
    page.wait_for_function('(p) => !document.querySelector(`#git-places-panel .git-outline summary[data-git-place="${p}"]`)', arg=working, timeout=20000)
    check('Remove empty folder takes it off the list', True)
    page.click(f'#git-places-panel .git-outline summary[data-git-place="{HOME}"]')
    check('a folder with saved files offers no removal', not page.query_selector('[data-git-places-action="forget"]'))
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
