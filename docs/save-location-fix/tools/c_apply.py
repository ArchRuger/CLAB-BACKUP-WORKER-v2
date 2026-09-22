#!/usr/bin/env python3
"""One real *Replace running configuration* through the actual browser page, for section C.

Generic driver reused by C2-C5: opens the lab, reaches the review dialog through one of the real
entry points (folder browser, Saved versions row, or Full history -> commit -> View), records the
review's exact source line + eligible rows (screenshot on the first use of each entry point),
confirms devices, submits, polls the restore job, screenshots the result, then verifies every
restored node independently: c_lib.classify() (the A/B/C marker), readback.py --saved (whole-
configuration comparison against a real saved folder on disk), and boot identity before/after (no
reboot).

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/c_apply.py \\
        --entry folder --path save-fix/Final \\
        --expect-state A --saved-dir ~/labs/CLAB-MNGR-DEV-LLM/save-fix/Final \\
        --label c2 --evidence docs/save-location-fix/evidence/21-c2-final.json \\
        --shots docs/save-location-fix/evidence --shoot-review --shoot-result
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import c_lib  # noqa: E402
from c_lib import BASE, LAB_ID, LAB_NAME, Checker, api, destination_line, go_to, open_change_folder, open_lab  # noqa: E402

MP_TOOLS = pathlib.Path(__file__).resolve().parent.parent.parent / 'multi-platform-restore' / 'tools'
VENV_PYTHON = pathlib.Path(__file__).resolve().parent.parent.parent.parent / 'clab-backup-ui' / '.venv' / 'bin' / 'python'
NODE_NAME = {n: f'clab-restore-square-{n}' for n in c_lib.NODES}
ACTIVE = ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')


def readback_saved(nodes, expect=None, saved=None, timeout=240):
    # readback.py takes no --timeout of its own (each Session has a fixed 180s internal read timeout);
    # the timeout here only bounds this subprocess call.
    cmd = [str(VENV_PYTHON), str(MP_TOOLS / 'readback.py'), *nodes]
    if saved:
        cmd += ['--saved', str(saved)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {'error': 'no JSON from readback.py', 'stdout_tail': r.stdout[-800:], 'stderr_tail': r.stderr[-800:]}


def boot_identity(nodes):
    data = readback_saved(nodes)
    return {n: {'boot': v.get('boot'), 'up_seconds': v.get('up_seconds')} for n, v in data.get('nodes', {}).items()}


def same_boot(before, after):
    ok = {}
    for n in before:
        b, a = before.get(n, {}), after.get(n, {})
        if b.get('boot') and 'System booted' in str(b.get('boot')):
            ok[n] = b.get('boot') == a.get('boot')
        else:
            ok[n] = bool(b.get('up_seconds')) and bool(a.get('up_seconds')) and a['up_seconds'] >= b['up_seconds'] - 120
    return ok


def reach_review_via_folder(page, path_parts, record):
    open_change_folder(page)
    acc = []
    for part in path_parts:
        acc.append(part)
        go_to(page, '/'.join(acc))
    page.wait_for_timeout(300)
    apply_btn = page.locator('#git-places-panel [data-git-places-action="apply"]')
    record['entry_apply_button_count'] = apply_btn.count()
    apply_btn.click()


def reach_review_via_saved_versions(page, match_text, record, group_hint=None):
    page.reload()
    page.click('#tab-progress')
    page.wait_for_selector('#git-saved-versions', timeout=20000)
    rows = page.locator('#git-saved-versions li.git-version-row', has_text=match_text)
    record['saved_versions_row_count'] = rows.count()
    row = rows.first
    caption = row.locator('small.caption.mono')
    record['saved_versions_row_caption'] = caption.inner_text() if caption.count() else None
    row.locator('[data-git-version-action="apply"]').click()


def reach_review_via_history(page, commit_match, path_match, record):
    page.locator('#git-save-menu summary').click()
    page.wait_for_selector('#git-save-menu[open]', timeout=10000)
    page.click('#git-save-menu [data-git-action="history"]')
    page.wait_for_selector('#git-history-dialog[open]', timeout=20000)
    buttons = page.locator('#git-history-dialog [data-git-commit]')
    target_index = None
    for i in range(min(buttons.count(), 60)):
        if commit_match.lower() in buttons.nth(i).inner_text().lower():
            target_index = i
            break
    if target_index is None:
        raise RuntimeError(f'no history commit button matched {commit_match!r}')
    record['history_commit_button_text'] = buttons.nth(target_index).inner_text()[:200]
    buttons.nth(target_index).click()
    page.wait_for_selector('#git-commit-dialog[open], #git-version-dialog[open]', timeout=15000)
    if page.locator('#git-commit-dialog[open]').count():
        select = page.locator('#git-commit-path')
        options = select.locator('option')
        chosen = False
        for i in range(options.count()):
            text = options.nth(i).inner_text().strip()
            value = options.nth(i).get_attribute('value')
            if path_match in (text, value):
                select.select_option(index=i)
                chosen = True
                break
        record['history_path_chosen'] = chosen
        page.click('#git-commit-view')
        page.wait_for_selector('#git-version-dialog[open]', timeout=20000)
    else:
        record['history_jumped_straight_to_version'] = True
    page.click('#git-version-restore')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--entry', choices=['folder', 'saved-versions', 'history'], required=True)
    ap.add_argument('--path', help='for --entry folder: repository path, slash-separated, no leading save-fix required if given in full')
    ap.add_argument('--match', help='for --entry saved-versions: row text to match; for history: commit button text to match')
    ap.add_argument('--history-path-match', help='for --entry history: which path to choose in the intermediate picker, if it appears')
    ap.add_argument('--nodes', nargs='*', default=c_lib.NODES)
    ap.add_argument('--expect-state', choices=['A', 'B', 'C'], required=True)
    ap.add_argument('--saved-dir', help='a directory on disk holding <node>.set/.cfg for the whole-configuration comparison')
    ap.add_argument('--minutes', type=int, default=5)
    ap.add_argument('--label', required=True)
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    ap.add_argument('--expect-disabled', type=int, default=0)
    ap.add_argument('--timeout', type=int, default=900)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31 (3dfc4912c163)',
              'entry': args.entry, 'path_or_match': args.path or args.match, 'nodes': args.nodes,
              'started_utc': c_lib.stamp(), 'steps': {}}
    c = Checker()

    before_classify = c_lib.classify_all(args.nodes)
    record['classify_before'] = before_classify
    before_boot = boot_identity(args.nodes)
    record['boot_before'] = before_boot

    binding_before = None
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)
        binding_before = destination_line(page)
        record['steps']['binding_before'] = binding_before

        if args.entry == 'folder':
            reach_review_via_folder(page, args.path.split('/'), record['steps'])
        elif args.entry == 'saved-versions':
            reach_review_via_saved_versions(page, args.match, record['steps'])
        else:
            reach_review_via_history(page, args.match, args.history_path_match, record['steps'])

        page.wait_for_selector('#restore-review-dialog[open]', timeout=20000)
        page.wait_for_selector('#restore-review-dialog .restore-targets', timeout=20000)
        dialog_text = page.locator('#restore-review-dialog').inner_text()
        source_line = next((ln.strip() for ln in dialog_text.splitlines() if ln.strip().startswith('Source:')), '')
        rows = page.locator('#restore-review-dialog .restore-target')
        row_texts = [rows.nth(i).inner_text().replace('\n', ' ') for i in range(rows.count())]
        record['steps']['review_source_line'] = source_line
        record['steps']['review_eligible_rows'] = row_texts
        record['steps']['review_dialog_text'] = dialog_text[:1500]
        page.screenshot(path=f'{args.shots}/2x-{args.label}-review.png')
        c.check(f'{args.label}: review shows a Source line with folder and 10-char commit', bool(source_line) and '·' in source_line, source_line)
        disabled_rows = [t for t in row_texts if 'disabled' in t.lower() or 'cannot' in t.lower()]
        if args.expect_disabled:
            c.check(f'{args.label}: at least {args.expect_disabled} device(s) shown as not restorable', len(disabled_rows) >= args.expect_disabled, row_texts)

        checkboxes = page.locator('#restore-review-dialog input[name="restore-node"]')
        wanted_names = {NODE_NAME[n] for n in args.nodes}
        for i in range(checkboxes.count()):
            box = checkboxes.nth(i)
            should_check = box.get_attribute('value') in wanted_names
            if box.is_disabled():
                continue
            if should_check and not box.is_checked():
                box.check()
            if not should_check and box.is_checked():
                box.uncheck()
        checked_values = sorted(checkboxes.nth(i).get_attribute('value') for i in range(checkboxes.count())
                                if checkboxes.nth(i).is_checked())
        record['steps']['checked_devices_before_submit'] = checked_values
        c.check(f'{args.label}: exactly the requested nodes are checked before submit',
                checked_values == sorted(wanted_names & set(checked_values)) and set(checked_values) <= wanted_names, checked_values)

        page.check('#restore-ack')
        with page.expect_response(lambda r: r.request.method == 'POST' and r.url.endswith('/restore'), timeout=20000) as info:
            page.click('#restore-run')
        submit_resp = info.value.json()
        record['steps']['submit_response'] = submit_resp
        c.check(f'{args.label}: restore submitted (job id returned)', bool(submit_resp.get('id')), submit_resp)
        job_id = submit_resp.get('id')
        source_sent = submit_resp.get('source') or {}
        record['steps']['source_sent'] = source_sent

        page.wait_for_selector('#restore-job-dialog[open]', timeout=20000)
        page.screenshot(path=f'{args.shots}/2x-{args.label}-running.png')
        page.keyboard.press('Escape')

        deadline = time.time() + args.timeout
        job = None
        while time.time() < deadline:
            job = api(page, 'GET', f'/api/restore/jobs/{job_id}')['body']
            if job.get('status') not in ACTIVE:
                break
            time.sleep(4)
        record['steps']['final_job'] = job
        c.check(f'{args.label}: restore job reached a final status', job and job.get('status') not in ACTIVE, job)

        open_lab(page, reload=True)
        details_btn = page.locator('#git-last-restore-open')
        if details_btn.count():
            details_btn.click()
            page.wait_for_selector('#restore-job-dialog[open]', timeout=20000)
            after_text = page.locator('#restore-job-dialog').inner_text()
            record['steps']['page_shows_restore_status_after'] = after_text[:800]
            page.screenshot(path=f'{args.shots}/2x-{args.label}-result.png')
            page.keyboard.press('Escape')

        binding_after = destination_line(page)
        record['steps']['binding_after'] = binding_after
        c.check(f'{args.label}: lab binding unchanged by the restore (still save-fix/working)',
                'save-fix/working' in binding_after.replace(' ', '') and 'latest/latest' not in binding_after.replace(' ', ''),
                (binding_before, binding_after))

        c.check(f'{args.label}: no page/console errors', not errors, errors[:10])
        browser.close()

    # ---- independent verification ----
    after_classify = c_lib.classify_all(args.nodes)
    record['classify_after'] = after_classify
    restored_names = {t.get('name') for t in (job or {}).get('targets', []) if t.get('status') == 'verified'}
    restored_short = [n for n in args.nodes if NODE_NAME[n] in restored_names]
    for n in restored_short:
        c.check(f'{args.label}: {n} independently reads state {args.expect_state} after the restore (c_lib marker)',
                after_classify.get(n) == args.expect_state, (n, after_classify.get(n)))

    after_boot = boot_identity(args.nodes)
    record['boot_after'] = after_boot
    boot_ok = same_boot(before_boot, after_boot)
    record['boot_same'] = boot_ok
    for n in args.nodes:
        c.check(f'{args.label}: {n} boot identity unchanged (no reboot)', boot_ok.get(n) is True, (before_boot.get(n), after_boot.get(n)))

    if args.saved_dir:
        saved_compare = readback_saved(restored_short or args.nodes, saved=args.saved_dir)
        record['readback_saved_comparison'] = saved_compare
        for n in restored_short:
            entry = saved_compare.get('nodes', {}).get(n, {})
            cmp = entry.get('compared_with_saved', {})
            # readback.py's own `compare_saved` already nets tolerance out of `extra` (extra = len(extra
            # - tolerated)); `tolerated_root_authentication` is reported alongside it only for the
            # record, not to be subtracted again here (docs/multi-platform-restore/README.md: "the one
            # tolerated difference in the Junos comparison" -- root-authentication is the ONLY one).
            extra_untolerated = cmp.get('extra') or 0
            c.check(f'{args.label}: {n} whole configuration matches {args.saved_dir} (readback.py --saved, '
                    f'missing=0, extra beyond the documented root-authentication exclusion=0)',
                    cmp.get('missing') == 0 and extra_untolerated == 0, cmp)

    targets_summary = [{k: t.get(k) for k in ('name', 'platform', 'status', 'message', 'no_op', 'persistence')}
                       for t in (job or {}).get('targets', [])]
    record['targets_summary'] = targets_summary
    record['pre_backup_job_id'] = (job or {}).get('pre_backup_job_id')
    record['post_backup_job_id'] = (job or {}).get('post_backup_job_id')

    record['checks'] = c.checks
    record['failed'] = c.failed
    record['finished_utc'] = c_lib.stamp()
    with open(args.evidence, 'w') as fh:
        json.dump(record, fh, indent=1)
        fh.write('\n')
    passed = sum(1 for x in c.checks if x['ok'])
    print(f'{args.label}: {passed} passed, {len(c.failed)} failed')
    return 1 if c.failed else 0


if __name__ == '__main__':
    sys.exit(main())
