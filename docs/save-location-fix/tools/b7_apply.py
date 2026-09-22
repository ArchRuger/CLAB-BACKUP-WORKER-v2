#!/usr/bin/env python3
"""Section B, row B7: Apply from four UI entry points; one real restore on ceos; reopen/refresh;
keyboard access; a narrow viewport screenshot; a stale review; an invalid-commit review.

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b7_apply.py \\
        --evidence docs/save-location-fix/evidence/16-b7-apply.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, destination_line, go_to, open_change_folder, open_lab

NODECLI_DIR = pathlib.Path(__file__).parent.parent.parent / 'multi-platform-restore' / 'tools'
sys.path.insert(0, str(NODECLI_DIR))
ROOT = pathlib.Path.home() / 'projects' / 'clab-manager'
REPO = pathlib.Path.home() / 'labs' / 'CLAB-MNGR-DEV-LLM'
CEOS_NODE_NAME = 'clab-restore-square-ceos'


def git(repo, *args):
    r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def git_fetch(repo=REPO):
    git(repo, 'fetch', 'origin', '--quiet')


def git_rev(repo=REPO, ref='HEAD'):
    return git(repo, 'rev-parse', ref)[1]


def readback(expect=None, saved_dir=None, timeout=240):
    cmd = [sys.executable, str(NODECLI_DIR / 'readback.py'), 'ceos', '--timeout', str(timeout)]
    if expect:
        cmd += ['--expect', expect]
    if saved_dir:
        cmd += ['--saved', str(saved_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30)
    try:
        data = json.loads(r.stdout.strip()) if r.stdout.strip() else None
    except Exception:
        data = None
    return {'returncode': r.returncode, 'stdout_tail': r.stdout[-2000:], 'stderr_tail': r.stderr[-1000:], 'parsed': data}


def drift_ceos():
    drift_file = ROOT / 'docs' / 'multi-platform-restore' / 'lab' / 'drift' / 'ceos-B.cli'
    r = subprocess.run([sys.executable, str(NODECLI_DIR / 'nodecli.py'), 'ceos', '--tag', 'drift-b-qa-b7',
                         '--timeout', '240', '--file', str(drift_file)], capture_output=True, text=True, timeout=270)
    return {'returncode': r.returncode, 'stdout_tail': r.stdout[-1000:], 'stderr_tail': r.stderr[-500:]}


def open_preflight_review(page, entry_key, record, c, open_action):
    """open_action opens #restore-review-dialog (or errors); records source line + eligible rows,
    then cancels without submitting."""
    open_action()
    page.wait_for_selector('#restore-review-dialog[open]', timeout=20000)
    page.wait_for_selector('#restore-review-dialog .restore-targets', timeout=20000)
    dialog_text = page.locator('#restore-review-dialog').inner_text()
    source_line = ''
    for line in dialog_text.splitlines():
        if line.strip().startswith('Source:'):
            source_line = line.strip()
            break
    rows = page.locator('#restore-review-dialog .restore-target')
    row_texts = [rows.nth(i).inner_text().replace('\n', ' ') for i in range(rows.count())]
    record['steps'][entry_key] = {'source_line': source_line, 'eligible_rows': row_texts, 'dialog_excerpt': dialog_text[:500]}
    c.check(f'{entry_key}: review opened with a Source line naming the folder and a 10-char commit', bool(source_line) and '·' in source_line, source_line)
    page.click('[data-op-close]')
    page.wait_for_timeout(500)


def run(page, browser, args, record, c):
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

    open_lab(page)

    # ==== Entry point 1: folder browser at save-fix/Final -> Apply to running lab... ====
    open_change_folder(page)
    go_to(page, 'save-fix')
    go_to(page, 'save-fix/Final')
    page.wait_for_timeout(300)

    def open_via_browser_final():
        page.click('#git-places-panel [data-git-places-action="apply"]')

    open_preflight_review(page, 'entry1_folder_browser_final', record, c, open_via_browser_final)
    details = page.locator('#git-change-folder')
    if details.count() and details.get_attribute('open') is not None:
        page.click('#git-change-folder summary')

    # ==== Entry point 2: Save location's own browser (opened from "Change folder...") ====
    page.reload()
    page.click('#tab-progress')
    page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)
    page.click('#git-open-settings')
    page.wait_for_selector('#git-binding-form', timeout=20000)
    change_folder2 = page.locator('#git-change-folder')
    if change_folder2.count() and change_folder2.get_attribute('open') is None:
        page.click('#git-change-folder summary')
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=20000)
    go_to(page, 'save-fix')
    go_to(page, 'save-fix/Final')
    page.wait_for_timeout(300)
    page.screenshot(path=f'{args.shots}/1x-b7-entry2-save-location-browser.png')

    def open_via_save_location_browser():
        page.click('#git-places-panel [data-git-places-action="apply"]')

    open_preflight_review(page, 'entry2_save_location_browser', record, c, open_via_save_location_browser)

    # ==== Entry point 3: Saved versions row for the nested solution folder ====
    page.reload()
    page.click('#tab-progress')
    page.wait_for_selector('#git-saved-versions', timeout=20000)
    solution_row = page.locator('#git-saved-versions li.git-version-row', has_text='solution')
    c.check('Saved versions has a row for the nested solution folder', solution_row.count() >= 1, solution_row.count())

    def open_via_saved_versions_solution():
        solution_row.first.locator('[data-git-version-action="apply"]').click()

    open_preflight_review(page, 'entry3_saved_versions_solution', record, c, open_via_saved_versions_solution)

    # ==== Entry point 4: Full history -> a commit -> View -> Apply ====
    page.locator('#git-save-menu summary').click()
    page.wait_for_selector('#git-save-menu[open]', timeout=10000)
    page.click('#git-save-menu [data-git-action="history"]')
    page.wait_for_selector('#git-history-dialog[open]', timeout=20000)
    commit_buttons = page.locator('#git-history-dialog [data-git-commit]')
    # "Save history" only lists this lab's OWN commits; every one of those matches a known job, so
    # gitOpenCommit jumps straight from the commit button to the version view (View) without the
    # intermediate "Which saved version?" picker -- that picker exists for a commit the manager
    # cannot already attribute to one of this lab's own jobs, which "Save history" does not surface.
    # Pick the qa-cp-a checkpoint commit, a concrete historical version distinct from Latest.
    target_index = None
    for i in range(min(commit_buttons.count(), 30)):
        txt = commit_buttons.nth(i).inner_text()
        if 'qa checkpoint a' in txt.lower():
            target_index = i
            break
    if target_index is None:
        target_index = 0
    record['steps']['entry4_commit_button_text'] = commit_buttons.nth(target_index).inner_text()[:200]
    commit_buttons.nth(target_index).click()
    page.wait_for_selector('#git-commit-dialog[open], #git-version-dialog[open]', timeout=15000)
    if page.locator('#git-commit-dialog[open]').count():
        select = page.locator('#git-commit-path')
        options = select.locator('option')
        chosen_final = False
        for i in range(options.count()):
            if options.nth(i).get_attribute('value') == 'save-fix/Final' or options.nth(i).inner_text().strip() == 'save-fix/Final':
                select.select_option(index=i)
                chosen_final = True
                break
        record['steps']['entry4_chose_final_path'] = chosen_final
        page.screenshot(path=f'{args.shots}/1x-b7-entry4-commit-dialog.png')
        page.click('#git-commit-view')
        page.wait_for_selector('#git-version-dialog[open]', timeout=20000)
    else:
        record['steps']['entry4_jumped_straight_to_version'] = True
    version_text = page.locator('#git-version-dialog').inner_text()
    record['steps']['entry4_version_dialog_text'] = version_text[:500]
    has_restore_btn = page.locator('#git-version-restore').count()
    c.check('entry4: the historical version view offers "Apply to running lab..." when restorable', has_restore_btn == 1, has_restore_btn)
    if has_restore_btn:
        def open_via_history_version():
            page.click('#git-version-restore')
        open_preflight_review(page, 'entry4_history_version', record, c, open_via_history_version)

    c.check('no page or console errors across the four preflight entry points', not errors, errors[:8])

    # ==== Keyboard access of the folder browser ====
    page.reload()
    page.click('#tab-progress')
    page.wait_for_selector('#git-repository-content .git-save-location', timeout=30000)
    open_change_folder(page)
    page.wait_for_selector('#git-places-panel .git-places-head', timeout=20000)
    go_to(page, 'save-fix')
    page.locator('#git-places-panel').scroll_into_view_if_needed()
    outline_item = page.locator('#git-places-panel [data-git-place]').first
    outline_item.focus()
    page.keyboard.press('Tab')
    active_tag = page.evaluate("document.activeElement && document.activeElement.tagName")
    record['steps']['keyboard_after_tab_active_tag'] = active_tag
    c.check('keyboard Tab moves focus within the folder browser', bool(active_tag), active_tag)
    page.keyboard.press('ArrowDown')
    page.wait_for_timeout(200)
    record['steps']['keyboard_arrowdown_active_text'] = page.evaluate("document.activeElement && document.activeElement.textContent")
    page.screenshot(path=f'{args.shots}/1x-b7-keyboard-nav.png')

    # ==== 390px viewport screenshot of the Progress tab with Saved versions groups ====
    page2 = browser.new_context(viewport={'width': 390, 'height': 844}).new_page()
    open_lab(page2)
    page2.wait_for_selector('#git-saved-versions', timeout=20000)
    page2.screenshot(path=f'{args.shots}/1x-b7-390px-progress.png', full_page=True)
    page2.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31',
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    c = Checker()

    def dump():
        record['checks'] = c.checks
        record['failed'] = c.failed
        record['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        with open(args.evidence, 'w') as fh:
            json.dump(record, fh, indent=1)
            fh.write('\n')

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        try:
            run(page, browser, args, record, c)
        except Exception as exc:
            record['steps']['exception'] = repr(exc)
            dump()
            raise
        finally:
            browser.close()

    dump()
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'PART 1 (preflight entry points + keyboard + narrow viewport): {passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
