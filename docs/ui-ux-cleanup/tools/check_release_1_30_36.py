#!/usr/bin/env python3
"""Independent browser verification of the 1.30.36 browser-visible items (B1-B7, D1) against the
REAL running manager and the real lab VM (never a fixture, never disposable data). Copies the
console/page-error capture and viewport conventions of docs/redesign/tools/verify_after.py, but
drives the manager this QA pass was assigned, not the fixture manager, and never deploys, destroys,
saves progress, restores or starts a capture — those actions are only opened and read.

    export LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps
    clab-backup-ui/.venv/bin/python docs/ui-ux-cleanup/tools/check_release_1_30_36.py

Writes screenshots and report.json under docs/ui-ux-cleanup/evidence/.
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8081')
OUT = os.environ.get('CLAB_SHOTS', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'evidence'))
LAB_NAME = os.environ.get('CLAB_LAB', 'restore-square')
TOPO_PATH = '/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml'


class Run:
    def __init__(self, page, tag):
        self.page, self.tag = page, tag
        self.results = []  # list of dict: id, ok(bool or None), detail
        page.on('console', lambda m: CONSOLE.append({'tag': tag, 'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: PAGEERRORS.append({'tag': tag, 'text': str(e)}))

    def rec(self, item, ok, detail=''):
        self.results.append({'item': item, 'ok': ok, 'detail': str(detail)[:2000]})
        status = 'PASS' if ok is True else ('FAIL' if ok is False else 'INFO')
        print(f'[{self.tag}] {status} {item}: {str(detail)[:300]}', flush=True)

    def shot(self, name, full=False):
        path = os.path.join(OUT, f'{self.tag}-{name}.png')
        try:
            self.page.screenshot(path=path, full_page=full)
        except Exception as exc:
            print(f'  (screenshot failed: {exc})')
        return path

    def js(self, expr, arg=None):
        return self.page.evaluate(expr, arg)


CONSOLE = []
PAGEERRORS = []
HANDLED = 'Failed to load resource: the server responded with a status of '
ALL_RESULTS = []


def goto_home(r):
    """Back to My labs the way a student goes: the breadcrumb. A bare '/' restores the last lab from
    sessionStorage (hash -> sessionStorage -> Home) rather than showing the card grid, so only a
    fresh document (no state loaded yet) uses goto (docs/redesign/tools/verify_after.py go_home)."""
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


def open_topology_file_dialog(r):
    """Home -> Choose a file on the lab VM... -> navigate to restore-square.clab.yml -> op-editor dialog."""
    p = r.page
    goto_home(r)
    p.click('#home-deploy')
    p.wait_for_selector('#op-browser[open]', timeout=15000)
    p.wait_for_selector('#op-file-tree summary', timeout=15000)
    p.locator('#op-file-tree summary', has_text='/srv/containerlab-node-manager/projects').first.click()
    p.wait_for_selector('#op-file-tree details[open] summary', timeout=15000)
    p.locator('#op-file-tree details details summary', has_text='restore-square').first.click()
    p.wait_for_function(
        '() => [...document.querySelectorAll("#op-file-tree .op-tree-file")].some(b => b.textContent.includes("restore-square.clab.yml"))',
        timeout=15000)
    p.locator('#op-file-tree .op-tree-file', has_text='restore-square.clab.yml').first.click()
    p.wait_for_selector('#op-editor[open]', timeout=15000)
    p.wait_for_selector('#op-edit-text', timeout=15000)
    p.wait_for_function('() => document.getElementById("op-edit-text").value.length > 0', timeout=15000)


# ---------------------------------------------------------------------------
# B2 + B3 + B4: Topology file dialog -> Open in Lab Builder..., Preview topology, Deploy review
# ---------------------------------------------------------------------------
def check_b2_b4(r):
    p = r.page
    open_topology_file_dialog(r)
    r.shot('b2-topology-file-dialog')
    buttons = r.js('() => [...document.querySelectorAll("#op-editor .actions button")].map(b => b.textContent.trim())')
    r.rec('B2: dialog button label is "Open in Lab Builder..." not "Edit visually..."',
          'Open in Lab Builder…' in buttons and 'Edit visually…' not in buttons, buttons)

    # Click Open in Lab Builder...
    p.click('#op-build-edit')
    p.wait_for_url('**/static/lab-builder.html**', timeout=15000)
    p.wait_for_selector('.react-flow__node', timeout=30000)
    r.rec('B2: Lab Builder opens with the topology (.react-flow__node present)', True,
          r.js('() => document.querySelectorAll(".react-flow__node").length') )
    r.shot('b2-lab-builder-opened')

    # "<- My labs" link back
    back_href = r.js('() => document.querySelector("a.builder-back")?.getAttribute("href")')
    r.rec('B2: builder back link exists and points to /', back_href == '/', back_href)
    p.click('a.builder-back')
    try:
        p.wait_for_selector('#op-editor[open]', timeout=15000)
        p.wait_for_function('() => document.getElementById("op-edit-text").value.length > 0', timeout=15000)
        path_val = r.js('() => document.getElementById("op-edit-path")?.value')
        text_len = r.js('() => document.getElementById("op-edit-text")?.value.length')
        r.rec('B2: "<- My labs" reopens the Topology file dialog on the same VM path with YAML content',
              path_val == TOPO_PATH and text_len and text_len > 0, {'path': path_val, 'text_len': text_len})
        r.shot('b2-reopened-after-my-labs-link')
    except Exception as exc:
        r.rec('B2: "<- My labs" reopens the Topology file dialog on the same VM path with YAML content',
              False, repr(exc))
        r.shot('b2-reopen-FAILED-my-labs-link')

    # Now test browser Back button: reopen builder from the (now reopened) dialog, then use page.go_back()
    p.click('#op-build-edit')
    p.wait_for_url('**/static/lab-builder.html**', timeout=15000)
    p.wait_for_selector('.react-flow__node', timeout=30000)
    r.shot('b2-lab-builder-before-browser-back')
    p.go_back()
    try:
        p.wait_for_selector('#op-editor[open]', timeout=15000)
        p.wait_for_function('() => document.getElementById("op-edit-text").value.length > 0', timeout=15000)
        path_val = r.js('() => document.getElementById("op-edit-path")?.value')
        r.rec('B2: browser Back button from the builder also reopens the Topology file dialog',
              path_val == TOPO_PATH, {'path': path_val, 'url': p.url})
        r.shot('b2-reopened-after-browser-back')
    except Exception as exc:
        r.rec('B2: browser Back button from the builder also reopens the Topology file dialog',
              False, f'{exc!r} url={p.url}')
        r.shot('b2-reopen-FAILED-browser-back')

    # If the dialog did not reopen, re-navigate fresh for the rest of the checks.
    if not p.evaluate('() => document.getElementById("op-editor")?.open'):
        open_topology_file_dialog(r)

    # B3: Preview topology
    check_b3(r)

    # Re-open the file dialog if the preview closed things unexpectedly
    if not p.evaluate('() => document.getElementById("op-editor")?.open'):
        open_topology_file_dialog(r)

    # B4: Deploy review
    check_b4(r)

    if p.evaluate('() => document.getElementById("op-editor")?.open'):
        p.click('#op-editor [data-op-close]')
    if p.evaluate('() => document.getElementById("op-browser")?.open'):
        p.click('#op-browser [data-op-close]')


def check_b3(r):
    p = r.page
    if not p.evaluate('() => document.getElementById("op-editor")?.open'):
        open_topology_file_dialog(r)
    p.click('#op-validate')
    p.wait_for_selector('#op-map-preview[open]', timeout=15000)
    p.wait_for_timeout(400)
    info = r.js('''() => {
      const d = document.getElementById('op-map-preview'), rect = d.getBoundingClientRect();
      return {width: rect.width, height: rect.height, vw: innerWidth, vh: innerHeight,
              text: d.textContent, svgHidden: !document.getElementById('op-preview-map'),
              svgClient: document.getElementById('op-preview-map')?.getBoundingClientRect()};
    }''')
    wpct = info['width'] / info['vw'] * 100
    hpct = info['height'] / info['vh'] * 100
    caption_absent = 'Wiring from the topology file; device positions from its saved map file.' not in info['text']
    r.rec(f'B3 [{r.tag}]: preview dialog size vs viewport (width {wpct:.0f}%, height {hpct:.0f}%, expect >=80% of both, with margins, no clipping)',
          wpct >= 80 and hpct >= 80, info)
    r.rec(f'B3 [{r.tag}]: caption "Wiring from the topology file; device positions from its saved map file." is absent',
          caption_absent, info['text'][-300:])
    r.shot('b3-preview-dialog')
    p.click('#op-map-preview [data-op-close]')


def check_b4(r):
    p = r.page
    if not p.evaluate('() => document.getElementById("op-editor")?.open'):
        open_topology_file_dialog(r)
    p.click('#op-deploy-project')
    p.wait_for_selector('#operation-review[open]', timeout=20000)
    p.wait_for_timeout(300)
    info = r.js('''() => {
      const d = document.getElementById('operation-review');
      return {title: d.querySelector('h2')?.textContent, text: d.textContent,
              hasDetails: !!d.querySelector('details'), hasSummary: !!d.querySelector('summary'),
              hasCommandHeading: !!d.querySelector('h4')?.textContent,
              headings: [...d.querySelectorAll('h4')].map(h => h.textContent),
              pre: d.querySelector('pre.op-output')?.textContent || '',
              confirm: document.getElementById('op-confirm')?.textContent};
    }''')
    r.rec('B4: review title is "Start restore-square?"', info['title'] == f'Start {LAB_NAME}?', info['title'])
    r.rec('B4: no orange "Runs this trusted topology with host privileges..." box',
          'Runs this trusted topology with host privileges' not in info['text'], '')
    r.rec('B4: no "Runs on the lab VM. If the lab changes before you confirm, this check is repeated." caption',
          'Runs on the lab VM. If the lab changes before you confirm, this check is repeated.' not in info['text'], '')
    r.rec('B4: no "Technical details" summary wrapper (command shown directly)',
          'Technical details' not in info['text'], info['headings'])
    r.rec('B4: "Command run on the VM" with the containerlab argv is visible directly',
          'Command run on the VM' in info['headings'] and 'containerlab' in info['pre'], info['pre'][:300])
    r.shot('b4-deploy-review')
    p.click('#op-cancel')


# ---------------------------------------------------------------------------
# B5: banners can be hidden and stay hidden across a reload
# ---------------------------------------------------------------------------
def check_b5(r):
    p = r.page
    open_lab(r, LAB_NAME)
    p.wait_for_timeout(600)
    lab_banner = r.js('''() => {
      const b = document.getElementById('lab-banner');
      return {hidden: b.hidden, text: document.getElementById('lab-banner-text')?.textContent,
              closeLabel: document.getElementById('lab-banner-close')?.getAttribute('aria-label')};
    }''')
    home_banner = None
    if lab_banner['hidden']:
        p.click('#crumb-home')
        p.wait_for_selector('#home:not([hidden])', timeout=10000)
        p.wait_for_timeout(600)
        home_banner = r.js('''() => {
          const b = document.getElementById('home-banner');
          return {hidden: b.hidden, text: document.getElementById('home-banner-text')?.textContent,
                  closeLabel: document.getElementById('home-banner-close')?.getAttribute('aria-label')};
        }''')
    # Not a product failure either way: restore-square's devices are all Ready and the VM is
    # connected, so this run's state has no notice to show. Recorded as INFO, not a FAIL.
    r.rec('B5: banner found on the lab or home page (this lab is currently fully healthy, so none may be showing)',
          None if (lab_banner['hidden'] and not (home_banner and not home_banner['hidden'])) else True,
          {'lab_banner': lab_banner, 'home_banner': home_banner})
    r.shot('b5-banner-before-dismiss', full=True)
    target = None
    if not lab_banner['hidden']:
        target = ('lab-banner', lab_banner)
        open_lab(r, LAB_NAME)
    elif home_banner and not home_banner['hidden']:
        target = ('home-banner', home_banner)
    if not target:
        r.rec('B5: no banner visible on lab or home page — nothing to dismiss', None, '')
        return
    banner_id, info = target
    r.rec(f'B5: {banner_id} close control has aria-label "Hide this notice"',
          info['closeLabel'] == 'Hide this notice', info)
    p.click(f'#{banner_id}-close')
    hidden_now = r.js(f'() => document.getElementById("{banner_id}").hidden')
    r.rec('B5: clicking the close control hides the banner', hidden_now, '')
    r.shot('b5-banner-after-dismiss', full=True)
    p.reload()
    p.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=15000)
    if banner_id == 'lab-banner':
        open_lab(r, LAB_NAME)
    else:
        p.wait_for_selector('#home:not([hidden])', timeout=10000)
    p.wait_for_timeout(800)
    hidden_after_reload = r.js(f'() => document.getElementById("{banner_id}").hidden')
    r.rec('B5: dismissal survives a reload (sessionStorage)', hidden_after_reload, '')
    r.shot('b5-banner-after-reload', full=True)


# ---------------------------------------------------------------------------
# B6: host1 (network-multitool) credential state
# ---------------------------------------------------------------------------
def check_b6(r):
    p = r.page
    open_lab(r, LAB_NAME)
    tab(r, 'topology')
    p.wait_for_selector('#topology-devices .device-row', timeout=15000)
    rail_row = r.js('''() => {
      const rows = [...document.querySelectorAll('#topology-devices .device-row')];
      const row = rows.find(li => li.querySelector('.node-name')?.textContent.trim() === 'host1');
      if (!row) return null;
      const cli = row.querySelector('[data-terminal]');
      return {pill: row.querySelector('.pill')?.textContent, needsCreds: /needs credentials|add login credentials/i.test(row.textContent),
              cliDisabled: cli?.disabled, cliTitle: cli?.title, rowText: row.textContent.replace(/\\s+/g,' ').trim()};
    }''')
    r.rec('B6: Topology tab device rail row for host1 found', rail_row is not None, rail_row)
    if rail_row:
        r.rec('B6: Topology rail row does not say "Needs credentials"/"Add login credentials..."',
              not rail_row['needsCreds'], rail_row)
        r.rec('B6: Topology rail Open CLI is enabled for host1', rail_row['cliDisabled'] is False, rail_row)
    r.shot('b6-topology-rail')

    tab(r, 'devices')
    p.wait_for_selector('#device-list .device-row', timeout=15000)
    dev_row = r.js('''() => {
      const rows = [...document.querySelectorAll('#device-list .device-row')];
      const row = rows.find(li => li.querySelector('.node-name')?.textContent.trim() === 'host1');
      if (!row) return null;
      const cli = row.querySelector('[data-terminal]');
      return {pill: row.querySelector('.pill')?.textContent, needsCreds: /needs credentials|add login credentials/i.test(row.textContent),
              cliDisabled: cli?.disabled, cliTitle: cli?.title, rowText: row.textContent.replace(/\\s+/g,' ').trim()};
    }''')
    r.rec('B6: Devices tab row for host1 found', dev_row is not None, dev_row)
    if dev_row:
        r.rec('B6: Devices tab row does not say "Needs credentials"/"Add login credentials..."',
              not dev_row['needsCreds'], dev_row)
        r.rec('B6: Devices tab Open CLI is enabled for host1', dev_row['cliDisabled'] is False, dev_row)
    r.shot('b6-devices-tab')


# ---------------------------------------------------------------------------
# B7: Topology tab hints, Details removal, device rail scrolling
# ---------------------------------------------------------------------------
def check_b7(r, force_1366_short=False):
    p = r.page
    open_lab(r, LAB_NAME)
    tab(r, 'topology')
    p.wait_for_selector('#topology-map [data-map-node]', timeout=15000)
    text_checks = r.js('''() => ({
      hasDetailsWiring: /Lines show how the lab is wired, not whether links are up\\./.test(document.getElementById('topology-view').textContent),
      hint: document.getElementById('topology-hint')?.textContent,
    })''')
    r.rec(f'B7 [{r.tag}]: "Details" disclosure / "Lines show how the lab is wired..." sentence is absent',
          not text_checks['hasDetailsWiring'], text_checks)
    r.rec(f'B7 [{r.tag}]: hint text present',
          text_checks['hint'] == 'Click a device to open it. Click a link to capture its traffic. Right-click for more actions.',
          text_checks['hint'])

    layout = r.js('''() => {
      const rail = document.querySelector('aside.device-rail');
      const cs = getComputedStyle(rail);
      const cols = getComputedStyle(document.querySelector('.topology-layout')).gridTemplateColumns;
      return {scrollHeight: rail.scrollHeight, clientHeight: rail.clientHeight, overflowY: cs.overflowY,
              columns: cols, colCount: cols.split(' ').length};
    }''')
    if r.tag == '390x844':
        # Below the 1280px breakpoint the rail intentionally stacks under the map and scrolls with
        # the page again (style.css "Breakpoints" section); independent scrolling is desktop-only.
        r.rec(f'B7 [{r.tag}]: below the 1280px breakpoint the rail scrolls with the page (overflow-y visible), not independently',
              layout['overflowY'] == 'visible' and layout['colCount'] == 1, layout)
    else:
        r.rec(f'B7 [{r.tag}]: device rail overflow-y is auto/scroll (independently scrollable)', layout['overflowY'] in ('auto', 'scroll'), layout)
    r.shot(f'b7-topology-{r.tag}')

    overflowed = layout['scrollHeight'] > layout['clientHeight'] + 1
    if not overflowed and force_1366_short:
        p.set_viewport_size({'width': 1366, 'height': 600})
        p.wait_for_timeout(300)
        layout = r.js('''() => {
          const rail = document.querySelector('aside.device-rail');
          return {scrollHeight: rail.scrollHeight, clientHeight: rail.clientHeight};
        }''')
        overflowed = layout['scrollHeight'] > layout['clientHeight'] + 1
        r.shot('b7-topology-1366x600-forced')

    r.rec(f'B7 [{r.tag}]: rail overflow numbers (scrollHeight {layout["scrollHeight"]} vs clientHeight {layout["clientHeight"]}, overflowed={overflowed})',
          None, layout)

    if overflowed:
        before = r.js('() => ({railScroll: document.querySelector("aside.device-rail").scrollTop, winScroll: window.scrollY})')
        r.js('() => { document.querySelector("aside.device-rail").scrollTop = 200; }')
        p.wait_for_timeout(150)
        after = r.js('() => ({railScroll: document.querySelector("aside.device-rail").scrollTop, winScroll: window.scrollY, headingVisible: (() => { const h = document.querySelector("aside.device-rail h2"); const r = h.getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight; })(), mapVisible: (() => { const m = document.getElementById("topology-map"); return m.getBoundingClientRect().height > 0 && getComputedStyle(m).visibility !== "hidden"; })() })')
        r.rec(f'B7 [{r.tag}]: scrolling the rail (scrollTop=200) changes only the rail, not the window; heading stays visible; map stays visible',
              after['railScroll'] > 0 and after['winScroll'] == before['winScroll'] and after['headingVisible'] and after['mapVisible'],
              {'before': before, 'after': after})
        r.shot(f'b7-topology-{r.tag}-scrolled')
    else:
        r.rec(f'B7 [{r.tag}]: rail did not overflow at this size even after forcing — scroll-behaviour not exercised', None, layout)

    if r.tag == '390x844':
        stacked = r.js('() => getComputedStyle(document.querySelector(".topology-layout")).gridTemplateColumns.split(" ").length === 1')
        r.rec('B7 [390x844]: layout stacks to a single column', stacked, '')


# ---------------------------------------------------------------------------
# B1: Upload dialog has the optional annotations input
# ---------------------------------------------------------------------------
def check_b1(r):
    p = r.page
    goto_home(r)
    p.click('#home-upload')
    p.wait_for_selector('#op-upload[open]', timeout=15000)
    info = r.js('''() => {
      const label = [...document.querySelectorAll('#op-upload label')].find(l => l.textContent.includes('Saved map'));
      return {labelText: label?.textContent, hasInput: !!document.getElementById('op-upload-annotations'),
              helpAfter: label?.nextElementSibling?.tagName === 'DIV' ? label.nextElementSibling.textContent : '',
              order: [...document.querySelectorAll('#op-upload label, #op-upload .upload-field')].map(e => e.tagName + ':' + (e.querySelector('input')?.id || e.textContent.slice(0,30)))};
    }''')
    r.rec('B1: second file input "Saved map (annotations JSON, optional)" exists below the topology input',
          info['hasInput'] and 'Saved map' in (info['labelText'] or '') and 'optional' in (info['labelText'] or '').lower(),
          info)
    r.shot('b1-upload-dialog')
    p.click('#op-upload-cancel')


# ---------------------------------------------------------------------------
# D1: capture endpoint -> container interface mapping
# ---------------------------------------------------------------------------
def find_wire_locator(p, a, b):
    return p.locator(f'g.topology-wire[data-capture-endpoints*="{a}"][data-capture-endpoints*="{b}"]').first


def check_d1(r):
    p = r.page
    open_lab(r, LAB_NAME)
    tab(r, 'topology')
    p.wait_for_selector('#topology-map [data-map-node]', timeout=15000)

    cases = [
        ('vjunos-switch', 'cjunosevolved', 'vjunos-switch', 'eth1', 'primary endpoint (ge-0/0/0 side)'),
        ('vjunos-switch', 'cjunosevolved', 'cjunosevolved', None, 'other endpoint (switch to it)'),
        ('vjunos-switch', 'xrv9k', 'xrv9k', 'eth1', 'Gi0/0/0/0 side'),
        ('ceos', 'xrv9k', 'ceos', 'eth2', 'ceos side of ceos<->xrv9k'),
        ('host1', 'vjunos-switch', 'host1', 'eth1', 'host1 side (identity mapping)'),
    ]
    for a, b, want_endpoint, expect_iface, note in cases:
        wire = find_wire_locator(p, a, b)
        count = wire.count()
        if not count:
            r.rec(f'D1: link {a}<->{b} ({note}) found on the map', False, 'no matching .topology-wire element')
            continue
        wire.scroll_into_view_if_needed()
        # Long wires (e.g. an endpoint two positions away in the auto-laid-out row) can overlap
        # other wires' bounding boxes; a real mouse click at the box centre can hit whichever path
        # paints on top. Dispatch the click straight at this element (the delegated handler reads
        # event.target.closest('[data-capture-endpoints]')), which is exact regardless of overlap.
        wire.dispatch_event('click')
        try:
            p.wait_for_selector('#capture-dialog[open]', timeout=10000)
        except Exception as exc:
            r.rec(f'D1: link {a}<->{b} ({note}) opens the capture dialog', False, repr(exc))
            continue
        # Switch to the wanted endpoint if it is not already selected.
        endpoints = r.js('() => [...document.querySelectorAll("#capture-endpoints [data-capture-end]")].map(b => b.textContent)')
        idx = next((i for i, t in enumerate(endpoints) if want_endpoint in t), None)
        if idx is not None:
            p.click(f'#capture-endpoints [data-capture-end="{idx}"]')
            p.wait_for_timeout(900)
        else:
            p.wait_for_timeout(900)
        status = r.js('() => document.getElementById("capture-status").textContent')
        ctx = r.js('() => document.getElementById("capture-context").textContent')
        checked = r.js('() => document.querySelector("#capture-interfaces input:checked")?.value || document.querySelector("#capture-interfaces-all input:checked")?.value || ""')
        r.rec(f'D1: {a}<->{b} endpoint "{want_endpoint}" ({note}) -> status text and preselected interface',
              None, {'endpoints': endpoints, 'chosen_idx': idx, 'context': ctx, 'status': status, 'checked_interface': checked})
        if expect_iface:
            r.rec(f'D1: {a}<->{b} endpoint "{want_endpoint}" preselects {expect_iface} (not a tapN)',
                  checked == expect_iface, {'checked': checked, 'status': status})
        r.shot(f'd1-{a}-{b}-{want_endpoint}')
        p.click('#capture-close')
        p.wait_for_timeout(150)


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)

        # Desktop context for most single-viewport checks
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = ctx.new_page()
        r = Run(page, '1920x1080')
        for fn in (check_b1, check_b2_b4, check_b5, check_b6, check_d1):
            try:
                fn(r)
            except Exception as exc:
                r.rec(f'{fn.__name__}: completed without an uncaught exception', False, repr(exc))
                r.shot(f'zz-{fn.__name__}-error')
        ALL_RESULTS.extend(r.results)
        ctx.close()

        # B3 also at laptop size (1366x768)
        ctx2 = browser.new_context(viewport={'width': 1366, 'height': 768})
        page2 = ctx2.new_page()
        r2 = Run(page2, '1366x768')
        try:
            open_topology_file_dialog(r2)
            check_b3(r2)
        except Exception as exc:
            r2.rec('check_b3 at 1366x768: completed', False, repr(exc))
        ALL_RESULTS.extend(r2.results)

        # B7 across three viewports (reuse the 1366x768 context)
        for tag, w, h, force in (('1920x1080', 1920, 1080, False), ('1366x768', 1366, 768, True), ('390x844', 390, 844, False)):
            cctx = browser.new_context(viewport={'width': w, 'height': h})
            cpage = cctx.new_page()
            rr = Run(cpage, tag)
            try:
                check_b7(rr, force_1366_short=force)
            except Exception as exc:
                rr.rec(f'check_b7 at {tag}: completed', False, repr(exc))
                rr.shot(f'zz-check_b7-{tag}-error')
            ALL_RESULTS.extend(rr.results)
            cctx.close()

        ctx2.close()
        browser.close()

    handled = [e for e in CONSOLE if e['text'].startswith(HANDLED)]
    real = [e for e in CONSOLE if e not in handled]
    report = {'results': ALL_RESULTS, 'console_errors': real, 'handled_http_errors': handled, 'page_errors': PAGEERRORS}
    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)

    passed = sum(1 for x in ALL_RESULTS if x['ok'] is True)
    failed = sum(1 for x in ALL_RESULTS if x['ok'] is False)
    info = sum(1 for x in ALL_RESULTS if x['ok'] is None)
    print(f'\n=== SUMMARY === PASS {passed} / FAIL {failed} / INFO {info}  console_errors={len(real)} handled_http={len(handled)} page_errors={len(PAGEERRORS)}')
    for e in real:
        print('  console error:', e)
    for e in PAGEERRORS:
        print('  page error:', e)
    print('report:', os.path.join(OUT, 'report.json'))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
