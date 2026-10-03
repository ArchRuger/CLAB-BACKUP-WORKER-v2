#!/usr/bin/env python3
"""Browser checks for the 2026-10-03 UI/UX email items T1-T3 (templates, image notice, centred label), against the
fixture manager (fresh FIXTURE_DATA; no VM). Usage:
    FIXTURE_DATA=<scratch> clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8147
    clab-backup-ui/.venv/bin/python docs/lab-builder/tools/uiux_email_checks.py --base http://127.0.0.1:8147 --out <dir>
"""
import argparse, json, sys, time
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('--base', default='http://127.0.0.1:8147'); ap.add_argument('--out', default='.')
args = ap.parse_args(); LAB = 'uiux' + time.strftime('%H%M%S'); checks = []; noise = []
TEMPLATES = [('Arista cEOS', 'ceos', 'n24l/ceos', '4.35.0F'), ('Juniper cJunosEvolved', 'ptx', 'n24l/cjunosevolved', '26.2R1.7-EVO'),
             ('Juniper vJunos-switch', 'sw', 'n24l/vjunos-switch', '23.2R1.14'), ('Cisco XRv9k', 'xr', 'n24l/cisco_xrv9k', '24.3.1')]

def check(name, ok, detail=''):
    checks.append((name, bool(ok))); print(('PASS  ' if ok else 'FAIL  ') + name + (('  · ' + str(detail)) if detail and not ok else ''), flush=True)

def center(loc): b = loc.bounding_box(); return b['x'] + b['width'] / 2, b['y'] + b['height'] / 2

with sync_playwright() as p:
    browser = p.chromium.launch(); ctx = browser.new_context(viewport={'width': 1440, 'height': 900})
    pg = ctx.new_page()
    pg.on('console', lambda m: noise.append(m.text[:200]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    pg.on('pageerror', lambda e: noise.append(str(e)[:200]))
    shot = lambda n: pg.screenshot(path=f'{args.out}/{n}.png')
    draft = lambda: json.loads(pg.evaluate(f"localStorage.getItem('clab-builder:draft:new:{LAB}')") or 'null')
    nodes = lambda: pg.locator('.react-flow__node').count()
    pg.goto(args.base + '/'); pg.wait_for_selector('#home-deploy', timeout=15000); pg.click('#home-deploy'); pg.wait_for_selector('#op-build'); pg.click('#op-build')
    pg.wait_for_selector('#builder-new-name'); pg.fill('#builder-new-name', LAB); pg.click('#builder-new-create')
    pg.wait_for_selector('[data-testid="navbar-layout"]', timeout=20000); pg.wait_for_timeout(1000)
    def drag(text, x, y):
        t = pg.get_by_text(text, exact=True).first; b = t.bounding_box(); pg.mouse.move(b['x'] + 10, b['y'] + 8); pg.mouse.down(); pg.mouse.move(x, y, steps=12); pg.mouse.up(); pg.wait_for_timeout(700)
    pos = [(330, 200), (560, 200), (330, 420), (560, 420)]
    for (name, base, repo, tag), (x, y) in zip(TEMPLATES, pos): drag(name, x, y)
    check('four built-in templates add four nodes', nodes() == 4, nodes())
    y = draft()['yaml']
    for name, base, repo, tag in TEMPLATES: check(f'YAML has {repo}:{tag} exactly once', y.count(f'image: {repo}:{tag}') == 1, y)
    check('cJunosEvolved env block exactly once', y.count('CPTX_AUTO_CONFIG: "1"') == 1 and y.count('env:') == 1, y)
    check('no :latest invented', ':latest' not in y)
    shot('t01-four-templates-canvas')
    # the template dialog: Image and Version fields
    if not pg.get_by_text('Cisco XRv9k', exact=True).first.is_visible(): pg.click('[data-testid="panel-tab-nodes"]'); pg.wait_for_timeout(400)
    for name, base, repo, tag in TEMPLATES:
        pg.evaluate("n => { const t = [...document.querySelectorAll('*')].find(e => e.children.length === 0 && e.textContent === n); let r = t; while (r && r.querySelectorAll('button').length < 3) r = r.parentElement; r.querySelectorAll('button')[1].click(); }", name); pg.wait_for_timeout(600)
        img = pg.get_by_label('Image', exact=True).first.input_value(); ver = pg.get_by_label('Version', exact=True).first.input_value()
        check(f'{name} dialog: Image={repo}, Version={tag}', img == repo and ver == tag, (img, ver))
        if name == 'Juniper cJunosEvolved': shot('t01-template-dialog-cjunos')
        pg.get_by_role('dialog').get_by_text('Cancel', exact=True).click(); pg.wait_for_timeout(400)
    # ---- T2: the image notice -------------------------------------------------------------------------------
    notice = pg.locator('#builder-images')
    pg.wait_for_timeout(1800)
    check('notice shows an error (fixture knows only n24l/cisco_xrv9k)', notice.is_visible() and notice.get_attribute('role') == 'alert' and pg.inner_text('#builder-images-text').startswith('Error: '), pg.inner_text('#builder-images-text'))
    check('error text names problems only, not the good image', 'cisco_xrv9k' not in pg.inner_text('#builder-images-text'))
    check('error is red and not by colour alone', 'error' in notice.get_attribute('class') and pg.evaluate("getComputedStyle(document.getElementById('builder-images')).color") != pg.evaluate("getComputedStyle(document.body).color"))
    shot('t02-error-notice')
    pg.keyboard.press('Escape')
    pg.focus('#builder-images-dismiss'); pg.keyboard.press('Enter'); pg.wait_for_timeout(300)
    check('keyboard dismiss hides it and focus moves to a real control', not notice.is_visible() and pg.evaluate("document.activeElement && document.activeElement.id") in ('builder-save', 'builder-yaml'), pg.evaluate("document.activeElement && document.activeElement.id"))
    # a change that does not change the images (move a node) must not bring the same result back
    n = pg.locator('.react-flow__node').first; bx = n.bounding_box(); pg.mouse.move(bx['x'] + 30, bx['y'] + 30); pg.mouse.down(); pg.mouse.move(bx['x'] + 80, bx['y'] + 90, steps=6); pg.mouse.up(); pg.wait_for_timeout(2500)
    check('the same result does not come back after a routine change', not notice.is_visible())
    # a different result shows (a new image the registry gives: Linux host from the palette)
    drag('Linux host', 760, 300); pg.wait_for_timeout(2500)
    check('a different result is shown after a dismissed one', notice.is_visible() and pg.inner_text('#builder-images-text').startswith('Error: '))
    check('the notice is a single slot (one text, not stacked)', pg.locator('#builder-images').count() == 1 and pg.inner_text('#builder-images-text').count('Error:') == 1)
    # request failure is shown
    pg.route('**/api/operations/image-check', lambda r: r.abort())
    drag('Linux host', 860, 420); pg.wait_for_timeout(2500)
    check('a failed request is shown, not hidden', notice.is_visible() and 'could not be checked' in pg.inner_text('#builder-images-text') and notice.get_attribute('role') == 'status', pg.inner_text('#builder-images-text'))
    shot('t02-request-failed-notice'); pg.unroute('**/api/operations/image-check')
    # all fine: delete the unavailable devices
    def menu(target, item):
        x, y = center(target); pg.mouse.click(x, y, button='right'); pg.wait_for_timeout(350); pg.get_by_role('menuitem', name=item).click(); pg.wait_for_timeout(500)
    node = lambda text: pg.locator('.react-flow__node').filter(has_text=text).first
    for t in ('ceos1', 'ptx1', 'sw1'): menu(node(t), 'Delete Node')
    pg.wait_for_timeout(2500)
    check('all-available result is a short info line', notice.is_visible() and notice.get_attribute('role') == 'status' and pg.inner_text('#builder-images-text').startswith('Images checked: all '), pg.inner_text('#builder-images-text'))
    shot('t02-all-available-notice')
    # ---- T3: Center label -----------------------------------------------------------------------------------
    drag('Cisco XRv9k', 400, 300); drag('Cisco XRv9k', 600, 300); drag('Cisco XRv9k', 500, 480)
    names = [x.inner_text().strip() for x in pg.locator('.react-flow__node').all()]
    print('nodes', names)
    ns = pg.locator('.react-flow__node')
    def link(a, b):
        menu(ns.filter(has_text=a).first, 'Create Link'); x, y = center(ns.filter(has_text=b).first); pg.mouse.click(x, y); pg.wait_for_timeout(700)
    link('xr1', 'xr2'); link('xr2', 'xr3'); link('xr3', 'xr1'); link('xr1', 'xr2'); link('xr2', 'xr3')
    shot('t03-before-center')
    menu(ns.filter(has_text='xr2').first, 'Edit Node')
    if not pg.get_by_label('Node Name').is_visible(): pg.click('[data-testid="panel-tab-edit"]'); pg.wait_for_timeout(400)
    pg.get_by_label('Label Position').click(); pg.wait_for_timeout(300)
    opts = [o.inner_text() for o in pg.get_by_role('option').all()]; print('label options', opts)
    check('Label Position offers Center', 'Center' in opts, opts)
    pg.get_by_role('option', name='Center', exact=True).click(); pg.wait_for_timeout(900)
    a = json.loads(draft()['annotations']); lp = [x.get('labelPosition') for x in a['nodeAnnotations'] if x['id'] == 'xr2']
    check('Center applies at once and is stored as labelPosition center in the draft annotations', lp == ['center'], lp)
    lab = pg.locator('.topology-node-label').filter(has_text='xr2').first
    st = lab.evaluate("e => { const s = getComputedStyle(e); const r = e.getBoundingClientRect(); const n = e.parentElement.getBoundingClientRect(); return {bg: s.backgroundColor, pe: s.pointerEvents, dx: (r.x + r.width / 2) - (n.x + n.width / 2), dy: (r.y + r.height / 2) - (n.y + n.height / 2)}; }")
    check('centred over the icon with near-opaque dark background and no pointer events', abs(st['dx']) < 2 and abs(st['dy']) < 2 and st['pe'] == 'none' and st['bg'].startswith('rgba(0, 0, 0, 0.94'), st)
    shot('t03-center-default-zoom')
    pg.keyboard.press('Escape')
    pg.mouse.move(440, 360)
    for _ in range(4): pg.mouse.wheel(0, -300); pg.wait_for_timeout(150)
    pg.wait_for_timeout(500); shot('t03-center-zoomed-in')
    for _ in range(4): pg.mouse.wheel(0, 300); pg.wait_for_timeout(150)
    pg.wait_for_timeout(300)
    # selection / drag / context menu still work through the label
    x, y = center(ns.filter(has_text='xr2').first); pg.mouse.click(x, y); pg.wait_for_timeout(300)
    check('the node is still selectable by clicking its centred label', 'selected' in (ns.filter(has_text='xr2').first.get_attribute('class') or ''))
    pg.mouse.click(x, y, button='right'); pg.wait_for_timeout(350); check('context menu still opens on the centred label', pg.get_by_role('menuitem', name='Edit Node').count() > 0); pg.keyboard.press('Escape')
    # long name: rename xr2 to a long name and zoom out
    menu(ns.filter(has_text='xr2').first, 'Edit Node')
    pg.get_by_label('Node Name').fill('edge-router-with-a-long-name-01'); pg.get_by_role('button', name='Apply', exact=True).first.click(); pg.wait_for_timeout(900)
    pg.mouse.move(500, 380)
    for _ in range(2): pg.mouse.wheel(0, 300); pg.wait_for_timeout(150)
    pg.wait_for_timeout(500); shot('t03-center-zoomed-out-long-name')
    ll = pg.locator('.topology-node-label').filter(has_text='edge-router').first.evaluate("e => ({w: e.scrollWidth, c: e.clientWidth, o: getComputedStyle(e).overflow})")
    check('a long centred name is not clipped', ll['w'] <= ll['c'] + 1 or ll['o'] == 'visible', ll)
    saved = pg.evaluate("1")
    print('console/page errors:', noise)
    check('no console or page errors', not noise, noise)
    browser.close()
    sys.exit(0 if all(ok for _, ok in checks) else 1)
