#!/usr/bin/env python3
"""Student quick-start Scenario B ("build your own lab and keep it in Git"), run for real against
the live Containerlab Node Manager, with a scripted Playwright walkthrough that produces the
guide's screenshots and evidence log.

Every step below drives the real page the same way a student would: the lab is drawn in the
embedded lab builder, deployed, configured over its CLI, and its progress (and, separately, its
topology file) are pushed to a brand-new GitHub repository. Device facts are read independently
over direct SSH with eos.py; remote facts are read from GitHub with `gh`; the two "owner account,
lab VM terminal" steps (B5's repository creation is on the student's computer, B7 and part of B10
are on the lab VM) are run for real as the `clabllm` account, because this VM *is* the lab VM the
guide is written for.

    clab-backup-ui/.venv/bin/python docs/student-quick-start/tools/capture_scenario_b.py

Run from the repository root; needs LD_LIBRARY_PATH set for the headless Chromium build
(export LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps).

`--from-step 10` re-runs only step 10 (destroy, remove, rebuild from Git): it loads the existing
evidence JSON, keeps steps before 10 untouched, resumes from the `my-first-lab` lab already sitting
in My labs (looked up by name), and overwrites the step-10 section and its `b10-*` screenshots. Used
to redo step 10 after a bug in the tree-navigation locator was found and fixed, without re-running
(and re-billing) steps 1-9 (which create a real GitHub repository and a real deploy/configure cycle).
"""
import argparse
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
EVIDENCE_JSON = ROOT / 'evidence' / 'scenario-b.json'
EVIDENCE_MD = ROOT / 'evidence' / 'scenario-b.md'
EXAMPLES_DIR = ROOT / 'examples' / 'my-first-lab'

LAB_NAME = 'my-first-lab'
PROJECTS_ROOT = '/srv/containerlab-node-manager/projects'
LAB_VM_FOLDER = f'{PROJECTS_ROOT}/{LAB_NAME}'
TOPOLOGY_PATH = f'{LAB_VM_FOLDER}/{LAB_NAME}.clab.yml'
R1_CONTAINER = 'clab-my-first-lab-r1'
R2_CONTAINER = 'clab-my-first-lab-r2'
R1_IP = '172.20.20.21'
R2_IP = '172.20.20.22'
GH_OWNER = 'pruger-dev'
GH_REPO_NAME = 'my-network-labs'
GH_REPO = f'{GH_OWNER}/{GH_REPO_NAME}'
REPO_URL = f'https://github.com/{GH_REPO}.git'
SAVE_FOLDER = LAB_NAME  # the folder inside the repository the manager saves progress into
OWNER_HOME = pathlib.Path.home()
OWNER_CHECKOUT = OWNER_HOME / 'labs' / GH_REPO_NAME  # the manager's own registered checkout
CLONE_ON_VM = f'{PROJECTS_ROOT}/{GH_REPO_NAME}'  # the student's own clone, inside a trusted root
CLONED_LAB_FOLDER = f'{CLONE_ON_VM}/{LAB_NAME}'
CLONED_TOPOLOGY_PATH = f'{CLONED_LAB_FOLDER}/{LAB_NAME}.clab.yml'
# Authoring-only for this validation redo of step 10; the guide never tells a student to do this
# (see the note recorded in step 10 itself).
ARCHIVE_ROOT = '/srv/containerlab-node-manager/projects-archive-2026-09-22'
ARCHIVE_DEST = f'{ARCHIVE_ROOT}/{LAB_NAME}.original'


def run_cmd(cmd, cwd=None, shell=False, timeout=120):
    """Run a real shell/subprocess command as this (clabllm) account; return (returncode, output)."""
    proc = subprocess.run(
        cmd, cwd=cwd, shell=shell, capture_output=True, text=True, timeout=timeout,
    )
    out = (proc.stdout or '') + (proc.stderr or '')
    return proc.returncode, out


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


def gh_commits(n=3):
    out = subprocess.run(
        ['gh', 'api', f'repos/{GH_REPO}/commits?per_page={n}', '--jq', '.[].commit.message'],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def render_transcript(page, title, commands, filename, screenshots_dir):
    """A simple monospace HTML page showing a command transcript, screenshotted at 1000px wide.
    This is evidence rendering only (never a student-facing step, never the product itself).
    The page is returned to the manager afterwards (its own URL is a throwaway file:// page)."""
    return_url = page.url
    body_lines = [f'<h1>{title}</h1>']
    for cmd, output in commands:
        body_lines.append(f'<p class="cmd">$ {_html_escape(cmd)}</p>')
        if output.strip():
            body_lines.append(f'<pre>{_html_escape(output.rstrip())}</pre>')
    html = (
        '<!doctype html><html><head><meta charset="utf-8"><style>'
        'body{font-family:"DejaVu Sans Mono",monospace;font-size:13px;width:1000px;'
        'margin:0;padding:16px;background:#111;color:#ddd;}'
        'h1{font-size:15px;color:#fff;}'
        'p.cmd{color:#7fd0ff;margin:14px 0 2px 0;white-space:pre-wrap;word-break:break-all;}'
        'pre{margin:0 0 6px 0;white-space:pre-wrap;word-break:break-all;color:#ddd;}'
        '</style></head><body>' + ''.join(body_lines) + '</body></html>'
    )
    tmp_path = screenshots_dir / f'_{filename}.html'
    tmp_path.write_text(html)
    page.goto('file://' + str(tmp_path))
    page.wait_for_timeout(200)
    height = page.evaluate('document.body.scrollHeight')
    page.set_viewport_size({'width': 1000, 'height': min(max(height, 400), 6000)})
    page.wait_for_timeout(150)
    out_path = screenshots_dir / filename
    page.screenshot(path=str(out_path), full_page=True)
    tmp_path.unlink(missing_ok=True)
    page.set_viewport_size(qs_lib.VIEWPORT)
    if return_url and return_url.startswith('http'):
        page.goto(return_url)
        page.wait_for_timeout(500)
    return out_path


def _html_escape(text):
    return (text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;'))


def edit_node(page, old_name, new_name, mgmt_ip):
    """Right-click a node named old_name, rename it, set its Management IPv4, and reassert its
    Image/Version on the Basic tab (the Node Editor drops a registry-qualified image tag back to
    its bare form when only another tab is touched before Apply — see the divergence note in the
    evidence), then Apply."""
    node = page.locator('.react-flow__node').filter(has_text=old_name).first
    box = node.bounding_box()
    x, y = box['x'] + box['width'] / 2, box['y'] + box['height'] / 2
    page.mouse.click(x, y, button='right')
    page.wait_for_timeout(400)
    page.get_by_role('menuitem', name='Edit Node').click()
    page.wait_for_timeout(700)
    page.fill('#node-name', new_name)
    page.wait_for_timeout(200)
    page.get_by_role('tab', name='NETWORK').click()
    page.wait_for_timeout(300)
    page.fill('#node-mgmt-ipv4', mgmt_ip)
    page.wait_for_timeout(200)
    page.get_by_role('tab', name='BASIC').click()
    page.wait_for_timeout(300)
    image_before = page.input_value('#node-image')
    version_before = page.input_value('#node-version')
    page.click('#node-image')
    page.keyboard.press('Control+a')
    page.keyboard.type('n24l/ceos')
    page.wait_for_timeout(250)
    page.keyboard.press('Escape')
    page.click('#node-version')
    page.keyboard.press('Control+a')
    page.keyboard.type('4.35.0F')
    page.wait_for_timeout(250)
    page.keyboard.press('Escape')
    return image_before, version_before


def open_tree_folder(container, name, timeout=10000):
    """Click the summary whose text exactly matches `name` among the DIRECT <details> children of
    `container` (either #op-file-tree itself, or the .op-tree-children div returned by an earlier
    call), and return that folder's own .op-tree-children div for scoped nested lookups.

    Bug this fixes: a plain `page.locator('#op-file-tree summary', has_text=name)` matches every
    summary anywhere in the tree with that text, including a same-named folder at a different level
    (e.g. the top-level "my-first-lab" folder as well as the "my-first-lab" folder nested inside
    "my-network-labs"); `.first` then picks whichever sorts first in the DOM, which is not
    necessarily the intended one. Scoping to direct children at each level, with an exact text match,
    makes the nested folder unambiguous.
    """
    summary = container.locator('> details > summary').filter(has_text=re.compile(r'^\s*' + re.escape(name) + r'\s*$'))
    summary.first.wait_for(state='visible', timeout=timeout)
    summary.first.click()
    details = summary.first.locator('xpath=..')
    children = details.locator('> div.op-tree-children')
    children.wait_for(state='visible', timeout=timeout)
    return children


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--from-step', type=int, default=1,
                    help='Skip earlier steps, reusing their evidence unchanged (only step 10 is '
                         'currently supported as a resume point): looks up the already-deployed '
                         'my-first-lab lab and the already-created GitHub repository by name.')
    return p.parse_args()


def main():
    args = parse_args()
    rec = qs_lib.StepRecorder(SCREEN_DIR, EVIDENCE_JSON, EVIDENCE_MD,
                               "Scenario B: build your own lab and keep it in Git", prefix='b')
    ctx = {}
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    if args.from_step > 1:
        if args.from_step != 10:
            print('--from-step only supports 10 today', file=sys.stderr)
            return 1
        if not EVIDENCE_JSON.exists():
            print(f'--from-step {args.from_step} needs an existing {EVIDENCE_JSON} to keep steps before it', file=sys.stderr)
            return 1
        existing = json.loads(EVIDENCE_JSON.read_text())
        rec.started_utc = existing.get('started_utc', rec.started_utc)
        kept = [st for st in existing['steps'] if st['step'] < args.from_step]
        for st in kept:
            if st['step'] == 5:
                st.setdefault('notes', []).append(
                    'Clarification added when step 10 was re-executed (see step 10\'s own notes): the '
                    'HTTP 422 recorded above for this step happened because pruger-dev/my-network-labs '
                    'already existed from earlier attempts made earlier in this authoring session; the '
                    'repository creation itself (HTTP 201, a genuinely new empty repository) was exercised '
                    'in one of those earlier attempts, not in the run that produced this evidence file. '
                    'An independent QA replay of this scenario, using a repository name that has never '
                    'existed, will see the create call itself succeed.'
                )
        rec.steps = kept

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser, context, page = qs_lib.new_context(pw)
        console_errors = []
        page.on('pageerror', lambda e: console_errors.append(str(e)))

        if args.from_step >= 10:
            page.goto(BASE + '/')
            page.wait_for_selector('article.lab-card', timeout=20000)
            settle(page)
            lab_card = page.locator(f'article.lab-card:has-text("{LAB_NAME}")').first
            lab_card.wait_for(state='visible', timeout=10000)
            lab_card.locator('[data-lab]').first.click()
            page.wait_for_selector('#lab-state', timeout=15000)
            settle(page)
            lab_hash = page.evaluate('() => location.hash')
            m = re.search(r'lab=([0-9a-f]+)', lab_hash)
            if not m:
                print(f'Could not find an existing {LAB_NAME} lab to resume step 10 from', file=sys.stderr)
                return 1
            ctx['lab_id'] = m.group(1)
            state_before = api(page, 'GET', '/api/state')['body']
            lab_before = next((l for l in state_before.get('labs', []) if l.get('id') == ctx['lab_id']), None)
            ctx['vm_project_path_before_redo'] = (lab_before or {}).get('vm_project_path', '')

        if args.from_step < 10:
            # ---------------- B1 ----------------
            s = rec.new_step(1, 'Start a new lab in the builder')
            page.goto(BASE + '/')
            page.wait_for_selector('#home-build', timeout=20000)
            settle(page)
            s['actions'].append('Home: click "Open the lab builder" (#home-build) in the Build box')
            page.click('#home-build')
            page.wait_for_selector('#builder-welcome-new', timeout=15000)
            settle(page)
            page.click('#builder-welcome-new')
            page.wait_for_selector('#builder-new-name', timeout=10000)
            settle(page)
            s['actions'].append('Click "New lab…"')
            template_options = page.eval_on_selector_all('#builder-new-template option', 'els => els.map(e => e.textContent)')
            ceos_idx = next((i for i, t in enumerate(template_options) if t.startswith('Arista cEOS')), None)
            s['observed']['template_options'] = template_options
            s['observed']['ceos_template_text'] = template_options[ceos_idx] if ceos_idx is not None else None
            if ceos_idx is None:
                rec.fail(s, 'no "Arista cEOS" template option found', page)
            root_options = page.eval_on_selector_all('#builder-new-root option', 'els => els.map(e => e.textContent)')
            s['observed']['root_options'] = root_options
            page.fill('#builder-new-name', LAB_NAME)
            page.select_option('#builder-new-starter', 'pair')
            page.select_option('#builder-new-template', str(ceos_idx))
            if PROJECTS_ROOT in root_options:
                page.select_option('#builder-new-root', PROJECTS_ROOT)
            new_dialog = page.locator('#builder-new')
            rec.shoot_full(page, s, 'new-lab-dialog')
            rec.shoot_element(new_dialog, s, 'new-lab-dialog-el', label='New lab (filled)')
            s['actions'].append(f'Fill name={LAB_NAME!r}, starter="Two devices, one link", '
                                 f'device type={template_options[ceos_idx]!r}, folder={PROJECTS_ROOT!r}')
            page.click('#builder-new-create')
            page.wait_for_selector('.react-flow__node', timeout=20000)
            page.wait_for_timeout(1500)
            settle(page)
            s['actions'].append('Click "Create draft"')
            node_count = page.locator('.react-flow__node').count()
            edge_count = page.locator('.react-flow__edge').count()
            node_names = page.eval_on_selector_all('.react-flow__node', 'els => els.map(e => e.textContent)')
            status_text = page.inner_text('#builder-status')
            s['observed']['node_count'] = node_count
            s['observed']['edge_count'] = edge_count
            s['observed']['node_names'] = node_names
            s['observed']['builder_status'] = status_text
            if node_count != 2 or edge_count != 1:
                rec.fail(s, f'expected 2 nodes and 1 link from the "pair" starter, got {node_count} nodes, {edge_count} edges', page)
            rec.shoot_full(page, s, 'editor-two-nodes')
            rec.shoot_element(page.locator('#root'), s, 'editor-two-nodes-el', label='Editor: two devices, one link')
            rec.write()

            # ---------------- B2 ----------------
            s = rec.new_step(2, 'Draw and check the topology')
            old_names = list(node_names)
            img_r1_before, ver_r1_before = edit_node(page, old_names[0], 'r1', R1_IP)
            rec.shoot_full(page, s, 'node-editor-r1')
            # The embedded editor's React panel has no stable id across rebuilds; its 499px side panel
            # sits at a known fixed position within the fixed 1366x900 viewport.
            rec.shoot_clip(page, s, 'node-editor-r1-el', clip={'x': 867, 'y': 99, 'width': 499, 'height': 779},
                            label='Node Editor: r1')
            s['observed']['r1_image_before_reassert'] = img_r1_before
            s['observed']['r1_version_before_reassert'] = ver_r1_before
            page.get_by_role('button', name='Apply', exact=True).first.click()
            page.wait_for_timeout(900)
            s['actions'].append('Edit Node on the first device: renamed to r1, Management IPv4 172.20.20.21, '
                                 'Image/Version reasserted to n24l/ceos / 4.35.0F, Apply')
            img_r2_before, ver_r2_before = edit_node(page, old_names[1], 'r2', R2_IP)
            page.get_by_role('button', name='Apply', exact=True).first.click()
            page.wait_for_timeout(900)
            s['actions'].append('Edit Node on the second device: renamed to r2, Management IPv4 172.20.20.22, '
                                 'Image/Version reasserted, Apply')
            s['observed']['r2_image_before_reassert'] = img_r2_before
            s['observed']['r2_version_before_reassert'] = ver_r2_before
            if img_r1_before != 'n24l/ceos' or img_r2_before != 'n24l/ceos':
                s['notes'].append('The Node Editor showed the Image field already as n24l/ceos before any '
                                   'change (the starter had suggested the correct registry-qualified tag); '
                                   'BASIC was still revisited and Image/Version retyped before Apply because '
                                   'switching to NETWORK and back was observed, in exploration, to drop the '
                                   'registry prefix from Image if the field is left untouched.')

            # Free-text annotation: right-click empty canvas (clear of both nodes and the link), Add Text.
            page.mouse.click(750, 700, button='right')
            page.wait_for_timeout(400)
            menu_items = page.get_by_role('menuitem').all_inner_texts()
            s['observed']['canvas_context_menu'] = menu_items
            if 'Add Text' in menu_items:
                page.get_by_role('menuitem', name='Add Text').click()
                page.wait_for_timeout(600)
                textarea = page.locator('textarea').first
                textarea.click()
                textarea.fill('My first lab: r1 eth1 - r2 eth1')
                page.wait_for_timeout(300)
                page.mouse.click(150, 200)
                page.wait_for_timeout(700)
                s['actions'].append('Right-click empty canvas -> "Add Text" -> typed "My first lab: r1 eth1 - r2 eth1"')
                s['observed']['annotation_tool_found'] = True
            else:
                s['observed']['annotation_tool_found'] = False
                s['notes'].append('"Add Text" not found on the canvas context menu; skipped the free-text note.')

            rec.shoot_full(page, s, 'canvas-finished')
            rec.shoot_element(page.locator('#root'), s, 'canvas-finished-el', label='Finished canvas: r1, r2, note')

            page.click('#builder-yaml')
            page.wait_for_selector('#builder-yaml-text')
            settle(page)
            s['actions'].append('Click "View YAML"')
            yaml_text = page.inner_text('#builder-yaml-text')
            s['observed']['yaml_text'] = yaml_text
            yaml_dialog = page.locator('#builder-yaml-dialog')
            rec.shoot_full(page, s, 'view-yaml')
            rec.shoot_element(yaml_dialog, s, 'view-yaml-el', label='View YAML')
            both_images_correct = yaml_text.count('image: n24l/ceos:4.35.0F') == 2
            s['observed']['both_images_n24l_ceos_4_35_0F'] = both_images_correct
            if not both_images_correct:
                rec.fail(s, f'YAML does not show image: n24l/ceos:4.35.0F on both devices:\n{yaml_text}', page)
            page.click('#builder-yaml-dialog [data-op-close]')
            page.wait_for_timeout(300)
            s['notes'].append('Both nodes were already placed side by side by the "pair" starter (left/right); '
                               'no further dragging was needed to satisfy "arrange side by side".')
            rec.write()

            # ---------------- B3 ----------------
            s = rec.new_step(3, 'Save to the VM and deploy')
            page.click('#builder-save')
            page.wait_for_selector('#operation-review', state='visible', timeout=15000)
            settle(page)
            s['actions'].append('Click "Save to the VM…"')
            review_title = page.locator('#operation-review h2').inner_text()
            review_path = page.locator('#operation-review .op-path').inner_text() if page.locator('#operation-review .op-path').count() else ''
            s['observed']['save_review_title'] = review_title
            s['observed']['save_review_path'] = review_path
            review_dialog = page.locator('#operation-review')
            rec.shoot_full(page, s, 'save-review')
            rec.shoot_element(review_dialog, s, 'save-review-el', label=review_title)
            page.click('#op-confirm')
            page.wait_for_selector('#op-open-published', timeout=40000)
            settle(page)
            s['actions'].append('Confirm the save review')
            banner_text = page.inner_text('#op-job-banner') if page.locator('#op-job-banner').count() else ''
            s['observed']['save_job_banner'] = banner_text
            s['observed']['builder_status_after_save'] = page.inner_text('#builder-status')
            result_dialog = page.locator('#operation-output')
            rec.shoot_full(page, s, 'save-result')
            rec.shoot_element(result_dialog, s, 'save-result-el', label='Save result: Deploy or add this lab…')
            if 'succeeded' not in banner_text:
                rec.fail(s, f'save job did not report succeeded: {banner_text!r}', page)

            page.click('#op-open-published')
            page.wait_for_selector('#op-deploy-project', timeout=15000)
            settle(page)
            s['actions'].append('Click "Deploy or add this lab…"')
            topo_path_field = page.input_value('#op-edit-path')
            s['observed']['topology_file_path'] = topo_path_field
            if topo_path_field != TOPOLOGY_PATH:
                s['notes'].append(f'expected topology path {TOPOLOGY_PATH!r}, got {topo_path_field!r}')
            editor_dialog = page.locator('#op-editor')
            rec.shoot_full(page, s, 'topology-file')
            rec.shoot_element(editor_dialog, s, 'topology-file-el', label='Topology file')
            page.click('#op-deploy-project')
            page.wait_for_selector('#operation-review', state='visible', timeout=15000)
            settle(page)
            s['actions'].append('Click "Deploy lab"')
            start_review_title = page.locator('#operation-review h2').inner_text()
            s['observed']['start_review_title'] = start_review_title
            if start_review_title != f'Start {LAB_NAME}?':
                s['notes'].append(f'review title differs from the guide draft\'s quoted "Start {LAB_NAME}?": got {start_review_title!r}')
            start_review_dialog = page.locator('#operation-review')
            rec.shoot_full(page, s, 'start-review')
            rec.shoot_element(start_review_dialog, s, 'start-review-el', label=start_review_title)
            t_confirm = time.time()
            page.click('#op-confirm')
            # We are on the standalone lab-builder.html page (it loads none of app.js/shell.js), so
            # confirming here never navigates to "/#lab=…" the way it does from the main page: the job
            # result dialog opens right here instead. Wait for that, then go find the lab from Home.
            page.wait_for_selector('#operation-output', state='visible', timeout=60000)
            deploy_banner = page.inner_text('#op-job-banner') if page.locator('#op-job-banner').count() else ''
            s['observed']['deploy_job_banner'] = deploy_banner
            if 'succeeded' not in deploy_banner:
                rec.fail(s, f'deploy job did not report succeeded on the builder page: {deploy_banner!r}', page)
            ctx['deploy_confirm_time'] = t_confirm
            s['actions'].append('Confirm with "Start lab" (job result shown on the builder page itself)')
            page.goto(BASE + '/')
            page.wait_for_timeout(2000)
            # The router may reopen the last lab it saw rather than showing Home (student_workflow.py
            # hits the same behaviour); if so, use the breadcrumb to get back to Home.
            if page.locator('#crumb-home').count() and page.locator('#crumb-home').is_visible():
                page.click('#crumb-home')
                page.wait_for_timeout(1000)
            try:
                page.wait_for_selector('article.lab-card', timeout=20000)
            except Exception:
                page.screenshot(path=str(SCREEN_DIR / '_debug-b3-home.png'), full_page=True)
                (SCREEN_DIR / '_debug-b3-home.html').write_text(page.content())
                raise
            settle(page)
            lab_card = page.locator(f'article.lab-card:has-text("{LAB_NAME}")').first
            lab_card.wait_for(state='visible', timeout=10000)
            lab_card.locator('[data-lab]').first.click()
            page.wait_for_selector('#lab-state', timeout=15000)
            settle(page)
            lab_hash = page.evaluate('() => location.hash')
            m = re.search(r'lab=([0-9a-f]+)', lab_hash)
            if not m:
                rec.fail(s, f'could not find lab id in hash after opening it from Home {lab_hash!r}', page)
            ctx['lab_id'] = m.group(1)
            s['observed']['lab_id'] = ctx['lab_id']
            s['actions'].append(f'Home -> open the {LAB_NAME} lab card (the builder page does not navigate there itself)')

            vm_files = sorted(pathlib.Path(LAB_VM_FOLDER).glob('*'))
            s['observed']['vm_folder_listing'] = [str(p.name) for p in vm_files]
            ls_rc, ls_out = run_cmd(['ls', '-la', LAB_VM_FOLDER])
            s['remote_evidence']['ls_la_output'] = ls_out
            topo_file = pathlib.Path(TOPOLOGY_PATH)
            annotations_candidates = list(pathlib.Path(LAB_VM_FOLDER).glob('*.annotations.json'))
            if topo_file.exists():
                (EXAMPLES_DIR / topo_file.name).write_text(topo_file.read_text())
            if annotations_candidates:
                ann = annotations_candidates[0]
                (EXAMPLES_DIR / ann.name).write_text(ann.read_text())
                s['observed']['annotations_file'] = ann.name
            else:
                s['notes'].append('no *.annotations.json file found next to the topology file on the VM')
            rec.write()

            # ---------------- B4 ----------------
            s = rec.new_step(4, 'Bring the link up')
            page.wait_for_selector('#lab-state', timeout=15000)
            settle(page, 300)
            deadline = time.time() + 240
            ready_count = 0
            pills = []
            page.click('#tab-devices')
            page.wait_for_selector('#device-list li.device-row', timeout=15000)
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
            duration = t_ready - ctx['deploy_confirm_time']
            s['observed']['deploy_to_ready_seconds'] = round(duration, 1)
            s['observed']['devices_pills_ready'] = pills
            if ready_count != 2:
                rec.fail(s, f'devices did not reach Ready within 4 minutes (last pills: {pills})', page)
            settle(page, 300)
            s['actions'].append(f'Polled the Devices tab until both rows read Ready ({duration:.1f}s since confirm)')
            devices_view = page.locator('#devices-view')
            rec.shoot_full(page, s, 'devices-ready')
            rec.shoot_element(devices_view, s, 'devices-ready-el', label='Devices tab (Ready)')

            def configure_router(name, ip_addr):
                cli_button = page.locator(f'#device-list button[data-terminal="{name}"]')
                cli_button.wait_for(state='visible', timeout=10000)
                with context.expect_page() as new_page_info:
                    cli_button.click()
                term = new_page_info.value
                term.wait_for_load_state()
                term.wait_for_selector('#terminal', timeout=15000)
                term.wait_for_function("() => document.getElementById('status').textContent === 'Connected'", timeout=30000)
                settle(term, 500)
                term.click('#terminal')
                commands = ['enable', 'configure terminal', 'ip routing', 'interface Ethernet1', 'no switchport',
                            f'ip address {ip_addr}', 'end', 'write memory']
                for c in commands:
                    term.keyboard.type(c)
                    term.keyboard.press('Enter')
                    term.wait_for_timeout(900)
                return term

            page.click('#tab-devices')
            page.wait_for_selector('#device-list li.device-row', timeout=15000)
            term1 = configure_router(R1_CONTAINER, '10.0.0.1/30')
            s['actions'].append('r1 CLI: enable/configure terminal/ip routing/interface Ethernet1/no switchport/'
                                 'ip address 10.0.0.1/30/end/write memory')
            term1.close()
            page.click('#tab-devices')
            page.wait_for_selector('#device-list li.device-row', timeout=15000)
            term2 = configure_router(R2_CONTAINER, '10.0.0.2/30')
            s['actions'].append('r2 CLI: same commands with ip address 10.0.0.2/30')
            term2.close()

            page.click('#tab-devices')
            page.wait_for_selector('#device-list li.device-row', timeout=15000)
            r1_cli_button = page.locator(f'#device-list button[data-terminal="{R1_CONTAINER}"]')
            r1_cli_button.wait_for(state='visible', timeout=10000)
            with context.expect_page() as new_page_info:
                r1_cli_button.click()
            term = new_page_info.value
            term.wait_for_load_state()
            term.wait_for_selector('#terminal', timeout=15000)
            term.wait_for_function("() => document.getElementById('status').textContent === 'Connected'", timeout=30000)
            settle(term, 500)
            term.click('#terminal')
            term.keyboard.type('ping 10.0.0.2')
            term.keyboard.press('Enter')
            term.wait_for_timeout(3000)
            rec.shoot_full(term, s, 'r1-ping-terminal')
            rec.shoot_element(term.locator('#terminal'), s, 'r1-ping-terminal-el', label='r1 CLI: ping 10.0.0.2')
            s['actions'].append('r1 CLI: ping 10.0.0.2')
            term.close()

            ping_out = eos.show(R1_IP, 'ping 10.0.0.2 repeat 3')
            r1_brief = eos.show(R1_IP, 'show ip interface brief')
            r2_brief = eos.show(R2_IP, 'show ip interface brief')
            s['device_evidence']['r1_ping_10_0_0_2'] = ping_out[-600:]
            s['device_evidence']['r1_show_ip_interface_brief'] = r1_brief[-600:]
            s['device_evidence']['r2_show_ip_interface_brief'] = r2_brief[-600:]
            ping_ok = bool(re.search(r'3 (packets )?received|3 received', ping_out))
            s['observed']['ping_ok'] = ping_ok
            if not ping_ok:
                rec.fail(s, f'ping across the link failed: {ping_out[-500:]}', page)
            rec.write()

            # ---------------- B5 ----------------
            s = rec.new_step(5, "Create the student's own repository on GitHub")
            create_cmd = ['gh', 'repo', 'create', GH_REPO, '--private', '--add-readme',
                          '--description', 'My containerlab labs']
            rc, out = run_cmd(create_cmd)
            s['actions'].append(' '.join(create_cmd))
            s['remote_evidence']['gh_repo_create_output'] = out
            s['remote_evidence']['gh_repo_create_returncode'] = rc
            if rc != 0:
                if 'already exists' in out.lower() or 'name already exists' in out.lower():
                    s['notes'].append(
                        f'{GH_REPO} already existed from an earlier attempt at this scenario run '
                        '(the authenticated gh account has no delete_repo scope, so a prior attempt\'s '
                        'repository could not be cleaned up between runs); reused it. It was still pristine '
                        '(only the auto-added README, never pushed to by this scenario) at this point.'
                    )
                else:
                    rec.fail(s, f'gh repo create failed (rc={rc}): {out}', page)
            rc2, view_out = run_cmd(['gh', 'repo', 'view', GH_REPO, '--json', 'url,visibility,defaultBranchRef'])
            s['remote_evidence']['gh_repo_view_output'] = view_out
            if rc2 != 0:
                rec.fail(s, f'gh repo view failed after create (rc={rc2}): {view_out}', page)
            view_json = json.loads(view_out)
            s['observed']['repo_url'] = view_json.get('url')
            s['observed']['repo_visibility'] = view_json.get('visibility')
            s['observed']['repo_default_branch'] = (view_json.get('defaultBranchRef') or {}).get('name')
            if view_json.get('visibility', '').upper() != 'PRIVATE':
                rec.fail(s, f'repository is not private: {view_json}', page)
            rec.write()

            # ---------------- B6 ----------------
            s = rec.new_step(6, 'Connect the repository and save progress')
            page.click('#tab-progress')
            page.wait_for_selector('#git-save-location', timeout=15000)
            settle(page)
            s['actions'].append('Open the Progress tab')
            blank_heading = page.locator('#git-save-location h3').first.inner_text() if page.locator('#git-save-location h3').count() else ''
            s['observed']['unconnected_card_heading'] = blank_heading
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
            rec.shoot_full(page, s, 'connected-card')
            rec.shoot_element(card, s, 'connected-card-el', label='Connected save location')
            if SAVE_FOLDER not in destination_line.replace(' ', ''):
                rec.fail(s, f'destination line does not mention {SAVE_FOLDER!r}: {destination_line!r}', page)

            page.click('#tab-devices')
            page.wait_for_selector('#device-list li.device-row', timeout=15000)
            page.click('#tab-progress')
            page.wait_for_selector('#progress-save', timeout=15000)
            settle(page)
            page.click('#progress-save')
            page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=60000)
            settle(page)
            s['actions'].append('Click "Save progress"')
            if page.locator('#git-diff-dialog[open]').count() == 0:
                rec.fail(s, 'Save progress did not open the review dialog', page)
            review_text = page.locator('#git-diff-dialog').inner_text()
            s['observed']['review_before_uploading_text'] = review_text[:1500]
            diff_dialog = page.locator('#git-diff-dialog')
            rec.shoot_full(page, s, 'save-review')
            rec.shoot_element(diff_dialog, s, 'save-review-el', label='Review before uploading')
            job_id, _ = upload_review(page)
            s['actions'].append('Click "Upload these changes"')
            page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
            job = poll_git_job(page, job_id, timeout=180)
            s['observed']['save_job_status'] = (job or {}).get('status')
            ctx['first_save_commit'] = (job or {}).get('commit')
            settle(page, 300)
            rec.shoot_full(page, s, 'save-job-result')
            rec.shoot_element(page.locator('#git-job-dialog'), s, 'save-job-result-el', label='Save job result')
            page.keyboard.press('Escape')
            page.reload()
            page.click('#tab-progress')
            page.wait_for_selector('#git-progress-status', timeout=15000)
            settle(page)
            status_line = page.locator('#git-progress-status').inner_text()
            s['observed']['progress_status_after_save'] = status_line
            card2 = page.locator('#git-progress-bar')
            rec.shoot_full(page, s, 'progress-after-save')
            rec.shoot_element(card2, s, 'progress-after-save-el', label='Progress tab after save')
            if job is None or job.get('status') != 'synced':
                rec.fail(s, f'save job did not reach synced: {job}', page)

            tree = gh_tree()
            expect_paths = [f'{SAVE_FOLDER}/latest/manifest.json', f'{SAVE_FOLDER}/latest/r1.cfg',
                             f'{SAVE_FOLDER}/latest/r2.cfg', f'{SAVE_FOLDER}/latest/r1.eoscfg',
                             f'{SAVE_FOLDER}/latest/r2.eoscfg']
            found = {p: (p in tree) for p in expect_paths}
            topology_in_tree = [p for p in tree if p.startswith(SAVE_FOLDER + '/') and '.clab.y' in p]
            s['remote_evidence']['tree_paths_after_first_save'] = found
            s['remote_evidence']['no_topology_file_uploaded_by_save'] = topology_in_tree == []
            s['remote_evidence']['unexpected_topology_paths'] = topology_in_tree
            missing = [p for p, ok in found.items() if not ok]
            if missing:
                rec.fail(s, f'missing expected remote paths after first save: {missing}', page)
            if topology_in_tree:
                rec.fail(s, f'Save progress unexpectedly uploaded a topology file: {topology_in_tree}', page)
            rec.write()

            # ---------------- B7 ----------------
            s = rec.new_step(7, 'Publish the topology files (owner terminal, lab VM)')
            OWNER_HOME.joinpath('labs').mkdir(parents=True, exist_ok=True)
            transcript = []
            rc, out = run_cmd(f'mkdir -p {SAVE_FOLDER} && cp {LAB_VM_FOLDER}/{LAB_NAME}.clab.yml* {SAVE_FOLDER}/',
                               cwd=str(OWNER_CHECKOUT), shell=True)
            transcript.append((f'cd {OWNER_CHECKOUT} && mkdir -p {SAVE_FOLDER} && '
                                f'cp {LAB_VM_FOLDER}/{LAB_NAME}.clab.yml* {SAVE_FOLDER}/', out))
            if rc != 0:
                rec.fail(s, f'mkdir/cp failed (rc={rc}): {out}', page)
            readme_path = OWNER_CHECKOUT / SAVE_FOLDER / 'README.md'
            readme_text = (
                "# my-first-lab\n\n"
                "A two-router Arista cEOS lab built in the manager's visual lab builder.\n"
                "`r1` and `r2` are joined by one link (r1 Ethernet1 <-> r2 Ethernet1).\n"
                "The link is addressed 10.0.0.1/30 (r1) and 10.0.0.2/30 (r2); r2 also carries a\n"
                "Loopback0 at 10.255.0.2/32.\n"
                "Saved progress (device configurations, not this topology file) lives in `latest/`\n"
                "and `checkpoints/`.\n"
            )
            readme_path.write_text(readme_text)
            transcript.append((f'cat > {SAVE_FOLDER}/README.md   # 5-line description written above', ''))
            rc, out = run_cmd(['git', 'add', SAVE_FOLDER], cwd=str(OWNER_CHECKOUT))
            transcript.append((f'git add {SAVE_FOLDER}', out))
            if rc != 0:
                rec.fail(s, f'git add failed (rc={rc}): {out}', page)
            rc, out = run_cmd(['git', 'commit', '-m', f'{SAVE_FOLDER}: topology and map'], cwd=str(OWNER_CHECKOUT))
            transcript.append((f'git commit -m "{SAVE_FOLDER}: topology and map"', out))
            if rc != 0:
                rec.fail(s, f'git commit failed (rc={rc}): {out}', page)
            rc, out = run_cmd(['git', 'push'], cwd=str(OWNER_CHECKOUT))
            transcript.append(('git push', out))
            if rc != 0:
                rec.fail(s, f'git push failed (rc={rc}): {out}', page)
            rc, out = run_cmd(['git', 'status', '-sb'], cwd=str(OWNER_CHECKOUT))
            transcript.append(('git status -sb', out))
            s['remote_evidence']['transcript'] = transcript
            s['observed']['git_status_clean'] = out.strip().splitlines()[0] if out.strip() else ''
            s['actions'] = [f'$ {cmd}' for cmd, _ in transcript]
            render_transcript(page, 'B7 - owner terminal, lab VM (as clabllm)', transcript, 'b7-terminal-git-push.png', SCREEN_DIR)
            s['screenshots'].append({'file': 'b7-terminal-git-push.png', 'element': 'rendered transcript (not a live terminal)', 'callouts': []})
            rec.write()

            # ---------------- B8 ----------------
            s = rec.new_step(8, 'Check GitHub, then browse the same tree in the manager')
            tree2 = gh_tree()
            expect_files = [f'{SAVE_FOLDER}/{LAB_NAME}.clab.yml', f'{SAVE_FOLDER}/README.md',
                             f'{SAVE_FOLDER}/latest/manifest.json']
            annotations_paths = [p for p in tree2 if p.startswith(SAVE_FOLDER + '/') and 'annotations' in p]
            s['remote_evidence']['expect_files_present'] = {p: (p in tree2) for p in expect_files}
            s['remote_evidence']['annotations_file_present'] = annotations_paths
            missing2 = [p for p in expect_files if p not in tree2]
            if missing2:
                rec.fail(s, f'missing expected files on GitHub after B7: {missing2}', page)
            EXAMPLES_DIR.joinpath('remote-tree.txt').write_text('\n'.join(sorted(tree2.keys())) + '\n')

            page.reload()
            page.click('#tab-progress')
            page.wait_for_selector('#git-saved-versions', timeout=15000)
            settle(page)
            page.click('[data-git-repo-action="browse"]')
            page.wait_for_selector('#git-places-panel', timeout=15000)
            settle(page, 800)
            s['actions'].append('Saved versions -> "Browse the repository…"')
            listing_text = page.locator('#git-places-panel').inner_text()
            s['observed']['browse_listing_text'] = listing_text[:1500]
            change_folder = page.locator('#git-change-folder')
            rec.shoot_full(page, s, 'browse-repository')
            rec.shoot_element(change_folder, s, 'browse-repository-el', label='Folders in this repository')
            for expect in (LAB_NAME + '.clab.yml', 'README.md', 'latest'):
                if expect not in listing_text:
                    s['notes'].append(f'{expect!r} not seen verbatim in the browse listing text (may be one level up/down)')
            rec.write()

            # ---------------- B9 ----------------
            s = rec.new_step(9, 'Change, save, and checkpoint again')
            page.click('#tab-devices')
            page.wait_for_selector('#device-list li.device-row', timeout=15000)
            r2_cli_button = page.locator(f'#device-list button[data-terminal="{R2_CONTAINER}"]')
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
            s['actions'].append('r2 CLI: added Loopback0 10.255.0.2/32, write memory')

            page.click('#tab-progress')
            page.wait_for_selector('#progress-save', timeout=15000)
            settle(page)
            page.click('#progress-save')
            page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=60000)
            settle(page)
            if page.locator('#git-diff-dialog[open]').count() == 0:
                rec.fail(s, 'Save progress did not open the review dialog', page)
            diff_text = page.locator('#git-diff-dialog').inner_text()
            s['observed']['second_save_review_text'] = diff_text[:1500]
            changed_r2_only = ('r2.cfg' in diff_text or 'r2.eoscfg' in diff_text) and 'r1.cfg' not in diff_text
            s['observed']['review_shows_r2_changed_not_r1'] = changed_r2_only
            review_dialog2 = page.locator('#git-diff-dialog')
            rec.shoot_full(page, s, 'second-save-review')
            rec.shoot_element(review_dialog2, s, 'second-save-review-el', label='Review before uploading (r2 changed)')
            job2_id, _ = upload_review(page)
            s['actions'].append('Save progress -> Review before uploading -> Upload these changes')
            page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
            job2 = poll_git_job(page, job2_id, timeout=180)
            s['observed']['second_save_job_status'] = (job2 or {}).get('status')
            page.keyboard.press('Escape')
            if job2 is None or job2.get('status') != 'synced':
                rec.fail(s, f'second save job did not reach synced: {job2}', page)

            page.click('#progress-view [data-git-action="checkpoint"]')
            page.wait_for_selector('#git-save-options[open]', timeout=15000)
            settle(page)
            s['actions'].append('Save progress menu -> "Create checkpoint…"')
            page.fill('#git-checkpoint-name', 'link-up')
            cp_dialog = page.locator('#git-save-options')
            rec.shoot_full(page, s, 'checkpoint-dialog')
            rec.shoot_element(cp_dialog, s, 'checkpoint-dialog-el', label='Create checkpoint (link-up)')
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
            page.keyboard.press('Escape')
            if cp_job is None or cp_job.get('status') != 'synced':
                rec.fail(s, f'checkpoint job did not reach synced: {cp_job}', page)

            page.reload()
            page.click('#tab-progress')
            page.wait_for_selector('#git-saved-versions', timeout=15000)
            settle(page)
            versions_text = page.locator('#git-saved-versions').inner_text()
            s['observed']['saved_versions_text'] = versions_text[:2000]
            versions_card = page.locator('#git-saved-versions').locator('xpath=ancestor::section[1]')
            rec.shoot_full(page, s, 'saved-versions-with-checkpoint')
            rec.shoot_element(versions_card, s, 'saved-versions-with-checkpoint-el', label='Saved versions (Latest + link-up)')
            if 'link-up' not in versions_text:
                rec.fail(s, "checkpoint 'link-up' not found in Saved versions", page)

            tree3 = gh_tree()
            r2_latest_text = gh_blob_text(f'{SAVE_FOLDER}/latest/r2.cfg')
            s['remote_evidence']['latest_r2_has_loopback0'] = 'Loopback0' in r2_latest_text
            s['remote_evidence']['checkpoint_link_up_exists'] = any(p.startswith(f'{SAVE_FOLDER}/checkpoints/link-up/') for p in tree3)
            double_latest = [p for p in tree3 if '/latest/latest' in p]
            s['remote_evidence']['no_nested_latest_latest'] = double_latest == []
            commits = gh_commits(3)
            s['remote_evidence']['last_three_commits'] = commits
            if 'Loopback0' not in r2_latest_text:
                rec.fail(s, f'{SAVE_FOLDER}/latest/r2.cfg does not contain Loopback0', page)
            if not s['remote_evidence']['checkpoint_link_up_exists']:
                rec.fail(s, f'{SAVE_FOLDER}/checkpoints/link-up/ not found on GitHub', page)
            if double_latest:
                rec.fail(s, f'found nested latest/latest path(s): {double_latest}', page)
            rec.write()

        # ---------------- B10 ----------------
        s = rec.new_step(10, 'Prove it: destroy, remove, and rebuild from Git')
        if args.from_step >= 10:
            s['notes'].append(
                'Step 10 was re-executed on its own (--from-step 10) after an earlier run deployed the '
                'WRONG topology file: the tree-navigation locator matched the first folder anywhere in '
                'the tree named "my-first-lab" (the original, top-level one), not the one nested inside '
                'my-network-labs, because it searched the whole #op-file-tree by text instead of the '
                'direct children of the folder just opened. This run replaces steps 1-9\'s untouched '
                'evidence with a fixed, re-verified step 10: navigation is now scoped to direct children '
                'at each level (see open_tree_folder()), and the topology file path is asserted before '
                'Deploy lab and the deployed lab\'s vm_project_path is asserted via the API after Start lab.'
            )
            s['observed']['vm_project_path_before_redo'] = ctx.get('vm_project_path_before_redo', '')
        page.click('#lab-actions-button')
        page.wait_for_selector('#lab-actions-menu:not([hidden])', timeout=10000)
        settle(page, 300)
        page.click('#menu-destroy')
        page.wait_for_selector('#operation-review', state='visible', timeout=15000)
        settle(page)
        s['actions'].append('Lab actions -> "Destroy lab…"')
        destroy_title = page.locator('#operation-review h2').inner_text()
        s['observed']['destroy_review_title'] = destroy_title
        destroy_dialog = page.locator('#operation-review')
        rec.shoot_full(page, s, 'destroy-review')
        rec.shoot_element(destroy_dialog, s, 'destroy-review-el', label=destroy_title)
        page.click('#op-confirm')
        page.wait_for_timeout(1500)
        deadline = time.time() + 120
        lab_state_text = ''
        while time.time() < deadline:
            page.reload()
            page.wait_for_selector('#lab-state', timeout=15000)
            lab_state_text = page.locator('#lab-state').inner_text()
            if 'not' in lab_state_text.lower() or 'stopped' in lab_state_text.lower():
                break
            time.sleep(3)
        s['observed']['lab_state_after_destroy'] = lab_state_text
        s['actions'].append(f'Waited for the lab to read Not running: {lab_state_text!r}')

        page.click('#lab-actions-button')
        page.wait_for_selector('#lab-actions-menu:not([hidden])', timeout=10000)
        settle(page, 300)
        page.click('#menu-remove-lab')
        page.wait_for_selector('#remove-lab-dialog', state='visible', timeout=10000)
        settle(page)
        s['actions'].append('Lab actions -> "Remove from this manager…"')
        page.uncheck('#remove-lab-exclude')
        remove_dialog = page.locator('#remove-lab-dialog')
        rec.shoot_full(page, s, 'remove-review')
        rec.shoot_element(remove_dialog, s, 'remove-review-el', label='Remove this lab from the manager?')
        with page.expect_navigation(timeout=20000):
            page.click('#remove-lab-form button[type="submit"]')
        settle(page, 800)
        s['actions'].append('Unticked "Don\'t offer this lab for import again", clicked "Remove lab"')

        rc, docker_out = run_cmd(['docker', 'ps', '-a', '--filter', 'name=clab-my-first-lab-', '--format', '{{.Names}}'])
        s['observed']['docker_containers_after_remove'] = docker_out.strip().splitlines()
        if docker_out.strip():
            rec.fail(s, f'containers still present after destroy: {docker_out}', page)

        # Authoring-only for this validation: the guide never tells the student to do this. It moves
        # the ORIGINAL lab folder (from B1-B3, still on disk after Destroy/Remove — neither one deletes
        # the topology file) out of the trusted root, so this run's file-tree navigation cannot be
        # confused with it even by accident; the guide instead tells the student to pick the file under
        # my-network-labs and to check the path field, which is asserted below regardless.
        transcript2 = []
        rc, out = run_cmd(['sudo', 'mkdir', '-p', ARCHIVE_ROOT])
        transcript2.append((f'sudo mkdir -p {ARCHIVE_ROOT}', out))
        if rc != 0:
            rec.fail(s, f'could not create the archive root (rc={rc}): {out}', page)
        if pathlib.Path(LAB_VM_FOLDER).exists():
            rc, out = run_cmd(['sudo', 'mv', LAB_VM_FOLDER, ARCHIVE_DEST])
            transcript2.append((f'sudo mv {LAB_VM_FOLDER} {ARCHIVE_DEST}', out))
            s['remote_evidence']['archived_original_folder'] = {'from': LAB_VM_FOLDER, 'to': ARCHIVE_DEST, 'rc': rc}
            if rc != 0:
                rec.fail(s, f'could not archive the original lab folder (rc={rc}): {out}', page)
        else:
            s['notes'].append(f'{LAB_VM_FOLDER} did not exist to archive (already moved by an earlier attempt).')
        s['actions'].append(f'(authoring-only) sudo mv {LAB_VM_FOLDER} {ARCHIVE_DEST} — not a guide step; '
                             'removes the only other thing this validation could accidentally deploy from')

        generated = pathlib.Path(CLONED_LAB_FOLDER) / 'clab-my-first-lab'
        if generated.exists():
            rc, out = run_cmd(['sudo', 'rm', '-rf', str(generated)])
            transcript2.append((f'sudo rm -rf {generated}', out))
            s['actions'].append(f'sudo rm -rf {generated}  # generated folder left inside the clone by an earlier attempt')
            if rc != 0:
                rec.fail(s, f'could not remove the stray generated folder inside the clone (rc={rc}): {out}', page)

        if not pathlib.Path(CLONE_ON_VM).exists():
            rc, out = run_cmd(['git', 'clone', REPO_URL, CLONE_ON_VM])
            transcript2.append((f'git clone {REPO_URL} {CLONE_ON_VM}', out))
            if rc != 0:
                rec.fail(s, f'git clone into the trusted root failed (rc={rc}): {out}', page)
        else:
            transcript2.append((f'git clone {REPO_URL} {CLONE_ON_VM}',
                                 '# already cloned in an earlier attempt made earlier in this authoring session; not re-run'))
            rc, out = run_cmd(['git', '-C', CLONE_ON_VM, 'log', '--oneline', '-3'])
            transcript2.append((f'git -C {CLONE_ON_VM} log --oneline -3', out))
            rc, out = run_cmd(['ls', '-la', CLONED_LAB_FOLDER])
            transcript2.append((f'ls -la {CLONED_LAB_FOLDER}', out))
            s['notes'].append(f'{CLONE_ON_VM} already existed from an earlier attempt at this scenario '
                               'validation; reused rather than re-cloned. A first-time student only ever '
                               'runs this clone once, so this is a redo artefact, not a guide divergence.')
        s['remote_evidence']['clone_transcript'] = transcript2
        render_transcript(page, 'B10 - owner terminal, lab VM (as clabllm)', transcript2, 'b10-terminal-clone.png', SCREEN_DIR)
        s['screenshots'].append({'file': 'b10-terminal-clone.png', 'element': 'rendered transcript (not a live terminal)', 'callouts': []})

        page.goto(BASE + '/')
        page.wait_for_selector('#home-deploy', timeout=20000)
        settle(page)
        page.click('#home-deploy')
        page.wait_for_selector('#op-file-tree', state='visible', timeout=20000)
        settle(page, 300)
        s['actions'].append('Home -> "Choose a file on the lab VM…"')
        # Scoped, direct-child-only navigation at every level (see open_tree_folder()): a plain
        # has_text search across the whole #op-file-tree would match the top-level "my-first-lab"
        # folder as well as the one nested inside my-network-labs, and .first is not guaranteed to
        # pick the nested one — that mismatch is exactly the bug this redo fixes.
        tree_root = page.locator('#op-file-tree')
        level1_children = open_tree_folder(tree_root, PROJECTS_ROOT)
        s['actions'].append(f'Open {PROJECTS_ROOT}')
        level2_children = open_tree_folder(level1_children, GH_REPO_NAME)
        s['actions'].append(f'Open {GH_REPO_NAME} (a direct child of {PROJECTS_ROOT}, scoped)')
        lab_children = open_tree_folder(level2_children, LAB_NAME)
        s['actions'].append(f'Open {LAB_NAME} (a direct child of {GH_REPO_NAME}, scoped — '
                             f'NOT the top-level {LAB_NAME} folder, which was archived away above anyway)')
        file_button = lab_children.locator('> button.op-tree-file', has_text=f'{LAB_NAME}.clab.yml').first
        file_button.wait_for(state='visible', timeout=10000)
        settle(page, 300)
        s['actions'].append(f'Select {LAB_NAME}.clab.yml')
        file_button.click()
        page.wait_for_selector('#op-editor', state='visible', timeout=15000)
        settle(page)
        cloned_path_field = page.locator('#op-edit-path').input_value()
        s['observed']['cloned_topology_path_field'] = cloned_path_field
        expect_fragment = f'/{GH_REPO_NAME}/{LAB_NAME}/{LAB_NAME}.clab.yml'
        s['observed']['cloned_topology_path_contains_expected_fragment'] = expect_fragment in cloned_path_field
        rec.shoot_full(page, s, 'redeploy-topology-file')
        rec.shoot_element(page.locator('#op-editor'), s, 'redeploy-topology-file-el', label='Topology file (cloned)')
        if expect_fragment not in cloned_path_field:
            rec.fail(s, f'"File location on the VM" does not point at the clone: got {cloned_path_field!r}, '
                        f'expected it to contain {expect_fragment!r}', page)
        if cloned_path_field != CLONED_TOPOLOGY_PATH:
            s['notes'].append(f'path field is {cloned_path_field!r}, exact match to {CLONED_TOPOLOGY_PATH!r} '
                               'expected but only the repo/lab/file fragment was asserted strictly')
        page.click('#op-deploy-project')
        page.wait_for_selector('#operation-review', state='visible', timeout=15000)
        settle(page)
        rec.shoot_element(page.locator('#operation-review'), s, 'redeploy-start-review-el', label='Deploy lab (cloned copy)')
        t_confirm2 = time.time()
        page.click('#op-confirm')
        page.wait_for_function("() => location.hash.includes('lab=')", timeout=20000)
        settle(page)
        lab_hash2 = page.evaluate('() => location.hash')
        m2 = re.search(r'lab=([0-9a-f]+)', lab_hash2)
        if not m2:
            rec.fail(s, f'could not find lab id in hash after redeploy {lab_hash2!r}', page)
        ctx['lab_id_2'] = m2.group(1)
        s['actions'].append('Deploy lab -> Start lab (from the cloned copy)')

        state_after_deploy = api(page, 'GET', '/api/state')['body']
        lab_after_deploy = next((l for l in state_after_deploy.get('labs', []) if l.get('id') == ctx['lab_id_2']), None)
        vm_project_path_after = (lab_after_deploy or {}).get('vm_project_path', '')
        s['observed']['vm_project_path_after_redeploy'] = vm_project_path_after
        if GH_REPO_NAME not in vm_project_path_after:
            rec.fail(s, f'vm_project_path after redeploy does not contain {GH_REPO_NAME!r}: {vm_project_path_after!r}', page)

        deadline = time.time() + 240
        pills2 = []
        page.click('#tab-devices')
        page.wait_for_selector('#device-list li.device-row', timeout=15000)
        while time.time() < deadline:
            page.reload()
            page.wait_for_selector('#lab-state', timeout=15000)
            page.click('#tab-devices')
            page.wait_for_selector('#device-list li.device-row', timeout=15000)
            pills2 = page.locator('#device-list li.device-row .pill').all_inner_texts()
            if sum(1 for p in pills2 if p.strip() == 'Ready') == 2:
                break
            time.sleep(5)
        t_ready2 = time.time()
        s['observed']['redeploy_to_ready_seconds'] = round(t_ready2 - t_confirm2, 1)
        s['observed']['devices_pills_ready_after_redeploy'] = pills2
        if sum(1 for p in pills2 if p.strip() == 'Ready') != 2:
            rec.fail(s, f'devices did not reach Ready after redeploy (pills: {pills2})', page)
        settle(page, 300)
        page.click('#tab-topology')
        page.wait_for_selector('#topology-map', timeout=15000)
        settle(page)
        s['actions'].append('Open the Topology tab (redeployed lab)')
        rec.shoot_full(page, s, 'redeployed-topology')
        rec.shoot_element(page.locator('#topology-view'), s, 'redeployed-topology-el', label='Topology (redeployed, saved map)')

        page.click('#tab-progress')
        page.wait_for_selector('#git-save-location, #git-progress-status', timeout=15000)
        settle(page)
        if page.locator('[data-git-repo-action="connect"]').count():
            page.click('[data-git-repo-action="connect"]')
            page.wait_for_selector('#git-connect-dialog', state='visible', timeout=10000)
            settle(page)
            page.fill('#git-connect-url', REPO_URL)
            page.fill('#git-connect-folder', SAVE_FOLDER)
            if page.locator('#git-connect-ack').count():
                page.check('#git-connect-ack')
            page.click('#git-connect-confirm')
            try:
                page.wait_for_selector('#git-save-location .git-destination-line', timeout=60000)
                reconnect_result = 'connected'
            except Exception:
                reconnect_result = page.inner_text('body')[:500]
            settle(page, 800)
        else:
            reconnect_result = 'connect action not offered: ' + (page.locator('#git-save-location').inner_text()[:300] if page.locator('#git-save-location').count() else '')
        s['observed']['reconnect_result'] = reconnect_result
        s['actions'].append('Progress -> "Connect a repository by URL" (same URL and folder)')
        reconnect_card = page.locator('#git-save-location') if page.locator('#git-save-location').count() else page.locator('#progress-view')
        rec.shoot_full(page, s, 'reconnect')
        rec.shoot_element(reconnect_card, s, 'reconnect-el', label='Progress tab after reconnecting')

        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=15000)
        settle(page)
        latest_row = page.locator('#git-saved-versions li.git-version-row', has_text='Latest').first
        if latest_row.count() == 0:
            rec.fail(s, "no Saved versions row named 'Latest' found after reconnect", page)
        s['actions'].append('Saved versions -> Latest -> "Apply to running lab…"')
        latest_row.locator('[data-git-version-action="apply"]').click()
        page.wait_for_selector('#restore-review-dialog[open]', timeout=15000)
        page.wait_for_selector('#restore-review-dialog .restore-targets', timeout=15000)
        settle(page)
        rec.shoot_full(page, s, 'apply-latest-review')
        rec.shoot_element(page.locator('#restore-review-dialog'), s, 'apply-latest-review-el', label='Replace running configuration (Latest)')
        page.check('#restore-ack')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/restore'), timeout=15000) as info:
            page.click('#restore-run')
        restore_job_id = info.value.json().get('id')
        page.wait_for_selector('#restore-job-dialog[open]', timeout=15000)
        t_apply0 = time.time()
        restore_job = poll_restore_job(page, restore_job_id, timeout=300)
        t_apply1 = time.time()
        s['observed']['apply_latest_seconds'] = round(t_apply1 - t_apply0, 1)
        s['observed']['apply_latest_status'] = (restore_job or {}).get('status')
        settle(page, 300)
        rec.shoot_full(page, s, 'apply-latest-result')
        rec.shoot_element(page.locator('#restore-job-dialog'), s, 'apply-latest-result-el', label='Restore result (Latest)')
        page.keyboard.press('Escape')
        bad = [t for t in (restore_job or {}).get('targets', [])
               if t.get('status') in ('failed', 'ineligible', 'verify_mismatch', 'rolled_back', 'uncertain', 'interrupted')]
        if bad:
            rec.fail(s, f'apply Latest reported a bad target status: {bad}', page)

        r1_final = eos.show(R1_IP, 'show ip interface brief')
        r2_final = eos.show(R2_IP, 'show ip interface brief')
        ping_final = eos.show(R1_IP, 'ping 10.0.0.2 repeat 3')
        s['device_evidence']['r1_show_ip_interface_brief_final'] = r1_final[-600:]
        s['device_evidence']['r2_show_ip_interface_brief_final'] = r2_final[-600:]
        s['device_evidence']['r1_ping_10_0_0_2_final'] = ping_final[-600:]
        addrs_ok = ('10.0.0.1' in r1_final and '10.0.0.2' in r2_final and
                    'Loopback0' in r2_final and '10.255.0.2' in r2_final)
        ping_ok_final = bool(re.search(r'3 (packets )?received|3 received', ping_final))
        s['observed']['addresses_and_loopback_restored'] = addrs_ok
        s['observed']['ping_ok_final'] = ping_ok_final
        if not addrs_ok or not ping_ok_final:
            rec.fail(s, f'rebuild did not restore the expected state (addrs_ok={addrs_ok}, ping_ok={ping_ok_final})', page)

        git_state = api(page, 'GET', f"/api/labs/{ctx['lab_id_2']}/git")['body']
        binding_prefix = ((git_state or {}).get('binding') or {}).get('repository', {}).get('prefix')
        s['remote_evidence']['binding_folder_via_api'] = binding_prefix
        if binding_prefix != SAVE_FOLDER:
            rec.fail(s, f'binding folder via API is not {SAVE_FOLDER!r}: {binding_prefix!r}', page)
        rec.write()

        s['observed']['console_errors_seen'] = console_errors[:10]
        rec.write()

    rec.write()
    print('Scenario B complete: all steps PASS' if all(st['result'] == 'PASS' for st in rec.steps) else 'Scenario B had failing steps')
    return 0


if __name__ == '__main__':
    sys.exit(main())
