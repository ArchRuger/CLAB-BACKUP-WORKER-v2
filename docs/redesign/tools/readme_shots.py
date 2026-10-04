#!/usr/bin/env python3
"""The two pictures of the README's "A quick look" that show Save and Load: All versions and the Load confirmation.

Fixture evidence only. They are taken on the Git save and load redesign's fixture (the full one, not --classic: the lab
`restore-square` has four devices on three network systems, a latest save, checkpoints, a starting point and the course's
lab states; docs/git-redesign/tools/fixture/SCENARIOS.md), at 1440x900, the size of every picture in docs/TOUR.md.
Nothing is changed: the script only opens All versions and chooses a state in the Load panel; it never presses Load.

    FIXTURE_DATA=$(mktemp -d) clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8128
    CLAB_BASE=http://127.0.0.1:8128 CLAB_SHOTS=docs/images ~/pw-venv/bin/python docs/redesign/tools/readme_shots.py

Writes all-versions.png and load-confirmation.png into CLAB_SHOTS and exits 1 on any console error, page error or missing
element. No picture shows a device configuration, a password or a token: the lists name devices and count lines.
"""
import os
import re
import sys

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8128')
OUT = os.environ.get('CLAB_SHOTS', '.')
LAB = os.environ.get('CLAB_LAB', 'restore-square')
STATE = os.environ.get('CLAB_STATE', 'Final · BGP')   # two states are named Final in the fixture: each adds its parent folder


def main():
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=1).new_page()
        page.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))
        page.on('console', lambda m: errors.append('console: ' + m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        page.request.post(BASE + '/fixture/switch', data={'capture_seconds': 1, 'restore_capture_seconds': 1})
        page.goto(BASE + '/')
        page.wait_for_selector('article.lab-card')
        page.click(f'article.lab-card:has(h3:text-is("{LAB}")) button[data-lab]')
        page.wait_for_selector('#lab-content:not([hidden])')
        expect(page.locator('#save-chip-text')).to_have_text(re.compile('^Saved '), timeout=20000)
        # All versions, with a lab state opened in place so its actions show
        page.click('#save-chip')
        page.click('#save-all')
        page.wait_for_selector('#save-drawer-content .save-list', timeout=20000)
        page.wait_for_selector('#save-drawer-content .save-foot button', timeout=20000)
        row = page.locator('#save-drawer-content .save-list > li').filter(has=page.locator('button.save-item > span:first-child', has_text=re.compile('^Broken$'))).first
        row.locator('button.save-item').click()
        expect(row).to_have_class(re.compile('open'))
        page.screenshot(path=os.path.join(OUT, 'all-versions.png'))
        page.click('#save-drawer-close')
        expect(page.locator('#save-drawer')).to_be_hidden()
        # The Load confirmation: every device with what would change, nothing pressed
        page.click('#load-button')
        page.wait_for_selector('#load-panel-body .save-list', timeout=20000)
        pick = page.locator('#load-panel-body .save-list > li').filter(has=page.locator('.save-item > span:first-child', has_text=re.compile('^' + re.escape(STATE)))).first
        pick.locator('button.save-item').click()
        page.wait_for_selector('#load-run', timeout=30000)
        page.wait_for_selector('#load-panel-body ul.save-devices > li', timeout=20000)
        page.screenshot(path=os.path.join(OUT, 'load-confirmation.png'))
        page.click('#load-cancel')
        browser.close()
    print('console/page errors:', len(errors))
    for error in errors:
        print('  ', error)
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
