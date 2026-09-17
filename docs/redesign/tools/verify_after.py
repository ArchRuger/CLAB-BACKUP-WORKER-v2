#!/usr/bin/env python3
"""After-redesign browser validation.

Drives the running manager (the fixture manager by default) at three viewports, collects every
console error and page error for the whole run, holds a menu and the device panel open across the
4 s polls, opens each screen and dialog, and writes screenshots plus a JSON report. Any console
error, page error or failed assertion makes the exit status 1.

    CLAB_BASE=http://127.0.0.1:8090 clab-backup-ui/.venv/bin/python docs/redesign/tools/verify_after.py
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shots', 'after'))
VIEWPORTS = [(1920, 1080), (1440, 900), (1366, 768)]
POLL_MS = 4000
TABS = ['topology', 'devices', 'progress', 'tools', 'advanced']
SHOWCASE = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
EMPTY_MAP_LAB = os.environ.get('CLAB_EMPTY_LAB', 'ospf-basics')


class Run:
    def __init__(self, page, tag):
        self.page, self.tag = page, tag
        self.console, self.pageerrors, self.asserts, self.shots, self.notes = [], [], [], [], []
        page.on('console', lambda m: self.console.append({'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.pageerrors.append(str(e)))

    def check(self, name, ok, detail=''):
        self.asserts.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:300]})
        if not ok:
            print(f'  FAIL [{self.tag}] {name}: {detail}', flush=True)

    def shot(self, name, full=False):
        path = os.path.join(OUT, f'{self.tag}-{name}.png')
        self.page.screenshot(path=path, full_page=full)
        self.shots.append(path)

    def js(self, expr, arg=None):
        return self.page.evaluate(expr, arg)

    def open_lab(self, name):
        card = self.page.locator(f'article.lab-card:has(h3:text-is("{name}")) button[data-lab]').first
        if card.count() == 0:
            # A single lab shows only the Continue card
            card = self.page.locator('#home-continue button[data-lab]').first
        card.click()
        self.page.wait_for_selector('#lab-content:not([hidden])', timeout=10000)
        self.page.wait_for_function('() => document.getElementById("title").textContent.trim().length > 0')

    def tab(self, name):
        self.page.click(f'#tab-{name}')
        self.page.wait_for_selector(f'#{name}-view:not([hidden])', timeout=5000)


def home(r):
    p = r.page
    p.goto(BASE + '/')
    p.wait_for_selector('article.lab-card, #empty:not([hidden])', timeout=20000)
    cards = r.js('() => [...document.querySelectorAll("article.lab-card")].map(a => ({name: a.querySelector("h3").textContent, pill: a.querySelector(".pill").textContent, continued: a.classList.contains("continue")}))')
    r.check('home: lab cards render', len(cards) >= 1, cards)
    r.check('home: skeleton hidden after load', r.js('() => document.getElementById("home-skeleton").hidden'))
    r.check('home: no VM banner when the VM is connected', r.js('() => document.getElementById("home-vm-banner").hidden'))
    r.check('home: other labs on the VM listed', not r.js('() => document.getElementById("home-discovered").hidden'))
    r.check('home: no raw deployment words in pills', not any(c['pill'] in ('Unlinked', 'Not deployed', 'Partially running') for c in cards), cards)
    # Manager menu open across a poll
    p.click('#manager-button')
    p.wait_for_selector('#manager-menu-list:not([hidden])')
    time.sleep(POLL_MS / 1000 + 0.5)
    r.check('home: Manager menu survives a poll', r.js('() => !document.getElementById("manager-menu-list").hidden && document.activeElement?.closest("#manager-menu-list") !== null'))
    r.shot('01-home-manager-menu')
    p.keyboard.press('Escape')
    r.check('home: Escape closes the Manager menu and returns focus', r.js('() => document.getElementById("manager-menu-list").hidden && document.activeElement?.id === "manager-button"'))
    r.shot('00-home')


def topology(r):
    p = r.page
    r.open_lab(SHOWCASE)
    p.wait_for_selector('#topology-map [data-map-node]', timeout=15000)
    info = r.js('''() => {
      const map = document.getElementById('topology-map'), rect = map.getBoundingClientRect();
      const states = {};
      for (const g of map.querySelectorAll('.map-device')) for (const c of g.classList) if (c.startsWith('state-')) states[c] = (states[c] || 0) + 1;
      const bg = map.querySelector('.topology-bg');
      return {bottom: rect.bottom, inner: innerHeight, states, dots: map.querySelectorAll('.device-state-dot').length,
              glyphs: map.querySelectorAll('.device-state-glyph').length, bgFill: bg && bg.getAttribute('fill'),
              status: document.getElementById('map-status').textContent, notes: document.getElementById('map-notes').hidden,
              hint: document.querySelector('.topology-hint').textContent, banner: document.getElementById('lab-banner').hidden,
              labels: [...map.querySelectorAll('[data-map-node]')].map(g => g.getAttribute('aria-label')).slice(0, 20),
              title: document.getElementById('title').textContent, pill: document.getElementById('lab-state').textContent, ready: document.getElementById('lab-ready').textContent};
    }''')
    r.notes.append({'topology': info})
    r.check('topology: map fits the viewport', info['bottom'] <= info['inner'] + 0.5, f"bottom {info['bottom']} inner {info['inner']} banner hidden={info['banner']}")
    r.check('topology: every drawn device has one state dot and glyph group', info['dots'] == info['glyphs'] and info['dots'] >= 1, info)
    r.check('topology: ready, starting and attention states are all shown', all(k in info['states'] for k in ('state-ready', 'state-starting', 'state-attention')), info['states'])
    r.check('topology: imported background colour is kept', info['bgFill'] and info['bgFill'].startswith('#'), info['bgFill'])
    r.check('topology: caption in student words', info['status'].endswith('links') or ' link' in info['status'], info['status'])
    r.check('topology: notes expander shown', info['notes'] is False)
    r.check('topology: aria-labels carry the state when not ready', any(' · ' in (l or '') for l in info['labels']), info['labels'])
    r.check('topology: header pill uses the student vocabulary', info['pill'] in ('Running', 'Starting', 'Needs attention'), info['pill'])
    r.shot('10-topology')
    # Context menu on a starting device: inline reasons, order, keyboard
    node = p.locator('#topology-map [data-map-node$="-PE1"]').first
    node.click(button='right')
    p.wait_for_selector('#node-context-menu:not([hidden])')
    menu = r.js('''() => { const m = document.getElementById('node-context-menu');
      return {items: [...m.querySelectorAll('[role=menuitem]')].map(b => ({text: b.textContent.trim().slice(0, 80), disabled: b.disabled, reason: b.querySelector('small')?.textContent})),
              header: m.querySelector('.context-node-name')?.textContent, focused: document.activeElement?.closest('#node-context-menu') !== null}; }''')
    r.check('menu: order CLI, capture, backup, details', [i['text'].split(' ')[0] for i in menu['items']] == ['Open', 'Capture', 'Back', 'Device'], menu)
    r.check('menu: a starting device explains why the CLI is unavailable', menu['items'][0]['disabled'] and 'still starting' in (menu['items'][0]['reason'] or ''), menu['items'][0])
    r.check('menu: header shows the state, not the address', 'Starting' in (menu['header'] or '') and '172.' not in (menu['header'] or ''), menu['header'])
    r.check('menu: focus moves into the menu', menu['focused'])
    r.shot('11-topology-context-menu')
    time.sleep(POLL_MS / 1000 + 0.5)
    r.check('menu: the context menu survives a poll', not r.js('() => document.getElementById("node-context-menu").hidden'))
    p.keyboard.press('Escape')
    r.check('menu: Escape closes it and focus returns to the device', r.js('() => document.getElementById("node-context-menu").hidden && document.activeElement?.dataset.mapNode?.endsWith("-PE1") === true'))
    p.keyboard.press('Shift+F10')
    r.check('menu: Shift+F10 opens it from the keyboard', not r.js('() => document.getElementById("node-context-menu").hidden'))
    p.keyboard.press('Escape')
    # Expand / collapse
    p.click('#map-expand')
    r.check('topology: Expand toggles the label', r.js('() => document.getElementById("map-expand").textContent') == 'Close expanded map')
    r.shot('12-topology-expanded')
    p.keyboard.press('Escape')
    r.check('topology: Escape closes the expanded map', r.js('() => !document.getElementById("topology-view").classList.contains("map-expanded") && document.getElementById("map-expand").textContent === "Expand"'))
    # Drawer for the device with a failed login, opened from the map
    p.locator('#topology-map [data-map-node$="-GTW-2"]').first.click()
    p.wait_for_selector('#details-dialog[open]')
    drawer = r.js('''() => ({title: document.getElementById('details-title').textContent, pill: document.getElementById('details-state').textContent,
      status: document.getElementById('details-status-text').textContent,
      actions: [...document.querySelectorAll('#details-status-actions button')].map(b => b.textContent.trim()),
      primary: [...document.querySelectorAll('#details-actions button')].map(b => ({text: b.textContent.trim(), disabled: b.disabled})),
      advanced: [...document.querySelectorAll('#details-advanced-actions button')].map(b => b.textContent.trim()),
      focusInside: document.activeElement?.closest('#details-dialog') !== null, hash: location.hash})''')
    r.check('drawer: attention state with Check credentials and Test login now', drawer['pill'] == 'Needs attention' and drawer['actions'] == ['Check credentials', 'Test login now'], drawer)
    r.check('drawer: Open CLI is the first action', drawer['primary'] and drawer['primary'][0]['text'].startswith('Open CLI'), drawer['primary'])
    r.check('drawer: route carries the device', 'device=' in drawer['hash'], drawer['hash'])
    r.shot('13-device-drawer-attention')
    time.sleep(POLL_MS / 1000 + 0.5)
    r.check('drawer: stays open across a poll', r.js('() => document.getElementById("details-dialog").open'))
    p.click('#details-next')
    r.check('drawer: Next device moves on', r.js('() => document.getElementById("details-title").textContent') != drawer['title'])
    p.keyboard.press('Escape')
    try:
        p.wait_for_function('() => !document.getElementById("details-dialog").open && !location.hash.includes("device=")', timeout=3000)
        r.check('drawer: Escape closes it and clears the route', True)
    except Exception as exc:
        r.check('drawer: Escape closes it and clears the route', False, repr(exc))
    # Devices tab
    r.tab('devices')
    rows = r.js('() => [...document.querySelectorAll("#device-list .device-row")].map(li => ({pill: li.querySelector(".pill").textContent, reason: li.querySelector(".row-reason")?.textContent, cli: li.querySelector("[data-terminal]").disabled}))')
    r.check('devices: every row has a pill and disabled CLIs carry a reason', all(r_['pill'] and (not r_['cli'] or r_['reason']) for r_ in rows), rows[:4])
    r.check('devices: no address in the simple rows', r.js('() => !document.querySelector("#device-list .device-meta")'))
    r.shot('20-devices')
    p.click('#devices-technical')
    r.check('devices: technical view shows the table', r.js('() => !document.getElementById("inventory-view").hidden && document.getElementById("devices-technical").getAttribute("aria-pressed") === "true"'))
    r.shot('21-devices-technical')
    p.click('#devices-technical')
    # Map editor and export-sessions dialogs
    r.tab('topology')
    p.click('#map-edit')
    p.wait_for_selector('#op-layout-editor[open]')
    r.check('editor: titled Edit lab map with student copy', r.js('() => document.querySelector("#op-layout-editor h2").textContent === "Edit lab map" && !!document.getElementById("op-layout-save") && document.getElementById("op-layout-save").textContent === "Save map"'))
    r.check('editor: no state dots on the editing canvas', r.js('() => [...document.querySelectorAll("#op-layout-map .device-state-dot")].every(c => getComputedStyle(c).display === "none")'))
    r.shot('14-map-editor')
    p.click('#diagram-cancel')
    r.check('editor: closes without changes', r.js('() => !document.getElementById("op-layout-editor").open'))
    p.click('#map-more-button')
    p.click('#import-map')
    p.wait_for_selector('#map-dialog[open]')
    r.check('import map dialog: student copy', r.js('() => document.querySelector("#map-dialog h2").textContent === "Import the lab map" && document.getElementById("map-annotations").required'))
    r.shot('15-import-map-dialog')
    p.click('#cancel-map')


def empty_map(r):
    p = r.page
    p.click('#crumb-home')
    p.wait_for_selector('#home:not([hidden])')
    r.open_lab(EMPTY_MAP_LAB)
    p.wait_for_selector('#map-empty:not([hidden])', timeout=10000)
    info = r.js('''() => ({empty: !document.getElementById('map-empty').hidden, svg: document.getElementById('topology-map').hidden,
      tools: ['map-fit','map-in','map-out','map-expand','map-edit'].map(id => document.getElementById(id).disabled),
      menuEdit: document.getElementById('menu-map-edit').disabled, status: document.getElementById('map-status').textContent,
      banner: document.getElementById('lab-banner-text').textContent, bannerHidden: document.getElementById('lab-banner').hidden,
      pill: document.getElementById('lab-state').textContent})''')
    r.check('empty map: state shown, SVG hidden, tools disabled', info['empty'] and info['svg'] and all(info['tools']) and info['menuEdit'], info)
    r.check('empty map: failed operation reads as Needs attention in the banner', (not info['bannerHidden']) and 'did not finish' in info['banner'], info)
    r.shot('16-topology-empty-map')
    p.click('#map-empty-import')
    p.wait_for_selector('#map-dialog[open]')
    r.check('empty map: Import map… opens the import dialog', True)
    p.click('#cancel-map')
    p.click('#banner-dismiss')
    r.check('banner: Dismiss hides the failed operation', r.js('() => document.getElementById("lab-state").textContent') == 'Stopped')


def run_viewport(browser, vw, vh):
    ctx = browser.new_context(viewport={'width': vw, 'height': vh}, device_scale_factor=1)
    page = ctx.new_page()
    r = Run(page, f'{vw}x{vh}')
    for step in (home, topology, empty_map):
        try:
            step(r)
        except Exception as exc:  # keep going: the report shows every failure
            r.check(f'{step.__name__}: completed', False, repr(exc))
            r.shot(f'zz-{step.__name__}-error')
    ctx.close()
    return r


def main():
    os.makedirs(OUT, exist_ok=True)
    report, failed = [], 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for vw, vh in VIEWPORTS:
            r = run_viewport(browser, vw, vh)
            bad = [a for a in r.asserts if not a['ok']]
            failed += len(bad) + len(r.console) + len(r.pageerrors)
            print(f'{r.tag}: {len(r.asserts) - len(bad)}/{len(r.asserts)} checks passed, console errors {len(r.console)}, page errors {len(r.pageerrors)}', flush=True)
            for e in r.console + r.pageerrors:
                print('  console/page error:', e, flush=True)
            report.append({'viewport': r.tag, 'asserts': r.asserts, 'console': r.console, 'pageerrors': r.pageerrors, 'notes': r.notes, 'shots': r.shots})
        browser.close()
    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)
    print('report:', os.path.join(OUT, 'report.json'))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
