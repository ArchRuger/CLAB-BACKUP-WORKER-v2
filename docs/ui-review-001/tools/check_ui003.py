#!/usr/bin/env python3
"""UI-003 browser check: Edit map is the lab builder's editor in map mode.

Runs against the fixture manager on fresh data; it edits and saves the fixture lab's map. Each check
names the row of docs/ui-review-001/MAP-PARITY.md it covers.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_ui003.py
"""
import json
import os
import sys
import tempfile
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


def shot(page, name):
    if OUT:
        page.screenshot(path=os.path.join(OUT, name + '.png'))


def menu(page):
    return page.evaluate('() => [...document.querySelectorAll("[role=menuitem]")].filter(e => e.offsetParent).map(e => e.textContent.trim())')


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
    page = ctx.new_page()
    errors, writes = [], []
    page.on('pageerror', lambda e: errors.append(str(e)[:300]))
    page.on('console', lambda m: errors.append(m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.on('request', lambda r: writes.append(r.method + ' ' + r.url.split('/api/')[-1]) if r.method != 'GET' else None)
    api = lambda path: json.loads(page.request.get(BASE + '/api' + path).text())
    lab = next(l for l in api('/state')['labs'] if l['name'] == LAB)
    lid = lab['id']
    before = api(f'/labs/{lid}/map-document')
    doc = lambda d: json.loads(d['annotations'])

    # Edit map on the lab page leads here
    page.goto(BASE + '/')
    page.wait_for_selector('article.lab-card')
    page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
    page.wait_for_selector('#map-edit:not([disabled])')
    page.click('#map-edit')
    page.wait_for_url('**/static/map-editor.html#lab=*', timeout=15000)
    page.wait_for_selector('.react-flow__node', timeout=30000)
    time.sleep(1.5)
    check('Edit map opens the builder\'s editor on the lab\'s own map', page.inner_text('#map-name') == LAB and page.locator('.react-flow__node-topology-node').count() == len(doc(before)['nodeAnnotations']))
    check('the existing annotations are all there (groups, text, shapes)', page.locator('.react-flow__node-group-node').count() >= 1 and page.locator('.react-flow__node-free-text-node').count() >= 1)
    check('it opens saved, with Save off', page.inner_text('#map-status') == 'Saved in the manager' and page.is_disabled('#map-save'))
    check('the palette shows the drawing tools, not devices', page.evaluate('() => !document.querySelector("[data-testid=panel-tab-nodes]")?.offsetParent') and 'Shapes' in page.inner_text('[data-testid="context-panel"]'))
    shot(page, 'ui003-opened')

    # Row 1: move a device
    node = page.locator('[data-testid="rf__node-RTR8"]')
    box = node.bounding_box()
    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    page.mouse.down()
    page.mouse.move(box['x'] + 150, box['y'] + 170, steps=12)
    page.mouse.up()
    time.sleep(1)
    check('row 1: dragging a device marks the map as unsaved', page.inner_text('#map-status') == 'Unsaved changes' and page.is_enabled('#map-save'))

    # Row 8: undo and redo (the page's own history; the editor has none in this mode)
    place = lambda: (round(node.bounding_box()['x']), round(node.bounding_box()['y']))
    moved = place()
    page.click('#map-undo')
    page.wait_for_function('() => document.getElementById("map-status").textContent === "Saved in the manager"', timeout=10000)
    time.sleep(.6)
    check('row 8: Undo puts the device back and there is nothing left to save', place() == (round(box['x']), round(box['y'])) and page.is_disabled('#map-save') and page.is_disabled('#map-undo'), (place(), box))
    page.mouse.click(900, 250)
    page.keyboard.press('Control+Shift+z')
    page.wait_for_function('() => document.getElementById("map-status").textContent === "Unsaved changes"', timeout=10000)
    time.sleep(.6)
    check('row 8: Redo (Ctrl+Shift+Z) brings the move back', place() == moved and page.is_disabled('#map-redo'), (place(), moved))

    # Row 9: the device look (a page dialog; the editor's own form is topology editing)
    entry = lambda: next(a for a in json.loads(page.evaluate('() => mapCurrent'))['nodeAnnotations'] if a['id'] == 'RTR8')
    node.click()
    page.click('#map-look')
    page.wait_for_selector('#map-look-dialog[open]')
    check('row 9: Device look opens on the device selected on the canvas', page.input_value('#map-look-device') == 'RTR8')
    page.select_option('#map-look-icon', 'server')
    page.uncheck('#map-look-color-default')
    page.fill('#map-look-color', '#cc2200')
    page.select_option('#map-look-position', 'top')
    page.fill('#map-look-radius', '12')
    page.click('#map-look-apply')
    page.wait_for_function('() => /Look applied to RTR8/.test(document.getElementById("toast").textContent)', timeout=10000)
    look = entry()
    check('row 9: icon, colour, corner radius and label position are in the document', (look.get('icon'), look.get('iconColor'), look.get('iconCornerRadius'), look.get('labelPosition')) == ('server', '#cc2200', 12, 'top'), look)
    page.fill('#map-look-radius', '99')
    page.click('#map-look-apply')
    check('row 9: a value the editor does not accept is refused in words', '0 to 20' in page.inner_text('#map-look-error') and entry().get('iconCornerRadius') == 12)
    page.click('#map-look-close')
    page.click('#map-undo')
    time.sleep(1)
    check('row 9: the look is one undo step', entry().get('icon') != 'server' and 'iconColor' not in entry(), entry())
    page.click('#map-redo')
    time.sleep(1)
    shot(page, 'ui003-device-look')

    # Rows 3 and 4: add a text and a shape from the pane menu
    page.mouse.click(620, 760, button='right')
    time.sleep(.5)
    items = menu(page)
    check('the pane menu offers Add Group, Add Text, Add Shape and nothing that needs a running lab', items[:3] == ['Add Group', 'Add Text', 'Add Shape'] and 'Add Traffic Rate' not in items and 'Open Palette' not in items, items)
    page.click('[data-testid="context-menu-item-add-text"]')
    time.sleep(1.2)
    shot(page, 'ui003-add-text')
    check('row 3: Add Text opens the inline editor with its formatting toolbar', page.is_visible('[data-testid="free-text-inline-toolbar"]'))
    # The inline box does not take the focus by itself once the context menu has closed (upstream): click into it.
    page.locator('textarea:visible').last.click()
    page.keyboard.type('Area 0 note')
    page.click('[data-testid="inline-text-bold"]')
    page.mouse.click(900, 250)
    time.sleep(1)
    texts = page.locator('.react-flow__node-free-text-node').count()

    # The topology cannot be changed
    count = page.locator('.react-flow__node-topology-node').count()
    node.click()
    page.keyboard.press('Delete')
    time.sleep(.8)
    check('a device cannot be deleted', page.locator('.react-flow__node-topology-node').count() == count)
    node.click(button='right')
    time.sleep(.5)
    items = menu(page)
    check('a device\'s menu has no runtime action (start, stop, SSH …) and no edit or delete', not any(w in items for w in ['Start', 'Stop', 'Restart', 'SSH', 'Shell', 'Logs', 'Edit', 'Delete']), items)
    page.keyboard.press('Escape')
    check('no deploy or VM control is shown', page.evaluate('() => ["navbar-deploy", "navbar-deploy-menu", "navbar-split-view"].every(id => !document.querySelector(`[data-testid="${id}"]`)?.offsetParent)'))

    # Rows 11 and 12 exist in this mode
    check('rows 11/12: link label mode and lab settings (grid) are available', page.is_visible('[data-testid="navbar-link-labels"]') and page.is_visible('[data-testid="navbar-lab-settings"]'))
    check('row 2: generated layouts are available', page.is_visible('[data-testid="navbar-layout"]'))
    check('row 14: fit to viewport is available', page.is_visible('[data-testid="navbar-fit-viewport"]'))

    # Row 17: leaving with unsaved changes asks
    page.click('#map-back')
    check('row 17: leaving with unsaved changes asks first', page.evaluate('() => document.getElementById("map-leave").open'))
    page.click('#map-leave-stay')

    # Save: only the annotations go to the manager; the drawing follows; the topology is untouched
    page.click('#map-save')
    page.wait_for_function('() => /Saved in the manager/.test(document.getElementById("map-status").textContent)', timeout=15000)
    after = api(f'/labs/{lid}/map-document')
    pos = lambda d: next(a for a in doc(d)['nodeAnnotations'] if a['id'] == 'RTR8')['position']
    check('the save sent one request, to the map document only', writes == [f'PUT labs/{lid}/map-document'], writes)
    check('the device position was saved and the topology text is byte-identical', pos(after) != pos(before) and after['yaml'] == before['yaml'], (pos(before), pos(after)))
    added = [t for t in doc(after).get('freeTextAnnotations', []) if t.get('text') == 'Area 0 note']
    check('row 3: the added text is in the saved document with its style', len(added) == 1 and added[0].get('fontWeight') == 'bold', added)
    check('nothing the manager does not draw was lost', all(len(doc(after).get(k, [])) >= len(doc(before).get(k, [])) for k in ('groupStyleAnnotations', 'freeShapeAnnotations', 'edgeAnnotations')))
    drawing = api(f'/labs/{lid}/topology')
    saved = next(n for n in drawing['nodes'] if n['id'] == 'RTR8')
    check('the manager\'s drawing follows the saved map', (saved['x'], saved['y']) == (pos(after)['x'], pos(after)['y']), (saved['x'], saved['y']))
    check('row 9: the manager\'s Topology view gets the device look', (saved.get('icon'), saved.get('iconColor'), saved.get('labelPosition')) == ('server', '#cc2200', 'top'), {k: saved.get(k) for k in ('icon', 'iconColor', 'labelPosition')})

    # Row 16: exports kept
    with page.expect_download(timeout=15000) as dl:
        page.click('#map-download')
    name = dl.value.suggested_filename
    data = json.load(open(dl.value.path()))
    check('row 16: Download map file gives the full document', name.endswith('.annotations.json') and data == doc(after), name)
    with page.expect_download(timeout=15000) as dl:
        page.click('#map-drawio')
    check('row 16: Export to draw.io still works, from the saved map', dl.value.suggested_filename.endswith('.drawio'), dl.value.suggested_filename)

    # Back on the lab page the Topology view shows the saved map
    page.click('#map-back')
    page.wait_for_selector('#lab-content:not([hidden]) #topology-map [data-map-id]', timeout=20000)
    check('Back to the lab returns to its Topology tab with the saved map', page.evaluate('() => location.hash.includes("view=topology") || !document.getElementById("topology-view").hidden'))
    shot(page, 'ui003-topology-after')

    # Reopen: what was saved is what opens; row 16 import replaces the map
    page.goto(BASE + '/static/map-editor.html#lab=' + lid)
    page.wait_for_selector('.react-flow__node', timeout=30000)
    time.sleep(1)
    check('reopening shows the saved map and nothing unsaved', page.inner_text('#map-status') == 'Saved in the manager' and api(f'/labs/{lid}/map-document')['annotations'] == after['annotations'])
    work = tempfile.mkdtemp()
    wrong, good = os.path.join(work, 'notes.json'), os.path.join(work, 'lab.annotations.json')
    open(wrong, 'w').write('{"name": "x"}')
    imported = doc(after)
    imported['freeTextAnnotations'] = imported.get('freeTextAnnotations', []) + [{'id': 'imported-note', 'text': 'Imported note', 'position': {'x': 40, 'y': 40}, 'fontSize': 18}]
    imported['vendorExtension'] = {'kept': True}
    open(good, 'w').write(json.dumps(imported))
    page.click('#map-import')
    page.set_input_files('#map-import-file', wrong)
    page.click('#map-import-confirm')
    page.wait_for_function('() => /not a containerlab map file/.test(document.getElementById("map-import-error").textContent)', timeout=10000)
    check('row 16: a file that is not a map file is refused in words', True)
    page.set_input_files('#map-import-file', good)
    page.click('#map-import-confirm')
    page.wait_for_function('() => [...document.querySelectorAll(".react-flow__node-free-text-node")].some(n => /Imported note/.test(n.textContent))', timeout=30000)
    now = doc(api(f'/labs/{lid}/map-document'))
    check('row 16: an imported map file replaces the map, unknown keys included', now.get('vendorExtension') == {'kept': True} and any(t.get('id') == 'imported-note' for t in now['freeTextAnnotations']))
    check('no operation, deployment or VM request was ever sent', all(w.startswith('PUT labs/') and w.endswith('/map-document') for w in writes), writes)
    check('no console or page errors', not errors, errors)
    browser.close()
sys.exit(1 if failed else 0)
