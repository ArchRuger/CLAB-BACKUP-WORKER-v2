#!/usr/bin/env python3
"""Student quick-start Scenario B ("build your own lab and keep it in Git"), replayed on the live Containerlab
Node Manager (release 1.31.6 UI: the builder's blank canvas and palette, Save to the VM…, the lab header's save
chip, Save, Load).

    /home/archtop/pw-venv/bin/python docs/student-quick-start/tools/capture_scenario_b.py            # all steps
    /home/archtop/pw-venv/bin/python docs/student-quick-start/tools/capture_scenario_b.py --steps 6-9

Steps share state (the lab id, timings) through build/state-b.json. Reset the starting state with
tools/reset_scenario_b.sh. Needs the manager on http://127.0.0.1:8081, the cEOS image n24l/ceos:4.35.0F on the VM
and a private repository (default ArchRuger/campaign2-my-network-labs, made with a README). Evidence goes to
evidence/scenario-b.{json,md}, raw screenshots to screenshots/raw/b<step>-<name>-{full,el}.png.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import qs_lib  # noqa: E402
import qs_ui  # noqa: E402
import eos  # noqa: E402
from qs_lib import BASE, api, settle, wait_idle, wait_text  # noqa: E402
from qs_ui import chip, open_chip, open_cli, open_lab, type_lines  # noqa: E402

SCREEN_DIR = ROOT / 'screenshots' / 'raw'
EVIDENCE_JSON = ROOT / 'evidence' / 'scenario-b.json'
EVIDENCE_MD = ROOT / 'evidence' / 'scenario-b.md'
STATE_FILE = ROOT / 'build' / 'state-b.json'

LAB_NAME = 'my-first-lab'
PROJECTS_ROOT = '/srv/containerlab-node-manager/projects'
LAB_VM_FOLDER = f'{PROJECTS_ROOT}/{LAB_NAME}'
TOPOLOGY_PATH = f'{LAB_VM_FOLDER}/{LAB_NAME}.clab.yml'
R1 = f'clab-{LAB_NAME}-r1'
R2 = f'clab-{LAB_NAME}-r2'
R1_IP, R2_IP = '172.20.20.21', '172.20.20.22'
GH_ACCOUNT = os.environ.get('QS_GH_ACCOUNT', 'ArchRuger')
REPO_NAME = os.environ.get('QS_B_REPO', 'campaign2-my-network-labs')
GH_REPO = f'{GH_ACCOUNT}/{REPO_NAME}'
REPO_URL = f'https://github.com/{GH_REPO}.git'
CLONE_ON_VM = f'{PROJECTS_ROOT}/{REPO_NAME}'
CLONED_TOPOLOGY = f'{CLONE_ON_VM}/{LAB_NAME}/latest/{LAB_NAME}.clab.yml'
EXAMPLES_DIR = ROOT / 'examples' / 'my-first-lab'


def tree():
    return qs_ui.gh_tree(GH_REPO)


def blob(path):
    return qs_ui.gh_blob_text(GH_REPO, path)


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1) + '\n')


def run_cmd(cmd, cwd=None, timeout=180):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)


def center(locator):
    b = locator.bounding_box()
    return b['x'] + b['width'] / 2, b['y'] + b['height'] / 2


def render_transcript(page, title, commands, filename):
    """A monospace HTML page of a command transcript, screenshotted. Evidence rendering only: the figure says so."""
    def esc(t):
        return t.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    body = [f'<h1>{esc(title)}</h1>']
    for cmd, output in commands:
        body.append(f'<p class="cmd">$ {esc(cmd)}</p>')
        if output.strip():
            body.append(f'<pre>{esc(output.rstrip())}</pre>')
    html = ('<!doctype html><html><head><meta charset="utf-8"><style>'
            'body{font-family:"DejaVu Sans Mono",monospace;font-size:13px;width:1000px;margin:0;padding:16px;'
            'background:#111;color:#ddd;}h1{font-size:15px;color:#fff;}'
            'p.cmd{color:#7fd0ff;margin:14px 0 2px 0;white-space:pre-wrap;word-break:break-all;}'
            'pre{margin:0 0 6px 0;white-space:pre-wrap;word-break:break-all;color:#ddd;}'
            '</style></head><body>' + ''.join(body) + '</body></html>')
    tmp = SCREEN_DIR / f'_{filename}.html'
    tmp.write_text(html)
    return_url = page.url
    page.goto('file://' + str(tmp))
    page.wait_for_timeout(200)
    height = page.evaluate('document.body.scrollHeight')
    page.set_viewport_size({'width': 1000, 'height': min(max(height, 300), 3000)})
    page.wait_for_timeout(150)
    page.screenshot(path=str(SCREEN_DIR / filename), full_page=True)
    tmp.unlink(missing_ok=True)
    page.set_viewport_size(qs_lib.VIEWPORT)
    if return_url.startswith('http'):
        page.goto(return_url)
        page.wait_for_timeout(500)


def open_tree_folder(container, name, timeout=15000):
    """Click the summary named `name` among the DIRECT children of `container` (a plain text search of the whole
    tree also matches a same-named folder at another level, for example the original my-first-lab folder)."""
    summary = container.locator('> details > summary').filter(has_text=re.compile(r'^\s*' + re.escape(name) + r'\s*$'))
    summary.first.wait_for(state='visible', timeout=timeout)
    summary.first.click()
    children = summary.first.locator('xpath=..').locator('> div.op-tree-children')
    children.wait_for(state='visible', timeout=timeout)
    return children


def lab_id_from_home(page, name=LAB_NAME):
    page.goto(BASE + '/#/')
    page.wait_for_selector('article.lab-card', timeout=30000)
    settle(page, 1200)
    card = page.locator(f'article.lab-card:has-text("{name}")').first
    card.wait_for(state='visible', timeout=15000)
    card.get_by_role('button', name='Open lab').click()
    page.wait_for_selector('#lab-content:not([hidden])', timeout=30000)
    m = re.search(r'lab=([0-9a-f]+)', page.evaluate('() => location.hash'))
    return m.group(1) if m else None


# ----------------------------------------------------------------------------------------------------
def step_1(rec, pw, st):
    wait_idle()
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(1, 'Start a new lab in the builder')
    page.goto(BASE + '/#/')
    page.wait_for_selector('#home-build', timeout=30000)
    settle(page, 1200)
    page.click('#home-build')
    page.wait_for_selector('#builder-welcome-new', timeout=30000)
    settle(page, 1500)
    s['observed']['welcome_text'] = page.locator('#builder-welcome').inner_text()
    rec.shoot_full(page, s, 'builder-welcome')
    page.click('#builder-welcome-new')
    page.wait_for_selector('#builder-new-name', timeout=15000)
    page.fill('#builder-new-name', LAB_NAME)
    page.select_option('#builder-new-root', PROJECTS_ROOT)
    settle(page, 800)
    s['observed']['new_lab_dialog'] = page.locator('#builder-new').inner_text()
    rec.shoot_full(page, s, 'new-lab-dialog')
    rec.shoot_element(page.locator('#builder-new'), s, 'new-lab-dialog', label='New lab')
    page.click('#builder-new-create')
    page.wait_for_selector('#builder-hint', timeout=20000)
    settle(page, 2500)
    s['observed']['builder_bar'] = page.locator('#builder-bar').inner_text()
    s['observed']['blank_canvas_hint'] = page.locator('#builder-hint').inner_text()
    s['observed']['palette_templates'] = page.locator('text=Arista cEOS').count() > 0
    rec.shoot_full(page, s, 'blank-canvas')
    rec.write()
    browser.close()


def drag_two_ceos(page):
    for i, (x, y) in enumerate(((150, 300), (500, 300))):
        for attempt in range(4):
            page.get_by_text('Arista cEOS', exact=True).first.drag_to(page.locator('.react-flow'), target_position={'x': x, 'y': y})
            page.wait_for_timeout(1500)
            if page.locator('.react-flow__node').count() > i:
                break
    nodes = page.locator('.react-flow__node')
    # place the two devices side by side, clear of the palette
    for node, (x, y) in ((nodes.nth(0), (170, 330)), (nodes.nth(1), (620, 330))):
        cx, cy = center(node)
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(x, y, steps=12)
        page.mouse.up()
        page.wait_for_timeout(700)
    # level: move the second device to the height of the first
    (_, y1), (x2, y2) = center(nodes.nth(0)), center(nodes.nth(1))
    page.mouse.move(x2, y2)
    page.mouse.down()
    page.mouse.move(x2, y1, steps=8)
    page.mouse.up()
    page.wait_for_timeout(700)


def create_link(page, first, second):
    x, y = center(page.locator('.react-flow__node').filter(has_text=first).first)
    page.mouse.click(x, y, button='right')
    page.get_by_role('menuitem', name='Create Link').click()
    page.wait_for_timeout(400)
    x, y = center(page.locator('.react-flow__node').filter(has_text=second).first)
    page.mouse.click(x, y)
    page.wait_for_timeout(1500)


def edit_node(page, old, new, ip):
    """Right-click a device > Edit Node: name, Network tab Management IPv4, back to Basic to see the image, Apply."""
    x, y = center(page.locator('.react-flow__node').filter(has_text=old).first)
    page.mouse.click(x, y, button='right')
    page.wait_for_timeout(500)
    page.get_by_role('menuitem', name='Edit Node').click()
    page.wait_for_timeout(1200)
    page.fill('#node-name', new)
    page.wait_for_timeout(200)
    shot_before_apply = None
    page.get_by_text('Network', exact=True).click()
    page.wait_for_timeout(400)
    page.fill('#node-mgmt-ipv4', ip)
    page.wait_for_timeout(200)
    page.get_by_text('Basic', exact=True).click()
    page.wait_for_timeout(500)
    return page.input_value('#node-image'), page.input_value('#node-version')


def step_2(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(2, 'Draw and check the topology')
    page.goto(BASE + '/#/')
    page.wait_for_selector('#home-build', timeout=30000)
    page.click('#home-build')
    page.wait_for_selector('#builder-welcome', timeout=30000)
    settle(page, 1500)
    # the draft of step 1 is kept in this browser's storage only: a new browser starts it again
    if page.locator('#builder-welcome-new').is_visible():
        page.click('#builder-welcome-new')
        page.wait_for_selector('#builder-new-name', timeout=15000)
        page.fill('#builder-new-name', LAB_NAME)
        page.select_option('#builder-new-root', PROJECTS_ROOT)
        page.click('#builder-new-create')
        page.wait_for_selector('#builder-hint', timeout=20000)
        settle(page, 2500)
    drag_two_ceos(page)
    s['actions'].append('Drag Arista cEOS from the palette twice; put the devices side by side')
    create_link(page, 'ceos1', 'ceos2')
    s['actions'].append('Right-click the first device > Create Link, click the second')
    s['observed']['nodes'] = page.locator('.react-flow__node').all_inner_texts()
    s['observed']['edges'] = page.locator('.react-flow__edge').count()
    if s['observed']['edges'] != 1 or len(s['observed']['nodes']) != 2:
        rec.fail(s, f"expected 2 devices and 1 link: {s['observed']}", page)
    img, ver = edit_node(page, 'ceos1', 'r1', R1_IP)
    s['observed']['r1_image_version'] = f'{img} {ver}'
    rec.shoot_full(page, s, 'node-editor-r1')
    head = page.locator('text=Node Editor').first.bounding_box()
    rec.shoot_clip(page, s, 'node-editor-r1', clip={'x': head['x'] - 17, 'y': head['y'] - 16, 'width': 1366 - (head['x'] - 17),
                                                     'height': 878 - (head['y'] - 16)}, label='Node Editor: r1')
    page.get_by_role('button', name='Apply', exact=True).first.click()
    page.wait_for_timeout(900)
    img, ver = edit_node(page, 'ceos2', 'r2', R2_IP)
    s['observed']['r2_image_version'] = f'{img} {ver}'
    page.get_by_role('button', name='Apply', exact=True).first.click()
    page.wait_for_timeout(900)
    s['actions'].append('Edit Node on each device: name r1 / r2, Management IPv4 172.20.20.21 / .22, Apply')
    # a text note on empty canvas
    page.mouse.click(400, 600, button='right')
    page.wait_for_timeout(500)
    s['observed']['canvas_menu'] = page.get_by_role('menuitem').all_inner_texts()
    page.get_by_role('menuitem', name='Add Text').click()
    page.wait_for_timeout(800)
    ta = page.locator('textarea').first
    ta.click()
    ta.fill('My first lab: r1 eth1 - r2 eth1')
    page.mouse.click(200, 200)
    page.wait_for_timeout(900)
    s['actions'].append('Right-click empty canvas > Add Text')
    rec.shoot_full(page, s, 'canvas-finished')
    rec.shoot_element(page.locator('#builder-stage'), s, 'canvas-finished', label='Finished canvas')
    page.click('#builder-yaml')
    page.wait_for_selector('#builder-yaml-editor', timeout=15000)
    settle(page, 1500)
    yaml_text = page.locator('#builder-yaml-editor').input_value()
    s['observed']['yaml'] = yaml_text
    rec.shoot_full(page, s, 'yaml')
    ok = yaml_text.count('image: n24l/ceos:4.35.0F') == 2 and f'mgmt-ipv4: {R1_IP}' in yaml_text and f'mgmt-ipv4: {R2_IP}' in yaml_text
    s['observed']['yaml_shows_both_images_and_addresses'] = ok
    if not ok:
        rec.fail(s, 'YAML does not show both devices with the image and the management addresses', page)
    st['draft_note'] = 'the draft lives in the browser that built it; step 3 continues in the same run'
    rec.write()
    # the draft is kept in this browser only: carry on in the same page (steps 2 and 3 share a browser)
    rec.carry = (browser, context, page)


def step_3(rec, pw, st):
    wait_idle()
    carried = getattr(rec, 'carry', None)
    if carried:
        browser, context, page = carried
    else:
        raise RuntimeError('step 3 needs the draft of step 2: run steps 2-3 together')
    s = rec.new_step(3, 'Save to the VM and deploy')
    try:
        page.keyboard.press('Escape')
    except Exception:
        pass
    page.click('#builder-save')
    page.wait_for_selector('#operation-review', state='visible', timeout=20000)
    settle(page, 1000)
    s['observed']['save_review'] = page.locator('#operation-review').inner_text()[:1500]
    rec.shoot_full(page, s, 'save-review')
    rec.shoot_element(page.locator('#operation-review'), s, 'save-review', label='Save my-first-lab to the VM?')
    page.click('#op-confirm')
    page.get_by_role('button', name='Deploy now').wait_for(state='visible', timeout=90000)
    settle(page, 1200)
    s['observed']['save_result_dialog'] = page.locator('#operation-output').inner_text()
    s['observed']['builder_status_after_save'] = page.locator('#builder-status').inner_text()
    s['observed']['save_button_after_save'] = page.locator('#builder-save').inner_text()
    rec.shoot_full(page, s, 'save-result')
    rec.shoot_element(page.locator('#operation-output'), s, 'save-result', label='Save lab result')
    if 'succeeded' not in s['observed']['save_result_dialog']:
        rec.fail(s, 'save did not succeed', page)
    page.get_by_role('button', name='Deploy now').click()
    # "Deploy now" opens the Topology file dialog or goes straight to the Start review
    for _ in range(40):
        if page.locator('#op-deploy-project').is_visible():
            s['observed']['deploy_now_opens'] = 'the Topology file dialog'
            s['observed']['topology_file_path'] = page.locator('#op-edit-path').input_value()
            settle(page, 800)
            rec.shoot_full(page, s, 'topology-file')
            page.click('#op-deploy-project')
            break
        if page.locator('#operation-review').is_visible():
            s['observed']['deploy_now_opens'] = 'the Start review'
            break
        page.wait_for_timeout(500)
    page.wait_for_selector('#operation-review', state='visible', timeout=20000)
    settle(page, 1000)
    s['observed']['start_review_title'] = page.locator('#operation-review h2').first.inner_text()
    rec.shoot_full(page, s, 'start-review')
    rec.shoot_element(page.locator('#operation-review'), s, 'start-review', label='Start my-first-lab?')
    t_confirm = time.time()
    page.click('#op-confirm')
    page.wait_for_selector('#operation-output', state='visible', timeout=90000)
    wait_text(page, '#op-job-banner', r'succeeded|failed', timeout=240)
    s['observed']['deploy_banner'] = page.locator('#op-job-banner').inner_text()
    st['deploy_confirm_time'] = t_confirm
    settle(page, 1000)
    s['observed']['vm_folder'] = sorted(p.name for p in pathlib.Path(LAB_VM_FOLDER).glob('*'))
    for f in pathlib.Path(LAB_VM_FOLDER).glob('*.clab.yml*'):
        EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)
        (EXAMPLES_DIR / f.name).write_text(f.read_text())
    st['lab_id'] = None
    browser.close()
    rec.carry = None
    b2, c2, p2 = qs_lib.new_context(pw)
    st['lab_id'] = lab_id_from_home(p2)
    s['observed']['lab_id'] = st['lab_id']
    s['actions'].append('Home > the my-first-lab card > Open lab (the builder page does not open the lab itself)')
    b2.close()
    rec.write()


def step_4(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(4, 'Bring the link up')
    open_lab(page, st['lab_id'], 'devices')
    pills, secs = qs_ui.wait_devices_ready(page, 2)
    s['observed']['deploy_to_ready_seconds'] = round(time.time() - st.get('deploy_confirm_time', time.time()), 1)
    s['observed']['pills'] = pills
    if secs is None:
        rec.fail(s, f'devices not Ready: {pills}', page)
    rec.shoot_full(page, s, 'devices-ready')
    for container, addr in ((R1, '10.0.0.1/30'), (R2, '10.0.0.2/30')):
        term = open_cli(context, page, container)
        type_lines(term, ['enable', 'configure terminal', 'ip routing', 'interface Ethernet1', 'no switchport',
                          f'ip address {addr}', 'end', 'write memory'])
        s['actions'].append(f'{container}: ip routing, Ethernet1 no switchport, ip address {addr}, write memory')
        term.close()
    term = open_cli(context, page, R1)
    type_lines(term, ['ping 10.0.0.2'], pause=3500)
    rec.shoot_full(term, s, 'ping')
    rec.shoot_element(term.locator('#terminal'), s, 'ping', label='r1: ping 10.0.0.2')
    term.close()
    out = eos.show(R1_IP, 'ping 10.0.0.2 repeat 3')
    s['device_evidence']['r1_ping'] = out[-500:]
    s['device_evidence']['r1_show_ip_interface_brief'] = eos.show(R1_IP, 'show ip interface brief')[-500:]
    s['device_evidence']['r2_show_ip_interface_brief'] = eos.show(R2_IP, 'show ip interface brief')[-500:]
    s['observed']['ping_ok'] = bool(re.search(r'3 received', out))
    if not s['observed']['ping_ok']:
        rec.fail(s, 'ping across the link failed', page)
    rec.write()
    browser.close()


def step_5(rec, pw, st):
    s = rec.new_step(5, 'Your own repository on GitHub')
    rc, out = run_cmd(['gh', 'repo', 'view', GH_REPO, '--json', 'visibility,defaultBranchRef,createdAt,url'])
    s['remote_evidence']['gh_repo_view'] = out.strip()
    s['notes'].append('The repository was created before the replay with: gh repo create '
                      f'{GH_REPO} --private --add-readme (the guide tells the student to do it in the browser or with that command).')
    t = tree()
    s['remote_evidence']['tree_before_first_save'] = sorted(p for p, v in t.items() if v['type'] == 'blob')
    if rc != 0 or '"PRIVATE"' not in out:
        rec.fail(s, f'repository {GH_REPO} is not private or not found: {out}')
    rec.write()


def step_6(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(6, 'Connect the repository; the first save')
    open_lab(page, st['lab_id'], 'topology')
    s['observed']['chip_before'] = chip(page)
    t0 = qs_ui.connect_and_save(rec, page, s, REPO_URL, LAB_NAME, label='connect')
    rec.shoot_full(page, s, 'first-save-panel')
    qs_ui.see_changes(rec, page, s, 'see-changes', upload=True)
    open_chip(page)
    s['observed']['panel_after_upload'] = page.locator('#save-panel').inner_text()
    s['observed']['chip_after_upload'] = chip(page)
    rec.shoot_full(page, s, 'saved-panel')
    t = tree()
    want = [f'{LAB_NAME}/latest/{n}' for n in ('manifest.json', f'{LAB_NAME}.clab.yml', f'{LAB_NAME}.clab.yml.annotations.json',
                                              'r1.cfg', 'r1.eoscfg', 'r2.cfg', 'r2.eoscfg')]
    s['remote_evidence']['first_save_files'] = {p: (p in t) for p in want}
    s['remote_evidence']['tree'] = sorted(p for p, v in t.items() if v['type'] == 'blob')
    if not all(s['remote_evidence']['first_save_files'].values()):
        rec.fail(s, 'files missing in the repository after the first upload', page)
    rec.write()
    browser.close()


def step_7(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(7, 'Check GitHub and browse the same tree in the manager')
    open_lab(page, st['lab_id'], 'topology')
    open_chip(page)
    page.get_by_role('button', name='All versions').click()
    wait_text(page, '#save-drawer', r'Browse the repository')
    settle(page, 1200)
    s['observed']['all_versions'] = page.locator('#save-drawer').inner_text()
    rec.shoot_full(page, s, 'all-versions')
    page.get_by_role('button', name='Browse the repository…').click()
    page.wait_for_timeout(3000)
    s['observed']['browse_text'] = qs_lib.StepRecorder.scrub(page.locator('#save-drawer').inner_text())[:2500]
    settle(page, 1200)
    rec.shoot_full(page, s, 'remote-tree')
    rec.shoot_element(page.locator('#save-drawer'), s, 'remote-tree', label='Browse the repository')
    t = tree()
    s['remote_evidence']['tree'] = sorted(p for p, v in t.items() if v['type'] == 'blob')
    rec.write()
    browser.close()


def step_8(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(8, 'Change, save, and checkpoint again')
    open_lab(page, st['lab_id'], 'devices')
    term = open_cli(context, page, R2)
    cmds = ['enable', 'configure terminal', 'interface Loopback0', 'description r2 loopback', 'ip address 10.255.0.2/32',
            'end', 'write memory']
    type_lines(term, cmds)
    s['actions'].append('r2 CLI: ' + '; '.join(cmds))
    term.close()
    brief = eos.show(R2_IP, 'show ip interface brief')
    s['device_evidence']['r2_show_ip_interface_brief'] = brief[-500:]
    s['observed']['r2_loopback_present'] = 'Loopback0' in brief and '10.255.0.2' in brief
    page.click('#tab-topology')
    t0 = qs_ui.do_save(rec, page, s, 'save2')
    qs_ui.upload_from_panel(page, s, 'save2', t0)
    open_chip(page)
    page.wait_for_selector('#save-name', timeout=20000)
    s['observed']['name_before'] = page.locator('#save-name').input_value()
    page.fill('#save-name', 'link-up')
    page.keyboard.press('Enter')
    page.wait_for_timeout(2000)
    rec.shoot_full(page, s, 'name-and-keep')
    page.click('#save-keep')
    wait_text(page, '#save-panel', r'Checkpoint link-up kept', timeout=120)
    settle(page, 1200)
    s['observed']['checkpoint_panel'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'checkpoint-kept')
    page.locator('#save-panel').get_by_role('button', name='Upload', exact=True).click()
    wait_text(page, '#save-chip-text', r'^Saved', timeout=180)
    settle(page, 1500)
    s['observed']['chip_after_checkpoint'] = chip(page)
    open_chip(page)
    page.get_by_role('button', name='All versions').click()
    wait_text(page, '#save-drawer', r'CHECKPOINTS')
    settle(page, 1500)
    s['observed']['all_versions'] = page.locator('#save-drawer').inner_text()
    rec.shoot_full(page, s, 'all-versions')
    rec.shoot_element(page.locator('#save-drawer'), s, 'all-versions', label='All versions')
    page.click('#save-drawer-close')
    t = tree()
    latest_r2 = blob(f'{LAB_NAME}/latest/r2.cfg')
    cp_r2 = blob(f'{LAB_NAME}/checkpoints/link-up/r2.cfg')
    nested = [p for p in t if '/latest/latest' in p]
    s['remote_evidence'] = {'latest_r2_has_loopback0': 'Loopback0' in latest_r2,
                            'checkpoint_r2_has_loopback0': 'Loopback0' in cp_r2,
                            'checkpoint_files': sorted(p for p in t if p.startswith(f'{LAB_NAME}/checkpoints/')),
                            'no_nested_latest_latest': nested == []}
    st['own_save_name'] = s['observed'].get('save2_panel', '')
    if 'Loopback0' not in latest_r2 or nested:
        rec.fail(s, 'remote files do not show the expected contents', page)
    rec.write()
    browser.close()


def step_9(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(9, 'Prove it: destroy, remove, rebuild from Git')
    open_lab(page, st['lab_id'], 'topology')
    wait_idle()
    page.click('#lab-actions-button')
    page.wait_for_selector('#lab-actions-menu:not([hidden])', timeout=10000)
    page.click('#menu-destroy')
    page.wait_for_selector('#operation-review', state='visible', timeout=20000)
    settle(page, 1000)
    s['observed']['destroy_review'] = page.locator('#operation-review').inner_text()[:1500]
    rec.shoot_full(page, s, 'destroy-review')
    rec.shoot_element(page.locator('#operation-review'), s, 'destroy-review', label='Destroy my-first-lab?')
    page.click('#op-confirm')
    wait_text(page, '#lab-state', r'Stopped|Not running|Not deployed', timeout=240)
    s['observed']['lab_state_after_destroy'] = page.locator('#lab-state').inner_text()
    settle(page, 1500)
    rec.shoot_full(page, s, 'destroyed')
    page.click('#lab-actions-button')
    page.click('#menu-remove-lab')
    page.wait_for_selector('#remove-lab-dialog', state='visible', timeout=15000)
    settle(page, 1000)
    s['observed']['remove_review'] = page.locator('#remove-lab-dialog').inner_text()[:1200]
    page.uncheck('#remove-lab-exclude')
    rec.shoot_full(page, s, 'remove-review')
    rec.shoot_element(page.locator('#remove-lab-dialog'), s, 'remove-review', label='Remove from this manager')
    with page.expect_navigation(timeout=30000):
        page.click('#remove-lab-form button[type="submit"]')
    settle(page, 1500)
    rc, out = run_cmd(['docker', 'ps', '-a', '--filter', f'name=clab-{LAB_NAME}-', '--format', '{{.Names}}'])
    s['observed']['containers_after_remove'] = out.strip().splitlines()
    # the original folder (from step 3) stays on the VM: nothing in the manager deletes a topology file
    s['observed']['original_folder_still_on_vm'] = pathlib.Path(TOPOLOGY_PATH).exists()
    # authoring only (not a guide step): put the original folder aside so the file picker cannot offer it by accident
    aside = f'{PROJECTS_ROOT}/../projects-aside-qs/{LAB_NAME}.original'
    run_cmd(['sudo', 'mkdir', '-p', str(pathlib.Path(aside).parent)])
    rc_mv, out_mv = run_cmd(['sudo', 'mv', LAB_VM_FOLDER, aside]) if pathlib.Path(LAB_VM_FOLDER).exists() else (0, 'already aside')
    s['notes'].append(f'(authoring only) sudo mv {LAB_VM_FOLDER} {aside}: rc={rc_mv}; the guide tells the student to read the path in the Topology file dialog instead')
    transcript = []
    if not pathlib.Path(CLONE_ON_VM).exists():
        rc, out = run_cmd(['git', 'clone', REPO_URL, CLONE_ON_VM])
        transcript.append((f'git clone {REPO_URL} {CLONE_ON_VM}', out))
        if rc != 0:
            rec.fail(s, f'git clone failed: {out}', page)
    else:
        transcript.append((f'git clone {REPO_URL} {CLONE_ON_VM}', '# already cloned in an earlier run'))
    rc, out = run_cmd(['ls', '-R', f'{CLONE_ON_VM}/{LAB_NAME}'])
    transcript.append((f'ls -R {CLONE_ON_VM}/{LAB_NAME}', out))
    s['remote_evidence']['clone_transcript'] = transcript
    render_transcript(page, 'Lab VM terminal (rendered transcript, not a live terminal)', transcript, 'b9-terminal-clone.png')
    s['screenshots'].append({'file': 'b9-terminal-clone.png', 'element': 'rendered transcript', 'callouts': []})
    page.goto(BASE + '/#/')
    page.wait_for_selector('#home-deploy', timeout=30000)
    settle(page, 1000)
    page.click('#home-deploy')
    page.wait_for_selector('#op-file-tree', state='visible', timeout=20000)
    root = open_tree_folder(page.locator('#op-file-tree'), PROJECTS_ROOT)
    c1 = open_tree_folder(root, REPO_NAME)
    c2 = open_tree_folder(c1, LAB_NAME)
    c3 = open_tree_folder(c2, 'latest')
    fbtn = c3.locator('> button.op-tree-file', has_text=f'{LAB_NAME}.clab.yml').first
    fbtn.wait_for(state='visible', timeout=15000)
    settle(page, 500)
    rec.shoot_element(page.locator('#op-browser'), s, 'file-picker', label='Deploy a new lab (clone)')
    fbtn.click()
    page.wait_for_selector('#op-editor', state='visible', timeout=20000)
    settle(page, 1000)
    path_field = page.locator('#op-edit-path').input_value()
    s['observed']['cloned_topology_path'] = path_field
    rec.shoot_full(page, s, 'redeploy-topology-file')
    rec.shoot_element(page.locator('#op-editor'), s, 'redeploy-topology-file', label='Topology file (clone)')
    if path_field != CLONED_TOPOLOGY:
        rec.fail(s, f'File location is {path_field!r}, expected {CLONED_TOPOLOGY!r}', page)
    wait_idle()
    page.click('#op-deploy-project')
    page.wait_for_selector('#operation-review', state='visible', timeout=20000)
    settle(page, 800)
    t_confirm = time.time()
    page.click('#op-confirm')
    for _ in range(80):
        if 'lab=' in page.evaluate('() => location.hash'):
            break
        page.wait_for_timeout(500)
    m = re.search(r'lab=([0-9a-f]+)', page.evaluate('() => location.hash'))
    if not m:
        rec.fail(s, 'the rebuilt lab did not open', page)
    st['lab_id_2'] = m.group(1)
    lab = next((l for l in api(page, 'GET', '/api/state')['body']['labs'] if l['id'] == st['lab_id_2']), {})
    s['observed']['vm_project_path'] = lab.get('vm_project_path')
    open_lab(page, st['lab_id_2'], 'devices')
    pills, secs = qs_ui.wait_devices_ready(page, 2)
    s['observed']['redeploy_to_ready_seconds'] = round(time.time() - t_confirm, 1)
    if secs is None:
        rec.fail(s, f'rebuilt devices not Ready: {pills}', page)
    page.click('#tab-topology')
    settle(page, 2000)
    rec.shoot_full(page, s, 'rebuilt-topology')
    # the rebuilt devices are in their fresh state: nothing is addressed yet
    s['device_evidence']['r1_ping_fresh'] = eos.show(R1_IP, 'ping 10.0.0.2 repeat 2')[-400:]
    s['observed']['ping_works_before_load'] = bool(re.search(r'2 received', s['device_evidence']['r1_ping_fresh']))
    # what the chip and Load offer for a lab that has no saves of its own yet
    open_chip(page)
    s['observed']['chip_rebuilt'] = page.locator('#save-panel').inner_text()
    page.keyboard.press('Escape')
    wait_idle()
    page.click('#load-button')
    wait_text(page, '#load-panel', r'Load a saved state|There is nothing to load', timeout=30)
    page.wait_for_timeout(2500)
    s['observed']['load_list_rebuilt'] = page.locator('#load-panel').inner_text()
    rec.shoot_full(page, s, 'rebuilt-load-list')
    page.keyboard.press('Escape')
    # connect the repository again: Choose another place > repository list > the folder my-first-lab
    wait_idle()
    open_chip(page)
    page.get_by_role('button', name='Choose another place').click()
    page.wait_for_selector('#folder-repo', timeout=20000)
    page.select_option('#folder-repo', label=REPO_NAME)
    wait_text(page, '#save-drawer', r'This folder holds the state', timeout=60)
    settle(page, 1200)
    s['observed']['reconnect_question'] = page.locator('#save-drawer').inner_text()
    rec.shoot_full(page, s, 'reconnect-question')
    rec.shoot_element(page.locator('#save-drawer'), s, 'reconnect-question', label='This folder holds the state')
    t0 = time.time()
    page.get_by_role('button', name='Replace it').click()
    wait_text(page, '#save-panel', r'Not uploaded yet', timeout=240)
    settle(page, 1200)
    s['observed']['reconnect_seconds'] = round(time.time() - t0, 1)
    s['observed']['reconnect_sentence'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'reconnect-saved')
    page.get_by_role('button', name='Not now').click()
    page.wait_for_timeout(1500)
    s['observed']['chip_after_not_now'] = chip(page)
    # Load the checkpoint kept in Git
    name = qs_ui.do_load(rec, page, s, 'link-up', 'loadcp')
    s['observed']['loaded'] = name
    ok = bool(re.search(r'3 received', eos.show(R1_IP, 'ping 10.0.0.2 repeat 3')))
    b2 = eos.show(R2_IP, 'show ip interface brief')
    s['device_evidence']['r2_show_ip_interface_brief'] = b2[-500:]
    s['observed']['ping_ok_after_load'] = ok
    s['observed']['r2_loopback_back'] = 'Loopback0' in b2 and '10.255.0.2' in b2
    wait_idle()
    open_chip(page)
    settle(page, 1200)
    s['observed']['chip_panel_after_load'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'link-up-loaded')
    # save what runs now and upload: the upload sentence names every save it sends
    page.keyboard.press('Escape')
    t1 = qs_ui.do_save(rec, page, s, 'final')
    qs_ui.upload_from_panel(page, s, 'final', t1)
    t = tree()
    latest_r2 = blob(f'{LAB_NAME}/latest/r2.cfg')
    latest_r1 = blob(f'{LAB_NAME}/latest/r1.cfg')
    s['remote_evidence']['latest_r2_has_loopback0_after_rebuild'] = 'Loopback0' in latest_r2
    s['remote_evidence']['latest_r1_has_10_0_0_1_after_rebuild'] = '10.0.0.1' in latest_r1
    if not ok or not s['observed']['r2_loopback_back'] or 'Loopback0' not in latest_r2:
        rec.fail(s, 'the rebuilt lab did not come back from Git', page)
    rec.write()
    browser.close()


STEPS = {1: step_1, 2: step_2, 3: step_3, 4: step_4, 5: step_5, 6: step_6, 7: step_7, 8: step_8, 9: step_9}


def parse_range(text):
    if not text:
        return sorted(STEPS)
    a, _, b = text.partition('-')
    lo, hi = int(a), int(b or a)
    return [n for n in sorted(STEPS) if lo <= n <= hi]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--steps', default='')
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright
    wanted = parse_range(args.steps)
    st = load_state()
    rec = qs_lib.StepRecorder(SCREEN_DIR, EVIDENCE_JSON, EVIDENCE_MD, 'Scenario B: build your own lab and keep it in Git', prefix='b')
    if args.steps and EVIDENCE_JSON.exists():
        old = json.loads(EVIDENCE_JSON.read_text())
        rec.steps = [x for x in old.get('steps', []) if x['step'] not in wanted]
        rec.started_utc = old.get('started_utc', rec.started_utc)
    with sync_playwright() as pw:
        for n in wanted:
            t0 = time.time()
            print(f'--- step B{n}', flush=True)
            STEPS[n](rec, pw, st)
            rec.steps[-1]['elapsed_seconds'] = round(time.time() - t0, 1)
            rec.steps.sort(key=lambda x: x['step'])
            rec.write()
            save_state(st)
    ok = all(x['result'] == 'PASS' for x in rec.steps)
    print('Scenario B: all recorded steps PASS' if ok else 'Scenario B: a step failed')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
