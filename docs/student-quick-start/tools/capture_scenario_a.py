#!/usr/bin/env python3
"""Student quick-start Scenario A ("use an instructor's lab"), run for real against the live
Containerlab Node Manager, with a scripted Playwright walkthrough that produces the guide's
screenshots and evidence log.

Every step below drives the real page the same way a student would; device facts are read
independently over direct SSH with eos.py, and remote facts are read from GitHub with `gh`.

    clab-backup-ui/.venv/bin/python docs/student-quick-start/tools/capture_scenario_a.py

Run from the repository root; needs LD_LIBRARY_PATH set for the headless Chromium build
(export LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps).
"""
import json
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
from qs_lib import BASE, api, poll_git_job, poll_restore_job, settle, upload_review  # noqa: E402

SCREEN_DIR = ROOT / 'screenshots' / 'raw'
EVIDENCE_JSON = ROOT / 'evidence' / 'scenario-a.json'
EVIDENCE_MD = ROOT / 'evidence' / 'scenario-a.md'

LAB_NAME = 'link-basics'
TOPOLOGY_PATH = '/srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml'
R1_NAME = 'clab-link-basics-r1'
R2_NAME = 'clab-link-basics-r2'
R1_IP = '172.20.20.11'
R2_IP = '172.20.20.12'
REPO_URL = 'https://github.com/pruger-dev/netlab-course-student.git'
SAVE_FOLDER = 'link-basics/work'
GH_REPO = 'pruger-dev/netlab-course-student'


def gh_tree():
    """Full recursive tree of origin/main, read-only, via the already-authenticated gh CLI."""
    out = subprocess.run(
        ['gh', 'api', f'repos/{GH_REPO}/git/trees/main?recursive=1'],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    data = json.loads(out)
    return {t['path']: t for t in data.get('tree', [])}


def gh_blob_text(path):
    out = subprocess.run(
        ['gh', 'api', f'repos/{GH_REPO}/contents/{path}', '-H', 'Accept: application/vnd.github.raw'],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return out


def main():
    rec = qs_lib.StepRecorder(SCREEN_DIR, EVIDENCE_JSON, EVIDENCE_MD, 'Scenario A: use an instructor\'s lab')
    ctx = {}

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, context, page = qs_lib.new_context(pw)
        console_errors = []
        page.on('pageerror', lambda e: console_errors.append(str(e)))

        # ---------------- A1 ----------------
        s = rec.new_step(1, 'Home: empty My labs, Deploy box')
        page.goto(BASE + '/')
        page.wait_for_function(
            "() => !document.getElementById('lab-cards').hidden || !document.getElementById('empty').hidden",
            timeout=30000,
        )
        settle(page)
        s['actions'].append('Navigate to the manager home page')
        lab_card_count = page.locator('article.lab-card').count()
        empty_text = page.locator('#empty h2').inner_text() if page.locator('#empty').count() else ''
        s['observed']['lab_card_count'] = lab_card_count
        s['observed']['empty_state_heading'] = empty_text
        if lab_card_count != 0:
            rec.fail(s, f'expected My labs empty, found {lab_card_count} lab card(s)', page)
        rec.shoot_full(page, s, 'home')
        deploy_box = page.locator('article.start-card', has=page.locator('#home-deploy'))
        rec.shoot_element(deploy_box, s, 'deploy-box', label='Deploy box')
        s['screenshots'][-1]['callouts'] = [rec.bbox_of(page.locator('#home-deploy'), 'Choose a file on the lab VM…')]
        rec.write()

        # ---------------- A2 ----------------
        s = rec.new_step(2, 'Deploy link-basics from the lab VM')
        page.click('#home-deploy')
        page.wait_for_selector('#op-file-tree', state='visible', timeout=20000)
        settle(page)
        s['actions'].append('Click "Choose a file on the lab VM…"')
        root_summary = page.locator('#op-file-tree summary', has_text='/srv/containerlab-node-manager/projects').first
        if root_summary.count() == 0:
            root_summary = page.locator('#op-file-tree summary', has_text='projects').first
        root_summary.click()
        folder_summary = page.locator('#op-file-tree summary', has_text='link-basics').first
        folder_summary.wait_for(state='visible', timeout=10000)
        s['actions'].append('Open folder /srv/containerlab-node-manager/projects')
        folder_summary.click()
        file_button = page.locator('button.op-tree-file', has_text='link-basics.clab.yml').first
        file_button.wait_for(state='visible', timeout=10000)
        s['actions'].append('Open folder link-basics')
        settle(page, 300)
        dialog = page.locator('#op-browser')
        rec.shoot_full(page, s, 'file-picker')
        rec.shoot_element(dialog, s, 'file-picker-dialog', label='Lab folders on the VM',
                           callouts=[rec.bbox_of(file_button, '◇ link-basics.clab.yml')])
        file_button.click()
        page.wait_for_selector('#op-editor', state='visible', timeout=15000)
        settle(page)
        s['actions'].append('Click ◇ link-basics.clab.yml')
        yaml_text = page.locator('#op-edit-text').input_value()
        s['observed']['topology_path_field'] = page.locator('#op-edit-path').input_value()
        s['observed']['yaml_preview_first_line'] = yaml_text.splitlines()[0] if yaml_text else ''
        if s['observed']['topology_path_field'] != TOPOLOGY_PATH:
            rec.fail(s, f"expected topology path {TOPOLOGY_PATH!r}, got {s['observed']['topology_path_field']!r}", page)
        editor_dialog = page.locator('#op-editor')
        rec.shoot_full(page, s, 'topology-file')
        rec.shoot_element(editor_dialog, s, 'topology-file-dialog', label='Topology file',
                           callouts=[rec.bbox_of(page.locator('#op-deploy-project'), 'Deploy lab')])
        s['actions'].append('Topology file dialog shown with YAML preview')
        page.click('#op-deploy-project')
        page.wait_for_selector('#operation-review', state='visible', timeout=15000)
        settle(page)
        s['actions'].append('Click "Deploy lab"')
        review_title = page.locator('#operation-review h2').inner_text()
        s['observed']['review_title'] = review_title
        if review_title != f'Start {LAB_NAME}?':
            s['notes'].append(f'review title differs from the brief\'s quoted "Start {LAB_NAME}?": got {review_title!r}')
        review_dialog = page.locator('#operation-review')
        rec.shoot_full(page, s, 'start-review')
        rec.shoot_element(review_dialog, s, 'start-review-dialog', label=review_title,
                           callouts=[rec.bbox_of(page.locator('#op-confirm'), 'Start lab')])
        t_confirm = time.time()
        page.click('#op-confirm')
        page.wait_for_function("() => location.hash.includes('lab=')", timeout=20000)
        settle(page)
        lab_hash = page.evaluate('() => location.hash')
        m = re.search(r'lab=([0-9a-f]+)', lab_hash)
        if not m:
            rec.fail(s, f'could not find lab id in hash {lab_hash!r}', page)
        ctx['lab_id'] = m.group(1)
        ctx['deploy_confirm_time'] = t_confirm
        s['observed']['confirm_button_label'] = 'Start lab'
        s['observed']['post_confirm_hash'] = lab_hash
        s['observed']['lab_id'] = ctx['lab_id']
        rec.write()

        # ---------------- A3 ----------------
        s = rec.new_step(3, 'Starting -> Ready (deploy timing)')
        page.wait_for_selector('#lab-state', timeout=15000)
        settle(page, 300)
        lab_state_text = page.locator('#lab-state').inner_text()
        lab_ready_text = page.locator('#lab-ready').inner_text()
        s['observed']['lab_state_starting'] = lab_state_text
        s['observed']['lab_ready_starting'] = lab_ready_text
        header = page.locator('header.lab-header')
        rec.shoot_full(page, s, 'header-starting')
        rec.shoot_element(header, s, 'header-starting-el', label='Lab header (Starting)')
        page.click('#tab-devices')
        page.wait_for_selector('#device-list li.device-row', timeout=15000)
        settle(page)
        s['actions'].append('Open the Devices tab while devices are starting')
        starting_pills = page.locator('#device-list li.device-row .pill').all_inner_texts()
        s['observed']['devices_pills_starting'] = starting_pills
        devices_view = page.locator('#devices-view')
        rec.shoot_full(page, s, 'devices-starting')
        rec.shoot_element(devices_view, s, 'devices-starting-el', label='Devices tab (Starting)')

        deadline = time.time() + 240
        ready_count = 0
        pills = []
        while time.time() < deadline:
            page.reload()
            page.wait_for_selector('#lab-state', timeout=15000)
            page.click('#tab-devices')
            page.wait_for_selector('#device-list li.device-row', timeout=15000)
            pills = page.locator('#device-list li.device-row .pill').all_inner_texts()
            ready_count = sum(1 for p in pills if p.strip() == 'Ready')
            if ready_count == 2:
                break
            time.sleep(5)
        t_ready = time.time()
        ctx['ready_time'] = t_ready
        duration = t_ready - ctx['deploy_confirm_time']
        s['observed']['deploy_to_ready_seconds'] = round(duration, 1)
        if ready_count != 2:
            rec.fail(s, f'devices did not reach Ready within 4 minutes (last pills: {pills})', page)
        settle(page, 300)
        s['observed']['lab_ready_final'] = page.locator('#lab-ready').inner_text()
        s['observed']['devices_pills_ready'] = page.locator('#device-list li.device-row .pill').all_inner_texts()
        devices_view = page.locator('#devices-view')
        rec.shoot_full(page, s, 'devices-ready')
        rec.shoot_element(devices_view, s, 'devices-ready-el', label='Devices tab (Ready)')
        s['actions'].append(f'Polled the Devices tab until both rows read Ready ({duration:.1f}s since confirm)')
        rec.write()

        # ---------------- A4 ----------------
        s = rec.new_step(4, 'Topology tab and r1 CLI (show version / show interfaces status)')
        page.click('#tab-topology')
        page.wait_for_selector('#topology-map', timeout=15000)
        settle(page)
        s['actions'].append('Open the Topology tab')
        topo_view = page.locator('#topology-view')
        rec.shoot_full(page, s, 'topology')
        rec.shoot_element(topo_view, s, 'topology-el', label='Topology map')
        page.click('#tab-devices')
        page.wait_for_selector('#device-list li.device-row', timeout=15000)
        settle(page)
        r1_cli_button = page.locator(f'#device-list button[data-terminal="{R1_NAME}"]')
        r1_cli_button.wait_for(state='visible', timeout=10000)
        s['actions'].append('Open CLI on r1 from the Devices tab')
        with context.expect_page() as new_page_info:
            r1_cli_button.click()
        term = new_page_info.value
        term.wait_for_load_state()
        term.wait_for_selector('#terminal', timeout=15000)
        term.wait_for_function("() => document.getElementById('status').textContent === 'Connected'", timeout=30000)
        settle(term, 500)
        term.click('#terminal')
        term.keyboard.type('show version')
        term.keyboard.press('Enter')
        term.wait_for_timeout(1500)
        term.keyboard.type('show interfaces status')
        term.keyboard.press('Enter')
        term.wait_for_timeout(1500)
        rec.shoot_full(term, s, 'r1-terminal')
        rec.shoot_element(term.locator('#terminal'), s, 'r1-terminal-el', label='r1 CLI (show version / show interfaces status)')
        term.close()
        s['observed']['terminal_status_before_typing'] = 'Connected'

        r1_iface_status = eos.show(R1_IP, 'show interfaces status')
        r1_ip_brief = eos.show(R1_IP, 'show ip interface brief')
        s['device_evidence']['r1_show_interfaces_status'] = r1_iface_status[-800:]
        s['device_evidence']['r1_show_ip_interface_brief'] = r1_ip_brief[-800:]
        et1_connected = bool(re.search(r'Et(hernet)?1\s+.*connected', r1_iface_status, re.IGNORECASE))
        no_ip_yet = 'Ethernet1' not in r1_ip_brief or not re.search(r'Ethernet1\s+10\.', r1_ip_brief)
        s['observed']['et1_connected'] = et1_connected
        s['observed']['no_ip_on_et1_yet'] = no_ip_yet
        if not et1_connected:
            rec.fail(s, f'r1 Et1 not shown as connected: {r1_iface_status[-500:]}', page)
        rec.write()

        # ---------------- A5 ----------------
        s = rec.new_step(5, 'Connect a repository by URL')
        page.click('#tab-progress')
        page.wait_for_selector('#git-save-location', timeout=15000)
        settle(page)
        s['actions'].append('Open the Progress tab')
        blank_heading = page.locator('#git-save-location h3').inner_text()
        s['observed']['unconnected_card_heading'] = blank_heading
        card = page.locator('#git-save-location')
        rec.shoot_full(page, s, 'progress-unconnected')
        rec.shoot_element(card, s, 'progress-unconnected-el', label='Choose where to save your progress')
        page.click('[data-git-repo-action="connect"]')
        page.wait_for_selector('#git-connect-dialog', state='visible', timeout=10000)
        settle(page)
        s['actions'].append('Click "Connect a repository by URL"')
        page.fill('#git-connect-url', REPO_URL)
        page.fill('#git-connect-folder', SAVE_FOLDER)
        page.check('#git-connect-ack')
        connect_dialog = page.locator('#git-connect-dialog')
        rec.shoot_full(page, s, 'connect-dialog-filled')
        rec.shoot_element(connect_dialog, s, 'connect-dialog-filled-el', label='Connect a repository by URL (filled)')
        page.click('#git-connect-confirm')
        page.wait_for_selector('#git-save-location .git-destination-line', timeout=60000)
        settle(page, 1000)
        s['actions'].append('Click "Connect repository" and wait for the clone/check/register')
        destination_line = page.locator('#git-save-location .git-destination-line').inner_text().replace('\n', ' ')
        s['observed']['destination_line'] = destination_line
        card = page.locator('#git-save-location')
        rec.shoot_full(page, s, 'progress-connected')
        rec.shoot_element(card, s, 'progress-connected-el', label='Connected save location')
        if SAVE_FOLDER not in destination_line.replace(' ', ''):
            rec.fail(s, f'destination line does not mention {SAVE_FOLDER!r}: {destination_line!r}', page)
        versions_text = page.locator('#git-saved-versions').inner_text()
        s['observed']['saved_versions_text'] = versions_text[:2000]
        for expect_label in ('Starting state', 'Final state (instructor)', 'Troubleshooting scenario 01'):
            if expect_label not in versions_text:
                s['notes'].append(f'expected reference label {expect_label!r} not found verbatim in Saved versions text')
        rows = page.locator('#git-saved-versions li.git-version-row')
        row_summaries = []
        for i in range(rows.count()):
            row_summaries.append(rows.nth(i).inner_text().replace('\n', ' | '))
        s['observed']['saved_versions_rows'] = row_summaries
        reference_group = page.locator('#git-saved-versions .git-version-group', has_text='Instructor and reference versions')
        s['observed']['reference_group_present'] = reference_group.count() > 0
        rec.write()

        # ---------------- A6 ----------------
        s = rec.new_step(6, "Apply reference 'start' state")
        row = page.locator('#git-saved-versions li.git-version-row', has_text='Starting state').first
        if row.count() == 0:
            rec.fail(s, "no Saved versions row named 'Starting state' found", page)
        s['observed']['start_row_caption'] = row.locator('small.caption.mono').inner_text() if row.locator('small.caption.mono').count() else ''
        s['actions'].append("Click Saved versions › Starting state › Apply to running lab…")
        row.locator('[data-git-version-action="apply"]').click()
        page.wait_for_selector('#restore-review-dialog[open]', timeout=15000)
        page.wait_for_selector('#restore-review-dialog .restore-targets', timeout=15000)
        settle(page)
        review_text = page.locator('#restore-review-dialog').inner_text()
        source_line = next((ln.strip() for ln in review_text.splitlines() if ln.strip().startswith('Source:')), '')
        rows_txt = page.locator('#restore-review-dialog .restore-target')
        target_rows = [rows_txt.nth(i).inner_text().replace('\n', ' ') for i in range(rows_txt.count())]
        s['observed']['restore_source_line'] = source_line
        s['observed']['restore_target_rows'] = target_rows
        restore_dialog = page.locator('#restore-review-dialog')
        rec.shoot_full(page, s, 'apply-start-review')
        rec.shoot_element(restore_dialog, s, 'apply-start-review-el', label='Replace running configuration (start)')
        page.check('#restore-ack')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/restore'), timeout=15000) as info:
            page.click('#restore-run')
        submit_resp = info.value.json()
        job_id = submit_resp.get('id')
        s['observed']['restore_job_id'] = job_id
        page.wait_for_selector('#restore-job-dialog[open]', timeout=15000)
        t0 = time.time()
        job = poll_restore_job(page, job_id, timeout=300)
        t1 = time.time()
        s['observed']['restore_apply_seconds'] = round(t1 - t0, 1)
        s['observed']['restore_job_status'] = (job or {}).get('status')
        s['observed']['restore_targets'] = [{k: t.get(k) for k in ('name', 'status', 'message')} for t in (job or {}).get('targets', [])]
        settle(page, 300)
        result_dialog = page.locator('#restore-job-dialog')
        rec.shoot_full(page, s, 'apply-start-result')
        rec.shoot_element(result_dialog, s, 'apply-start-result-el', label='Restore result (start)')
        page.keyboard.press('Escape')
        if job is None:
            rec.fail(s, 'restore job did not reach a final status within the timeout', page)
        # Accept any final job status; only fail if a target explicitly reports a bad outcome.
        bad = [t for t in job.get('targets', [])
               if t.get('status') in ('failed', 'ineligible', 'verify_mismatch', 'rolled_back', 'uncertain', 'interrupted')]
        if bad:
            rec.fail(s, f'restore reported a bad target status: {bad}', page)

        r1_brief = eos.show(R1_IP, 'show ip interface brief')
        r2_brief = eos.show(R2_IP, 'show ip interface brief')
        ping_out = eos.show(R1_IP, 'ping 10.0.0.2 repeat 3')
        s['device_evidence']['r1_show_ip_interface_brief'] = r1_brief[-600:]
        s['device_evidence']['r2_show_ip_interface_brief'] = r2_brief[-600:]
        s['device_evidence']['r1_ping_10_0_0_2'] = ping_out[-600:]
        ping_ok = bool(re.search(r'3 (packets )?received|3 received', ping_out))
        s['observed']['ping_ok_after_start'] = ping_ok
        if not ping_ok:
            rec.fail(s, f'ping across the link failed after applying start: {ping_out[-500:]}', page)

        git_state = api(page, 'GET', f"/api/labs/{ctx['lab_id']}/git")['body']
        binding_prefix = ((git_state or {}).get('binding') or {}).get('repository', {}).get('prefix')
        s['remote_evidence']['binding_prefix_after_apply_start'] = binding_prefix
        if binding_prefix != SAVE_FOLDER:
            rec.fail(s, f'binding prefix changed after apply: {binding_prefix!r}', page)
        rec.write()

        # ---------------- A7 ----------------
        s = rec.new_step(7, 'r1: add Loopback0 over the CLI')
        page.click('#tab-devices')
        page.wait_for_selector('#device-list li.device-row', timeout=15000)
        r1_cli_button = page.locator(f'#device-list button[data-terminal="{R1_NAME}"]')
        r1_cli_button.wait_for(state='visible', timeout=10000)
        with context.expect_page() as new_page_info:
            r1_cli_button.click()
        term = new_page_info.value
        term.wait_for_load_state()
        term.wait_for_selector('#terminal', timeout=15000)
        term.wait_for_function("() => document.getElementById('status').textContent === 'Connected'", timeout=30000)
        settle(term, 500)
        term.click('#terminal')
        commands = ['enable', 'configure terminal', 'interface Loopback0', 'description r1 loopback',
                    'ip address 10.255.0.1/32', 'end', 'write memory', 'show ip interface brief']
        s['actions'] = [f'Terminal: {c}' for c in commands]
        for c in commands:
            term.keyboard.type(c)
            term.keyboard.press('Enter')
            term.wait_for_timeout(900)
        term.wait_for_timeout(1000)
        rec.shoot_full(term, s, 'r1-loopback-terminal')
        rec.shoot_element(term.locator('#terminal'), s, 'r1-loopback-terminal-el', label='r1 CLI (Loopback0 readback)')
        term.close()

        r1_readback = eos.show(R1_IP, 'show ip interface brief')
        s['device_evidence']['r1_show_ip_interface_brief_after_loopback'] = r1_readback[-600:]
        s['observed']['loopback0_present'] = 'Loopback0' in r1_readback and '10.255.0.1' in r1_readback
        if not s['observed']['loopback0_present']:
            rec.fail(s, f'Loopback0 with 10.255.0.1 not confirmed on r1: {r1_readback[-500:]}', page)
        rec.write()

        # ---------------- A8 ----------------
        s = rec.new_step(8, 'Save progress and upload')
        page.click('#tab-progress')
        page.wait_for_selector('#progress-save', timeout=15000)
        settle(page)
        s['actions'].append('Click "Save progress"')
        page.click('#progress-save')
        page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=60000)
        if page.locator('#git-diff-dialog[open]').count() == 0:
            rec.fail(s, 'Save progress did not open the review dialog', page)
        settle(page)
        changed_files_text = page.locator('#git-diff-dialog').inner_text()
        s['observed']['review_before_uploading_text'] = changed_files_text[:1500]
        diff_dialog = page.locator('#git-diff-dialog')
        rec.shoot_full(page, s, 'save-review')
        rec.shoot_element(diff_dialog, s, 'save-review-el', label='Review before uploading',
                           callouts=[rec.bbox_of(page.locator('#git-review-push'), 'Upload these changes'),
                                     rec.bbox_of(page.locator('#git-review-cancel'), 'Not now — keep it on the VM')])
        s['observed']['upload_button_label'] = page.locator('#git-review-push').inner_text()
        s['observed']['not_now_button_label'] = page.locator('#git-review-cancel').inner_text()
        s['notes'].append('Documented "Not now — keep it on the VM" sentence (not exercised here): '
                           '"This save is on the lab VM only. Nothing is uploaded to <host> unless you choose Upload these changes."')
        job_id, retry_resp = upload_review(page)
        s['actions'].append('Click "Upload these changes"')
        page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
        job = poll_git_job(page, job_id, timeout=180)
        s['observed']['save_job_status'] = (job or {}).get('status')
        s['observed']['save_job_commit'] = (job or {}).get('commit')
        ctx['first_save_commit'] = (job or {}).get('commit')
        settle(page, 300)
        job_dialog = page.locator('#git-job-dialog')
        rec.shoot_full(page, s, 'save-job-result')
        rec.shoot_element(job_dialog, s, 'save-job-result-el', label='Save job result')
        page.keyboard.press('Escape')
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-progress-status', timeout=15000)
        settle(page)
        status_line = page.locator('#git-progress-status').inner_text()
        s['observed']['progress_status_after_save'] = status_line
        card = page.locator('#git-progress-bar')
        rec.shoot_full(page, s, 'progress-after-save')
        rec.shoot_element(card, s, 'progress-after-save-el', label='Progress tab after save')
        if job is None or job.get('status') != 'synced':
            rec.fail(s, f'save job did not reach synced: {job}', page)

        tree = gh_tree()
        expect_paths = [f'{SAVE_FOLDER}/latest/manifest.json', f'{SAVE_FOLDER}/latest/r1.cfg',
                         f'{SAVE_FOLDER}/latest/r2.cfg', f'{SAVE_FOLDER}/latest/r1.eoscfg',
                         f'{SAVE_FOLDER}/latest/r2.eoscfg']
        found = {p: (p in tree) for p in expect_paths}
        s['remote_evidence']['tree_paths_after_first_save'] = found
        s['remote_evidence']['commit'] = ctx['first_save_commit']
        missing = [p for p, ok in found.items() if not ok]
        if missing:
            rec.fail(s, f'missing expected remote paths after first save: {missing}', page)
        rec.write()

        # ---------------- A9 ----------------
        s = rec.new_step(9, "Checkpoint 'loopback-added', then r2's loopback and a second save")
        page.click('#progress-view [data-git-action="checkpoint"]')
        page.wait_for_selector('#git-save-options[open]', timeout=15000)
        settle(page)
        s['actions'].append('Click "Create checkpoint…"')
        page.fill('#git-checkpoint-name', 'loopback-added')
        cp_dialog = page.locator('#git-save-options')
        rec.shoot_full(page, s, 'checkpoint-dialog')
        rec.shoot_element(cp_dialog, s, 'checkpoint-dialog-el', label='Create checkpoint (loopback-added)')
        page.click('#git-save-confirm')
        page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=60000)
        settle(page)
        if page.locator('#git-diff-dialog[open]').count() == 0:
            rec.fail(s, 'checkpoint save did not open the review dialog', page)
        cp_job_id, _ = upload_review(page)
        s['actions'].append('Review before uploading -> Upload these changes')
        page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
        cp_job = poll_git_job(page, cp_job_id, timeout=180)
        s['observed']['checkpoint_job_status'] = (cp_job or {}).get('status')
        s['observed']['checkpoint_job_commit'] = (cp_job or {}).get('commit')
        settle(page, 300)
        rec.shoot_full(page, s, 'checkpoint-job-result')
        rec.shoot_element(page.locator('#git-job-dialog'), s, 'checkpoint-job-result-el', label='Checkpoint job result')
        page.keyboard.press('Escape')
        if cp_job is None or cp_job.get('status') != 'synced':
            rec.fail(s, f'checkpoint job did not reach synced: {cp_job}', page)

        page.click('#tab-devices')
        page.wait_for_selector('#device-list li.device-row', timeout=15000)
        r2_cli_button = page.locator(f'#device-list button[data-terminal="{R2_NAME}"]')
        r2_cli_button.wait_for(state='visible', timeout=10000)
        with context.expect_page() as new_page_info:
            r2_cli_button.click()
        term = new_page_info.value
        term.wait_for_load_state()
        term.wait_for_selector('#terminal', timeout=15000)
        term.wait_for_function("() => document.getElementById('status').textContent === 'Connected'", timeout=30000)
        settle(term, 500)
        term.click('#terminal')
        r2_commands = ['enable', 'configure terminal', 'interface Loopback0', 'description r2 loopback',
                       'ip address 10.255.0.2/32', 'end', 'write memory']
        for c in r2_commands:
            term.keyboard.type(c)
            term.keyboard.press('Enter')
            term.wait_for_timeout(900)
        term.close()
        s['actions'].append('r2 terminal: added Loopback0 10.255.0.2/32, write memory')

        page.click('#tab-progress')
        page.wait_for_selector('#progress-save', timeout=15000)
        settle(page)
        page.click('#progress-save')
        page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=60000)
        settle(page)
        if page.locator('#git-diff-dialog[open]').count() == 0:
            rec.fail(s, 'second Save progress did not open the review dialog', page)
        job2_id, _ = upload_review(page)
        s['actions'].append('Save progress again -> Review -> Upload these changes')
        page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
        job2 = poll_git_job(page, job2_id, timeout=180)
        s['observed']['second_save_job_status'] = (job2 or {}).get('status')
        s['observed']['second_save_job_commit'] = (job2 or {}).get('commit')
        ctx['second_save_commit'] = (job2 or {}).get('commit')
        page.keyboard.press('Escape')
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=15000)
        settle(page)
        versions_text2 = page.locator('#git-saved-versions').inner_text()
        s['observed']['saved_versions_text_after_checkpoint'] = versions_text2[:2000]
        versions_card = page.locator('#git-saved-versions').locator('xpath=ancestor::section[1]')
        rec.shoot_full(page, s, 'saved-versions-with-checkpoint')
        rec.shoot_element(versions_card, s, 'saved-versions-with-checkpoint-el', label='Saved versions (Latest + loopback-added)')
        if job2 is None or job2.get('status') != 'synced':
            rec.fail(s, f'second save job did not reach synced: {job2}', page)

        tree2 = gh_tree()
        r2_latest_text = gh_blob_text(f'{SAVE_FOLDER}/latest/r2.cfg')
        r2_checkpoint_text = gh_blob_text(f'{SAVE_FOLDER}/checkpoints/loopback-added/r2.cfg')
        s['remote_evidence']['latest_r2_has_loopback0'] = 'Loopback0' in r2_latest_text
        s['remote_evidence']['checkpoint_r2_lacks_loopback0'] = 'Loopback0' not in r2_checkpoint_text
        double_latest = [p for p in tree2 if '/latest/latest' in p]
        s['remote_evidence']['no_nested_latest_latest'] = double_latest == []
        s['remote_evidence']['double_latest_paths_found'] = double_latest
        if 'Loopback0' not in r2_latest_text:
            rec.fail(s, 'link-basics/work/latest/r2.cfg does not contain Loopback0', page)
        if 'Loopback0' in r2_checkpoint_text:
            rec.fail(s, 'link-basics/work/checkpoints/loopback-added/r2.cfg unexpectedly contains Loopback0', page)
        if double_latest:
            rec.fail(s, f'found nested latest/latest path(s): {double_latest}', page)
        rec.write()

        # ---------------- A10 ----------------
        s = rec.new_step(10, "Apply reference 'broken-01', then return to the lab's own Latest")
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=15000)
        settle(page)
        broken_row = page.locator('#git-saved-versions li.git-version-row', has_text='Troubleshooting scenario 01').first
        if broken_row.count() == 0:
            rec.fail(s, "no Saved versions row named 'Troubleshooting scenario 01' found", page)
        s['actions'].append('Saved versions › Troubleshooting scenario 01 › Apply to running lab…')
        broken_row.locator('[data-git-version-action="apply"]').click()
        page.wait_for_selector('#restore-review-dialog[open]', timeout=15000)
        page.wait_for_selector('#restore-review-dialog .restore-targets', timeout=15000)
        settle(page)
        broken_review_text = page.locator('#restore-review-dialog').inner_text()
        s['observed']['broken_source_line'] = next((ln.strip() for ln in broken_review_text.splitlines() if ln.strip().startswith('Source:')), '')
        rec.shoot_full(page, s, 'apply-broken-review')
        rec.shoot_element(page.locator('#restore-review-dialog'), s, 'apply-broken-review-el', label='Replace running configuration (broken-01)')
        page.check('#restore-ack')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/restore'), timeout=15000) as info:
            page.click('#restore-run')
        broken_job_id = info.value.json().get('id')
        page.wait_for_selector('#restore-job-dialog[open]', timeout=15000)
        broken_job = poll_restore_job(page, broken_job_id, timeout=300)
        s['observed']['broken_restore_status'] = (broken_job or {}).get('status')
        settle(page, 300)
        rec.shoot_full(page, s, 'apply-broken-result')
        rec.shoot_element(page.locator('#restore-job-dialog'), s, 'apply-broken-result-el', label='Restore result (broken-01)')
        page.keyboard.press('Escape')

        ping_broken = eos.show(R1_IP, 'ping 10.0.0.2 repeat 3')
        r1_iface_broken = eos.show(R1_IP, 'show interfaces status')
        s['device_evidence']['r1_ping_after_broken'] = ping_broken[-600:]
        s['device_evidence']['r1_show_interfaces_status_after_broken'] = r1_iface_broken[-600:]
        ping_failed = not bool(re.search(r'3 (packets )?received|3 received', ping_broken))
        et1_notconnect = bool(re.search(r'Et(hernet)?1\s+.*notconnect', r1_iface_broken, re.IGNORECASE))
        s['observed']['ping_fails_after_broken'] = ping_failed
        s['observed']['et1_notconnect_after_broken'] = et1_notconnect
        if not ping_failed or not et1_notconnect:
            rec.fail(s, f'broken-01 did not reproduce the expected fault (ping_failed={ping_failed}, '
                        f'et1_notconnect={et1_notconnect})', page)

        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=15000)
        settle(page)
        latest_row = page.locator('#git-saved-versions li.git-version-row', has_text='Latest').first
        s['actions'].append('Saved versions › Latest › Apply to running lab…')
        latest_row.locator('[data-git-version-action="apply"]').click()
        page.wait_for_selector('#restore-review-dialog[open]', timeout=15000)
        page.wait_for_selector('#restore-review-dialog .restore-targets', timeout=15000)
        settle(page)
        latest_review_text = page.locator('#restore-review-dialog').inner_text()
        s['observed']['latest_source_line'] = next((ln.strip() for ln in latest_review_text.splitlines() if ln.strip().startswith('Source:')), '')
        rec.shoot_full(page, s, 'apply-latest-review')
        rec.shoot_element(page.locator('#restore-review-dialog'), s, 'apply-latest-review-el', label='Replace running configuration (own Latest)')
        page.check('#restore-ack')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/restore'), timeout=15000) as info:
            page.click('#restore-run')
        latest_job_id = info.value.json().get('id')
        page.wait_for_selector('#restore-job-dialog[open]', timeout=15000)
        latest_job = poll_restore_job(page, latest_job_id, timeout=300)
        s['observed']['latest_restore_status'] = (latest_job or {}).get('status')
        settle(page, 300)
        rec.shoot_full(page, s, 'apply-latest-result')
        rec.shoot_element(page.locator('#restore-job-dialog'), s, 'apply-latest-result-el', label='Restore result (own Latest)')
        page.keyboard.press('Escape')

        ping_restored = eos.show(R1_IP, 'ping 10.0.0.2 repeat 3')
        r1_brief2 = eos.show(R1_IP, 'show ip interface brief')
        r2_brief2 = eos.show(R2_IP, 'show ip interface brief')
        s['device_evidence']['r1_ping_after_latest'] = ping_restored[-600:]
        s['device_evidence']['r1_show_ip_interface_brief_after_latest'] = r1_brief2[-600:]
        s['device_evidence']['r2_show_ip_interface_brief_after_latest'] = r2_brief2[-600:]
        ping_ok2 = bool(re.search(r'3 (packets )?received|3 received', ping_restored))
        loopbacks_back = ('Loopback0' in r1_brief2 and '10.255.0.1' in r1_brief2 and
                          'Loopback0' in r2_brief2 and '10.255.0.2' in r2_brief2)
        s['observed']['ping_ok_after_latest'] = ping_ok2
        s['observed']['loopbacks_back'] = loopbacks_back
        if not ping_ok2 or not loopbacks_back:
            rec.fail(s, f'own Latest did not restore the expected state (ping_ok={ping_ok2}, '
                        f'loopbacks_back={loopbacks_back})', page)

        git_state2 = api(page, 'GET', f"/api/labs/{ctx['lab_id']}/git")['body']
        binding_prefix2 = ((git_state2 or {}).get('binding') or {}).get('repository', {}).get('prefix')
        s['remote_evidence']['binding_prefix_after_apply_latest'] = binding_prefix2
        if binding_prefix2 != SAVE_FOLDER:
            rec.fail(s, f'binding prefix changed after apply: {binding_prefix2!r}', page)

        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=15000)
        settle(page)
        checkpoint_row = page.locator('#git-saved-versions li.git-version-row', has_text='loopback-added').first
        compare_btn = checkpoint_row.locator('[data-git-version-action="compare"]') if checkpoint_row.count() else None
        if compare_btn is not None and compare_btn.count():
            compare_btn.click()
            page.wait_for_selector('#git-diff-dialog[open]', timeout=15000)
            settle(page)
            s['observed']['compare_checkpoint_dialog_title'] = page.locator('#git-diff-dialog h2').inner_text()
            rec.shoot_full(page, s, 'compare-checkpoint')
            rec.shoot_element(page.locator('#git-diff-dialog'), s, 'compare-checkpoint-el', label='Compare with my latest save (loopback-added)')
            page.keyboard.press('Escape')
        else:
            s['notes'].append('No "Compare with my latest save" button found on the loopback-added checkpoint row; skipped that capture.')
        rec.write()

        # ---------------- A11 ----------------
        s = rec.new_step(11, 'Fresh context: Home card, Progress tab, Lab actions menu, Destroy review (cancelled)')
        context.close()
        browser2, context2, page2 = qs_lib.new_context(pw)
        page2.goto(BASE + '/')
        page2.wait_for_selector('article.lab-card', timeout=20000)
        settle(page2)
        s['actions'].append('Fresh browser context -> Home')
        card2 = page2.locator(f'article.lab-card:has-text("{LAB_NAME}")').first
        s['observed']['home_card_text'] = card2.inner_text().replace('\n', ' | ')
        rec.shoot_full(page2, s, 'home-fresh')
        rec.shoot_element(card2, s, 'home-fresh-lab-card-el', label=f'{LAB_NAME} lab card')
        card2.locator('[data-lab]').first.click()
        page2.wait_for_selector('#tab-progress', timeout=15000)
        page2.click('#tab-progress')
        page2.wait_for_selector('#git-saved-versions', timeout=15000)
        settle(page2)
        versions_card2 = page2.locator('#git-saved-versions').locator('xpath=ancestor::section[1]')
        rec.shoot_full(page2, s, 'progress-fresh')
        rec.shoot_element(versions_card2, s, 'progress-fresh-el', label='Saved versions (fresh context)')
        page2.click('#lab-actions-button')
        page2.wait_for_selector('#lab-actions-menu:not([hidden])', timeout=10000)
        settle(page2, 300)
        menu = page2.locator('#lab-actions-menu')
        rec.shoot_full(page2, s, 'lab-actions-menu')
        rec.shoot_element(menu, s, 'lab-actions-menu-el', label='Lab actions menu')
        s['observed']['lab_actions_menu_items'] = [t.strip() for t in menu.locator('[role="menuitem"]').all_inner_texts()]
        page2.click('#menu-destroy')
        page2.wait_for_selector('#operation-review', state='visible', timeout=15000)
        settle(page2)
        destroy_title = page2.locator('#operation-review h2').inner_text()
        s['observed']['destroy_review_title'] = destroy_title
        destroy_dialog = page2.locator('#operation-review')
        rec.shoot_full(page2, s, 'destroy-review')
        rec.shoot_element(destroy_dialog, s, 'destroy-review-el', label=destroy_title)
        page2.click('#op-cancel')
        page2.wait_for_timeout(500)
        s['actions'].append('Opened "Destroy lab…" review, screenshotted it, then Cancel (no destroy performed)')
        s['notes'].append('Lab left running and connected for the lead, as instructed.')
        rec.write()

        s['observed']['console_errors_seen'] = console_errors[:10]
        rec.write()
        context2.close()
        browser2.close()

    rec.write()
    print('Scenario A complete: all steps PASS' if all(st['result'] == 'PASS' for st in rec.steps) else 'Scenario A had failing steps')
    return 0


if __name__ == '__main__':
    sys.exit(main())
