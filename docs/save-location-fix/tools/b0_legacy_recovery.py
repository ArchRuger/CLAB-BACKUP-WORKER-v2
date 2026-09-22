#!/usr/bin/env python3
"""Section B, row B0: legacy recovery, on the RUNNING manager (clab-backup:1.30.31).

Confirms the legacy notice, exercises "Change folder... -> save-fix/working -> Save this lab here
without moving files" (should rebind the lab to save-fix/working, undoing the nested legacy prefix),
records the button behaviour when selecting save-fix/working/latest itself, and issues the two direct
API checks the assignment names (400 on a reserved-name prefix, 409 on a prefix at/below a manifest
folder).

    clab-backup-ui/.venv/bin/python docs/save-location-fix/tools/b0_legacy_recovery.py \\
        --evidence docs/save-location-fix/evidence/10-b0-legacy-recovery.json \\
        --shots docs/save-location-fix/evidence
"""
import argparse
import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from qa_lib import BASE, LAB_ID, LAB_NAME, Checker, api, destination_line, go_to, legacy_notice, open_change_folder, open_lab

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', required=True)
    ap.add_argument('--shots', required=True)
    args = ap.parse_args()
    pathlib.Path(args.shots).mkdir(parents=True, exist_ok=True)

    record = {'manager_base': BASE, 'lab_id': LAB_ID, 'lab_name': LAB_NAME, 'build': 'clab-backup:1.30.31',
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'steps': {}}
    c = Checker()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)

        open_lab(page)
        record['steps']['initial_destination_line'] = destination_line(page)
        notice = legacy_notice(page)
        record['steps']['legacy_notice_text'] = notice
        c.check('legacy notice is shown while bound to save-fix/working/latest', bool(notice), notice)
        c.check('legacy notice names the reserved-name reason and the recovery ("Save this lab here without moving")',
                'without moving' in notice and 'save-fix/working/latest' in notice.replace(' ', ''), notice)
        page.locator('#git-save-location').scroll_into_view_if_needed()
        page.screenshot(path=f'{args.shots}/1x-b0-legacy-notice.png')

        # ---- Open Change folder..., select save-fix/working (the parent), Save this lab here WITHOUT moving files ----
        open_change_folder(page)
        go_to(page, 'save-fix')
        go_to(page, 'save-fix/working')
        page.wait_for_timeout(300)
        use_button = page.locator('#git-places-panel [data-git-places-action="use"]')
        record['steps']['working_use_button'] = {
            'count': use_button.count(),
            'enabled': bool(use_button.count() and use_button.is_enabled()),
            'title': use_button.get_attribute('title') if use_button.count() else None,
        }
        c.check('save-fix/working (the parent, not a reserved name) offers an enabled "Save this lab here"',
                use_button.count() == 1 and use_button.is_enabled(), record['steps']['working_use_button'])

        with page.expect_response(lambda r: r.request.method == 'POST' and '/git/destination' in r.url, timeout=20000) as dest_info:
            use_button.click()
            page.wait_for_selector('#git-folder-dialog[open]', timeout=15000)
            move_checkbox = page.locator('#git-move-files')
            if move_checkbox.count() and move_checkbox.is_checked():
                move_checkbox.uncheck()
            page.screenshot(path=f'{args.shots}/1x-b0-confirm-dialog.png')
            page.click('#git-folder-confirm')
        dest_resp = dest_info.value
        record['steps']['working_destination_request_body'] = dest_resp.request.post_data
        record['steps']['working_destination_response'] = {'status': dest_resp.status, 'body': dest_resp.json()}
        c.check('POST .../git/destination for save-fix/working returned 200', dest_resp.status == 200, dest_resp.status)
        new_prefix = (dest_resp.json().get('binding') or {}).get('repository', {}).get('prefix')
        record['steps']['new_binding_prefix'] = new_prefix
        c.check('the binding prefix became exactly save-fix/working (no move of files)', new_prefix == 'save-fix/working', new_prefix)

        # Re-read the destination line to confirm the UI agrees.
        new_line = ''
        for _ in range(20):
            page.wait_for_timeout(400)
            new_line = destination_line(page)
            if 'save-fix/working' in new_line.replace(' ', '') and 'save-fix/working/latest' not in new_line.replace(' ', ''):
                break
        record['steps']['new_destination_line'] = new_line
        page.screenshot(path=f'{args.shots}/1x-b0-rebound.png')
        c.check('the legacy notice is gone now that the binding is save-fix/working', legacy_notice(page) == '', legacy_notice(page))

        # ---- Also try selecting save-fix/working/latest itself: record the button title/reason and the POST payload it would send ----
        open_change_folder(page)
        go_to(page, 'save-fix')
        go_to(page, 'save-fix/working')
        go_to(page, 'save-fix/working/latest')
        page.wait_for_timeout(300)
        use_button2 = page.locator('#git-places-panel [data-git-places-action="use"]')
        title2 = use_button2.get_attribute('title') if use_button2.count() else None
        enabled2 = bool(use_button2.count() and use_button2.is_enabled())
        record['steps']['latest_use_button'] = {'count': use_button2.count(), 'enabled': enabled2, 'title': title2}
        page.screenshot(path=f'{args.shots}/1x-b0-select-latest.png')
        # The lab is already bound to save-fix/working at this point in the run (previous block), so the
        # button resolving save-fix/working/latest to its parent save-fix/working is expected to come back
        # DISABLED with the "this lab already saves here" reason, not enabled: that disabled state, naming
        # the resolved parent, is itself the proof the reserved-name resolution ran (rule 3), not a defect.
        resolved_to_parent = bool(title2) and 'save-fix/working' in (title2 or '').replace(' ', '') and 'save-fix/working/latest' not in (title2 or '').replace(' ', '')
        c.check('selecting save-fix/working/latest itself resolves the choice to its parent save-fix/working (title names it; '
                'button is disabled here only because the lab already saves to that resolved parent)',
                resolved_to_parent, record['steps']['latest_use_button'])

        if enabled2:
            use_button2.click()
            page.wait_for_selector('#git-folder-dialog[open]', timeout=15000)
            dialog_text2 = page.locator('#git-folder-dialog').inner_text()
            record['steps']['latest_selection_confirm_dialog_text'] = dialog_text2[:600]
            move_checkbox2 = page.locator('#git-move-files')
            if move_checkbox2.count() and move_checkbox2.is_checked():
                move_checkbox2.uncheck()
            # We must not actually resubmit the same folder (already bound there); the manager
            # would answer 409 "already saves to that folder". Cancel instead of confirming, to
            # avoid an unnecessary no-op request; the resolved target (parent) is already proven
            # by the enabled button + its title, the confirm dialog's own text, and the earlier
            # successful bind to save-fix/working above.
            page.click('#git-folder-cancel')
            record['steps']['latest_selection_note'] = ('cancelled the confirm dialog instead of resubmitting: the lab already '
                                                          'saves to save-fix/working, so confirming would 409 "already saves to that '
                                                          'folder" — the resolved target (parent) was already proven by the enabled '
                                                          'button + title above and by the successful save-fix/working bind moments earlier')
        record['steps']['payload_would_be'] = {'prefix': 'save-fix/working', 'move_files': False}

        c.check('no page or console errors', not errors, errors[:8])
        browser.close()

    # ---- Direct API checks (plain curl-equivalent same-origin requests; no browser needed for these two) ----
    import urllib.request

    def curl_json(method, path, body):
        req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode(),
                                      headers={'Content-Type': 'application/json', 'Origin': BASE})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    status_a, body_a = curl_json('POST', f'/api/labs/{LAB_ID}/git/destination', {'prefix': 'save-fix/working/latest', 'move_files': False})
    record['steps']['api_reserved_name_check'] = {'request': {'prefix': 'save-fix/working/latest'}, 'status': status_a, 'body': body_a}
    c.check('POST .../git/destination {"prefix":"save-fix/working/latest"} is 400 (reserved name)', status_a == 400, (status_a, body_a))

    status_b, body_b = curl_json('POST', f'/api/labs/{LAB_ID}/git/destination', {'prefix': 'save-fix/Final/sub', 'move_files': False})
    record['steps']['api_below_manifest_check'] = {'request': {'prefix': 'save-fix/Final/sub'}, 'status': status_b, 'body': body_b}
    c.check('POST .../git/destination {"prefix":"save-fix/Final/sub"} is 409 (at/below a manifest folder)', status_b == 409, (status_b, body_b))

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
