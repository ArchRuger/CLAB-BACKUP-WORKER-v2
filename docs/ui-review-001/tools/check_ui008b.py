#!/usr/bin/env python3
"""UI-008 B browser check, rewritten for the header Save and Load (Git save and load redesign): the folder tree opens on
the lab's folder, a branch the student closes stays closed, browsing is not saving, the arrows work, a long name stays on
one line.

Until 1.30.x this drove the folder outline of the Progress tab (`#git-places-panel .git-outline`, `data-git-place`,
`data-git-twist`). The tab and the outline are gone; the one tree is the chooser's (`#folder-tree`, treeitems with
`data-folder`, a twist `data-folder-twist`), opened from the chip panel (Saves to: Change...). The claims move with it:

  * first display leads to the folder the lab saves to: the way down is open, the folder is shown selected and carries the
    tag "This lab saves here" (was: `.current` + "This lab"). A lab folder no longer lists its own latest/baseline/checkpoints
    folders, so the lab's folder is a leaf and the open branches are ['', labs, labs/BGP];
  * an ancestor can be closed without selecting anything; the destination line and the path field keep naming the lab's
    folder. The old "closed branch says This lab is inside" hint does not exist any more: the nearest claim is that the
    destination line still names the folder (reported to the lead as a page difference);
  * the fold is the student's and survives the 4 s polls and the re-renders of selecting a folder and of typing a path
    (was: the re-render after Save settings and leaving and reopening the tab). A new opening of the chooser starts on the
    lab's folder again (the tab is gone; the same claim as check_ui007ab);
  * "another branch opens while the first stays closed": the fixture's second branch (labs/VLAN) is a lab folder now and
    has no children, so a second branch is made by closing and reopening 'labs' while 'labs/BGP' stays closed;
  * browsing is not saving: selecting another folder (labs/BGP/start) moves the selection only; the tag stays on the
    lab's folder and the stored place does not change (was: the current marker and "This lab saves to ..." in the foot);
  * keyboard: the twisty button is gone; Left and Right on a tree item close and open it, the focus stays on the item and
    the arrows do not select it;
  * a long name stays on one line inside the tree and keeps its full name reachable. The old tooltip (`title`) is not
    on the new row: the full name stays in the item's `data-folder-label` and in the path field (reported).

Runs against the fixture manager (the lab saves to labs/BGP/work). It plans one empty folder; use a scratch FIXTURE_DATA
directory.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui008b.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
HOME = 'labs/BGP/work'
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def shot(page, name):
    if OUT:
        page.locator('#save-drawer').screenshot(path=os.path.join(OUT, name + '.png'))


OPEN = '() => [...document.querySelectorAll("#folder-tree [role=treeitem][aria-expanded=true]")].map(e => e.dataset.folder)'
SHOWN = '() => [...document.querySelectorAll("#folder-tree [role=treeitem]")].filter(e => e.offsetParent).map(e => e.dataset.folder)'
DEST = '() => document.getElementById("folder-result").innerText.replace(/\\s+/g, " ")'
SELECTED = '() => document.querySelector("#folder-tree [role=treeitem][aria-selected=true]")?.dataset.folder'
CURRENT = '() => [...document.querySelectorAll("#folder-tree [role=treeitem]")].filter(e => /This lab saves here/.test(e.querySelector(".folder-row").innerText)).map(e => e.dataset.folder)'
PLACE = '''async (lab) => { const s = await (await fetch('/api/state')).json(); return (s.labs.find(l => l.name === lab).git_binding.repository.prefix || '').replace(/^\\/+|\\/+$/g, ''); }'''
FOCUSED = '() => document.activeElement?.dataset?.folder'


def open_chooser(page):
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card, #lab-content:not([hidden])')
    if page.is_visible('article.lab-card'):
        page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')
    page.wait_for_function('() => document.getElementById("save-chip-text").textContent.length > 0')
    reopen(page)


def reopen(page):
    if page.is_hidden('#save-panel'):
        page.click('#save-chip')
    page.click('#save-change')
    page.wait_for_selector('#folder-tree [role=treeitem][aria-selected=true]')


def twist(page, path):
    page.click(f'#folder-tree [data-folder-twist="{path}"]')


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1366, 'height': 900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    open_chooser(page)
    dest = page.evaluate(DEST)
    check('first display leads to the folder the lab saves to', page.evaluate(OPEN) == ['', 'labs', 'labs/BGP'] and HOME in page.evaluate(SHOWN) and page.evaluate(SELECTED) == HOME, (page.evaluate(OPEN), page.evaluate(SELECTED)))
    check('the lab\'s folder carries the tag "This lab saves here", alone', page.evaluate(CURRENT) == [HOME], page.evaluate(CURRENT))
    check('the lab\'s own save folders (latest, baseline, checkpoints) are not offered', not any(p.rsplit('/', 1)[-1] in ('latest', 'baseline', 'checkpoints') for p in page.evaluate(SHOWN)), page.evaluate(SHOWN))
    shot(page, 'ui008b-first-display')

    # An ancestor of the active save location closes, and the twisty does not select
    twist(page, 'labs/BGP')
    shown = page.evaluate(SHOWN)
    check('an ancestor of the save location can be closed', HOME not in shown and 'labs/BGP' in shown, shown)
    check('closing did not change the selected folder or the destination line', page.evaluate(DEST) == dest and page.input_value('#folder-path') == HOME, (page.evaluate(DEST), page.input_value('#folder-path')))
    check('the destination line still names the lab\'s folder inside the closed branch', HOME in page.evaluate(DEST))
    shot(page, 'ui008b-ancestor-collapsed')
    # Another branch closes and opens while the first stays closed, and both states hold across polls and re-renders
    twist(page, 'labs')
    twist(page, 'labs')
    expected = page.evaluate(OPEN)
    check('another branch opens while the first stays closed', 'labs' in expected and 'labs/BGP' not in expected, expected)
    page.wait_for_timeout(9000)   # two background polls, on purpose
    check('both survive two background polls', page.evaluate(OPEN) == expected, page.evaluate(OPEN))
    page.click('#folder-tree [data-folder="labs/VLAN"] > .folder-row')   # selecting redraws the tree
    page.wait_for_function('() => document.querySelector("#folder-tree [role=treeitem][aria-selected=true]")?.dataset.folder === "labs/VLAN"')
    check('and the re-render of selecting a folder', page.evaluate(OPEN) == expected, page.evaluate(OPEN))
    page.fill('#folder-path', 'labs/VLAN')   # typing redraws it too
    page.wait_for_function('() => !/Checking/.test(document.getElementById("folder-answer").textContent)')
    check('and the re-render of typing a path', page.evaluate(OPEN) == expected, page.evaluate(OPEN))
    # Leaving and reopening: the chooser is a new opening that starts on the lab's folder again
    page.click('#save-drawer-close')
    page.wait_for_function('() => !document.getElementById("save-drawer").open')
    reopen(page)
    check('reopening the chooser starts on the lab\'s folder again (the open branches live as long as the chooser)', page.evaluate(OPEN) == ['', 'labs', 'labs/BGP'] and HOME in page.evaluate(SHOWN))
    # Reopen: nothing was lost
    twist(page, 'labs/BGP')
    twist(page, 'labs/BGP')
    check('the ancestor reopens with its branch as it was', HOME in page.evaluate(SHOWN) and not any(p.endswith('/latest') for p in page.evaluate(SHOWN)), page.evaluate(SHOWN))

    # Browsing is not saving
    page.click('#folder-tree [data-folder="labs/BGP/start"] > .folder-row')
    page.wait_for_function('() => document.querySelector("#folder-tree [role=treeitem][aria-selected=true]")?.dataset.folder === "labs/BGP/start"')
    check('browsing another folder selects it without moving the "This lab saves here" tag', page.evaluate(SELECTED) == 'labs/BGP/start' and page.evaluate(CURRENT) == [HOME])
    check('the stored place did not change', page.evaluate(PLACE, LAB) == HOME, page.evaluate(PLACE, LAB))
    check('the destination line follows the choice, not the stored place', 'labs/BGP/start' in page.evaluate(DEST) and page.evaluate(DEST) != dest)
    shot(page, 'ui008b-browsing')
    opened = page.evaluate(OPEN)
    page.click('#folder-tree [data-folder="labs/BGP/start"] > .folder-row')
    check('clicking a selected folder again closes nothing', page.evaluate(OPEN) == opened and page.evaluate(SELECTED) == 'labs/BGP/start')

    # Keyboard: the arrows close and open a tree item and the focus stays on it
    page.focus('#folder-tree [data-folder="labs/BGP"]')
    page.keyboard.press('ArrowLeft')
    page.wait_for_function('() => document.querySelector("#folder-tree [data-folder=\\"labs/BGP\\"]").getAttribute("aria-expanded") === "false"')
    check('Left arrow closes a branch and keeps the focus on it', 'labs/BGP' not in page.evaluate(OPEN) and page.evaluate(FOCUSED) == 'labs/BGP', (page.evaluate(OPEN), page.evaluate(FOCUSED)))
    page.keyboard.press('ArrowRight')
    page.wait_for_function('() => document.querySelector("#folder-tree [data-folder=\\"labs/BGP\\"]").getAttribute("aria-expanded") === "true"')
    check('Right arrow opens it and the focus stays on it', 'labs/BGP' in page.evaluate(OPEN) and page.evaluate(FOCUSED) == 'labs/BGP')
    check('the arrows did not select it', page.evaluate(SELECTED) == 'labs/BGP/start')

    # A long name does not wrap or push its tag out
    page.click(f'#folder-tree [data-folder="{HOME}"] > .folder-row')
    page.click('.folder-chooser [data-folder-action="new"]')
    page.fill('#folder-new', 'a-very-long-folder-name-for-week-04-final-state')
    page.click('.folder-chooser [data-folder-action="new-add"]')
    long = HOME + '/a-very-long-folder-name-for-week-04-final-state'
    page.wait_for_selector(f'#folder-tree [data-folder="{long}"]', timeout=20000)
    box = page.evaluate('''(p) => { const item = document.querySelector(`#folder-tree [data-folder="${p}"]`), tree = document.getElementById('folder-tree').getBoundingClientRect(), row = item.querySelector('.folder-row'), r = row.getBoundingClientRect(), own = document.querySelector('#folder-tree [data-folder="labs/BGP/work"] > .folder-row').getBoundingClientRect(), tag = row.querySelector('.git-tag').getBoundingClientRect();
      return {rowHeight: r.height, ownHeight: own.height, inside: r.right <= tree.right + 1 && tag.right <= tree.right + 1, label: item.dataset.folderLabel, path: document.getElementById('folder-path').value}; }''', long)
    check('a long name stays on one line inside the tree with its tag in view', box['rowHeight'] <= 36 and box['ownHeight'] <= 36 and box['inside'], box)
    check('and its full name stays reachable (the item label and the path field)', box['label'].startswith('a-very-long') and box['path'].endswith('final-state'), box)
    check('the folder the page created is revealed and selected', page.evaluate(SELECTED) == long)
    shot(page, 'ui008b-long-name')
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
