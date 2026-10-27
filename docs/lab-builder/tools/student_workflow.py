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

ap = argparse.ArgumentParser(); ap.add_argument('--base', default='http://127.0.0.1:8090'); ap.add_argument('--out', default='.'); ap.add_argument('--name', default=''); ap.add_argument('--template', default='Arista cEOS', help='device template for the starter, e.g. "Linux host" for a fast real deploy'); ap.add_argument('--job-timeout', type=int, default=40000)
args = ap.parse_args()
BASE = 'host' if args.template == 'Linux host' else {'Arista cEOS': 'ceos', 'Juniper cJunosEvolved': 'ptx', 'Juniper vJunos-switch': 'sw', 'Cisco XRv9k': 'xr'}[args.template]
N1, N2, N3, ADDED = BASE + '1', BASE + '2', BASE + '3', 'host4' if BASE == 'host' else 'host1'
LAB = args.name or 'student-' + time.strftime('%H%M%S'); checks = []; noise = []; state = {}

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
    def wait_job(label, timeout=args.job_timeout):
        # The output dialog is reused: the banner of the job before this one may still be showing, so the
        # label of the awaited operation has to be in it as well as the word that ends it.
        end = time.time() + timeout / 1000
        while time.time() < end:
            text = pg.inner_text('#op-job-banner') if pg.locator('#op-job-banner').count() else ''
            if label in text and ('succeeded' in text or 'failed' in text or 'interrupted' in text): return text
            pg.wait_for_timeout(500)
        raise TimeoutError('no result for ' + label)

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
    # A new lab always starts blank; the triangle this workflow needs from here on is built by hand,
    # dragging the chosen device template from the palette three times and linking the devices in a ring.
    pg.fill('#builder-new-name', LAB); pg.click('#builder-new-create')
    pg.wait_for_selector('[data-testid="navbar-layout"]', timeout=20000); pg.wait_for_timeout(1000)
    check('a new lab starts as a blank canvas', nodes() == 0 and edges() == 0, f'{nodes()} nodes, {edges()} edges')
    template = pg.get_by_text(args.template, exact=True).first
    for x, y in ((360, 220), (620, 220), (490, 420)):
        bx = template.bounding_box(); pg.mouse.move(bx['x'] + 10, bx['y'] + 8); pg.mouse.down(); pg.mouse.move(x, y, steps=12); pg.mouse.up(); pg.wait_for_timeout(700)
    check('three devices dragged from the palette are added', nodes() == 3, f'{nodes()} nodes')
    menu(node(N1), 'Create Link'); x, y = center(node(N2)); pg.mouse.click(x, y); pg.wait_for_timeout(700)
    menu(node(N2), 'Create Link'); x, y = center(node(N3)); pg.mouse.click(x, y); pg.wait_for_timeout(700)
    menu(node(N3), 'Create Link'); x, y = center(node(N1)); pg.mouse.click(x, y); pg.wait_for_timeout(700)
    check('a triangle of links can be built by hand from the palette', nodes() == 3 and edges() == 3, f'{nodes()} nodes, {edges()} edges')
    check('links are visible (not collapsed by the manager stylesheet)', pg.evaluate("getComputedStyle(document.querySelector('.react-flow__edge').closest('svg')).width") != '0px')
    check('status says the draft is only in this browser', 'not on the VM yet' in pg.inner_text('#builder-status'))
    for tid in ('navbar-deploy', 'navbar-deploy-menu', 'navbar-split-view'):
        check(f'editor control {tid} is hidden', not pg.locator(f'[data-testid="{tid}"]').is_visible())
    pg.click('[data-testid="navbar-layout"]'); pg.wait_for_timeout(300)
    check('Geo layout is hidden, the other layouts remain', not pg.locator('[data-testid="navbar-layout-geo"]').is_visible() and pg.locator('[data-testid="navbar-layout-force"]').is_visible()); pg.keyboard.press('Escape'); pg.wait_for_timeout(300)
    check('YAML and JSON editor tabs are absent', pg.get_by_role('tab', name='YAML').count() == 0 and pg.get_by_role('tab', name='JSON').count() == 0); shot('03-editor')

    # 2. Build: add a device, link it, edit it, delete and undo
    # After a link is made the editor's side panel shows the Link Editor; its Nodes tab brings the palette back.
    if not pg.get_by_text('Linux host', exact=True).first.is_visible(): pg.click('[data-testid="panel-tab-nodes"]'); pg.wait_for_timeout(400)
    bx = pg.get_by_text('Linux host', exact=True).first.bounding_box(); pg.mouse.move(bx['x'] + 10, bx['y'] + 8); pg.mouse.down(); pg.mouse.move(640, 520, steps=12); pg.mouse.up(); pg.wait_for_timeout(900)
    check('a device dragged from the palette is added', nodes() == 4 and ADDED in draft()['yaml'])
    known = pg.evaluate("fetch('/api/operations/known-images').then(r => r.json()).then(v => (v.images.linux || [])[0] || '')")
    if known: check('a device from the palette carries the image this site already uses for its kind', f'image: {known}' in draft()['yaml'].split(ADDED + ':')[1], known)
    menu(node(ADDED), 'Create Link'); x, y = center(node(N1)); pg.mouse.click(x, y); pg.wait_for_timeout(900)
    check('a link is drawn with allocated interfaces', edges() == 4 and f'"{ADDED}:eth1", "{N1}:' in draft()['yaml'], draft()['yaml'][-200:])
    menu(node(ADDED), 'Edit Node')
    if not pg.get_by_label('Node Name').is_visible(): pg.click('[data-testid="panel-tab-edit"]'); pg.wait_for_timeout(400)  # the Nodes tab chosen above stays in front
    pg.get_by_label('Node Name').fill('pc1'); pg.get_by_role('button', name='Apply', exact=True).first.click(); pg.wait_for_timeout(900)
    check('renaming a device updates its links', 'pc1:eth1' in draft()['yaml'] and (ADDED + ':') not in draft()['yaml'])
    before = draft()['yaml']; menu(node(N3), 'Delete Node'); pg.wait_for_timeout(700)
    check('deleting a device removes it and its links', nodes() == 3 and N3 not in draft()['yaml'])
    pg.click('[data-testid="navbar-undo"]'); pg.wait_for_timeout(900)
    check('undo restores the device and its links', nodes() == 4 and draft()['yaml'].count(N3) == before.count(N3))
    pg.click('#builder-yaml'); pg.wait_for_selector('#builder-yaml-editor', state='visible'); check('the YAML panel shows the draft\'s topology text', pg.input_value('#builder-yaml-editor') == draft()['yaml'] and f'name: {LAB}' in draft()['yaml']); shot('04-view-yaml'); pg.click('#builder-yaml-close'); pg.wait_for_timeout(300)
    with pg.expect_download() as dl: pg.click('#builder-download')
    exported = json.load(open(dl.value.path())); check('Download draft gives a portable draft file', exported['format'] == 'clab-manager-lab-draft' and exported['name'] == LAB)

    # 3. A second tab editing the same draft is detected instead of silently overwriting
    other = watch(ctx.new_page()); other.goto(pg.url); other.wait_for_selector('.react-flow__node', timeout=20000); other.wait_for_timeout(1000)
    ox, oy = center(other.locator('.react-flow__node').filter(has_text='pc1').first); other.mouse.click(ox, oy, button='right'); other.wait_for_timeout(350); other.get_by_role('menuitem', name='Delete Node').click(); other.wait_for_timeout(900); other.close()
    menu(node(N2), 'Delete Node'); pg.wait_for_timeout(900)
    check('an edit over a newer version from another tab is stopped', pg.locator('#builder-problem').is_visible() and 'another tab' in pg.inner_text('#builder-problem-text')); shot('05-other-tab')
    pg.click('#builder-problem-reload'); pg.wait_for_selector('.react-flow__node', timeout=20000); pg.wait_for_timeout(1000)
    check('after reloading the newer version is shown', nodes() == 3 and 'pc1' not in draft()['yaml'])

    # 4. Save to the VM through the reviewed operation, then deploy through the normal flow
    pg.click('#builder-save'); pg.wait_for_selector('#op-confirm', timeout=15000)
    review = pg.inner_text('#operation-review')
    check('the save review names the lab folder and shows the YAML', f'/srv/containerlab-node-manager/projects/{LAB}' in review and f'name: {LAB}' in pg.inner_text('#op-review-yaml')); shot('06-save-review')
    # The builder's own save result offers the next step itself (opRenderPublished): "Add to My labs without
    # starting" and "Deploy now", not the generic Topology file dialog.
    pg.click('#op-confirm'); pg.wait_for_selector('#op-published-add', timeout=args.job_timeout)
    check('the save succeeds and offers to deploy or add the lab', 'succeeded' in pg.inner_text('#op-job-banner') and pg.locator('#op-published-deploy').is_visible() and 'Add to My labs without starting' in pg.inner_text('#op-published-add')); shot('07-saved')
    check('status says the lab is saved on the VM', 'Saved on the VM' in pg.inner_text('#builder-status'))
    check('the result names the saved topology file and says it is not running', f'{LAB}.clab.yml' in pg.inner_text('#operation-output #op-job-result') and 'not running' in pg.inner_text('#operation-output #op-job-result'), pg.inner_text('#operation-output #op-job-result')[:200])
    pg.click('#op-published-add'); pg.wait_for_selector('#op-published-status', timeout=20000)
    check('Add to My labs without starting adds the lab and says nothing was started', LAB in pg.inner_text('#op-published-status') and 'not running' in pg.inner_text('#op-published-status'), pg.inner_text('#op-published-status')); shot('08-added')
    pg.click('#op-published-deploy'); pg.wait_for_selector('#op-confirm', timeout=20000); check('Deploy now asks for the usual review', 'Start' in pg.inner_text('#operation-review h2')); pg.click('#op-confirm')
    ended = wait_job('Start lab'); shot('09-deployed'); check('the deploy job succeeds', 'succeeded' in ended, ended)
    pg.goto(args.base + '/'); pg.wait_for_timeout(2500)
    labs = pg.evaluate("state.labs.map(l => ({name: l.name, path: l.vm_project_path, nodes: l.nodes.length}))"); mine = next((l for l in labs if l['name'] == LAB), None)
    check('the lab is in My labs, linked to its topology file, with its devices', bool(mine) and mine['path'].endswith(f'/{LAB}/{LAB}.clab.yml') and mine['nodes'] == 3, mine); shot('10-my-labs')
    drawing = pg.evaluate(f"fetch('/api/labs/' + state.labs.find(l => l.name === '{LAB}').id + '/topology').then(r => r.json())")
    placed = [n for n in drawing.get('nodes', []) if n.get('x') is not None]
    check("the manager's own map uses the layout drawn in the builder", drawing.get('placed') is True and len(placed) == 3, {k: drawing.get(k) for k in ('placed',)})

    # 5. Saving again while the lab runs: the lab-state line says it, the review names the running devices, the save leaves
    #    the running lab alone and the output dialog leads back to the lab's own apply review
    lab_id = pg.evaluate(f"fetch('/api/state').then(r => r.json()).then(s => s.labs.find(l => l.name === '{LAB}').id)")
    for attempt in range(30):  # the manager learns from discovery that the lab runs
        if pg.evaluate(f"fetch('/api/state').then(r => r.json()).then(s => /running/i.test(s.labs.find(l => l.name === '{LAB}')?.deployment?.status || ''))"): break
        pg.wait_for_timeout(2000)
    pg.goto(args.base + f'/static/lab-builder.html#draft=new:{LAB}&lab={lab_id}'); pg.reload(); pg.wait_for_selector('.react-flow__node', timeout=20000); pg.wait_for_timeout(1500)
    bx = pg.get_by_text('Linux host', exact=True).bounding_box(); pg.mouse.move(bx['x'] + 10, bx['y'] + 8); pg.mouse.down(); pg.mouse.move(640, 560, steps=12); pg.mouse.up(); pg.wait_for_timeout(900)
    check('a later edit shows as not saved to the VM', 'Changes not saved' in pg.inner_text('#builder-status') and 'Save changes' in pg.inner_text('#builder-save'))
    check('the lab-state line says the lab is running and that applying is a separate step', 'running' in pg.inner_text('#builder-line-text') and 'applying is a separate step' in pg.inner_text('#builder-line-text'), pg.inner_text('#builder-line-text'))
    for attempt in range(20):  # while the automatic login test of the new lab runs, the answer is "wait for the job": a dialog that is closed and retried
        pg.click('#builder-save')
        try: pg.wait_for_selector('#op-confirm', timeout=8000); break
        except Exception:
            if pg.locator('#builder-save-problem-close').is_visible(): pg.click('#builder-save-problem-close')
            pg.wait_for_timeout(3000)
    review = pg.inner_text('#operation-review')
    check('saving over a running lab opens a review that names the running devices and shows what changes', pg.locator('#op-confirm').is_visible() and 'running' in review.lower() and '+' in review and 'kind: linux' in review, review[:300]); shot('11-revise-review-deployed')
    for attempt in range(6):  # 'Wait for the current lab operation' while discovery is still refreshing
        pg.click('#op-confirm'); pg.wait_for_timeout(2500)
        if not pg.locator('#operation-review').evaluate('d => d.open'): break
    pg.wait_for_selector('#op-back-review', timeout=args.job_timeout)
    result = pg.inner_text('#operation-output #op-job-result')
    check('the save succeeds and says the running lab is unchanged until the changes are applied', 'succeeded' in pg.inner_text('#op-job-banner') and 'The running lab is unchanged until you apply the changes' in result and 'not running yet' not in result, result[:300])
    check('the output dialog offers only Back to lab and review changes…, no Deploy now', 'Back to lab and review changes' in pg.inner_text('#op-back-review') and not pg.locator('#op-published-deploy').count() and not pg.locator('#op-published-go').count())
    check('the status reads Saved on the VM (not applied while the plan differs)', pg.inner_text('#builder-status').startswith('Saved on the VM'), pg.inner_text('#builder-status'))
    check('a recovery copy of the previous version is reported', 'A recovery copy of the previous version was kept at' in result, result[:300])
    pg.click('#op-back-review'); pg.wait_for_selector('#op-confirm', timeout=30000)
    check('Back to lab and review changes… opens the lab with its apply review, once', pg.locator('#op-confirm').is_visible() and 'review=' not in pg.url and f'lab={lab_id}' in pg.url, pg.url); shot('12-apply-review')
    pg.click('#operation-review [data-op-close]')

    # 6. Opening an existing topology from the Deploy dialog
    updated = pg.evaluate(f"fetch('/api/state').then(r => r.json()).then(s => s.labs.find(l => l.name === '{LAB}').nodes.length)")
    check('My labs keeps the running lab as it is until the changes are applied (three devices)', updated == 3, updated)
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
