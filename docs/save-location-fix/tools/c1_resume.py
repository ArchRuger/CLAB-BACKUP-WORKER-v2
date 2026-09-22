#!/usr/bin/env python3
"""Resume section-C preparation after c1_prepare.py's first run crashed picking the baseline option
(the dropdown carries only relative time + device count as its visible text; the job id is the
option's value -- fixed in c1_prepare.py's set_baseline_from, kept here as the same function).
States A, B (working/latest, temporary) and the state-B checkpoint, and state C (working/latest,
current) were already made through the real product before the crash; this script re-derives their
job ids/commits from GET /api/labs/<id>/git (the manager's own job history, not re-done), then
completes: Set baseline from the state-B checkpoint; seeds Final/Broken/Legacy/solution from a second
checkout; runs Update from the repository; verifies discovery. Produces the full 20-c-preparation
evidence, combining the already-completed steps (read back from the API, not repeated) with the
steps performed by this run.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/c1_resume.py \\
        --secondary /path/to/scratch/CLAB-MNGR-DEV-LLM-secondary \\
        --evidence docs/save-location-fix/evidence/20-c-preparation.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import c_lib  # noqa: E402
from c_lib import BASE, LAB_ID, LAB_NAME, Checker, api, complete_pending_via_recent  # noqa: E402
from c_lib import destination_line, open_lab  # noqa: E402
from c1_prepare import set_baseline_from, update_from_repository  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--secondary', required=True)
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)
    secondary = pathlib.Path(args.secondary)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31 (3dfc4912c163)',
              'started_utc': c_lib.stamp(), 'steps': {}, 'note': 'resumed after c1_prepare.py crashed selecting the '
              'baseline dropdown option by its visible text (relative time only); the four product-side saves before '
              'that point are re-derived here from GET /api/labs/<id>/git, not repeated'}
    c = Checker()

    jobs = requests_jobs = None
    import urllib.request
    with urllib.request.urlopen(f'{BASE}/api/labs/{LAB_ID}/git', timeout=20) as resp:
        jobs = json.load(resp)['jobs']

    def find(target, checkpoint=None, snapshot_path=None):
        for j in jobs:
            if j.get('target') == target and j.get('status') == 'synced' and \
               (checkpoint is None or j.get('checkpoint') == checkpoint) and \
               (snapshot_path is None or j.get('snapshot_path') == snapshot_path):
                return j
        return None

    job_a = find('latest', snapshot_path='save-fix/working/latest')
    # job_a is the OLDEST of the three consecutive 'latest' saves (A, then B, then C); pick by time order.
    latest_saves = sorted([j for j in jobs if j.get('target') == 'latest' and j.get('status') == 'synced'
                           and j.get('snapshot_path') == 'save-fix/working/latest'], key=lambda j: j['created'])
    job_a, job_b_latest, job_c = latest_saves[-3], latest_saves[-2], latest_saves[-1]
    job_cp = find('checkpoint', checkpoint='state-B')
    record['steps']['save_a_job'] = job_a
    record['steps']['save_b_latest_job'] = job_b_latest
    record['steps']['checkpoint_state_b_job'] = job_cp
    record['steps']['save_c_job'] = job_c
    record['state_a_commit'] = job_a['commit']
    record['state_c_commit'] = job_c['commit']
    record['checkpoint_state_b_commit'] = job_cp['commit']
    c.check('state A save found synced at working/latest (re-derived from job history)', bool(job_a), job_a and job_a['id'])
    c.check('state B save found synced at working/latest, self-healed after the transient push_pending '
            '(commit 0f6aa6bd matches the run log)', job_b_latest and job_b_latest['commit'] == '0f6aa6bd9928e07f052155c4e7361f5262ec5b6c', job_b_latest)
    c.check('checkpoint state-B found synced at working/checkpoints/state-B', bool(job_cp), job_cp and job_cp['id'])
    c.check('state C save found synced at working/latest (current)', bool(job_c), job_c and job_c['id'])

    before = c_lib.classify_all()
    record['classify_before_resume'] = before
    c.check('all four nodes read C when this resume run starts (state C was already saved)', all(v == 'C' for v in before.values()), before)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)

        # ---- 7. Set baseline from the state-B checkpoint (the dropdown lists BACKUP jobs, selected
        # by the checkpoint's own backup_job_id -- not the git save job's id). A previous run of this
        # script already completed this (job e000587d..., backup_job_id matches the checkpoint's own):
        # reused rather than repeated, to avoid an unnecessary extra "replace the baseline" write.
        existing_baseline = next((j for j in jobs if j.get('target') == 'baseline' and j.get('status') == 'synced'
                                  and j.get('backup_job_id') == job_cp['backup_job_id']), None)
        if existing_baseline:
            job_baseline = existing_baseline
            record['steps']['baseline_reused_existing'] = True
        else:
            baseline_job_id, baseline_resp, baseline_options = set_baseline_from(page, job_cp['backup_job_id'])
            record['steps']['baseline_options'] = baseline_options
            record['steps']['baseline_create_response'] = baseline_resp
            job_baseline = complete_pending_via_recent(page, baseline_job_id)
        record['steps']['baseline_job'] = job_baseline
        c.check('baseline set from the state-B checkpoint job id, reached synced', job_baseline and job_baseline.get('status') == 'synced', job_baseline)
        # The baseline write is its own commit at working/baseline (a different path from the
        # checkpoint, so a different commit sha is expected); file content is compared below via git
        # tree hash once the second checkout has fetched both paths.
        record['baseline_job_id'] = job_baseline.get('id') if job_baseline else None

        c.check('no page/console errors while setting the baseline', not errors, errors[:10])
        browser.close()

    # ---- 8/9. Second checkout: seed Final/Legacy/solution (A) and Broken (B, direct manifest) ----
    c_lib.git(secondary, 'fetch', 'origin', '--quiet')
    c_lib.git(secondary, 'reset', '--hard', 'origin/main', '--quiet')

    if record.get('baseline_job_id'):
        with __import__('urllib.request', fromlist=['urlopen']).urlopen(f'{BASE}/api/git/jobs/{record["baseline_job_id"]}', timeout=20) as r:
            job_baseline_full = json.load(r)
        baseline_tree = c_lib.git(secondary, 'rev-parse', f'{job_baseline_full["commit"]}:save-fix/working/baseline')[1]
        checkpoint_tree = c_lib.git(secondary, 'rev-parse', f'{job_cp["commit"]}:save-fix/working/checkpoints/state-B')[1]
        record['steps']['baseline_vs_checkpoint_tree'] = {'baseline_tree': baseline_tree, 'checkpoint_tree': checkpoint_tree}
        c.check('baseline snapshot (save-fix/working/baseline) is byte-identical to the state-B checkpoint (same backup capture)',
                baseline_tree == checkpoint_tree, (baseline_tree, checkpoint_tree))

    commit_a = job_a['commit']
    a_dir = secondary / '_extract_a'
    a_dir.mkdir(exist_ok=True)
    listing = c_lib.git(secondary, 'ls-tree', '-r', commit_a, '--', 'save-fix/working/latest')[1]
    names = [line.split('\t')[1] for line in listing.splitlines() if line.split()[1] == 'blob']
    names = [n for n in names if '/' not in n.split('save-fix/working/latest/')[-1]]
    for name in names:
        rel = name.split('save-fix/working/latest/')[-1]
        content = c_lib.git_show_raw(secondary, f'{commit_a}:{name}')
        (a_dir / rel).write_bytes(content)
    record['steps']['state_a_files_extracted'] = names

    seed_results = {}
    for dest in ('save-fix/Final', 'save-fix/course/lab/reference/solution'):
        sha, copied = c_lib.replace_snapshot_folder(secondary, a_dir, dest, f'section C: {dest} = state A (commit {commit_a[:10]})')
        seed_results[dest] = {'commit': sha, 'files': copied}
    sha, copied = c_lib.replace_snapshot_folder(secondary, a_dir, 'save-fix/Legacy/latest',
                                                 f'section C: save-fix/Legacy/latest = state A (commit {commit_a[:10]})')
    seed_results['save-fix/Legacy/latest'] = {'commit': sha, 'files': copied}
    record['steps']['seed_a_folders'] = seed_results
    c.check('save-fix/Final, .../solution and Legacy/latest seeded with state A files (9 each)',
            all(len(v['files']) >= 9 for v in seed_results.values()), seed_results)

    c_lib.git(secondary, 'fetch', 'origin', '--quiet')
    b_dir = secondary / '_extract_b'
    b_dir.mkdir(exist_ok=True)
    cp_commit = job_cp['commit']
    listing_b = c_lib.git(secondary, 'ls-tree', '-r', 'HEAD', '--', 'save-fix/working/checkpoints/state-B')[1]
    names_b = [line.split('\t')[1] for line in listing_b.splitlines() if line.split()[1] == 'blob']
    names_b = [n for n in names_b if '/' not in n.split('save-fix/working/checkpoints/state-B/')[-1]]
    for name in names_b:
        rel = name.split('save-fix/working/checkpoints/state-B/')[-1]
        content = c_lib.git_show_raw(secondary, f'HEAD:{name}')
        (b_dir / rel).write_bytes(content)
    sha_broken, copied_broken = c_lib.replace_snapshot_folder(secondary, b_dir, 'save-fix/Broken',
                                                               'section C: save-fix/Broken (direct manifest) = state B (checkpoint state-B)')
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
    c.check('all four nodes still read C at the end of preparation (devices only ever changed by this run\'s '
            'own drift/undo/marker steps, never by Update)', all(v == 'C' for v in record['classify_end'].values()), record['classify_end'])

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
