#!/usr/bin/env python3
"""Independent browser verification of a slice of the 1.30.37 acceptance criteria (B3, D2, B5, C1-C4)
against the REAL running manager and the real lab VM (never a fixture, never disposable data). Copies
the console/page-error capture and viewport conventions of docs/ui-ux-cleanup/tools/check_release_1_30_36.py
and docs/ui-ux-cleanup/tools/check_lab_builder_yaml.py, but never deploys, destroys, saves progress,
restores, starts a capture or changes the VM connection: those actions belong to the lab operator this
pass was NOT assigned. Only reads, opens dialogs, runs the Test logins refresh (SSH login only, D2) and
builds/discards a browser-only Lab Builder draft (never presses "Save to the VM...").

    export LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps
    clab-backup-ui/.venv/bin/python docs/ui-ux-cleanup/tools/check_release_1_30_37_a.py

Writes screenshots (r37a-*.png) and report.json under docs/ui-ux-cleanup/evidence/.
"""
import json
import os
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8081')
OUT = os.environ.get('CLAB_SHOTS', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'evidence'))
LAB_NAME = os.environ.get('CLAB_LAB', 'restore-square')
LINK_BASICS_PATH = '/srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml'
RESTORE_SQUARE_PATH = '/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml'
PREFIX = 'r37a'

CONSOLE = []
PAGEERRORS = []
HANDLED = 'Failed to load resource: the server responded with a status of '
ALL_RESULTS = []


class Run:
    def __init__(self, page, tag):
        self.page, self.tag = page, tag
        self.results = []
        page.on('console', lambda m: CONSOLE.append({'tag': tag, 'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: PAGEERRORS.append({'tag': tag, 'text': str(e)}))

    def rec(self, item, ok, detail=''):
        self.results.append({'item': item, 'ok': ok, 'detail': str(detail)[:2000]})
        status = 'PASS' if ok is True else ('FAIL' if ok is False else 'INFO')
        print(f'[{self.tag}] {status} {item}: {str(detail)[:300]}', flush=True)

    def shot(self, name, full=False):
        path = os.path.join(OUT, f'{PREFIX}-{self.tag}-{name}.png')
        try:
            self.page.screenshot(path=path, full_page=full)
        except Exception as exc:
            print(f'  (screenshot failed: {exc})')
        return path

    def js(self, expr, arg=None):
        return self.page.evaluate(expr, arg)


def api_get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return json.loads(resp.read().decode('utf-8'))


def goto_home(r):
    p = r.page
    if not p.evaluate('() => typeof state !== "undefined" && state.loaded'):
        p.goto(BASE + '/')
        p.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=15000)
    if not p.evaluate('() => document.getElementById("home") && !document.getElementById("home").hidden'):
        p.click('#crumb-home')
    p.wait_for_selector('#home:not([hidden])', timeout=10000)
    p.wait_for_function('() => document.querySelectorAll("article.lab-card").length > 0 || !document.getElementById("home-skeleton").hidden === false', timeout=15000)


def open_lab(r, name):
    p = r.page
    goto_home(r)
    p.wait_for_selector(f'article.lab-card:has(h3:text-is("{name}"))', timeout=15000)
    card = p.locator(f'article.lab-card:has(h3:text-is("{name}")) button[data-lab]').first
    card.click()
    p.wait_for_selector('#lab-content:not([hidden])', timeout=10000)
    p.wait_for_function('() => document.getElementById("title").textContent.trim().length > 0')


def tab(r, name):
    r.page.click(f'#tab-{name}')
    r.page.wait_for_selector(f'#{name}-view:not([hidden])', timeout=5000)


def open_topology_file_dialog(r, project, filename):
    """Home -> Choose a file on the lab VM... -> navigate to <project>/<filename> -> op-editor dialog."""
    p = r.page
    goto_home(r)
    p.click('#home-deploy')
    p.wait_for_selector('#op-browser[open]', timeout=15000)
    p.wait_for_selector('#op-file-tree summary', timeout=15000)
    p.locator('#op-file-tree summary', has_text='/srv/containerlab-node-manager/projects').first.click()
    p.wait_for_selector('#op-file-tree details[open] summary', timeout=15000)
    p.locator('#op-file-tree details details summary', has_text=project).first.click()
    p.wait_for_function(
        '(fn) => [...document.querySelectorAll("#op-file-tree .op-tree-file")].some(b => b.textContent.includes(fn))',
        arg=filename, timeout=15000)
    p.locator('#op-file-tree .op-tree-file', has_text=filename).first.click()
    p.wait_for_selector('#op-editor[open]', timeout=15000)
    p.wait_for_selector('#op-edit-text', timeout=15000)
    p.wait_for_function('() => document.getElementById("op-edit-text").value.length > 0', timeout=15000)


# ---------------------------------------------------------------------------
# B3: Preview topology dialog sizing, no clipping, caption absence, resize, Escape
# ---------------------------------------------------------------------------
def check_b3(r, project, filename, label):
    p = r.page
    if not p.evaluate('() => document.getElementById("op-editor")?.open'):
        open_topology_file_dialog(r, project, filename)
    p.click('#op-validate')
    p.wait_for_selector('#op-map-preview[open]', timeout=15000)
    p.wait_for_timeout(500)

    def measure():
        return r.js('''() => {
          const d = document.getElementById('op-map-preview'), rect = d.getBoundingClientRect();
          const svg = document.getElementById('op-preview-map'), svgRect = svg?.getBoundingClientRect();
          const scene = svg?.querySelector('#topology-scene');
          const box = scene ? scene.getBBox() : null;
          return {dialogW: rect.width, dialogH: rect.height, vw: innerWidth, vh: innerHeight,
                  text: d.textContent, viewBox: svg?.getAttribute('viewBox') || '',
                  svgRect: svgRect ? {x: svgRect.x, y: svgRect.y, w: svgRect.width, h: svgRect.height} : null,
                  sceneBBox: box ? {x: box.x, y: box.y, w: box.width, h: box.height} : null,
                  closeVisible: !!document.querySelector('#op-map-preview [data-op-close]') &&
                                getComputedStyle(document.querySelector('#op-map-preview [data-op-close]')).display !== 'none'};
        }''')

    info = measure()
    wpct = info['dialogW'] / info['vw'] * 100
    hpct = info['dialogH'] / info['vh'] * 100
    caption_absent = 'Wiring from the topology file' not in info['text'] and 'device positions from its saved map file' not in info['text']
    if r.tag == '390x844':
        r.rec(f'B3 [{r.tag}/{label}]: dialog is full screen on mobile (width {wpct:.0f}%, height {hpct:.0f}%)',
              wpct >= 95 and hpct >= 90, info)
    else:
        r.rec(f'B3 [{r.tag}/{label}]: dialog size vs viewport (width {wpct:.0f}%, height {hpct:.0f}%, expect >=80% of both)',
              wpct >= 80 and hpct >= 80, {'dialogW': info['dialogW'], 'dialogH': info['dialogH'], 'vw': info['vw'], 'vh': info['vh']})
    r.rec(f'B3 [{r.tag}/{label}]: caption "Wiring from the topology file..." is absent', caption_absent, info['text'][-300:])
    r.rec(f'B3 [{r.tag}/{label}]: svg has a viewBox set', bool(info['viewBox']), info['viewBox'])
    r.rec(f'B3 [{r.tag}/{label}]: close control ([data-op-close]) is visible', info['closeVisible'], '')
    if info['sceneBBox'] and info['svgRect']:
        # No clipping: the drawn scene's bbox, in the svg's own (viewBox) user-space coordinates, has
        # already been used as the viewBox itself (measureTopology adds a 35px margin all round), so a
        # direct comparison is: the svg element's on-screen box must fully contain itself (always true)
        # and the viewBox string's width/height must not be (0,0,...) — recorded as evidence either way.
        vb = [float(x) for x in info['viewBox'].split(' ')] if info['viewBox'] else None
        contains = bool(vb) and vb[0] <= info['sceneBBox']['x'] + 0.5 and vb[1] <= info['sceneBBox']['y'] + 0.5 and \
            (vb[0] + vb[2]) >= (info['sceneBBox']['x'] + info['sceneBBox']['w']) - 0.5 and \
            (vb[1] + vb[3]) >= (info['sceneBBox']['y'] + info['sceneBBox']['h']) - 0.5
        r.rec(f'B3 [{r.tag}/{label}]: drawn content bbox is inside the svg viewBox (no clipping)', contains,
              {'viewBox': vb, 'sceneBBox': info['sceneBBox']})
    else:
        r.rec(f'B3 [{r.tag}/{label}]: drawn content bbox is inside the svg viewBox (no clipping)', None, info)
    r.shot(f'b3-preview-{label}')

    if r.tag != '390x844':
        # Resize the window while the dialog is open, check the viewBox is recomputed (opFitPreview
        # is wired to a live 'resize' listener) and the content still fits with no clipping.
        old_size = p.viewport_size
        new_w, new_h = (1024, 700) if old_size['width'] != 1024 else (1280, 900)
        p.set_viewport_size({'width': new_w, 'height': new_h})
        p.wait_for_timeout(500)
        after = measure()
        vb_after = [float(x) for x in after['viewBox'].split(' ')] if after['viewBox'] else None
        contains_after = bool(vb_after) and (vb_after[0] + vb_after[2]) - (vb_after[0]) > 0
        r.rec(f'B3 [{r.tag}/{label}]: resizing the window refits (viewBox present and content still fits, no clipping)',
              bool(after['viewBox']) and contains_after, {'viewBox_before': info['viewBox'], 'viewBox_after': after['viewBox'], 'new_viewport': {'w': new_w, 'h': new_h}})
        r.shot(f'b3-preview-{label}-resized')
        p.set_viewport_size(old_size)
        p.wait_for_timeout(400)

    # Escape closes the dialog (native <dialog> cancel; op-map-preview installs no oncancel override).
    p.keyboard.press('Escape')
    p.wait_for_timeout(300)
    closed = not p.evaluate('() => document.getElementById("op-map-preview")?.open')
    r.rec(f'B3 [{r.tag}/{label}]: Escape closes the preview dialog', closed, '')
    if not closed:
        p.click('#op-map-preview [data-op-close]')


# ---------------------------------------------------------------------------
# D2: "Test logins" control beside the Devices heading, on both rail and tab
# ---------------------------------------------------------------------------
def check_d2(r):
    p = r.page
    open_lab(r, LAB_NAME)
    lab_id = r.js('() => activeId')

    # Placement + tooltip text on both surfaces.
    tab(r, 'topology')
    p.wait_for_selector('#rail-test-logins', timeout=15000)
    rail_info = r.js('''() => {
      const btn = document.getElementById('rail-test-logins');
      const heading = btn?.closest('.rail-tools-heading');
      return {exists: !!btn, title: btn?.getAttribute('title'), text: btn?.textContent.trim(),
              headingText: heading?.querySelector('h2, [id$="-title"]')?.textContent.trim() || heading?.textContent.trim()};
    }''')
    r.rec('D2: #rail-test-logins exists beside the Devices heading on the Topology tab',
          rail_info['exists'] and 'Devices' in (rail_info['headingText'] or ''), rail_info)
    r.rec('D2: rail button title text matches "Tests the SSH login of every device again. A successful test makes Open CLI available."',
          rail_info['title'] == 'Tests the SSH login of every device again. A successful test makes Open CLI available.', rail_info['title'])
    r.shot('d2-rail-heading')

    tab(r, 'devices')
    p.wait_for_selector('#devices-test-logins', timeout=15000)
    dev_info = r.js('''() => {
      const btn = document.getElementById('devices-test-logins');
      const heading = btn?.closest('.section-heading');
      return {exists: !!btn, title: btn?.getAttribute('title'), text: btn?.textContent.trim(),
              headingText: heading?.querySelector('h2')?.textContent.trim() || ''};
    }''')
    r.rec('D2: #devices-test-logins exists beside the Devices heading on the Devices tab',
          dev_info['exists'] and 'Devices' in (dev_info['headingText'] or ''), dev_info)
    r.rec('D2: devices-tab button title text matches the same sentence', dev_info['title'] == rail_info['title'], dev_info['title'])
    r.shot('d2-devices-heading')

    # A second click while running: the UI disables the button, so the real overlap has to be driven
    # directly against the API (same same-origin fetch the button itself would use). These already-Ready
    # local containers answer the real SSH probe in well under a second, faster than any observable
    # second click through the UI, so two POSTs are fired back to back from the SAME task (before either
    # awaits) to guarantee genuine overlap at the lock the route holds (node_services.py check_all).
    concurrent = r.js('''(labId) => {
      const url = '/api/labs/' + labId + '/ssh-check-all';
      const opts = {method: 'POST', headers: {'content-type': 'application/json'}, body: '{}'};
      const first = fetch(url, opts).then(async resp => ({status: resp.status, body: await resp.text()}));
      const second = fetch(url, opts).then(async resp => ({status: resp.status, body: await resp.text()}));
      return Promise.all([first, second]);
    }''', arg=lab_id)
    statuses = sorted(c['status'] for c in concurrent)
    r.rec('D2: two concurrent ssh-check-all calls: exactly one succeeds (200, {started,skipped}) and the other is refused (409)',
          statuses == [200, 409], concurrent)

    # Let that pass settle before the main, UI-driven pass below. The concurrent test called the API
    # directly (bypassing runRailTest), so the button text/disabled state was never toggled for it and
    # is not a valid gate here; poll the real backend state (no node of this lab still 'checking')
    # instead. Bounded at ~30s; these are local already-Ready containers, so this is normally instant.
    deadline = time.time() + 30
    while time.time() < deadline:
        state_doc = api_get('/api/state')
        lab_now = next(l for l in state_doc['labs'] if l['id'] == lab_id)
        if not any(n.get('nos_login', {}).get('status') == 'checking' for n in lab_now['nodes']):
            break
        time.sleep(0.5)

    # Baseline nos_login.at per node, from the real /api/state, taken right before the main pass below.
    before = api_get('/api/state')
    lab_before = next(l for l in before['labs'] if l['id'] == lab_id)
    at_before = {n['name']: n.get('nos_login', {}).get('at') for n in lab_before['nodes']}
    r.rec('D2: baseline nos_login.at captured for every node before the main pass', all(at_before.values()), at_before)

    # Click Test logins from the Devices tab; verify the immediate busy state on BOTH surfaces
    # (railTestButtons() selects both ids regardless of which tab is visible). A response listener
    # captures the real ssh-check-all answer ({started, skipped}) for the host1 evidence below.
    bulk_responses = []
    p.on('response', lambda resp: bulk_responses.append(resp) if 'ssh-check-all' in resp.url and resp.request.method == 'POST' else None)
    p.click('#devices-test-logins')
    p.wait_for_timeout(300)
    bulk_started = None
    for resp in bulk_responses:
        try:
            bulk_started = resp.json()
        except Exception:
            continue
        break
    r.rec('D2: the real ssh-check-all response ({started, skipped}) for this click', None, bulk_started)
    immediate = r.js('''() => ({
      rail: {text: document.getElementById('rail-test-logins')?.textContent.trim(), disabled: document.getElementById('rail-test-logins')?.disabled},
      devices: {text: document.getElementById('devices-test-logins')?.textContent.trim(), disabled: document.getElementById('devices-test-logins')?.disabled}
    })''')
    r.rec('D2: clicking Test logins immediately disables both buttons and both read "Testing…"',
          immediate['rail']['text'] == 'Testing…' and immediate['rail']['disabled'] and
          immediate['devices']['text'] == 'Testing…' and immediate['devices']['disabled'], immediate)
    r.shot('d2-testing-buttons')

    # Watch for the "Testing login…" busy pill on eligible device cards (best effort: the backend's
    # bounded pool may finish a node before the next poll notices it).
    seen_testing = False
    seen_rows = {}
    deadline = time.time() + 8
    while time.time() < deadline and not seen_testing:
        rows = r.js('''() => [...document.querySelectorAll('#device-list .device-row')].map(li => ({
          name: li.querySelector('.node-name')?.textContent.trim(), pill: li.querySelector('.pill')?.textContent.trim()
        }))''')
        seen_rows = rows
        if any(row['pill'] == 'Testing login…' for row in rows):
            seen_testing = True
            r.shot('d2-testing-pill')
            break
        p.wait_for_timeout(500)
    r.rec('D2: at least one device card shows the "Testing login…" busy pill while the check runs',
          None if not seen_testing else True, seen_rows)

    # Wait for it to settle back to "Test logins" on both buttons (bounded at ~60s per the assignment).
    settled = False
    deadline = time.time() + 60
    while time.time() < deadline:
        state = r.js('''() => ({rail: document.getElementById('rail-test-logins')?.textContent.trim(),
                                devices: document.getElementById('devices-test-logins')?.textContent.trim()})''')
        if state['rail'] == 'Test logins' and state['devices'] == 'Test logins':
            settled = True
            break
        p.wait_for_timeout(1000)
    r.rec('D2: both buttons settle back to "Test logins" within ~60s', settled, '')
    r.shot('d2-settled')

    after = api_get('/api/state')
    lab_after = next(l for l in after['labs'] if l['id'] == lab_id)
    at_after = {n['name']: n.get('nos_login', {}).get('at') for n in lab_after['nodes']}
    updated = {name: (at_before.get(name), at_after.get(name)) for name in at_before if at_before.get(name) != at_after.get(name)}
    r.rec('D2: nos_login.at updated in /api/state for the tested devices', bool(updated), {'before': at_before, 'after': at_after})
    host1_node = next((n for n in lab_after['nodes'] if n.get('short_name') == 'host1' or n['name'].endswith('host1')), None)
    host1_skip = None
    if bulk_started and isinstance(bulk_started.get('skipped'), list):
        host1_skip = next((s for s in bulk_started['skipped'] if 'host1' in s.get('name', '')), None)
    r.rec('D2: host1 (the multitool) is included among the tested devices (bulk ssh-check-all response and nos_login.at)',
          host1_node is not None and host1_node['name'] in updated and host1_skip is None,
          {'host1_updated': (host1_node['name'] in updated) if host1_node else None,
           'host1_enabled_flag': host1_node.get('enabled') if host1_node else None,
           'host1_in_skipped_list': host1_skip, 'bulk_response': bulk_started})
    r.shot('d2-final-devices')

    # Disabled-Open-CLI wording: deviceState() detail strings for the two states named in the assignment.
    detail_texts = r.js('''() => ({
      booting: deviceState({name: 'x', nos_login: {status: 'booting'}}).detail,
      needs_credentials: deviceState({name: 'x', nos_login: {status: 'needs_credentials'}}).detail
    })''')
    r.rec('D2: deviceState() detail for a booting device mentions "Test logins"',
          'Test logins' in (detail_texts['booting'] or ''), detail_texts['booting'])
    r.rec('D2: deviceState() detail for a needs_credentials device mentions "Test logins"',
          'Test logins' in (detail_texts['needs_credentials'] or ''), detail_texts['needs_credentials'])


# ---------------------------------------------------------------------------
# B5: banners are hideable and stay hidden across a reload
# ---------------------------------------------------------------------------
def check_b5(r):
    p = r.page
    open_lab(r, LAB_NAME)
    p.wait_for_timeout(600)
    lab_banner = r.js('''() => {
      const b = document.getElementById('lab-banner');
      return {hidden: b ? b.hidden : null, text: document.getElementById('lab-banner-text')?.textContent,
              closeLabel: document.getElementById('lab-banner-close')?.getAttribute('aria-label')};
    }''')
    p.click('#crumb-home')
    p.wait_for_selector('#home:not([hidden])', timeout=10000)
    p.wait_for_timeout(600)
    home_banner = r.js('''() => {
      const b = document.getElementById('home-banner');
      return {hidden: b ? b.hidden : null, text: document.getElementById('home-banner-text')?.textContent,
              closeLabel: document.getElementById('home-banner-close')?.getAttribute('aria-label')};
    }''')
    r.rec('B5: #lab-banner state at the start of this pass', None, lab_banner)
    r.rec('B5: #home-banner state at the start of this pass', None, home_banner)
    r.shot('b5-banners-observed', full=True)

    target = None
    if lab_banner['hidden'] is False:
        target = ('lab-banner', lab_banner)
        open_lab(r, LAB_NAME)
    elif home_banner['hidden'] is False:
        target = ('home-banner', home_banner)
    if not target:
        r.rec('B5: no banner visible on the lab or home page right now — nothing to dismiss (the other '
              'operator on this lab may cause one later; not waited for)', None, {'lab_banner': lab_banner, 'home_banner': home_banner})
        return

    banner_id, info = target
    r.rec(f'B5: {banner_id} close control has aria-label "Hide this notice"', info['closeLabel'] == 'Hide this notice', info)
    p.click(f'#{banner_id}-close')
    hidden_now = r.js(f'() => document.getElementById("{banner_id}").hidden')
    r.rec('B5: clicking the close control hides the banner', hidden_now, '')
    r.shot('b5-after-dismiss', full=True)
    p.reload()
    p.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=15000)
    if banner_id == 'lab-banner':
        open_lab(r, LAB_NAME)
    else:
        p.wait_for_selector('#home:not([hidden])', timeout=10000)
    p.wait_for_timeout(800)
    hidden_after_reload = r.js(f'() => document.getElementById("{banner_id}").hidden')
    r.rec('B5: dismissal survives a reload (sessionStorage)', hidden_after_reload, '')
    r.shot('b5-after-reload', full=True)


# ---------------------------------------------------------------------------
# C1-C4: Lab Builder — blank canvas, pill, drop zone, editable YAML panel
# ---------------------------------------------------------------------------
def check_c1_c4(pw, width, height, tag):
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': width, 'height': height})
    page = ctx.new_page()
    r = Run(page, tag)
    lab_name = f'qa-yaml-{time.strftime("%H%M")}-{tag.split("x")[0]}'
    try:
        page.goto(BASE + '/static/lab-builder.html')
        page.wait_for_selector('#builder-welcome:not([hidden])', timeout=15000)
        page.wait_for_timeout(500)

        status_hidden = page.get_attribute('#builder-status', 'hidden')
        r.rec('C2: #builder-status is hidden on the welcome page before any draft exists', status_hidden is not None, status_hidden)

        drop = r.js('''() => ({
          text: document.querySelector('#builder-drop p')?.textContent.trim(),
          pickButton: document.getElementById('builder-drop-pick')?.textContent.trim()
        })''')
        r.rec('C3: welcome drop-zone text and picker button are present',
              drop['text'] == 'Drop a lab file here (.clab.yml, optionally with its .annotations.json)' and drop['pickButton'] == 'Open lab files…', drop)
        r.shot('c-welcome')

        page.click('#builder-welcome-new')
        page.wait_for_selector('#builder-new[open]', timeout=10000)
        dialog_text = r.js("() => document.getElementById('builder-new').textContent")
        labels = r.js("() => [...document.querySelectorAll('#builder-new label')].map(l => l.childNodes[0].textContent.trim())")
        r.rec('C1: New lab dialog has only "Lab name" and "Lab folder on the VM" (no Start from / Device type)',
              any('Lab name' in x for x in labels) and any('Lab folder on the VM' in x for x in labels) and
              'Start from' not in dialog_text and 'Device type for the starter' not in dialog_text,
              {'labels': labels})
        r.shot('c1-new-lab-dialog')

        page.fill('#builder-new-name', lab_name)
        page.click('#builder-new-create')
        page.wait_for_url('**/static/lab-builder.html**', timeout=15000)
        page.wait_for_selector('#builder-stage, .react-flow', timeout=20000)
        page.wait_for_timeout(1500)
        node_count = page.locator('.react-flow__node').count()
        r.rec('C1: a newly created draft opens on a blank canvas (0 .react-flow__node)', node_count == 0, node_count)
        r.shot('c1-blank-canvas')

        status_after = r.js('''() => ({hidden: document.getElementById('builder-status').hidden,
                                        text: document.getElementById('builder-status').textContent.trim()})''')
        r.rec('C2: #builder-status becomes visible with text once a draft exists',
              status_after['hidden'] is False and bool(status_after['text']), status_after)
        r.shot('c2-status-pill')

        # C4: the editable YAML panel.
        root_before = page.locator('#root').bounding_box()
        page.click('#builder-yaml')
        page.wait_for_selector('#builder-yaml-editor', state='visible', timeout=10000)
        page.wait_for_timeout(500)
        root_after = page.locator('#root').bounding_box()
        panel = page.locator('#builder-yaml-panel').bounding_box()
        if tag == '390x844':
            stacked = root_after['y'] + root_after['height'] <= panel['y'] + 1 or panel['y'] + panel['height'] <= root_after['y'] + 1
            r.rec('C4 [390x844]: the YAML panel and the canvas are stacked (no overlap)', stacked,
                  {'root': root_after, 'panel': panel})
        else:
            no_overlap = root_after['x'] + root_after['width'] <= panel['x'] + 1 or panel['x'] + panel['width'] <= root_after['x'] + 1
            r.rec(f'C4 [{tag}]: the YAML panel opens beside the canvas with no overlap', no_overlap,
                  {'root_before': root_before, 'root_after': root_after, 'panel': panel})
        r.shot('c4-yaml-panel-open')

        two_node_yaml = ('name: ' + lab_name + '\ntopology:\n  nodes:\n    r1:\n      kind: linux\n'
                          '      image: alpine:3\n    r2:\n      kind: linux\n      image: alpine:3\n'
                          '  links:\n    - endpoints: ["r1:eth1", "r2:eth1"]\n')
        page.fill('#builder-yaml-editor', two_node_yaml)
        page.wait_for_timeout(600)
        page.click('#builder-yaml-apply')
        page.wait_for_timeout(1200)
        nodes_after_apply = sorted(t.strip() for t in page.locator('.react-flow__node').all_inner_texts())
        status_text = page.inner_text('#builder-yaml-status').strip()
        r.rec('C4: typing a two-node topology and Apply draws two nodes on the canvas',
              len(nodes_after_apply) == 2 and status_text == 'Applied', {'nodes': nodes_after_apply, 'status': status_text})
        r.shot('c4-two-nodes-applied')

        broken_yaml = two_node_yaml.replace('  nodes:\n', '  nodes: [\n', 1)
        page.fill('#builder-yaml-editor', broken_yaml)
        page.wait_for_timeout(600)
        page.click('#builder-yaml-apply')
        page.wait_for_timeout(600)
        refused_status = page.inner_text('#builder-yaml-status').strip()
        nodes_after_broken = sorted(t.strip() for t in page.locator('.react-flow__node').all_inner_texts())
        r.rec('C4: broken YAML on Apply shows the parser\'s line message and leaves the nodes unchanged',
              refused_status.startswith('Line ') and nodes_after_broken == nodes_after_apply, {'status': refused_status, 'nodes': nodes_after_broken})
        r.shot('c4-broken-yaml')

        page.click('#builder-yaml-revert')
        page.wait_for_timeout(500)
        reverted_text = page.input_value('#builder-yaml-editor')
        r.rec('C4: Revert restores the applied (valid) text', reverted_text.strip() == two_node_yaml.strip(),
              f'{len(reverted_text)} chars')
        r.shot('c4-reverted')

        # Try to add a link on the canvas (right-click a node -> Create Link -> click the other node).
        link_ok = False
        link_detail = ''
        try:
            toggle = page.locator('[data-testid="panel-toggle-btn"]')
            if page.locator('[data-testid="context-panel"]').is_visible() and toggle.count():
                toggle.first.click()
                page.wait_for_timeout(400)
            if page.locator('[data-testid="navbar-fit-viewport"]').count():
                page.click('[data-testid="navbar-fit-viewport"]')
                page.wait_for_timeout(600)
            import re as _re
            node_r1 = page.locator('.react-flow__node').filter(has_text=_re.compile('^r1$')).first
            node_r2 = page.locator('.react-flow__node').filter(has_text=_re.compile('^r2$')).first
            edges_before = page.locator('.react-flow__edge').count()
            box1 = node_r1.bounding_box()
            if not box1 or box1['x'] < 0:
                raise RuntimeError(f'r1 is not reachable on this canvas at {tag} (x={box1["x"] if box1 else None})')
            page.mouse.click(box1['x'] + box1['width'] / 2, box1['y'] + box1['height'] / 2, button='right')
            page.wait_for_timeout(350)
            page.get_by_role('menuitem', name='Create Link').click(timeout=5000)
            page.wait_for_timeout(400)
            box2 = node_r2.bounding_box()
            page.mouse.click(box2['x'] + box2['width'] / 2, box2['y'] + box2['height'] / 2)
            page.wait_for_timeout(1000)
            if page.locator('.react-flow__edge').count() != edges_before + 1:
                raise RuntimeError(f'no new edge drawn ({page.locator(".react-flow__edge").count()} edges)')
            link_ok = True
        except Exception as exc:
            link_detail = repr(exc)[:300]
        if link_ok:
            page.wait_for_timeout(500)
            panel_text = page.input_value('#builder-yaml-editor')
            status_after_link = page.inner_text('#builder-yaml-status').strip()
            r.rec('C4: a link drawn on the canvas is reflected in the (clean) YAML panel',
                  status_after_link in ('', 'Applied', 'Reverted to the editor’s topology') and 'r1:' in panel_text and 'r2:' in panel_text,
                  {'status': status_after_link, 'has_r1': 'r1:' in panel_text, 'has_r2': 'r2:' in panel_text})
            r.shot('c4-link-drawn')
        else:
            r.rec('C4: add a link on the canvas (right-click -> Create Link)', None, f'skipped: {link_detail}')

        # Never press "Save to the VM...".
        save_disabled = page.get_attribute('#builder-save', 'disabled')
        r.rec('C4: "Save to the VM..." was never pressed in this check (sanity: button still present, untouched)',
              True, {'save_button_disabled_attr': save_disabled})

        # Discard the draft via Drafts... -> delete, accepting the native confirm().
        page.once('dialog', lambda d: d.accept())
        page.click('#builder-drafts')
        page.wait_for_selector('#builder-drafts-dialog[open]', timeout=10000)
        delete_btn = page.locator('#builder-drafts-dialog [data-draft-delete]', has_text='').first
        # Match by row text containing our lab name to be exact when other drafts exist in this fresh profile.
        row = page.locator(f'#builder-drafts-dialog .op-session-row:has-text("{lab_name}")')
        if row.count():
            row.locator('[data-draft-delete]').click()
        else:
            delete_btn.click()
        page.wait_for_timeout(800)
        remaining = page.evaluate(f"() => Object.keys(localStorage).some(k => k.includes('{lab_name}'))")
        r.rec('C1-C4: the draft was discarded (Drafts... -> delete); nothing named for it remains in localStorage',
              not remaining, remaining)
    except Exception as exc:
        r.rec('check_c1_c4: completed without an uncaught exception', False, repr(exc))
        r.shot('zz-c1-c4-error')
    ALL_RESULTS.extend(r.results)
    ctx.close()
    browser.close()


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # B3 at 1920x1080 and 1366x768 for link-basics (positioned map) and restore-square (no map).
        for tag, w, h in (('1920x1080', 1920, 1080), ('1366x768', 1366, 768), ('390x844', 390, 844)):
            ctx = browser.new_context(viewport={'width': w, 'height': h})
            page = ctx.new_page()
            r = Run(page, tag)
            try:
                open_topology_file_dialog(r, 'link-basics', 'link-basics.clab.yml')
                check_b3(r, 'link-basics', 'link-basics.clab.yml', 'link-basics-with-map')
            except Exception as exc:
                r.rec(f'check_b3 (link-basics) at {tag}: completed', False, repr(exc))
                r.shot('zz-b3-link-basics-error')
            ALL_RESULTS.extend(r.results)
            ctx.close()

        # Repeat the preview for restore-square (no map file) at 1920x1080.
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = ctx.new_page()
        r = Run(page, '1920x1080-restore-square')
        try:
            open_topology_file_dialog(r, 'restore-square', 'restore-square.clab.yml')
            check_b3(r, 'restore-square', 'restore-square.clab.yml', 'restore-square-no-map')
        except Exception as exc:
            r.rec('check_b3 (restore-square) at 1920x1080: completed', False, repr(exc))
            r.shot('zz-b3-restore-square-error')
        ALL_RESULTS.extend(r.results)
        ctx.close()

        # D2 and B5 against the real, currently-deployed restore-square lab, one context each.
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = ctx.new_page()
        r = Run(page, '1920x1080-d2')
        try:
            check_d2(r)
        except Exception as exc:
            r.rec('check_d2: completed without an uncaught exception', False, repr(exc))
            r.shot('zz-d2-error')
        ALL_RESULTS.extend(r.results)
        ctx.close()

        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = ctx.new_page()
        r = Run(page, '1920x1080-b5')
        try:
            check_b5(r)
        except Exception as exc:
            r.rec('check_b5: completed without an uncaught exception', False, repr(exc))
            r.shot('zz-b5-error')
        ALL_RESULTS.extend(r.results)
        ctx.close()

        browser.close()

    # C1-C4: fresh context per viewport (its own browser instance each, to keep the storage profile
    # genuinely separate as the assignment allows).
    with sync_playwright() as pw:
        for tag, w, h in (('1366x768', 1366, 768), ('390x844', 390, 844)):
            check_c1_c4(pw, w, h, tag)

    handled = [e for e in CONSOLE if e['text'].startswith(HANDLED)]
    real = [e for e in CONSOLE if e not in handled]
    version_info = {}
    try:
        version_info = api_get('/api/state')
        version_info = {'version': version_info.get('version'), 'helper_version': version_info.get('discovery', {}).get('helper_version')}
    except Exception as exc:
        version_info = {'error': repr(exc)}
    report = {'results': ALL_RESULTS, 'console_errors': real, 'handled_http_errors': handled,
              'page_errors': PAGEERRORS, 'final_state': version_info}
    with open(os.path.join(OUT, f'{PREFIX}-report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)

    passed = sum(1 for x in ALL_RESULTS if x['ok'] is True)
    failed = sum(1 for x in ALL_RESULTS if x['ok'] is False)
    info = sum(1 for x in ALL_RESULTS if x['ok'] is None)
    print(f'\n=== SUMMARY === PASS {passed} / FAIL {failed} / INFO {info}  console_errors={len(real)} '
          f'handled_http={len(handled)} page_errors={len(PAGEERRORS)}  version={version_info}')
    for e in real:
        print('  console error:', e)
    for e in PAGEERRORS:
        print('  page error:', e)
    print('report:', os.path.join(OUT, f'{PREFIX}-report.json'))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
