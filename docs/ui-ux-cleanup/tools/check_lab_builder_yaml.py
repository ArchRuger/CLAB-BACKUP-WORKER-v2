#!/usr/bin/env python3
"""C4: the lab builder's editable YAML panel, in a real browser, against the fixture manager.

    FIXTURE_DATA=<scratch> clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8093
    LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps clab-backup-ui/.venv/bin/python \
        docs/ui-ux-cleanup/tools/check_lab_builder_yaml.py --base http://127.0.0.1:8093 --out docs/ui-ux-cleanup/evidence

The fixture serves the working tree's page and the committed editor bundle, so this proves the panel, the
adapter's YAML handle and the real editing engine together; it proves nothing about a VM. Each viewport gets
a fresh browser context and its own draft. Console errors, page errors and CSP violations fail the run.
Writes lab-builder-yaml-<viewport>-<step>.png and lab-builder-yaml-report.json into --out.
"""
import argparse, json, re, sys, time
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('--base', default='http://127.0.0.1:8093'); ap.add_argument('--out', default='.')
ap.add_argument('--viewports', default='1366x768,390x844')
args = ap.parse_args()
results = []

START = '''name: {lab}
topology:
  nodes:
    r1:
      kind: linux
      image: alpine:3
    r2:
      kind: linux
      image: alpine:3
  links:
    - endpoints: ["r1:eth1", "r2:eth1"]
'''
LAYOUT = json.dumps({'nodeAnnotations': [{'id': 'r1', 'position': {'x': 120, 'y': 140}}, {'id': 'r2', 'position': {'x': 380, 'y': 140}}]})


def run_viewport(p, width, height):
    tag = f'{width}x{height}'; lab = 'yaml' + time.strftime('%H%M%S') + ('w' if width > 900 else 'n'); noise = []
    def check(name, ok, observed=''):
        results.append({'viewport': tag, 'check': name, 'pass': None if ok is None else bool(ok), 'observed': observed})
        print(('SKIP  ' if ok is None else 'PASS  ' if ok else 'FAIL  ') + f'[{tag}] {name}' + (f'  · {observed}' if observed else ''), flush=True)
    browser = p.chromium.launch(); ctx = browser.new_context(viewport={'width': width, 'height': height})
    ctx.add_init_script("window.__csp=[];document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective+' | '+(e.blockedURI||'inline')))")
    pg = ctx.new_page()
    pg.on('console', lambda m: noise.append('console: ' + m.text[:200]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
    pg.on('pageerror', lambda e: noise.append('pageerror: ' + str(e)[:200]))
    shot = lambda n: pg.screenshot(path=f'{args.out}/lab-builder-yaml-{tag}-{n}.png')
    draft = lambda: json.loads(pg.evaluate(f"localStorage.getItem('clab-builder:draft:new:{lab}')") or 'null')
    text = lambda: pg.input_value('#builder-yaml-editor')
    status = lambda: pg.inner_text('#builder-yaml-status').strip()
    def labels(): return sorted(t.strip() for t in pg.locator('.react-flow__node').all_inner_texts())
    edges = lambda: pg.locator('.react-flow__edge').count()
    def fill(value): pg.fill('#builder-yaml-editor', value); pg.wait_for_timeout(600)  # past the 400 ms live check
    def apply(): pg.click('#builder-yaml-apply'); pg.wait_for_timeout(1200)
    def center(loc): b = loc.bounding_box(); return b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
    def node(name): return pg.locator('.react-flow__node').filter(has_text=re.compile('^' + re.escape(name) + '$')).first
    def clear_canvas():
        # With the YAML panel open the canvas is narrower and the editor's own side panel (the palette) can
        # cover the devices: fold it and fit the view, as a student would.
        toggle = pg.locator('[data-testid="panel-toggle-btn"]')
        if pg.locator('[data-testid="context-panel"]').is_visible() and toggle.count(): toggle.first.click(); pg.wait_for_timeout(500)
        pg.click('[data-testid="navbar-fit-viewport"]'); pg.wait_for_timeout(700)
    def link(a, b):
        clear_canvas(); count = edges()
        x, y = center(node(a)); pg.mouse.click(x, y, button='right'); pg.wait_for_timeout(350)
        pg.get_by_role('menuitem', name='Create Link').click(timeout=5000); pg.wait_for_timeout(400)
        x, y = center(node(b)); pg.mouse.click(x, y); pg.wait_for_timeout(1000)
        if edges() != count + 1: raise RuntimeError(f'no link drawn ({edges()} links)')

    # Seed the draft through the page's own storage function, then open it.
    pg.goto(args.base + '/static/lab-builder.html'); pg.wait_for_selector('#builder-welcome', timeout=15000); pg.wait_for_timeout(800)
    pg.evaluate("([id,name,yaml,annotations])=>draftWrite(builderStore,{id,name,yaml,annotations},undefined)", ['new:' + lab, lab, START.format(lab=lab), LAYOUT])
    pg.goto(args.base + f'/static/lab-builder.html#draft=new:{lab}'); pg.reload()
    pg.wait_for_selector('.react-flow__node', timeout=20000); pg.wait_for_timeout(1500)
    vw = pg.evaluate('innerWidth'); off = [b for b in ('builder-drafts', 'builder-download', 'builder-yaml', 'builder-save') if (lambda r: r['x'] < 0 or r['x'] + r['width'] > vw + 1)(pg.locator('#' + b).bounding_box())]
    check('every bar action is inside the window', not off, ', '.join(off))
    check('the bar button is labelled YAML and starts collapsed', pg.inner_text('#builder-yaml').strip() == 'YAML' and pg.get_attribute('#builder-yaml', 'aria-expanded') == 'false', pg.inner_text('#builder-yaml'))

    # 1. Open: the panel shows the draft's text; the canvas makes room.
    root_before = pg.locator('#root').bounding_box()
    pg.click('#builder-yaml'); pg.wait_for_selector('#builder-yaml-editor', state='visible'); pg.wait_for_timeout(500)
    root_after, panel = pg.locator('#root').bounding_box(), pg.locator('#builder-yaml-panel').bounding_box()
    side = root_after['x'] + root_after['width'] <= panel['x'] + 1 if width > 900 else root_after['y'] + root_after['height'] <= panel['y'] + 1
    check('the panel opens with the draft\'s topology text', text() == draft()['yaml'] and pg.get_attribute('#builder-yaml', 'aria-expanded') == 'true', f'{len(text())} chars')
    check('the canvas and the panel do not overlap (' + ('side by side' if width > 900 else 'stacked') + ')', side, f"root {root_before['width']:.0f}x{root_before['height']:.0f} -> {root_after['width']:.0f}x{root_after['height']:.0f}, panel at x={panel['x']:.0f} y={panel['y']:.0f}")
    check('the line gutter numbers every line', pg.inner_text('#builder-yaml-gutter').split('\n')[-1].strip() == str(len(text().split('\n'))), pg.inner_text('#builder-yaml-gutter').split('\n')[-1])
    shot('01-open')

    # 2. Add a device in the text, Apply: it appears on the canvas.
    added = text().replace('  links:\n', '    r3:\n      kind: linux\n      image: alpine:3\n  links:\n')
    fill(added); edited = status()
    apply()
    check('typing marks the panel edited, Apply adds the device to the canvas', edited == 'Edited · not applied' and 'r3' in labels() and status() == 'Applied' and 'r3:' in draft()['yaml'], f'before apply "{edited}", after "{status()}", nodes {labels()}')
    shot('02-applied-device')

    # 3. The toolbar's Undo takes the apply back in one step, and a clean panel follows.
    undo = pg.locator('[data-testid="navbar-undo"]')
    check('Undo is enabled after an apply', undo.is_enabled())
    undo.click(); pg.wait_for_timeout(1200)
    check('Undo removes the applied device and the panel shows the text before the apply', 'r3' not in labels() and 'r3:' not in text() and text() == draft()['yaml'], f'nodes {labels()}')
    shot('03-undo')

    # 4. Invalid YAML: diagnostics while typing, refusal on Apply, graph and draft untouched.
    before, nodes_before = draft()['yaml'], labels()
    fill(before.replace('  nodes:\n', '  nodes: [\n', 1)); live = status(); apply(); refused = status()
    check('a syntax error is shown while typing and refused on Apply, graph untouched', live.startswith('Line ') and refused.startswith('Line ') and labels() == nodes_before and draft()['yaml'] == before, f'live "{live}" · apply "{refused}"')
    check('the refused text stays in the panel, marked invalid', 'nodes: [' in text() and pg.get_attribute('#builder-yaml-editor', 'aria-invalid') == 'true')
    shot('04-invalid')
    fill('name: ' + lab + '\ntopology:\n  nodes: [r1, r2]\n'); apply(); shape = status()
    check('a readable text of the wrong shape is refused before the engine, graph untouched', 'topology.nodes must be a mapping' in shape and labels() == nodes_before and draft()['yaml'] == before, shape)
    pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
    check('Escape does not close the panel while it holds edits', pg.locator('#builder-yaml-panel').is_visible(), status())
    pg.click('#builder-yaml-revert'); pg.wait_for_timeout(300)
    check('Revert loads the editor\'s text again', text() == draft()['yaml'] and pg.get_attribute('#builder-yaml-editor', 'aria-invalid') == 'false', status())

    # 5. Rename a device in the text: the canvas renames it (the link follows).
    renamed = text().replace('    r2:\n', '    core2:\n').replace('"r2:eth1"', '"core2:eth1"')
    fill(renamed); pg.keyboard.press('Control+Enter'); pg.wait_for_timeout(1200)
    check('renaming a device in the text (Ctrl+Enter) renames it on the canvas', 'core2' in labels() and 'r2' not in labels() and edges() == 1, f'nodes {labels()}, {edges()} links, status "{status()}"')
    shot('05-renamed')

    # 6. Keys the editor does not know survive a visual edit; a clean panel follows the canvas.
    custom = text().replace('name: ' + lab + '\n', 'name: ' + lab + '\nx-course: {lesson: 3}\n').replace('    r1:\n      kind: linux\n', '    r1:\n      kind: linux\n      x-note: keep me   # a comment\n')
    fill(custom); apply()
    check('unknown keys and comments are applied verbatim', draft()['yaml'] == custom, status())
    toggle = pg.locator('[data-testid="panel-toggle-btn"]').first.bounding_box()
    if toggle and toggle['x'] < 0:
        # The editor's own side panel (the palette) is wider than a phone's canvas and its fold button lies off
        # screen: drawing on the canvas is not possible at this width, with or without the YAML panel.
        linked = False; check('canvas edits at this width', None, f"the editor's palette covers the canvas; its fold button is at x={toggle['x']:.0f}")
    else:
      try:
        link('r1', 'core2'); linked = True
      except Exception as e:  # noqa: BLE001 - reported as the observation
        linked = False; shot('06-link-failed'); check('a link can be drawn on the canvas', False, str(e)[:160])
    if linked:
        y = draft()['yaml']
        check('a link drawn on the canvas reaches a clean panel', edges() == 2 and y != custom and text() == y and 'r1:eth2' in y, f'{edges()} links, panel==draft {text() == y}')
        check('unknown keys and comments survive the canvas edit (reformatted by the engine)', 'x-course:' in y and 'lesson: 3' in y and 'x-note: keep me' in y and '# a comment' in y,
              next((l for l in y.split('\n') if 'x-course' in l), '') + ' | ' + next((l for l in y.split('\n') if 'x-note' in l), ''))
        shot('06-canvas-link')
        # 7. A canvas edit while the student types: the text stays, the panel says so; Revert loads the canvas.
        fill(text() + '# my note\n')
        link('core2', 'r1'); after = status()
        check('a canvas edit never overwrites unapplied text', '# my note' in text() and after == 'Canvas changed · Revert to load it', after)
        shot('07-canvas-changed')
        pg.click('#builder-yaml-revert'); pg.wait_for_timeout(300)
        check('Revert then shows the canvas\'s text', text() == draft()['yaml'] and '# my note' not in text())
    pg.click('#builder-yaml-close'); pg.wait_for_timeout(400)
    check('the panel closes, the bar button and the layout follow', not pg.locator('#builder-yaml-panel').is_visible() and pg.get_attribute('#builder-yaml', 'aria-expanded') == 'false' and pg.locator('#root').bounding_box()['width'] >= root_before['width'] - 1)
    csp = pg.evaluate('window.__csp')
    check('no console errors, page errors or CSP violations', not noise and not csp, '; '.join(noise + csp)[:300])
    browser.close()


with sync_playwright() as p:
    for vp in args.viewports.split(','):
        w, h = (int(v) for v in vp.split('x')); run_viewport(p, w, h)
json.dump(results, open(f'{args.out}/lab-builder-yaml-report.json', 'w'), indent=1)
failed = [r for r in results if r['pass'] is False]; skipped = [r for r in results if r['pass'] is None]
print(f"\n{len(results) - len(failed) - len(skipped)}/{len(results)} checks passed, {len(skipped)} skipped")
sys.exit(1 if failed else 0)
