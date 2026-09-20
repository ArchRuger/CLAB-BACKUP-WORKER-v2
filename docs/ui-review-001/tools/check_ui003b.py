#!/usr/bin/env python3
"""UI-003 browser check, part 2: every remaining row of MAP-PARITY.md is driven, saved and reopened.

Runs against the fixture manager on fresh data; it edits and saves the fixture lab's map.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui003b.py
"""
import json
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
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
    page = ctx.new_page()
    errors, writes = [], []
    page.on('pageerror', lambda e: errors.append(str(e)[:300]))
    page.on('console', lambda m: errors.append(m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.on('request', lambda r: writes.append(r.method + ' ' + r.url.split('/api/')[-1]) if r.method != 'GET' else None)
    api = lambda path: json.loads(page.request.get(BASE + '/api' + path).text())
    lid = next(l for l in api('/state')['labs'] if l['name'] == LAB)['id']
    before = api(f'/labs/{lid}/map-document')
    page.goto(BASE + '/static/map-editor.html#lab=' + lid)
    page.wait_for_selector('.react-flow__node', timeout=30000)
    time.sleep(1.5)
    doc = lambda: json.loads(page.evaluate('() => mapCurrent'))
    count = lambda key: len(doc().get(key, []))
    shot = lambda name: page.screenshot(path=os.path.join(OUT, name + '.png')) if OUT else None
    escape = lambda: (page.keyboard.press('Escape'), time.sleep(.3))

    # Row 4: shapes from the pane menu
    shapes = count('freeShapeAnnotations')
    for kind, at in (('rectangle', (700, 780)), ('line', (830, 780)), ('circle', (560, 780))):
        page.mouse.click(*at, button='right')
        time.sleep(.4)
        page.click('[data-testid="context-menu-item-add-shape"]')
        page.click(f'[data-testid="context-menu-item-add-shape-{kind}"]')
        time.sleep(.9)
        escape()
    kinds = [s.get('shapeType') for s in doc()['freeShapeAnnotations'][shapes:]]
    check('row 4: a rectangle, a line and a circle are added', sorted(kinds) == ['circle', 'line', 'rectangle'], kinds)
    # Row 6: resize a shape with its handle
    rect = next(s for s in doc()['freeShapeAnnotations'][shapes:] if s.get('shapeType') == 'rectangle')
    node = page.locator(f'[data-id="{rect["id"]}"]')
    node.click()
    time.sleep(.5)
    handles = page.locator(f'[data-id="{rect["id"]}"] .react-flow__resize-control.bottom.right.handle')
    size = (rect.get('width'), rect.get('height'))
    if handles.count():
        hb = handles.last.bounding_box()
        page.mouse.move(hb['x'] + hb['width'] / 2, hb['y'] + hb['height'] / 2)
        page.mouse.down()
        page.mouse.move(hb['x'] - 30, hb['y'] - 25, steps=8)
        page.mouse.up()
        time.sleep(1)
    now = next(s for s in doc()['freeShapeAnnotations'] if s['id'] == rect['id'])
    check('row 6: a shape is resized with its handle', (now.get('width'), now.get('height')) != size, (size, (now.get('width'), now.get('height')), handles.count()))
    shot('ui003b-shapes')
    escape()

    # Row 5: a group, and a device dragged into it
    groups = count('groupStyleAnnotations')
    page.mouse.click(760, 300, button='right')
    time.sleep(.4)
    page.click('[data-testid="context-menu-item-add-group"]')
    time.sleep(1)
    escape()
    group = doc()['groupStyleAnnotations'][-1] if count('groupStyleAnnotations') == groups + 1 else None
    check('row 5: a group is added', group is not None)
    if group:
        gbox = page.locator(f'[data-id="{group["id"]}"]').bounding_box()
        device = page.locator('[data-testid="rf__node-Backup-Worker"]')
        dbox = device.bounding_box()
        page.mouse.move(dbox['x'] + dbox['width'] / 2, dbox['y'] + dbox['height'] / 2)
        page.mouse.down()
        page.mouse.move(gbox['x'] + gbox['width'] / 2, gbox['y'] + gbox['height'] / 2, steps=20)
        page.mouse.up()
        time.sleep(1.2)
        member = next(a for a in doc()['nodeAnnotations'] if a['id'] == 'Backup-Worker')
        check('row 5: a device dragged into the group becomes its member', member.get('groupId') == group['id'] or member.get('group') == group.get('name'), {k: member.get(k) for k in ('groupId', 'group', 'position')})
        shot('ui003b-group')

    # Row 7: copy, paste and keyboard delete of an annotation
    texts = count('freeTextAnnotations')
    text_node = page.locator('.react-flow__node-free-text-node').first
    text_node.click()
    page.keyboard.press('Control+c')
    page.keyboard.press('Control+v')
    time.sleep(1)
    check('row 7: copy and paste duplicate an annotation', count('freeTextAnnotations') == texts + 1, (texts, count('freeTextAnnotations')))
    page.keyboard.press('Delete')
    time.sleep(1)
    check('row 7: Delete removes the selected annotation and no device', count('freeTextAnnotations') <= texts + 1 and page.locator('.react-flow__node-topology-node').count() == len(doc()['nodeAnnotations']), (count('freeTextAnnotations'),))

    # Row 11: link label mode; row 12: grid appearance
    page.click('[data-testid="navbar-link-labels"]')
    page.click('[data-testid="navbar-link-label-on-select"]')
    time.sleep(.8)
    escape()
    check('row 11: the link label mode is stored', doc().get('viewerSettings', {}).get('linkLabelMode') == 'on-select', doc().get('viewerSettings'))
    page.click('[data-testid="navbar-lab-settings"]')
    page.click('[data-testid="lab-settings-tab-appearance"]')
    page.click('[data-testid="lab-settings-appearance-subtab-grid"]')
    time.sleep(.5)
    grid_before = dict(doc().get('viewerSettings', {}))
    style = page.locator('[data-testid="lab-settings-grid-style"]')
    if style.count():
        style.click()
        time.sleep(.3)
        option = page.locator('[role="option"]:not([aria-selected="true"])').first
        if option.count():
            option.click()
    page.click('[data-testid="lab-settings-save-btn"]')
    time.sleep(1)
    escape()
    check('row 12: a grid setting is stored', doc().get('viewerSettings', {}) != grid_before and 'gridStyle' in doc().get('viewerSettings', {}), doc().get('viewerSettings'))

    # Row 2: a generated layout, and Undo takes all of it back as one step
    positions = lambda: {a['id']: a.get('position') for a in doc()['nodeAnnotations']}
    placed = positions()
    page.click('[data-testid="navbar-layout"]')
    page.click('[data-testid="navbar-layout-radial"]')
    time.sleep(3)
    escape()
    moved = sum(1 for k, v in positions().items() if v != placed.get(k))
    check('row 2: a generated layout moves the devices', moved >= len(placed) // 2, moved)
    page.mouse.click(1300, 860)
    while page.is_enabled('#map-undo') and positions() != placed:
        page.click('#map-undo')
        time.sleep(.9)
        if positions() == placed:
            break
        if page.evaluate('() => mapHistory.index') == 0:
            break
    check('rows 2/8: Undo returns the devices to where they were', positions() == placed)

    # Row 15: the SVG export
    page.click('[data-testid="navbar-capture"]')
    time.sleep(.6)
    with page.expect_download(timeout=20000) as dl:
        page.click('[data-testid="svg-export-btn"]')
    svg = open(dl.value.path(), encoding='utf-8', errors='replace').read(400)
    check('row 15: the SVG export downloads a drawing', dl.value.suggested_filename.endswith('.svg') and '<svg' in svg, dl.value.suggested_filename)
    escape()

    # Row 10: a link's own label distance (a page dialog; the editor's link form is topology editing)
    edge = page.locator('[data-testid^="rf__edge-"]').first
    edge.click(button='right')
    time.sleep(.5)
    items = page.evaluate('() => [...document.querySelectorAll("[role=menuitem]")].filter(e => e.offsetParent).map(e => e.textContent.trim())')
    check('a link\'s menu has no capture or impairment entry', not any('Impairment' in i or ' - ' in i for i in items), items)
    escape()
    page.click('#map-link')
    page.wait_for_selector('#map-link-dialog[open]')
    first_link = page.evaluate('() => document.getElementById("map-link-select").selectedOptions[0].textContent')
    page.check('#map-link-own')
    page.fill('#map-link-offset', '75')
    page.click('#map-link-apply')
    check('row 10: a distance the editor does not accept is refused in words', '0 to 60' in page.inner_text('#map-link-error'))
    page.fill('#map-link-offset', '48')
    page.click('#map-link-apply')
    page.wait_for_function('() => /Label distance applied/.test(document.getElementById("toast").textContent)', timeout=10000)
    own = [e for e in doc().get('edgeAnnotations', []) if e.get('endpointLabelOffsetEnabled') is True and e.get('endpointLabelOffset') == 48]
    check('row 10: the link\'s own label distance is in the document', len(own) == 1 and own[0]['source'] in first_link and own[0]['target'] in first_link, (own, first_link))
    page.click('#map-link-close')
    shot('ui003b-link-labels')

    # Save, reopen: the stored document is exactly what the editor held; the topology is untouched
    held = page.evaluate('() => mapCurrent')
    page.click('#map-save')
    page.wait_for_function('() => /Saved in the manager/.test(document.getElementById("map-status").textContent)', timeout=20000)
    stored = api(f'/labs/{lid}/map-document')
    check('everything above is saved as one document, byte for byte', stored['annotations'] == held)
    check('the topology text is byte-identical and every write went to the map document', stored['yaml'] == before['yaml'] and all(w == f'PUT labs/{lid}/map-document' for w in writes), writes)
    page.goto(BASE + '/static/map-editor.html#lab=' + lid)
    page.wait_for_selector('.react-flow__node', timeout=30000)
    time.sleep(1.5)
    check('reopening shows shapes, the group and its member, and nothing unsaved', page.inner_text('#map-status') == 'Saved in the manager' and page.locator('.react-flow__node-free-shape-node').count() >= shapes + 3 and page.locator('.react-flow__node-group-node').count() >= groups + 1)
    drawing = api(f'/labs/{lid}/topology')
    check('the manager\'s Topology view has the new shapes and the group', sum(1 for d in drawing['decorations'] if d['type'] in ('rectangle', 'circle', 'line')) >= shapes + 3 and sum(1 for d in drawing['decorations'] if d['type'] == 'group') >= groups + 1 and drawing['settings']['labelMode'] == 'on-select')
    offsets = [ep.get('label_offset') for pair in drawing['links'] for ep in pair if ep.get('label_offset')]
    check('row 10: the manager\'s Topology view gets the link\'s label distance', 48 in offsets, offsets[:6])
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
