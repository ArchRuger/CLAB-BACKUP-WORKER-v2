#!/usr/bin/env python3
"""Acceptance pass 7's own adversarial check: QA-002 (Design tab's More menu never explained why
Download design file / Import design file… / Renumber / Remove design were disabled, although the
routes behind them refuse with 404/409). The defect ledger records this as fixed via
`designMoreMenuReasons()` in network-design.js, but none of the charter's replay tools (check_design_ui.py,
check_design_poll_retry.py, stress_design.py, coverage_run.py, design_probes.py) drives the More menu's
four items through real clicks and reads their `disabled` state and `.menu-reason` text end to end across
every state transition (empty -> unsaved draft -> saved -> generating). coverage_run.py's committed
coverage.json rows for ND-EXPORT-001/ND-IMPORT-001 predate the fix and only note the pre-fix asymmetry as
a "note", not a live retest of the disabled reasons.

Drives a real Chromium (Playwright) against the fixture manager (real app, real netlab engine, no VM),
never the deployed product. Real clicks on the More menu button and its items; reads DOM state only.

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/acceptance/pass-7/tools/check_more_menu_reasons.py --port 8185

Exit status 1 when a check failed or an unexpected console/page error was seen.
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
FIXTURE = ROOT / 'docs' / 'redesign' / 'tools' / 'fixture_manager.py'
LAB = 'ospf-basics'

WAIT = 'Wait for the plan being generated to finish.'
SAVE_FIRST = 'Save a design first.'
NOTHING_TO_REMOVE = 'There is no design to remove.'
UNSAVED = 'Save or discard your unsaved changes first.'
EXPORT_STALE = 'Save the design first: the download is the saved design, not your unsaved changes.'


def wait_http(url, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return json.loads(response.read())
        except Exception:
            time.sleep(0.5)
    raise SystemExit('fixture manager did not answer at ' + url)


class Run:
    def __init__(self, page):
        self.page = page
        self.console, self.pageerrors, self.checks = [], [], []
        page.on('console', lambda m: self.console.append({'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.pageerrors.append(str(e)))

    def check(self, name, ok, detail=''):
        self.checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:300]})
        print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:200]), flush=True)

    def open_menu(self):
        if self.page.locator('#design-more-menu').get_attribute('hidden') is None:
            self.page.click('#design-more-button')
            self.page.wait_for_timeout(50)
        else:
            self.page.click('#design-more-button')
            self.page.wait_for_selector('#design-more-menu:not([hidden])', timeout=5000)

    def close_menu(self):
        if self.page.locator('#design-more-menu').get_attribute('hidden') is None:
            self.page.click('#design-more-button')

    def item_state(self, item_id):
        disabled = self.page.eval_on_selector('#' + item_id, 'el => el.disabled')
        reason_el = self.page.locator('#' + item_id + ' .menu-reason')
        reason_hidden = reason_el.get_attribute('hidden') is not None
        reason_text = reason_el.text_content() or ''
        title = self.page.eval_on_selector('#' + item_id, 'el => el.title')
        return disabled, reason_text.strip(), reason_hidden, title


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=8185)
    args = parser.parse_args()
    data = Path(tempfile.mkdtemp(prefix='more-menu-fixture-'))
    base = 'http://127.0.0.1:%d' % args.port
    fixture = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(args.port), '--data', str(data)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    started = datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        state = wait_http(base + '/api/state')
        lab = next(l for l in state['labs'] if l['name'] == LAB)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            chromium_version = browser.version
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            r = Run(page)
            page.goto(base + '/#lab=' + lab['id'] + '&view=design')
            page.wait_for_selector('#design-view:not([hidden])', timeout=15000)
            page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=15000)

            # --- State 1: empty lab, no design saved, nothing edited. ---
            r.open_menu()
            exp_d, exp_r, exp_h, _ = r.item_state('design-export')
            imp_d, imp_r, imp_h, _ = r.item_state('design-import')
            ren_d, ren_r, ren_h, _ = r.item_state('design-renumber')
            clr_d, clr_r, clr_h, _ = r.item_state('design-clear')
            r.check('empty lab: Download design file is disabled with "Save a design first."', exp_d and exp_r == SAVE_FIRST and not exp_h, (exp_d, exp_r, exp_h))
            r.check('empty lab: Import design file… is enabled (nothing saved yet, nothing unsaved either)', not imp_d and imp_r == '' and imp_h, (imp_d, imp_r, imp_h))
            r.check('empty lab: Renumber is disabled with "Save a design first."', ren_d and ren_r == SAVE_FIRST and not ren_h, (ren_d, ren_r, ren_h))
            r.check('empty lab: Remove design is disabled with "There is no design to remove."', clr_d and clr_r == NOTHING_TO_REMOVE and not clr_h, (clr_d, clr_r, clr_h))
            r.close_menu()

            # Attempting a real click on a disabled item must do nothing (no navigation, no dialog).
            popup_seen = []
            page.on('popup', lambda p: popup_seen.append(p))
            r.open_menu()
            page.click('#design-renumber', force=True)
            page.wait_for_timeout(200)
            dialog_open = page.locator('#design-renumber-dialog[open]').count() > 0
            r.check('clicking the disabled Renumber item opens no dialog', not dialog_open, dialog_open)
            r.close_menu()

            # --- State 2: an unsaved edit (draft), not yet saved. ---
            for module in ('ospf',):
                box = page.locator('input[name="design-module"][value="%s"]' % module)
                if not box.is_checked():
                    box.check()
            page.wait_for_function('() => (document.getElementById("design-state")?.textContent || "").includes("Unsaved")', timeout=5000)
            r.open_menu()
            exp_d, exp_r, exp_h, _ = r.item_state('design-export')
            imp_d, imp_r, imp_h, _ = r.item_state('design-import')
            r.check('unsaved draft: Download design file still disabled with "Save a design first." (nothing saved yet)', exp_d and exp_r == SAVE_FIRST, (exp_d, exp_r))
            r.check('unsaved draft: Import design file… is disabled with the unsaved-changes reason', imp_d and imp_r == UNSAVED and not imp_h, (imp_d, imp_r, imp_h))
            r.close_menu()

            # --- State 3: saved design, nothing generating. ---
            page.click('#design-save')
            page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Unsaved")', timeout=10000)
            r.open_menu()
            exp_d, exp_r, exp_h, _ = r.item_state('design-export')
            imp_d, imp_r, imp_h, _ = r.item_state('design-import')
            ren_d, ren_r, ren_h, _ = r.item_state('design-renumber')
            clr_d, clr_r, clr_h, _ = r.item_state('design-clear')
            r.check('saved design: Download design file is enabled with no reason', not exp_d and exp_r == '' and exp_h, (exp_d, exp_r, exp_h))
            r.check('saved design: Import design file… is enabled with no reason', not imp_d and imp_r == '' and imp_h, (imp_d, imp_r, imp_h))
            r.check('saved design: Renumber is enabled with no reason', not ren_d and ren_r == '' and ren_h, (ren_d, ren_r, ren_h))
            r.check('saved design: Remove design is enabled with no reason', not clr_d and clr_r == '' and clr_h, (clr_d, clr_r, clr_h))
            r.close_menu()

            # --- State 4: a plan is generating (real netlab engine run). ---
            page.click('#design-generate')
            page.wait_for_function('() => (document.getElementById("design-state")?.textContent || "").includes("Generating")', timeout=10000)
            r.open_menu()
            exp_d, exp_r, exp_h, _ = r.item_state('design-export')
            imp_d, imp_r, imp_h, _ = r.item_state('design-import')
            ren_d, ren_r, ren_h, _ = r.item_state('design-renumber')
            clr_d, clr_r, clr_h, _ = r.item_state('design-clear')
            r.check('generating: Download design file stays enabled (it downloads the saved design, not the plan)', not exp_d and exp_r == '', (exp_d, exp_r))
            r.check('generating: Import design file… is disabled with the "wait for the plan" reason', imp_d and imp_r == WAIT and not imp_h, (imp_d, imp_r, imp_h))
            r.check('generating: Renumber is disabled with the "wait for the plan" reason', ren_d and ren_r == WAIT and not ren_h, (ren_d, ren_r, ren_h))
            r.check('generating: Remove design is disabled with the "wait for the plan" reason', clr_d and clr_r == WAIT and not clr_h, (clr_d, clr_r, clr_h))
            r.close_menu()
            page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Generating")', timeout=30000)

            r.check('no unexpected console errors', len(r.console) == 0, r.console)
            r.check('no page errors', len(r.pageerrors) == 0, r.pageerrors)

            browser.close()
    finally:
        fixture.terminate()
        try:
            fixture.wait(timeout=10)
        except Exception:
            fixture.kill()

    total = len(r.checks)
    failed = [c for c in r.checks if not c['ok']]
    print('%d of %d checks passed; %d console errors; %d page errors' % (total - len(failed), total, len(r.console), len(r.pageerrors)))
    print('started %s, chromium %s' % (started, chromium_version))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
