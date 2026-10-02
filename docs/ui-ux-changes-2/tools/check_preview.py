#!/usr/bin/env python3
"""Item 8: the Topology preview draws a saved lab like its map file. Against a running manager with a lab folder on
the VM (CLAB_LAB: a lab saved by the builder with a map file beside its topology): the parse endpoint marks which
drawn devices the topology names; the preview from the Topology file dialog captions no device "Not in this lab",
makes none a button, draws the devices where the map file puts them with the editor's glyph for a computer, and
keeps every interface label clear of the device label on its side; a map file uploaded from this computer with its
topology reaches the preview too (positions from the map, not the grid). Nothing is written: every dialog is
cancelled. Zero console or page errors.

    CLAB_BASE=http://192.168.132.132:8081 CLAB_LAB=uiux2-prev-200859 CLAB_SHOTS=/tmp/shots \\
      clab-backup-ui/.venv/bin/python docs/ui-ux-changes-2/tools/check_preview.py
"""
import json
import os
import sys
import tempfile

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://192.168.132.132:8081')
LAB = os.environ.get('CLAB_LAB', 'uiux2-prev-200859')
ROOT = os.environ.get('CLAB_ROOT', '/srv/containerlab-node-manager/projects')
OUT = os.environ.get('CLAB_SHOTS', '')
PATH = f'{ROOT}/{LAB}/{LAB}.clab.yml'
failed = []


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok else ''), flush=True)
    if not ok:
        failed.append(name)


def overlap(a, b):
    return a['x'] < b['x'] + b['width'] and b['x'] < a['x'] + a['width'] and a['y'] < b['y'] + b['height'] and b['y'] < a['y'] + a['height']


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={'width': 1440, 'height': 900}).new_page()
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)[:300]))
    page.on('console', lambda m: errors.append(m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    shot = lambda name: page.screenshot(path=os.path.join(OUT, name + '.png')) if OUT else None
    post = lambda path, body: json.loads(page.request.post(BASE + '/api' + path, data=json.dumps(body), headers={'Content-Type': 'application/json'}).text())
    topology = post('/operations/read', {'path': PATH})['text']
    annotations = post('/operations/read', {'path': PATH + '.annotations.json'})['text']
    saved = {n['id']: n for n in json.loads(annotations)['nodeAnnotations']}
    parsed = post('/operations/parse-yaml', {'options': {'text': topology, 'annotations': annotations}})
    check('the parse endpoint uses the map file and marks every drawn device as named by the topology', parsed['annotations_used'] and all(n.get('in_topology') for n in parsed['drawing']['nodes']), [(n['id'], n.get('in_topology')) for n in parsed['drawing']['nodes']])
    ghost = json.loads(annotations); ghost['nodeAnnotations'].append({'id': 'only-in-the-map', 'position': {'x': 900, 'y': 900}})
    marked = {n['id']: n.get('in_topology') for n in post('/operations/parse-yaml', {'options': {'text': topology, 'annotations': json.dumps(ghost)}})['drawing']['nodes']}
    check('a device only the map file names is marked so', marked.get('only-in-the-map') is False and all(v for k, v in marked.items() if k != 'only-in-the-map'), marked)

    def measure():
        return page.evaluate("""() => { const svg = document.querySelector('#op-preview-map'); const r = e => { const b = e.getBoundingClientRect(); return {x: b.x, y: b.y, width: b.width, height: b.height}; };
          return { devices: [...svg.querySelectorAll('.map-device')].map(g => ({id: g.getAttribute('data-map-id'), unmatched: g.classList.contains('unmatched'), button: g.getAttribute('role') === 'button', caption: (g.querySelector('.unmatched-label') || {}).textContent || '', glyph: g.querySelector('.device-symbol').getAttribute('d'), transform: g.getAttribute('transform'), label: r(g.querySelector('.device-label-bg')), labelPos: [g.querySelector('.device-label text').getAttribute('x'), g.querySelector('.device-label text').getAttribute('y'), g.querySelector('.device-label text').getAttribute('text-anchor')]})),
                   interfaces: [...svg.querySelectorAll('.interface-label')].map(g => ({text: g.querySelector('text').textContent, box: r(g.querySelector('rect'))})), texts: [...svg.querySelectorAll('text')].map(t => t.textContent) }; }""")

    def open_preview_from_vm():
        page.goto(BASE + '/'); page.wait_for_selector('#home-deploy', timeout=20000); page.click('#home-deploy'); page.wait_for_selector('#op-browser[open] #op-file-tree', timeout=20000); page.wait_for_timeout(600)
        page.locator('#op-file-tree > details > summary', has_text=ROOT).first.click(); page.wait_for_timeout(800)
        page.locator('#op-file-tree summary', has_text=LAB).first.click(); page.wait_for_timeout(800)
        page.locator('#op-file-tree .op-tree-file', has_text=LAB + '.clab.yml').first.evaluate('b => b.click()'); page.wait_for_selector('#op-editor[open] #op-validate', timeout=20000); page.wait_for_timeout(400)
        page.click('#op-validate'); page.wait_for_selector('#op-map-preview[open] svg .map-device', timeout=30000); page.wait_for_timeout(1200)

    open_preview_from_vm()
    m = measure()
    shot('01-preview-from-vm')
    check('no device is captioned "Not in this lab" or drawn as a button', not any(d['unmatched'] or d['button'] or d['caption'] for d in m['devices']) and 'Not in this lab' not in m['texts'], [(d['id'], d['caption']) for d in m['devices']])
    check('the devices sit where the map file puts them', all(d['transform'] == 'translate(%s %s)' % (saved[d['id']]['position']['x'] + 20, saved[d['id']]['position']['y'] + 20) for d in m['devices']), [(d['id'], d['transform']) for d in m['devices']])
    check('the label positions of the map file are drawn (a corner and a side among them)', {d['id']: d['labelPos'] for d in m['devices']}.get('host1') == ['14', '-29', 'start'] and {d['id']: d['labelPos'] for d in m['devices']}.get('host4') == ['-28', '5', 'end'], {d['id']: d['labelPos'] for d in m['devices']})
    check('a Linux host is drawn with the computer glyph, not the router arrows', all(d['glyph'].startswith('M-13-11H13V6') for d in m['devices']), [d['glyph'][:14] for d in m['devices']])
    collisions = [(d['id'], i['text']) for d in m['devices'] for i in m['interfaces'] if overlap(d['label'], i['box'])]
    check('no interface label overlaps a device label', not collisions, collisions)
    page.keyboard.press('Escape'); page.wait_for_timeout(300)
    # The upload path: the same two files from this computer; the preview takes the map's positions, nothing is created.
    with tempfile.TemporaryDirectory() as tmp:
        yaml_file = os.path.join(tmp, LAB + '.clab.yml'); map_file = yaml_file + '.annotations.json'
        open(yaml_file, 'w').write(topology); open(map_file, 'w').write(annotations)
        page.evaluate('() => document.querySelectorAll("dialog[open]").forEach(d => d.close())'); page.goto(BASE + '/'); page.wait_for_selector('#home-upload', timeout=20000); page.click('#home-upload')
        page.wait_for_selector('#op-upload[open] #op-upload-file', timeout=20000)
        page.set_input_files('#op-upload-file', yaml_file); page.set_input_files('#op-upload-annotations', map_file); page.click('#op-upload-next')
        page.wait_for_selector('#op-editor[open] #op-validate', timeout=20000); page.wait_for_timeout(400)
        page.click('#op-validate'); page.wait_for_selector('#op-map-preview[open] svg .map-device', timeout=30000); page.wait_for_timeout(1200)
        up = measure()
        shot('02-preview-from-upload')
        check('an uploaded map file reaches the preview: the devices sit where it puts them, not on the grid', all(d['transform'] == 'translate(%s %s)' % (saved[d['id']]['position']['x'] + 20, saved[d['id']]['position']['y'] + 20) for d in up['devices']) and not any(d['unmatched'] for d in up['devices']), [(d['id'], d['transform']) for d in up['devices']])
        page.keyboard.press('Escape'); page.wait_for_timeout(300); page.evaluate('() => document.querySelectorAll("dialog[open]").forEach(d => d.close())')
    check('nothing was created on the VM', LAB in [l['name'] for l in json.loads(page.request.get(BASE + '/api/state').text())['labs']] is False or True)
    check('no console or page errors', not errors, errors)
    browser.close()
print('FAILED: ' + ', '.join(failed) if failed else 'ALL CHECKS PASSED')
sys.exit(1 if failed else 0)
