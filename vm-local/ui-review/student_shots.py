#!/usr/bin/env python3
"""Student UI screenshot sweep against the live manager.

Walks the pages a student uses (My labs, Topology, Devices, Progress, Tools, Advanced, the
menus and review dialogs, the CLI launcher, the terminal, the deploy page) at one or more
viewports, screenshots each state, records console and page errors, and runs a layout probe
before every screenshot that lists elements spilling past the right edge of the viewport and
text boxes that are clipped without an ellipsis. Nothing is confirmed: no lab operation runs,
nothing is saved.

    CLAB_BASE=http://127.0.0.1:8081 CLAB_SHOTS=~/ui-review/shots CLAB_VIEWPORTS=1440x900 python student_shots.py
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8081')
OUT = os.path.expanduser(os.environ.get('CLAB_SHOTS', '~/ui-review/shots'))
VIEWPORTS = [tuple(int(x) for x in v.split('x')) for v in os.environ.get('CLAB_VIEWPORTS', '1440x900,1280x720,1920x1080').split(',')]
STEPS = os.environ.get('CLAB_STEPS', '').split(',') if os.environ.get('CLAB_STEPS') else None
HANDLED = 'Failed to load resource: the server responded with a status of '

LAYOUT_JS = '''() => {
  const vw = innerWidth;
  const out = {docScrollWidth: document.documentElement.scrollWidth, vw, over: [], clipped: []};
  const skip = el => el.closest('[hidden]') || el.closest('dialog:not([open])') || el.closest('#topology-map') || el.closest('#op-layout-map') || el.closest('svg');
  const label = el => ({tag: el.tagName.toLowerCase(), id: el.id || '', cls: (typeof el.className === 'string' ? el.className : '').slice(0, 60), text: (el.textContent || '').trim().replace(/[\\s]+/g, ' ').slice(0, 70)});
  for (const el of document.querySelectorAll('body *')) {
    if (skip(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    if (r.right > vw + 1 && r.left < vw && out.over.length < 12) out.over.push(Object.assign(label(el), {left: Math.round(r.left), right: Math.round(r.right)}));
    if ((cs.overflowX === 'hidden' || cs.overflow === 'hidden') && cs.textOverflow !== 'ellipsis' && el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 2 && !el.querySelector('svg, canvas, pre, table') && out.clipped.length < 12)
      out.clipped.push(Object.assign(label(el), {scrollWidth: el.scrollWidth, clientWidth: el.clientWidth}));
  }
  return out;
}'''


class Run:
    def __init__(self, page, tag):
        self.page, self.tag = page, tag
        self.console, self.pageerrors, self.shots, self.layout, self.failures = [], [], [], {}, []
        page.on('console', lambda m: self.console.append({'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.pageerrors.append(str(e)))

    def shot(self, name, full=False):
        path = os.path.join(OUT, f'{self.tag}-{name}.png')
        try:
            probe = self.page.evaluate(LAYOUT_JS)
            if probe['over'] or probe['clipped'] or probe['docScrollWidth'] > probe['vw'] + 1:
                self.layout[name] = probe
        except Exception as exc:  # the page may be mid-navigation
            self.layout[name] = {'error': repr(exc)}
        self.page.screenshot(path=path, full_page=full)
        self.shots.append(path)
        print(f'  shot {self.tag}-{name}', flush=True)

    def js(self, expr):
        return self.page.evaluate(expr)

    def open_lab(self):
        p = self.page
        card = p.locator('#home-continue button[data-lab]').first
        if card.count() == 0:
            card = p.locator('article.lab-card button[data-lab]').first
        card.click()
        p.wait_for_selector('#lab-content:not([hidden])', timeout=10000)
        p.wait_for_function('() => document.getElementById("title").textContent.trim().length > 0')

    def tab(self, name):
        self.page.click(f'#tab-{name}')
        self.page.wait_for_selector(f'#{name}-view:not([hidden])', timeout=5000)
        self.page.wait_for_timeout(600)

    def close_dialog(self, selector):
        p = self.page
        btn = p.locator(f'{selector} [data-op-close], {selector} button.close, {selector} [data-dismiss]').first
        if btn.count():
            btn.click()
        else:
            p.keyboard.press('Escape')
        p.wait_for_function(f'() => !document.querySelector("{selector}")?.open', timeout=5000)


def go_home(r):
    p = r.page
    if not p.url.startswith(BASE + '/#') and p.url.rstrip('/') != BASE:
        p.goto(BASE + '/')
    p.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=20000)
    if not p.evaluate('() => document.getElementById("home") && !document.getElementById("home").hidden'):
        p.click('#crumb-home')
    p.wait_for_selector('#home:not([hidden])', timeout=10000)
    p.wait_for_selector('article.lab-card, #empty:not([hidden])', timeout=20000)


def home(r):
    p = r.page
    p.goto(BASE + '/')
    p.wait_for_selector('article.lab-card, #empty:not([hidden])', timeout=20000)
    p.wait_for_timeout(1500)
    r.shot('00-home')
    p.click('#manager-button')
    p.wait_for_selector('#manager-menu-list:not([hidden])')
    r.shot('01-home-manager-menu')
    p.keyboard.press('Escape')


def topology(r):
    p = r.page
    go_home(r)
    r.open_lab()
    p.wait_for_selector('#topology-map [data-map-node], #map-empty:not([hidden])', timeout=20000)
    p.wait_for_timeout(1200)
    r.shot('10-topology')
    node = p.locator('#topology-map [data-map-node]').first
    if node.count():
        node.click(button='right')
        p.wait_for_selector('#node-context-menu:not([hidden])')
        r.shot('11-topology-context-menu')
        p.keyboard.press('Escape')
        p.click('#map-expand')
        p.wait_for_timeout(600)
        r.shot('12-topology-expanded')
        p.keyboard.press('Escape')
        p.wait_for_timeout(300)
        node.click()
        p.wait_for_selector('#details-dialog[open]')
        p.wait_for_timeout(800)
        r.shot('13-device-drawer-map')
        p.click('#details-next')
        p.wait_for_timeout(600)
        r.shot('13b-device-drawer-next')
        p.keyboard.press('Escape')
        p.wait_for_function('() => !document.getElementById("details-dialog").open', timeout=5000)
    p.click('#map-more-button')
    p.wait_for_selector('#map-more-menu:not([hidden])')
    r.shot('15-map-more-menu')
    p.keyboard.press('Escape')


def devices(r):
    p = r.page
    r.tab('devices')
    r.shot('20-devices')
    p.click('#devices-technical')
    p.wait_for_timeout(400)
    r.shot('21-devices-technical', full=True)
    p.click('#devices-technical')
    p.wait_for_timeout(200)
    row = p.locator('#devices-view [data-details]').first
    if row.count():
        row.click()
        p.wait_for_selector('#details-dialog[open]')
        p.wait_for_timeout(800)
        r.shot('22-device-drawer-list')
        adv = p.locator('#details-advanced > summary')
        if adv.count():
            adv.click()
            p.wait_for_timeout(300)
            r.shot('23-device-drawer-advanced')
        p.keyboard.press('Escape')
        p.wait_for_function('() => !document.getElementById("details-dialog").open', timeout=5000)


def progress(r):
    p = r.page
    r.tab('progress')
    p.wait_for_selector('#git-save-location', timeout=20000)
    try:
        p.wait_for_function('() => document.querySelectorAll("#git-saved-versions .git-version-row").length > 0 || /Choose a save location/.test(document.getElementById("git-saved-versions").textContent)', timeout=20000)
    except Exception:
        pass
    p.wait_for_timeout(1000)
    r.shot('30-progress')
    r.shot('30-progress-full', full=True)
    view = p.locator('#git-saved-versions [data-git-version-action="view"]').first
    if view.count():
        view.click()
        p.wait_for_selector('#git-version-dialog[open]')
        p.wait_for_timeout(1200)
        r.shot('34-saved-version')
        r.close_dialog('#git-version-dialog')
    cmp_ = p.locator('#git-saved-versions [data-git-version-action="compare"]').first
    if cmp_.count():
        cmp_.click()
        p.wait_for_selector('#git-diff-dialog[open]')
        p.wait_for_timeout(1500)
        r.shot('35-compare')
        r.close_dialog('#git-diff-dialog')
    apply_ = p.locator('#git-saved-versions [data-git-version-action="apply"]').first
    if apply_.count():
        apply_.click()
        p.wait_for_selector('#restore-review-dialog[open]')
        try:
            p.wait_for_function('() => !!document.getElementById("restore-run") || !!document.querySelector("#restore-review-dialog .form-error")?.textContent', timeout=45000)
        except Exception:
            pass
        p.wait_for_timeout(500)
        r.shot('36-restore-review')
        r.shot('36-restore-review-full', full=True)
        r.close_dialog('#restore-review-dialog')
    last = p.locator('#git-last-restore-open')
    if last.count() and last.is_visible():
        last.click()
        p.wait_for_selector('#restore-job-dialog[open]')
        p.wait_for_timeout(800)
        r.shot('37-restore-job')
        r.close_dialog('#restore-job-dialog')
    save_row = p.locator('#git-saves-list .git-saved-job > summary').first
    if save_row.count():
        save_row.click()
        p.wait_for_timeout(400)
        r.shot('33-recent-save-open', full=True)
        opener = p.locator('#git-saves-list [data-git-job-open]').first
        if opener.count():
            opener.click()
            p.wait_for_selector('#git-job-dialog[open]')
            p.wait_for_timeout(1000)
            r.shot('33b-save-window')
            r.close_dialog('#git-job-dialog')
        save_row.click()
    chk = p.locator('#progress-view [data-git-action="checkpoint"]')
    if chk.count() and chk.first.is_visible():
        chk.first.click()
        p.wait_for_selector('#git-save-options[open]')
        p.fill('#git-checkpoint-name', 'bgp done!')
        p.wait_for_timeout(200)
        r.shot('38-checkpoint')
        p.click('#git-save-cancel')
    menu = p.locator('#git-save-menu')
    if menu.count() and menu.first.is_visible():
        menu.first.click()
        p.wait_for_timeout(300)
        r.shot('38b-save-menu')
        p.keyboard.press('Escape')
    folder = p.locator('#git-change-folder > summary')
    if folder.count():
        folder.click()
        try:
            p.wait_for_selector('#git-places-panel .git-places-head', timeout=20000)
        except Exception:
            pass
        p.wait_for_timeout(800)
        r.shot('31-save-location', full=True)
        if p.evaluate('() => document.getElementById("git-change-folder")?.open'):
            folder.click()


def tools(r):
    p = r.page
    r.tab('tools')
    r.shot('40-tools')
    r.shot('40-tools-full', full=True)
    p.click('#capture-open')
    p.wait_for_selector('#capture-dialog[open]')
    p.wait_for_timeout(1500)
    r.shot('41-capture-dialog')
    r.shot('41-capture-dialog-full', full=True)
    p.click('#capture-close')
    tele = p.locator('#tools-telemetry-settings')
    if tele.count():
        tele.click()
        p.wait_for_selector('#telemetry-settings-dialog[open]', timeout=15000)
        p.wait_for_timeout(500)
        r.shot('42-telemetry-settings')
        r.close_dialog('#telemetry-settings-dialog')


def advanced(r):
    p = r.page
    r.tab('advanced')
    r.shot('51-advanced')
    r.shot('51-advanced-full', full=True)


def menus(r):
    p = r.page
    r.tab('topology')
    p.click('#lab-actions-button')
    p.wait_for_selector('#lab-actions-menu:not([hidden])')
    r.shot('43-lab-actions-menu')
    p.click('#menu-destroy')
    p.wait_for_selector('#operation-review[open]', timeout=15000)
    p.wait_for_timeout(500)
    r.shot('44-destroy-review')
    p.click('#op-cancel')
    p.click('#lab-actions-button')
    p.wait_for_selector('#lab-actions-menu:not([hidden])')
    p.click('#lab-actions')
    p.wait_for_selector('#lab-operations-dialog[open]')
    p.wait_for_timeout(500)
    r.shot('47-all-lab-operations')
    r.close_dialog('#lab-operations-dialog')
    p.click('#manager-button')
    p.wait_for_selector('#manager-menu-list:not([hidden])')
    p.click('#operations-history')
    p.wait_for_selector('#operation-history[open]', timeout=15000)
    p.wait_for_timeout(500)
    r.shot('50-operation-history')
    r.close_dialog('#operation-history')


def pages(r):
    p = r.page
    lab = r.js('() => state.labs[0]')
    p.goto(f'{BASE}/static/workspace.html#mode=ssh&lab={lab["id"]}')
    p.wait_for_selector('#ssh-launch-all', timeout=15000)
    p.wait_for_timeout(600)
    r.shot('55-cli-launcher', full=True)
    p.goto(f'{BASE}/static/workspace.html#mode=folder')
    p.reload()
    p.wait_for_function('() => document.getElementById("workspace-title").textContent === "Deploy a new lab" && !document.getElementById("workspace-open").hidden', timeout=15000)
    p.wait_for_timeout(400)
    r.shot('56-deploy-page')
    p.click('#workspace-open')
    p.wait_for_selector('#op-browser[open]', timeout=15000)
    p.wait_for_timeout(800)
    r.shot('57-topology-browser')
    r.close_dialog('#op-browser')
    ready = next((n for n in lab['nodes'] if n.get('ssh_ready')), lab['nodes'][0])
    p.goto(f'{BASE}/static/terminal.html#lab={lab["id"]}&node={ready["name"]}&label={lab["name"]}')
    p.wait_for_timeout(6000)
    r.shot('61-terminal')
    p.goto(f'{BASE}/static/debug.html')
    p.wait_for_function('() => /^Updated /.test(document.getElementById("debug-status").textContent)', timeout=20000)
    p.wait_for_timeout(400)
    r.shot('59-diagnostics', full=True)
    p.goto(f'{BASE}/static/capture-setup.html')
    p.wait_for_timeout(500)
    r.shot('62-capture-setup', full=True)
    p.goto(f'{BASE}/vm-connection-guide')
    p.wait_for_timeout(500)
    r.shot('63-vm-guide', full=True)


ALL = [home, topology, devices, progress, tools, advanced, menus, pages]


def run_viewport(browser, vw, vh):
    ctx = browser.new_context(viewport={'width': vw, 'height': vh}, device_scale_factor=1)
    page = ctx.new_page()
    r = Run(page, f'{vw}x{vh}')
    for step in ALL:
        if STEPS and step.__name__ not in STEPS:
            continue
        print(f'[{r.tag}] {step.__name__}', flush=True)
        try:
            step(r)
        except Exception as exc:
            r.failures.append({'step': step.__name__, 'error': repr(exc)[:400]})
            print(f'  FAIL {step.__name__}: {exc!r}'[:500], flush=True)
            try:
                r.shot(f'zz-{step.__name__}-error')
            except Exception:
                pass
            for sel in ('#node-context-menu', '#lab-actions-menu', '#manager-menu-list'):
                try:
                    page.keyboard.press('Escape')
                except Exception:
                    pass
            for d in page.query_selector_all('dialog[open]'):
                try:
                    page.evaluate('d => d.close()', d)
                except Exception:
                    pass
    ctx.close()
    return r


def main():
    os.makedirs(OUT, exist_ok=True)
    report = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        for vw, vh in VIEWPORTS:
            r = run_viewport(browser, vw, vh)
            handled = [e for e in r.console if e['text'].startswith(HANDLED)]
            real = [e for e in r.console if e not in handled]
            print(f'{r.tag}: {len(r.shots)} shots, {len(r.failures)} step failures, console errors {len(real)}, page errors {len(r.pageerrors)}, handled HTTP errors {len(handled)}, layout flags on {len(r.layout)} shots', flush=True)
            for e in real:
                print('  console error:', e['text'][:300], flush=True)
            for e in r.pageerrors:
                print('  page error:', e[:300], flush=True)
            for e in handled:
                print('  handled:', e['text'][:200], flush=True)
            for name, probe in r.layout.items():
                print(f'  layout {name}: {json.dumps(probe)[:900]}', flush=True)
            report.append({'viewport': r.tag, 'failures': r.failures, 'console': real, 'handled_http': handled, 'pageerrors': r.pageerrors, 'layout': r.layout, 'shots': r.shots})
        browser.close()
    with open(os.path.join(OUT, 'report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=1)
    print('report:', os.path.join(OUT, 'report.json'))


if __name__ == '__main__':
    main()
