#!/usr/bin/env python3
"""UI-007 A + B browser check, rewritten for the header Save and Load (Git save and load redesign): "Git details" and the
folder chooser open on the lab's own folder, with a fold that lasts.

Until 1.30.x this drove the Progress tab's Save location card. The tab is gone; the card's two homes are Save settings
(chip > Save settings: the save location, the devices and the *Git details* disclosure) and the folder chooser
(Save settings > Change folder..., or chip > Saves to: Change...; the tree is `#folder-tree`). The claims move with them:

  * the chooser opens on the way down to the folder the lab saves to, with the tree loaded (was: "Change folder is open
    when Save location is entered");
  * the repository disclosure of Save settings reads "Git details" (not "Technical details") and shows the push
    destination, branch, VM account and path; the Advanced tab keeps its own "Technical details";
  * a branch the student closed stays closed across the 4 s polls and across re-renders (selecting a folder, typing a
    path): the open branches belong to the student, never derived from the selection (CLAUDE.md invariant);
  * the old "fold survives leaving and reopening the tab" has no tab to leave. What is asserted instead: the open
    branches live as long as the chooser (a drawer opening), and a new opening starts again on the lab's own folder,
    like "a fresh visit starts with Change folder open";
  * "Browse the repository..." (All versions) opens the tree again, in browse mode, on the lab's folder.

Runs against the fixture manager; read-only apart from selecting folders (nothing is saved).

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui007ab.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
HOME = os.environ.get('CLAB_FOLDER', 'labs/BGP/work')   # where the fixture lab saves
failed = []

OPEN = '() => [...document.querySelectorAll("#folder-tree [role=treeitem][aria-expanded=true]")].map(e => e.dataset.folder)'
SHOWN = '() => [...document.querySelectorAll("#folder-tree [role=treeitem]")].filter(e => e.offsetParent).map(e => e.dataset.folder)'
SELECTED = '() => [...document.querySelectorAll("#folder-tree [role=treeitem][aria-selected=true]")].map(e => e.dataset.folder)'


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def open_lab(page):
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.wait_for_selector('#lab-content:not([hidden])')
    page.wait_for_function('() => document.getElementById("save-chip-text").textContent.length > 0')


def open_settings(page):
    page.click('#save-chip')
    page.click('#save-settings')
    page.wait_for_selector('#save-drawer[open] .save-settings')
    page.wait_for_selector('#save-drawer-content #save-git-details')


def open_chooser(page):
    page.click('#save-drawer-content [data-save-action="folder"]')
    page.wait_for_selector('#folder-tree')
    page.wait_for_selector(f'#folder-tree [data-folder="{HOME}"]')


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={'width': 1366, 'height': 768})
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    open_lab(page)
    open_settings(page)
    summaries = page.evaluate('() => [...document.querySelectorAll("#save-drawer-content summary")].map(s => s.textContent.trim())')
    check('the repository disclosure of Save settings reads "Git details"', 'Git details' in summaries and 'Technical details' not in summaries, summaries)
    page.click('#save-git-details > summary')
    details = page.inner_text('#save-git-details')
    check('Git details shows the push destination, branch, account and path', all(w in details for w in ['Verified push destination', 'Branch', 'VM account', 'Checkout path']), details)
    check('the Advanced tab keeps its own "Technical details" panel', page.evaluate('() => document.getElementById("technical-title").textContent') == 'Technical details')
    if OUT:
        page.locator('#save-drawer').screenshot(path=os.path.join(OUT, 'ui007ab-save-settings-details.png'))
    open_chooser(page)
    check('Change folder... opens the chooser with the folder tree loaded', page.is_visible('#folder-tree') and page.inner_text('#save-drawer-title').startswith('Where should'))
    opened = page.evaluate(OPEN)
    check('it opens on the way down to the folder the lab saves to, and that folder is selected', opened[:3] == ['', 'labs', 'labs/BGP'] and page.evaluate(SELECTED) == [HOME], (opened, page.evaluate(SELECTED)))
    if OUT:
        page.locator('#save-drawer').screenshot(path=os.path.join(OUT, 'ui007ab-chooser-open.png'))
    # A deliberate fold survives polls and re-renders
    page.click('#folder-tree [data-folder-twist="labs/BGP"]')
    check('the student can fold it', 'labs/BGP' not in page.evaluate(OPEN) and HOME not in page.evaluate(SHOWN), page.evaluate(OPEN))
    page.wait_for_timeout(9000)   # two background polls, on purpose
    check('the fold survives background polling', 'labs/BGP' not in page.evaluate(OPEN) and HOME not in page.evaluate(SHOWN))
    page.click('#folder-tree [data-folder="labs/VLAN"] > .folder-row')   # selecting redraws the tree
    page.wait_for_function('() => document.querySelector("#folder-tree [role=treeitem][aria-selected=true]")?.dataset.folder === "labs/VLAN"')
    check('the fold survives the re-render of selecting another folder', 'labs/BGP' not in page.evaluate(OPEN))
    page.fill('#folder-path', 'labs/VLAN')   # typing redraws it too
    page.wait_for_function('() => !/Checking/.test(document.getElementById("folder-answer").textContent)')
    check('the fold survives the re-render of typing a path', 'labs/BGP' not in page.evaluate(OPEN))
    if OUT:
        page.locator('#save-drawer').screenshot(path=os.path.join(OUT, 'ui007ab-chooser-folded.png'))
    # Leaving: the open branches live as long as the chooser; a new opening starts on the lab's folder again
    page.click('#save-drawer-close')
    page.wait_for_function('() => !document.getElementById("save-drawer").open')
    open_settings(page)
    open_chooser(page)
    check('a new opening of the chooser starts on the lab\'s own folder again', HOME in page.evaluate(SHOWN) and page.evaluate(SELECTED) == [HOME], (page.evaluate(OPEN), page.evaluate(SELECTED)))
    # Browse the repository... (All versions) opens the tree again
    page.click('#folder-tree [data-folder-twist="labs/BGP"]')
    page.click('#save-drawer-close')
    page.wait_for_function('() => !document.getElementById("save-drawer").open')
    page.click('#save-chip')
    page.click('#save-all')
    page.wait_for_selector('#save-drawer-content [data-save-action="browse"]')
    page.click('#save-drawer-content [data-save-action="browse"]')
    page.wait_for_selector('#folder-tree')
    page.wait_for_selector(f'#folder-tree [data-folder="{HOME}"]')
    check('Browse the repository... opens the tree again, in browse mode, on the lab\'s folder', page.evaluate('() => document.querySelector(".folder-chooser").dataset.mode') == 'browse' and HOME in page.evaluate(SHOWN), page.evaluate('() => document.querySelector(".folder-chooser").dataset.mode'))
    page.click('#save-drawer-close')
    # A new visit starts open on the lab's folder
    page2 = browser.new_page(viewport={'width': 1366, 'height': 768})
    page2.on('pageerror', lambda e: errors.append(str(e)))
    page2.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    open_lab(page2)
    open_settings(page2)
    open_chooser(page2)
    check('a fresh visit starts with the chooser open on the lab\'s folder', HOME in page2.evaluate(SHOWN) and page2.evaluate(SELECTED) == [HOME], page2.evaluate(OPEN))
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
