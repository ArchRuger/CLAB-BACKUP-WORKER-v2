#!/usr/bin/env python3
"""Items 3 and 4: the lab builder writes the image exactly as typed (`<image>:<version>`, nothing added, an empty
version writes the image with no tag) and never fills the Version field in by itself (clearing it keeps it empty,
pasting another image keeps whatever is typed). Driven in a real browser against a running manager; the draft and the
edited template live in the browser context only and are discarded with it. Zero console or page errors.

    CLAB_BASE=http://192.168.132.132:8081 CLAB_SHOTS=/tmp/shots clab-backup-ui/.venv/bin/python docs/ui-ux-changes-2/tools/check_image_fields.py
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://192.168.132.132:8081')
OUT = os.environ.get('CLAB_SHOTS', '')
LAB = 'uiux2-img-' + time.strftime('%H%M%S')
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:300]))
    page.on('console', lambda m: errors.append(m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    shot = lambda name: page.screenshot(path=os.path.join(OUT, name + '.png')) if OUT else None
    value = lambda sel: page.input_value(sel)
    page.goto(BASE + '/static/lab-builder.html'); page.wait_for_selector('#builder-welcome-new', timeout=20000); page.click('#builder-welcome-new')
    page.wait_for_selector('#builder-new-name', timeout=20000); page.fill('#builder-new-name', LAB); page.click('#builder-new-create')
    page.wait_for_selector('[data-testid="navbar-layout"]', timeout=20000); page.wait_for_timeout(1200)
    yaml = lambda: (json.loads(page.evaluate(f"localStorage.getItem('clab-builder:draft:new:{LAB}')") or '{}').get('yaml', ''))
    image_lines = lambda: [l.strip() for l in yaml().splitlines() if l.strip().startswith('image:')]

    def template_card(name):
        return page.get_by_text(name, exact=True).first.locator('xpath=ancestor::*[@draggable="true"][1]')

    def open_template(name):
        template_card(name).locator('button[aria-label="Edit"]').click()
        page.wait_for_selector('#node-version', timeout=15000); page.wait_for_timeout(400)

    def clear(sel):
        page.click(sel); page.keyboard.press('Control+A'); page.keyboard.press('Backspace'); page.wait_for_timeout(500)

    def type_into(sel, text):
        clear(sel); page.keyboard.type(text); page.wait_for_timeout(500)

    def paste_into(sel, text):
        # one input event with the whole value, like a paste
        page.fill(sel, text); page.wait_for_timeout(500)

    def save_dialog():
        page.get_by_role('button', name='Save', exact=True).click(); page.wait_for_timeout(700)

    def drag(name, x, y):
        card = template_card(name); box = card.bounding_box()
        page.mouse.move(box['x'] + 10, box['y'] + 8); page.mouse.down(); page.mouse.move(x, y, steps=12); page.mouse.up(); page.wait_for_timeout(900)

    # Item 4: clearing the Version field keeps it empty; pasting another image keeps the typed version.
    open_template('Cisco XRv9k')
    check('the template dialog shows an Image and a Version field', value('#node-image') != '' and page.locator('#node-version').count() == 1, value('#node-image'))
    shot('01-template-dialog-opened')
    clear('#node-version')
    check('item 4: backspacing the Version field leaves it empty', value('#node-version') == '', 'Version reads %r' % value('#node-version'))
    shot('02-version-cleared')
    type_into('#node-version', '24.3.1')
    check('item 4: a typed version is kept as typed', value('#node-version') == '24.3.1', value('#node-version'))
    paste_into('#node-image', 'registry.example/vendor/router')
    check('item 4: pasting an unknown image keeps the typed version (no latest)', value('#node-version') == '24.3.1', 'Version reads %r' % value('#node-version'))
    shot('03-image-pasted')
    clear('#node-version'); paste_into('#node-image', 'registry.example/vendor/other')
    check('item 4: pasting an image into an empty version leaves it empty', value('#node-version') == '', 'Version reads %r' % value('#node-version'))
    # Item 3: the YAML receives exactly <image>:<version>.
    paste_into('#node-image', 'n24l/cisco_xrv9k'); type_into('#node-version', '24.3.1')
    save_dialog()
    drag('Cisco XRv9k', 420, 260)
    check('item 3: the placed node writes exactly image:version', image_lines() == ['image: n24l/cisco_xrv9k:24.3.1'], image_lines())
    shot('04-node-placed')
    # An empty version writes the image with no tag.
    open_template('Cisco XRv9k'); paste_into('#node-image', 'n24l/vjunos-switch'); clear('#node-version')
    check('the dialog keeps the empty version before saving', value('#node-version') == '', value('#node-version'))
    save_dialog()
    drag('Cisco XRv9k', 700, 260)
    check('item 4: an empty version writes the image with no tag', image_lines() == ['image: n24l/cisco_xrv9k:24.3.1', 'image: n24l/vjunos-switch'], image_lines())
    # The node editor's own Image and Version fields follow the same rule (Apply is the node editor's own step).
    node = page.locator('.react-flow__node').filter(has_text='xr1').first
    box = node.bounding_box(); page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, button='right'); page.wait_for_timeout(400)
    page.get_by_role('menuitem', name='Edit Node').click(); page.wait_for_selector('#node-version', timeout=15000); page.wait_for_timeout(500)
    before = value('#node-image') + ':' + value('#node-version')
    clear('#node-version')
    check('node editor: clearing the version keeps it empty', value('#node-version') == '', 'was %s, now Version reads %r' % (before, value('#node-version')))
    page.click('[data-testid="panel-apply-btn"]'); page.wait_for_timeout(900)
    check('node editor: Apply writes the image with no tag', 'image: n24l/cisco_xrv9k' in image_lines() and 'image: n24l/cisco_xrv9k:latest' not in image_lines(), image_lines())
    shot('05-node-editor-applied')
    check('no console or page errors', not errors, errors)
    browser.close()
print('FAILED: ' + ', '.join(failed) if failed else 'ALL CHECKS PASSED')
sys.exit(1 if failed else 0)
