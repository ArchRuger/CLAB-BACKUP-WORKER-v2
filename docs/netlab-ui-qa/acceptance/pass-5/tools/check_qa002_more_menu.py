#!/usr/bin/env python3
"""Acceptance pass 5 adversarial check: QA-002 (More menu items without a client-side reason).

DEFECTS.md records QA-002 as "fixed, awaiting independent retest ... Author retest: unit (66/66).
Deployed build and independent retest: pending the next deploy." None of the charter's step-3 tools
(check_design_ui.py, check_design_poll_retry.py, stress_design.py, coverage_run.py, design_probes.py)
assert on the four More-menu items' disabled state or their reason text, so this is an independent,
real-browser reproduction of the fix against the fixture manager (real app, real netlab engine, no VM).

Checks, against a fresh ospf-basics lab:

  1. Before any design exists: Download design file, Renumber and Remove design are disabled with the
     reasons "Save a design first." / "Save a design first." / "There is no design to remove."; a
     forced click dispatches no navigation/popup (the pre-fix bug opened a 404 in a new tab).
  2. After Save: all four items are enabled (reason "").
  3. While Generate plan is running (state includes "Generating"): Import design file, Renumber and
     Remove design read the busy reason "Wait for the plan being generated to finish."; Download design
     file stays enabled (a saved, non-draft design).

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/acceptance/pass-5/tools/check_qa002_more_menu.py --port 8165 --data <fresh>

Exit status 1 if any check failed.
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

CHECKS = []


def check(name, ok, detail=''):
    CHECKS.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:300]})
    print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:200]), flush=True)


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


def item_state(page, item_id):
    el = page.locator('#' + item_id)
    disabled = el.get_attribute('disabled') is not None
    title = el.get_attribute('title') or ''
    return disabled, title


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=8165)
    parser.add_argument('--data', default=None)
    args = parser.parse_args()
    data = Path(args.data) if args.data else Path(tempfile.mkdtemp(prefix='qa002-fixture-'))
    data.mkdir(parents=True, exist_ok=True)
    base = 'http://127.0.0.1:%d' % args.port
    fixture = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(args.port), '--data', str(data)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    started = datetime.now(timezone.utc).isoformat(timespec='seconds')
    popups = []
    try:
        state = wait_http(base + '/api/state')
        lab = next(l for l in state['labs'] if l['name'] == LAB)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.on('popup', lambda p: popups.append(p.url))
            page.goto(base + '/#lab=' + lab['id'] + '&view=design')
            page.wait_for_selector('#design-view:not([hidden])', timeout=15000)
            page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=15000)
            page.click('#design-more-button')  # open the More menu so the items are visible before we assert on them
            page.wait_for_timeout(200)

            # --- 1. before any design exists ---
            exp_disabled, exp_title = item_state(page, 'design-export')
            check('QA-002/1 Download design file is disabled before a design exists', exp_disabled, exp_title)
            check('QA-002/1 Download design file reason says to save first', exp_title == 'Save a design first.', exp_title)
            ren_disabled, ren_title = item_state(page, 'design-renumber')
            check('QA-002/1 Renumber is disabled before a design exists', ren_disabled, ren_title)
            check('QA-002/1 Renumber reason says to save first', ren_title == 'Save a design first.', ren_title)
            clr_disabled, clr_title = item_state(page, 'design-clear')
            check('QA-002/1 Remove design is disabled before a design exists', clr_disabled, clr_title)
            check('QA-002/1 Remove design reason says there is no design', clr_title == 'There is no design to remove.', clr_title)
            # A visible menu-reason line under each disabled item (not just title="", the original bug's leftover markup).
            for item, want in (('design-export', 'Save a design first.'), ('design-renumber', 'Save a design first.'), ('design-clear', 'There is no design to remove.')):
                small = page.locator('#' + item + ' small.menu-reason')
                reason_text = (small.first.text_content() or '').strip() if small.count() else ''
                check('QA-002/1 %s carries a visible reason line' % item, reason_text == want, reason_text)
            # Force a click on the disabled control: real browsers refuse pointer events on [disabled]. Prove no
            # popup/new tab opened (the pre-fix bug opened a 404 in a new tab for Download design file).
            page.locator('#design-export').click(force=True)
            page.wait_for_timeout(300)
            check('QA-002/1 forcing a click on a disabled Download design file opens no popup/tab', popups == [], popups)

            # --- 2. after Save ---
            page.fill('#design-pool-lan-ipv4', '172.16.0.0/16')
            page.locator('#design-pool-lan-ipv4').dispatch_event('change')
            page.locator('input[name="design-module"][value="ospf"]').check()
            page.click('#design-save')
            page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Unsaved")', timeout=10000)
            page.click('#design-more-button')
            page.wait_for_timeout(200)
            for item in ('design-export', 'design-import', 'design-renumber', 'design-clear'):
                disabled, title = item_state(page, item)
                check('QA-002/2 %s is enabled once a design is saved' % item, not disabled and title == '', (disabled, title))

            # --- 3. while Generate plan is running ---
            page.click('#design-generate')
            page.wait_for_function('(w) => (document.getElementById("design-state")?.textContent || "").includes(w)', arg='Generating', timeout=10000)
            page.click('#design-more-button')
            page.wait_for_timeout(50)
            imp_disabled, imp_title = item_state(page, 'design-import')
            check('QA-002/3 Import design file is disabled while generating', imp_disabled, imp_title)
            check('QA-002/3 Import reason names the busy wait', imp_title == 'Wait for the plan being generated to finish.', imp_title)
            ren_disabled2, ren_title2 = item_state(page, 'design-renumber')
            check('QA-002/3 Renumber is disabled while generating', ren_disabled2, ren_title2)
            check('QA-002/3 Renumber reason names the busy wait', ren_title2 == 'Wait for the plan being generated to finish.', ren_title2)
            clr_disabled2, clr_title2 = item_state(page, 'design-clear')
            check('QA-002/3 Remove design is disabled while generating', clr_disabled2, clr_title2)
            check('QA-002/3 Remove design reason names the busy wait', clr_title2 == 'Wait for the plan being generated to finish.', clr_title2)
            exp_disabled2, exp_title2 = item_state(page, 'design-export')
            check('QA-002/3 Download design file stays enabled while generating (saved, non-draft)', not exp_disabled2 and exp_title2 == '', (exp_disabled2, exp_title2))
            page.wait_for_function('(w) => (document.getElementById("design-state")?.textContent || "").includes(w)', arg='Plan ready', timeout=120000)
            browser.close()
    finally:
        fixture.terminate()
        try:
            fixture.wait(timeout=10)
        except Exception:
            fixture.kill()
    finished = datetime.now(timezone.utc).isoformat(timespec='seconds')
    failed = [c for c in CHECKS if not c['ok']]
    print('%d checks, %d failed' % (len(CHECKS), len(failed)))
    result = {'started': started, 'finished': finished, 'checks': CHECKS, 'popups': popups}
    out = HERE.parent / 'qa002-more-menu-results.json'
    out.write_text(json.dumps(result, indent=2) + '\n')
    print('wrote', out)
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
