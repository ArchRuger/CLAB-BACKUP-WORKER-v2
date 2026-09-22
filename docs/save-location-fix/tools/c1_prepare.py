#!/usr/bin/env python3
"""Section C preparation: build states A / B / C on all four real devices through the product's own
Save progress / Create checkpoint / Set baseline, then seed Final, Broken, Legacy and the nested
solution folder out of band (a second checkout, like a course maintainer would) and prove the manager
discovers all of it with Update from the repository.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/c1_prepare.py \\
        --secondary /path/to/scratch/CLAB-MNGR-DEV-LLM-secondary \\
        --evidence docs/save-location-fix/evidence/20-c-preparation.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import c_lib  # noqa: E402
from c_lib import BASE, LAB_ID, LAB_NAME, Checker, api, click_save_with_retry, complete_pending_via_recent  # noqa: E402
from c_lib import destination_line, go_to, open_change_folder, open_lab, poll_job, upload_review  # noqa: E402


def create_checkpoint(page, name, note):
    page.locator('[data-git-action="checkpoint"]').nth(1).click()
    page.wait_for_selector('#git-save-options[open]', timeout=15000)
    page.fill('#git-checkpoint-name', name)
    page.fill('#git-save-note', note)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/git/save'), timeout=20000) as info:
        page.click('#git-save-confirm')
    resp = info.value.json()
    return resp.get('id'), resp


def set_baseline_from(page, job_id):
    page.click('#progress-more-button')
    page.wait_for_selector('#progress-more-menu:not([hidden])', timeout=10000)
    page.click('[data-git-action="baseline"]')
    page.wait_for_selector('#git-save-options[open]', timeout=15000)
    options = page.locator('#git-baseline-job option')
    texts = [options.nth(i).inner_text() for i in range(options.count())]
    values = [options.nth(i).get_attribute('value') for i in range(options.count())]
    if job_id not in values:
        raise RuntimeError(f'baseline job id {job_id!r} not in dropdown values: {values}')
    page.select_option('#git-baseline-job', value=job_id)
    replace_box = page.locator('#git-replace-baseline')
    if replace_box.count():
        replace_box.check()
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/git/save'), timeout=20000) as info:
        page.click('#git-save-confirm')
    resp = info.value.json()
    return resp.get('id'), resp, {'texts': texts, 'values': values, 'replace_checkbox_present': replace_box.count() > 0}


def do_save(page, record, key):
    attempts = click_save_with_retry(page)
    record['steps'][key + '_attempts'] = attempts
    job_id, retry = upload_review(page)
    page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
    job = poll_job(page, job_id)
    page.keyboard.press('Escape')
    page.wait_for_timeout(800)
    deadline = time.time() + 60
    while job and job.get('status') == 'push_pending' and time.time() < deadline:
        page.wait_for_timeout(4000)
        job = api(page, 'GET', f"/api/git/jobs/{job['id']}")['body']
    record['steps'][key + '_job'] = job
    return job


def update_from_repository(page, record):
    page.click('#progress-more-button')
    page.wait_for_selector('#progress-more-menu:not([hidden])', timeout=10000)
    page.click('[data-git-action="update"]')
    page.wait_for_selector('#git-update-dialog[open]', timeout=15000)
    with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/git/update'), timeout=20000) as info:
        page.click('#git-update-confirm')
    try:
        resp = info.value.json()
    except Exception:
        resp = None
    page.wait_for_timeout(1000)
    if page.locator('#git-update-dialog[open]').count():
        page.keyboard.press('Escape')
    record['steps']['update_from_repository_response'] = resp
    return resp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secondary', required=True)
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)
    secondary = pathlib.Path(args.secondary)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31 (3dfc4912c163)',
              'started_utc': c_lib.stamp(), 'steps': {}}
    c = Checker()

    # ---- 0. confirm all four on A before any product interaction ----
    before = c_lib.classify_all()
    record['steps']['classify_before'] = before
    c.check('all four nodes read A before preparation begins', all(v == 'A' for v in before.values()), before)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)
        record['steps']['binding_at_start'] = destination_line(page)
        c.check('bound to save-fix/working at the start', 'save-fix/working' in record['steps']['binding_at_start'].replace(' ', ''),
                record['steps']['binding_at_start'])

        # ---- 1. Save progress -> working/latest = A ----
        job_a = do_save(page, record, 'save_a')
        c.check('Save progress (state A) reached synced at save-fix/working/latest',
                job_a and job_a.get('status') == 'synced' and job_a.get('snapshot_path') == 'save-fix/working/latest', job_a)
        commit_a = job_a.get('commit') if job_a else None
        record['state_a_commit'] = commit_a

        # ---- 2. Drift all four to B ----
        drift_results = {}
        for node in c_lib.NODES:
            drift_results[node] = c_lib.drift_to_b(node)[-400:]
        record['steps']['drift_results_tail'] = drift_results
        after_drift = c_lib.classify_all()
        record['steps']['classify_after_drift'] = after_drift
        c.check('all four nodes read B after applying the drift files', all(v == 'B' for v in after_drift.values()), after_drift)

        # ---- 3. Save progress -> working/latest = B (temporary; overwritten by C later) ----
        job_b_latest = do_save(page, record, 'save_b_latest')
        c.check('Save progress (state B) reached synced at save-fix/working/latest',
                job_b_latest and job_b_latest.get('status') == 'synced' and job_b_latest.get('snapshot_path') == 'save-fix/working/latest', job_b_latest)

        # ---- 4. Create checkpoint state-B ----
        cp_job_id, cp_resp = create_checkpoint(page, 'state-B', 'QA section C: configuration B, all four nodes')
        record['steps']['checkpoint_state_b_create_response'] = cp_resp
        job_cp = complete_pending_via_recent(page, cp_job_id)
        record['steps']['checkpoint_state_b_job'] = job_cp
        c.check('checkpoint state-B reached synced at save-fix/working/checkpoints/state-B',
                job_cp and job_cp.get('status') == 'synced' and job_cp.get('snapshot_path') == 'save-fix/working/checkpoints/state-B', job_cp)

        # ---- 5. Undo B, add C marker on all four -> C ----
        for node in c_lib.NODES:
            c_lib.undo_b_to_a(node)
        after_undo = c_lib.classify_all()
        record['steps']['classify_after_undo'] = after_undo
        c.check('all four nodes back to A after undoing the drift', all(v == 'A' for v in after_undo.values()), after_undo)
        for node in c_lib.NODES:
            c_lib.add_c_marker(node)
        after_marker = c_lib.classify_all()
        record['steps']['classify_after_c_marker'] = after_marker
        c.check('all four nodes read C after adding the marker', all(v == 'C' for v in after_marker.values()), after_marker)

        # ---- 6. Save progress -> working/latest = C ----
        job_c = do_save(page, record, 'save_c')
        c.check('Save progress (state C) reached synced at save-fix/working/latest',
                job_c and job_c.get('status') == 'synced' and job_c.get('snapshot_path') == 'save-fix/working/latest', job_c)
        commit_c = job_c.get('commit') if job_c else None
        record['state_c_commit'] = commit_c

        # ---- 7. Set baseline from the state-B checkpoint ----
        baseline_job_id, baseline_resp, baseline_options = set_baseline_from(page, job_cp.get('id'))
        record['steps']['baseline_options'] = baseline_options
        record['steps']['baseline_create_response'] = baseline_resp
        job_baseline = complete_pending_via_recent(page, baseline_job_id)
        record['steps']['baseline_job'] = job_baseline
        c.check('baseline set from the state-B checkpoint, reached synced', job_baseline and job_baseline.get('status') == 'synced', job_baseline)

        c.check('no page/console errors through the whole product-side preparation', not errors, errors[:10])
        browser.close()

    # ---- 8. Second checkout: seed Final (A), Legacy/latest (A), course/lab/reference/solution (A), Broken (B from checkpoint) ----
    c_lib.git(secondary, 'fetch', 'origin', '--quiet')
    c_lib.git(secondary, 'reset', '--hard', 'origin/main', '--quiet')
    working_latest_a = None  # snapshot content is only ever inspected from the checkout after a pull that includes commit_c;
    # so instead of trying to catch "latest" mid-flight as A, pull the exact A commit's tree with git show.
    a_dir = secondary / '_extract_a'
    a_dir.mkdir(exist_ok=True)
    c_lib.git(secondary, 'fetch', 'origin', '--quiet')
    # Extract the working/latest tree exactly as of commit_a (before it was overwritten by B then C).
    listing = c_lib.git(secondary, 'ls-tree', '-r', commit_a, '--', 'save-fix/working/latest')[1]
    names = [line.split('\t')[1] for line in listing.splitlines() if line.split()[1] == 'blob']
    names = [n for n in names if '/' not in n.split('save-fix/working/latest/')[-1]]
    for name in names:
        rel = name.split('save-fix/working/latest/')[-1]
        content = c_lib.git(secondary, 'show', f'{commit_a}:{name}')[1]
        (a_dir / rel).write_bytes(content.encode() if isinstance(content, str) else content)
    record['steps']['state_a_files_extracted'] = names

    seed_results = {}
    for dest in ('save-fix/Final', 'save-fix/course/lab/reference/solution'):
        sha, copied = c_lib.replace_snapshot_folder(secondary, a_dir, dest, f'section C: {dest} = state A (commit {commit_a[:10]})')
        seed_results[dest] = {'commit': sha, 'files': copied}
    sha, copied = c_lib.replace_snapshot_folder(secondary, a_dir, 'save-fix/Legacy/latest', f'section C: save-fix/Legacy/latest = state A (commit {commit_a[:10]})')
    seed_results['save-fix/Legacy/latest'] = {'commit': sha, 'files': copied}
    record['steps']['seed_a_folders'] = seed_results
    c.check('save-fix/Final, .../solution and Legacy/latest seeded with state A files (9 each)',
            all(len(v['files']) >= 9 for v in seed_results.values()), seed_results)

    # ---- 9. Broken = direct manifest of the state-B checkpoint ----
    c_lib.git(secondary, 'fetch', 'origin', '--quiet')
    b_dir = secondary / '_extract_b'
    b_dir.mkdir(exist_ok=True)
    cp_commit = job_cp.get('commit') if job_cp else None
    record['checkpoint_state_b_commit'] = cp_commit
    listing_b = c_lib.git(secondary, 'ls-tree', '-r', 'HEAD', '--', 'save-fix/working/checkpoints/state-B')[1]
    names_b = [line.split('\t')[1] for line in listing_b.splitlines() if line.split()[1] == 'blob']
    names_b = [n for n in names_b if '/' not in n.split('save-fix/working/checkpoints/state-B/')[-1]]
    for name in names_b:
        rel = name.split('save-fix/working/checkpoints/state-B/')[-1]
        content = c_lib.git(secondary, 'show', f'HEAD:{name}')[1]
        (b_dir / rel).write_bytes(content.encode() if isinstance(content, str) else content)
    sha_broken, copied_broken = c_lib.replace_snapshot_folder(secondary, b_dir, 'save-fix/Broken', f'section C: save-fix/Broken (direct) = state B (checkpoint state-B)')
    record['steps']['seed_broken'] = {'commit': sha_broken, 'files': copied_broken}
    c.check('save-fix/Broken seeded directly (not a legacy parent) with state B files (9)', len(copied_broken) >= 9, copied_broken)

    record['final_git'] = {'local': c_lib.git_rev(secondary), 'origin': c_lib.git(secondary, 'rev-parse', 'origin/main')[1]}
    c.check('second checkout local HEAD == origin/main after seeding', record['final_git']['local'] == record['final_git']['origin'], record['final_git'])

    # ---- 10. Update from the repository in the product; verify /git/history and Saved versions ----
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        open_lab(page)
        update_resp = update_from_repository(page, record)
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=20000)
        versions_text = page.locator('#git-saved-versions').inner_text()
        record['steps']['saved_versions_text_after_update'] = versions_text[:3000]
        page.screenshot(path=f'{args.shots}/20-saved-versions-prepared.png')
        binding_after = destination_line(page)
        record['steps']['binding_after_update'] = binding_after
        c.check('binding still save-fix/working after Update from the repository',
                'save-fix/working' in binding_after.replace(' ', '') and 'latest/latest' not in binding_after.replace(' ', ''), binding_after)

        history = api(page, 'GET', f'/api/labs/{LAB_ID}/git/history')['body']
        paths = [v.get('path') for v in history.get('versions', [])]
        record['steps']['history_total'] = len(paths)
        expected_paths = ['save-fix/Final', 'save-fix/Broken', 'save-fix/course/lab/reference/solution',
                           'save-fix/Legacy/latest', 'save-fix/working/checkpoints/state-B', 'save-fix/working/baseline',
                           'save-fix/working/latest']
        for expect in expected_paths:
            c.check(f'/git/history lists {expect}', expect in paths, expect in paths)
        record['steps']['history_paths_matched'] = {p: (p in paths) for p in expected_paths}
        browser.close()

    record['classify_end'] = c_lib.classify_all()
    c.check('all four nodes read C at the end of preparation (working/latest = C on the devices)',
            all(v == 'C' for v in record['classify_end'].values()), record['classify_end'])

    record['checks'] = c.checks
    record['failed'] = c.failed
    record['finished_utc'] = c_lib.stamp()
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'{passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
