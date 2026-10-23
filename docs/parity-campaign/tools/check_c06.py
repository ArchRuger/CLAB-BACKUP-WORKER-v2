#!/usr/bin/env python3
"""C06 browser check: the Topology tab's link state, Find, link hover, picture, draw.io export, Arrange and Undo.

Fixture evidence only: the real manager on a scratch FIXTURE_DATA with scripted VM answers (fixture_manager.py), so link
state here is what the scripted helper reports, not a live lab. Start the fixture on a port of your own with a FRESH data
directory, then run this against it; the check changes the fixture (switches, an arrangement it undoes again) and
exits non-zero when any check fails. One line per check. Never point it at a live manager.

    FIXTURE_DATA=$(mktemp -d) clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 9010 &
    ~/pw-venv/bin/python docs/parity-campaign/tools/check_c06.py --base http://127.0.0.1:9010 [--shots DIR] [--widths 1440,760,390]

Switches and actions used (docs/git-redesign/tools/fixture/SCENARIOS.md): link_state, link_helper, refresh_capabilities,
busy_lab, reset.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

VIEWPORTS = {1440: 800, 760: 700, 390: 700}     # width: height (a short page makes the stage as small as it gets)
BGP, SQUARE = 'BGP_TheoryToPractice', 'square-fresh'
failed = []
trace = []          # the last link-state and arrange answers this page saw, printed with a failure
base = ''
shots = ''


def check(name, ok, detail=''):
    print(('ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if not ok and detail else ''), flush=True)
    if not ok:
        failed.append(name)
        if trace:
            print('     recent answers: ' + ' | '.join(trace[-6:]), flush=True)
    return ok


def fixture(route, body=None):
    request = urllib.request.Request(base + route, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json'}, method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def switch(**values):
    return fixture('/fixture/switch', values)


def action(**values):
    return fixture('/fixture/action', values)


def until(page, script, timeout=20.0, arg=None):
    """Poll a page function until it returns something truthy (the page's CSP forbids wait_for_function strings)."""
    end = time.time() + timeout
    value = None
    while time.time() < end:
        value = page.evaluate(script, arg) if arg is not None else page.evaluate(script)
        if value:
            return value
        page.wait_for_timeout(150)
    return value


def text_of(page, selector):
    return page.evaluate('(s) => { const e = document.querySelector(s); return e ? e.innerText : null; }', selector) or ''


def api(page, method, path, body=None):
    """A same-origin request from the page (its Origin header is what the guard wants); returns [status, parsed body or text]."""
    return page.evaluate('''async ([method, path, body]) => {
        const response = await fetch('/api' + path, {method, headers: {'Content-Type': 'application/json'}, body: body === null ? undefined : JSON.stringify(body)});
        const text = await response.text();
        let data = text; try { data = JSON.parse(text); } catch (e) {}
        return [response.status, data, response.headers.get('content-disposition') || ''];
    }''', [method, path, body])


def shot(page, name):
    if shots:
        page.screenshot(path=os.path.join(shots, name + '.png'))


def lab_ids():
    state = json.loads(urllib.request.urlopen(urllib.request.Request(base + '/api/state', headers={'Origin': base}), timeout=30).read())
    return {lab['name']: lab['id'] for lab in state['labs']}


races = []     # page loads where the map-tools hook never ran (see open_map)


def open_map(page, lab_id, ready=True):
    """Open the lab's Topology view and wait for the link-state chip. A page load can finish the /topology answer before
    map-tools.js has run: refreshMap then skips the mapToolsRendered hook and its unchanged-drawing early return never calls it
    again, so the chip stays empty and no link state is ever fetched (reproduced on purpose by delaying map-tools.js by 1.5 s;
    about 1 load in 100 on the fixture). The check notes it, reloads once more and goes on, so one defect does not hide the rest."""
    page.goto(f'{base}/#lab={lab_id}&view=topology')
    for attempt in range(3):
        page.reload()
        page.wait_for_selector('#topology-map .topology-wire', timeout=30000)
        if not ready:
            break
        if until(page, '() => /Links:|Link state (off|stopped)|not running/.test((document.getElementById("map-links")||{}).innerText||"")', 12 if attempt < 2 else 25):
            break
        hook = page.evaluate('() => typeof mapToolsDrawing !== "undefined" && !!mapToolsDrawing')
        if not hook:
            races.append(lab_id)
            print(f'note  load race: the map is drawn but map-tools never saw the drawing (attempt {attempt + 1}); reloading', flush=True)
    page.wait_for_timeout(300)


def wire_point(page, selector):
    """The screen point of the middle of a wire's hit path, scrolled into the viewport first."""
    for _ in range(3):
        point = page.evaluate('''(s) => { const p = document.querySelector(s); if (!p) return null;
            const len = p.getTotalLength(), pt = p.getPointAtLength(len / 2), m = p.getScreenCTM();
            return {x: m.a * pt.x + m.c * pt.y + m.e, y: m.b * pt.x + m.d * pt.y + m.f, h: window.innerHeight, w: window.innerWidth}; }''', selector)
        if not point:
            return None
        if 0 <= point['y'] < point['h'] - 4 and 0 <= point['x'] < point['w']:
            return point
        page.evaluate('(y) => window.scrollBy(0, y)', point['y'] - point['h'] / 2)
        page.wait_for_timeout(200)
    return point


def counts(page):
    return page.evaluate('''() => ({
        wires: document.querySelectorAll('.topology-wire').length,
        up: document.querySelectorAll('.topology-wire.link-up').length,
        down: document.querySelectorAll('.topology-wire.link-down').length,
        dimmedDevices: document.querySelectorAll('.map-device.dimmed').length,
        dimmedWires: document.querySelectorAll('.topology-wire.dimmed').length,
        devices: document.querySelectorAll('.map-device').length})''')


def run_width(pw, width, height, ids):
    tag = f'w{width}'
    browser = pw.chromium.launch()
    context = browser.new_context(viewport={'width': width, 'height': height}, accept_downloads=True)
    page = context.new_page()
    problems, bad_status = [], []
    page.on('pageerror', lambda e: problems.append('pageerror: ' + str(e)[:300]))
    page.on('console', lambda m: problems.append('console: ' + m.text[:300]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    page.on('response', lambda r: trace.append(f'{r.status} {r.request.method} {r.url.split(base)[-1][:70]}') if ('link-state' in r.url or '/arrange' in r.url or 'capabilities' in r.url) else None)
    page.on('response', lambda r: bad_status.append(f'{r.status} {r.request.method} {r.url.split(base)[-1][:120]}') if r.status >= 400 else None)
    downloads = tempfile.mkdtemp(prefix='c06dl')
    try:
        action(action='busy_lab', on=False)
        action(action='reset')
        action(action='refresh_capabilities')

        # ---- Link state: chip, legend, classes (every end up) ------------------------------------------------------------
        open_map(page, ids[BGP])
        chip = text_of(page, '#map-links')
        c = counts(page)
        check(f'{tag} chip counts every link, worded "connected" for a lab with VM-in-container devices', 'Links: 16 connected' in chip, chip)
        check(f'{tag} legend names the dotted red down stroke', 'dotted red = down (container link)' in chip, chip)
        check(f'{tag} every wire is link-up and none link-down', c['wires'] == 16 and c['up'] == 16 and c['down'] == 0, str(c))
        label = page.evaluate('() => document.querySelector(".topology-wire").getAttribute("aria-label")')
        check(f'{tag} a wire keeps its capture name and gains the state clause', label.startswith('Capture RTR6:eth1 to PE1:Gi0/0/0/1') and 'connected' in label, label)
        shot(page, f'c06-{tag}-links-up')

        # ---- One link down: the chip, the red dotted wire, the hover line naming both ends ------------------------------
        switch(link_state={'RTR6': {'eth1': 'dormant'}, 'PE1': {'Gi0/0/0/1': 'dormant'}})
        open_map(page, ids[BGP])
        chip = text_of(page, '#map-links')
        c = counts(page)
        check(f'{tag} one dormant link: chip reads 15 connected and 1 down', 'Links: 15 connected · 1 down' in chip, chip)
        check(f'{tag} exactly one wire is link-down', c['down'] == 1 and c['up'] == 15, str(c))
        stroke = page.evaluate('''() => { const p = document.querySelector('.topology-wire.link-down path:not(.capture-hit)');
            const s = getComputedStyle(p); return [s.strokeDasharray, s.stroke]; }''')
        check(f'{tag} the down wire is dotted and red', stroke[0] not in ('none', '') and re.search(r'rgb\(\s*(1[5-9]\d|2\d\d)\s*,', stroke[1]) is not None, str(stroke))
        point = wire_point(page, '.topology-wire.link-down path.capture-hit')
        page.mouse.move(point['x'], point['y'])
        hover = until(page, '() => { const e = document.getElementById("map-link-hover"); return e && !e.hidden ? e.textContent : ""; }', 5)
        check(f'{tag} hover line names both ends and both states', bool(hover) and 'RTR6:eth1' in hover and 'PE1:Gi0/0/0/1' in hover
              and 'down at both ends (dormant' in hover, hover)
        ends = page.evaluate('() => document.querySelectorAll(".map-device.hover-end").length')
        check(f'{tag} hover marks the two end devices', ends == 2, str(ends))
        shot(page, f'c06-{tag}-link-hover')
        page.mouse.move(2, 2)
        gone = until(page, '() => document.getElementById("map-link-hover").hidden', 5)
        check(f'{tag} leaving the wire clears the hover line', gone is True)
        page.focus('.topology-wire.link-down')
        keyed = until(page, '() => { const e = document.getElementById("map-link-hover"); return e && !e.hidden ? e.textContent : ""; }', 5)
        check(f'{tag} focusing the wire from the keyboard shows the same line', bool(keyed) and 'RTR6:eth1' in keyed and 'PE1:Gi0/0/0/1' in keyed, keyed)

        switch(link_state={'RTR6': {'eth1': 'dormant'}})
        open_map(page, ids[BGP])
        until(page, '() => document.querySelectorAll(".topology-wire.link-down").length > 0', 20)
        clause = page.evaluate('() => { const g = document.querySelector(".topology-wire.link-down"); return g ? g.getAttribute("data-state-text") : null; }')
        check(f'{tag} one end down names that end', clause is not None and clause.startswith('down: RTR6 eth1 is dormant'), f'{clause!r} chip={text_of(page, "#map-links")!r}')
        switch(link_state={'PE1': 'absent'})
        open_map(page, ids[BGP])
        until(page, '() => document.querySelectorAll(".topology-wire.link-down").length > 0', 20)
        clause = page.evaluate('() => [...document.querySelectorAll(".topology-wire.link-down")].map(g => g.getAttribute("data-state-text"))')
        check(f'{tag} a device missing from the listing reads "not running" on its wires', len(clause) >= 1 and all('PE1 is not running' in x for x in clause), str(clause))
        switch(link_state=None)

        # ---- Degraded: an old helper, a containerlab without the command, an unlinked lab ---------------------------------
        switch(link_helper='old')
        action(action='refresh_capabilities')
        open_map(page, ids[BGP])
        chip = text_of(page, '#map-links')
        check(f'{tag} an old helper: link state off with the update sentence, wires plain', 'Link state off' in chip and 'needs the updated VM helper' in chip
              and counts(page)['up'] == 0 and counts(page)['down'] == 0, repr(chip))
        switch(link_helper='containerlab')
        action(action='refresh_capabilities')
        open_map(page, ids[BGP])
        chip = text_of(page, '#map-links')
        check(f'{tag} containerlab before 0.64: link state off naming the version', 'needs containerlab 0.64 or later' in chip and '0.60.0' in chip, repr(chip))
        switch(link_helper=None)
        action(action='refresh_capabilities')

        # ---- Find: by keyboard, dimming and the count, Enter fits, Escape clears --------------------------------------------
        open_map(page, ids[BGP])
        before_box = page.evaluate('() => document.getElementById("topology-map").getAttribute("viewBox")')
        page.focus('#map-find')
        page.keyboard.type('PE')
        count = until(page, '() => { const e = document.getElementById("map-find-count"); return e && !e.hidden ? e.innerText : ""; }', 5)
        m = re.match(r'^(\d+) of 13 devices? match', count or '')
        c = counts(page)
        check(f'{tag} Find shows the count and dims the rest', bool(m) and int(m.group(1)) >= 1 and c['dimmedDevices'] == 13 - int(m.group(1)), f'{count} {c}')
        check(f'{tag} wires between dimmed devices dim, wires touching a match stay', 0 < c['dimmedWires'] < c['wires'], str(c))
        shot(page, f'c06-{tag}-find')
        page.keyboard.press('Enter')
        page.wait_for_timeout(400)
        after_box = page.evaluate('() => document.getElementById("topology-map").getAttribute("viewBox")')
        check(f'{tag} Enter fits the matching devices', after_box != before_box, f'{before_box} -> {after_box}')
        page.keyboard.press('Control+A')
        page.keyboard.type('zzz')
        none = until(page, '() => { const e = document.getElementById("map-find-count"); return e && !e.hidden ? e.innerText : ""; }', 5)
        check(f'{tag} no match says so and dims everything', 'No device matches "zzz"' in (none or '') and counts(page)['dimmedDevices'] == 13, str(none))
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        c = counts(page)
        check(f'{tag} Escape clears the term, the count and the dimming', page.input_value('#map-find') == '' and c['dimmedDevices'] == 0 and c['dimmedWires'] == 0
              and page.evaluate('() => document.getElementById("map-find-count").hidden') is True, str(c))
        check(f'{tag} Find leaves the Devices search alone', page.evaluate('() => (document.getElementById("search") || {value: ""}).value') == '')
        page.click('#map-expand')
        page.focus('#map-find')
        page.keyboard.type('PE')
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        expanded = page.evaluate('() => document.getElementById("topology-view").classList.contains("map-expanded")')
        check(f'{tag} Escape in Find clears the term and keeps an expanded map open', page.input_value('#map-find') == '' and expanded is True)
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        check(f'{tag} a second Escape closes the expanded map', page.evaluate('() => document.getElementById("topology-view").classList.contains("map-expanded")') is False)

        # ---- Download picture ---------------------------------------------------------------------------------------------
        switch(link_state={'RTR6': {'eth1': 'dormant'}, 'PE1': {'Gi0/0/0/1': 'dormant'}})
        open_map(page, ids[BGP])
        until(page, '() => document.querySelectorAll(".topology-wire.link-down").length > 0', 20)

        def picture(png=False, state=False, whole=True):
            page.click('#map-more-button')
            page.click('#map-picture')
            page.wait_for_selector('#map-picture-dialog[open]')
            if png:
                page.check('#map-picture-png')
            if not whole:
                page.check('#map-picture-shown')
            if state:
                page.check('#map-picture-state')
            with page.expect_download(timeout=30000) as info:
                page.click('#map-picture-form button[type=submit]')
            download = info.value
            path = os.path.join(downloads, download.suggested_filename)
            download.save_as(path)
            page.wait_for_selector('#map-picture-dialog[open]', state='hidden')
            return download.suggested_filename, open(path, 'rb').read()

        name, data = picture()
        svg = data.decode('utf8', 'replace')
        check(f'{tag} picture: the SVG is named after the lab', name == f'{BGP}-map.svg', name)
        check(f'{tag} picture: the SVG is a standalone drawing', svg.startswith('<svg') and 'xmlns="http://www.w3.org/2000/svg"' in svg and 'viewBox="' in svg and len(svg) > 3000, svg[:120])
        leaks = [word for word in ('capture-hit', 'link-down', 'link-up', 'state-ready', 'state-starting', 'hover', 'dimmed', 'data-', 'tabindex', 'aria-', '<title') if word in svg]
        check(f'{tag} picture: no hit paths, state classes, data or accessibility attributes in the SVG', not leaks, ','.join(leaks))
        dotted_off = svg.count('stroke-dasharray')
        name, data = picture(state=True)
        dotted_on = data.decode('utf8', 'replace').count('stroke-dasharray')
        check(f'{tag} picture: with state on the down link is drawn dotted in the SVG', dotted_on > dotted_off, f'{dotted_off} vs {dotted_on}')
        check(f'{tag} picture: the live map is unchanged after a download', counts(page)['down'] == 1 and page.evaluate('() => document.querySelectorAll(".map-device.state-ready").length') > 0)
        name, data = picture(png=True)
        check(f'{tag} picture: the PNG is named after the lab and is a real PNG', name == f'{BGP}-map.png' and data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) > 2000, f'{name} {len(data)} bytes')
        shot(page, f'c06-{tag}-picture')
        switch(link_state=None)

        # ---- Export to draw.io ---------------------------------------------------------------------------------------------
        def drawio(layout=None, theme=None):
            page.click('#map-more-button')
            page.click('#map-drawio-export')
            page.wait_for_selector('#map-drawio-dialog[open]')
            if layout:
                page.check(f'#map-drawio-layout-{layout}')
            if theme:
                page.check(f'#map-drawio-theme-{theme}')
            with page.expect_download(timeout=30000) as info:
                page.click('#map-drawio-form button[type=submit]')
            download = info.value
            path = os.path.join(downloads, download.suggested_filename)
            download.save_as(path)
            page.wait_for_selector('#map-drawio-dialog[open]', state='hidden')
            return download.suggested_filename, open(path, 'rb').read().decode('utf8', 'replace')

        open_map(page, ids[BGP])
        name, body = drawio()
        check(f'{tag} draw.io: As on the map saves <lab>.drawio with mxfile XML', name == f'{BGP}.drawio' and '<mxfile' in body[:200] and '<mxCell' in body, f'{name} {body[:80]}')
        name, body = drawio(layout='rows', theme='print')
        check(f'{tag} draw.io: Rows saves <lab>-rows.drawio', name == f'{BGP}-rows.drawio' and '<mxfile' in body, name)
        check(f'{tag} draw.io: the print theme draws black on white', 'strokeColor=#000000' in body and 'fillColor=#ffffff' in body, 'print markers missing')
        name, manager = drawio(layout='columns')
        check(f'{tag} draw.io: Columns saves <lab>-columns.drawio', name == f'{BGP}-columns.drawio' and '<mxfile' in manager, name)
        status = api(page, 'GET', f'/labs/{ids[BGP]}/drawio?layout=map&theme=print')
        check(f'{tag} draw.io: the route answers 200 with a .drawio attachment', status[0] == 200 and '.drawio' in status[2] and '<mxfile' in str(status[1]), f'{status[0]} {status[2]}')
        status = api(page, 'GET', f'/labs/{ids[BGP]}/drawio?layout=horizontal')
        check(f'{tag} draw.io: the removed horizontal layout is still refused', status[0] == 400 and 'Choose a supported layout.' in json.dumps(status[1]), str(status[:2]))
        status = api(page, 'GET', f'/labs/{ids[BGP]}/drawio?theme=neon')
        check(f'{tag} draw.io: an unknown theme is refused with its sentence', status[0] == 400 and 'Choose a supported theme.' in json.dumps(status[1]), str(status[:2]))

        # ---- Arrange devices, Undo, the stale 412 and the busy 409 -----------------------------------------------------------
        sq = ids[SQUARE]
        open_map(page, sq)
        hint = text_of(page, '#map-links')
        check(f'{tag} a map on the default grid says so and offers Arrange', 'Devices sit on the default grid.' in hint and page.locator('#map-arrange-hint').count() == 1, hint)
        original = api(page, 'GET', f'/labs/{sq}/topology')[1]
        positions = lambda d: sorted((n['id'], n['x'], n['y']) for n in d['nodes'])
        check(f'{tag} the drawing carries revision and placed=false', bool(original.get('revision')) and original.get('placed') is False)
        drawn = lambda: page.evaluate('() => [...document.querySelectorAll(".map-device")].map(e => e.getAttribute("transform")).sort()')
        grid = drawn()
        page.click('#map-arrange-hint')
        page.wait_for_selector('#map-arrange-dialog[open]')
        check(f'{tag} the dialog offers Rows, Columns and Ring, all enabled for a linked map', all(page.is_enabled(f'#map-arrange-{m}') for m in ('rows', 'columns', 'ring')))
        shot(page, f'c06-{tag}-arrange-dialog')
        page.click('#map-arrange-rows')
        page.wait_for_selector('#map-arrange-dialog[open]', state='hidden')
        undo_shown = until(page, '() => !!document.querySelector("[data-map-arrange-undo]")', 15)
        arranged = api(page, 'GET', f'/labs/{sq}/topology')[1]
        check(f'{tag} Arrange rows saved: positions changed, placed=true, new revision', positions(arranged) != positions(original) and arranged['placed'] is True
              and arranged['revision'] != original['revision'])
        check(f'{tag} the map shows Undo arrange and the grid sentence is gone', bool(undo_shown) and 'Devices sit on the default grid.' not in text_of(page, '#map-links'), text_of(page, '#map-links'))
        rendered = drawn()
        check(f'{tag} the map was redrawn from the saved positions (the server is the only source)', rendered != grid and len(rendered) == len(grid), f'{grid} -> {rendered}')
        shot(page, f'c06-{tag}-arranged')
        stale = api(page, 'POST', f'/labs/{sq}/arrange', {'mode': 'columns', 'revision': original['revision']})
        check(f'{tag} a second arrange with the old revision is a 412 stale', stale[0] == 412 and stale[1].get('reason') == 'stale' and 'The map changed since you looked at it' in stale[1].get('detail', ''), str(stale[:2]))
        action(action='busy_lab', on=True, lab=SQUARE)
        busy = api(page, 'POST', f'/labs/{sq}/arrange', {'mode': 'ring', 'revision': arranged['revision']})
        check(f'{tag} arrange while an operation runs is the busy 409', busy[0] == 409 and busy[1].get('detail') == 'Wait for the current lab operation to finish.', str(busy[:2]))
        page.click('[data-map-arrange-undo]')
        said = until(page, '() => (document.getElementById("map-status").innerText || "").indexOf("Wait for the current lab operation") >= 0', 8)
        check(f'{tag} Undo while busy shows the sentence and stays offered', bool(said) and page.locator('[data-map-arrange-undo]').count() == 1, text_of(page, '#map-status'))
        action(action='busy_lab', on=False)
        still = api(page, 'GET', f'/labs/{sq}/topology')[1]
        check(f'{tag} the busy refusal changed nothing', positions(still) == positions(arranged))
        page.wait_for_timeout(500)
        page.click('[data-map-arrange-undo]')
        back = until(page, '() => !document.querySelector("[data-map-arrange-undo]") && document.getElementById("map-links").innerText.indexOf("default grid") >= 0', 15)
        restored = api(page, 'GET', f'/labs/{sq}/topology')[1]
        check(f'{tag} Undo restores the positions, placed=false and the revision', positions(restored) == positions(original) and restored['placed'] is False
              and restored['revision'] == original['revision'])
        check(f'{tag} Undo brings the default-grid sentence back and redraws the grid', bool(back) and drawn() == grid, text_of(page, '#map-links'))
        again = api(page, 'POST', f'/labs/{sq}/arrange', {'undo': True, 'revision': restored['revision']})
        check(f'{tag} a second Undo has nothing to undo (412 stale)', again[0] == 412 and again[1].get('reason') == 'stale', str(again[:2]))

        # ---- The More menu with the C05 chip shown ---------------------------------------------------------------------
        open_map(page, ids[BGP])
        until(page, '() => { const e = document.getElementById("map-impaired"); return !!e && !e.hidden; }', 25)
        chip_shown = page.evaluate('() => { const e = document.getElementById("map-impaired"); return !!e && !e.hidden && e.getBoundingClientRect().width > 0; }')
        check(f'{tag} the impairment chip is shown beside the tools', chip_shown, text_of(page, '#map-impaired'))
        page.click('#map-more-button')
        page.wait_for_selector('#map-more-menu:not([hidden])')
        geometry = page.evaluate('''() => {
            const items = [...document.querySelectorAll('#map-more-menu [role=menuitem]')], last = items[items.length - 1], r = last.getBoundingClientRect();
            const hit = (x, y) => { const e = document.elementFromPoint(x, y); return !!e && (e === last || last.contains(e)); };
            const stage = document.getElementById('topology-map').getBoundingClientRect();
            return {items: items.map(e => e.id), bottom: r.bottom, top: r.top, left: r.left, right: r.right, viewport: [window.innerWidth, window.innerHeight], scroll: window.scrollY,
                    visible: r.width > 0 && r.height > 0 && r.left >= 0 && r.right <= window.innerWidth,
                    hits: [hit(r.left + 4, r.top + 3), hit((r.left + r.right) / 2, (r.top + r.bottom) / 2), hit(r.right - 4, r.bottom - 3)],
                    stageHeight: stage.height};
        }''')
        if geometry['bottom'] > geometry['viewport'][1]:       # a long menu may sit below the fold: bring it up like a person scrolling
            page.evaluate('(y) => window.scrollBy(0, y)', geometry['bottom'] - geometry['viewport'][1] + 8)
            page.wait_for_timeout(200)
            geometry = page.evaluate('''() => { const items = [...document.querySelectorAll('#map-more-menu [role=menuitem]')], last = items[items.length - 1], r = last.getBoundingClientRect();
                const hit = (x, y) => { const e = document.elementFromPoint(x, y); return !!e && (e === last || last.contains(e)); };
                return {items: items.map(e => e.id), bottom: r.bottom, viewport: [window.innerWidth, window.innerHeight], visible: r.width > 0 && r.left >= 0 && r.right <= window.innerWidth,
                        hits: [hit(r.left + 4, r.top + 3), hit((r.left + r.right) / 2, (r.top + r.bottom) / 2), hit(r.right - 4, r.bottom - 3)]}; }''')
        check(f'{tag} the More menu lists Import map, the three new items, Open all CLIs and Back up all in order',
              geometry['items'] == ['import-map', 'map-picture', 'map-drawio-export', 'map-arrange', 'map-ssh-all', 'map-backup-all'], str(geometry['items']))
        check(f'{tag} the last menu item is fully visible and not clipped (top, middle, bottom all hit it)', geometry['visible'] and all(geometry['hits']), json.dumps(geometry))
        shot(page, f'c06-{tag}-more-menu')
        page.keyboard.press('Escape')

        # ---- No console errors, and only the failures this check provoked --------------------------------------------------
        expected = {'412 POST', '409 POST'}
        unexpected = [s for s in bad_status if ' '.join(s.split()[:2]) not in expected or '/arrange' not in s]
        # the draw.io 400s and the 404s of probes made through api() above are provoked too
        unexpected = [s for s in unexpected if '/drawio' not in s]
        check(f'{tag} no console or page errors', not problems, ' | '.join(problems[:5]))
        check(f'{tag} no failed request other than the refusals this check provoked', not unexpected, ' | '.join(unexpected[:6]))
    finally:
        action(action='busy_lab', on=False)
        switch(link_state=None, link_helper=None)
        browser.close()


def main():
    global base, shots
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default=os.environ.get('CLAB_BASE', ''))
    parser.add_argument('--shots', default=os.environ.get('CLAB_SHOTS', ''))
    parser.add_argument('--widths', default='1440,760,390')
    args = parser.parse_args()
    if not args.base:
        print('Give the fixture address: --base http://127.0.0.1:9010')
        return 2
    base, shots = args.base.rstrip('/'), args.shots
    if shots:
        os.makedirs(shots, exist_ok=True)
    ids = lab_ids()
    for name in (BGP, SQUARE):
        if name not in ids:
            print(f'The fixture has no lab {name}; start fixture_manager.py on a fresh data directory.')
            return 2
    with sync_playwright() as pw:
        for width in [int(w) for w in args.widths.split(',')]:
            print(f'--- {width} px', flush=True)
            run_width(pw, width, VIEWPORTS.get(width, 800), ids)
    if races:
        print(f'note  {len(races)} page load(s) hit the map-tools load race (see open_map); reloaded and continued', flush=True)
    print('FAILED: ' + ', '.join(failed) if failed else 'all checks passed', flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
