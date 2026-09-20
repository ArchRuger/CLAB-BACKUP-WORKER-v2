#!/usr/bin/env python3
"""UI-008 (part 2) browser check: the folder tree opens and closes by the student's own clicks.

Runs against the fixture manager (the lab saves to labs/BGP/work). It plans one empty folder; use a
scratch FIXTURE_DATA directory.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui008b.py
"""
import os
import sys
import time

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
        page.locator('#git-change-folder').screenshot(path=os.path.join(OUT, name + '.png'))


OPEN = '() => [...document.querySelectorAll("#git-places-panel .git-outline details[open] > summary")].map(s => s.dataset.gitPlace)'
SHOWN = '() => [...document.querySelectorAll("#git-places-panel .git-outline summary")].filter(s => s.offsetParent).map(s => s.dataset.gitPlace)'
DEST = '() => document.querySelector("#git-save-location .git-destination-line").innerText.replace(/\\s+/g, " ")'
SELECTED = '() => document.querySelector("#git-places-panel .git-outline summary.selected")?.dataset.gitPlace'
CURRENT = '() => [...document.querySelectorAll("#git-places-panel .git-outline summary.current")].map(s => s.dataset.gitPlace)'


def twist(page, path):
    page.click(f'#git-places-panel [data-git-twist="{path}"]')


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1366, 'height': 900})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.click('#tab-progress')
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=20000)
    dest = page.evaluate(DEST)
    check('first display leads to the folder the lab saves to', page.evaluate(OPEN) == ['', 'labs', 'labs/BGP', HOME], page.evaluate(OPEN))
    check('the save destination is marked current and carries This lab', page.evaluate(CURRENT) == [HOME] and 'This lab' in page.inner_text(f'#git-places-panel summary[data-git-place="{HOME}"]'))
    shot(page, 'ui008b-first-display')

    # An ancestor of the active save location collapses, and the twisty does not select
    twist(page, 'labs/BGP')
    shown = page.evaluate(SHOWN)
    check('an ancestor of the save location can be collapsed', HOME not in shown and 'labs/BGP' in shown, shown)
    check('collapsing did not change the browsed folder or the save destination', page.evaluate(SELECTED) is None and page.evaluate(DEST) == dest and 'work' in page.inner_text('#git-places-panel .git-crumbs'))
    check('the closed branch says the lab\'s folder is inside', 'This lab is inside' in page.inner_text('#git-places-panel summary[data-git-place="labs/BGP"]'))
    shot(page, 'ui008b-ancestor-collapsed')
    # Another branch opens and both states hold across polls, a forced refresh and a tab change
    twist(page, 'labs/VLAN')
    expected = page.evaluate(OPEN)
    check('another branch opens while the first stays closed', 'labs/VLAN' in expected and 'labs/BGP' not in expected, expected)
    time.sleep(9)
    check('both survive two background polls', page.evaluate(OPEN) == expected, page.evaluate(OPEN))
    page.click('#git-binding-form button[type=submit]')
    page.wait_for_function('() => /Save settings updated/.test(document.getElementById("toast").textContent)', timeout=15000)
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=20000)
    check('and the re-render after Save settings', page.evaluate(OPEN) == expected, page.evaluate(OPEN))
    page.click('#tab-devices')
    page.click('#tab-progress')
    check('and leaving and reopening the tab', page.evaluate(OPEN) == expected, page.evaluate(OPEN))
    # Reopen: nothing was lost
    twist(page, 'labs/BGP')
    check('the ancestor reopens with its branch as it was', HOME in page.evaluate(SHOWN) and HOME + '/latest' in page.evaluate(SHOWN), page.evaluate(SHOWN))

    # Browsing is not saving
    page.click('#git-places-panel .git-outline summary[data-git-place="labs/BGP/start"]')
    check('browsing another folder selects it without moving the current marker', page.evaluate(SELECTED) == 'labs/BGP/start' and page.evaluate(CURRENT) == [HOME])
    foot = page.inner_text('#git-places-panel .git-places-foot')
    check('the panel says where the lab saves while another folder is looked at', f'This lab saves to {HOME}' in foot, foot)
    check('the save destination did not change', page.evaluate(DEST) == dest, page.evaluate(DEST))
    shot(page, 'ui008b-browsing')
    page.click('#git-places-panel .git-outline summary[data-git-place="labs/BGP/start"]')
    check('clicking a selected folder again closes nothing', 'labs/BGP/start' in page.evaluate(OPEN))

    # Keyboard: focus stays on the control across the redraw; arrows open and close
    page.focus('#git-places-panel [data-git-twist="labs/VLAN"]')
    page.keyboard.press('Enter')
    check('the twisty works from the keyboard and keeps the focus', 'labs/VLAN' not in page.evaluate(OPEN) and page.evaluate('() => document.activeElement?.dataset?.gitTwist') == 'labs/VLAN')
    page.focus('#git-places-panel .git-outline summary[data-git-place="labs/VLAN"]')
    page.keyboard.press('ArrowRight')
    check('Right arrow opens a folder and the focus stays on it', 'labs/VLAN' in page.evaluate(OPEN) and page.evaluate('() => document.activeElement?.dataset?.gitPlace') == 'labs/VLAN')
    page.keyboard.press('ArrowLeft')
    check('Left arrow closes it', 'labs/VLAN' not in page.evaluate(OPEN))
    check('the arrows did not select it', page.evaluate(SELECTED) == 'labs/BGP/start')

    # A long name does not wrap or push its tag out
    page.click(f'#git-places-panel .git-outline summary[data-git-place="{HOME}"]')
    page.click('[data-git-places-action="new"]')
    page.fill('#git-new-folder-name', 'a-very-long-folder-name-for-week-04-final-state')
    if page.is_checked('#git-new-folder-use'):
        page.click('#git-new-folder-use')
    page.click('#git-new-folder-confirm')
    long = HOME + '/a-very-long-folder-name-for-week-04-final-state'
    page.wait_for_selector(f'#git-places-panel .git-outline summary[data-git-place="{long}"]', timeout=20000)
    box = page.evaluate('''(p) => { const s = document.querySelector(`#git-places-panel .git-outline summary[data-git-place="${p}"]`), o = document.querySelector('#git-places-panel .git-outline').getBoundingClientRect(), r = s.getBoundingClientRect(), own = document.querySelector('#git-places-panel .git-outline summary.current').getBoundingClientRect();
      return {rowHeight: r.height, ownHeight: own.height, inside: r.right <= o.right + 1, title: s.querySelector('.git-outline-name').title}; }''', long)
    check('a long name stays on one line inside the outline and keeps its full name as a tooltip', box['rowHeight'] <= 36 and box['ownHeight'] <= 36 and box['title'].startswith('a-very-long'), box)
    check('the folder the page created is revealed and selected', page.evaluate(SELECTED) == long)
    shot(page, 'ui008b-long-name')
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
