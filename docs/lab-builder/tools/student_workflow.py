#!/usr/bin/env python3
"""A student's whole path through the lab builder, in a real browser, against the fixture manager.

    FIXTURE_DATA=<scratch> clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8090
    clab-backup-ui/.venv/bin/python docs/lab-builder/tools/student_workflow.py --base http://127.0.0.1:8090 --out <dir>

The fixture manager is the real application with the VM answered in-process, so this proves the page, the
drafts, the reviewed save and the hand-over to the normal deploy flow; it proves nothing about a VM. Every
step is a check; console errors, page errors and Content-Security-Policy violations fail the run.
"""
import argparse, json, sys, time
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser(); ap.add_argument('--base', default='http://127.0.0.1:8090'); ap.add_argument('--out', default='.'); ap.add_argument('--name', default='')
args = ap.parse_args(); LAB = args.name or 'student-' + time.strftime('%H%M%S'); checks = []; noise = []; state = {}

def check(name, ok, detail=''):
    checks.append((name, bool(ok), detail)); print(('PASS  ' if ok else 'FAIL  ') + name + (('  · ' + str(detail)) if detail and not ok else ''), flush=True)

def center(loc): b = loc.bounding_box(); return b['x'] + b['width'] / 2, b['y'] + b['height'] / 2

def run(p):
    browser = p.chromium.launch(); ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
    ctx.add_init_script("window.__csp=[];document.addEventListener('securitypolicyviolation',e=>window.__csp.push(e.violatedDirective+' | '+(e.blockedURI||'inline')))")
    def watch(page):
        page.on('console', lambda m: noise.append('console: ' + m.text[:200]) if m.type == 'error' and 'Failed to load resource' not in m.text and 'changed in another tab' not in m.text else None)  # the editor logs the edit the second-tab check refused
        page.on('pageerror', lambda e: noise.append('pageerror: ' + str(e)[:200])); return page
    pg = watch(ctx.new_page()); shot = lambda n: pg.screenshot(path=f'{args.out}/{n}.png'); state['page'] = pg
    node = lambda text: pg.locator('.react-flow__node').filter(has_text=text).first
    nodes = lambda: pg.locator('.react-flow__node').count(); edges = lambda: pg.locator('.react-flow__edge').count()
    draft = lambda: json.loads(pg.evaluate(f"localStorage.getItem('clab-builder:draft:new:{LAB}')") or 'null')
    def menu(target, item):
        x, y = center(target); pg.mouse.click(x, y, button='right'); pg.wait_for_timeout(350); pg.get_by_role('menuitem', name=item).click(); pg.wait_for_timeout(500)
    def wait_job(word='succeeded', timeout=40000): pg.wait_for_function(f"document.querySelector('#op-job-banner')?.textContent.includes('{word}')", timeout=timeout)

    # 1. From the manager's Home page into the builder
    pg.goto(args.base + '/'); pg.wait_for_selector('#home-deploy', timeout=15000); pg.click('#home-deploy'); pg.wait_for_selector('#op-build', timeout=15000)
    check('Deploy dialog offers "Build a lab visually" beside "Write a new topology"', pg.locator('#op-build').is_visible() and pg.locator('#op-create').is_visible()); shot('01-deploy-dialog')
    pg.click('#op-build'); pg.wait_for_selector('#builder-new-name', timeout=15000)
    check('builder opens on its own page with the new-lab dialog', '/static/lab-builder.html' in pg.url); shot('02-new-lab')
    pg.fill('#builder-new-name', 'bad name!'); pg.click('#builder-new-create'); pg.wait_for_timeout(400)
    check('an unusable lab name is refused with an explanation', 'letters, digits' in pg.inner_text('#builder-new .form-error'))
    taken = pg.evaluate("state.labs[0] ? (state.labs[0].deployment_name || state.labs[0].name) : ''")
    if taken:
        pg.fill('#builder-new-name', taken); pg.click('#builder-new-create'); pg.wait_for_timeout(400)
        check('the name of a lab already in My labs is refused', 'already in My labs' in pg.inner_text('#builder-new .form-error'))
    pg.fill('#builder-new-name', LAB); pg.select_option('#builder-new-starter', 'triangle'); pg.click('#builder-new-create')
    pg.wait_for_selector('.react-flow__node', timeout=20000); pg.wait_for_timeout(1500)
    check('triangle starter: three devices, three links', nodes() == 3 and edges() == 3, f'{nodes()} nodes, {edges()} edges')
    check('links are visible (not collapsed by the manager stylesheet)', pg.evaluate("getComputedStyle(document.querySelector('.react-flow__edge').closest('svg')).width") != '0px')
    check('status says the draft is only in this browser', 'not on the VM yet' in pg.inner_text('#builder-status'))
    for tid in ('navbar-deploy', 'navbar-deploy-menu', 'navbar-split-view'):
        check(f'editor control {tid} is hidden', not pg.locator(f'[data-testid="{tid}"]').is_visible())
    pg.click('[data-testid="navbar-layout"]'); pg.wait_for_timeout(300)
    check('Geo layout is hidden, the other layouts remain', not pg.locator('[data-testid="navbar-layout-geo"]').is_visible() and pg.locator('[data-testid="navbar-layout-force"]').is_visible()); pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
    check('YAML and JSON editor tabs are absent', pg.get_by_role('tab', name='YAML').count() == 0 and pg.get_by_role('tab', name='JSON').count() == 0); shot('03-editor')

    # 2. Build: add a device, link it, edit it, delete and undo
    bx = pg.get_by_text('Linux host', exact=True).bounding_box(); pg.mouse.move(bx['x'] + 10, bx['y'] + 8); pg.mouse.down(); pg.mouse.move(640, 520, steps=12); pg.mouse.up(); pg.wait_for_timeout(900)
    check('a device dragged from the palette is added', nodes() == 4 and 'host1' in draft()['yaml'])
    menu(node('host1'), 'Create Link'); x, y = center(node('ceos1')); pg.mouse.click(x, y); pg.wait_for_timeout(900)
    check('a link is drawn with allocated interfaces', edges() == 4 and '"host1:eth1", "ceos1:eth3"' in draft()['yaml'], draft()['yaml'][-200:])
    menu(node('host1'), 'Edit Node'); pg.get_by_label('Node Name').fill('pc1'); pg.get_by_role('button', name='Apply', exact=True).first.click(); pg.wait_for_timeout(900)
    check('renaming a device updates its links', 'pc1:eth1' in draft()['yaml'] and 'host1' not in draft()['yaml'])
    before = draft()['yaml']; menu(node('ceos3'), 'Delete Node'); pg.wait_for_timeout(700)
    check('deleting a device removes it and its links', nodes() == 3 and 'ceos3' not in draft()['yaml'])
    pg.click('[data-testid="navbar-undo"]'); pg.wait_for_timeout(900)
    check('undo restores the device and its links', nodes() == 4 and draft()['yaml'].count('ceos3') == before.count('ceos3'))
    pg.click('#builder-yaml'); pg.wait_for_selector('#builder-yaml-text'); check('View YAML shows the topology read-only', f'name: {LAB}' in pg.inner_text('#builder-yaml-text')); shot('04-view-yaml'); pg.click('#builder-yaml-dialog [data-op-close]')
    with pg.expect_download() as dl: pg.click('#builder-download')
    exported = json.load(open(dl.value.path())); check('Download draft gives a portable draft file', exported['format'] == 'clab-manager-lab-draft' and exported['name'] == LAB)

    # 3. A second tab editing the same draft is detected instead of silently overwriting
    other = watch(ctx.new_page()); other.goto(pg.url); other.wait_for_selector('.react-flow__node', timeout=20000); other.wait_for_timeout(1000)
    ox, oy = center(other.locator('.react-flow__node').filter(has_text='pc1').first); other.mouse.click(ox, oy, button='right'); other.wait_for_timeout(350); other.get_by_role('menuitem', name='Delete Node').click(); other.wait_for_timeout(900); other.close()
    menu(node('ceos2'), 'Delete Node'); pg.wait_for_timeout(900)
    check('an edit over a newer version from another tab is stopped', pg.locator('#builder-problem').is_visible() and 'another tab' in pg.inner_text('#builder-problem-text')); shot('05-other-tab')
    pg.click('#builder-problem-reload'); pg.wait_for_selector('.react-flow__node', timeout=20000); pg.wait_for_timeout(1000)
    check('after reloading the newer version is shown', nodes() == 3 and 'pc1' not in draft()['yaml'])

    # 4. Save to the VM through the reviewed operation, then deploy through the normal flow
    pg.click('#builder-save'); pg.wait_for_selector('#op-confirm', timeout=15000)
    review = pg.inner_text('#operation-review')
    check('the save review names the lab folder and shows the YAML', f'/srv/containerlab-node-manager/projects/{LAB}' in review and f'name: {LAB}' in pg.inner_text('#op-review-yaml')); shot('06-save-review')
    pg.click('#op-confirm'); pg.wait_for_selector('#op-open-published', timeout=40000)
    check('the save succeeds and offers to deploy or add the lab', 'succeeded' in pg.inner_text('#op-job-banner')); shot('07-saved')
    check('status says the lab is saved on the VM', 'Saved on the VM' in pg.inner_text('#builder-status'))
    pg.click('#op-open-published'); pg.wait_for_selector('#op-deploy-project', timeout=15000)
    check('the saved file opens in the normal Topology file dialog', f'{LAB}.clab.yml' in pg.input_value('#op-edit-path')); shot('08-topology-file')
    pg.click('#op-deploy-project'); pg.wait_for_selector('#op-confirm', timeout=20000); check('Deploy lab asks for the usual review', 'Start' in pg.inner_text('#operation-review h2')); pg.click('#op-confirm')
    wait_job(); shot('09-deployed'); check('the deploy job succeeds', True)
    pg.goto(args.base + '/'); pg.wait_for_timeout(2500)
    labs = pg.evaluate("state.labs.map(l => ({name: l.name, path: l.vm_project_path, nodes: l.nodes.length}))"); mine = next((l for l in labs if l['name'] == LAB), None)
    check('the lab is in My labs, linked to its topology file, with its devices', bool(mine) and mine['path'].endswith(f'/{LAB}/{LAB}.clab.yml') and mine['nodes'] == 3, mine); shot('10-my-labs')
    drawing = pg.evaluate(f"fetch('/api/labs/' + state.labs.find(l => l.name === '{LAB}').id + '/topology').then(r => r.json())")
    placed = [n for n in drawing.get('nodes', []) if n.get('x') is not None]
    check("the manager's own map uses the layout drawn in the builder", drawing.get('placed') is True and len(placed) == 3, {k: drawing.get(k) for k in ('placed',)})

    # 5. Saving again: refused while deployed, allowed after destroy, with the changes shown
    pg.goto(args.base + f'/static/lab-builder.html#draft=new:{LAB}'); pg.wait_for_selector('.react-flow__node', timeout=20000); pg.wait_for_timeout(1000)
    bx = pg.get_by_text('Linux host', exact=True).bounding_box(); pg.mouse.move(bx['x'] + 10, bx['y'] + 8); pg.mouse.down(); pg.mouse.move(640, 560, steps=12); pg.mouse.up(); pg.wait_for_timeout(900)
    check('a later edit shows as not saved to the VM', 'Changes not saved' in pg.inner_text('#builder-status') and 'Save changes' in pg.inner_text('#builder-save'))
    pg.click('#builder-save'); pg.wait_for_timeout(2500)
    check('saving over a deployed lab is refused with the reason', 'deployed' in pg.inner_text('#toast').lower() or 'deployed' in pg.inner_text('body').lower()); shot('11-refused-while-deployed')
    lab_id = pg.evaluate(f"fetch('/api/state').then(r => r.json()).then(s => s.labs.find(l => l.name === '{LAB}').id)")
    token = pg.evaluate(f"fetch('/api/operations/preview', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{action:'destroy', lab_id:'{lab_id}', options:{{cleanup:true}}}})}}).then(r => r.json()).then(v => v.token)")
    job_id = pg.evaluate(f"fetch('/api/operations/confirm', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{token:'{token}'}})}}).then(r => r.json()).then(j => j.id)")
    pg.wait_for_function(f"fetch('/api/operations/{job_id}').then(r => r.json()).then(j => j.status === 'succeeded')", timeout=90000, polling=1000)
    pg.wait_for_timeout(4000)  # the manager refreshes discovery before it accepts the next operation
    for attempt in range(10):  # discovery needs a poll to see that the lab is gone; a review may open late
        if pg.locator('#op-confirm').is_visible(): break
        try: pg.click('#builder-save', timeout=3000); pg.wait_for_selector('#op-confirm', timeout=10000)
        except Exception: pg.wait_for_timeout(2000)
    check('after destroy the save review shows what changes', pg.locator('#op-confirm').is_visible() and '+' in pg.inner_text('#operation-review') and 'host1' in pg.inner_text('#operation-review')); shot('12-revise-review')
    for attempt in range(6):  # 'Wait for the current lab operation' while discovery is still refreshing
        pg.click('#op-confirm'); pg.wait_for_timeout(2500)
        if not pg.locator('#operation-review').evaluate('d => d.open'): break
    pg.wait_for_selector('#op-open-published', timeout=40000)
    check('the revision is saved and a recovery copy is reported', 'succeeded' in pg.inner_text('#op-job-banner') and 'Saved on the VM' in pg.inner_text('#builder-status'))
    pg.click('#operation-output [data-op-close]')

    # 6. Opening an existing topology from the Deploy dialog
    updated = pg.evaluate(f"fetch('/api/state').then(r => r.json()).then(s => s.labs.find(l => l.name === '{LAB}').nodes.length)")
    check('My labs follows the revised topology (four devices)', updated == 4, updated)
    pg.goto(args.base + '/'); pg.wait_for_timeout(1500)
    if pg.locator('#crumb-home').is_visible(): pg.click('#crumb-home')  # the router reopens the last lab
    pg.wait_for_selector('#home-deploy'); pg.click('#home-deploy'); pg.wait_for_selector('#op-file-tree'); pg.wait_for_timeout(800)
    pg.get_by_text('/srv/containerlab-node-manager/projects', exact=True).first.click(); pg.wait_for_timeout(900); pg.locator('#op-file-tree summary', has_text=LAB).first.click(); pg.wait_for_timeout(900)
    pg.locator('.op-tree-file', has_text=f'{LAB}.clab.yml').first.click(); pg.wait_for_selector('#op-build-edit', timeout=15000)
    check('an existing topology file offers "Edit visually"', pg.locator('#op-build-edit').is_visible()); pg.click('#op-build-edit'); pg.wait_for_selector('.react-flow__node', timeout=20000); pg.wait_for_timeout(1200)
    check('the VM version opens in the builder with its layout', nodes() == 4 and 'Saved on the VM' in pg.inner_text('#builder-status'), f'{nodes()} nodes · ' + pg.inner_text('#builder-status')); shot('13-edit-existing')

    csp = pg.evaluate('window.__csp'); check('no Content-Security-Policy violation on the last page', not csp, csp[:3]); check('no console or page errors in the whole run', not noise, noise[:4])
    browser.close()


with sync_playwright() as p:
    try: run(p)
    except Exception as exc:
        check('the run reached its end', False, str(exc).splitlines()[0][:200])
        try:
            pg = state['page']; pg.screenshot(path=f'{args.out}/failure.png')
            print('  dialog errors:', [t for t in pg.locator('dialog[open] .form-error').all_inner_texts() if t.strip()], '| toast:', pg.inner_text('#toast') if pg.locator('#toast').count() else '')
        except Exception: pass
failed = [c for c in checks if not c[1]]
json.dump({'lab': LAB, 'passed': len(checks) - len(failed), 'failed': [c[0] for c in failed], 'checks': [{'name': c[0], 'ok': c[1]} for c in checks]}, open(f'{args.out}/student-workflow.json', 'w'), indent=1)
print(f'\n{len(checks) - len(failed)} of {len(checks)} checks passed'); sys.exit(1 if failed else 0)
