#!/usr/bin/env python3
"""UI-007 A + B browser check: "Git repo details", and Change folder open on entry with a fold that lasts.

Runs against the fixture manager; read-only apart from saving the unchanged save settings once.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui007ab.py
"""
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
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
    page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.wait_for_selector('#git-save-menu:not([hidden])')
    page.click('#git-save-menu > summary')
    page.click('#git-save-menu [data-git-action="settings"]')
    page.wait_for_selector('#git-save-location #git-change-folder')
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=15000)
    is_open = '() => document.getElementById("git-change-folder").open'
    check('Change folder is open when Save location is entered, with the folder browser loaded', page.evaluate(is_open) and page.is_visible('#git-places-panel .git-places-head'))
    summaries = page.evaluate('() => [...document.querySelectorAll("#git-save-location summary")].map(s => s.textContent.trim())')
    check('the repository disclosure reads "Git repo details"', 'Git repo details' in summaries and 'Technical details' not in summaries, summaries)
    page.click('#git-save-location .git-location-tech > summary')
    details = page.inner_text('#git-save-location .git-location-tech')
    check('Git repo details shows the push destination, branch, account and path', all(w in details for w in ['Verified push destination', 'Branch', 'VM account']), details)
    check('the Advanced tab keeps its own "Technical details" panel', page.evaluate('() => document.getElementById("technical-title").textContent') == 'Technical details')
    if OUT:
        page.locator('#git-save-location').screenshot(path=os.path.join(OUT, 'ui007ab-save-location-open.png'))
    # A deliberate fold survives polls, a forced re-render and a tab change
    page.click('#git-change-folder > summary')
    check('the student can fold it', not page.evaluate(is_open))
    time.sleep(9)  # two background polls
    check('the fold survives background polling', not page.evaluate(is_open))
    page.click('#tab-topology')
    page.click('#tab-progress')
    check('the fold survives leaving and reopening the tab', not page.evaluate(is_open))
    page.click('#git-binding-form button[type=submit]')
    page.wait_for_function('() => /Save settings updated/.test(document.getElementById("toast").textContent)', timeout=15000)
    page.wait_for_selector('#git-change-folder')
    check('the fold survives the re-render after saving the settings', not page.evaluate(is_open))
    if OUT:
        page.locator('#git-save-location').screenshot(path=os.path.join(OUT, 'ui007ab-save-location-folded.png'))
    # Asking for the browser by name opens it again
    page.click('[data-git-repo-action="browse"]')
    page.wait_for_function(is_open, timeout=15000)
    check('Browse the repository… opens it again', True)
    # A new visit starts unfolded
    page2 = browser.new_page(viewport={'width': 1366, 'height': 768})
    page2.goto(BASE + '/')
    page2.wait_for_selector('article.lab-card')
    page2.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page2.click('#tab-progress')
    page2.wait_for_selector('#git-change-folder')
    check('a fresh visit starts with Change folder open', page2.evaluate(is_open))
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
