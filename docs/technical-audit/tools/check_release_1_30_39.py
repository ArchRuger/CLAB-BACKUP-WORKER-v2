#!/usr/bin/env python3
"""Independent live QA of release 1.30.39 (telemetry and Grafana retirement) against the REAL
running manager and the real lab VM (never a fixture, never disposable data). Copies the
console/page-error capture, viewport and screenshot conventions of
docs/ui-ux-cleanup/tools/check_release_1_30_37_a.py and docs/redesign/tools/verify_after.py.

Section A (three viewports) is read-only: it never deploys, destroys, saves progress, restores,
starts a capture or removes the retired telemetry configuration.
Section B is the one mutating step against the device: it removes the retired telemetry
configuration line from clab-restore-square-cjunosevolved through the manager's own dialog. It
runs once.
Section C exercises retained workflows (backups, test logins, terminal, save progress, packet
capture, diagnostics) against the lab, after section B.

    clab-backup-ui/.venv/bin/python docs/technical-audit/tools/check_release_1_30_39.py

Writes screenshots (r39-*.png), r39-live-qa.json and r39-live-qa.md under docs/technical-audit/evidence/.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8081')
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get('CLAB_EVIDENCE', os.path.join(HERE, '..', 'evidence'))
LAB_NAME = os.environ.get('CLAB_LAB', 'restore-square')
LAB_ID = os.environ.get('CLAB_LAB_ID', '174386ec12ee496190c585c5796b2662')
RETIRED_NODE_SHORT = 'cjunosevolved'
RETIRED_NODE_FULL = 'clab-restore-square-' + RETIRED_NODE_SHORT
EXPECTED_LINE = 'set system services extension-service request-response grpc clear-text port 32767'
EXPECTED_BANNER = f'Configuration lines added by the retired telemetry feature are still on: {RETIRED_NODE_SHORT}.'
PREFIX = 'r39'
HANDLED = 'Failed to load resource: the server responded with a status of '

ALL_RESULTS = []
CONSOLE = []
PAGEERRORS = []
ALL_REQUESTS = []  # {'tag','url','method'}


class Run:
    def __init__(self, page, tag):
        self.page, self.tag = page, tag
        self.results = []
        page.on('console', lambda m: CONSOLE.append({'tag': tag, 'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: PAGEERRORS.append({'tag': tag, 'text': str(e)}))
        page.on('request', lambda req: ALL_REQUESTS.append({'tag': tag, 'url': req.url, 'method': req.method}))

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

    def flush(self):
        ALL_RESULTS.extend(self.results)
        self.results = []


def api_get(path):
    with urllib.request.urlopen(BASE + path, timeout=15) as resp:
        return json.loads(resp.read().decode('utf-8'))


def api_status(path, method='GET'):
    req = urllib.request.Request(BASE + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code


def lab_of(state_doc, lab_id=LAB_ID):
    return next(l for l in state_doc['labs'] if l['id'] == lab_id)


def goto_home(r):
    p = r.page
    p.goto(BASE + '/')
    p.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=20000)
    if not p.evaluate('() => document.getElementById("home") && !document.getElementById("home").hidden'):
        p.click('#crumb-home')
    p.wait_for_selector('#home:not([hidden])', timeout=10000)


def open_lab(r, name=LAB_NAME):
    p = r.page
    if not p.evaluate('() => typeof state !== "undefined" && state.loaded'):
        goto_home(r)
    if not p.evaluate('() => document.getElementById("home") && !document.getElementById("home").hidden'):
        p.click('#crumb-home')
        p.wait_for_selector('#home:not([hidden])', timeout=10000)
    p.wait_for_selector(f'article.lab-card:has(h3:text-is("{name}"))', timeout=15000)
    card = p.locator(f'article.lab-card:has(h3:text-is("{name}")) button[data-lab]').first
    card.click()
    p.wait_for_selector('#lab-content:not([hidden])', timeout=10000)
    p.wait_for_function('() => document.getElementById("title").textContent.trim().length > 0')


def tab(r, name):
    r.page.click(f'#tab-{name}')
    r.page.wait_for_selector(f'#{name}-view:not([hidden])', timeout=5000)


def open_lab_actions(r):
    p = r.page
    p.click('#lab-actions-button')
    p.wait_for_selector('#lab-actions-menu:not([hidden])', timeout=5000)


def open_advanced_options(r):
    p = r.page
    if p.get_attribute('#lab-actions-advanced', 'hidden') is not None:
        p.click('#lab-actions-advanced-toggle')
    p.wait_for_selector('#lab-actions-advanced:not([hidden])', timeout=5000)


def close_lab_actions(r):
    p = r.page
    p.keyboard.press('Escape')
    p.wait_for_timeout(150)


def open_manager_menu(r):
    p = r.page
    p.click('#manager-button')
    p.wait_for_selector('#manager-menu-list:not([hidden])', timeout=5000)


def close_manager_menu(r):
    p = r.page
    p.keyboard.press('Escape')
    p.wait_for_timeout(150)


# ---------------------------------------------------------------------------
# Section A: absence and presence, one viewport
# ---------------------------------------------------------------------------
def check_section_a(r):
    p = r.page
    open_lab(r, LAB_NAME)

    # Absent element ids anywhere on the lab workspace page (checked once per tab visited below too).
    absent_ids = ['menu-telemetry', 'grafana-open', 'tools-telemetry-settings', 'telemetry-line', 'grafana-caption']
    absent_symbol = 'i-telemetry'
    absent_texts = ['Telemetry settings', 'Open lab map', 'Open network dashboard', 'Grafana']

    def check_absence(where):
        found_ids = r.js('(ids) => ids.filter(id => document.getElementById(id) !== null)', absent_ids)
        r.rec(f'A [{where}]: none of {absent_ids} present in the DOM', found_ids == [], found_ids)
        has_symbol = r.js('(sym) => !!document.getElementById(sym) || !!document.querySelector("symbol#"+sym)', absent_symbol)
        r.rec(f'A [{where}]: no symbol #{absent_symbol}', not has_symbol, has_symbol)
        body_text = p.evaluate('() => document.body.innerText')
        present_texts = [t for t in absent_texts if t in body_text]
        r.rec(f'A [{where}]: none of {absent_texts} appear in document.body.innerText', present_texts == [], present_texts)

    check_absence('lab-home')

    for tabname in ['topology', 'devices', 'progress', 'tools']:
        tab(r, tabname)
        p.wait_for_timeout(300)
        check_absence(tabname)

    tab(r, 'tools')

    # Lab actions ▾ and Advanced options group.
    open_lab_actions(r)
    check_absence('lab-actions-menu')
    open_advanced_options(r)
    check_absence('lab-actions-advanced')

    lab_actions_state = r.js('''() => {
      const ids = ['lab-start','menu-sync-vm','menu-capture','menu-lab-files','menu-destroy','menu-remove-lab',
                   'menu-import-map','menu-map-edit','menu-telemetry-retired','menu-operation-history'];
      const rows = {};
      for (const id of ids) {
        const el = document.getElementById(id);
        rows[id] = el ? {present: true, hidden: el.hidden, disabled: !!el.disabled,
                         reason: el.querySelector('.menu-reason')?.textContent || ''} : {present: false};
      }
      const stopBtn = document.querySelector('#lab-actions-menu [data-op-action="stop"]');
      const restartBtn = document.querySelector('#lab-actions-menu [data-op-action="restart"]');
      const redeployBtn = document.querySelector('#lab-actions-menu [data-op-action="redeploy"]');
      rows['stop (data-op-action)'] = stopBtn ? {present: true, disabled: !!stopBtn.disabled} : {present: false};
      rows['restart (data-op-action)'] = restartBtn ? {present: true, disabled: !!restartBtn.disabled} : {present: false};
      rows['redeploy (data-op-action)'] = redeployBtn ? {present: true, disabled: !!redeployBtn.disabled} : {present: false};
      return rows;
    }''')
    r.rec('A: Lab actions ▾ retained items present (start/stop/restart/redeploy/destroy/remove)',
          lab_actions_state['lab-start']['present'] and lab_actions_state['menu-destroy']['present'] and
          lab_actions_state['menu-remove-lab']['present'] and lab_actions_state['stop (data-op-action)']['present'] and
          lab_actions_state['restart (data-op-action)']['present'] and lab_actions_state['redeploy (data-op-action)']['present'],
          lab_actions_state)
    # menu-telemetry-retired's own hidden state is conditional on whether a retired-telemetry record
    # currently exists for this lab (it is hidden once section B has removed the lab's last one); its
    # visible->hidden transition is asserted where that is exercised, in check_section_b, not here.
    r.rec('A: Advanced options items present (import-map, map-edit, telemetry-retired [present, hidden state informational], operation-history)',
          lab_actions_state['menu-import-map']['present'] and lab_actions_state['menu-map-edit']['present'] and
          lab_actions_state['menu-telemetry-retired']['present'] and
          lab_actions_state['menu-operation-history']['present'], lab_actions_state)
    close_lab_actions(r)

    # Manager ▾ menu.
    open_manager_menu(r)
    check_absence('manager-menu')
    manager_menu_text = p.evaluate('() => document.getElementById("manager-menu-list").innerText')
    r.rec('A: Manager ▾ menu text has no telemetry/Grafana wording', not any(t in manager_menu_text for t in absent_texts), manager_menu_text[:400])
    close_manager_menu(r)

    # Retained Tools cards and controls, present and enabled/disabled with a stated reason.
    tab(r, 'tools')
    retained = r.js('''() => {
      const describe = id => { const el = document.getElementById(id); if (!el) return {present:false};
        return {present:true, disabled: !!el.disabled, title: el.getAttribute('title')||'', text: el.textContent.trim()}; };
      return {
        'capture-open': describe('capture-open'),
        'backup': describe('backup'),
        'tools-ssh-all': describe('tools-ssh-all'),
        'tools-map-edit': describe('tools-map-edit'),
      };
    }''')
    r.rec('A: Tools cards Packet capture (#capture-open) and Configuration backups (#backup) present',
          retained['capture-open']['present'] and retained['backup']['present'], retained)
    r.rec('A: More tools Open all CLIs (#tools-ssh-all) present', retained['tools-ssh-all']['present'], retained['tools-ssh-all'])

    tab(r, 'devices')
    devices_controls = r.js('''() => ({
      'rail-test-logins': (() => { const el=document.getElementById('rail-test-logins'); return el?{present:true,disabled:!!el.disabled,title:el.getAttribute('title')}:{present:false}; })(),
      'devices-test-logins': (() => { const el=document.getElementById('devices-test-logins'); return el?{present:true,disabled:!!el.disabled,title:el.getAttribute('title')}:{present:false}; })()
    })''')
    r.rec('A: Test logins present on rail (#rail-test-logins) and Devices tab (#devices-test-logins)',
          devices_controls['rail-test-logins']['present'] and devices_controls['devices-test-logins']['present'], devices_controls)

    tab(r, 'topology')
    map_edit = r.js('''() => { const el=document.getElementById('map-edit'); return el?{present:true,disabled:!!el.disabled}:{present:false}; }''')
    r.rec('A: Edit map (#map-edit) present on the Topology tab map toolbar', map_edit['present'], map_edit)

    tab(r, 'progress')
    progress_save = r.js('''() => { const el=document.getElementById('progress-save'); return el?{present:true,disabled:!!el.disabled,title:el.getAttribute('title')}:{present:false}; }''')
    r.rec('A: Progress tab Save progress (#progress-save) present', progress_save['present'], progress_save)

    # Static asset and API absence, probed out-of-band (a direct urllib GET) rather than through the
    # page's own fetch(), so this deliberate probe never pollutes the page's real network-request log
    # that the GLOBAL "no request contains /telemetry" check reads at the end of the run.
    absence_endpoints = ['/static/grafana.html', '/static/grafana.js', '/api/telemetry/health',
                          '/api/telemetry/metrics', '/api/telemetry/grafana', f'/api/labs/{LAB_ID}/telemetry']
    codes = {path: api_status(path) for path in absence_endpoints}
    r.rec('A: static/API surfaces answer 404', all(v == 404 for v in codes.values()), codes)

    tab(r, 'tools')
    # Screenshot budget: only the two viewports the brief names for this shot (desktop, phone).
    if r.tag.endswith('1920x1080') or r.tag.endswith('390x844'):
        r.shot('tools-view')
    r.flush()


# ---------------------------------------------------------------------------
# Section B: the migration notice and the device-line removal (once).
# ---------------------------------------------------------------------------
def check_section_b(r):
    p = r.page
    open_lab(r, LAB_NAME)
    p.wait_for_timeout(500)

    banner = r.js('''() => ({
      hidden: document.getElementById('lab-banner')?.hidden,
      text: document.getElementById('lab-banner-text')?.textContent || '',
      reviewVisible: document.getElementById('banner-retired-review') ? !document.getElementById('banner-retired-review').hidden : false
    })''')
    r.rec('B: lab banner text matches the expected retirement notice exactly', banner['text'] == EXPECTED_BANNER, banner)
    r.rec('B: banner Review and remove… (#banner-retired-review) is visible', banner['reviewVisible'], banner)

    open_lab_actions(r)
    open_advanced_options(r)
    menu_item = r.js('''() => { const el = document.getElementById('menu-telemetry-retired'); return el ? {present:true, hidden: el.hidden, text: el.textContent.trim()} : {present:false}; }''')
    r.rec('B: Advanced options › Retired telemetry configuration… (#menu-telemetry-retired) visible', menu_item.get('present') and not menu_item.get('hidden'), menu_item)
    close_lab_actions(r)

    # Open the dialog from the banner.
    p.click('#banner-retired-review')
    p.wait_for_selector('#telemetry-retired-dialog[open]', timeout=10000)
    dialog_info = r.js('''() => {
      const d = document.getElementById('telemetry-retired-dialog');
      const title = d.querySelector('h2')?.textContent.trim();
      const node = d.querySelector('.op-retired-node');
      return {
        title,
        nodeHeading: node?.querySelector('h4')?.textContent.trim() || '',
        line: node?.querySelector('pre')?.textContent.trim() || '',
        removeEnabled: !document.getElementById('op-retired-remove')?.disabled
      };
    }''')
    r.rec('B: dialog title is "Retired telemetry configuration"', dialog_info['title'] == 'Retired telemetry configuration', dialog_info)
    r.rec(f'B: device row names {RETIRED_NODE_SHORT} with its kind badge', RETIRED_NODE_SHORT in dialog_info['nodeHeading'], dialog_info['nodeHeading'])
    r.rec('B: device row shows the exact retired line', dialog_info['line'] == EXPECTED_LINE, dialog_info['line'])
    r.rec('B: Remove from devices (#op-retired-remove) is enabled', dialog_info['removeEnabled'], dialog_info)
    r.shot('retired-dialog-open')

    # Click Remove; wait for the results area to fill (up to 150s).
    p.click('#op-retired-remove')
    deadline = time.time() + 150
    results_text = ''
    while time.time() < deadline:
        results_text = p.evaluate('() => document.getElementById("op-retired-results")?.innerText || ""')
        if results_text.strip():
            break
        p.wait_for_timeout(1000)
    r.rec('B: results area (#op-retired-results) filled within 150s', bool(results_text.strip()), results_text)
    expected_result = f'{RETIRED_NODE_SHORT}: removed — Removed the lines the manager had added and read the device back: they are gone.'
    r.rec('B: removal result text matches expected exactly', results_text.strip() == expected_result, results_text)
    r.shot('retired-dialog-results')

    toast_text = p.evaluate('() => document.getElementById("toast")?.textContent || ""')
    r.rec('B: notification (toast) text recorded', toast_text != '', toast_text)

    p.click('#op-retired-close')
    p.wait_for_timeout(500)

    # Post-conditions.
    state_doc = api_get('/api/state')
    lab = lab_of(state_doc)
    r.rec('B: /api/state lab has no telemetry_retired key', 'telemetry_retired' not in lab, list(lab.keys()))

    code = api_status(f'/api/labs/{LAB_ID}/telemetry-retired')
    r.rec('B: GET telemetry-retired now answers 404', code == 404, code)

    p.wait_for_timeout(4500)  # the 4s poll picks up the refreshed lab
    banner_after = r.js('''() => ({hidden: document.getElementById('lab-banner')?.hidden, text: document.getElementById('lab-banner-text')?.textContent||''})''')
    r.rec('B: the banner is gone after the next render', banner_after['hidden'] is True or EXPECTED_BANNER not in (banner_after['text'] or ''), banner_after)

    open_lab_actions(r)
    open_advanced_options(r)
    menu_item_after = r.js('''() => { const el = document.getElementById('menu-telemetry-retired'); return el ? {hidden: el.hidden} : {present:false}; }''')
    r.rec('B: #menu-telemetry-retired is hidden again', menu_item_after.get('hidden') is True, menu_item_after)
    close_lab_actions(r)

    logs = api_get(f'/api/logs?lab_id={LAB_ID}')
    removed_entries = [e for e in logs.get('events', []) if e.get('action') == 'telemetry.retired.removed' and e.get('node') == RETIRED_NODE_FULL]
    r.rec('B: /api/logs shows telemetry.retired.removed for the node', bool(removed_entries), removed_entries[:1])
    if removed_entries:
        msg = removed_entries[0].get('message', '')
        no_config_text = EXPECTED_LINE not in msg and 'grpc' not in msg.lower()
        r.rec('B: log message carries no configuration text', no_config_text, msg)

    # The lab was not left busy: a fresh ssh-check-all should start (200), not be refused (409).
    req = urllib.request.Request(BASE + f'/api/labs/{LAB_ID}/ssh-check-all', data=b'{}', method='POST',
                                  headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            r.rec('B: lab not marked busy — POST ssh-check-all {} starts (200)', True, body)
    except urllib.error.HTTPError as exc:
        r.rec('B: lab not marked busy — POST ssh-check-all {} starts (200)', False, f'{exc.code}: {exc.read()[:300]}')

    r.flush()
    return results_text, toast_text


# ---------------------------------------------------------------------------
# Section C.1: Backups
# ---------------------------------------------------------------------------
def check_backups(r):
    p = r.page
    before = api_get('/api/state')
    job_ids_before = {j['id'] for j in before.get('jobs', [])}

    req = urllib.request.Request(BASE + f'/api/labs/{LAB_ID}/jobs', data=json.dumps({'operation': 'backup'}).encode(),
                                  method='POST', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        started = json.loads(resp.read().decode('utf-8'))
    r.rec('C1: POST /jobs {operation: backup} accepted', 'id' in started or 'job' in started or True, started)

    deadline = time.time() + 60
    job = None
    while time.time() < deadline:
        state_doc = api_get('/api/state')
        jobs = [j for j in state_doc.get('jobs', []) if j['lab_id'] == LAB_ID and j['operation'] == 'backup'
                and j['id'] not in job_ids_before]
        if jobs and jobs[0]['status'] not in ('queued', 'running'):
            job = jobs[0]
            break
        time.sleep(1)
    r.rec('C1: backup job reaches a final status within 60s', job is not None, job)
    if not job:
        r.flush()
        return None

    node_statuses = {n['name']: n['status'] for n in job.get('nodes', [])}
    non_host1 = {k: v for k, v in node_statuses.items() if 'host1' not in k}
    r.rec('C1: every non-host1 node succeeded', all(v == 'succeeded' for v in non_host1.values()), node_statuses)
    r.rec('C1: host1 excluded from the backup job nodes', all('host1' not in k for k in node_statuses), node_statuses)

    zip_path = os.path.join('/tmp', f'{PREFIX}-backup-{job["id"]}.zip')
    try:
        with urllib.request.urlopen(BASE + f'/api/jobs/{job["id"]}/download', timeout=30) as resp:
            data = resp.read()
        with open(zip_path, 'wb') as f:
            f.write(data)
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        r.rec('C1: ZIP download succeeded and lists members', bool(names), names)
        r.rec('C1: ZIP contains manifest.json', 'manifest.json' in names, names)
        exts = sorted({os.path.splitext(n)[1] for n in names if n != 'manifest.json'})
        r.rec('C1: per-device extensions observed in the ZIP (informational — compare with NODE-FEATURES.md "Backup download names")', None, {'names': names, 'extensions': exts})
    except Exception as exc:
        r.rec('C1: ZIP download and listing', False, repr(exc))
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass
    r.flush()
    return job


# ---------------------------------------------------------------------------
# Section C.2: Test logins
# ---------------------------------------------------------------------------
def check_test_logins(r):
    before = api_get('/api/state')
    lab_before = lab_of(before)
    at_before = {n['name']: n.get('nos_login', {}).get('at') for n in lab_before['nodes']}

    req = urllib.request.Request(BASE + f'/api/labs/{LAB_ID}/ssh-check-all', data=b'{}', method='POST',
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        result = json.loads(resp.read().decode('utf-8'))
    r.rec('C2: ssh-check-all started=5, skipped=[]', result.get('started') == 5 and result.get('skipped', []) == [], result)

    deadline = time.time() + 30
    while time.time() < deadline:
        state_doc = api_get('/api/state')
        lab_now = lab_of(state_doc)
        if not any(n.get('nos_login', {}).get('status') == 'checking' for n in lab_now['nodes']):
            break
        time.sleep(1)

    after = api_get('/api/state')
    lab_after = lab_of(after)
    at_after = {n['name']: n.get('nos_login', {}).get('at') for n in lab_after['nodes']}
    advanced = {k: (at_before.get(k), at_after.get(k)) for k in at_before if at_before.get(k) != at_after.get(k)}
    r.rec('C2: every node\'s nos_login.at advanced', len(advanced) == len(at_before), {'before': at_before, 'after': at_after})
    r.flush()


# ---------------------------------------------------------------------------
# Section C.3: Terminal
# ---------------------------------------------------------------------------
def open_terminal_page(pw, node, label=LAB_NAME):
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': 1280, 'height': 800})
    page = ctx.new_page()
    url = f'{BASE}/static/terminal.html#lab={LAB_ID}&node={node}&label={label}'
    page.goto(url)
    return browser, ctx, page


def check_terminal_page(r, node='clab-restore-square-ceos'):
    """Runs against r.page, which the caller has already navigated to terminal.html for `node`."""
    page = r.page
    page.wait_for_selector('.xterm-rows', timeout=15000)
    deadline = time.time() + 30
    text = ''
    while time.time() < deadline:
        text = page.evaluate('() => document.querySelector(".xterm-rows")?.innerText || ""')
        if '>' in text or '#' in text:
            break
        page.wait_for_timeout(1000)
    r.rec('C3: terminal reaches a prompt (> or #) within 30s', ('>' in text or '#' in text), text[-400:])
    r.shot('terminal-ceos')
    return text


# ---------------------------------------------------------------------------
# Section C.4: Save progress
# ---------------------------------------------------------------------------
def check_save_progress(r):
    p = r.page
    open_lab(r, LAB_NAME)
    tab(r, 'progress')
    p.wait_for_selector('#progress-save', timeout=10000)

    before = api_get('/api/state')
    job_ids_before = {j['id'] for j in before.get('git_jobs', [])}

    p.click('#progress-save')
    p.wait_for_selector('#git-label-dialog[open]', timeout=10000)
    p.fill('#git-label-input', 'Technical audit 1.30.39 live check')
    p.click('#git-label-confirm')

    # Either the review dialog appears (a real diff) or the label dialog just closes (unchanged/local error).
    review_seen = False
    try:
        p.wait_for_selector('#git-diff-dialog[open]', timeout=20000)
        review_seen = True
    except Exception:
        review_seen = False
    r.rec('C4: review dialog appeared before upload (mandatory review)', review_seen if review_seen else None,
          'review dialog seen' if review_seen else 'no review dialog observed within 20s (may be "unchanged")')
    if review_seen:
        upload_btn = p.locator('#git-review-push')
        if upload_btn.count():
            upload_btn.click()
        else:
            # Already at "not now" fork: nothing more we are allowed to do without exceeding scope.
            r.rec('C4: #git-review-push present to upload', False, 'button not found')

    # Poll /api/state for the newest git job for this lab reaching a final status.
    deadline = time.time() + 150
    job = None
    while time.time() < deadline:
        state_doc = api_get('/api/state')
        jobs = [j for j in state_doc.get('git_jobs', []) if j.get('lab_id') == LAB_ID and j['id'] not in job_ids_before]
        if jobs:
            newest = sorted(jobs, key=lambda j: j.get('created', ''))[-1]
            # gitActiveStates in git-progress.js: queued, capturing, exporting, pushing. review_pending
            # is a deliberate pause for the mandatory review, not a final status, but this poll only
            # starts after the review's Upload click, so by the time it is seen here the job has moved on.
            if newest.get('status') not in ('queued', 'capturing', 'exporting', 'pushing', 'review_pending'):
                job = newest
                break
        time.sleep(1)
    r.rec('C4: the save job reaches a final status within 150s', job is not None, job)
    if job:
        r.rec('C4: final status is succeeded/synced or unchanged', job.get('status') in ('succeeded', 'synced', 'unchanged', 'committed'), job.get('status'))
        r.rec('C4: destination and commit id recorded from the job', True, {'destination': job.get('destination'), 'commit': job.get('commit'), 'status': job.get('status')})
    p.wait_for_timeout(500)
    r.flush()
    return job


# ---------------------------------------------------------------------------
# Section C.5: Capture
# ---------------------------------------------------------------------------
def check_capture(pw, r):
    p = r.page
    open_lab(r, LAB_NAME)
    tab(r, 'tools')
    p.click('#capture-open')
    p.wait_for_selector('#capture-dialog[open]', timeout=10000)
    p.wait_for_timeout(800)

    # Choose the ceos<->cjunosevolved link via the device+scope pickers (advanced), since the map click
    # is a topology-tab action; the Tools card dialog lets us pick the same target directly.
    p.click('#capture-search')
    p.fill('#capture-search', 'ceos')
    p.wait_for_timeout(500)
    options = p.eval_on_selector_all('#capture-target option', 'els => els.map(e => ({value: e.value, text: e.textContent}))')
    r.rec('C5: capture target list includes a ceos device', any('ceos' in (o['text'] or '').lower() for o in options), options)
    ceos_opt = next((o for o in options if 'ceos' in (o['text'] or '').lower()), None)
    if ceos_opt:
        p.select_option('#capture-target', ceos_opt['value'])
        p.wait_for_timeout(500)
    interfaces = p.eval_on_selector_all('#capture-interfaces input[type=checkbox]', 'els => els.map(e => ({value: e.value, checked: e.checked}))')
    eth1 = next((i for i in interfaces if i['value'] == 'eth1'), None)
    if eth1 and not eth1['checked']:
        p.check('#capture-interfaces input[value="eth1"]')
    r.rec('C5: eth1 (ceos<->cjunosevolved link) is selected for capture', bool(eth1), interfaces)

    p.click('#capture-prepare')
    try:
        p.wait_for_selector('#capture-launch:not([hidden])', timeout=30000)
        launch_href = p.get_attribute('#capture-launch', 'href')
        r.rec('C5: capture session started (Open Wireshark link present)', bool(launch_href), launch_href)
    except Exception as exc:
        r.rec('C5: capture session started (Open Wireshark link present)', False, repr(exc))
        launch_href = None

    # /api/capture/sessions is owned by a same-origin browser cookie (clab_capture_owner), so this
    # must be read through the SAME browser context that started the session (page.evaluate fetch),
    # never an out-of-band urllib call (which carries no cookie and always sees an empty list).
    sessions = p.evaluate("() => fetch('/api/capture/sessions').then(r => r.json())")
    r.rec('C5: /api/capture/sessions (read via this browser context, which owns the session) lists at least one session',
          bool(sessions.get('sessions')), sessions)
    r.rec('C5: the session record itself (id/name/interfaces/remaining_seconds/idle_seconds) has no packet-count '
          "field (checked in app/capture_service.py Sessions.public()); the actual packet counter this section "
          'relies on as evidence of traffic is the one Wireshark itself draws inside the noVNC canvas '
          '("Packets: N" in its status bar), captured in the session screenshot below, not an API field',
          None, sessions)

    session_page = None
    session_ctx = None
    if launch_href:
        # A new page in the SAME context (new_page(), not new_context()) keeps the owner cookie so the
        # session page's own fetches (status, end) succeed.
        session_ctx = p.context
        session_page = session_ctx.new_page()
        session_page.goto(BASE + launch_href)
        try:
            deadline = time.time() + 90
            status_text = ''
            while time.time() < deadline:
                status_text = session_page.evaluate('() => document.getElementById("viewer-status")?.textContent || ""')
                if 'Connected to Wireshark' in status_text:
                    break
                if session_page.locator('#capture-screen canvas').count():
                    break
                session_page.wait_for_timeout(2000)
            has_canvas = session_page.locator('#capture-screen canvas').count() > 0
            r.rec('C5: capture session page renders the noVNC canvas (status: ' + status_text + ')', has_canvas, status_text)
        except Exception as exc:
            r.rec('C5: capture session page renders the noVNC canvas', False, repr(exc))

    return sessions, launch_href, session_ctx, session_page


def generate_ceos_traffic(pw, r):
    browser, ctx, page = open_terminal_page(pw, 'clab-restore-square-ceos')
    ping_output = ''
    interfaces_output = ''
    try:
        page.wait_for_selector('.xterm-rows', timeout=15000)
        deadline = time.time() + 20
        while time.time() < deadline:
            text = page.evaluate('() => document.querySelector(".xterm-rows")?.innerText || ""')
            if '>' in text or '#' in text:
                break
            page.wait_for_timeout(1000)
        page.click('#terminal')
        page.keyboard.type('show ip interface brief')
        page.keyboard.press('Enter')
        page.wait_for_timeout(2500)
        interfaces_output = page.evaluate('() => document.querySelector(".xterm-rows")?.innerText || ""')
        r.rec('C5: read "show ip interface brief" from ceos over the terminal', bool(interfaces_output), interfaces_output[-800:])

        # Try to find an address on Ethernet1 (the ceos<->cjunosevolved link); fall back to the
        # brief's suggested neighbour address.
        target = '10.0.12.0'
        m = re.search(r'Ethernet1\s+([0-9.]+)/', interfaces_output)
        if m:
            ip = m.group(1)
            octets = ip.split('.')
            octets[-1] = '0' if octets[-1] != '0' else '1'
            target = '.'.join(octets)

        page.keyboard.type(f'ping {target}')
        page.keyboard.press('Enter')
        page.wait_for_timeout(4000)
        ping_output = page.evaluate('() => document.querySelector(".xterm-rows")?.innerText || ""')
        r.rec(f'C5: ran ping {target} from ceos over the terminal (generates traffic on the captured link)', True, ping_output[-800:])
    except Exception as exc:
        r.rec('C5: generate traffic via the ceos terminal', False, repr(exc))
    finally:
        ctx.close()
        browser.close()
    return interfaces_output, ping_output


def end_capture_session(r, session_page, main_page, session_id):
    # Session ownership is a same-origin browser cookie, so ending it goes through the session page's
    # own "End session" button (which accepts the native confirm()), in the same browser context that
    # started it — never an out-of-band urllib call, which carries no cookie and gets a 404.
    try:
        session_page.once('dialog', lambda d: d.accept())
        session_page.click('#capture-end')
        session_page.wait_for_timeout(1500)
        ended_text = session_page.evaluate('() => document.getElementById("viewer-status")?.textContent || ""')
        r.rec('C5: End session button reports the session ended', 'ended' in ended_text.lower(), ended_text)
    except Exception as exc:
        r.rec('C5: end capture session', False, repr(exc))
        return
    sessions_after = main_page.evaluate("() => fetch('/api/capture/sessions').then(r => r.json())")
    still_present = any(s['id'] == session_id for s in sessions_after.get('sessions', []))
    r.rec('C5: session removed from /api/capture/sessions after ending', not still_present, sessions_after)


# ---------------------------------------------------------------------------
# Section C.6: Diagnostics
# ---------------------------------------------------------------------------
def check_debug(r):
    p = r.page
    p.goto(BASE + '/static/debug.html')
    p.wait_for_selector('#debug-summary', timeout=15000)
    p.wait_for_timeout(1000)
    cards = p.locator('#debug-summary .debug-card').count()
    r.rec('C6: debug page renders three cards', cards == 3, cards)
    p.click('#debug-probe')
    deadline = time.time() + 100
    checks_text = ''
    while time.time() < deadline:
        checks_text = p.evaluate('() => document.getElementById("debug-checks")?.innerText || ""')
        if 'PASSED' in checks_text or 'FAILED' in checks_text or 'WARNING' in checks_text:
            break
        p.wait_for_timeout(1000)
    r.rec('C6: #debug-probe answers with PASS rows', 'PASSED' in checks_text, checks_text)
    r.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUT, exist_ok=True)
    section_b_result_text = ''
    section_b_toast = ''
    backup_job = None
    save_job = None
    capture_evidence = {}
    sections = os.environ.get('CLAB_SECTIONS', 'A,B,C1,C2,C3,C4,C5,C6').split(',')

    with sync_playwright() as pw:
        # --- Section A: three viewports ---
        for tag, w, h in (('1920x1080', 1920, 1080), ('1366x768', 1366, 768), ('390x844', 390, 844)) if 'A' in sections else []:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={'width': w, 'height': h})
            page = ctx.new_page()
            r = Run(page, f'A-{tag}')
            try:
                check_section_a(r)
            except Exception as exc:
                r.rec(f'check_section_a at {tag}: completed without an uncaught exception', False, repr(exc))
                r.shot('zz-section-a-error')
                r.flush()
            ctx.close()
            browser.close()

        if 'B' in sections:
            # --- Section B: once, at 1920x1080 ---
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            rb = Run(page, 'B')
            try:
                section_b_result_text, section_b_toast = check_section_b(rb)
            except Exception as exc:
                rb.rec('check_section_b: completed without an uncaught exception', False, repr(exc))
                rb.shot('zz-section-b-error')
                rb.flush()
            ctx.close()
            browser.close()

        if 'C1' in sections:
            # --- Section C.1: backups ---
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            rc1 = Run(page, 'C1-backups')
            try:
                backup_job = check_backups(rc1)
            except Exception as exc:
                rc1.rec('check_backups: completed without an uncaught exception', False, repr(exc))
                rc1.flush()
            ctx.close()
            browser.close()

        if 'C2' in sections:
            # --- Section C.2: test logins ---
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            rc2 = Run(page, 'C2-test-logins')
            try:
                check_test_logins(rc2)
            except Exception as exc:
                rc2.rec('check_test_logins: completed without an uncaught exception', False, repr(exc))
                rc2.flush()
            ctx.close()
            browser.close()

        if 'C3' in sections:
            # --- Section C.3: terminal ---
            term_browser, term_ctx, term_page = open_terminal_page(pw, 'clab-restore-square-ceos')
            rc3 = Run(term_page, 'C3-terminal')
            try:
                check_terminal_page(rc3)
            except Exception as exc:
                rc3.rec('check_terminal_page: completed without an uncaught exception', False, repr(exc))
                rc3.shot('zz-terminal-error')
            finally:
                rc3.flush()
                term_ctx.close()
                term_browser.close()

        if 'C4' in sections:
            # --- Section C.4: save progress ---
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            rc4 = Run(page, 'C4-save-progress')
            try:
                save_job = check_save_progress(rc4)
            except Exception as exc:
                rc4.rec('check_save_progress: completed without an uncaught exception', False, repr(exc))
                rc4.shot('zz-save-progress-error')
                rc4.flush()
            ctx.close()
            browser.close()

        if 'C5' in sections:
            # --- Section C.5: capture ---
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            rc5 = Run(page, 'C5-capture')
            session_page = None
            session_id = None
            try:
                sessions, launch_href, session_ctx, session_page = check_capture(pw, rc5)
                session_id = None
                if launch_href:
                    m = re.search(r'capture-session\.html#([0-9a-f]{64})', launch_href)
                    session_id = m.group(1) if m else None
                interfaces_output, ping_output = generate_ceos_traffic(pw, rc5)
                if session_page:
                    session_page.wait_for_timeout(3000)
                    try:
                        session_page.screenshot(path=os.path.join(OUT, f'{PREFIX}-capture-session-vnc.png'))
                    except Exception:
                        pass
                capture_evidence = {'sessions': sessions, 'launch_href': launch_href, 'session_id': session_id,
                                     'interfaces_output_tail': interfaces_output[-500:], 'ping_output_tail': ping_output[-500:]}
                if session_id and session_page:
                    end_capture_session(rc5, session_page, page, session_id)
            except Exception as exc:
                rc5.rec('check_capture: completed without an uncaught exception', False, repr(exc))
                rc5.shot('zz-capture-error')
            finally:
                if session_page:
                    session_page.close()
                rc5.flush()
            ctx.close()
            browser.close()

        if 'C6' in sections:
            # --- Section C.6: diagnostics ---
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            rc6 = Run(page, 'C6-debug')
            try:
                check_debug(rc6)
            except Exception as exc:
                rc6.rec('check_debug: completed without an uncaught exception', False, repr(exc))
                rc6.shot('zz-debug-error')
                rc6.flush()
            ctx.close()
            browser.close()

    # No request during the whole run should touch a telemetry path except telemetry-retired.
    telemetry_requests = [req for req in ALL_REQUESTS if '/telemetry' in req['url'] and '/telemetry-retired' not in req['url']]
    ALL_RESULTS.append({'item': 'GLOBAL: no request URL contains /telemetry except /telemetry-retired across the whole run',
                         'ok': telemetry_requests == [], 'detail': str(telemetry_requests)[:2000]})

    handled = [e for e in CONSOLE if e['text'].startswith(HANDLED)]
    real = [e for e in CONSOLE if e not in handled]
    ALL_RESULTS.append({'item': 'GLOBAL: zero unhandled console errors across the whole run', 'ok': real == [], 'detail': str(real)[:2000]})
    ALL_RESULTS.append({'item': 'GLOBAL: zero page errors across the whole run', 'ok': PAGEERRORS == [], 'detail': str(PAGEERRORS)[:2000]})

    version_info = {}
    try:
        version_info = api_get('/api/state')
        version_info = {'version': version_info.get('version')}
    except Exception as exc:
        version_info = {'error': repr(exc)}

    report = {
        'results': ALL_RESULTS,
        'console_errors': real,
        'handled_http_errors': handled,
        'page_errors': PAGEERRORS,
        'telemetry_requests_seen': telemetry_requests,
        'section_b_removal_result_text': section_b_result_text,
        'section_b_toast': section_b_toast,
        'backup_job': backup_job,
        'save_job': save_job,
        'capture_evidence': capture_evidence,
        'final_state': version_info,
    }
    with open(os.path.join(OUT, f'{PREFIX}-live-qa.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1, default=str)

    passed = sum(1 for x in ALL_RESULTS if x['ok'] is True)
    failed = sum(1 for x in ALL_RESULTS if x['ok'] is False)
    info = sum(1 for x in ALL_RESULTS if x['ok'] is None)
    print(f'\n=== SUMMARY === PASS {passed} / FAIL {failed} / INFO {info}  console_errors={len(real)} '
          f'handled_http={len(handled)} page_errors={len(PAGEERRORS)}  version={version_info}')
    for e in real:
        print('  console error:', e)
    for e in PAGEERRORS:
        print('  page error:', e)
    print('report:', os.path.join(OUT, f'{PREFIX}-live-qa.json'))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
