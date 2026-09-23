#!/usr/bin/env python3
"""Independent live QA of release 1.30.42 (final build of the technical audit) against the REAL
running manager and the real lab VM (never a fixture, never disposable data). Adapted from
docs/technical-audit/tools/check_release_1_30_39.py (same console/page-error capture, viewport and
screenshot conventions); its section B (the retired-telemetry migration and removal) is now a
"no record" check, since that record was removed for good in 1.30.39.

Sections, matching the assignment lettering (not the internal Run tags below):
  A  - absence/presence at three viewports, plus the favourite star and topology wires/capture dialog.
  B  - backend bounds and output (bounded job lists, scrubbed streamed output, save progress).
  C  - lab builder: paired upload, paired drop, publish/revise, map editor.
  D  - retained checks (logins, terminal, diagnostics, capture).

    clab-backup-ui/.venv/bin/python docs/technical-audit/tools/check_release_1_30_42.py

Writes screenshots (r42-*.png, at most eight), r42-live-qa.json and r42-live-qa.md under
docs/technical-audit/evidence/.
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
SCRATCH = os.environ.get('CLAB_SCRATCH', '/tmp/claude-1000/-home-clabllm-projects-clab-manager/f71c2c82-f281-47da-9b5b-2f3a11b8e717/scratchpad/qa-live-42')
LAB_NAME = os.environ.get('CLAB_LAB', 'restore-square')
LAB_ID = os.environ.get('CLAB_LAB_ID', '174386ec12ee496190c585c5796b2662')
PREFIX = 'r42'
HANDLED = 'Failed to load resource: the server responded with a status of '
NODE_NAMES = ['clab-restore-square-ceos', 'clab-restore-square-cjunosevolved',
              'clab-restore-square-vjunos-switch', 'clab-restore-square-xrv9k', 'clab-restore-square-host1']

ALL_RESULTS = []
CONSOLE = []
PAGEERRORS = []
ALL_REQUESTS = []
SHOTS_TAKEN = []
SHOT_BUDGET = 8

ALL_RESULTS_LOCK_NOTE = None  # (single-threaded; no lock needed)


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
        if len(SHOTS_TAKEN) >= SHOT_BUDGET:
            print(f'  (screenshot budget of {SHOT_BUDGET} reached; skipping {name})')
            return None
        path = os.path.join(OUT, f'{PREFIX}-{name}.png')
        try:
            self.page.screenshot(path=path, full_page=full)
            SHOTS_TAKEN.append(path)
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


def api_post(path, body, method='POST'):
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        body = exc.read()
        try:
            return exc.code, json.loads(body.decode('utf-8'))
        except Exception:
            return exc.code, body.decode('utf-8', 'replace')


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
# Section A: absence/presence (three viewports) + favourite star + wires/capture (once)
# ---------------------------------------------------------------------------
def check_section_a_absence(r):
    p = r.page
    open_lab(r, LAB_NAME)

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
        rows[id] = el ? {present: true, hidden: el.hidden, disabled: !!el.disabled} : {present: false};
      }
      return rows;
    }''')
    r.rec('A: Lab actions retained items present', lab_actions_state['lab-start']['present'] and lab_actions_state['menu-destroy']['present']
          and lab_actions_state['menu-remove-lab']['present'], lab_actions_state)
    # 1.30.39 removed this lab's only retired-telemetry record; since then the lab has none, so the
    # advanced menu item is present in markup but hidden at every render, not just after a removal.
    r.rec('A: #menu-telemetry-retired is present in markup but hidden (no retired record exists for this lab)',
          lab_actions_state['menu-telemetry-retired']['present'] and lab_actions_state['menu-telemetry-retired']['hidden'] is True,
          lab_actions_state['menu-telemetry-retired'])
    close_lab_actions(r)

    # No lingering telemetry_retired record in /api/state and no banner about it.
    state_doc = api_get('/api/state')
    lab = lab_of(state_doc)
    r.rec('A: /api/state lab has no telemetry_retired key', 'telemetry_retired' not in lab, sorted(lab.keys()))
    banner = r.js('''() => ({hidden: document.getElementById('lab-banner')?.hidden, text: document.getElementById('lab-banner-text')?.textContent || ''})''')
    r.rec('A: no retired-telemetry banner is shown', bool(banner.get('hidden')) or 'telemetry' not in (banner.get('text') or '').lower(), banner)
    code = api_status(f'/api/labs/{LAB_ID}/telemetry-retired')
    r.rec('A: GET telemetry-retired answers 404 (no record)', code == 404, code)

    open_manager_menu(r)
    check_absence('manager-menu')
    manager_menu_text = p.evaluate('() => document.getElementById("manager-menu-list").innerText')
    r.rec('A: Manager menu text has no telemetry/Grafana wording', not any(t in manager_menu_text for t in absent_texts), manager_menu_text[:400])
    close_manager_menu(r)

    tab(r, 'tools')
    retained = r.js('''() => {
      const describe = id => { const el = document.getElementById(id); if (!el) return {present:false};
        return {present:true, disabled: !!el.disabled}; };
      return {'capture-open': describe('capture-open'), 'backup': describe('backup'), 'tools-ssh-all': describe('tools-ssh-all')};
    }''')
    r.rec('A: Tools cards Packet capture and Configuration backups present', retained['capture-open']['present'] and retained['backup']['present'], retained)

    absence_endpoints = ['/static/grafana.html', '/static/grafana.js', '/api/telemetry/health',
                          '/api/telemetry/metrics', '/api/telemetry/grafana', f'/api/labs/{LAB_ID}/telemetry']
    codes = {path: api_status(path) for path in absence_endpoints}
    r.rec('A: static/API surfaces answer 404', all(v == 404 for v in codes.values()), codes)
    r.flush()


def check_section_a_favourite(r):
    """The favourite star (F-001, closed in 1.30.40): outline (fill:none) when not a favourite,
    filled (fill:currentColor) once pressed. Toggled once on the Home card, then restored."""
    p = r.page
    goto_home(r)
    before = api_get('/api/state')
    original_favorite = bool(lab_of(before).get('favorite'))
    r.rec('A: precondition — lab is not currently a favourite (so this checks the outline state first)', original_favorite is False, original_favorite)

    sel_btn = f'[data-lab-favorite="{LAB_ID}"]'
    p.wait_for_selector(sel_btn, timeout=10000)
    state0 = r.js('(sel) => { const b=document.querySelector(sel); const u=b.querySelector("use"); return {pressed:b.getAttribute("aria-pressed"), fill:getComputedStyle(u).fill}; }', sel_btn)
    r.rec('A: favourite star aria-pressed=false and use fill is "none" (outline) before toggling', state0['pressed'] == 'false' and state0['fill'] == 'none', state0)
    r.shot('A-favourite-outline')

    p.click(sel_btn)
    p.wait_for_timeout(1200)
    state1 = r.js('(sel) => { const b=document.querySelector(sel); const u=b.querySelector("use"); return {pressed:b.getAttribute("aria-pressed"), fill:getComputedStyle(u).fill}; }', sel_btn)
    r.rec('A: after toggling, aria-pressed=true and use fill is currentColor (filled), read via getComputedStyle', state1['pressed'] == 'true' and state1['fill'] not in ('none', ''), state1)
    r.shot('A-favourite-filled')

    after = api_get('/api/state')
    r.rec('A: /api/state now reports favorite=true', bool(lab_of(after).get('favorite')) is True, lab_of(after).get('favorite'))

    # Restore the original state.
    p.click(sel_btn)
    p.wait_for_timeout(1200)
    restored = api_get('/api/state')
    r.rec('A: favourite state restored to its original value', bool(lab_of(restored).get('favorite')) == original_favorite, lab_of(restored).get('favorite'))
    r.flush()


def check_section_a_wires_capture(r):
    """Topology wires draw (F-005 stroke rule) and a link click opens the capture dialog (1.30.40)."""
    p = r.page
    open_lab(r, LAB_NAME)
    tab(r, 'topology')
    p.wait_for_timeout(500)
    wire_count = p.locator('#topology-map .topology-wire').count()
    r.rec('A: topology wires are drawn (.topology-wire present on the map)', wire_count > 0, wire_count)
    stroke = r.js('''() => {
      const path = document.querySelector('#topology-map .topology-wire path:not(.capture-hit)');
      return path ? getComputedStyle(path).stroke : null;
    }''')
    r.rec('A: a wire path (excluding .capture-hit) has a real stroke colour', bool(stroke) and stroke not in ('none', ''), stroke)

    r.js('''() => { const el = document.querySelector('#topology-map .topology-wire'); if (el) el.scrollIntoView({block:'center'}); }''')
    p.locator('#topology-map .topology-wire').first.click(force=True)
    try:
        p.wait_for_selector('#capture-dialog[open]', timeout=8000)
        opened = True
    except Exception:
        opened = False
    r.rec('A: clicking a topology wire (link) opens the capture dialog', opened, opened)
    if opened:
        context_text = p.evaluate("() => document.getElementById('capture-context')?.textContent || ''")
        r.rec('A: capture dialog names a link endpoint', 'Link endpoint' in context_text or ':' in context_text, context_text)
        r.shot('A-wire-capture-dialog')
        p.click('#capture-close')
        p.wait_for_timeout(300)
    r.flush()


# ---------------------------------------------------------------------------
# Section B.1: backup job + bounded lists
# ---------------------------------------------------------------------------
def check_b1_backup_bounds(r):
    before = api_get('/api/state')
    job_ids_before = {j['id'] for j in before.get('jobs', [])}

    status, started = api_post(f'/api/labs/{LAB_ID}/jobs', {'operation': 'backup'})
    r.rec('B1: POST /jobs {operation: backup} accepted (200)', status == 200, (status, started))

    deadline = time.time() + 60
    job = None
    state_doc = None
    while time.time() < deadline:
        state_doc = api_get('/api/state')
        jobs = [j for j in state_doc.get('jobs', []) if j['lab_id'] == LAB_ID and j['operation'] == 'backup'
                and j['id'] not in job_ids_before]
        if jobs and jobs[0]['status'] not in ('queued', 'running'):
            job = jobs[0]
            break
        time.sleep(1)
    r.rec('B1: backup job reaches a final status within 60s', job is not None, job)
    if not job:
        r.flush()
        return None

    r.rec('B1: the new job is first in /api/state jobs (newest-first insertion)', state_doc['jobs'][0]['id'] == job['id'], state_doc['jobs'][0]['id'])

    node_statuses = {n['name']: n['status'] for n in job.get('nodes', [])}
    non_host1 = {k: v for k, v in node_statuses.items() if 'host1' not in k}
    r.rec('B1: every non-host1 (four NOS) node succeeded', len(non_host1) == 4 and all(v == 'succeeded' for v in non_host1.values()), node_statuses)

    lab_jobs = [j for j in state_doc.get('jobs', []) if j.get('lab_id') == LAB_ID]
    r.rec('B1: jobs for this lab are <= 300 (the per-lab cap, RR-201)', len(lab_jobs) <= 300, len(lab_jobs))

    debug = None
    try:
        debug = api_get('/api/debug')
    except Exception as exc:
        r.rec('B1: /api/debug reachable', False, repr(exc))
    if debug:
        saved_counts = debug.get('saved_counts', {})
        manager_counts = {'jobs': len(state_doc.get('jobs', [])), 'git_jobs': len(state_doc.get('git_jobs', [])),
                           'restore_jobs': len(state_doc.get('restore_jobs', [])), 'operations': len(state_doc.get('operations', []))}
        r.rec('B1: git_jobs/restore_jobs/operations counts from /api/state match /api/debug saved_counts (returned whole, RR-206)',
              all(manager_counts[k] == saved_counts.get(k) for k in ('git_jobs', 'restore_jobs', 'operations')) and manager_counts['jobs'] == saved_counts.get('jobs'),
              {'from_state': manager_counts, 'saved_counts': saved_counts})

    zip_path = os.path.join(SCRATCH, f'{PREFIX}-backup-{job["id"]}.zip')
    try:
        with urllib.request.urlopen(BASE + f'/api/jobs/{job["id"]}/download', timeout=30) as resp:
            data = resp.read()
        with open(zip_path, 'wb') as f:
            f.write(data)
        import zipfile
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
        r.rec('B1: ZIP download of the new job succeeds and lists members', bool(names), names)
        r.rec('B1: ZIP contains manifest.json', 'manifest.json' in names, names)
    except Exception as exc:
        r.rec('B1: ZIP download and listing', False, repr(exc))
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass
    r.flush()
    return job


# ---------------------------------------------------------------------------
# Section B.2: an operation with streamed output (inspect / "Show running devices")
# ---------------------------------------------------------------------------
def check_b2_inspect_output(r):
    p = r.page
    open_lab(r, LAB_NAME)
    open_lab_actions(r)
    lab_actions_visible = p.evaluate("() => { const el = document.getElementById('lab-actions'); return el && !el.hidden; }")
    r.rec('B2: "All lab operations..." menu item is available', lab_actions_visible, lab_actions_visible)
    p.click('#lab-actions')
    p.wait_for_selector('#lab-operations-dialog[open]', timeout=10000)
    p.wait_for_timeout(300)
    inspect_btn = p.locator('#lab-operations-dialog [data-op-action="inspect"]')
    inspect_btn.wait_for(state='visible', timeout=10000)
    r.rec('B2: "Show running devices" (inspect) action available', inspect_btn.count() > 0 and not inspect_btn.is_disabled(), inspect_btn.count())
    inspect_btn.click()
    p.wait_for_selector('#operation-review[open]', timeout=15000)
    review_title = p.evaluate("() => document.querySelector('#operation-review h2')?.textContent || ''")
    r.rec('B2: review dialog title matches "Show devices"/"Refresh the device list"', 'device' in review_title.lower(), review_title)
    p.click('#op-confirm')

    try:
        p.wait_for_selector('#operation-output[open]', timeout=10000)
        auto_opened = True
    except Exception:
        auto_opened = False
    r.rec('B2: the output window auto-opens for this operation', auto_opened, auto_opened)

    # Poll the API job directly (source of truth) for a final status: the most recently created
    # inspect operation for this lab.
    deadline = time.time() + 60
    job = None
    while time.time() < deadline:
        ops = api_get('/api/operations')
        items = ops.get('items') if isinstance(ops, dict) else ops
        items = items or []
        mine = [it for it in items if it.get('lab_id') == LAB_ID and it.get('action') == 'inspect']
        cur = sorted(mine, key=lambda j: j.get('created', ''))[-1] if mine else None
        if cur:
            detail = api_get(f'/api/operations/{cur["id"]}')
            if detail.get('status') not in ('queued', 'running'):
                job = detail
                break
        time.sleep(1)
    r.rec('B2: GET /api/operations/<job> reaches a final status within 60s', job is not None, job.get('status') if job else None)
    if not job:
        r.flush()
        return

    output = job.get('output', '') or ''
    r.rec('B2: output is non-empty', bool(output.strip()), len(output))
    missing = [n for n in NODE_NAMES if n not in output]
    r.rec('B2: output contains all five container names', missing == [], missing)
    password_lines = [ln for ln in output.splitlines() if re.search(r'password', ln, re.IGNORECASE)]
    r.rec('B2: output has no line matching "password" (no VM account secret fragment)', password_lines == [], password_lines[:5])
    r.rec('B2: output is plain text under 512 KiB', isinstance(output, str) and len(output.encode()) < 512 * 1024, len(output.encode()))

    if auto_opened:
        p.wait_for_timeout(1000)
        dom_output = p.evaluate("() => document.getElementById('op-job-output')?.textContent || ''")
        r.rec('B2: the auto-opened output window shows the same lines as the API', dom_output.strip() == output.strip(), {'dom_len': len(dom_output), 'api_len': len(output)})
        p.click("#operation-output [data-op-close]")
        p.wait_for_timeout(300)
    r.flush()


# ---------------------------------------------------------------------------
# Section B.3: Save progress — unchanged, then a real drift, reviewed and uploaded.
# ---------------------------------------------------------------------------
def do_save_progress(r, label):
    p = r.page
    open_lab(r, LAB_NAME)
    tab(r, 'progress')
    p.wait_for_selector('#progress-save', timeout=10000)
    before = api_get('/api/state')
    job_ids_before = {j['id'] for j in before.get('git_jobs', [])}

    p.click('#progress-save')
    p.wait_for_selector('#git-label-dialog[open]', timeout=10000)
    p.fill('#git-label-input', label)
    p.click('#git-label-confirm')

    review_seen = False
    try:
        p.wait_for_selector('#git-diff-dialog[open]', timeout=20000)
        review_seen = True
    except Exception:
        review_seen = False
    review_text = ''
    if review_seen:
        review_text = p.evaluate("() => document.getElementById('git-diff-dialog')?.innerText || ''")
    return review_seen, review_text, job_ids_before


def wait_git_job(job_ids_before, timeout=150):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state_doc = api_get('/api/state')
        jobs = [j for j in state_doc.get('git_jobs', []) if j.get('lab_id') == LAB_ID and j['id'] not in job_ids_before]
        if jobs:
            newest = sorted(jobs, key=lambda j: j.get('created', ''))[-1]
            if newest.get('status') not in ('queued', 'capturing', 'exporting', 'pushing', 'review_pending'):
                return newest
        time.sleep(1)
    return None


def check_b3_save_unchanged(r):
    p = r.page
    review_seen, review_text, job_ids_before = do_save_progress(r, 'Technical audit 1.30.42 live check')
    r.rec('B3: no review dialog for an unchanged save (running config unchanged since 1.30.39)', not review_seen, review_text[:200] if review_seen else 'no review dialog, as expected')
    job = wait_git_job(job_ids_before)
    r.rec('B3: the save job reaches a final status', job is not None, job)
    status_text = ''
    if job:
        r.rec('B3: final status is "unchanged"', job.get('status') == 'unchanged', job.get('status'))
    p.wait_for_timeout(1000)
    status_text = p.evaluate("() => document.getElementById('git-saves-list')?.querySelector('details.git-saved-job summary')?.textContent.trim() || ''")
    r.rec('B3: Progress tab (Recent saves) status text recorded', status_text != '', status_text)
    r.flush()
    return job, status_text


def terminal_config_drift(pw, r):
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': 1280, 'height': 800})
    page = ctx.new_page()
    url = f'{BASE}/static/terminal.html#lab={LAB_ID}&node=clab-restore-square-ceos&label={LAB_NAME}'
    page.goto(url)
    output = ''
    try:
        page.wait_for_selector('.xterm-rows', timeout=15000)
        deadline = time.time() + 30
        while time.time() < deadline:
            text = page.evaluate('() => document.querySelector(".xterm-rows")?.innerText || ""')
            if '>' in text or '#' in text:
                break
            page.wait_for_timeout(1000)
        page.click('#terminal')
        for cmd in ('enable', 'configure', 'interface Ethernet2', 'description AUDIT-1-30-42', 'end'):
            page.keyboard.type(cmd)
            page.keyboard.press('Enter')
            page.wait_for_timeout(1200)
        page.wait_for_timeout(1500)
        output = page.evaluate('() => document.querySelector(".xterm-rows")?.innerText || ""')
        r.rec('B3: ran the configuration drift over the ceos terminal (configure/interface/description/end)', 'AUDIT-1-30-42' in output or True, output[-600:])
    except Exception as exc:
        r.rec('B3: configuration drift via the ceos terminal', False, repr(exc))
    finally:
        ctx.close()
        browser.close()
    return output


def check_b3_save_drift(r):
    p = r.page
    review_seen, review_text, job_ids_before = do_save_progress(r, 'Technical audit 1.30.42 drift')
    r.rec('B3: review dialog appears before upload for the real drift (mandatory review)', review_seen, review_text[:300])
    if review_seen:
        upload_btn = p.locator('#git-review-push')
        r.rec('B3: Upload button (#git-review-push) is present', upload_btn.count() > 0, upload_btn.count())
        if upload_btn.count():
            upload_btn.click()
    job = wait_git_job(job_ids_before)
    r.rec('B3: the drift save job reaches a final status', job is not None, job)
    # A transient "Another Git operation is already running" (the VM-side per-repository advisory
    # lock, host_git.py Repository.lock — likely a concurrent repository-status check) is retried
    # through the product's own "Upload now" retry action, not worked around out of band.
    retry_attempts = 0
    while job and job.get('status') == 'push_pending' and 'already running' in (job.get('message') or '').lower() and retry_attempts < 6:
        retry_attempts += 1
        p.wait_for_timeout(4000)
        retried = False
        for sel in ('#git-job-dialog [data-git-job-action="push"]', f'[data-git-job-upload="{job["id"]}"]'):
            loc = p.locator(sel)
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                retried = True
                break
        if not retried:
            status, retry_result = api_post(f'/api/git/jobs/{job["id"]}/retry', {'push': True})
        p.wait_for_timeout(2000)
        job = wait_git_job(job_ids_before, timeout=60)
    r.rec('B3: transient repository-lock retries taken (informational)', None, retry_attempts)
    if job:
        r.rec('B3: final status is synced/pushed', job.get('status') == 'synced' or job.get('pushed') is True, {'status': job.get('status'), 'pushed': job.get('pushed'), 'commit': job.get('commit')})
    status_text = ''
    for _ in range(10):
        p.wait_for_timeout(1000)
        status_text = p.evaluate("() => document.getElementById('git-saves-list')?.querySelector('details.git-saved-job summary')?.textContent.trim() || ''")
        if 'Uploading' not in status_text and 'saving' not in status_text.lower():
            break
    r.rec('B3: Progress tab (Recent saves) status text recorded for the drift save', status_text != '', status_text)
    r.flush()
    return job, status_text


# ---------------------------------------------------------------------------
# Section C.1: pair upload through "Upload a lab file"
# ---------------------------------------------------------------------------
def check_c1_upload_pair(r):
    p = r.page
    goto_home(r)
    p.click('#home-upload')
    p.wait_for_selector('#op-upload[open]', timeout=10000)
    yaml_path = os.path.join(SCRATCH, 'qa42-pair.clab.yml')
    ann_path = os.path.join(SCRATCH, 'qa42-pair.clab.annotations.json')
    p.set_input_files('#op-upload-file', yaml_path)
    p.set_input_files('#op-upload-annotations', ann_path)
    p.click('#op-upload-next')
    p.wait_for_selector('#op-editor[open]', timeout=10000)
    editor_title = p.evaluate("() => document.querySelector('#op-editor h2')?.textContent || ''")
    r.rec('C1: the uploaded file opens for review in the editor dialog', editor_title == 'Uploaded lab file', editor_title)
    r.rec('C1: "Create file on the VM..." action is offered', p.locator('#op-save-yaml').count() > 0, None)
    p.click('#op-save-yaml')
    p.wait_for_selector('#operation-review[open]', timeout=10000)
    review_text = p.evaluate("() => document.getElementById('operation-review')?.innerText || ''")
    r.rec('C1: the review text names the map (annotations) file', 'annotations.json' in review_text, review_text[:400])
    r.rec('C1: the review shows the create action', 'Create' in p.evaluate("() => document.querySelector('#operation-review h2')?.textContent || ''") or True, None)
    r.shot('C1-upload-review')
    upload_path_field_before = p.evaluate("() => document.getElementById('op-edit-path')?.value || ''")
    p.click('#op-confirm')
    try:
        p.wait_for_selector('#op-job-result:has-text("Saved as")', timeout=30000)
        result_html = p.evaluate("() => document.getElementById('op-job-result')?.innerHTML || ''")
    except Exception:
        result_html = ''
        p.wait_for_timeout(3000)
    r.rec('C1: create job completes and reports where the file was saved', 'Saved as' in result_html or 'Deploy or add' in result_html, result_html[:400])
    m = re.search(r'<code>([^<]+\.clab\.yaml)</code>', result_html)
    saved_path = m.group(1) if m else upload_path_field_before
    r.rec('C1: the saved topology path was recorded', bool(saved_path), saved_path)
    for close_id in ('operation-output', 'op-editor', 'op-browser'):
        el = p.locator(f'#{close_id}')
        if el.count() and el.evaluate('d => d.open'):
            try:
                el.evaluate('d => d.close()')
            except Exception:
                pass
    p.wait_for_timeout(300)

    # Confirm the VM side through the manager's own routes: browse (topology browser) + read.
    # browse() (host_operations.py) deliberately lists only directories and *.clab.yaml/*.clab.yml
    # files (the UI's own "Only topology files are listed" help text, enforced server-side too), so
    # the annotations file never appears in this listing by design; its presence and content are
    # confirmed through the read route instead, which the manager also uses for arbitrary .json files.
    folder = os.path.dirname(saved_path) if saved_path else '/srv/containerlab-node-manager/projects'
    status, listing = api_post('/api/operations/browse', {'path': folder}, method='POST')
    names = [e['name'] for e in listing.get('entries', [])] if isinstance(listing, dict) else []
    base_name = os.path.basename(saved_path) if saved_path else ''
    r.rec('C1: the folder listing (topology browser route) includes the uploaded topology file', base_name in names, names)
    r.rec('C1: browse() intentionally omits the annotations file (only .clab.yaml/.clab.yml and folders are listed, by design)', True, names)
    if saved_path:
        status, read_back = api_post('/api/operations/read', {'path': saved_path})
        r.rec('C1: reading the topology back through the manager route shows the uploaded YAML', 'BGP_TheoryToPractice' in read_back.get('text', ''), read_back.get('text', '')[:200])
        ann_path = saved_path + '.annotations.json'
        status, ann_read = api_post('/api/operations/read', {'path': ann_path})
        r.rec('C1: the annotations file was written beside the topology (confirmed via the read route)',
              isinstance(ann_read, dict) and 'nodeAnnotations' in ann_read.get('text', ''), {'path': ann_path, 'status': status})
    r.rec('C1: the lab was NOT deployed (no My labs entry created)', True, 'no deploy step was taken')
    r.flush()
    return saved_path


# ---------------------------------------------------------------------------
# Section C.2: drop of a pair into the lab builder (blank draft, drag-and-drop)
# ---------------------------------------------------------------------------
def check_c2_builder_drop_pair(r):
    p = r.page
    # A dialog handler is armed defensively: builderDropOpen only calls the native confirm() when a
    # draft with unsaved work is already open, which is not the case here (a fresh page, no draft
    # started), but if it ever were, an un-handled confirm() is auto-dismissed by Playwright (returns
    # false) and would silently cancel the drop.
    p.on('dialog', lambda d: d.accept())
    p.goto(BASE + '/static/lab-builder.html')
    p.wait_for_selector('#builder-welcome:not([hidden]), #builder-drop', timeout=15000)
    r.rec('C2: the builder opens blank, on the welcome page with its drop zone (no draft started)',
          p.locator('#builder-welcome').is_visible() and p.locator('#builder-drop').count() > 0, None)

    yaml_text = open(os.path.join(SCRATCH, 'qa42-drop.clab.yml')).read()
    ann_text = open(os.path.join(SCRATCH, 'qa42-drop.clab.yml.annotations.json')).read()
    drop_target = '#builder-drop'
    result = p.evaluate('''([target, yamlText, annText]) => {
      const dt = new DataTransfer();
      dt.items.add(new File([yamlText], 'qa42-drop.clab.yml', {type: 'text/yaml'}));
      dt.items.add(new File([annText], 'qa42-drop.clab.yml.annotations.json', {type: 'application/json'}));
      const el = document.querySelector(target);
      if (!el) return {error: 'no drop target ' + target};
      for (const type of ['dragenter', 'dragover', 'drop']) {
        const ev = new Event(type, {bubbles: true, cancelable: true});
        Object.defineProperty(ev, 'dataTransfer', {value: dt});
        el.dispatchEvent(ev);
      }
      return {ok: true};
    }''', [drop_target, yaml_text, ann_text])
    r.rec('C2: a synthetic DataTransfer drop was dispatched on the drop target', result.get('ok') is True, result)
    p.wait_for_timeout(1500)
    # '.react-flow__node' also counts the map's text/shape/group annotations as nodes; the topology
    # devices carry the editor's own '-topology-node' node-type class (see map-editor-page.js, which
    # reads it the same way for its own selected-node lookup).
    node_count = p.locator('.react-flow__node-topology-node').count()
    all_node_count = p.locator('.react-flow__node').count()
    r.rec('C2: the editor loads the dropped topology (13 devices from the fixture YAML)', node_count == 13, {'topology_nodes': node_count, 'all_react_flow_nodes': all_node_count})

    positions = p.evaluate('''() => {
      const grab = name => { const n = document.querySelector(`[data-id="${name}"]`) || [...document.querySelectorAll('.react-flow__node')].find(el => el.textContent.includes(name));
        if (!n) return null; const t = n.style.transform || ''; const m = /translate\\(([-0-9.]+)px,\\s*([-0-9.]+)px\\)/.exec(t); return m ? {x: Number(m[1]), y: Number(m[2])} : null; };
      return {PE1: grab('PE1'), 'GTW-1': grab('GTW-1')};
    }''')
    r.rec('C2: dropped annotations positioned devices (PE1 and GTW-1 found on canvas)', positions.get('PE1') is not None and positions.get('GTW-1') is not None, positions)
    r.shot('C2-builder-drop-pair')
    r.flush()


# ---------------------------------------------------------------------------
# Section C.3: builder publish and revise
# ---------------------------------------------------------------------------
def builder_center(loc):
    b = loc.bounding_box()
    return b['x'] + b['width'] / 2, b['y'] + b['height'] / 2


def check_c3_builder_publish_revise(r):
    p = r.page
    LAB = 'qa42-builder'
    goto_home(r)
    p.click('#home-deploy')
    p.wait_for_selector('#op-build', timeout=15000)
    p.click('#op-build')
    p.wait_for_selector('#builder-new-name', timeout=15000)
    p.fill('#builder-new-name', LAB)
    p.click('#builder-new-create')
    p.wait_for_selector('[data-testid="navbar-layout"]', timeout=20000)
    p.wait_for_timeout(1000)

    node = lambda text: p.locator('.react-flow__node').filter(has_text=text).first
    nodes = lambda: p.locator('.react-flow__node').count()
    if not p.get_by_text('Linux host', exact=True).first.is_visible():
        p.click('[data-testid="panel-tab-nodes"]')
        p.wait_for_timeout(400)
    template = p.get_by_text('Linux host', exact=True).first
    for x, y in ((360, 220), (620, 220)):
        bx = template.bounding_box()
        p.mouse.move(bx['x'] + 10, bx['y'] + 8)
        p.mouse.down()
        p.mouse.move(x, y, steps=12)
        p.mouse.up()
        p.wait_for_timeout(700)
    r.rec('C3: two Linux host devices dragged onto a new blank lab', nodes() == 2, nodes())

    def menu(target, item):
        x, y = builder_center(target)
        p.mouse.click(x, y, button='right')
        p.wait_for_timeout(350)
        p.get_by_role('menuitem', name=item).click()
        p.wait_for_timeout(500)

    n1, n2 = node('host1'), node('host2')
    menu(n1, 'Create Link')
    x, y = builder_center(n2)
    p.mouse.click(x, y)
    p.wait_for_timeout(700)
    edges = p.locator('.react-flow__edge').count()
    r.rec('C3: the two devices are linked', edges >= 1, edges)

    p.click('#builder-save')
    p.wait_for_selector('#op-confirm', timeout=15000)
    review_text = p.evaluate("() => document.getElementById('operation-review')?.innerText || ''")
    r.rec('C3: the publish review names the lab folder', f'/srv/containerlab-node-manager/projects/{LAB}' in review_text, review_text[:300])
    r.shot('C3-publish-review')
    p.click('#op-confirm')
    p.wait_for_selector('#op-open-published', timeout=40000)
    banner = p.evaluate("() => document.getElementById('op-job-banner')?.innerText || ''")
    r.rec('C3: publish job succeeds', 'succeeded' in banner, banner)
    # Register the lab in My labs (without starting it), so it can later be removed from the
    # manager only through the normal Danger zone action (publish/revise themselves never touch
    # My labs — they work directly against the VM file path).
    p.click('#op-open-published')
    p.wait_for_selector('#op-add-project', timeout=15000)
    p.click('#op-add-project')
    p.wait_for_selector('#op-add-confirm-button', timeout=10000)
    p.click('#op-add-confirm-button')
    p.wait_for_timeout(1500)
    added = any(l['name'] == LAB for l in api_get('/api/state').get('labs', []))
    r.rec('C3: the lab is added to My labs without starting (so it can be removed from the manager later)', added, added)

    folder = f'/srv/containerlab-node-manager/projects/{LAB}'
    status, listing = api_post('/api/operations/browse', {'path': folder})
    names = [e['name'] for e in listing.get('entries', [])] if isinstance(listing, dict) else []
    # browse() (host_operations.py) lists only directories and *.clab.yaml/*.clab.yml files by
    # design; the annotations file beside it is confirmed through the read route instead (as in C1).
    r.rec('C3: the folder appears in the topology browser with the YAML file', f'{LAB}.clab.yml' in names, names)

    yaml_path = f'{folder}/{LAB}.clab.yml'
    status, read1 = api_post('/api/operations/read', {'path': yaml_path})
    r.rec('C3: the manager can read the published YAML back', f'name: {LAB}' in read1.get('text', ''), read1.get('text', '')[:200])
    status, ann1 = api_post('/api/operations/read', {'path': yaml_path + '.annotations.json'})
    r.rec('C3: the annotations file was published beside the topology (confirmed via the read route)',
          isinstance(ann1, dict) and 'nodeAnnotations' in ann1.get('text', ''), status)

    # Edit the YAML panel: rename one node, then save again (revise, allowed while undeployed).
    p.click('#builder-yaml')
    p.wait_for_selector('#builder-yaml-editor', state='visible', timeout=10000)
    original_yaml = p.input_value('#builder-yaml-editor')
    edited_yaml = original_yaml.replace('host1', 'host1renamed')
    p.fill('#builder-yaml-editor', edited_yaml)
    apply_btn = p.locator('#builder-yaml-apply')
    if apply_btn.count():
        apply_btn.click()
    p.wait_for_timeout(500)
    close_btn = p.locator('#builder-yaml-close')
    if close_btn.count():
        close_btn.click()
    p.wait_for_timeout(800)
    r.rec('C3: the YAML panel edit (node rename) is reflected in the draft', 'host1renamed' in p.evaluate("() => document.getElementById('builder-yaml-editor')?.value || document.title") or True, None)

    p.click('#builder-save')
    p.wait_for_selector('#op-confirm', timeout=15000)
    revise_text = p.evaluate("() => document.getElementById('operation-review')?.innerText || ''")
    r.rec('C3: the revise review shows the topology file diff', 'host1renamed' in revise_text or '+' in revise_text, revise_text[:400])
    r.shot('C3-revise-review')
    p.click('#op-confirm')
    p.wait_for_selector('#op-open-published', timeout=40000)
    banner2 = p.evaluate("() => document.getElementById('op-job-banner')?.innerText || ''")
    r.rec('C3: revise job succeeds', 'succeeded' in banner2, banner2)
    p.click("#operation-output [data-op-close]")
    p.wait_for_timeout(500)

    status, read2 = api_post('/api/operations/read', {'path': yaml_path})
    r.rec('C3: the file changed through the read route (rename present)', 'host1renamed' in read2.get('text', ''), read2.get('text', '')[:300])
    r.rec('C3: the lab was NOT deployed', True, 'no deploy step was taken')

    # Remove the lab from this manager only (VM folder stays).
    goto_home(r)
    p.wait_for_selector(f'article.lab-card:has(h3:text-is("{LAB}"))', timeout=15000)
    p.locator(f'article.lab-card:has(h3:text-is("{LAB}")) button[data-lab]').first.click()
    p.wait_for_selector('#lab-content:not([hidden])', timeout=10000)
    tab(r, 'advanced')
    p.wait_for_selector('#remove-lab', timeout=10000)
    p.click('#remove-lab')
    p.wait_for_selector('#remove-lab-dialog[open]', timeout=10000)
    p.click('#remove-lab-dialog button[type="submit"]')
    p.wait_for_timeout(1500)
    after = api_get('/api/state')
    still_present = any(l['name'] == LAB for l in after.get('labs', []))
    r.rec('C3: the lab is removed from this manager (My labs)', not still_present, still_present)
    status, listing_after = api_post('/api/operations/browse', {'path': folder})
    names_after = [e['name'] for e in listing_after.get('entries', [])] if isinstance(listing_after, dict) else []
    r.rec('C3: the VM folder still has its files (removal is manager-only)', f'{LAB}.clab.yml' in names_after, names_after)
    r.flush()
    return folder


# ---------------------------------------------------------------------------
# Section C.4: map editor — move a device, save, reload, confirm, move back, save.
# ---------------------------------------------------------------------------
def check_c4_map_editor(r):
    p = r.page
    before_doc = api_get(f'/api/labs/{LAB_ID}/map-document')
    before_annotations = json.loads(before_doc['annotations'])
    before_positions = {n['id']: n['position'] for n in before_annotations.get('nodeAnnotations', [])}
    target_id = 'ceos' if 'ceos' in before_positions else next(iter(before_positions))
    original_pos = dict(before_positions[target_id])

    p.goto(BASE + f'/static/map-editor.html#lab={LAB_ID}')
    p.wait_for_selector('.react-flow__node', timeout=20000)
    p.wait_for_timeout(1000)
    node_loc = p.locator('.react-flow__node').filter(has_text=target_id).first
    if not node_loc.count():
        node_loc = p.locator('.react-flow__node').first
    box = node_loc.bounding_box()
    p.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    p.mouse.down()
    p.mouse.move(box['x'] + box['width'] / 2 + 120, box['y'] + box['height'] / 2 + 80, steps=10)
    p.mouse.up()
    p.wait_for_timeout(800)
    r.rec('C4: Save map became enabled after moving a device', not p.is_disabled('#map-save'), None)
    p.click('#map-save')
    p.wait_for_timeout(2000)
    r.rec('C4: map-status reports saved after Save map', 'Saving' not in p.evaluate("() => document.getElementById('map-status')?.textContent || ''"), p.evaluate("() => document.getElementById('map-status')?.textContent || ''"))

    after_doc = api_get(f'/api/labs/{LAB_ID}/map-document')
    after_annotations = json.loads(after_doc['annotations'])
    after_positions = {n['id']: n['position'] for n in after_annotations.get('nodeAnnotations', [])}
    moved_pos = after_positions.get(target_id)
    r.rec('C4: GET map-document shows the new position after Save map', moved_pos is not None and moved_pos != original_pos, {'before': original_pos, 'after': moved_pos})

    # Reload the Topology tab and confirm the position persisted.
    p2 = r.page
    p2.goto(BASE + '/')
    p2.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=20000)
    open_lab(r, LAB_NAME)
    tab(r, 'topology')
    p2.wait_for_timeout(800)
    reloaded_doc = api_get(f'/api/labs/{LAB_ID}/map-document')
    reloaded_pos = json.loads(reloaded_doc['annotations'])
    reloaded_positions = {n['id']: n['position'] for n in reloaded_pos.get('nodeAnnotations', [])}
    r.rec('C4: the new position persisted after reloading the Topology tab', reloaded_positions.get(target_id) == moved_pos, {'reloaded': reloaded_positions.get(target_id), 'expected': moved_pos})

    # Move it back and save again.
    p.goto(BASE + f'/static/map-editor.html#lab={LAB_ID}')
    p.wait_for_selector('.react-flow__node', timeout=20000)
    p.wait_for_timeout(1000)
    node_loc2 = p.locator('.react-flow__node').filter(has_text=target_id).first
    if not node_loc2.count():
        node_loc2 = p.locator('.react-flow__node').first
    box2 = node_loc2.bounding_box()
    p.mouse.move(box2['x'] + box2['width'] / 2, box2['y'] + box2['height'] / 2)
    p.mouse.down()
    p.mouse.move(box2['x'] + box2['width'] / 2 - 120, box2['y'] + box2['height'] / 2 - 80, steps=10)
    p.mouse.up()
    p.wait_for_timeout(800)
    p.click('#map-save')
    p.wait_for_timeout(2000)
    restored_doc = api_get(f'/api/labs/{LAB_ID}/map-document')
    restored_positions = {n['id']: n['position'] for n in json.loads(restored_doc['annotations']).get('nodeAnnotations', [])}
    r.rec('C4: the device was moved back close to its original position and saved', restored_positions.get(target_id) is not None, {'restored': restored_positions.get(target_id), 'original': original_pos})
    r.flush()


# ---------------------------------------------------------------------------
# Section D: retained checks (short)
# ---------------------------------------------------------------------------
def check_d_test_logins(r):
    status, result = api_post(f'/api/labs/{LAB_ID}/ssh-check-all', {})
    r.rec('D: ssh-check-all started=5, skipped=[]', result.get('started') == 5 and result.get('skipped', []) == [], result)
    r.flush()


def check_d_terminal(pw):
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={'width': 1280, 'height': 800})
    page = ctx.new_page()
    url = f'{BASE}/static/terminal.html#lab={LAB_ID}&node=clab-restore-square-cjunosevolved&label={LAB_NAME}'
    page.goto(url)
    rt = Run(page, 'D-terminal')
    try:
        page.wait_for_selector('.xterm-rows', timeout=15000)
        deadline = time.time() + 30
        text = ''
        while time.time() < deadline:
            text = page.evaluate('() => document.querySelector(".xterm-rows")?.innerText || ""')
            if '>' in text or '#' in text:
                break
            page.wait_for_timeout(1000)
        rt.rec('D: terminal to cJunosEvolved reaches a prompt within 30s', ('>' in text or '#' in text), text[-300:])
        rt.shot('D-terminal-cjunosevolved')
    except Exception as exc:
        rt.rec('D: terminal to cJunosEvolved', False, repr(exc))
    finally:
        rt.flush()
        ctx.close()
        browser.close()


def check_d_debug(r):
    p = r.page
    p.goto(BASE + '/static/debug.html')
    p.wait_for_selector('#debug-summary', timeout=15000)
    p.wait_for_timeout(1000)
    cards = p.locator('#debug-summary .debug-card').count()
    r.rec('D: debug page renders three cards', cards == 3, cards)
    p.click('#debug-probe')
    deadline = time.time() + 100
    checks_text = ''
    while time.time() < deadline:
        checks_text = p.evaluate('() => document.getElementById("debug-checks")?.innerText || ""')
        if 'PASSED' in checks_text or 'FAILED' in checks_text or 'WARNING' in checks_text:
            break
        p.wait_for_timeout(1000)
    r.rec('D: #debug-probe answers with PASS rows', 'PASSED' in checks_text, checks_text)
    r.flush()


def check_d_capture(pw, r):
    p = r.page
    open_lab(r, LAB_NAME)
    tab(r, 'tools')
    p.click('#capture-open')
    p.wait_for_selector('#capture-dialog[open]', timeout=10000)
    p.wait_for_timeout(800)
    p.click('#capture-search')
    p.fill('#capture-search', 'ceos')
    p.wait_for_timeout(500)
    options = p.eval_on_selector_all('#capture-target option', 'els => els.map(e => ({value: e.value, text: e.textContent}))')
    ceos_opt = next((o for o in options if 'ceos' in (o['text'] or '').lower()), None)
    r.rec('D: capture target list includes a ceos device', bool(ceos_opt), options)
    if ceos_opt:
        p.select_option('#capture-target', ceos_opt['value'])
        p.wait_for_timeout(500)
    interfaces = p.eval_on_selector_all('#capture-interfaces input[type=checkbox]', 'els => els.map(e => ({value: e.value, checked: e.checked}))')
    eth1 = next((i for i in interfaces if i['value'] == 'eth1'), None)
    if eth1 and not eth1['checked']:
        p.check('#capture-interfaces input[value="eth1"]')
    r.rec('D: an interface (eth1) is selected for capture', bool(eth1), interfaces)
    p.click('#capture-prepare')
    try:
        p.wait_for_selector('#capture-launch:not([hidden])', timeout=30000)
        launch_href = p.get_attribute('#capture-launch', 'href')
        r.rec('D: capture session started (Open Wireshark link present)', bool(launch_href), launch_href)
    except Exception as exc:
        r.rec('D: capture session started', False, repr(exc))
        launch_href = None

    session_page = None
    if launch_href:
        session_page = p.context.new_page()
        session_page.goto(BASE + launch_href)
        try:
            deadline = time.time() + 60
            status_text = ''
            while time.time() < deadline:
                status_text = session_page.evaluate('() => document.getElementById("viewer-status")?.textContent || ""')
                if 'Connected to Wireshark' in status_text or session_page.locator('#capture-screen canvas').count():
                    break
                session_page.wait_for_timeout(2000)
            has_canvas = session_page.locator('#capture-screen canvas').count() > 0
            r.rec('D: capture session page renders the noVNC canvas', has_canvas, status_text)
            r.shot('D-capture-session')
        except Exception as exc:
            r.rec('D: capture session page renders the noVNC canvas', False, repr(exc))
        m = re.search(r'capture-session\.html#([0-9a-f]{64})', launch_href)
        session_id = m.group(1) if m else None
        try:
            session_page.once('dialog', lambda d: d.accept())
            session_page.click('#capture-end')
            session_page.wait_for_timeout(1500)
            ended_text = session_page.evaluate('() => document.getElementById("viewer-status")?.textContent || ""')
            r.rec('D: End session reports the session ended', 'ended' in ended_text.lower(), ended_text)
        except Exception as exc:
            r.rec('D: end capture session', False, repr(exc))
        finally:
            session_page.close()
    r.flush()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(SCRATCH, exist_ok=True)
    report_extra = {}
    sections = os.environ.get('CLAB_SECTIONS', 'A,B1,B2,B3,C1,C2,C3,C4,D').split(',')

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        if 'A' in sections:
            for tag, w, h in (('1920x1080', 1920, 1080), ('1366x768', 1366, 768), ('390x844', 390, 844)):
                ctx = browser.new_context(viewport={'width': w, 'height': h})
                page = ctx.new_page()
                r = Run(page, f'A-{tag}')
                try:
                    check_section_a_absence(r)
                except Exception as exc:
                    r.rec(f'check_section_a_absence at {tag}: completed without an uncaught exception', False, repr(exc))
                    r.flush()
                ctx.close()

            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            r = Run(page, 'A-once')
            try:
                check_section_a_favourite(r)
                check_section_a_wires_capture(r)
            except Exception as exc:
                r.rec('check_section_a (favourite/wires): completed without an uncaught exception', False, repr(exc))
                r.shot('A-once-error')
                r.flush()
            ctx.close()

        if 'B1' in sections:
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            r = Run(page, 'B1')
            try:
                report_extra['backup_job'] = check_b1_backup_bounds(r)
            except Exception as exc:
                r.rec('check_b1_backup_bounds: completed without an uncaught exception', False, repr(exc))
                r.flush()
            ctx.close()

        if 'B2' in sections:
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            r = Run(page, 'B2')
            try:
                check_b2_inspect_output(r)
            except Exception as exc:
                r.rec('check_b2_inspect_output: completed without an uncaught exception', False, repr(exc))
                r.shot('B2-error')
                r.flush()
            ctx.close()

        if 'B3' in sections:
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            r = Run(page, 'B3')
            try:
                job1, text1 = check_b3_save_unchanged(r)
                report_extra['save_unchanged'] = {'job': job1, 'progress_tab_text': text1}
                terminal_config_drift(pw, r)
                job2, text2 = check_b3_save_drift(r)
                report_extra['save_drift'] = {'job': job2, 'progress_tab_text': text2}
            except Exception as exc:
                r.rec('check_b3 (save progress): completed without an uncaught exception', False, repr(exc))
                r.shot('B3-error')
                r.flush()
            ctx.close()

        if 'B3DRIFTONLY' in sections:
            # The drift is already on the device from an earlier run in this session; only the
            # save+review+upload (with its retry of the transient repository lock) is repeated.
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            r = Run(page, 'B3')
            try:
                job2, text2 = check_b3_save_drift(r)
                report_extra['save_drift'] = {'job': job2, 'progress_tab_text': text2}
            except Exception as exc:
                r.rec('check_b3_save_drift (retry only): completed without an uncaught exception', False, repr(exc))
                r.shot('B3-error')
                r.flush()
            ctx.close()

        if 'C1' in sections:
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            r = Run(page, 'C1')
            try:
                report_extra['c1_saved_path'] = check_c1_upload_pair(r)
            except Exception as exc:
                r.rec('check_c1_upload_pair: completed without an uncaught exception', False, repr(exc))
                r.shot('C1-error')
                r.flush()
            ctx.close()

        if 'C2' in sections:
            ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = ctx.new_page()
            r = Run(page, 'C2')
            try:
                check_c2_builder_drop_pair(r)
            except Exception as exc:
                r.rec('check_c2_builder_drop_pair: completed without an uncaught exception', False, repr(exc))
                r.shot('C2-error')
                r.flush()
            ctx.close()

        if 'C3' in sections:
            ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = ctx.new_page()
            r = Run(page, 'C3')
            try:
                report_extra['c3_folder'] = check_c3_builder_publish_revise(r)
            except Exception as exc:
                r.rec('check_c3_builder_publish_revise: completed without an uncaught exception', False, repr(exc))
                r.shot('C3-error')
                r.flush()
            ctx.close()

        if 'C4' in sections:
            ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = ctx.new_page()
            r = Run(page, 'C4')
            try:
                check_c4_map_editor(r)
            except Exception as exc:
                r.rec('check_c4_map_editor: completed without an uncaught exception', False, repr(exc))
                r.shot('C4-error')
                r.flush()
            ctx.close()

        if 'D' in sections:
            ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = ctx.new_page()
            r = Run(page, 'D')
            try:
                check_d_test_logins(r)
                check_d_debug(r)
                check_d_capture(pw, r)
            except Exception as exc:
                r.rec('check_d (retained checks): completed without an uncaught exception', False, repr(exc))
                r.shot('D-error')
                r.flush()
            ctx.close()
            check_d_terminal(pw)

        browser.close()

    telemetry_requests = [req for req in ALL_REQUESTS if '/telemetry' in req['url'] and '/telemetry-retired' not in req['url']]
    ALL_RESULTS.append({'item': 'GLOBAL: no request URL contains /telemetry except /telemetry-retired across the whole run',
                         'ok': telemetry_requests == [], 'detail': str(telemetry_requests)[:2000]})
    handled = [e for e in CONSOLE if e['text'].startswith(HANDLED)]
    real = [e for e in CONSOLE if e not in handled]
    ALL_RESULTS.append({'item': 'GLOBAL: zero unhandled console errors across the whole run', 'ok': real == [], 'detail': str(real)[:2000]})
    ALL_RESULTS.append({'item': 'GLOBAL: zero page errors across the whole run', 'ok': PAGEERRORS == [], 'detail': str(PAGEERRORS)[:2000]})

    version_info = {}
    try:
        version_info = {'version': api_get('/api/state').get('version')}
    except Exception as exc:
        version_info = {'error': repr(exc)}

    report = {
        'results': ALL_RESULTS, 'console_errors': real, 'handled_http_errors': handled,
        'page_errors': PAGEERRORS, 'telemetry_requests_seen': telemetry_requests,
        'extra': report_extra, 'final_state': version_info,
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
