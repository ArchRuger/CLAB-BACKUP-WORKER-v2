#!/usr/bin/env python3
"""UI-008 A browser check, rewritten for the header Save and Load (Git save and load redesign): New folder, moving a lab,
and removing an empty folder from the list, in the folder chooser.

Until 1.30.x this drove the Progress tab's Save location card and its folder browser (`#git-places-panel`). Both are
gone; the folders now live in one chooser inside the Save drawer (chip > Saves to: Change..., or Save settings > Change
folder...; the tree is `#folder-tree`, its foot `#folder-foot`). The claims keep their subject and move with it:

  * the destination line states the folder the lab saves to: the chip panel's "Saves to:" and the chooser's "Saves go to";
  * New folder... makes a folder below the selected one without moving the lab: it is listed at once, selected, chosen as
    the destination with *Save here*, described as new and not in the repository yet, and it is still listed after two
    polls, after a reload and after closing and reopening the chooser (was: leaving and reopening the tab);
  * the chooser no longer says "still saves to X" in a toast (there is no toast): the lab's place is unchanged, which is
    asserted on the stored binding and on the chip panel;
  * a duplicate name is no longer refused in a dialog: the chooser selects the folder that exists and says "already
    exists. It is selected." (docs/git-redesign DESIGN.md section 6.2: a dead end became an answer); no second row is made;
  * *Save here* moves the lab into the empty folder (the line that brings the saved files along is unticked: a move waits
    for upload like a save), and on to a second new folder: the folder it left is still listed (the reported defect);
  * on the VM a folder change retires nothing (owner decision, DESIGN.md 2.4: the old claim "only the folder in use is
    registered" is now "the folder in use is registered and the ones left stay"); an empty folder nobody uses is taken
    off the manager's list with *Remove from the list* (was: Remove empty folder; app/git_progress.py forget_folder: "Nothing
    on the VM changes", so the registrations stay); a folder with saved files offers no removal.

Runs against the fixture manager, whose scripted Git helper retires registrations and refuses a lab folder inside
another's saved state like app/host_git.py. It changes where the fixture lab saves; use a scratch FIXTURE_DATA directory.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui008a.py
"""
import os
import sys

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
        page.locator('#save-drawer').screenshot(path=os.path.join(OUT, name + '.png'))


OUTLINE = '() => [...document.querySelectorAll("#folder-tree [role=treeitem]")].map(e => e.dataset.folder)'
# The chooser is rebuilt after a request; the line is read null-safely
DESTINATION = '() => (document.getElementById("folder-result")?.innerText || "").replace(/\\s+/g, " ")'
PLACE = '''async (lab) => { const s = await (await fetch('/api/state')).json(); return (s.labs.find(l => l.name === lab).git_binding.repository.prefix || '').replace(/^\\/+|\\/+$/g, ''); }'''


def open_lab(page):
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card, #lab-content:not([hidden])')
    if page.is_visible('article.lab-card'):
        page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')
    page.wait_for_function('() => document.getElementById("save-chip-text").textContent.length > 0')


def open_chooser(page):
    """The chooser from the chip panel's Saves to: Change..."""
    if page.is_hidden('#save-panel'):
        page.click('#save-chip')
    page.click('#save-change')
    page.wait_for_selector('#folder-tree')
    page.wait_for_selector('#folder-tree [role=treeitem][aria-selected=true]')


def close_chooser(page):
    page.click('#save-drawer-close')
    page.wait_for_function('() => !document.getElementById("save-drawer").open')


def select(page, folder):
    page.click(f'#folder-tree [data-folder="{folder}"] > .folder-row')
    page.wait_for_function('(f) => document.querySelector("#folder-tree [role=treeitem][aria-selected=true]")?.dataset.folder === f', arg=folder)


def new_folder(page, parent, name):
    select(page, parent)
    page.click('.folder-chooser [data-folder-action="new"]')
    page.fill('#folder-new', name)
    page.click('.folder-chooser [data-folder-action="new-add"]')
    page.wait_for_selector('#folder-new', state='detached')


def answer(page):
    page.wait_for_function('() => !/Checking/.test(document.getElementById("folder-answer")?.textContent || "Checking")')
    return page.inner_text('#folder-answer')


def save_here(page, folder):
    """Save here with the line that brings the saved files along unticked, then wait for the lab to save in `folder`."""
    box = page.locator('#folder-move input')
    if box.count() and box.is_checked():
        box.uncheck()
    page.click('#folder-foot [data-folder-action="save"]')
    page.wait_for_function('() => !document.getElementById("save-drawer").open', timeout=30000)
    page.wait_for_function('''async ([lab, folder]) => { const s = await (await fetch('/api/state')).json(); return (s.labs.find(l => l.name === lab).git_binding.repository.prefix || '').replace(/^\\/+|\\/+$/g, '') === folder; }''', arg=[LAB, folder], timeout=30000)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1366, 'height': 900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    open_lab(page)
    working, solution = HOME + '/working', HOME + '/solution'
    page.click('#save-chip')
    place = page.inner_text('#save-place')
    check('the chip panel states the folder the lab saves to', HOME in place and 'Saves to' in place, place)
    open_chooser(page)
    before = page.evaluate(DESTINATION)
    check('the chooser states the folder the lab saves to', HOME in before and 'Saves go to' in before, before)

    # 1. Create "working" beneath the folder the lab saves to, without moving the lab there
    new_folder(page, HOME, 'working')
    outline = page.evaluate(OUTLINE)
    check('the new folder appears at once under its parent', working in outline, outline)
    check('it is selected and can be chosen as the destination', page.evaluate('() => document.querySelector("#folder-tree [aria-selected=true]").dataset.folder') == working and page.is_enabled('#folder-foot [data-folder-action="save"]'))
    check('it is described truthfully as new and not in the repository yet', 'is new. It appears in the repository with the first save.' in answer(page), answer(page))
    check('creating it did not change where the lab saves', page.evaluate(PLACE, LAB) == HOME, page.evaluate(PLACE, LAB))
    shot(page, 'ui008a-created')
    page.wait_for_timeout(9000)   # two background polls, on purpose
    check('it is still there after two background polls', working in page.evaluate(OUTLINE))
    close_chooser(page)
    page.click('#save-chip')
    check('closing the chooser left the lab where it was (chip panel)', HOME in page.inner_text('#save-place') and 'working' not in page.inner_text('#save-place'), page.inner_text('#save-place'))
    page.keyboard.press('Escape')
    open_lab(page)
    open_chooser(page)
    check('it is still there after reloading the page', working in page.evaluate(OUTLINE))
    close_chooser(page)
    open_chooser(page)
    check('and after closing and reopening the chooser', working in page.evaluate(OUTLINE))

    # 2. A duplicate is not refused: the folder that exists is selected and the chooser says so; no second row
    page.evaluate('() => { document.getElementById("toast").textContent = ""; }')
    new_folder(page, HOME, 'working')
    check('a duplicate name is answered with the reason (it exists and is selected)', 'already exists. It is selected.' in page.inner_text('#folder-answer'), page.inner_text('#folder-answer'))
    check('and nothing is made twice', page.evaluate(OUTLINE).count(working) == 1 and page.evaluate('() => document.querySelector("#folder-tree [aria-selected=true]").dataset.folder') == working)

    # 3. The lab moves into it, then on to a second new folder: the first one used to vanish here
    save_here(page, working)
    check('Save here moves the lab into the empty folder', page.evaluate(PLACE, LAB) == working)
    open_chooser(page)
    page.wait_for_selector(f'#folder-tree [data-folder="{HOME}"]')
    new_folder(page, HOME, 'solution')
    save_here(page, solution)
    check('Save here moves the lab on to a second new folder', page.evaluate(PLACE, LAB) == solution)
    open_chooser(page)
    page.wait_for_selector(f'#folder-tree [data-folder="{solution}"]')
    outline = page.evaluate(OUTLINE)
    check('after the lab moved on, the folder it left is still listed (the reported defect)', working in outline and solution in outline, outline)
    registered = page.evaluate('''async () => (await (await fetch('/api/git/repositories')).json()).repositories.map(r => r.prefix)''')
    # Owner decision (docs/git-redesign DESIGN.md 2.4): a folder change registers the new folder and retires nothing, so the
    # old claim "only the folder in use is registered" became: the folder in use is registered and the ones left are kept.
    check('on the VM the folder in use is registered and a folder change retires nothing (DESIGN.md 2.4)', solution in registered and working in registered and HOME in registered, registered)
    shot(page, 'ui008a-after-moving-on')
    close_chooser(page)
    open_lab(page)
    open_chooser(page)
    check('and it is still listed after a reload', working in page.evaluate(OUTLINE))

    # 4. An empty folder nobody uses can be removed from the list
    select(page, working)
    page.click('.folder-chooser [data-folder-action="forget"]')
    page.wait_for_function('(p) => !document.querySelector(`#folder-tree [data-folder="${p}"]`)', arg=working, timeout=20000)
    check('Remove from the list takes the empty folder off the list', working not in page.evaluate(OUTLINE))
    registered = page.evaluate('''async () => (await (await fetch('/api/git/repositories')).json()).repositories.map(r => r.prefix)''')
    check('and nothing on the VM changes: the manager only forgets the folder it had planned (the registrations stay)', solution in registered and HOME in registered and working in registered, registered)
    select(page, HOME)
    check('a folder with saved files offers no removal', page.locator('.folder-chooser [data-folder-action="forget"]').count() == 0)
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
