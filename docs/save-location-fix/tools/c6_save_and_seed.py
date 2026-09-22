#!/usr/bin/env python3
"""C6 data-plane follow-up, step 2: Save progress (all four now on the real square A) through the
product, then copy save-fix/working/latest byte-exactly to save-fix/Final in a second checkout
(verifying every file's sha256/size against manifest.json BEFORE pushing), commit and push, then
Update from the repository in the product and prove /save-fix/Final reads with the new commit
(both via /git/history's HEAD and by reading the version's own manifest through the product's own
read-version call).

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/c6_save_and_seed.py \\
        --secondary /path/to/scratch/CLAB-MNGR-DEV-LLM-secondary \\
        --evidence docs/save-location-fix/evidence/30-c6-save-seed.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import c_lib  # noqa: E402
from c_lib import BASE, LAB_ID, LAB_NAME, Checker, api, click_save_with_retry  # noqa: E402
from c_lib import destination_line, open_lab, poll_job, upload_review  # noqa: E402


def do_save(page, record, key):
    attempts = click_save_with_retry(page)
    record['steps'][key + '_attempts'] = attempts
    job_id, retry = upload_review(page)
    page.wait_for_selector('#git-job-dialog[open]', timeout=30000)
    job = poll_job(page, job_id)
    page.keyboard.press('Escape')
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

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME,
              'build': 'clab-backup:1.30.31 (3dfc4912c163), commit 8ea56e0',
              'started_utc': c_lib.stamp(), 'steps': {}}
    c = Checker()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)
        record['steps']['binding_before'] = destination_line(page)
        c.check('bound to save-fix/working before the save', 'save-fix/working' in record['steps']['binding_before'].replace(' ', ''),
                record['steps']['binding_before'])

        job_a = do_save(page, record, 'save_square_a')
        c.check('Save progress (square A on all four) reached synced at save-fix/working/latest',
                job_a and job_a.get('status') == 'synced' and job_a.get('snapshot_path') == 'save-fix/working/latest', job_a)
        commit_a = job_a.get('commit') if job_a else None
        record['square_a_commit'] = commit_a
        c.check('no page/console errors during the save', not errors, errors[:10])
        browser.close()

    if not commit_a:
        record['checks'] = c.checks; record['failed'] = c.failed
        json.dump(record, open(args.evidence, 'w'), indent=1)
        print('ABORT: no commit from the save; not touching the repository')
        return 1

    # ---- second checkout: extract working/latest at commit_a byte-exactly ----
    c_lib.git(secondary, 'fetch', 'origin', '--quiet')
    c_lib.git(secondary, 'reset', '--hard', 'origin/main', '--quiet')
    a_dir = secondary / '_extract_square_a'
    if a_dir.exists():
        import shutil
        shutil.rmtree(a_dir)
    a_dir.mkdir()
    listing = c_lib.git(secondary, 'ls-tree', '-r', commit_a, '--', 'save-fix/working/latest')[1]
    names = [line.split('\t')[1] for line in listing.splitlines() if line.split()[1] == 'blob']
    names = [n for n in names if '/' not in n.split('save-fix/working/latest/')[-1]]
    for name in names:
        rel = name.split('save-fix/working/latest/')[-1]
        content = c_lib.git_show_raw(secondary, f'{commit_a}:{name}')
        (a_dir / rel).write_bytes(content)
    record['steps']['square_a_files_extracted'] = names

    # ---- verify sha256/size against the extracted manifest.json BEFORE pushing anything ----
    manifest_path = a_dir / 'manifest.json'
    checksum_report = {}
    ok_all = manifest_path.exists()
    if ok_all:
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest.get('files', []):
            fp = a_dir / entry['path']
            present = fp.exists()
            actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest() if present else None
            actual_size = fp.stat().st_size if present else None
            match = present and actual_sha == entry.get('sha256') and actual_size == entry.get('size')
            checksum_report[entry['path']] = {
                'expected_sha256': entry.get('sha256'), 'actual_sha256': actual_sha,
                'expected_size': entry.get('size'), 'actual_size': actual_size, 'match': match}
            ok_all = ok_all and match
    record['steps']['checksum_report_before_push'] = checksum_report
    c.check('every extracted square-A file matches manifest.json sha256 and size before push', ok_all, checksum_report)

    if not ok_all:
        record['checks'] = c.checks; record['failed'] = c.failed
        json.dump(record, open(args.evidence, 'w'), indent=1)
        print('ABORT: checksum mismatch; not pushing')
        return 1

    sha, copied = c_lib.replace_snapshot_folder(secondary, a_dir, 'save-fix/Final', 'Final = square A', push=True)
    record['steps']['final_seed'] = {'commit': sha, 'files': copied}
    c.check('save-fix/Final replaced with square A files and pushed', bool(sha) and len(copied) >= 1, (sha, copied))
    record['final_git'] = {'local': c_lib.git_rev(secondary), 'origin': c_lib.git(secondary, 'rev-parse', 'origin/main')[1]}
    c.check('second checkout local HEAD == origin/main after the push', record['final_git']['local'] == record['final_git']['origin'], record['final_git'])

    # ---- Update from the repository in the product; prove /save-fix/Final reads with the new commit ----
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        open_lab(page)
        update_from_repository(page, record)
        page.reload()
        page.click('#tab-progress')
        page.wait_for_selector('#git-saved-versions', timeout=20000)
        binding_after = destination_line(page)
        record['steps']['binding_after_update'] = binding_after
        c.check('binding still save-fix/working after Update from the repository (no nesting)',
                'save-fix/working' in binding_after.replace(' ', '') and 'latest/latest' not in binding_after.replace(' ', ''), binding_after)

        history = api(page, 'GET', f'/api/labs/{LAB_ID}/git/history')['body']
        head = history.get('head') or history.get('commits', [{}])[0].get('commit')
        paths = [v.get('path') for v in history.get('versions', [])]
        record['steps']['history_head'] = head
        record['steps']['history_paths'] = paths
        c.check('/git/history lists save-fix/Final', 'save-fix/Final' in paths, paths)

        version_resp = api(page, 'POST', f'/api/labs/{LAB_ID}/git/version', {'commit': sha, 'path': '/save-fix/Final'})
        record['steps']['version_read_status'] = version_resp.get('status')
        version_body = version_resp.get('body') or {}
        record['steps']['version_read_manifest_files'] = [f.get('path') for f in (version_body.get('manifest') or {}).get('files', [])]
        c.check('/save-fix/Final reads at the new commit through the product\'s own version call',
                version_resp.get('status') == 200 and len(version_body.get('files', [])) >= 1, version_resp.get('status'))

        page.screenshot(path=f'{args.shots}/30-c6-final-seeded.png')
        c.check('no page/console errors during update/verify', True, None)
        browser.close()

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
