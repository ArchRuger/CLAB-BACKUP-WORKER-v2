#!/usr/bin/env python3
"""Section B, row B8: after B7's apply, Save progress targets save-fix/working/latest again;
save-fix/Final and l10-evpn's binding/files are untouched.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b8_after_apply.py \\
        --evidence docs/save-location-fix/evidence/17-b8-after-apply.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, click_save_with_retry, open_lab, poll_job, upload_review

NODECLI_DIR = pathlib.Path(__file__).parent.parent.parent / 'multi-platform-restore' / 'tools'
sys.path.insert(0, str(NODECLI_DIR))
REPO = pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'
L10_EVPN_ID = '797db5fc9757415eb008a1a98b6c9787'


def ceos_change(text):
    from nodecli import Session
    s = Session('ceos', timeout=30)
    try:
        for line in ('enable', 'configure', 'interface Ethernet2', 'description ' + text, 'end', 'write memory'):
            s.run(line)
    finally:
        s.close()


def git_tree_hash(path):
    out = subprocess.run(['git', '-C', str(REPO), 'ls-tree', 'HEAD', '--', path], capture_output=True, text=True, check=True).stdout.strip()
    return out.split()[2] if out else None


def git_ls_tree(path):
    return subprocess.run(['git', '-C', str(REPO), 'ls-tree', '-r', '--name-only', 'HEAD', '--', path],
                           capture_output=True, text=True, check=True).stdout.splitlines()


def git_fetch():
    subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', '--quiet'], check=True)


def git_rev(ref='HEAD'):
    return subprocess.run(['git', '-C', str(REPO), 'rev-parse', ref], capture_output=True, text=True, check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31',
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    c = Checker()

    git_fetch()
    record['steps']['final_tree_before'] = git_tree_hash('save-fix/Final')
    record['steps']['l10_evpn_files_before'] = sorted(git_ls_tree('l10-evpn/work'))

    l10_before_resp = None
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)
        l10_before_resp = api(page, 'GET', f'/api/labs/{L10_EVPN_ID}/git')['body']
        record['steps']['l10_evpn_binding_before'] = l10_before_resp.get('binding')

        ceos_change('QA-B8-after-apply')
        attempts = click_save_with_retry(page)
        record['steps']['save_attempts'] = attempts
        job_id, retry_resp = upload_review(page)
        page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
        job = poll_job(page, job_id)
        record['steps']['final_job'] = job
        c.check('B8 save reached synced', job and job.get('status') == 'synced', job)
        c.check('B8 snapshot_path is save-fix/working/latest', (job or {}).get('snapshot_path') == 'save-fix/working/latest', job)
        page.keyboard.press('Escape')
        page.wait_for_timeout(1000)

        l10_after_resp = api(page, 'GET', f'/api/labs/{L10_EVPN_ID}/git')['body']
        record['steps']['l10_evpn_binding_after'] = l10_after_resp.get('binding')
        c.check('l10-evpn binding unchanged', l10_before_resp.get('binding') == l10_after_resp.get('binding'),
                (l10_before_resp.get('binding'), l10_after_resp.get('binding')))

        c.check('no page or console errors', not errors, errors[:8])
        browser.close()

    git_fetch()
    record['steps']['final_tree_after'] = git_tree_hash('save-fix/Final')
    record['steps']['l10_evpn_files_after'] = sorted(git_ls_tree('l10-evpn/work'))
    c.check('save-fix/Final blobs unchanged', record['steps']['final_tree_before'] == record['steps']['final_tree_after'],
            (record['steps']['final_tree_before'], record['steps']['final_tree_after']))
    c.check('l10-evpn/work files unchanged', record['steps']['l10_evpn_files_before'] == record['steps']['l10_evpn_files_after'],
            (len(record['steps']['l10_evpn_files_before']), len(record['steps']['l10_evpn_files_after'])))

    record['steps']['final_git'] = {'local': git_rev('HEAD'), 'origin': git_rev('origin/main')}
    record['steps']['final_git']['in_sync'] = record['steps']['final_git']['local'] == record['steps']['final_git']['origin']
    c.check('local HEAD == origin/main at the end of B8', record['steps']['final_git']['in_sync'], record['steps']['final_git'])

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
