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
              status: document.getElementById('map-status').textContent, notes: !document.getElementById('map-notes'),
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


def progress(r):
    p = r.page
    p.click('#crumb-home')
    p.wait_for_selector('#home:not([hidden])')
    r.open_lab(SHOWCASE)
    r.tab('progress')
    p.wait_for_selector('#git-save-location', timeout=15000)
    p.wait_for_function('() => document.querySelectorAll("#git-saved-versions .git-version-row").length > 0', timeout=15000)
    info = r.js('''() => ({destination: document.getElementById('git-destination').textContent, status: document.getElementById('git-progress-status').textContent,
      save: {text: document.getElementById('git-save-progress').textContent, disabled: document.getElementById('git-save-progress').disabled},
      progressSave: {text: document.getElementById('progress-save').textContent, disabled: document.getElementById('progress-save').disabled, reasonHidden: document.getElementById('progress-save-reason').hidden},
      groups: [...document.querySelectorAll('#git-saved-versions h3, #git-saved-versions summary')].map(h => h.textContent),
      apply: document.querySelectorAll('#git-saved-versions [data-git-version-action="apply"]').length,
      compare: document.querySelectorAll('#git-saved-versions [data-git-version-action="compare"]').length,
      saves: [...document.querySelectorAll('#git-saves-list .git-saved-job > summary')].map(s => s.textContent.trim()),
      locationHead: document.querySelector('#git-save-location h2')?.textContent, folderOpen: document.getElementById('git-change-folder')?.open,
      advancedHidden: document.getElementById('git-repository-advanced').hidden, pushUrl: document.getElementById('git-advanced-push-url').textContent,
      lastChange: document.getElementById('git-last-restore').hidden ? '' : document.getElementById('git-last-restore-text').textContent,
      problemHidden: document.getElementById('git-problem').hidden, header: document.getElementById('lab-progress').textContent})''')
    r.notes.append({'progress': info})
    r.check('progress: destination in words', info['destination'].startswith('Saving to '), info['destination'])
    r.check('progress: status is the student sentence', info['status'].startswith('Saved to Git'), info['status'])
    r.check('progress: Save progress enabled on both buttons', info['save']['text'] == 'Save progress' and not info['save']['disabled'] and info['progressSave']['text'] == 'Save progress' and info['progressSave']['reasonHidden'], info)
    r.check('progress: versions grouped for the student', all(any(g.startswith(k) for g in info['groups']) for k in ('Latest', 'Checkpoints', 'Baseline', 'Instructor and reference versions', 'Other labs in this repository')), info['groups'])
    r.check('progress: other labs stay collapsed', r.js('() => { const d = [...document.querySelectorAll("#git-saved-versions details.git-version-group")]; return d.length === 1 && !d[0].open; }'))
    r.check('progress: apply offered only where a restore artifact exists', info['apply'] >= 2, info['apply'])
    r.check('progress: compare with my latest save on the other rows', info['compare'] >= 2, info['compare'])
    r.check('progress: recent saves in student words', len(info['saves']) >= 2 and any('Progress saved to Git' in s for s in info['saves']), info['saves'])
    r.check('progress: save location shows its folder browser for a connected lab', info['locationHead'] == 'Save location' and info['folderOpen'] is True, info)
    r.check('progress: advanced details filled', (not info['advancedHidden']) and 'Verified push destination' in info['pushUrl'], info['pushUrl'])
    r.check('progress: last configuration change is one click away', info['lastChange'].startswith('Last configuration change'), info['lastChange'])
    r.check('progress: header line agrees', info['header'].startswith('Saved to Git'), info['header'])
    r.shot('30-progress', full=True)
    # Saved version dialogs: View (Apply available), Compare, and the restore review
    p.locator('#git-saved-versions [data-git-version-action="view"]').first.click()
    p.wait_for_selector('#git-version-dialog[open]')
    r.check('version dialog: Saved version with Apply, Compare and Download', r.js('() => document.querySelector("#git-version-dialog h2").textContent === "Saved version" && !!document.getElementById("git-version-restore") && document.getElementById("git-version-compare").textContent === "Compare with my latest save" && document.getElementById("git-version-download").textContent === "Download (ZIP)"'))
    r.shot('34-saved-version')
    p.click('#git-version-dialog [data-op-close]')
    p.locator('#git-saved-versions [data-git-version-action="compare"]').first.click()
    p.wait_for_selector('#git-diff-dialog[open]')
    r.check('compare dialog: named after the latest save, never the running devices', r.js('() => document.querySelector("#git-diff-dialog h2").textContent === "Compared with your latest save" && !/running configuration|compare with current/i.test(document.querySelector("#git-diff-dialog h2").textContent)'))
    r.shot('35-compare')
    p.click('#git-diff-dialog [data-op-close]')
    p.locator('#git-saved-versions .git-version-group:has(h3:text-is("Instructor and reference versions")) [data-git-version-action="apply"]').first.click()
    p.wait_for_selector('#restore-review-dialog[open]')
    p.wait_for_function('() => !!document.getElementById("restore-run") || !!document.querySelector("#restore-review-dialog .form-error")?.textContent', timeout=30000)
    review = r.js(r'''() => ({title: document.querySelector('#restore-review-dialog h2')?.textContent, legend: document.querySelector('#restore-review-dialog legend')?.textContent,
       rows: [...document.querySelectorAll('#restore-review-dialog .restore-target')].map(l => l.textContent.trim().replace(/\s+/g, ' ').slice(0, 120)),
       bullets: document.querySelectorAll('#restore-review-dialog .restore-safety li').length, ack: !!document.getElementById('restore-ack'), minutes: !!document.getElementById('restore-confirm-minutes'),
       run: document.getElementById('restore-run')?.textContent, advanced: document.querySelector('#restore-review-dialog .restore-advanced summary')?.textContent, text: document.getElementById('restore-review-dialog').textContent})''')
    r.check('restore review: title, Devices legend, three safety bullets, acknowledgement and undo minutes', review['title'] == 'Replace running configuration' and review['legend'] == 'Devices' and review['bullets'] == 3 and review['ack'] and review['minutes'] and review['run'] == 'Replace configurations' and review['advanced'] == 'Advanced options', review)
    r.check('restore review: skipped devices explain why in student words', any('Skipped — The device did not answer over SSH.' in row for row in review['rows']), review['rows'][:3])
    r.check('restore review: matching and differing devices are described', any('Already matches' in row for row in review['rows']) and any('differences from the running configuration' in row for row in review['rows']), review['rows'][:3])
    r.check('restore review: no router wording', 'router' not in review['text'].lower(), '')
    r.shot('36-restore-review')
    p.click('#restore-review-dialog [data-op-close]')
    # Last configuration change → the finished restore job
    p.click('#git-last-restore-open')
    p.wait_for_selector('#restore-job-dialog[open]')
    r.check('restore job: result sentence and per-device outcomes', r.js('() => /Configuration replaced on \\d+ device/.test(document.getElementById("restore-job-detail").textContent) && document.querySelectorAll("#restore-job-dialog .restore-target-row").length >= 2'))
    r.shot('37-restore-job')
    p.click('#restore-job-dialog [data-op-close]')
    # Recent saves row → Open → job window
    p.locator('#git-saves-list .git-saved-job > summary').first.click()
    p.locator('#git-saves-list [data-git-job-open]').first.click()
    p.wait_for_selector('#git-job-dialog[open]')
    try:
        p.wait_for_function('() => ["Progress saved", "Save needs attention", "Repository update", "Save failed"].includes(document.querySelector("#git-job-dialog h2").textContent) && !!document.querySelector("#git-job-detail details")', timeout=15000)
        r.check('save window: student title and Details with the raw status', True)
    except Exception as exc:
        r.check('save window: student title and Details with the raw status', False, repr(exc))
    p.click('#git-job-dialog [data-op-close]')
    # Create checkpoint dialog: sanitised name with live preview
    p.click('#progress-view [data-git-action="checkpoint"]')
    p.wait_for_selector('#git-save-options[open]')
    p.fill('#git-checkpoint-name', 'ospf done!')
    r.check('checkpoint dialog: name sanitised live', r.js('() => document.getElementById("git-checkpoint-name").value === "ospf-done" && document.getElementById("git-checkpoint-preview").textContent === "Saved as: ospf-done"'))
    r.shot('38-checkpoint')
    p.click('#git-save-cancel')
    # Change folder… is unfolded when Save location is entered: the browser is inside the form
    r.check('save location: Change folder is open on entry', r.js('() => document.getElementById("git-change-folder").open'))
    p.wait_for_selector('#git-places-panel .git-places-head', timeout=15000)
    places = r.js('() => ({use: document.querySelector("[data-git-places-action=use]")?.textContent, crumbs: [...document.querySelectorAll(".git-crumbs button")].map(b => b.textContent), select: document.getElementById("git-binding-id")?.value, heading: document.querySelector("#git-change-folder h3")?.textContent})')
    r.check('save location: folder browser with Save this lab here and the heading', places['use'] == 'Save this lab here' and places['heading'] == 'Folders in this repository', places)
    r.shot('31-save-location', full=True)
    # Save progress (quiet): the header carries the phases
    p.click('#git-save-progress')
    p.wait_for_function('() => document.getElementById("git-save-progress").textContent === "Saving…"', timeout=10000)
    r.check('save: header button reads Saving…', True)
    r.check('save: no job window for a plain save', r.js('() => !document.getElementById("git-job-dialog")?.open'))
    # The review before an upload is mandatory: the save stops on the VM, the review opens by itself and
    # only its button uploads.
    p.wait_for_selector('#git-diff-dialog[open] #git-review-push', timeout=60000)
    r.check('save: the review opens before anything is uploaded', r.js('() => document.querySelector("#git-diff-dialog h2").textContent') == 'Review before uploading' and r.js('() => document.getElementById("git-progress-status").textContent.startsWith("Saved on this VM")'), r.js('() => document.getElementById("git-progress-status").textContent'))
    r.shot('39-review-before-upload')
    p.click('#git-review-push')
    p.wait_for_function('() => document.getElementById("git-progress-status").textContent.startsWith("Saved to Git")', timeout=60000)
    r.check('save: uploaded after the review and the status card agrees', True)
    if r.js('() => !!document.getElementById("git-job-dialog")?.open'):
        p.keyboard.press('Escape')
    # An unbound lab: the header button leads to the first-save dialog
    p.click('#crumb-home')
    p.wait_for_selector('#home:not([hidden])')
    r.open_lab(EMPTY_MAP_LAB)
    r.tab('progress')
    p.wait_for_selector('#git-save-location', timeout=15000)
    first = r.js('() => ({button: document.getElementById("git-save-progress").textContent, disabled: document.getElementById("git-save-progress").disabled, destination: document.getElementById("git-destination").textContent, head: document.querySelector("#git-save-location h2")?.textContent, folderOpen: document.getElementById("git-change-folder")?.open, versions: document.getElementById("git-saved-versions").textContent, menuHidden: document.getElementById("git-save-menu").hidden})')
    r.check('unbound lab: Connect a save location… enabled, browser open, empty states', first['button'] == 'Connect a save location…' and not first['disabled'] and first['head'] == 'Choose a save location' and first['folderOpen'] is True and 'Choose a save location first' in first['versions'] and first['menuHidden'], first)
    r.shot('39-progress-unbound', full=True)
    p.click('#git-save-progress')
    p.wait_for_selector('#git-first-save-dialog[open]', timeout=15000)
    r.check('first save: dialog asks where to save with repository, folder, devices and consent', r.js('() => document.querySelector("#git-first-save-dialog h2").textContent.startsWith("Where should") && !!document.getElementById("git-first-repo") && !!document.getElementById("git-first-folder") && !!document.getElementById("git-first-ack") && document.getElementById("git-first-confirm").textContent === "Save progress"'))
    r.shot('32-first-save')
    p.click('#git-first-cancel')



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
    """Tools tab: cards with captions, the capture dialog (device picker first) and telemetry settings."""
    p = r.page
    go_home(r)
    r.open_lab(SHOWCASE); r.tab('tools'); p.wait_for_timeout(500)
    cards = r.js('() => ({grafana: document.getElementById("grafana-open").hidden ? "" : document.getElementById("grafana-open").textContent.trim(), caption: document.getElementById("grafana-caption").textContent, tele: document.getElementById("telemetry-line").textContent, capture: document.getElementById("capture-open").textContent, cap_caption: document.getElementById("capture-caption").hidden ? "" : document.getElementById("capture-caption").textContent, ssh: document.getElementById("tools-ssh-all")?.textContent.trim()})')
    r.check('tools: dashboard link label, telemetry line, Capture traffic…, capture caption when disabled', cards['grafana'] in ('', 'Open lab map ↗', 'Open network dashboard ↗') and cards['tele'] and cards['capture'] == 'Capture traffic…' and (cards['cap_caption'] == '' or 'not set up' in cards['cap_caption']), cards)
    r.shot('40-tools')
    p.click('#capture-open'); p.wait_for_selector('#capture-dialog[open]'); p.wait_for_timeout(800)
    cap = r.js('() => ({ctx: document.getElementById("capture-context").textContent, adv: document.getElementById("capture-advanced-label").textContent, open: document.getElementById("capture-advanced").open, legend: document.getElementById("capture-primary-legend").textContent, start: document.getElementById("capture-prepare").textContent, order: [...document.querySelectorAll("#capture-form > *")].map(e => e.id || e.tagName.toLowerCase()), sessions: document.getElementById("capture-sessions").textContent})')
    r.check('capture dialog: lab context, device picker unfolded first, Start capture, sessions explained', cap['ctx'].startswith('Lab ') and cap['adv'] == 'Choose a device' and cap['open'] and cap['start'] == 'Start capture' and cap['order'].index('capture-advanced') < cap['order'].index('fieldset') and cap['sessions'], cap)
    r.shot('41-capture-dialog')
    p.click('#capture-close')
    p.click('#tools-telemetry-settings'); p.wait_for_selector('#telemetry-settings-dialog[open]', timeout=15000); p.wait_for_timeout(300)
    tele = r.js('() => document.getElementById("telemetry-settings-dialog").textContent')
    r.check('telemetry settings: student sentences with a Dashboard: line', tele.startswith('Telemetry settings') and 'Dashboard:' in tele and 'pygnmi' not in tele, tele[:160])
    r.shot('42-telemetry-settings')
    p.click('#telemetry-settings-dialog [data-op-close]')


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
    p.goto(f'{BASE}/static/grafana.html#path=%2Fd%2Fclab-map-abc&title={SHOWCASE}'); p.wait_for_timeout(1500)
    gf = r.js('() => ({title: document.getElementById("grafana-title").textContent, headline: document.getElementById("grafana-headline").textContent, status: document.getElementById("grafana-status").textContent})')
    r.check('network dashboard page: title, headline sentence and the raw reason as details', gf['title'] == f'Network dashboard · {SHOWCASE}' and gf['headline'] and gf['status'], gf)
    r.shot('60-network-dashboard')
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
    for step in (home, topology, empty_map, progress, tools, operations, advanced, polling, pages):
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
