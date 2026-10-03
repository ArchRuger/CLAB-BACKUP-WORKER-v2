#!/usr/bin/env python3
"""Browser checks for the 2026-10-03 UI/UX email item T5 (the lab builder's post-save hand-off and closing it), against
the fixture manager (fresh FIXTURE_DATA; no VM). Usage:
    FIXTURE_DATA=<scratch> clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8231
    clab-backup-ui/.venv/bin/python docs/lab-builder/tools/post_save_checks.py --base http://127.0.0.1:8231 --out <dir>
--orphans additionally reproduces the old defect (a closed topology preview kept on screen by .dialog-viewport's
display:flex) by forcing that rule back on, for the "before" screenshot.
"""
import argparse, json, sys, time
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('--base', default='http://127.0.0.1:8231'); ap.add_argument('--out', default='.'); ap.add_argument('--orphans', action='store_true')
args = ap.parse_args(); LAB = 't5' + time.strftime('%H%M%S'); checks = []; noise = []

def check(name, ok, detail=''):
    checks.append((name, bool(ok))); print(('PASS  ' if ok else 'FAIL  ') + name + (('  · ' + str(detail)) if detail and not ok else ''), flush=True)

PROBE = """() => { const c = document.querySelector('.react-flow'); const b = c.getBoundingClientRect(); const el = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
  const a = document.activeElement; const ab = a && a.getBoundingClientRect();
  const vp = document.querySelector('.react-flow__viewport'); const pal = [...document.querySelectorAll('*')].find(e => e.children.length === 0 && e.textContent === 'Palette');
  return {open: [...document.querySelectorAll('dialog[open]')].map(d => d.id), center: !!(el && el.closest('.react-flow')), roots: document.querySelectorAll('#root').length,
   overflow: getComputedStyle(document.body).overflow, focusVisible: !!(a && a !== document.body && ab.width > 0 && ab.height > 0), focus: a && (a.id || a.tagName),
   viewport: vp && vp.style.transform, palette: !!(pal && pal.getBoundingClientRect().width > 0),
   shown: [...document.querySelectorAll('dialog')].filter(d => !d.open && getComputedStyle(d).display !== 'none').map(d => d.id)}; }"""

with sync_playwright() as p:
    browser = p.chromium.launch(); ctx = browser.new_context(viewport={'width': 1440, 'height': 900}); pg = ctx.new_page()
    reqs = []
    pg.on('request', lambda r: reqs.append((r.method, r.url.split('/api')[-1])) if r.method != 'GET' and '/api/' in r.url else None)
    pg.on('console', lambda m: noise.append(m.text[:200]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    pg.on('pageerror', lambda e: noise.append(str(e)[:200]))
    probe = lambda: pg.evaluate(PROBE); shot = lambda n: pg.screenshot(path=f'{args.out}/{n}.png')
    count = lambda m, frag: sum(1 for x in reqs if x[0] == m and frag in x[1])
    pg.goto(args.base + '/'); pg.wait_for_selector('#home-deploy', timeout=15000); pg.click('#home-deploy'); pg.wait_for_selector('#op-build'); pg.click('#op-build')
    pg.wait_for_selector('#builder-new-name'); pg.fill('#builder-new-name', LAB); pg.click('#builder-new-create')
    pg.wait_for_selector('[data-testid="navbar-layout"]', timeout=20000); pg.wait_for_timeout(1000)
    t = pg.get_by_text('Linux host', exact=True).first
    for x, y in ((360, 220), (620, 220)):
        b = t.bounding_box(); pg.mouse.move(b['x'] + 10, b['y'] + 8); pg.mouse.down(); pg.mouse.move(x, y, steps=12); pg.mouse.up(); pg.wait_for_timeout(700)
    base = probe(); check('baseline: no dialog, canvas at centre, one editor root, palette shown', base['open'] == [] and base['center'] and base['roots'] == 1 and base['palette'], base)

    def save_and_reach_result():
        pg.click('#builder-save'); pg.wait_for_selector('#op-confirm'); pg.click('#op-confirm'); pg.wait_for_selector('#op-published-block', timeout=30000)
    save_and_reach_result()
    check('result offers Add / Deploy now, not the generic "Deploy or add this lab…"', pg.locator('#op-published-add').is_visible() and pg.locator('#op-published-deploy').is_visible() and pg.locator('#op-open-published').count() == 0)
    check('the result says it is not running', 'not running yet' in pg.inner_text('#operation-output'))
    shot('t05a-result')
    # Escape and × return to the editor; Save again reopens the same result (View output path is the same dialog)
    pg.keyboard.press('Escape'); pg.wait_for_timeout(300); s = probe()
    check('Escape closes the result: no dialog, canvas at centre, focus on a visible element', s['open'] == [] and s['center'] and s['focusVisible'], s)
    # ---- Add without starting; double click posts once ----------------------------------------------------
    pg.click('#builder-save'); pg.wait_for_selector('#op-confirm', timeout=15000); pg.click('#op-confirm'); pg.wait_for_selector('#op-published-block', timeout=30000)
    posts0 = count('POST', '/lab-definitions'); deploys0 = count('POST', '/operations/preview'); conf1 = count('POST', '/operations/confirm')
    pg.dblclick('#op-published-add'); pg.wait_for_selector('#op-published-go', timeout=15000); pg.wait_for_timeout(800)
    check('double click on Add imports exactly once', count('POST', '/lab-definitions') - posts0 == 1, count('POST', '/lab-definitions') - posts0)
    check('adding never asks for or runs a deploy', count('POST', '/operations/preview') == deploys0 and count('POST', '/operations/confirm') == conf1, reqs[-8:])
    txt = pg.inner_text('#operation-output')
    check('unambiguous result: in My labs, not running, two distinct buttons', 'is in My labs' in txt and 'not running' in txt and pg.locator('#op-published-deploy').is_visible() and pg.locator('#op-published-go').is_visible() and pg.locator('#op-published-add').count() == 0 and pg.locator('#op-open-published').count() == 0, txt)
    shot('t05a-after-buttons')
    # Deploy now opens the reviewed deploy flow; nothing deploys before the confirmation; cancelling returns
    confirm0 = count('POST', '/operations/confirm'); pg.dblclick('#op-published-deploy'); pg.wait_for_selector('#op-confirm', timeout=15000); pg.wait_for_timeout(500)
    check('Deploy now opens the deploy review and posts no confirm', 'Start' in pg.inner_text('#operation-review h2') and count('POST', '/operations/confirm') == confirm0, pg.inner_text('#operation-review h2'))
    check('double click on Deploy now did not import again or open two reviews', count('POST', '/lab-definitions') - posts0 == 1 and count('POST', '/operations/preview') - deploys0 == 1, (count('POST', '/lab-definitions') - posts0, count('POST', '/operations/preview') - deploys0))
    shot('t05a-deploy-review')
    pg.keyboard.press('Escape'); pg.wait_for_timeout(400)
    check('cancelling the review leaves the result with both buttons, nothing deployed', pg.locator('#op-published-go').is_visible() and count('POST', '/operations/confirm') == confirm0)
    # reopen from the bar: a second save of unchanged work must not duplicate the lab
    pg.click('#operation-output [data-op-close]'); pg.wait_for_timeout(300); s = probe()
    check('× closes the result: zero dialog[open], canvas at centre, one root, same palette, same viewport, focus visible',
          s['open'] == [] and s['center'] and s['roots'] == 1 and s['palette'] == base['palette'] and s['viewport'] == base['viewport'] and s['focusVisible'] and s['overflow'] == base['overflow'] and s['shown'] == [], (s, base))
    check('focus returned to the Save button', s['focus'] == 'builder-save', s['focus'])
    shot('t05b-after-close')
    # Go to My labs: navigates, the lab is listed; Back does not import again
    pg.click('#builder-save'); pg.wait_for_selector('#op-confirm', timeout=15000); pg.click('#op-confirm'); pg.wait_for_selector('#op-published-block', timeout=30000)
    pg.wait_for_timeout(1500); listed = pg.evaluate("n => fetch('/api/state').then(r => r.json()).then(v => v.labs.filter(l => l.name === n || l.deployment_name === n).length)", LAB)
    check('a second visit finds the lab already in My labs: one lab of that name, Go to My labs offered (a revise refreshes it, never imports a second)', pg.locator('#op-published-go').is_visible() and listed == 1, (listed, pg.inner_text('#operation-output')[:200]))
    pg.click('#op-published-go'); pg.wait_for_url('**/#lab=*', timeout=15000); pg.wait_for_selector('.lab-item', state='attached', timeout=15000); pg.wait_for_timeout(1500)
    check('Go to My labs navigates to the manager with the lab open', '/#lab=' in pg.url or '#lab=' in pg.url, pg.url)
    check('the saved lab is listed', LAB in pg.inner_text('body'), pg.url); shot('t05a-my-labs')
    pg.wait_for_timeout(1000); n = count('POST', '/lab-definitions'); cn = count('POST', '/operations/confirm'); pg.go_back(); pg.wait_for_timeout(2500); pg.go_forward(); pg.wait_for_timeout(2000)
    check('Back / Forward re-import nothing and deploy nothing', count('POST', '/lab-definitions') == n and count('POST', '/operations/confirm') == cn, (n, count('POST', '/lab-definitions')))
    # ---- 5b root cause: the topology preview closed through ×, Escape and Cancel path ----------------------
    pg.goto(args.base + '/static/lab-builder.html'); pg.wait_for_selector('#builder-welcome-new'); pg.click('#builder-welcome-new'); pg.wait_for_selector('#builder-new-name')
    L2 = LAB + 'b'; pg.fill('#builder-new-name', L2); pg.click('#builder-new-create'); pg.wait_for_selector('[data-testid="navbar-layout"]', timeout=20000); pg.wait_for_timeout(1000)
    for x, y in ((360, 220), (620, 220)):
        b = pg.get_by_text('Linux host', exact=True).first.bounding_box(); pg.mouse.move(b['x'] + 10, b['y'] + 8); pg.mouse.down(); pg.mouse.move(x, y, steps=12); pg.mouse.up(); pg.wait_for_timeout(600)
    base2 = probe()
    yaml = 'name: probe\ntopology:\n  nodes:\n    a: {kind: linux, image: alpine:latest}\n    b: {kind: linux, image: alpine:latest}\n  links:\n    - endpoints: ["a:eth1", "b:eth1"]\n'
    draw = pg.evaluate("t => json('/operations/parse-yaml', 'POST', {options: {text: t}}).then(v => v.drawing)", yaml)
    for how in ('x', 'escape', 'x', 'escape'):
        pg.evaluate("d => { document.getElementById('builder-save').focus(); opMapPreview(d, 'probe'); }", draw); pg.wait_for_selector('#op-map-preview[open]'); pg.wait_for_timeout(400)
        if args.orphans and how == 'x': shot('t05b-preview-open')
        if how == 'x': pg.click('#op-map-preview [data-op-close]')
        else: pg.keyboard.press('Escape')
        pg.wait_for_timeout(300)
        if args.orphans: pg.add_style_tag(content='dialog.dialog-viewport:not([open]){display:flex!important}'); pg.evaluate("document.getElementById('op-map-preview').style.display=''"); pg.wait_for_timeout(200)
        s = probe()
        if args.orphans: shot('t05b-before-orphans'); print('orphan probe', s); break
        check(f'closed topology preview ({how}) leaves nothing on screen: zero open, none displayed, canvas at centre, viewport and palette unchanged, focus on Save',
              s['open'] == [] and s['shown'] == [] and s['center'] and s['roots'] == 1 and s['viewport'] == base2['viewport'] and s['palette'] == base2['palette'] and s['focus'] == 'builder-save' and s['overflow'] == base2['overflow'], (s, base2))
    check('no console or page errors', not noise, noise[:3])
    browser.close()
bad = [n for n, ok in checks if not ok]; print(f'\n{len(checks) - len(bad)}/{len(checks)} checks passed'); sys.exit(1 if bad else 0)
