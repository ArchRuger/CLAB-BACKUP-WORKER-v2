#!/usr/bin/env python3
"""Student quick-start Scenario A ("use an instructor's lab"), replayed on the live Containerlab Node
Manager (release 1.31.6 UI: the lab header's save chip, Save, the chip panel and drawers, Load).

Every step drives the real page the way a student would. Device facts are read independently over direct SSH
(eos.py) and remote facts with the already-authenticated `gh`. Evidence goes to evidence/scenario-a.{json,md}
and the raw screenshots to screenshots/raw/ (a<step>-<name>-full.png: the whole page; -el.png: one dialog or
panel). `tools/compose_screenshots.py` + `screenshots/spec.json` turn them into the figures.

    /home/archtop/pw-venv/bin/python docs/student-quick-start/tools/capture_scenario_a.py            # all steps
    /home/archtop/pw-venv/bin/python docs/student-quick-start/tools/capture_scenario_a.py --steps 5-8 # a range

Steps share state (the lab id, timings) through build/state-a.json, so a range can resume a run. Reset the
starting state first with tools/reset_scenario_a.sh. Needs the manager on http://127.0.0.1:8081, the instructor
package staged under /srv/containerlab-node-manager/projects/link-basics/ and the student repository
(default ArchRuger/campaign2-netlab-course-student, private, made from the pruger-dev/netlab-course template).
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
ROOT = HERE.parent  # docs/student-quick-start
sys.path.insert(0, str(HERE))
import qs_lib  # noqa: E402
import eos  # noqa: E402
from qs_lib import BASE, api, settle, wait_idle, wait_text  # noqa: E402

SCREEN_DIR = ROOT / 'screenshots' / 'raw'
EVIDENCE_JSON = ROOT / 'evidence' / 'scenario-a.json'
EVIDENCE_MD = ROOT / 'evidence' / 'scenario-a.md'
STATE_FILE = ROOT / 'build' / 'state-a.json'

LAB_NAME = 'link-basics'
TOPOLOGY_PATH = '/srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml'
R1_NAME = 'clab-link-basics-r1'
R2_NAME = 'clab-link-basics-r2'
R1_IP = '172.20.20.11'
R2_IP = '172.20.20.12'
GH_ACCOUNT = os.environ.get('QS_GH_ACCOUNT', 'ArchRuger')
STUDENT_REPO = os.environ.get('QS_STUDENT_REPO', 'campaign2-netlab-course-student')
REPO_URL = f'https://github.com/{GH_ACCOUNT}/{STUDENT_REPO}.git'
GH_REPO = f'{GH_ACCOUNT}/{STUDENT_REPO}'
SAVE_FOLDER = 'link-basics/work'


def gh_tree():
    """Full recursive tree of origin/main, read-only, via the already-authenticated gh CLI."""
    out = subprocess.run(['gh', 'api', f'repos/{GH_REPO}/git/trees/main?recursive=1'],
                         capture_output=True, text=True, timeout=60, check=True).stdout
    return {t['path']: t for t in json.loads(out).get('tree', [])}


def gh_blob_text(path):
    return subprocess.run(['gh', 'api', f'repos/{GH_REPO}/contents/{path}', '-H', 'Accept: application/vnd.github.raw'],
                          capture_output=True, text=True, timeout=60, check=True).stdout


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=1) + '\n')


def open_lab(page, lab_id, view='topology'):
    page.goto(f'{BASE}/#lab={lab_id}&view={view}')
    page.wait_for_selector('#lab-content:not([hidden])', timeout=30000)
    page.wait_for_selector('#save-chip-text', timeout=15000)
    settle(page, 800)


def open_cli(context, page, container):
    """Devices tab > Open CLI of one device; returns the terminal page once it reads Connected."""
    page.click('#tab-devices')
    button = page.locator(f'#device-list button[data-terminal="{container}"]')
    button.wait_for(state='visible', timeout=15000)
    with context.expect_page() as info:
        button.click()
    term = info.value
    term.wait_for_selector('#terminal', timeout=20000)
    wait_text(term, '#status', r'^Connected$', timeout=40)
    settle(term, 600)
    term.click('#terminal')
    return term


def type_lines(term, lines, pause=900):
    for line in lines:
        term.keyboard.type(line)
        term.keyboard.press('Enter')
        term.wait_for_timeout(pause)


def wait_load_done(page, pattern, timeout=300):
    """The chip first reads Loading… (or the old state for a moment): wait for Loading…, then for the end."""
    try:
        wait_text(page, '#save-chip-text', r'^(Loading|Checking)', timeout=30, interval=0.3)
    except TimeoutError:
        pass
    return wait_text(page, '#save-chip-text', pattern, timeout=timeout)


def open_chip(page):
    """Open the chip panel unless it is already open (it opens by itself after a save or a load)."""
    if not page.locator('#save-panel').is_visible():
        page.click('#save-chip')
    page.wait_for_selector('#save-panel', state='visible', timeout=10000)


def chip(page):
    return page.locator('#save-chip-text').inner_text().strip()


# ----------------------------------------------------------------------------------------------------
def step_1(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(1, 'Home: Deploy and Build boxes')
    page.goto(BASE + '/#/')
    page.wait_for_selector('#home-deploy', timeout=30000)
    page.wait_for_selector('#home-labs', timeout=30000)
    settle(page, 1500)
    s['actions'].append('Open the manager address')
    s['observed']['home_title'] = page.locator('#home-title').inner_text()
    s['observed']['deploy_box'] = page.locator('#home-start-deploy').inner_text()
    s['observed']['build_box'] = page.locator('#home-start-build').inner_text()
    s['observed']['lab_cards_on_this_manager'] = page.locator('article.lab-card h3').all_inner_texts()
    s['notes'].append('The development manager already lists other labs; the figure is cropped to the Deploy and '
                      'Build boxes. A new installation reads "No labs yet".')
    rec.shoot_full(page, s, 'home')
    rec.write()
    browser.close()


def step_2(rec, pw, st):
    waited = wait_idle()
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(2, 'Deploy link-basics from the lab VM')
    s['notes'].append(f'waited {waited}s for other work on the shared manager to finish')
    page.goto(BASE + '/#/')
    page.wait_for_selector('#home-deploy', timeout=30000)
    settle(page, 1000)
    page.click('#home-deploy')
    page.wait_for_selector('#op-file-tree', state='visible', timeout=20000)
    s['actions'].append('Click "Choose a file on the lab VM…"')
    root = page.locator('#op-file-tree summary', has_text='/srv/containerlab-node-manager/projects').first
    root.click()
    folder = page.locator('#op-file-tree summary', has_text='link-basics').first
    folder.wait_for(state='visible', timeout=15000)
    folder.click()
    file_button = page.locator('button.op-tree-file', has_text='link-basics.clab.yml').first
    file_button.wait_for(state='visible', timeout=15000)
    s['actions'].append('Open /srv/containerlab-node-manager/projects, then link-basics')
    settle(page, 400)
    rec.shoot_element(page.locator('#op-browser'), s, 'file-picker', label='Deploy a new lab (folders)')
    file_button.click()
    page.wait_for_selector('#op-editor', state='visible', timeout=15000)
    settle(page, 800)
    s['actions'].append('Click ◇ link-basics.clab.yml')
    s['observed']['topology_path_field'] = page.locator('#op-edit-path').input_value()
    s['observed']['editor_buttons'] = page.locator('#op-editor button').all_inner_texts()
    s['observed']['editor_title'] = page.locator('#op-editor h2').first.inner_text()
    if s['observed']['topology_path_field'] != TOPOLOGY_PATH:
        rec.fail(s, f"unexpected topology path {s['observed']['topology_path_field']!r}", page)
    rec.shoot_element(page.locator('#op-editor'), s, 'topology-file', label='Topology file')
    page.click('#op-deploy-project')
    try:
        page.wait_for_selector('#operation-review', state='visible', timeout=20000)
    except Exception:
        page.screenshot(path=str(ROOT / 'build' / 'a2-fail.png'))
        raise
    settle(page, 800)
    s['actions'].append('Click "Deploy lab"')
    s['observed']['review_title'] = page.locator('#operation-review h2').first.inner_text()
    s['observed']['review_text'] = page.locator('#operation-review').inner_text()[:1200]
    rec.shoot_element(page.locator('#operation-review'), s, 'start-review', label=s['observed']['review_title'])
    t_confirm = time.time()
    s['observed']['confirm_button'] = page.locator('#op-confirm').inner_text()
    page.click('#op-confirm')
    s['actions'].append('Click "Start lab"')
    for _ in range(60):
        h = page.evaluate('() => location.hash')
        if 'lab=' in h:
            break
        page.wait_for_timeout(500)
    m = re.search(r'lab=([0-9a-f]+)', page.evaluate('() => location.hash'))
    if not m:
        # the page may stay on Home with the operation output; find the lab through the API
        state = api(page, 'GET', '/api/state')['body']
        lab = next((l for l in state['labs'] if l['name'] == LAB_NAME), None)
        lab_id = lab['id'] if lab else None
    else:
        lab_id = m.group(1)
    if not lab_id:
        rec.fail(s, 'link-basics did not appear in My labs after Start lab', page)
    st['lab_id'] = lab_id
    st['deploy_confirm_time'] = t_confirm
    s['observed']['lab_id'] = lab_id
    s['observed']['hash_after_confirm'] = page.evaluate('() => location.hash')
    rec.write()
    save_state(st)
    settle(page, 1500)
    browser.close()


def step_3(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(3, 'Starting, then Ready')
    open_lab(page, st['lab_id'], 'devices')
    s['observed']['header_state_starting'] = page.locator('#lab-state').inner_text()
    s['observed']['header_ready_starting'] = page.locator('#lab-ready').inner_text()
    s['observed']['chip_starting'] = chip(page)
    s['observed']['device_pills_starting'] = page.locator('#device-list li.device-row .pill').all_inner_texts()
    rec.shoot_full(page, s, 'devices-starting')
    deadline = time.time() + 420
    pills = []
    while time.time() < deadline:
        page.reload()
        page.wait_for_selector('#device-list li.device-row', timeout=30000)
        settle(page, 500)
        pills = [p.strip() for p in page.locator('#device-list li.device-row .pill').all_inner_texts()]
        if len(pills) == 2 and all(p == 'Ready' for p in pills):
            break
        page.wait_for_timeout(8000)
    t_ready = time.time()
    s['observed']['deploy_to_ready_seconds'] = round(t_ready - st.get('deploy_confirm_time', t_ready), 1)
    if not (len(pills) == 2 and all(p == 'Ready' for p in pills)):
        rec.fail(s, f'devices not Ready in time: {pills}', page)
    settle(page, 800)
    s['observed']['header_state_ready'] = page.locator('#lab-state').inner_text()
    s['observed']['header_ready_ready'] = page.locator('#lab-ready').inner_text()
    s['observed']['chip_ready'] = chip(page)
    rec.shoot_full(page, s, 'devices-ready')
    rec.write()
    browser.close()


def step_4(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(4, 'Look around from the command line')
    open_lab(page, st['lab_id'], 'topology')
    s['observed']['topology_toolbar'] = page.locator('#topology-view button').all_inner_texts()[:12]
    rec.shoot_full(page, s, 'topology')
    term = open_cli(context, page, R1_NAME)
    s['actions'].append('Devices tab > Open CLI next to r1; wait for Connected')
    type_lines(term, ['show version', 'show interfaces status', 'show ip interface brief'], pause=1500)
    rec.shoot_full(term, s, 'r1-terminal')
    rec.shoot_element(term.locator('#terminal'), s, 'r1-terminal', label='r1 CLI')
    term.close()
    status = eos.show(R1_IP, 'show interfaces status')
    brief = eos.show(R1_IP, 'show ip interface brief')
    s['device_evidence']['r1_show_interfaces_status'] = status[-700:]
    s['device_evidence']['r1_show_ip_interface_brief'] = brief[-500:]
    s['observed']['et1_connected'] = bool(re.search(r'Et1\s+.*connected', status))
    if not s['observed']['et1_connected']:
        rec.fail(s, 'Et1 is not connected on r1', page)
    rec.write()
    browser.close()


def step_5(rec, pw, st):
    """Connect the repository by URL; the first save is made and uploaded in the same step."""
    wait_idle()
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(5, 'Connect your repository (the first save)')
    open_lab(page, st['lab_id'], 'topology')
    s['observed']['chip_before'] = chip(page)
    open_chip(page)
    wait_text(page, '#save-panel', r'Not saved yet')
    page.wait_for_selector('#save-panel button:has-text("Connect by URL…")', timeout=20000)
    settle(page, 800)
    s['observed']['first_save_panel'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'chip-first-save')
    s['actions'].append('Click the chip (Not saved yet), then Connect by URL…')
    page.get_by_role('button', name='Connect by URL…').click()
    page.wait_for_selector('#folder-url', timeout=20000)
    page.fill('#folder-url', REPO_URL)
    page.fill('#folder-path', SAVE_FOLDER)
    wait_text(page, '#save-drawer', r'Saves go to')
    settle(page, 800)
    s['observed']['drawer_text'] = page.locator('#save-drawer').inner_text()
    rec.shoot_full(page, s, 'connect-drawer')
    rec.shoot_element(page.locator('#save-drawer'), s, 'connect-drawer', label='Where should link-basics save?')
    t0 = time.time()
    page.get_by_role('button', name='Save here').click()
    s['actions'].append('Click Save here')
    # The place is connected and the lab is saved in one click. If another worker holds the manager's guard at
    # that moment the lab is connected but the save waits ("Your first save goes to ...": press Save again).
    deadline = time.time() + 240
    path = None
    while time.time() < deadline:
        try:
            drawer_open = page.evaluate("() => document.getElementById('save-drawer').open")
            if not drawer_open and not page.locator('#save-panel').is_visible() and time.time() - t0 > 6:
                page.click('#save-chip')
                page.wait_for_timeout(800)
            text = page.locator('#save-panel').inner_text(timeout=2000) if page.locator('#save-panel').is_visible() else ''
        except Exception:
            text = ''
        if 'Not uploaded yet' in text:
            path = 'saved at once'
            break
        if 'Your first save goes to' in text and page.locator('#git-save-progress').is_enabled():
            wait_idle()
            page.click('#git-save-progress')
            path = 'connected, then Save pressed (the guard was busy at the first click)'
            wait_text(page, '#save-panel', r'Not uploaded yet', timeout=240)
            break
        page.wait_for_timeout(1000)
    if path is None:
        rec.fail(s, 'the first save never reached "Not uploaded yet"', page)
    s['observed']['connect_path'] = path
    s['observed']['seconds_to_first_save_on_vm'] = round(time.time() - t0, 1)
    settle(page, 800)
    s['observed']['first_save_sentence'] = page.locator('#save-panel').inner_text()
    s['observed']['chip_after_connect'] = chip(page)
    rec.shoot_full(page, s, 'first-save-panel')
    # View what the save holds, then come back and upload
    page.get_by_role('button', name='See changes').click()
    wait_text(page, '#save-drawer', r'What changed')
    settle(page, 1000)
    s['observed']['see_changes_files'] = re.findall(r'^(?:Topology file|Map|r\d)\s.*$', page.locator('#save-drawer').inner_text(), re.M)
    rec.shoot_full(page, s, 'see-changes')
    rec.shoot_element(page.locator('#save-drawer'), s, 'see-changes', label='What changed (first save)')
    page.locator('#save-drawer-actions').get_by_role('button', name='Upload', exact=True).click()
    s['actions'].append('See changes > Upload')
    wait_text(page, '#save-chip-text', r'^Saved', timeout=180)
    s['observed']['seconds_to_uploaded'] = round(time.time() - t0, 1)
    settle(page, 1500)
    s['observed']['chip_after_upload'] = chip(page)
    page.keyboard.press('Escape')
    open_chip(page)
    settle(page, 1200)
    s['observed']['panel_after_upload'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'saved-panel')
    tree = gh_tree()
    want = [f'{SAVE_FOLDER}/latest/{n}' for n in ('manifest.json', 'link-basics.clab.yml', 'link-basics.clab.yml.annotations.json',
                                                  'r1.cfg', 'r1.eoscfg', 'r2.cfg', 'r2.eoscfg')]
    s['remote_evidence']['first_save_files'] = {p: (p in tree) for p in want}
    if not all(s['remote_evidence']['first_save_files'].values()):
        rec.fail(s, 'files missing in the repository after the first upload', page)
    st['first_save_done'] = True
    rec.write()
    browser.close()


def read_load_rows(page):
    return [t.replace('\n', ' | ') for t in page.locator('#load-panel-body li, #load-panel-body button.load-row').all_inner_texts()]


def do_load(rec, page, s, name, label, first_own_save=False):
    """Load > row > confirmation > red Load; waits for the chip to say Running <name>. Returns the name loaded.
    first_own_save=True takes the first row of "Your saves" (the newest own save) whatever its name."""
    wait_idle()
    page.click('#load-button')
    wait_text(page, '#load-panel', r'Load a saved state')
    page.wait_for_selector('#load-panel [data-load-row]', timeout=20000)
    settle(page, 1000)
    s['observed'][f'{label}_list'] = page.locator('#load-panel').inner_text()
    rec.shoot_full(page, s, f'{label}-list')
    if first_own_save:
        row = page.locator('#load-panel [data-load-row]').first
    else:
        row = page.locator('#load-panel [data-load-row]').filter(has=page.get_by_text(name, exact=True)).first
    row.click()
    text = wait_text(page, '#load-panel', r'Load .+\?', timeout=90)
    loaded_name = re.search(r'Load (.+)\?', text).group(1)
    page.wait_for_selector('#load-run', state='visible', timeout=30000)
    settle(page, 1000)
    s['observed'][f'{label}_confirmation'] = page.locator('#load-panel').inner_text()
    rec.shoot_full(page, s, f'{label}-confirm')
    t0 = time.time()
    page.click('#load-run')
    wait_load_done(page, rf'^(Running {re.escape(loaded_name)}|Loaded \d+ of \d+)')
    s['observed'][f'{label}_seconds'] = round(time.time() - t0, 1)
    settle(page, 1500)
    s['observed'][f'{label}_chip'] = chip(page)
    return loaded_name


def step_6(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(6, 'Load the Start state')
    open_lab(page, st['lab_id'], 'topology')
    s['actions'].append('Load > Start > red Load')
    do_load(rec, page, s, 'Start', 'start')
    wait_idle()
    open_chip(page)
    settle(page, 1200)
    s['observed']['chip_panel_after_load'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'start-loaded')
    ping = eos.show(R1_IP, 'ping 10.0.0.2 repeat 3')
    brief1 = eos.show(R1_IP, 'show ip interface brief')
    brief2 = eos.show(R2_IP, 'show ip interface brief')
    s['device_evidence']['r1_ping'] = ping[-500:]
    s['device_evidence']['r1_show_ip_interface_brief'] = brief1[-500:]
    s['device_evidence']['r2_show_ip_interface_brief'] = brief2[-500:]
    s['observed']['ping_ok'] = bool(re.search(r'3 received', ping))
    if not s['observed']['ping_ok'] or s['observed']['start_chip'] != 'Running Start':
        rec.fail(s, 'Start did not load cleanly', page)
    rec.write()
    browser.close()


def step_7(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(7, 'Make a change on r1')
    open_lab(page, st['lab_id'], 'topology')
    term = open_cli(context, page, R1_NAME)
    cmds = ['enable', 'configure terminal', 'interface Loopback0', 'description r1 loopback',
            'ip address 10.255.0.1/32', 'end', 'write memory', 'show ip interface brief']
    s['actions'] = [f'r1 CLI: {c}' for c in cmds]
    type_lines(term, cmds)
    term.wait_for_timeout(1200)
    rec.shoot_full(term, s, 'r1-loopback')
    rec.shoot_element(term.locator('#terminal'), s, 'r1-loopback', label='r1 CLI after the change')
    term.close()
    brief = eos.show(R1_IP, 'show ip interface brief')
    s['device_evidence']['r1_show_ip_interface_brief'] = brief[-500:]
    s['observed']['loopback0_present'] = 'Loopback0' in brief and '10.255.0.1' in brief
    if not s['observed']['loopback0_present']:
        rec.fail(s, 'Loopback0 not present on r1', page)
    rec.write()
    browser.close()


def do_save(rec, page, s, label, upload=True):
    """Save in the lab header; the chip panel opens with the one-sentence summary. Optionally Upload."""
    wait_idle()
    t0 = time.time()
    page.click('#git-save-progress')
    wait_text(page, '#save-panel', r'Not uploaded yet|Nothing changed', timeout=240)
    s['observed'][f'{label}_seconds_to_commit'] = round(time.time() - t0, 1)
    settle(page, 1200)
    s['observed'][f'{label}_panel'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, f'{label}-panel')
    return t0


def upload_from_panel(page, s, label, t0):
    page.locator('#save-panel').get_by_role('button', name='Upload', exact=True).click()
    wait_text(page, '#save-chip-text', r'^Saved', timeout=180)
    s['observed'][f'{label}_seconds_to_uploaded'] = round(time.time() - t0, 1)
    settle(page, 1500)
    s['observed'][f'{label}_chip'] = chip(page)


def step_8(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(8, 'Save, look at the changes, upload')
    open_lab(page, st['lab_id'], 'topology')
    s['observed']['chip_before'] = chip(page)
    t0 = do_save(rec, page, s, 'save2')
    s['actions'].append('Save in the lab header; the chip panel opens')
    page.get_by_role('button', name='See changes').click()
    wait_text(page, '#save-drawer', r'What changed')
    settle(page, 1200)
    s['observed']['see_changes_text'] = page.locator('#save-drawer').inner_text()[:3000]
    rec.shoot_full(page, s, 'see-changes')
    rec.shoot_element(page.locator('#save-drawer'), s, 'see-changes', label='What changed (second save)')
    page.locator('#save-drawer-actions').get_by_role('button', name='Upload', exact=True).click()
    s['actions'].append('See changes > Upload')
    wait_text(page, '#save-chip-text', r'^Saved', timeout=180)
    settle(page, 1500)
    s['observed']['chip_after_upload'] = chip(page)
    page.keyboard.press('Escape')
    open_chip(page)
    settle(page, 1200)
    s['observed']['panel_after_upload'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'saved-panel')
    tree = gh_tree()
    r1 = gh_blob_text(f'{SAVE_FOLDER}/latest/r1.cfg')
    s['remote_evidence']['latest_r1_has_loopback0'] = 'Loopback0' in r1
    s['remote_evidence']['latest_folder_files'] = sorted(p for p in tree if p.startswith(f'{SAVE_FOLDER}/latest/'))
    if 'Loopback0' not in r1:
        rec.fail(s, 'latest/r1.cfg on GitHub lacks Loopback0', page)
    rec.write()
    browser.close()


def step_9(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(9, 'Checkpoint, then r2 and a second upload')
    open_lab(page, st['lab_id'], 'topology')
    wait_idle()
    open_chip(page)
    page.wait_for_selector('#save-name', timeout=20000)
    s['observed']['name_before'] = page.locator('#save-name').input_value()
    page.fill('#save-name', 'loopback-added')
    page.keyboard.press('Enter')
    page.wait_for_timeout(2000)
    s['actions'].append('Chip panel: name the save loopback-added, tick Keep as a checkpoint')
    rec.shoot_full(page, s, 'name-and-keep')
    page.click('#save-keep')
    wait_text(page, '#save-panel', r'Checkpoint loopback-added kept', timeout=120)
    settle(page, 1200)
    s['observed']['checkpoint_panel'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'checkpoint-kept')
    page.locator('#save-panel').get_by_role('button', name='Upload', exact=True).click()
    wait_text(page, '#save-chip-text', r'^Saved', timeout=180)
    settle(page, 1200)
    s['observed']['chip_after_checkpoint_upload'] = chip(page)
    page.keyboard.press('Escape')
    term = open_cli(context, page, R2_NAME)
    cmds = ['enable', 'configure terminal', 'interface Loopback0', 'description r2 loopback',
            'ip address 10.255.0.2/32', 'end', 'write memory']
    s['actions'].append('r2 CLI: ' + '; '.join(cmds))
    type_lines(term, cmds)
    term.close()
    brief = eos.show(R2_IP, 'show ip interface brief')
    s['device_evidence']['r2_show_ip_interface_brief'] = brief[-500:]
    s['observed']['r2_loopback0_present'] = 'Loopback0' in brief and '10.255.0.2' in brief
    page.click('#tab-topology')
    t0 = do_save(rec, page, s, 'save3')
    upload_from_panel(page, s, 'save3', t0)
    open_chip(page)
    settle(page, 1200)
    s['observed']['panel_after_save3'] = page.locator('#save-panel').inner_text()
    s['observed']['save3_name'] = page.locator('#save-name').input_value()
    page.keyboard.press('Escape')
    open_chip(page)
    page.get_by_role('button', name='All versions').click()
    wait_text(page, '#save-drawer', r'CHECKPOINTS')
    settle(page, 1500)
    s['observed']['all_versions'] = page.locator('#save-drawer').inner_text()
    rec.shoot_full(page, s, 'all-versions')
    rec.shoot_element(page.locator('#save-drawer'), s, 'all-versions', label='All versions')
    page.click('#save-drawer-close')
    tree = gh_tree()
    latest_r2 = gh_blob_text(f'{SAVE_FOLDER}/latest/r2.cfg')
    cp_r2 = gh_blob_text(f'{SAVE_FOLDER}/checkpoints/loopback-added/r2.cfg')
    nested = [p for p in tree if '/latest/latest' in p]
    s['remote_evidence'] = {'latest_r2_has_loopback0': 'Loopback0' in latest_r2,
                            'checkpoint_r2_lacks_loopback0': 'Loopback0' not in cp_r2,
                            'checkpoint_folder_files': sorted(p for p in tree if p.startswith(f'{SAVE_FOLDER}/checkpoints/')),
                            'no_nested_latest_latest': nested == []}
    if 'Loopback0' not in latest_r2 or 'Loopback0' in cp_r2 or nested:
        rec.fail(s, 'remote files do not show the expected latest/checkpoint contents', page)
    st['own_save_name'] = s['observed']['save3_name']
    rec.write()
    browser.close()


def ping_ok(host=R1_IP):
    out = eos.show(host, 'ping 10.0.0.2 repeat 3')
    return bool(re.search(r'3 received', out)), out


def step_10(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(10, 'Break it with Broken-01, go back two ways')
    open_lab(page, st['lab_id'], 'topology')
    # 1. Load Broken-01: the link goes down
    s['actions'].append('Load > Broken-01 > red Load')
    do_load(rec, page, s, 'Broken-01', 'broken')
    ok, out = ping_ok()
    status = eos.show(R1_IP, 'show interfaces status')
    s['device_evidence']['r1_ping_after_broken'] = out[-400:]
    s['device_evidence']['r1_show_interfaces_status_after_broken'] = status[-500:]
    s['observed']['ping_fails_after_broken'] = not ok
    s['observed']['et1_notconnect_after_broken'] = bool(re.search(r'Et1\s+.*notconnect', status))
    wait_idle()
    open_chip(page)
    settle(page, 1200)
    s['observed']['chip_panel_broken'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'broken-loaded')
    if ok or not s['observed']['et1_notconnect_after_broken']:
        rec.fail(s, 'Broken-01 did not break the link', page)
    # 2. The quick way back: Undo this load
    undo = page.locator('#save-panel').get_by_role('button', name='Undo this load')
    undo.wait_for(state='visible', timeout=20000)
    s['actions'].append('Chip panel > Undo this load > red Load')
    undo.click()
    page.wait_for_selector('#load-run', state='visible', timeout=60000)
    settle(page, 1000)
    s['observed']['undo_confirmation'] = page.locator('#load-panel').inner_text()
    rec.shoot_full(page, s, 'undo-confirm')
    t0 = time.time()
    page.click('#load-run')
    wait_load_done(page, r'^(Running|Loaded \d+ of)')
    s['observed']['undo_seconds'] = round(time.time() - t0, 1)
    settle(page, 1500)
    s['observed']['chip_after_undo'] = chip(page)
    ok3, out3 = ping_ok()
    s['observed']['ping_ok_after_undo'] = ok3
    s['device_evidence']['r1_ping_after_undo'] = out3[-400:]
    if not ok3:
        rec.fail(s, 'Undo this load did not restore the link', page)
    # 3. Break it again, then go back with the own save (works any time)
    s['actions'].append('Load > Broken-01 again')
    do_load(rec, page, s, 'Broken-01', 'broken2')
    ok4, out4 = ping_ok()
    s['observed']['ping_fails_after_broken2'] = not ok4
    s['actions'].append('Load > your newest own save > red Load')
    name = do_load(rec, page, s, '', 'recover', first_own_save=True)
    s['observed']['recovered_with'] = name
    ok2, out2 = ping_ok()
    b1 = eos.show(R1_IP, 'show ip interface brief')
    b2 = eos.show(R2_IP, 'show ip interface brief')
    s['device_evidence']['r1_ping_after_recover'] = out2[-400:]
    s['device_evidence']['r1_show_ip_interface_brief'] = b1[-500:]
    s['device_evidence']['r2_show_ip_interface_brief'] = b2[-500:]
    s['observed']['ping_ok_after_recover'] = ok2
    s['observed']['loopbacks_back'] = all(x in b1 for x in ('Loopback0', '10.255.0.1')) and all(x in b2 for x in ('Loopback0', '10.255.0.2'))
    wait_idle()
    open_chip(page)
    settle(page, 1200)
    s['observed']['chip_panel_recovered'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'recovered')
    if ok4 or not ok2 or not s['observed']['loopbacks_back']:
        rec.fail(s, 'own save did not restore the lab', page)
    # what changed since the checkpoint: All versions > loopback-added > See what's different
    page.get_by_role('button', name='All versions').click()
    wait_text(page, '#save-drawer', r'CHECKPOINTS')
    page.locator('#save-drawer').get_by_text('loopback-added').nth(1).click()
    page.get_by_role('button', name='See what’s different').click()
    page.wait_for_timeout(3000)
    s['observed']['compare_drawer_text'] = re.sub(r'sha512 \S+', 'sha512 <hash>', page.locator('#save-drawer').inner_text())[:1500]
    rec.shoot_full(page, s, 'compare')
    page.click('#save-drawer-close')
    page.wait_for_timeout(800)
    rec.write()
    browser.close()


def step_11(rec, pw, st):
    browser, context, page = qs_lib.new_context(pw)
    s = rec.new_step(11, 'Next time you open this lab')
    page.goto(BASE + '/#/')
    page.wait_for_selector('article.lab-card', timeout=30000)
    settle(page, 1500)
    card = page.locator(f'article.lab-card:has-text("{LAB_NAME}")').first
    s['observed']['home_card_text'] = card.inner_text().replace('\n', ' | ')
    rec.shoot_element(card, s, 'home-card', label='link-basics card')
    card.get_by_role('button', name='Open lab').click()
    page.wait_for_selector('#lab-content:not([hidden])', timeout=30000)
    settle(page, 2000)
    s['observed']['chip_reopened'] = chip(page)
    open_chip(page)
    settle(page, 1200)
    s['observed']['panel_reopened'] = page.locator('#save-panel').inner_text()
    rec.shoot_full(page, s, 'reopened-panel')
    page.keyboard.press('Escape')
    page.click('#load-button')
    page.wait_for_selector('#load-panel [data-load-row]', timeout=20000)
    settle(page, 1000)
    s['observed']['load_list_reopened'] = page.locator('#load-panel').inner_text()
    rec.shoot_full(page, s, 'load-list')
    page.keyboard.press('Escape')
    page.click('#lab-actions-button')
    page.wait_for_selector('#lab-actions-menu:not([hidden])', timeout=10000)
    page.click('#lab-actions-advanced-toggle')
    settle(page, 500)
    menu = page.locator('#lab-actions-menu')
    s['observed']['lab_actions_items'] = [t.strip().replace('\n', ' ') for t in menu.locator('[role="menuitem"]').all_inner_texts()]
    rec.shoot_full(page, s, 'lab-actions')
    rec.shoot_element(menu, s, 'lab-actions', label='Lab actions')
    page.click('#menu-destroy')
    page.wait_for_selector('#operation-review', state='visible', timeout=20000)
    settle(page, 1000)
    s['observed']['destroy_review'] = page.locator('#operation-review').inner_text()
    rec.shoot_full(page, s, 'destroy-review')
    rec.shoot_element(page.locator('#operation-review'), s, 'destroy-review', label='Destroy review')
    page.click('#op-cancel')
    page.wait_for_timeout(800)
    page.click('#lab-actions-button')
    page.click('#menu-remove-lab')
    page.wait_for_selector('#operation-review, dialog[open]', timeout=20000)
    settle(page, 1000)
    open_ids = page.evaluate("() => [...document.querySelectorAll('dialog[open]')].map(d => d.id)")
    s['observed']['remove_dialog_ids'] = open_ids
    s['observed']['remove_dialog_text'] = page.locator('dialog[open]').last.inner_text()
    rec.shoot_full(page, s, 'remove-review')
    page.keyboard.press('Escape')
    rec.write()
    browser.close()

STEPS = {1: step_1, 2: step_2, 3: step_3, 4: step_4, 5: step_5, 6: step_6, 7: step_7, 8: step_8, 9: step_9, 10: step_10, 11: step_11}


def parse_range(text):
    if not text:
        return sorted(STEPS)
    a, _, b = text.partition('-')
    lo = int(a)
    hi = int(b) if b else lo
    return [n for n in sorted(STEPS) if lo <= n <= hi]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--steps', default='', help='e.g. 5-8 or 11 (default: all)')
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright
    wanted = parse_range(args.steps)
    st = load_state()
    rec = qs_lib.StepRecorder(SCREEN_DIR, EVIDENCE_JSON, EVIDENCE_MD, "Scenario A: use an instructor's lab", prefix='a')
    if args.steps and EVIDENCE_JSON.exists():
        # resume: keep the records of the steps that are not rerun
        old = json.loads(EVIDENCE_JSON.read_text())
        rec.steps = [x for x in old.get('steps', []) if x['step'] not in wanted]
        rec.started_utc = old.get('started_utc', rec.started_utc)
    with sync_playwright() as pw:
        for n in wanted:
            t0 = time.time()
            print(f'--- step A{n}', flush=True)
            STEPS[n](rec, pw, st)
            rec.steps[-1]['elapsed_seconds'] = round(time.time() - t0, 1)
            rec.steps.sort(key=lambda x: x['step'])
            rec.write()
            save_state(st)
    ok = all(x['result'] == 'PASS' for x in rec.steps)
    print('Scenario A: all recorded steps PASS' if ok else 'Scenario A: a step failed')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
