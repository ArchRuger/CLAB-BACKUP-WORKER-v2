#!/usr/bin/env python3
"""Section B, rows B1-B2: four real Save Latest cycles into save-fix/working/latest.

Each save makes one distinguishable, reversible change on ceos only (an Ethernet2 description, never
OSPF/loopbacks) over a fresh SSH session (docs/multi-platform-restore/tools/nodecli.py), then goes
through the real Progress tab: Save progress -> review -> Upload these changes. Runs:
  1 (B1)  after B0's rebind to save-fix/working
  2a (B2) after browsing to save-fix/working/latest in the folder browser (disabled -- already bound)
  2b (B2) after a full page reload
  2c (B2) after a real `docker restart` of the manager container (waits for /api/state + readiness)

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b1_b2_saves.py \\
        --evidence docs/save-location-fix/evidence/11-b1-b2-saves.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import (BASE, LAB_ID, LAB_NAME, Checker, api, click_save_with_retry, destination_line,
                     open_change_folder, open_lab, poll_job, upload_review, go_to)

NODECLI = pathlib.Path(__file__).parent.parent.parent / 'multi-platform-restore' / 'tools' / 'nodecli.py'
sys.path.insert(0, str(NODECLI.parent))


def ceos_change(text):
    from nodecli import Session
    s = Session('ceos', timeout=30)
    try:
        for line in ('enable', 'configure', 'interface Ethernet2', 'description ' + text, 'end', 'write memory'):
            s.run(line)
    finally:
        s.close()


def save_cycle(page, c, record, key, change_text):
    ceos_change(change_text)
    record['steps'][key] = {'change': change_text}
    attempts = click_save_with_retry(page)
    record['steps'][key]['save_attempts'] = attempts
    review_text = page.locator('#git-diff-dialog').inner_text() if page.locator('#git-diff-dialog[open]').count() else ''
    record['steps'][key]['review_excerpt'] = review_text[:800]
    job_id, retry_resp = upload_review(page)
    record['steps'][key]['retry_response'] = retry_resp
    page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
    job = poll_job(page, job_id)
    record['steps'][key]['final_job'] = job
    page.keyboard.press('Escape')
    page.wait_for_timeout(1000)
    c.check(f'{key}: job reached a synced state', job and job.get('status') == 'synced', job and job.get('status'))
    c.check(f'{key}: snapshot_path == save-fix/working/latest (not nested)',
            (job or {}).get('snapshot_path') == 'save-fix/working/latest', (job or {}).get('snapshot_path'))
    return job


def git_ls_tree(path):
    out = subprocess.run(['git', '-C', str(pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'),
                           'ls-tree', '-r', '--name-only', 'HEAD', '--', path],
                          capture_output=True, text=True, check=True).stdout
    return sorted(out.splitlines())


def git_rev(ref='HEAD'):
    return subprocess.run(['git', '-C', str(pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'), 'rev-parse', ref],
                           capture_output=True, text=True, check=True).stdout.strip()


def git_tree_hash(path):
    out = subprocess.run(['git', '-C', str(pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'),
                           'ls-tree', 'HEAD', '--', path], capture_output=True, text=True, check=True).stdout.strip()
    return out.split()[2] if out else None


def git_log_oneline(path):
    out = subprocess.run(['git', '-C', str(pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'),
                           'log', '--oneline', '--', path], capture_output=True, text=True, check=True).stdout
    return out.splitlines()


def wait_manager_ready(timeout=180):
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(BASE + '/api/state', method='GET', headers={'Content-Length': '0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31',
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    c = Checker()

    record['steps']['legacy_nested_tree_hash_before'] = git_tree_hash('save-fix/working/latest/latest')
    record['steps']['manifest_log_before'] = git_log_oneline('save-fix/working/latest/manifest.json')

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        # ---- B1: first save after B0's rebind ----
        open_lab(page)
        record['steps']['destination_before_b1'] = destination_line(page)
        page.screenshot(path=f'{args.shots}/1x-b1-before-save.png')
        save_cycle(page, c, record, 'b1', 'QA-B1 save test')

        # ---- B2a: browse to save-fix/working/latest first (proves no accidental rebind/nest), then save ----
        open_change_folder(page)
        go_to(page, 'save-fix')
        go_to(page, 'save-fix/working')
        go_to(page, 'save-fix/working/latest')
        page.wait_for_timeout(300)
        use_button = page.locator('#git-places-panel [data-git-places-action="use"]')
        record['steps']['b2a_browse_use_button'] = {
            'count': use_button.count(), 'enabled': bool(use_button.count() and use_button.is_enabled()),
            'title': use_button.get_attribute('title') if use_button.count() else None,
        }
        c.check('b2a: browsing to the lab\'s own save-fix/working/latest folder shows "already saves here" (disabled), no rebind offered',
                use_button.count() == 1 and not use_button.is_enabled(), record['steps']['b2a_browse_use_button'])
        page.screenshot(path=f'{args.shots}/1x-b2a-browse-latest.png')
        # Close the folder browser panel without submitting anything, then do the real save.
        details = page.locator('#git-change-folder')
        if details.count() and details.get_attribute('open') is not None:
            page.click('#git-change-folder summary')
        save_cycle(page, c, record, 'b2a', 'QA-B2a save test')

        # ---- B2b: page reload, then save ----
        open_lab(page, reload=True)
        record['steps']['destination_before_b2b'] = destination_line(page)
        save_cycle(page, c, record, 'b2b', 'QA-B2b save test')

        c.check('no page or console errors before restart', not errors, errors[:8])
        browser.close()

    # ---- B2c: real docker restart of the manager container, then save ----
    restart_out = subprocess.run(['docker', 'restart', 'containerlab-node-manager-backup-ui-1'],
                                  capture_output=True, text=True)
    record['steps']['b2c_docker_restart'] = {'returncode': restart_out.returncode, 'stdout': restart_out.stdout.strip(), 'stderr': restart_out.stderr.strip()}
    ready = wait_manager_ready()
    record['steps']['b2c_manager_ready_after_restart'] = ready
    c.check('manager /api/state answers again after docker restart', ready)
    # Also wait for the lab's own node readiness to settle back to Ready before saving (a restart
    # briefly re-checks readiness).
    time.sleep(5)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors2 = []
        page.on('pageerror', lambda e: errors2.append(str(e)))
        page.on('console', lambda m: errors2.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        open_lab(page)
        record['steps']['destination_after_restart'] = destination_line(page)
        save_cycle(page, c, record, 'b2c', 'QA-B2c save test')
        c.check('no page or console errors after restart save', not errors2, errors2[:8])
        browser.close()

    # ---- Independent Git verification ----
    local_head = git_rev('HEAD')
    subprocess.run(['git', '-C', str(pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'), 'fetch', 'origin', '--quiet'], check=True)
    origin_head = git_rev('origin/main')
    record['steps']['git_verification'] = {
        'local_head': local_head, 'origin_head': origin_head, 'in_sync': local_head == origin_head,
        'ls_tree_save_fix_working': git_ls_tree('save-fix/working'),
        'legacy_nested_tree_hash_after': git_tree_hash('save-fix/working/latest/latest'),
        'manifest_log_after': git_log_oneline('save-fix/working/latest/manifest.json'),
    }
    c.check('local HEAD == origin/main after all four saves', local_head == origin_head, (local_head, origin_head))
    c.check('the legacy nested save-fix/working/latest/latest tree is byte-identical (unchanged) across all four saves',
            record['steps']['legacy_nested_tree_hash_before'] == record['steps']['git_verification']['legacy_nested_tree_hash_after'],
            (record['steps']['legacy_nested_tree_hash_before'], record['steps']['git_verification']['legacy_nested_tree_hash_after']))
    c.check('no double-nested save-fix/working/latest/latest/latest was created',
            not any('latest/latest/latest' in p for p in record['steps']['git_verification']['ls_tree_save_fix_working']),
            record['steps']['git_verification']['ls_tree_save_fix_working'])
    manifest_log = record['steps']['git_verification']['manifest_log_after']
    c.check('git log -- save-fix/working/latest/manifest.json shows every save\'s commit (history intact, >= 5 commits: original + B1 + 3xB2)',
            len(manifest_log) >= 5, manifest_log)

    record['checks'] = c.checks
    record['failed'] = c.failed
    record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'{passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
