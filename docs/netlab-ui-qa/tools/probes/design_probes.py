#!/usr/bin/env python3
"""QA reproduction probes for the Network design (Design tab) UI, campaign owner's §6, ten hypotheses.

Drives a real Chromium (Playwright) against the fixture manager (the real FastAPI app on scratch state
with the pinned netlab engine, no VM) — never the deployed product on 8081. Each probe is a function
`probeN(ctx, page, base, labs)` that performs real clicks/typing (never calling a production JS handler
directly, never toggling `disabled`, never force-clicking through an overlay) and records PASS/FAIL
checks plus screenshots. Fault injection (delay/fail a response) uses Playwright request interception
(`page.route`), labelled as such in the check names.

Usage (fixture manager must be reachable; this script can also start/stop its own on --port, default
8098; never 8097, another agent's instance):

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/tools/probes/design_probes.py --port 8098 --data <FRESH dir> \\
        --probes 1,2,3,4,5,6,7,8,9,10

Prints a PASS/FAIL line per check to stdout and writes screenshots under
docs/netlab-ui-qa/evidence/probes/P<n>-<step>.png. Exit status is 1 if any check recorded FAIL
(a probe that could not be exercised at all should be read from the printed "NOT RUN" line, not
inferred from the exit status alone — see the report for the authoritative verdict per hypothesis).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
FIXTURE = ROOT / 'docs' / 'redesign' / 'tools' / 'fixture_manager.py'
EVIDENCE = ROOT / 'docs' / 'netlab-ui-qa' / 'evidence' / 'probes'


class Ctx:
    """Per-run bookkeeping: checks, screenshots, console/page errors. One instance for the whole session
    so the report can cite a single, consistent list of unexpected console/page errors."""
    def __init__(self, page):
        self.page = page
        self.console = []
        self.pageerrors = []
        self.checks = []
        self.requests = []   # (url, method, body-snippet) for every /api/ request, for evidence
        page.on('console', lambda m: self.console.append({'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.pageerrors.append(str(e)))

    def check(self, probe, name, ok, detail=''):
        row = {'probe': probe, 'name': name, 'ok': bool(ok), 'detail': str(detail)[:600]}
        self.checks.append(row)
        print(('  PASS ' if ok else '  FAIL ') + '[P%d] ' % probe + name + ('' if ok else ': ' + str(detail)[:400]), flush=True)

    def note(self, probe, message):
        print('  ..   [P%d] %s' % (probe, message), flush=True)

    def shot(self, name):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        path = EVIDENCE / (name + '.png')
        self.page.screenshot(path=str(path), full_page=True)
        print('  shot: ' + str(path), flush=True)
        return path

    def text(self, selector):
        node = self.page.locator(selector).first
        return (node.text_content() or '') if node.count() else ''

    def val(self, selector):
        node = self.page.locator(selector).first
        return node.input_value() if node.count() else ''


def wait_http(url, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read())
        except Exception:
            time.sleep(0.5)
    raise SystemExit('fixture manager did not answer at ' + url)


def raw_get(base, path):
    """A direct HTTP GET bypassing Playwright/page.route entirely: used to check the server's real state
    independently of whatever the browser's network layer has been made to see (fault injection, races)."""
    with urllib.request.urlopen(base + path, timeout=10) as response:
        return json.loads(response.read())


def lab_map(base):
    state = raw_get(base, '/api/state')
    return {l['name']: l['id'] for l in state['labs']}


def goto_design(page, base, lab_id, timeout=20000):
    page.goto(base + '/#lab=' + lab_id + '&view=design')
    page.wait_for_selector('#design-view:not([hidden])', timeout=timeout)
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=timeout)


def blur_form(page):
    """Leave any focused guided/advanced control: the renderer only rewrites a guarded control while
    nothing inside #design-form has focus (designFormFocused()). Clicking the view heading is the same
    trick check_design_ui.py uses."""
    page.locator('#design-view h2').first.click()
    page.wait_for_timeout(250)


def open_advanced(page):
    details = page.locator('#design-advanced-details')
    if details.count() and not details.evaluate('el => el.open'):
        page.click('#design-advanced-details summary')
        page.wait_for_timeout(100)


def set_advanced(page, intent, wait_ms=250):
    """Type a whole intent document into the Advanced textarea and blur it, the same path a student
    pastes an edited export into. Uses fill()+dispatch_event('change') exactly as designOnAdvancedChange
    listens for, then blurs so the guided controls (and the ledger) catch up."""
    open_advanced(page)
    text = json.dumps(intent, indent=2)
    page.fill('#design-advanced', text)
    page.locator('#design-advanced').dispatch_event('change')
    page.wait_for_timeout(wait_ms)


def save(page, timeout=15000):
    page.click('#design-save')
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Unsaved")', timeout=timeout)


def wait_state(page, word, timeout=90000):
    page.wait_for_function('(w) => (document.getElementById("design-state")?.textContent || "").includes(w)', arg=word, timeout=timeout)


def open_more_menu(page, item_id):
    page.click('#design-more-button')
    page.wait_for_selector('#design-more-menu:not([hidden])', timeout=5000)
    page.click('#' + item_id)


def delayed_continue(route, seconds):
    """Let a request through after `seconds`, WITHOUT blocking Playwright's own driver thread. A route
    handler that calls time.sleep() directly blocks the sync API's single background event loop —
    stalling every other Playwright command (clicks, waits) for the same duration, which makes any
    concurrent action in the test itself serialize behind the "network" delay instead of racing it.
    Handing the delay to its own thread and calling route.continue_() from there (safe: the sync
    wrappers dispatch via run_coroutine_threadsafe) keeps the delay real without blocking the test."""
    def worker():
        time.sleep(seconds)
        try: route.continue_()
        except Exception: pass
    threading.Thread(target=worker, daemon=True).start()


def generation_id_from_download(page):
    href = page.locator('#design-download').get_attribute('href') or ''
    m = re.search(r'/generations/([0-9a-f]{32})/download', href)
    return m.group(1) if m else ''


# ---------------------------------------------------------------------------------------------------
# Probe 1: advanced-to-guided data loss on the addressing pools
# ---------------------------------------------------------------------------------------------------
def probe1(ctx, page, base, labs):
    n = 1
    lab_id = labs['ospf-basics']
    goto_design(page, base, lab_id)
    baseline = {
        'schema': 1, 'label': 'P1', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {
            'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
            'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
            'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24, 'start': 5, 'allocation': 'sequential'},
            'vrf_loopback': {'ipv4': '10.250.0.0/24'},
            'router_id': {'ipv4': '192.0.2.0/24'},
        },
        'modules': ['ospf'], 'ospf': {'area': '0.0.0.0'},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline)
    ctx.check(n, 'baseline with vrf_loopback/router_id pools and extra lan pool keys parses with no problems', ctx.text('#design-problems').strip() == '', ctx.text('#design-problems'))
    save(page)
    ctx.check(n, 'baseline saves without problems', ctx.text('#design-problems').strip() == '', ctx.text('#design-problems'))
    page.reload()
    goto_design(page, base, lab_id)
    advanced_after_save = ctx.val('#design-advanced')
    ctx.check(n, 'a reload shows the extra pools were actually stored (not just accepted client-side)',
               'vrf_loopback' in advanced_after_save and 'router_id' in advanced_after_save and '"start": 5' in advanced_after_save and '"allocation": "sequential"' in advanced_after_save,
               advanced_after_save[:400])
    ctx.shot('P1-01-baseline-saved')

    # Now touch one unrelated guided field: OSPF area. This fires designOnGuidedChange, which rebuilds
    # intent.addressing from exactly the three visible pools (network-design.js designIntentFromForm).
    page.fill('#design-ospf-area', '0.0.0.1')
    page.locator('#design-ospf-area').dispatch_event('change')
    blur_form(page)
    advanced_after_edit = ctx.val('#design-advanced')
    ctx.check(n, 'editing an unrelated guided field (OSPF area) is reflected', '0.0.0.1' in advanced_after_edit, advanced_after_edit[:200])
    lost_vrf_loopback = 'vrf_loopback' not in advanced_after_edit
    lost_router_id = 'router_id' not in advanced_after_edit
    lost_lan_extras = '"start"' not in advanced_after_edit or '"allocation"' not in advanced_after_edit
    ctx.check(n, 'CONFIRMED-target: an unrelated guided edit silently drops the vrf_loopback pool', lost_vrf_loopback, advanced_after_edit[:600])
    ctx.check(n, 'CONFIRMED-target: an unrelated guided edit silently drops the router_id pool', lost_router_id, advanced_after_edit[:600])
    ctx.check(n, 'CONFIRMED-target: an unrelated guided edit silently drops the lan pool\'s start/allocation keys', lost_lan_extras, advanced_after_edit[:600])
    ctx.shot('P1-02-after-unrelated-guided-edit')
    problems_now = ctx.text('#design-problems')
    ctx.check(n, 'no warning is shown that data was dropped', problems_now.strip() == '', problems_now)

    save(page)
    page.reload()
    goto_design(page, base, lab_id)
    advanced_after_reload = ctx.val('#design-advanced')
    ctx.check(n, 'the loss is permanent: gone again after Save + reload', 'vrf_loopback' not in advanced_after_reload and 'router_id' not in advanced_after_reload, advanced_after_reload[:400])
    ctx.shot('P1-03-after-save-and-reload')


# ---------------------------------------------------------------------------------------------------
# Probe 2: multiple route reflectors collapsed to one
# ---------------------------------------------------------------------------------------------------
def probe2(ctx, page, base, labs):
    n = 2
    lab_id = labs['ospf-basics']
    goto_design(page, base, lab_id)
    baseline = {
        'schema': 1, 'label': 'P2', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['bgp'], 'bgp': {'as': 65010},
        'nodes': {'r1': {'bgp': {'rr': True}}, 'r2': {'bgp': {'rr': True}}},
        'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline)
    save(page)
    ctx.check(n, 'a two-reflector design (r1 and r2 both bgp.rr=true) saves without problems', ctx.text('#design-problems').strip() == '', ctx.text('#design-problems'))
    page.reload()
    goto_design(page, base, lab_id)
    advanced0 = ctx.val('#design-advanced')
    both_present = advanced0.count('"rr": true') == 2
    ctx.check(n, 'both route reflectors are actually stored after reload', both_present, advanced0[:500])
    ctx.shot('P2-01-two-reflectors-saved')

    # Touch one unrelated guided field: the BGP AS number (not the reflector selection itself). A text
    # field's native blur-triggered 'change' forces a fresh, unfocused re-render, so save right after to
    # observe the actually-persisted result rather than a transiently stale Advanced view.
    page.fill('#design-bgp-as', '65020')
    page.locator('#design-bgp-as').dispatch_event('change')
    blur_form(page)
    save(page)
    advanced1 = ctx.val('#design-advanced')
    rr_count = advanced1.count('"rr": true')
    ctx.check(n, 'CONFIRMED-target: an unrelated guided edit collapses two route reflectors to at most one', rr_count <= 1, 'rr_count=%d advanced=%s' % (rr_count, advanced1[:600]))
    ctx.shot('P2-02-after-unrelated-guided-edit')
    problems_now = ctx.text('#design-problems')
    ctx.check(n, 'no warning is shown that a route reflector was silently dropped', problems_now.strip() == '', problems_now)


# ---------------------------------------------------------------------------------------------------
# Probe 3: acting on the last parsed (stale) intent while the Advanced textarea shows something else
# ---------------------------------------------------------------------------------------------------
def probe3(ctx, page, base, labs):
    n = 3
    lab_id = labs['ospf-basics']
    goto_design(page, base, lab_id)
    baseline = {
        'schema': 1, 'label': 'P3-baseline', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['ospf'], 'ospf': {'area': '0.0.0.0'},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline)
    save(page)
    ctx.shot('P3-00-baseline-saved')

    captured = {'body': None}
    def spy_put(route):
        if route.request.method == 'PUT':
            try: captured['body'] = route.request.post_data
            except Exception: captured['body'] = None
        route.continue_()
    page.route('**/api/labs/%s/design' % lab_id, spy_put)

    malformed = '{ "schema": 1, "label": "P3-BROKEN-EDIT", "families": {"ipv4": true "ipv6": true'  # missing comma/braces: invalid JSON
    open_advanced(page)
    page.fill('#design-advanced', malformed)
    ctx.shot('P3-01-malformed-typed-not-yet-blurred')
    ctx.check(n, 'the textarea shows the malformed text before any blur', ctx.val('#design-advanced') == malformed)

    # A real click on Save necessarily blurs the textarea first (Chromium's own focus semantics), which
    # fires the 'change' listener designOnAdvancedChange is bound to; note this as an environment fact
    # rather than skip the probe, then observe what happens next.
    page.click('#design-save')
    page.wait_for_timeout(2000)
    problems_at_blur = ctx.text('#design-problems')
    ctx.shot('P3-02-after-click-save')
    saved_notify_or_state = ctx.text('#design-state')
    textarea_now = ctx.val('#design-advanced')
    ctx.check(n, 'CONFIRMED-target: Save proceeded using the stale (pre-edit) intent, not the malformed on-screen text', captured['body'] is not None and 'P3-baseline' in (captured['body'] or ''), str(captured['body'])[:400])
    ctx.check(n, 'CONFIRMED-target: the screen reverts to the stale content with no explicit "your edit was discarded" message', 'P3-BROKEN-EDIT' not in textarea_now and 'discarded' not in ctx.text('#design-detail').lower(), 'detail=%r textarea=%s' % (ctx.text('#design-detail'), textarea_now[:200]))
    ctx.note(n, 'design-problems at the moment of blur: %r' % problems_at_blur)
    ctx.note(n, 'design-state after Save click: %r' % saved_notify_or_state)
    page.unroute('**/api/labs/%s/design' % lab_id, spy_put)

    # Same shape, but for Generate: malformed text, click Generate, confirm the generation uses the
    # still-saved (stale) revision/intent rather than being blocked or reflecting the malformed edit.
    malformed2 = '{ "schema": 1, "label": "P3-BROKEN-2", not valid json at all'
    open_advanced(page)
    page.fill('#design-advanced', malformed2)
    ctx.shot('P3-03-malformed-before-generate')
    page.click('#design-generate')
    try:
        wait_state(page, 'Generating', timeout=8000)
        generating_ok = True
    except Exception as exc:
        generating_ok = False
        ctx.note(n, 'Generate did not start: %s' % exc)
    ctx.check(n, 'Generate was not blocked by the malformed on-screen text (no disabled state, no refusal)', generating_ok)
    if generating_ok:
        wait_state(page, 'ready', timeout=120000)
        ctx.shot('P3-04-generated-after-malformed-edit')
        plan_label = ctx.text('#design-plan-status')
        ctx.note(n, 'plan status after generating through malformed on-screen text: %r' % plan_label)


# ---------------------------------------------------------------------------------------------------
# Probe 4: Generate/Export act on the saved design, silently ignoring an unsaved edit
# ---------------------------------------------------------------------------------------------------
def probe4(ctx, page, base, labs):
    n = 4
    lab_id = labs['ospf-basics']
    goto_design(page, base, lab_id)
    baseline = {
        'schema': 1, 'label': 'P4', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['bgp'], 'bgp': {'as': 65001},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline)
    save(page)
    page.click('#design-generate')
    wait_state(page, 'Generating', timeout=8000)
    wait_state(page, 'ready', timeout=120000)
    ctx.shot('P4-01-plan-with-as-65001')
    plan_text_1 = ctx.text('#design-plan-body')
    files_text_1 = ctx.text('#design-files-body')
    ctx.check(n, 'the first generated plan reflects AS 65001', '65001' in plan_text_1, plan_text_1[:400])

    # Edit BGP AS to 65099 through the guided field, WITHOUT saving.
    page.fill('#design-bgp-as', '65099')
    page.locator('#design-bgp-as').dispatch_event('change')
    blur_form(page)
    ctx.check(n, 'the edit is held as an unsaved draft', 'Unsaved' in ctx.text('#design-state'), ctx.text('#design-state'))
    ctx.shot('P4-02-unsaved-edit-to-65099')

    generate_body = {'body': None}
    def spy_generate(route):
        if route.request.method == 'POST':
            try: generate_body['body'] = route.request.post_data
            except Exception: generate_body['body'] = None
        route.continue_()
    page.route('**/api/labs/%s/design/generate' % lab_id, spy_generate)
    page.click('#design-generate')
    wait_state(page, 'Generating', timeout=8000)
    # NOTE: #design-state (the header pill) can never show "ready" here: designStateOf() checks
    # view.draft BEFORE the newest-generation/"ready" branch, so it is stuck on "Unsaved changes" for
    # the rest of this probe regardless of the plan's own status — this is itself part of the
    # CONFIRMED-target finding, not a probe bug. Poll the plan card's own status line instead.
    page.wait_for_function('() => (document.getElementById("design-plan-status")?.textContent || "").includes("Plan generated")', timeout=120000)
    page.unroute('**/api/labs/%s/design/generate' % lab_id, spy_generate)
    ctx.shot('P4-03-plan-after-clicking-generate-while-unsaved')
    plan_text_2 = ctx.text('#design-plan-body')
    header_now = ctx.text('#design-state')
    ctx.check(n, 'Generate never sent the draft intent, only a revision', generate_body['body'] is not None and 'bgp' not in (generate_body['body'] or '') and '65099' not in (generate_body['body'] or ''), str(generate_body['body']))
    ctx.check(n, 'CONFIRMED-target: the "new" plan still reflects the OLD saved AS 65001, not the unsaved 65099', '65001' in plan_text_2 and '65099' not in plan_text_2, plan_text_2[:400])
    ctx.check(n, 'CONFIRMED-target: the header still shows "Unsaved changes" even though a plan was just generated successfully (view.draft is checked before the newest-generation branch in designStateOf)', 'Unsaved' in header_now, header_now)
    as_field_now = ctx.val('#design-bgp-as')
    ctx.check(n, 'the guided AS field still shows the unsaved 65099 the whole time (contradicts the plan just shown)', as_field_now == '65099', as_field_now)

    # Export while unsaved: the downloaded document should also be the stale, saved 65001 design.
    with page.expect_download() as dl_info:
        open_more_menu(page, 'design-export')
    download = dl_info.value
    tmp = Path(tempfile.mkstemp(prefix='design-export-')[1])
    download.save_as(str(tmp))
    exported = tmp.read_text(errors='replace')
    ctx.check(n, 'CONFIRMED-target: "Download design file" while unsaved exports the OLD saved AS 65001, not 65099', '65001' in exported and '65099' not in exported, exported[:400])
    tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------------------------------
# Probe 5: cross-lab asynchronous contamination (delayed Save response lands after switching labs)
# ---------------------------------------------------------------------------------------------------
def probe5(ctx, page, base, labs):
    n = 5
    a_id, b_id = labs['ospf-basics'], labs['vlan-lab']
    goto_design(page, base, a_id)
    distinctive = {
        'schema': 1, 'label': 'LAB-A-DISTINCTIVE', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['ospf'], 'ospf': {'area': '9.9.9.9'},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, distinctive)

    def delay_put(route):
        if route.request.method == 'PUT':
            delayed_continue(route, 5)
        else:
            route.continue_()
    page.route('**/api/labs/%s/design' % a_id, delay_put)
    page.click('#design-save')   # fires the delayed PUT for lab A; do not wait for it

    # Immediately switch to lab B (vlan-lab) via the sidebar + Design tab, well before the 5s delay elapses.
    page.click('#crumb-home')
    page.wait_for_timeout(300)
    # Scope to the lab card's own "Open lab" button: [data-lab] alone also matches the (hidden)
    # lab-switcher sidebar entry sharing the same id.
    page.click('article.lab-card[data-lab-id="%s"] [data-lab="%s"]' % (b_id, b_id))
    page.click('#tab-design')
    page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=15000)
    ctx.shot('P5-01-lab-b-immediately-after-switch')
    b_state_immediate = ctx.text('#design-state')
    ctx.check(n, 'lab B initially shows its own (no-design) state, not lab A\'s', 'No design yet' in b_state_immediate or '9.9.9.9' not in ctx.text('#design-ospf-area'), b_state_immediate)

    page.wait_for_timeout(6000)   # let lab A's delayed PUT resolve in the background
    ctx.shot('P5-02-lab-b-after-lab-a-save-resolved')
    b_state_after = ctx.text('#design-state')
    b_area_after = ctx.val('#design-ospf-area')
    b_advanced_after = ctx.val('#design-advanced')
    still_on_b = page.locator('#tab-design[aria-selected="true"]').count() == 1
    contaminated = ('9.9.9.9' in b_area_after) or ('LAB-A-DISTINCTIVE' in b_advanced_after)
    ctx.check(n, 'CONFIRMED-target: lab A\'s delayed Save response overwrote what is shown under lab B\'s Design tab', contaminated, 'still_on_design_tab=%s state=%r area=%r advanced=%s' % (still_on_b, b_state_after, b_area_after, b_advanced_after[:300]))
    page.unroute('**/api/labs/%s/design' % a_id, delay_put)

    # Verify server-side lab B truly has no design (the contamination, if any, is a client-side render bug).
    b_view = raw_get(base, '/api/labs/%s/design' % b_id)
    ctx.note(n, 'server-side lab B intent: %r' % (b_view.get('intent'),))
    ctx.check(n, 'server-side lab B was never actually touched (this is a rendering race, not a server bug)', b_view.get('intent') is None, b_view.get('intent'))


# ---------------------------------------------------------------------------------------------------
# Probe 6: same-lab different-generation race (a lab-id-only check lets a stale generation's plan show)
# ---------------------------------------------------------------------------------------------------
def probe6(ctx, page, base, labs):
    n = 6
    lab_id = labs['ospf-basics']
    goto_design(page, base, lab_id)
    baseline1 = {
        'schema': 1, 'label': 'P6-G1', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['ospf'], 'ospf': {'area': '0.0.0.0'},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline1)
    save(page)
    page.click('#design-generate')
    wait_state(page, 'Generating', timeout=8000)
    wait_state(page, 'ready', timeout=120000)
    g1_id = generation_id_from_download(page)
    ctx.note(n, 'G1 id = %s' % g1_id)
    ctx.check(n, 'G1 generated and its id was recovered from the download link', bool(g1_id))
    plan1 = ctx.text('#design-plan-body')
    ctx.check(n, 'G1\'s plan does not mention bgp (ospf-only design)', 'bgp' not in plan1.lower(), plan1[:200])

    delayed_pattern = '**/api/labs/%s/design/generations/%s' % (lab_id, g1_id)
    def delay_g1(route):
        url = route.request.url
        if url.rstrip('/').endswith('/generations/%s' % g1_id):
            delayed_continue(route, 10)
        else:
            route.continue_()
    page.route(delayed_pattern, delay_g1)

    page.reload()   # triggers a fresh designLoad(); since G1 is still "newest succeeded" this refetches
                    # G1's plan through the now-delayed route, in flight for the next ~10s.
    page.wait_for_selector('#design-view:not([hidden])', timeout=15000)

    # While that fetch is in flight, change the design (add bgp) and regenerate: G2.
    page.click('[name="design-module"][value="bgp"]')
    page.wait_for_timeout(150)
    page.fill('#design-bgp-as', '65077')
    page.locator('#design-bgp-as').dispatch_event('change')
    blur_form(page)
    save(page)
    page.click('#design-generate')
    wait_state(page, 'Generating', timeout=8000)
    wait_state(page, 'ready', timeout=120000)
    g2_id = generation_id_from_download(page)
    ctx.note(n, 'G2 id = %s (started while G1\'s delayed fetch was still in flight)' % g2_id)
    plan2_immediately = ctx.text('#design-plan-body')
    ctx.shot('P6-01-g2-ready-immediately')
    ctx.check(n, 'G2 is correctly shown immediately after it succeeds (mentions bgp/65077)', 'bgp' in plan2_immediately.lower() and '65077' in plan2_immediately, plan2_immediately[:400])

    page.wait_for_timeout(11000)   # let the delayed G1 fetch land
    ctx.shot('P6-02-after-delayed-g1-fetch-lands')
    plan_final = ctx.text('#design-plan-body')
    download_href_final = page.locator('#design-download').get_attribute('href') or ''
    history_final = ctx.text('#design-history-body')
    reverted_to_g1 = ('bgp' not in plan_final.lower()) or ('65077' not in plan_final)
    still_says_g2_in_history_or_download = (g2_id in download_href_final)
    ctx.check(n, 'CONFIRMED-target: the delayed G1 fetch overwrote the plan body with stale G1 content after G2 was already shown correctly',
               reverted_to_g1 and still_says_g2_in_history_or_download,
               'plan_final=%s download_href=%s history=%s' % (plan_final[:300], download_href_final, history_final[:200]))
    page.unroute(delayed_pattern, delay_g1)


# ---------------------------------------------------------------------------------------------------
# Probe 7: polling failure kills the watch permanently, leaving "Generating…" frozen
# ---------------------------------------------------------------------------------------------------
def probe7(ctx, page, base, labs):
    n = 7
    # A bigger lab (13 devices): ospf-basics' real netlab generation is fast enough that the first
    # post-Generate fetch can already see "succeeded", leaving no genuine poll cycle to fail.
    lab_id = labs['BGP_TheoryToPractice']
    goto_design(page, base, lab_id)
    baseline = {
        'schema': 1, 'label': 'P7', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['ospf'], 'ospf': {'area': '0.0.0.0'},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline)
    save(page)

    calls = {'n': 0}
    def flaky_view(route):
        if route.request.method == 'GET':
            calls['n'] += 1
            if calls['n'] == 2:   # let the first (post-POST) fetch through; fail the first poll cycle
                route.fulfill(status=500, body='fault injection: simulated transient failure')
                return
        route.continue_()
    page.route('**/api/labs/%s/design' % lab_id, flaky_view)

    seen_requests = []
    page.on('request', lambda req: seen_requests.append(req.url) if ('/design' in req.url and lab_id in req.url and 'generate' not in req.url) else None)

    page.click('#design-generate')
    wait_state(page, 'Generating', timeout=8000)
    ctx.shot('P7-01-generating-before-fault')

    # Wait past the injected 500 but well short of app.js's own global 4s refresh heartbeat
    # (setInterval(() => refresh(), 4000) in app.js), which turns out to be the thing that eventually
    # revives the design tab's own dead poll (see below) — this window isolates the design-specific
    # poll's OWN behaviour right after the fault, before that unrelated timer can interfere.
    page.wait_for_timeout(3000)
    state_shortly_after_fault = ctx.text('#design-state'); detail_shortly_after_fault = ctx.text('#design-detail')
    ctx.shot('P7-02-shortly-after-injected-500')
    # The label under #design-state reads "Generating the plan…" for the whole busy period whatever happens to the
    # poll; the retry notice ("attempt 1 of 5 … Trying again") is written to #design-detail (QA-009).
    ctx.check(n, "CONFIRMED-target: the design tab's own poll dies silently on the first failed request (no retry notice, no error shown) 3s after a single injected 500, well past its normal 2s cadence",
               'Generating' in state_shortly_after_fault and 'attempt' not in detail_shortly_after_fault, state_shortly_after_fault + ' | ' + detail_shortly_after_fault)

    page.wait_for_timeout(8000)   # give app.js's unrelated global refresh (every 4s) a chance to land
    state_later = ctx.text('#design-state')
    ctx.shot('P7-03-well-after-fault-recovered-via-the-global-refresh')
    page.unroute('**/api/labs/%s/design' % lab_id, flaky_view)

    server_side = raw_get(base, '/api/labs/%s/design' % lab_id)
    server_generations = server_side.get('generations') or []
    server_newest = server_generations[-1] if server_generations else None
    ctx.note(n, 'server-side newest generation status (fetched directly, bypassing the page): %r' % ((server_newest or {}).get('status'),))
    ctx.note(n, 'state ~11s after the fault: %r (recovered by app.js\'s unrelated 4s refresh calling designRenderAll(), which restarts designMaybeStartWatch() as a side effect of designWatch having been nulled — not by the poll\'s own retry, which never fires again)' % state_later)
    ctx.check(n, 'the tab does eventually recover, but only via an unrelated global timer, never the poll\'s own logic — a student on a lab the global refresh does not reach (navigated away and the lab no longer resolves via current()) would stay stuck indefinitely',
               'ready' in state_later.lower() or 'Plan ready' in state_later, state_later)
    ctx.check(n, 'no error/retry indication was ever shown to the user at any point after the injected failure', 'failed' not in state_shortly_after_fault.lower() and 'failed' not in state_later.lower(), state_shortly_after_fault + ' | ' + state_later)
    ctx.note(n, 'design GET requests observed by the page during the window: %d' % len(seen_requests))


# ---------------------------------------------------------------------------------------------------
# Probe 8: draft conflict and storage failure — is the user's only copy ever silently destroyed?
# ---------------------------------------------------------------------------------------------------
def probe8(ctx, page, base, labs, context):
    n = 8
    lab_id = labs['ospf-basics']
    goto_design(page, base, lab_id)
    baseline = {
        'schema': 1, 'label': 'P8', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['ospf'], 'ospf': {'area': '0.0.0.0'},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline)
    save(page)

    # --- 8a: localStorage.setItem throws (quota / private browsing) -----------------------------------
    context.add_init_script("""
        (() => { const orig = Storage.prototype.setItem;
          window.__origSetItem = orig;   // kept so the test itself can still write around the fault later
          Storage.prototype.setItem = function(k, v) {
            if (String(k).indexOf('clab.design.draft.') === 0) throw new DOMException('simulated quota', 'QuotaExceededError');
            return orig.call(this, k, v);
          }; })();
    """)
    page.reload()
    goto_design(page, base, lab_id)
    page.fill('#design-ospf-area', '1.1.1.1')
    page.locator('#design-ospf-area').dispatch_event('change')
    blur_form(page)
    ctx.shot('P8-01-unsaved-edit-with-storage-failing')
    unsaved_shown = 'Unsaved' in ctx.text('#design-state'); detail_before_reload = ctx.text('#design-detail')
    page_errors_during = list(ctx.pageerrors)
    ctx.check(n, 'the app tolerates a throwing localStorage.setItem without crashing (no uncaught page error)', len(page_errors_during) == 0, page_errors_during)
    ctx.check(n, 'the edit is shown as an in-memory unsaved draft', unsaved_shown, ctx.text('#design-state'))
    # The fix (QA-010) is a red warning while the edit is still on screen; once the write has failed and the page is
    # reloaded there is nothing left to recover, so the moment to look is before the reload.
    ctx.check(n, 'CONFIRMED-target: no message tells the student the edit could not be kept in this browser (a plain "Unsaved changes" with no warning)', 'could not be kept' not in detail_before_reload, detail_before_reload)

    page.reload()
    goto_design(page, base, lab_id)
    ctx.shot('P8-02-after-reload-storage-had-failed')
    area_after_reload = ctx.val('#design-ospf-area')
    # Inherent, not a defect: the browser could not store the draft, so a reload starts from the saved design.
    ctx.check(n, 'after the reload the page starts from the saved design (the browser held no draft)', area_after_reload == '0.0.0.0', area_after_reload)

    # --- 8b: contrast case — a genuinely stale draft (revision mismatch) DOES get an explicit message ---
    # Written through window.__origSetItem (captured before the fault above), since the page-wide
    # override from 8a is still in effect on this context and would otherwise swallow this write too.
    page.evaluate("""(labId) => {
        const write = window.__origSetItem || Storage.prototype.setItem;
        write.call(localStorage, 'clab.design.draft.' + labId, JSON.stringify({revision: 'not-the-current-revision', intent: {schema:1, label:'stale-draft', families:{ipv4:true,ipv6:true}, addressing:{}, modules:[], nodes:{}, links:{}, vlans:{}, vrfs:{}, interfaces:{}, allocations:{}}}));
    }""", lab_id)
    page.reload()
    goto_design(page, base, lab_id)
    ctx.shot('P8-03-stale-draft-discard-message-for-contrast')
    detail_stale = ctx.text('#design-detail')
    ctx.check(n, 'contrast: a stale (revision-mismatched) draft DOES get an explicit discard message', 'discarded' in detail_stale.lower(), detail_stale)


# ---------------------------------------------------------------------------------------------------
# Probe 9: history usefulness — are retained results identifiable and retrievable?
# ---------------------------------------------------------------------------------------------------
def probe9(ctx, page, base, labs):
    n = 9
    lab_id = labs['ospf-basics']
    goto_design(page, base, lab_id)
    baseline_ok = {
        'schema': 1, 'label': 'P9-G1-ok', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['ospf'], 'ospf': {'area': '0.0.0.0'},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline_ok)
    save(page)
    page.click('#design-generate')
    wait_state(page, 'Generating', timeout=8000)
    wait_state(page, 'ready', timeout=120000)
    g1_id = generation_id_from_download(page)
    ctx.note(n, 'G1 (succeeded, ospf-only) id = %s' % g1_id)

    # Make it fail: an unsupported protocol (eigrp on arista_ceos), the same proven path check_design_ui.py uses.
    page.click('[name="design-module"][value="eigrp"]')
    save(page)
    page.click('#design-generate')
    wait_state(page, 'failed', timeout=60000)
    g2_errors = ctx.text('#design-plan-errors')
    ctx.check(n, 'the failed generation (G2) names the device and the unsupported protocol', 'eigrp' in g2_errors, g2_errors[:300])
    ctx.shot('P9-01-g2-failed')

    # Fix it and generate again successfully: G3.
    page.click('[name="design-module"][value="eigrp"]')
    save(page)
    page.click('#design-generate')
    wait_state(page, 'Generating', timeout=8000)
    wait_state(page, 'ready', timeout=120000)
    g3_id = generation_id_from_download(page)
    ctx.note(n, 'G3 (succeeded again) id = %s' % g3_id)
    ctx.shot('P9-02-g3-ready-history-has-three')

    history_text = ctx.text('#design-history-body')
    ctx.check(n, 'history lists all three generations (by count of pills/messages)', history_text.count('Waiting to start') + history_text.count('Generating') + history_text.count('Succeeded') + history_text.count('Failed') >= 1 and len(history_text) > 0, history_text[:400])
    clickable_in_history = page.locator('#design-history-body a, #design-history-body button').count()
    ctx.check(n, 'CONFIRMED-target: history has no link/button to open a superseded generation\'s own plan or errors (G1 and G2 become unreachable once G3 exists)', clickable_in_history == 0, 'clickable_elements=%d body=%s' % (clickable_in_history, history_text[:300]))

    download_href = page.locator('#design-download').get_attribute('href') or ''
    ctx.check(n, 'the one Download link always points at the newest generation only (G3), never G1', ('/generations/%s/' % g3_id) in download_href, download_href)

    # Now Remove design and check retention through the promised workflow.
    open_more_menu(page, 'design-clear')
    page.wait_for_selector('#design-clear-run', timeout=5000)
    page.click('#design-clear-run')
    page.wait_for_timeout(500)
    ctx.shot('P9-03-after-remove-design')
    state_after_clear = ctx.text('#design-state')
    history_after_clear = ctx.text('#design-history-body')
    download_after_clear = page.locator('#design-download')
    download_visible = download_after_clear.count() == 1 and not download_after_clear.is_hidden()
    download_href_after_clear = download_after_clear.get_attribute('href') if download_visible else ''
    guided_modules_checked = page.locator('#design-modules input[name="design-module"]:checked').count()
    advanced_after_clear = ctx.val('#design-advanced')
    # designStateOf() (network-design.js) never checks view.intent at all: it derives the header purely
    # from the newest generation's status/staleness. A retained, non-stale succeeded generation therefore
    # keeps reporting "Plan ready to review" even though the design that produced it was just removed —
    # the guided form and Advanced JSON correctly go back to empty, but the header and the whole
    # "Generated plan" card keep presenting G3 as a live, current, ready-to-review result.
    ctx.check(n, 'CONFIRMED-target: the header still says "Plan ready to review" (not "No design yet") right after Remove design, because designStateOf() never checks whether an intent is actually saved — a retained plan masquerades as belonging to a current design', 'ready' in state_after_clear.lower() or 'Plan ready' in state_after_clear, state_after_clear)
    ctx.check(n, 'meanwhile the guided form and Advanced JSON correctly show the design is gone (no modules checked, empty intent) — a direct, visible contradiction with the still-"ready" header/plan card on the same page', guided_modules_checked == 0 and '"modules": []' in advanced_after_clear, 'checked=%d advanced=%s' % (guided_modules_checked, advanced_after_clear[:200]))
    ctx.check(n, 'history still lists the retained generations after Remove design (server keeps them, per the event message)', len(history_after_clear.strip()) > 0 and 'No plans generated' not in history_after_clear, history_after_clear[:300])
    ctx.check(n, 'the last succeeded generation (G3) is still downloadable after Remove design', download_visible and ('/generations/%s/' % g3_id) in (download_href_after_clear or ''), download_href_after_clear)
    ctx.note(n, 'G1/G2 remain server-side but have no path back to their own files/errors through the UI once superseded (same gap as before Remove design)')


# ---------------------------------------------------------------------------------------------------
# Probe 10: falsy/default coercion, and a module checkbox that silently reverts
# ---------------------------------------------------------------------------------------------------
def probe10(ctx, page, base, labs):
    n = 10
    lab_id = labs['ospf-basics']
    goto_design(page, base, lab_id)
    baseline = {
        'schema': 1, 'label': 'P10', 'families': {'ipv4': True, 'ipv6': True},
        'addressing': {'loopback': {'ipv4': '10.255.0.0/24', 'ipv6': '2001:db8:ff::/48'},
                       'p2p': {'ipv4': '10.1.0.0/16', 'ipv6': '2001:db8:1::/48', 'prefix': 31},
                       'lan': {'ipv4': '172.16.0.0/16', 'ipv6': '2001:db8:2::/48', 'prefix': 24}},
        'modules': ['bgp'], 'bgp': {'as': 65010},
        'nodes': {}, 'links': {}, 'vlans': {}, 'vrfs': {}, 'interfaces': {}, 'allocations': {},
    }
    set_advanced(page, baseline)
    save(page)

    # 10a: BGP AS = "0" silently becomes 65000.
    page.fill('#design-bgp-as', '0')
    page.locator('#design-bgp-as').dispatch_event('change')
    blur_form(page)
    as_field_shown = ctx.val('#design-bgp-as')
    advanced_now = ctx.val('#design-advanced')
    ctx.shot('P10-01-as-zero-coerced')
    ctx.check(n, 'CONFIRMED-target: typing AS 0 is silently coerced to the default 65000 (falsy Number(...)||65000), not flagged as invalid', as_field_shown == '65000' and '"as": 65000' in advanced_now, 'field=%r advanced=%s' % (as_field_shown, advanced_now[:200]))
    problems_after_zero = ctx.text('#design-problems')
    ctx.check(n, 'no problem/warning is raised about the 0 being replaced', problems_after_zero.strip() == '', problems_after_zero)

    # 10b: p2p prefix blank silently becomes 31.
    page.fill('#design-pool-p2p-prefix', '')
    page.locator('#design-pool-p2p-prefix').dispatch_event('change')
    blur_form(page)
    p2p_prefix_shown = ctx.val('#design-pool-p2p-prefix')
    ctx.shot('P10-02-p2p-prefix-blank-coerced')
    ctx.check(n, 'CONFIRMED-target: a blank p2p prefix size is silently coerced to the default 31', str(p2p_prefix_shown) == '31', p2p_prefix_shown)

    # 10c: the vrf module checkbox silently reverts to checked while a VRF row still exists.
    page.click('#design-vrf-add')
    page.wait_for_selector('[data-design-vrf-key]', timeout=5000)
    name_box = page.locator('[data-design-vrf-key] [data-design-vrf-field="name"]').first
    name_box.fill('red')
    name_box.dispatch_event('change')
    blur_form(page)
    vrf_box = page.locator('input[name="design-module"][value="vrf"]')
    vrf_checked_after_add = vrf_box.is_checked()
    ctx.shot('P10-03-vrf-module-auto-checked-after-naming-a-vrf')
    ctx.check(n, 'defining a VRF auto-enables the vrf module (documented behaviour)', vrf_checked_after_add)

    # Since QA-012 the box is re-synced from the draft on every render (a module with VRFs defined stays on and a
    # notice says why), so a plain click is used here: uncheck() would refuse when the box bounces back.
    vrf_box.click()
    vrf_box.dispatch_event('change')
    blur_form(page)
    vrf_checked_right_after = page.locator('input[name="design-module"][value="vrf"]').is_checked()
    draft_modules_right_after = page.evaluate("() => designState.draft && designState.draft.intent && designState.draft.intent.modules")
    ctx.shot('P10-04-vrf-checkbox-immediately-after-manual-uncheck')
    ctx.check(n, 'CONFIRMED-target: the checkbox visually stays unchecked (a checkbox click gets no follow-up blur re-render), but the underlying draft silently kept the vrf module on — an invisible desync', not vrf_checked_right_after and bool(draft_modules_right_after) and 'vrf' in draft_modules_right_after, 'checkbox_checked=%s draft_modules=%s' % (vrf_checked_right_after, draft_modules_right_after))
    problems_right_after = ctx.text('#design-problems')
    ctx.check(n, 'no message explains the desync at this point', problems_right_after.strip() == '', problems_right_after)

    # Steps 10a/10b left an AS of 0 and a blank p2p prefix, which the fixed product refuses by name (QA-012): valid values
    # go back in so the Save below can succeed and the checkbox path can be judged.
    page.fill('#design-bgp-as', '65020'); page.locator('#design-bgp-as').dispatch_event('change')
    page.fill('#design-pool-p2p-prefix', '31'); page.locator('#design-pool-p2p-prefix').dispatch_event('change')
    blur_form(page)
    save(page)
    vrf_checked_after_save = page.locator('input[name="design-module"][value="vrf"]').is_checked()
    advanced_after_save = ctx.val('#design-advanced')
    ctx.shot('P10-05-vrf-checkbox-after-save-still-shows-unchecked')
    # setMarkup (app.js) caches the last HTML string per element and skips reassigning innerHTML when the
    # newly computed string is byte-identical to the cached one. Because the vrf checkbox's re-added state
    # renders to the SAME markup string as it did right after "Add VRF" (P10-03), the DOM's live .checked
    # property is never actually touched again after our manual uncheck — so the desync is not a visible
    # "snap back" but a PERSISTENT, invisible-to-the-user mismatch: Save reports success, #design-problems
    # stays empty, and the checkbox keeps showing unchecked even though the module it controls is still on.
    ctx.check(n, 'CONFIRMED-target: after Save succeeds, the checkbox still visually shows unchecked (setMarkup\'s string-equality cache skips the DOM update) even though the saved intent still has the vrf module on — a persistent, invisible desync, not a visible revert', not vrf_checked_after_save and '"vrf"' in advanced_after_save, 'checkbox_checked=%s advanced=%s' % (vrf_checked_after_save, advanced_after_save[:300]))
    page.reload()
    goto_design(page, base, lab_id)
    vrf_checked_after_reload = page.locator('input[name="design-module"][value="vrf"]').is_checked()
    ctx.shot('P10-06-vrf-checkbox-corrects-itself-only-after-a-full-reload')
    ctx.check(n, 'only a full page reload (a fresh render with no stale setMarkup cache) reveals the module was in fact still on the whole time', vrf_checked_after_reload)


PROBES = {1: probe1, 2: probe2, 3: probe3, 4: probe4, 5: probe5, 6: probe6, 7: probe7, 8: probe8, 9: probe9, 10: probe10}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=8098)
    parser.add_argument('--data', default='')
    parser.add_argument('--probes', default='1,2,3,4,5,6,7,8,9,10')
    parser.add_argument('--keep-data', action='store_true')
    parser.add_argument('--launch-fixture', action='store_true', default=True)
    parser.add_argument('--no-launch-fixture', dest='launch_fixture', action='store_false')
    args = parser.parse_args()
    if args.port == 8097:
        raise SystemExit('port 8097 is reserved for another agent\'s fixture manager; use 8098')

    wanted = sorted(int(p) for p in args.probes.split(',') if p.strip())
    base = 'http://127.0.0.1:%d' % args.port
    started = datetime.now(timezone.utc).isoformat(timespec='seconds')

    fixture = None
    data_dir = Path(args.data) if args.data else Path(tempfile.mkdtemp(prefix='design-probes-'))
    if args.launch_fixture:
        data_dir.mkdir(parents=True, exist_ok=True)
        fixture = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(args.port), '--data', str(data_dir)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        wait_http(base + '/api/state')
        labs = lab_map(base)
        print('Run started %s against %s, data dir %s' % (started, base, data_dir))
        print('Labs: %s' % labs)

        all_checks = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            chromium_version = browser.version
            print('Chromium %s' % chromium_version)
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            page = context.new_page()
            ctx = Ctx(page)
            for num in wanted:
                fn = PROBES[num]
                print('\n=== Probe %d ===' % num)
                try:
                    if num == 8:
                        fn(ctx, page, base, labs, context)
                    else:
                        fn(ctx, page, base, labs)
                except Exception as exc:
                    ctx.check(num, 'probe %d raised an exception (see detail)' % num, False, repr(exc))
                    try:
                        ctx.shot('P%d-EXCEPTION' % num)
                    except Exception:
                        pass
            browser.close()
            all_checks = ctx.checks
            console_errors = ctx.console
            page_errors = ctx.pageerrors

        print('\n=== Summary ===')
        by_probe = {}
        for c in all_checks:
            by_probe.setdefault(c['probe'], []).append(c)
        for num in wanted:
            rows = by_probe.get(num, [])
            failed = [r for r in rows if not r['ok']]
            print('P%d: %d/%d checks passed' % (num, len(rows) - len(failed), len(rows)))
        print('Console errors: %d, page errors: %d' % (len(console_errors), len(page_errors)))
        for e in console_errors:
            print('  console: %s' % e['text'][:200])
        for e in page_errors:
            print('  pageerror: %s' % e[:200])
        return 0
    finally:
        if fixture is not None:
            fixture.terminate()
            try: fixture.wait(timeout=10)
            except subprocess.TimeoutExpired: fixture.kill()
        if fixture is not None and not args.keep_data:
            shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
