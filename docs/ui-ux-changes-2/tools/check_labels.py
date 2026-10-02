#!/usr/bin/env python3
"""Items 5, 6 and 7: labels. In the lab builder a device's label position, chosen in the node editor, applies the
moment it is chosen (no Apply step), is one Undo step, and offers the four corners; in Edit map (the editor's view
mode over an existing lab) the device's look is edited through the editor's own node editor (right-click › Device
look) with just the icon and label sections, the topology text never changes, Undo takes the look back, Save map
keeps it, and the manager's Topology tab, its preview renderer and the draw.io export draw the corner. Nothing is
deployed; the map of CLAB_LAB is changed and then restored. Zero console or page errors.

    CLAB_BASE=http://192.168.132.132:8081 CLAB_LAB=netlab-test CLAB_SHOTS=/tmp/shots \\
      clab-backup-ui/.venv/bin/python docs/ui-ux-changes-2/tools/check_labels.py
"""
import json
import os
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://192.168.132.132:8081')
LAB = os.environ.get('CLAB_LAB', 'netlab-test')
OUT = os.environ.get('CLAB_SHOTS', '')
NAME = 'uiux2-lbl-' + time.strftime('%H%M%S')
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def choose(page, select_id, option):
    page.click('#' + select_id); page.wait_for_timeout(300)
    page.get_by_role('option', name=option, exact=True).click(); page.wait_for_timeout(900)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:300]))
    page.on('console', lambda m: errors.append(m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    shot = lambda name: page.screenshot(path=os.path.join(OUT, name + '.png')) if OUT else None
    api = lambda path: json.loads(page.request.get(BASE + '/api' + path).text())
    node_at = lambda text: page.locator('.react-flow__node').filter(has_text=text).first
    def right_click(loc):
        box = loc.bounding_box(); page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, button='right'); page.wait_for_timeout(500)

    # --- The lab builder (edit mode): immediate apply, one undo step, the corners.
    page.goto(BASE + '/static/lab-builder.html'); page.wait_for_selector('#builder-welcome-new', timeout=20000); page.click('#builder-welcome-new')
    page.wait_for_selector('#builder-new-name', timeout=20000); page.fill('#builder-new-name', NAME); page.click('#builder-new-create')
    page.wait_for_selector('[data-testid="navbar-layout"]', timeout=20000); page.wait_for_timeout(1200)
    card = page.get_by_text('Linux host', exact=True).first.locator('xpath=ancestor::*[@draggable="true"][1]'); box = card.bounding_box()
    page.mouse.move(box['x'] + 10, box['y'] + 8); page.mouse.down(); page.mouse.move(420, 300, steps=12); page.mouse.up(); page.wait_for_timeout(900)
    draft = lambda: json.loads(page.evaluate(f"localStorage.getItem('clab-builder:draft:new:{NAME}')") or '{}')
    position = lambda: {n.get('id'): n.get('labelPosition') for n in json.loads(draft().get('annotations') or '{"nodeAnnotations":[]}').get('nodeAnnotations', [])}
    right_click(node_at('host1')); page.get_by_role('menuitem', name='Edit Node').click(); page.wait_for_selector('#node-label-position', timeout=15000); page.wait_for_timeout(500)
    page.click('#node-label-position'); page.wait_for_timeout(300)
    options = page.evaluate("[...document.querySelectorAll('[role=listbox] [role=option]')].map(o => o.getAttribute('data-value'))")
    check('item 6: the Label Position list offers the four corners', options == ['bottom', 'top', 'left', 'right', 'top-left', 'top-right', 'bottom-left', 'bottom-right'], options)
    page.get_by_role('option', name='Top right', exact=True).click(); page.wait_for_timeout(1200)
    check('item 5: the chosen position is in the draft at once, with no Apply step', position().get('host1') == 'top-right' and page.locator('[data-testid="panel-apply-btn"]').count() == 0, (position(), page.locator('[data-testid="panel-apply-btn"]').count()))
    style = page.locator('.react-flow__node .topology-node-label').first.get_attribute('style') or ''
    check('item 6: the canvas draws the label at the corner (above and to the right of the icon)', 'bottom:' in style and 'left:' in style and 'translate' not in style, style[-120:])
    shot('01-builder-top-right')
    choose(page, 'node-direction', 'Rotate text 90deg')
    check('item 5: the text direction applies at once too', json.loads(draft()['annotations'])['nodeAnnotations'][0].get('direction') == 'down')
    page.keyboard.press('Escape'); page.mouse.click(700, 650); page.wait_for_timeout(300)
    page.keyboard.press('Control+z'); page.wait_for_timeout(900)
    check('item 5: each change is one undo step (the direction goes first)', position().get('host1') == 'top-right' and not json.loads(draft()['annotations'])['nodeAnnotations'][0].get('direction'))
    page.keyboard.press('Control+z'); page.wait_for_timeout(900)
    check('item 5: the second undo takes the position back', not position().get('host1'), position())

    # --- Edit map (view mode over an existing lab): the editor's node editor as the device look.
    lab = next((l for l in api('/state')['labs'] if l['name'] == LAB), None)
    check('the lab is in My labs with a map editor', lab is not None and lab.get('map_editor'), LAB)
    lid = lab['id']
    saved = page.request.get(BASE + f'/api/labs/{lid}/map-document').json()
    page.goto(BASE + '/static/map-editor.html#lab=' + lid); page.wait_for_selector('.react-flow__node', timeout=30000); page.wait_for_timeout(1500)
    check('item 7: the Device look button and its dialog are gone from the bar', page.locator('#map-look').count() == 0 and page.locator('#map-look-dialog').count() == 0)
    device = page.locator('.react-flow__node-topology-node').first
    device_id = device.get_attribute('data-id')
    right_click(device)
    items = page.evaluate("[...document.querySelectorAll('[data-testid^=context-menu-item-]')].filter(e => e.offsetParent).map(e => e.getAttribute('data-testid') + '|' + e.textContent.trim())")
    check('item 7: the device menu offers Device look and no topology edit', any(i == 'context-menu-item-edit-node|Device look' for i in items) and not any('create-link' in i or 'delete-node' in i for i in items), items)
    shot('02-map-device-menu')
    page.get_by_role('menuitem', name='Device look').click(); page.wait_for_selector('#node-label-position', timeout=15000); page.wait_for_timeout(600)
    panel = page.inner_text('[role="tabpanel"], .MuiDrawer-root') if page.locator('[role="tabpanel"]').count() else page.inner_text('body')
    check('item 7: the node editor shows the icon and label sections only', 'Node Parameters' not in panel and page.locator('#node-kind').count() == 0 and page.locator('#node-image').count() == 0 and page.locator('#node-icon').count() == 1)
    tabs = page.evaluate("[...document.querySelectorAll('[data-testid^=panel-tab-]')].filter(e => e.offsetParent).map(e => e.getAttribute('data-testid'))")
    check('item 7: the other node editor tabs are hidden', not any(t in tabs for t in ('panel-tab-config', 'panel-tab-runtime', 'panel-tab-network', 'panel-tab-advanced')), tabs)
    shot('03-map-device-look-panel')
    current = lambda: json.loads(page.evaluate('() => mapCurrent'))
    entry = lambda: next((a for a in current().get('nodeAnnotations', []) if a.get('id') == device_id), {})
    yaml_before = page.evaluate('() => mapDoc.yaml')
    choose(page, 'node-label-position', 'Bottom left')
    check('item 7: the corner is in the map document at once, no Apply', entry().get('labelPosition') == 'bottom-left' and page.locator('[data-testid="panel-apply-btn"]').count() == 0, entry())
    check('item 7: the topology text is untouched', page.evaluate('() => mapDoc.yaml') == yaml_before and page.evaluate('() => document.getElementById("map-status").textContent') == 'Unsaved changes')
    shot('04-map-bottom-left')
    page.click('#map-undo'); page.wait_for_timeout(900)
    check('item 7: Undo takes the look back', entry().get('labelPosition') != 'bottom-left', entry())
    page.click('#map-redo'); page.wait_for_timeout(900)
    check('item 7: Redo brings it back', entry().get('labelPosition') == 'bottom-left')
    page.click('#map-save'); page.wait_for_function('() => document.getElementById("map-status").textContent === "Saved in the manager"', timeout=15000)
    drawing = api(f'/labs/{lid}/topology')
    drawn = next((n for n in drawing.get('nodes', []) if n.get('id') == device_id), {})
    check('item 6: the saved map reaches the manager\'s drawing with the corner', drawn.get('labelPosition') == 'bottom-left', drawn)
    drawio = page.request.get(BASE + f'/api/labs/{lid}/drawio').text()
    check('item 6: the draw.io export places the label at the corner', 'labelPosition=left;verticalLabelPosition=bottom;align=right;verticalAlign=top;' in drawio)
    page.goto(BASE + '/#lab=' + lid + '&view=topology'); page.wait_for_selector('#topology-map .map-device', timeout=30000); page.wait_for_timeout(1500)
    text = page.evaluate(f"() => {{ const g = document.querySelector('#topology-map .map-device[data-map-id=\"{device_id}\"] .device-label text'); return g ? [g.getAttribute('x'), g.getAttribute('y'), g.getAttribute('text-anchor')] : null; }}")
    check('item 6: the Topology tab draws the corner label (left of the icon, below it, anchored at its end)', text == ['-14', '35', 'end'], text)
    shot('05-topology-tab-corner')
    # restore the lab's map as it was
    restored = page.request.put(BASE + f'/api/labs/{lid}/map-document', data=json.dumps({'annotations': saved['annotations'], 'revision': api(f'/labs/{lid}/map-document')['revision']}), headers={'Content-Type': 'application/json'})
    check('the lab\'s map is restored', restored.ok, restored.status)
    check('no console or page errors', not errors, errors)
    browser.close()
print('FAILED: ' + ', '.join(failed) if failed else 'ALL CHECKS PASSED')
sys.exit(1 if failed else 0)
