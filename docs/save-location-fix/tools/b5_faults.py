#!/usr/bin/env python3
"""Section B, row B5: fault injection -- incomplete capture, then a failed push and its retry.

(a) assign the QA-wrong-password-ceos profile to ceos, Save progress -> expect capture_incomplete,
    prove save-fix/working/latest is unchanged (HEAD unchanged), restore the right credentials.
(b) gh auth switch to ArchRuger (no push right to pruger-dev's repo), make a change, save, review,
    upload -> expect push_pending, local commit present; switch back to pruger-dev, retry from the
    page (Upload now) -> synced, no duplicate nesting, no second commit. Leaves gh on pruger-dev.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b5_faults.py \\
        --evidence docs/save-location-fix/evidence/14-b5-faults.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, click_save_with_retry, destination_line, open_lab, poll_job, upload_review

NODECLI_DIR = pathlib.Path(__file__).parent.parent.parent / 'multi-platform-restore' / 'tools'
sys.path.insert(0, str(NODECLI_DIR))
REPO = pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'
CEOS_NODE_NAME = 'clab-restore-square-ceos'
WRONG_PROFILE_ID = '311acce74c984d03a811fd789a821fe6'  # QA-wrong-password-ceos


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


def git_fetch():
    subprocess.run(['git', '-C', str(REPO), 'fetch', 'origin', '--quiet'], check=True)


def git_rev(ref='HEAD'):
    return subprocess.run(['git', '-C', str(REPO), 'rev-parse', ref], capture_output=True, text=True, check=True).stdout.strip()


def gh_active_account():
    out = subprocess.run(['gh', 'auth', 'status'], capture_output=True, text=True).stdout + subprocess.run(['gh', 'auth', 'status'], capture_output=True, text=True).stderr
    lines = out.splitlines()
    current = None
    for line in lines:
        if 'Logged in to github.com account' in line:
            current = line.strip().split('account ')[1].split(' ')[0]
        if 'Active account: true' in line:
            return current
    return None


def gh_switch(user):
    r = subprocess.run(['gh', 'auth', 'switch', '-u', user], capture_output=True, text=True)
    return {'returncode': r.returncode, 'stdout': r.stdout.strip(), 'stderr': r.stderr.strip(), 'active_after': gh_active_account()}


def node_edit_payload(node, profile_id):
    return {'name': node['name'], 'address': node['address'], 'port': node['port'], 'platform': node['platform'],
            'profile_id': profile_id, 'enabled': node['enabled'], 'short_name': node['short_name'], 'endpoint_mode': node['endpoint_mode']}


def get_ceos_node(page):
    state = api(page, 'GET', '/api/state')['body']
    for lab in state['labs']:
        if lab['id'] == LAB_ID:
            for n in lab['nodes']:
                if n['name'] == CEOS_NODE_NAME:
                    return n
    return None


def wait_readiness(page, expect='Ready', timeout=180):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        node = get_ceos_node(page)
        last = node.get('readiness') if node else None
        if last == expect:
            return True, last
        time.sleep(3)
    return False, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31',
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    c = Checker()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)

        # ==================== (a) incomplete capture ====================
        node_before = get_ceos_node(page)
        record['steps']['a_node_before'] = {'profile_id': node_before.get('profile_id'), 'readiness': node_before.get('readiness')}
        git_fetch()
        tree_before_fault = git_tree_hash('save-fix/working/latest')
        head_before_fault = git_rev('HEAD')
        record['steps']['a_git_before'] = {'tree_hash': tree_before_fault, 'head': head_before_fault}

        assign_resp = api(page, 'PUT', '/api/labs/' + LAB_ID + '/node', node_edit_payload(node_before, WRONG_PROFILE_ID))
        record['steps']['a_assign_wrong_profile'] = assign_resp
        c.check('assigning QA-wrong-password-ceos to ceos returned 200', assign_resp['status'] == 200, assign_resp)

        not_ready, readiness_after_wrong = wait_readiness(page, expect='Ready', timeout=1)  # quick single read, no wait needed to prove not-ready yet
        record['steps']['a_readiness_after_assign'] = readiness_after_wrong

        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)
        page.click('#progress-save')
        try:
            page.wait_for_selector('#git-diff-dialog[open], #git-job-dialog[open]', timeout=60000)
        except Exception:
            pass
        opened = 'diff' if page.locator('#git-diff-dialog[open]').count() else ('job' if page.locator('#git-job-dialog[open]').count() else 'none')
        job_text = ''
        if opened == 'job':
            job_text = page.locator('#git-job-dialog').inner_text()
            page.screenshot(path=f'{args.shots}/1x-b5-capture-incomplete.png')
        record['steps']['a_save_attempt'] = {'dialog_opened': opened, 'job_text': job_text[:500]}
        page.wait_for_timeout(2000)
        jobs = api(page, 'GET', f'/api/labs/{LAB_ID}/git')['body']['jobs']
        newest = jobs[0] if jobs else None
        record['steps']['a_newest_job'] = newest
        c.check('Save progress with wrong ceos credentials reports capture_incomplete',
                newest and newest.get('status') == 'capture_incomplete', newest)
        if opened != 'none':
            page.keyboard.press('Escape')

        git_fetch()
        tree_after_fault = git_tree_hash('save-fix/working/latest')
        head_after_fault = git_rev('HEAD')
        record['steps']['a_git_after'] = {'tree_hash': tree_after_fault, 'head': head_after_fault}
        c.check('save-fix/working/latest tree unchanged after the incomplete capture', tree_before_fault == tree_after_fault, (tree_before_fault, tree_after_fault))
        c.check('local HEAD unchanged after the incomplete capture', head_before_fault == head_after_fault, (head_before_fault, head_after_fault))

        # restore the right credentials
        restore_resp = api(page, 'PUT', '/api/labs/' + LAB_ID + '/node', node_edit_payload(node_before, ''))
        record['steps']['a_restore_profile'] = restore_resp
        c.check('restoring the default/inventory credential (profile_id="") returned 200', restore_resp['status'] == 200, restore_resp)
        ready_again, final_readiness = wait_readiness(page, expect='Ready', timeout=120)
        record['steps']['a_readiness_restored'] = final_readiness
        c.check('ceos readiness returns to Ready after restoring the credential', ready_again, final_readiness)

        c.check('no page or console errors in part (a)', not errors, errors[:8])
        browser.close()

    # ==================== (b) failed push, then retry ====================
    before_account = gh_active_account()
    record['steps']['b_gh_account_before'] = before_account
    switch_wrong = gh_switch('ArchRuger')
    record['steps']['b_gh_switch_to_archruger'] = switch_wrong
    c.check('gh auth switch -u ArchRuger succeeded', switch_wrong['active_after'] == 'ArchRuger', switch_wrong)

    ceos_change('QA-B5-failed-push')
    git_fetch()
    origin_before_fail = git_rev('origin/main')
    local_before_fail = git_rev('HEAD')

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors2 = []
        page.on('pageerror', lambda e: errors2.append(str(e)))
        page.on('console', lambda m: errors2.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        open_lab(page)
        attempts = click_save_with_retry(page)
        record['steps']['b_save_attempts'] = attempts
        review_text = page.locator('#git-diff-dialog').inner_text() if page.locator('#git-diff-dialog[open]').count() else ''
        page.screenshot(path=f'{args.shots}/1x-b5-review-before-failed-push.png')
        job_id, retry_resp = upload_review(page)
        record['steps']['b_retry_response'] = retry_resp
        page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
        job_failed_push = poll_job(page, job_id)
        record['steps']['b_job_after_failed_push'] = job_failed_push
        job_dialog_text = page.locator('#git-job-dialog').inner_text()
        record['steps']['b_job_dialog_text'] = job_dialog_text[:600]
        page.screenshot(path=f'{args.shots}/1x-b5-push-pending.png')
        c.check('save with wrong gh account reports push_pending (saved on the VM, push failed)',
                job_failed_push and job_failed_push.get('status') == 'push_pending' and not job_failed_push.get('pushed'), job_failed_push)
        page.keyboard.press('Escape')

        git_fetch()
        origin_after_fail = git_rev('origin/main')
        local_after_fail = git_rev('HEAD')
        record['steps']['b_git_after_fail'] = {'origin_before': origin_before_fail, 'origin_after': origin_after_fail,
                                                 'local_before': local_before_fail, 'local_after': local_after_fail}
        c.check('origin/main unchanged after the failed push', origin_before_fail == origin_after_fail, (origin_before_fail, origin_after_fail))
        c.check('local checkout HAS the new commit even though the push failed', local_after_fail != local_before_fail, (local_before_fail, local_after_fail))

        # ---- switch back, retry from the page ----
        switch_back = gh_switch('pruger-dev')
        record['steps']['b_gh_switch_back'] = switch_back
        c.check('gh auth switch -u pruger-dev succeeded', switch_back['active_after'] == 'pruger-dev', switch_back)

        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saves-list', timeout=20000)
        row = page.locator(f'#git-saves-list [data-git-job="{job_id}"]')
        for _ in range(20):
            page.locator('#git-saves-list').scroll_into_view_if_needed()
            if row.count() and row.get_attribute('open') is None:
                row.locator('summary').click()
            page.wait_for_timeout(500)
            upload_btn = row.locator('[data-git-job-upload]')
            if upload_btn.count() and upload_btn.is_visible():
                break
        upload_btn = row.locator('[data-git-job-upload]')
        upload_label = upload_btn.inner_text() if upload_btn.count() else None
        record['steps']['b_retry_button_label'] = upload_label
        c.check('Recent saves offers "Upload now" for the push_pending job (already reviewed)', upload_label == 'Upload now', upload_label)
        upload_btn.click()
        page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
        job_retried = poll_job(page, job_id)
        record['steps']['b_job_after_retry'] = job_retried
        page.screenshot(path=f'{args.shots}/1x-b5-retry-synced.png')
        c.check('retry after switching gh account back reaches synced', job_retried and job_retried.get('status') == 'synced', job_retried)
        c.check('the same commit is the one that ended up pushed (no duplicate commit)',
                job_retried and job_retried.get('commit') == job_failed_push.get('commit'), (job_retried, job_failed_push))
        page.keyboard.press('Escape')

        c.check('no page or console errors in part (b)', not errors2, errors2[:8])
        browser.close()

    git_fetch()
    final_local, final_origin = git_rev('HEAD'), git_rev('origin/main')
    tree_final = git_tree_hash('save-fix/working')
    record['steps']['b_final_git'] = {'local': final_local, 'origin': final_origin, 'in_sync': final_local == final_origin,
                                       'ls_tree_save_fix_working_names': subprocess.run(
                                           ['git', '-C', str(REPO), 'ls-tree', '-r', '--name-only', 'HEAD', '--', 'save-fix/working/latest'],
                                           capture_output=True, text=True, check=True).stdout.splitlines()}
    c.check('local HEAD == origin/main at the end of B5', final_local == final_origin, (final_local, final_origin))
    c.check('no double nesting under save-fix/working/latest', not any('latest/latest/latest' in p for p in record['steps']['b_final_git']['ls_tree_save_fix_working_names']),
            record['steps']['b_final_git']['ls_tree_save_fix_working_names'])
    record['steps']['gh_final_account'] = gh_active_account()
    c.check('gh is left active on pruger-dev', record['steps']['gh_final_account'] == 'pruger-dev', record['steps']['gh_final_account'])

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
