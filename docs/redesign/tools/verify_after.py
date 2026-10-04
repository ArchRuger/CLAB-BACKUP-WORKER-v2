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
import re
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8090')
OUT = os.environ.get('CLAB_SHOTS', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shots', 'after'))
VIEWPORTS = [(1920, 1080), (1440, 900), (1366, 768)]
POLL_MS = 4000
TABS = ['topology', 'devices', 'tools', 'advanced']
SHOWCASE = os.environ.get('CLAB_LAB', 'BGP_TheoryToPractice')
EMPTY_MAP_LAB = os.environ.get('CLAB_EMPTY_LAB', 'ospf-basics')
HANDLED = 'Failed to load resource: the server responded with a status of '


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
    r.check('home: Deploy and Build lead the page and the list opens on Recent labs', r.js('() => !document.getElementById("home-start").hidden && document.getElementById("home-tab-recent").getAttribute("aria-selected") === "true" && !document.getElementById("home-continue")'))
    r.check('home: no discovered section on the main page', r.js('() => !document.getElementById("home-discovered")'))
    r.check('home: no raw deployment words in pills', not any(c['pill'] in ('Unlinked', 'Not deployed', 'Partially running') for c in cards), cards)
    # Labs the VM has that are not in My labs live under the Manager menu
    p.click('#manager-button')
    p.wait_for_selector('#manager-menu-list:not([hidden])')
    r.check('manager menu: labs found on the VM are counted', 'not in My labs' in r.js('() => document.getElementById("manager-vm-labs-note").textContent'))
    p.click('#manager-vm-labs')
    p.wait_for_selector('#vm-labs-dialog[open]')
    r.check('labs found on the VM: a lab can be added', r.js('() => document.querySelectorAll("#discovered-labs [data-setup-name]").length') >= 1)
    r.shot('home-vm-labs-dialog')
    p.click('#vm-labs-dialog .dialog-actions [data-dismiss]')
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
              status: document.getElementById('map-status').textContent, mapNotesAbsent: !document.getElementById('map-notes'), hintPresent: !!document.getElementById('topology-hint'),
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
    r.check('topology: the old #map-notes expander is gone and the current #topology-hint line is present (both since 1.30.36)', info['mapNotesAbsent'] and info['hintPresent'], info)
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
    r.check('menu: order CLI, capture, backup, restart, details', [i['text'].split(' ')[0] for i in menu['items']] == ['Open', 'Capture', 'Back', 'Restart', 'Device'], menu)
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
    r.check('devices: technical view shows the table alone and the button now reads Standard view (no aria-pressed)', r.js('() => !document.getElementById("inventory-view").hidden && document.getElementById("device-list").hidden && document.getElementById("devices-technical").textContent.trim() === "Standard view" && !document.getElementById("devices-technical").hasAttribute("aria-pressed")'))
    r.shot('21-devices-technical')
    p.click('#devices-technical')
    r.check('devices: the label swaps back to Technical view and the cards return', r.js('() => document.getElementById("devices-technical").textContent.trim() === "Technical view" && document.getElementById("inventory-view").hidden && !document.getElementById("device-list").hidden'))
    # Map editor and export-sessions dialogs
    r.tab('topology')
    # Edit map opens the full map editor (the lab builder's editor in map mode) for a lab whose topology
    # text the manager has; docs/ui-review-001/tools/check_ui003.py exercises it in depth.
    p.click('#map-edit')
    p.wait_for_url('**/static/map-editor.html#lab=*', timeout=15000)
    p.wait_for_selector('.react-flow__node', timeout=30000)
    r.check('editor: Edit map opens the map editor on this lab, saved and with Save off', r.js('() => document.getElementById("map-name").textContent.length > 0 && document.getElementById("map-status").textContent === "Saved in the manager" && document.getElementById("map-save").disabled'))
    r.check('editor: no deploy control and the drawing-only notice', r.js('() => !document.querySelector("[data-testid=navbar-deploy]")?.offsetParent && /drawing only/.test(document.getElementById("map-note").textContent)'))
    r.shot('14-map-editor')
    p.click('#map-back')
    p.wait_for_selector('#lab-content:not([hidden]) #topology-map', timeout=20000)
    r.check('editor: Back to the lab returns to the lab without a question when nothing changed', r.js('() => !document.getElementById("lab-content").hidden'))
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


def panel_open(r):
    return r.js('() => !document.getElementById("save-panel").hidden')


def open_chip_panel(r, wait='#save-panel-body *'):
    """The chip's panel, opened the way a student opens it (the chip), unless a save already opened it by itself."""
    if not panel_open(r):
        r.page.click('#save-chip')
    r.page.wait_for_selector('#save-panel:not([hidden]) ' + wait, timeout=15000)


def close_chip_panel(r):
    if panel_open(r):
        r.page.keyboard.press('Escape')
        r.page.wait_for_function('() => document.getElementById("save-panel").hidden', timeout=5000)


def drawer_close(r):
    r.page.click('#save-drawer-close')
    r.page.wait_for_function('() => !document.getElementById("save-drawer").open', timeout=5000)


def version_row(r, name):
    """The row of All versions whose name is exactly `name` (a row opens in place when its name is pressed)."""
    p = r.page
    return p.locator('#save-drawer-content .save-list > li').filter(has=p.locator('button.save-item > span:first-child', has_text=re.compile('^' + re.escape(name) + '$'))).first


def open_version_row(r, name):
    row = version_row(r, name)
    row.locator('button.save-item').click()
    r.page.wait_for_function('(n) => [...document.querySelectorAll("#save-drawer-content .save-list > li.open")].some(li => li.querySelector("button.save-item > span:first-child")?.textContent.trim() === n)', arg=name, timeout=5000)
    return row


def save_and_load(r):
    """Save and Load in the lab header. The Progress tab, its Save location card, Saved versions list, restore review and
    save window are gone (docs/git-redesign); each claim the old `progress` step made is checked in its new home: the chip
    panel (status, destination, last load), All versions, Save settings, the folder chooser, the Load confirmation."""
    p = r.page
    go_home(r)
    r.open_lab(SHOWCASE)
    r.check('header: the Progress tab and its view are gone, the chip and Load are in the lab header', r.js('() => !document.getElementById("tab-progress") && !document.getElementById("progress-view") && !document.getElementById("progress-save") && !!document.getElementById("save-chip") && !!document.getElementById("load-button")'))
    p.wait_for_function('() => /^Saved /.test(document.getElementById("save-chip-text").textContent)', timeout=20000)
    # ---- the chip panel at rest: status, destination, last load -------------------------------------------------------------
    open_chip_panel(r, '#save-place')
    info = r.js('''() => ({chip: document.getElementById('save-chip-text').textContent, title: document.getElementById('save-panel-title-text').textContent,
      place: document.getElementById('save-place').textContent.replace(/\\s+/g, ' ').trim(), uploaded: document.getElementById('save-uploaded')?.textContent.trim(),
      lastLoad: document.getElementById('save-last-load')?.textContent.replace(/\\s+/g, ' ').trim(), lastLoadButton: !!document.getElementById('save-load-details'),
      save: {text: document.getElementById('git-save-progress').textContent, disabled: document.getElementById('git-save-progress').disabled, reasonHidden: document.getElementById('save-reason').hidden},
      foot: [...document.querySelectorAll('#save-panel-body .save-foot button')].map(b => b.textContent.trim()), name: document.getElementById('save-name')?.value,
      keep: !!document.getElementById('save-keep')})''')
    r.notes.append({'save_panel': info})
    r.check('save panel: destination in words', info['place'].startswith('Saves to: ') and 'labs/BGP/work' in info['place'], info['place'])
    r.check('save panel: status is the student sentence', info['title'].startswith('Saved ') and (info['uploaded'] or '').startswith('Uploaded: yes, to github.com'), info)
    r.check('save panel: Save is one enabled header button with no reason under it', info['save']['text'] == 'Save' and not info['save']['disabled'] and info['save']['reasonHidden'], info['save'])
    r.check('save panel: the foot offers All versions, Save as a lab state… and Save settings', info['foot'] == ['All versions', 'Save as a lab state…', 'Save settings'], info['foot'])
    r.check('save panel: the last load is one click away', (info['lastLoad'] or '').startswith('Last load:') and info['lastLoadButton'], info['lastLoad'])
    r.check('save panel: the chip and the panel title agree', info['chip'].startswith('Saved ') and re.search(r'\d+', info['chip']) and re.search(r'\d+', info['chip']).group() == (re.search(r'\d+', info['title']) or re.search(r'$', '')).group(), (info['chip'], info['title']))
    r.shot('30a-save-panel-rest')
    # The last load, one click from the panel: its finished job (Details)
    p.click('#save-load-details')
    p.wait_for_selector('#restore-job-dialog[open]')
    r.check('last load: result sentence and per-device outcomes', r.js('() => /Configuration replaced on \\d+ device/.test(document.getElementById("restore-job-detail").textContent) && document.querySelectorAll("#restore-job-dialog .restore-target-row").length >= 2'))
    r.shot('37-restore-job')
    p.click('#restore-job-dialog [data-op-close]')
    # ---- All versions --------------------------------------------------------------------------------------------------------
    open_chip_panel(r)
    p.click('#save-all')
    p.wait_for_selector('#save-drawer-content .save-list', timeout=20000)
    p.wait_for_selector('#save-drawer-content .save-foot button', timeout=20000)
    versions = r.js('''() => ({title: document.getElementById('save-drawer-title').textContent, groups: [...document.querySelectorAll('#save-drawer-content h3.save-heading')].map(h => h.textContent.trim().toLowerCase()),
      folds: [...document.querySelectorAll('#save-drawer-content > details')].map(d => ({text: d.querySelector('summary').textContent.trim(), open: d.open})),
      foot: [...document.querySelectorAll('#save-drawer-content .save-foot button')].map(b => b.textContent.trim())})''')
    r.notes.append({'all_versions': versions})
    r.check('all versions: versions grouped for the student', versions['title'] == 'All versions' and versions['groups'] == ['your saves', 'checkpoints', 'starting point', 'lab states'], versions)
    r.check('all versions: other labs stay collapsed', any(f['text'].startswith('Other labs in this repository') and not f['open'] for f in versions['folds']), versions['folds'])
    r.check('all versions: it ends with Full history… and Browse the repository…', versions['foot'] == ['Full history…', 'Browse the repository…'], versions['foot'])
    # Every row opens in place with its actions; Load this state… only where a restore artifact exists. The saves and
    # checkpoints are taken by position in their group (their names change with every run on the same fixture), the lab
    # states by name.
    loadable, differ, rows = 0, 0, {}
    lists = p.locator('#save-drawer-content .save-list')
    for label, row in (('your latest save', lists.nth(0).locator('> li').first), ('a checkpoint', lists.nth(1).locator('> li').first), ('the starting point', lists.nth(2).locator('> li').first),
                       ('Solution', version_row(r, 'Solution')), ('Start', version_row(r, 'Start'))):
        row.locator('button.save-item').click()
        p.wait_for_function('() => document.querySelectorAll("#save-drawer-content .save-list > li.open").length === 1', timeout=5000)
        rows[label] = [(b.inner_text(), b.is_disabled()) for b in row.locator('button[data-save-action]').all()]
        loadable += sum(1 for text, disabled in rows[label] if text == 'Load this state…' and not disabled)
        differ += sum(1 for text, _ in rows[label] if text == 'See what’s different')
    r.check('all versions: Load this state… is offered only where a restore artifact exists', loadable >= 2 and ('Load this state…', True) in rows['Start'] and 'View only' in version_row(r, 'Start').inner_text(), rows)
    r.check('all versions: See what’s different (against my latest save) on the other rows', differ >= 2, differ)
    p.locator('#save-drawer-content > details:has(> summary:text-matches("^Save activity"))').locator('summary').click()
    activity = r.js('() => [...document.querySelectorAll("#save-drawer-content > details")].filter(d => /^Save activity/.test(d.querySelector("summary").textContent)).map(d => d.innerText)[0] || ""')
    r.check('all versions: save activity in student words', any(w in activity for w in ('Repository updated', 'Starting point set', "Checkpoint 'ospf-done' saved")) and 'Progress saved to Git' not in activity, activity)
    solution = open_version_row(r, 'Solution')
    r.check('version row: Load this state…, See what’s different, View files and Download ZIP', solution.locator('button[data-save-action]').all_inner_texts() == ['Load this state…', 'See what’s different', 'View files', 'Download ZIP'], solution.inner_text())
    r.shot('34-all-versions')
    solution.locator('[data-save-action="files"]').click()
    p.wait_for_function('() => document.getElementById("save-drawer-title").textContent === "View files" && /Topology file/.test(document.getElementById("save-drawer-content").textContent)', timeout=15000)
    r.check('view files: the devices, the topology file and the map, with Back', r.js('() => !document.getElementById("save-drawer-back").hidden && /Map/.test(document.getElementById("save-drawer-content").textContent) && /\\.cfg/.test(document.getElementById("save-drawer-content").textContent)'))
    p.click('#save-drawer-back')
    p.wait_for_selector('#save-drawer-content .save-list', timeout=20000)
    solution = open_version_row(r, 'Solution')
    solution.locator('[data-save-action="different"]').click()
    p.wait_for_function('() => document.getElementById("save-drawer-title").textContent === "Different from your latest save"', timeout=15000)
    r.check('see what’s different: named after the latest save, never the running devices', r.js('() => !/running configuration|compare with current/i.test(document.getElementById("save-drawer-title").textContent) && !document.getElementById("save-drawer-back").hidden'))
    r.shot('35-compare')
    p.click('#save-drawer-back')
    p.wait_for_selector('#save-drawer-content .save-list', timeout=20000)
    # ---- Load: the confirmation with its device list -------------------------------------------------------------------------
    solution = open_version_row(r, 'Solution')
    solution.locator('[data-save-action="load"]').click()
    p.wait_for_selector('#load-run', timeout=30000)
    review = r.js(r'''() => ({headline: document.querySelector('#load-panel-body .save-state')?.textContent, text: document.getElementById('load-panel-body').innerText,
       rows: [...document.querySelectorAll('#load-panel-body ul.save-devices > li')].map(li => li.innerText.trim().replace(/\s+/g, ' ')),
       boxes: [...document.querySelectorAll('#load-panel-body input[type=checkbox]')].map(b => b.name), run: document.getElementById('load-run')?.textContent,
       buttons: [...document.querySelectorAll('#load-panel-body .save-row:last-child button')].map(b => b.textContent.trim()), options: document.querySelector('#load-panel-body details summary')?.textContent, minutes: !!document.getElementById('load-minutes'),
       drawerClosed: !document.getElementById('save-drawer').open})''')
    r.notes.append({'load_confirmation': review})
    r.check('load confirmation: headline, device tick boxes, no acknowledgement to tick, undo minutes under Options', review['headline'] == 'Load Solution?' and review['drawerClosed'] and review['boxes'] and set(review['boxes']) == {'load-node'} and review['run'] == 'Load' and review['buttons'][:2] == ['Load', 'Cancel'] and review['options'] == 'Options' and review['minutes'], review)
    r.check('load confirmation: skipped devices explain why in student words', any('The device did not answer over SSH.' in row and 'Not reachable' in row for row in review['rows']), review['rows'][:3])
    r.check('load confirmation: matching and differing devices are described', any('Already matches' in row for row in review['rows']) and any(re.search(r'\d+ lines? differs?', row) for row in review['rows']), review['rows'][:3])
    r.check('load confirmation: the running configuration is replaced only after the safety backup, in one sentence', 'The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.' in review['text'], review['text'][:200])
    r.check('load confirmation: no router wording', 'router' not in review['text'].lower(), '')
    r.shot('36-load-confirmation')
    p.click('#load-cancel')
    close_chip_panel(r)
    if r.js('() => !document.getElementById("load-panel").hidden'):
        p.keyboard.press('Escape')
    # ---- Save settings: the devices of every save, Git details, Change folder… --------------------------------------------------
    open_chip_panel(r)
    p.click('#save-settings')
    p.wait_for_selector('#save-drawer-content .save-settings', timeout=20000)
    p.wait_for_selector('#save-drawer-content input[name="git-node"]', timeout=20000)
    p.locator('#save-git-details > summary').click()
    settings = r.js('''() => ({title: document.getElementById('save-drawer-title').textContent, text: document.getElementById('save-drawer-content').innerText,
      ticks: document.querySelectorAll('#save-drawer-content input[name="git-node"]').length, push: document.getElementById('git-advanced-push-url')?.textContent || ''})''')
    r.notes.append({'save_settings': {k: v for k, v in settings.items() if k != 'text'}})
    r.check('save settings: the save location with Change folder…, Use a different repository…, Connect by URL…, Disconnect this lab…', settings['title'] == 'Save settings' and all(w in settings['text'] for w in ('Change folder…', 'Use a different repository…', 'Connect by URL…', 'Disconnect this lab…')), settings['text'][:200])
    r.check('save settings: the devices of every save are real tick boxes', settings['ticks'] >= 1, settings['ticks'])
    r.check('save settings: Git details filled', 'Verified push destination' in settings['push'], settings['push'])
    r.shot('31a-save-settings')
    # Change folder… opens the chooser with the way down to the lab's folder open and Save here, Back returns to the settings
    p.locator('#save-drawer-content [data-save-action="folder"]').click()
    p.wait_for_selector('#folder-tree', timeout=20000)
    p.wait_for_selector('#folder-tree [data-folder="labs/BGP/work"]', timeout=20000)
    chooser = r.js('''() => ({title: document.getElementById('save-drawer-title').textContent, label: document.getElementById('folder-tree').getAttribute('aria-label'), back: !document.getElementById('save-drawer-back').hidden,
      foot: [...document.querySelectorAll('#folder-foot button')].map(b => b.textContent.trim()), mine: document.querySelector('#folder-tree [data-folder="labs/BGP/work"]')?.textContent.includes('This lab saves here'),
      newFolder: !!document.querySelector('.folder-chooser [data-folder-action="new"]'), note: document.getElementById('folder-answer')?.textContent.trim()})''')
    r.check('folder chooser: opens on the lab’s own folder (This lab saves here, Keep saving here) with New folder…, Back returns to the settings', chooser['title'] == 'Where should %s save?' % SHOWCASE and chooser['label'] == 'Folders of Course-Labs' and chooser['back'] and chooser['mine'] and chooser['foot'] == ['Cancel', 'Keep saving here'] and chooser['newFolder'], chooser)
    r.shot('31-folder-chooser')
    p.click('#save-drawer-back')
    p.wait_for_selector('#save-drawer-content .save-settings', timeout=20000)
    drawer_close(r)
    # ---- Save: no label to type; the save ends in the waiting panel, whose review comes before any upload ------------------------
    # (Since the redesign Save names the save itself and the name can be changed afterwards; the review before every upload stays.)
    r.check('save: there is no "What changed?" label dialog any more', r.js('() => !document.getElementById("git-label-dialog")'))
    p.click('#git-save-progress')
    p.wait_for_function('() => document.getElementById("save-chip-text").textContent === "Saving…"', timeout=10000)
    r.check('save: the chip reads Saving… and Save waits', r.js('() => document.getElementById("git-save-progress").disabled'))
    r.check('save: no job window for a plain save', r.js('() => !document.getElementById("git-job-dialog")?.open'))
    p.wait_for_function('() => /^\\d+ saves? to upload$/.test(document.getElementById("save-chip-text").textContent)', timeout=90000)
    p.wait_for_function('() => !document.getElementById("save-panel").hidden && document.getElementById("save-panel-title-text").textContent === "Not uploaded yet" && !document.getElementById("save-upload").disabled', timeout=30000)
    waiting = r.js('''() => ({title: document.getElementById('save-panel-title-text').textContent, sentence: document.getElementById('save-changes').textContent, to: document.getElementById('save-to').textContent,
      buttons: [...document.querySelectorAll('#save-panel-body .save-row button')].map(b => b.textContent.trim()), status: document.getElementById('save-panel-body').innerText})''')
    r.notes.append({'waiting': {k: v for k, v in waiting.items() if k != 'status'}})
    r.check('save: the review opens before anything is uploaded, the panel says so and offers Upload, Not now, See changes and Details', waiting['title'] == 'Not uploaded yet' and waiting['buttons'] == ['Upload', 'Not now', 'See changes', 'Details'] and 'Uploaded: yes' not in waiting['status'], waiting)
    r.check('save: the sentence names the devices changed and where the upload goes', re.search(r'\d+ devices? changed since your last save', waiting['sentence']) and waiting['to'].startswith('To: Course-Labs'), waiting)
    r.shot('30-save-panel')
    # Details: the save window with the raw status under Details
    p.click('#save-details')
    p.wait_for_selector('#git-job-dialog[open]', timeout=15000)
    try:
        p.wait_for_function('() => ["Saved", "Save needs attention", "Repository update", "Save failed"].includes(document.querySelector("#git-job-dialog h2").textContent) && !!document.querySelector("#git-job-detail details")', timeout=15000)
        r.check('save window: student title and Details with the raw status', True)
    except Exception as exc:
        r.check('save window: student title and Details with the raw status', False, repr(exc))
    p.click('#git-job-dialog [data-op-close]')
    # See changes: the drawer with Upload and Not now at the top; Upload uploads and the panel agrees
    open_chip_panel(r, '#save-see')
    p.click('#save-see')
    p.wait_for_selector('#save-drawer-content .diff-file', timeout=20000)
    r.check('see changes: What changed, with Upload and Not now at the top', r.js('() => document.getElementById("save-drawer-title").textContent') == 'What changed' and r.js('() => !!document.querySelector("#save-drawer-actions [data-save-action=upload]:not(:disabled)") && !!document.querySelector("#save-drawer-actions [data-save-action=not-now]")'))
    p.click('#save-drawer-actions [data-save-action="upload"]')
    p.wait_for_function('() => /^Saved /.test(document.getElementById("save-chip-text").textContent) && !document.getElementById("save-drawer").open', timeout=60000)
    open_chip_panel(r, '#save-uploaded')
    r.check('save: uploaded after the review and the panel agrees', r.js('() => document.getElementById("save-uploaded").textContent.trim().startsWith("Uploaded: yes, to github.com")'), r.js('() => document.getElementById("save-panel-body").innerText'))
    if r.js('() => !!document.getElementById("git-job-dialog")?.open'):
        p.keyboard.press('Escape')
    # Keep as a checkpoint: the name is sanitised live with a preview (All versions, on the save just made)
    p.click('#save-all')
    p.wait_for_selector('#save-drawer-content .save-list', timeout=20000)
    first = p.locator('#save-drawer-content .save-list').first.locator('> li').first
    first.locator('button.save-item').click()
    first.locator('[data-save-action="checkpoint"]').click()
    p.wait_for_selector('#save-checkpoint-name', timeout=5000)
    p.fill('#save-checkpoint-name', 'ospf done!')
    r.check('checkpoint: name sanitised live', r.js('() => document.getElementById("save-checkpoint-name").value === "ospf-done" && /Saved as: ospf-done/.test(document.getElementById("save-drawer-content").textContent)'))
    r.shot('38-checkpoint')
    p.locator('#save-drawer-content [data-save-action="checkpoint-cancel"]').click()
    drawer_close(r)
    # ---- A lab without a save location: Save opens the first-save view; Choose another place opens the chooser ---------------------
    go_home(r)
    r.open_lab(EMPTY_MAP_LAB)
    p.wait_for_function('() => document.getElementById("save-chip-text").textContent === "Not saved yet"', timeout=20000)
    p.click('#git-save-progress')
    p.wait_for_selector('#save-first', timeout=15000)
    first = r.js('''() => ({save: document.getElementById('save-first').textContent, saveDisabled: document.getElementById('save-first').disabled, headerDisabled: document.getElementById('git-save-progress').disabled,
      title: document.getElementById('save-panel-title-text').textContent, place: document.getElementById('save-first-place').textContent, other: document.getElementById('save-first-place-other')?.textContent,
      url: document.getElementById('save-first-url')?.textContent, text: document.getElementById('save-panel-body').innerText})''')
    r.notes.append({'first_save': {k: v for k, v in first.items() if k != 'text'}})
    r.check('unbound lab: Save is enabled and opens the first-save view with the place, Choose another place and Connect by URL…', first['title'] == 'Not saved yet' and not first['headerDisabled'] and not first['saveDisabled'] and first['save'] == 'Save' and first['place'].startswith('Your first save goes to ') and first['other'] == 'Choose another place' and first['url'] == 'Connect by URL…', first)
    r.check('first save: the sentence names the repository and the folder, and the consent sentence is there', 'in a folder named %s' % EMPTY_MAP_LAB in first['place'] and 'Saved files can contain passwords or keys.' in first['text'], first['text'])
    r.shot('39-save-first')
    p.click('#save-first-place-other')
    p.wait_for_selector('#folder-tree', timeout=20000)
    r.check('first save: Choose another place opens the chooser with where uploads go, the folder to type or pick and Save here', r.js('() => document.getElementById("save-drawer-title").textContent') == 'Where should %s save?' % EMPTY_MAP_LAB and r.js('() => !!document.getElementById("folder-uploads") && !!document.getElementById("folder-path") && [...document.querySelectorAll("#folder-foot button")].some(b => b.textContent.trim() === "Save here")'))
    r.shot('32-first-save-chooser')
    drawer_close(r)


def go_home(r):
    """Back to My labs the way a student goes: the breadcrumb. A bare '/' would restore the last lab from
    session storage (hash → sessionStorage → Home), so only a fresh document starts with goto."""
    p = r.page
    if not p.url.startswith(BASE + '/#') and p.url.rstrip('/') != BASE:
        p.goto(BASE + '/')
    p.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=15000)
    if not p.evaluate('() => document.getElementById("home") && !document.getElementById("home").hidden'):
        p.click('#crumb-home')
    p.wait_for_selector('#home:not([hidden])', timeout=10000)
    p.wait_for_function('() => document.querySelectorAll("article.lab-card").length > 0', timeout=15000)


def labs_by_name(r):
    return {l['name']: l for l in r.js('() => state.labs')}


def tools(r):
    """Tools tab: cards with captions, the capture dialog (device picker first)."""
    p = r.page
    go_home(r)
    r.open_lab(SHOWCASE); r.tab('tools'); p.wait_for_timeout(500)
    cards = r.js('() => ({capture: document.getElementById("capture-open").textContent, cap_caption: document.getElementById("capture-caption").hidden ? "" : document.getElementById("capture-caption").textContent, ssh: document.getElementById("tools-ssh-all")?.textContent.trim()})')
    r.check('tools: Capture traffic…, capture caption when disabled', cards['capture'] == 'Capture traffic…' and (cards['cap_caption'] == '' or 'not set up' in cards['cap_caption']), cards)
    r.shot('40-tools')
    p.click('#capture-open'); p.wait_for_selector('#capture-dialog[open]'); p.wait_for_timeout(800)
    cap = r.js('() => ({ctx: document.getElementById("capture-context").textContent, adv: document.getElementById("capture-advanced-label").textContent, open: document.getElementById("capture-advanced").open, legend: document.getElementById("capture-primary-legend").textContent, start: document.getElementById("capture-prepare").textContent, order: [...document.querySelectorAll("#capture-form > *")].map(e => e.id || e.tagName.toLowerCase()), sessions: document.getElementById("capture-sessions").textContent})')
    r.check('capture dialog: lab context, device picker unfolded first, Start capture, sessions explained', cap['ctx'].startswith('Lab ') and cap['adv'] == 'Choose a device' and cap['open'] and cap['start'] == 'Start capture' and cap['order'].index('capture-advanced') < cap['order'].index('fieldset') and cap['sessions'], cap)
    r.shot('41-capture-dialog')
    p.click('#capture-close')


def operations(r):
    """Lab actions ▾, the review confirmations, the banner-first confirm, All lab operations, Manager ▾ items."""
    p = r.page
    go_home(r)
    r.open_lab(SHOWCASE); r.tab('tools')
    p.wait_for_function('() => state.discovery?.connected && current()?.deployment?.status === "Running" && !busy()', timeout=60000); p.wait_for_timeout(300)
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])')
    menu = r.js('() => [...document.querySelectorAll("#lab-actions-menu button")].map(b => ({t: b.querySelector("span")?.textContent || b.textContent, d: b.disabled, r: b.querySelector(".menu-reason")?.textContent || ""}))')
    r.check('lab actions menu: every disabled item carries a visible reason', all(m['r'] for m in menu if m['d']), menu)
    r.shot('43-lab-actions-menu')
    p.click('#menu-destroy'); p.wait_for_selector('#operation-review[open]', timeout=15000)
    review = r.js('() => ({title: document.querySelector("#operation-review h2").textContent, text: document.getElementById("operation-review").textContent, confirm: document.getElementById("op-confirm").textContent, danger: document.getElementById("op-confirm").classList.contains("danger"), save: !!document.getElementById("op-save-first"), pre: document.querySelector("#operation-review details pre")?.textContent || "", tops: [...document.querySelectorAll("#operation-review > p")].map(p => p.textContent).join(" ")})')
    r.check('destroy review: student title, unsaved-work and last-save lines, danger confirm, Save progress first', review['title'].startswith('Destroy ') and 'Configuration changes you have not saved are lost' in review['text'] and ('Last saved' in review['text'] or 'Never saved' in review['text']) and review['confirm'] == 'Destroy lab' and review['danger'] and review['save'], review['title'])
    r.check('destroy review: the raw command only under Technical details', '/usr/bin/containerlab' in review['pre'] and '/usr/bin/containerlab' not in review['tops'], '')
    r.shot('44-destroy-review')
    p.click('#op-cancel')
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])')
    p.click('#lab-actions-menu [data-op-action="stop"]'); p.wait_for_selector('#operation-review[open]', timeout=15000)
    r.check('stop review: title and confirm label', r.js('() => document.querySelector("#operation-review h2").textContent === "Stop devices?" && document.getElementById("op-confirm").textContent === "Stop devices"'))
    p.click('#op-confirm')
    p.wait_for_function('() => !document.getElementById("operation-review")?.open && !document.getElementById("lab-banner").hidden && /stop/i.test(document.getElementById("lab-banner-text").textContent)', timeout=15000)
    banner = r.js('() => ({text: document.getElementById("lab-banner-text").textContent, output: !document.getElementById("banner-output").hidden, out: document.getElementById("operation-output")?.open || false, pill: document.getElementById("lab-state").textContent})')
    r.check('confirm: no output window pops up; the banner names the operation with View output', 'stop' in banner['text'].lower() and banner['output'] and not banner['out'], banner)
    r.shot('45-operation-banner')
    p.click('#banner-output'); p.wait_for_selector('#operation-output[open]'); p.wait_for_timeout(400)
    r.check('operation output: student heading and banner', r.js('() => /Stop devices/.test(document.querySelector("#operation-output h2").textContent) && /Stop devices/.test(document.getElementById("op-job-banner").textContent)'))
    r.shot('46-operation-output')
    p.click('#operation-output [data-op-close]')
    p.wait_for_function('() => document.getElementById("lab-banner").hidden || !/stop/i.test(document.getElementById("lab-banner-text").textContent)', timeout=30000)
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])')
    p.click('#lab-actions'); p.wait_for_selector('#lab-operations-dialog[open]'); p.wait_for_timeout(500)
    ops = r.js('() => ({sections: [...document.querySelectorAll("#lab-operations-dialog .op-sections h3")].map(h => h.textContent), buttons: [...document.querySelectorAll("#lab-operations-dialog [data-op-action]")].map(b => b.textContent.trim()), danger: !!document.querySelector("#lab-operations-dialog .op-danger [data-op-action=destroy]")})')
    r.check('all lab operations: Deployment / Lab tools / Danger with student labels', ops['sections'] == ['Deployment', 'Lab tools', 'Danger'] and 'Start devices' in ops['buttons'] and ops['danger'], ops)
    r.shot('47-all-lab-operations')
    p.click('#lab-operations-dialog [data-op-close]')
    p.click('#manager-button'); p.wait_for_selector('#manager-menu-list:not([hidden])')
    p.click('#inspect-all'); p.wait_for_selector('#operation-review[open]', timeout=15000)
    r.check('running labs review: read-only wording and Show running labs', r.js('() => document.querySelector("#operation-review h2").textContent === "Refresh the list of running labs on the VM" && document.getElementById("op-confirm").textContent === "Show running labs" && /Nothing is changed/.test(document.getElementById("operation-review").textContent)'))
    r.shot('48-running-labs-review')
    p.click('#op-confirm'); p.wait_for_selector('#operation-output[open]', timeout=15000)
    p.wait_for_function('() => !!document.querySelector("#operation-output table caption") || /✖/.test(document.getElementById("op-job-banner").textContent)', timeout=30000)
    r.check('running labs: inspection table with student columns', r.js('() => { const c = document.querySelector("#operation-output table caption"); const h = [...document.querySelectorAll("#operation-output th")].map(t => t.textContent); return !!c && /running devices/.test(c.textContent) && h[2] === "Device" && h[3] === "Type / image"; }'))
    r.shot('49-running-labs-table')
    p.click('#operation-output [data-op-close]')
    p.click('#manager-button'); p.wait_for_selector('#manager-menu-list:not([hidden])')
    p.click('#operations-history'); p.wait_for_selector('#operation-history[open]', timeout=15000)
    hist = r.js('() => ({title: document.querySelector("#operation-history h2").textContent, rows: [...document.querySelectorAll("#operation-history [data-job] strong")].map(s => s.textContent)})')
    r.check('operation history: student action names in every row', hist['title'].startswith('Operation history') and hist['rows'] and all(' · ' in row for row in hist['rows']), hist)
    r.shot('50-operation-history')
    p.click('#operation-history [data-op-close]')


def advanced(r):
    """Advanced tab of a lab without a VM topology path: deployment sentences, banner reason, Remove lab dialog."""
    p = r.page
    go_home(r)
    r.open_lab(EMPTY_MAP_LAB); r.tab('advanced'); p.wait_for_timeout(500)
    adv = r.js('() => ({files: document.getElementById("vm-files-status").textContent, vm: document.getElementById("vm-summary").textContent, start: document.getElementById("banner-start").textContent, disabled: document.getElementById("banner-start").disabled, detail: document.getElementById("lab-banner-detail-text").textContent, hidden: document.getElementById("lab-banner-detail").hidden})')
    r.check('advanced: VM status sentence; a disabled Start explains itself in the banner details', adv['vm'].startswith('Lab VM:') and adv['start'] == 'Start lab' and (not adv['disabled'] or (adv['detail'] and not adv['hidden'])), adv)
    r.shot('51-advanced', full=True)
    p.click('#remove-lab'); p.wait_for_selector('#remove-lab-dialog[open]')
    r.check('remove lab dialog: named title and danger submit', r.js('() => document.getElementById("remove-lab-title").textContent.startsWith("Remove ") && document.querySelector("#remove-lab-form button[type=submit]").classList.contains("danger")'))
    r.shot('52-remove-lab')
    p.click('#remove-lab-dialog [data-dismiss]')


def polling(r):
    """The device panel and a menu survive two polls with focus and content intact."""
    p = r.page
    go_home(r)
    r.open_lab(SHOWCASE); r.tab('devices'); p.wait_for_timeout(300)
    p.locator('#devices-view [data-details]').first.click(); p.wait_for_selector('#details-dialog[open]')
    before = r.js('() => ({title: document.getElementById("details-title")?.textContent, actions: document.getElementById("details-actions")?.innerHTML.length, focus: document.activeElement?.id || document.activeElement?.tagName})')
    p.wait_for_timeout(POLL_MS * 2 + 800)
    after = r.js('() => ({open: document.getElementById("details-dialog").open, title: document.getElementById("details-title")?.textContent, actions: document.getElementById("details-actions")?.innerHTML.length, focus: document.activeElement?.id || document.activeElement?.tagName})')
    r.check('polling: the device panel stays open with the same device and focus across two polls', after['open'] and after['title'] == before['title'] and after['focus'] == before['focus'], {'before': before, 'after': after})
    r.shot('53-drawer-after-polls')
    p.keyboard.press('Escape'); p.wait_for_function('() => !document.getElementById("details-dialog").open')
    p.click('#lab-actions-button'); p.wait_for_selector('#lab-actions-menu:not([hidden])')
    p.keyboard.press('ArrowDown'); p.keyboard.press('ArrowDown')
    focused = r.js('() => document.activeElement?.id || document.activeElement?.textContent')
    p.wait_for_timeout(POLL_MS * 2 + 800)
    still = r.js('() => ({open: !document.getElementById("lab-actions-menu").hidden, focus: document.activeElement?.id || document.activeElement?.textContent})')
    r.check('polling: an open menu keeps its item focus across two polls', still['open'] and still['focus'] == focused, {'focused': focused, 'still': still})
    r.shot('54-menu-after-polls')
    p.keyboard.press('Escape'); p.wait_for_function('() => document.getElementById("lab-actions-menu").hidden')


def pages(r):
    """The standalone pages: CLI launcher, deploy page with the topology browser, Diagnostics, network dashboard, terminal, guides."""
    p = r.page
    labs = labs_by_name(r); bgp = labs[SHOWCASE]
    p.goto(f'{BASE}/static/workspace.html#mode=ssh&lab={bgp["id"]}'); p.wait_for_selector('#ssh-launch-all', timeout=15000); p.wait_for_timeout(300)
    ws = r.js('() => ({title: document.getElementById("workspace-title").textContent, doc: document.title, msg: document.getElementById("workspace-message").textContent, rows: document.querySelectorAll(".op-session-row").length, links: document.querySelectorAll(".op-session-row a").length, pills: document.querySelectorAll(".op-session-row .pill").length, history: !!document.getElementById("ssh-history")})')
    r.check('CLI launcher: Open CLIs title, devices-ready sentence, pills, Open CLI links, history link row', ws['title'].startswith('Open CLIs · ') and ws['doc'].startswith('Open CLIs · ') and 'devices ready' in ws['msg'] and ws['rows'] == len(bgp['nodes']) and ws['pills'] == ws['rows'] and ws['links'] > 0 and ws['history'], ws)
    r.shot('55-cli-launcher', full=True)
    p.goto(f'{BASE}/static/workspace.html#mode=folder'); p.reload(); p.wait_for_function('() => document.getElementById("workspace-title").textContent === "Deploy a new lab" && !document.getElementById("workspace-open").hidden', timeout=15000)
    r.shot('56-deploy-page')
    p.click('#workspace-open'); p.wait_for_selector('#op-browser[open]', timeout=15000); p.wait_for_timeout(500)
    browser = r.js('() => ({title: document.querySelector("#op-browser h2").textContent, buttons: [...document.querySelectorAll("#op-browser .actions button")].map(b => b.textContent), tree: [...document.querySelectorAll("#op-file-tree summary")].map(s => s.textContent)})')
    r.check('topology browser: title, toolbar labels, folder tree', browser['title'] == 'Deploy a new lab' and 'All lab folders' in browser['buttons'] and browser['tree'], browser)
    p.click('#op-file-tree summary >> nth=0'); p.wait_for_function('() => document.querySelectorAll("#op-file-tree details details, #op-file-tree .op-tree-file").length > 0', timeout=15000)
    inner = p.locator('#op-file-tree details details > summary')
    if inner.count():
        inner.first.click(); p.wait_for_selector('#op-file-tree .op-tree-file', timeout=15000)
    r.shot('57-topology-browser')
    p.locator('#op-file-tree .op-tree-file').first.click(); p.wait_for_selector('#op-editor[open]', timeout=15000); p.wait_for_timeout(300)
    editor = r.js('() => [...document.querySelectorAll("#op-editor .actions button")].map(b => b.textContent)')
    r.check('topology file dialog: Preview topology / Open in Lab Builder / Add to My labs / Deploy lab', editor == ['Preview topology', 'Open in Lab Builder…', 'Add to My labs without starting', 'Deploy lab'], editor)
    p.click('#op-validate'); p.wait_for_selector('#op-map-preview[open]', timeout=15000); p.wait_for_timeout(300)
    r.shot('58-topology-preview')
    p.click('#op-map-preview [data-op-close]'); p.click('#op-editor [data-op-close]'); p.click('#op-browser [data-op-close]')
    p.goto(f'{BASE}/static/debug.html'); p.wait_for_function('() => /^Updated /.test(document.getElementById("debug-status").textContent)', timeout=15000)
    dbg = r.js('() => ({h1: document.querySelector("h1").textContent, cards: [...document.querySelectorAll("#debug-summary h2")].map(h => h.textContent), first: [...document.querySelectorAll("#debug-summary dt")].slice(0,4).map(d => d.textContent)})')
    r.check('diagnostics: page name, card titles and the manager card order', dbg['h1'] == 'Diagnostics' and dbg['cards'] == ['This manager', 'VM connection', 'Saved in this manager'] and dbg['first'] == ['Version', 'Python', 'Running for', 'Activity log'], dbg)
    p.click('#debug-probe'); p.wait_for_function('() => document.querySelectorAll("#debug-checks p").length >= 2', timeout=120000)
    probe = r.js('() => [...document.querySelectorAll("#debug-checks p")].map(p => p.textContent)')
    r.check('diagnostics: probe rows use student names and an uppercase status', all(row.startswith(('Folder listing — ', 'VM commands — ')) for row in probe), probe)
    r.shot('59-diagnostics')
    ready = next((n for n in bgp['nodes'] if n.get('ssh_ready')), bgp['nodes'][0])
    p.goto(f'{BASE}/static/terminal.html#lab={bgp["id"]}&node={ready["name"]}&label={SHOWCASE}'); p.wait_for_timeout(2500)
    term = r.js('() => ({title: document.getElementById("title").textContent, back: document.getElementById("back").textContent, status: document.getElementById("status").textContent, notice: document.getElementById("notice-text").textContent, connect: document.getElementById("connect").textContent})')
    r.check('terminal: device-first title, back link, Reconnect, notice with the saved credentials', term['title'].endswith(' · ' + SHOWCASE) and term['back'] == '← ' + SHOWCASE and term['connect'] == 'Reconnect' and 'credentials saved for' in term['notice'], term)
    r.shot('61-terminal')
    p.goto(f'{BASE}/static/capture-setup.html'); p.wait_for_timeout(300); r.shot('62-capture-setup')
    p.goto(f'{BASE}/vm-connection-guide'); p.wait_for_timeout(300)
    r.check('vm guide: Diagnostics link', 'Open Diagnostics' in r.js('() => document.body.textContent'))
    go_home(r)

def run_viewport(browser, vw, vh):
    ctx = browser.new_context(viewport={'width': vw, 'height': vh}, device_scale_factor=1)
    page = ctx.new_page()
    r = Run(page, f'{vw}x{vh}')
    for step in (home, topology, empty_map, save_and_load, tools, operations, advanced, polling, pages):
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
            # Chromium logs every non-2xx fetch as a console error; the ones the page handles (a missing
            # optional file, a disabled service) are listed apart from real errors and do not fail the run.
            handled = [e for e in r.console if e['text'].startswith(HANDLED)]
            real = [e for e in r.console if e not in handled]
            failed += len(bad) + len(real) + len(r.pageerrors)
            print(f'{r.tag}: {len(r.asserts) - len(bad)}/{len(r.asserts)} checks passed, console errors {len(real)}, page errors {len(r.pageerrors)}, handled HTTP error responses {len(handled)}', flush=True)
            for e in real + r.pageerrors:
                print('  console/page error:', e, flush=True)
            for e in handled:
                print('  handled:', e['text'], flush=True)
            report.append({'viewport': r.tag, 'asserts': r.asserts, 'console': real, 'handled_http': handled, 'pageerrors': r.pageerrors, 'notes': r.notes, 'shots': r.shots})
        browser.close()
    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)
    print('report:', os.path.join(OUT, 'report.json'))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
