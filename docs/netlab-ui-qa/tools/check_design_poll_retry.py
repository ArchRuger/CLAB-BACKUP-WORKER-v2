#!/usr/bin/env python3
"""QA-009 positive check: a failed progress poll on the Design tab is retried with the student told, and after
five failures the watch stops with *Plan progress unknown* instead of dying silently or polling forever.

Runs the fixture manager (real app, real netlab engine, no VM) on its own port, opens the 13-device lab
`BGP_TheoryToPractice` (its generation takes long enough to poll), starts Generate plan and, with Playwright
request interception (fault injection, labelled as such):

  A. fails the second design poll once with HTTP 500 → the state line must say "attempt 1 of 5 … Trying
     again", the poll must continue, and the plan must reach *Plan ready to review* with no reload;
  B. fails every poll after the generation has started → the state must become *Plan progress unknown* after
     the fifth failure, and no further design polls may be sent for the next 15 s (the watch stopped for good);
     Generate plan again (or reopening the tab) then loads afresh.

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/tools/check_design_poll_retry.py [--port 8104] [--out DIR]
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIXTURE = ROOT / 'docs' / 'redesign' / 'tools' / 'fixture_manager.py'
LAB = 'BGP_TheoryToPractice'


def wait_http(url, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200: return json.loads(response.read())
        except Exception:
            time.sleep(0.5)
    raise SystemExit('fixture manager did not answer at ' + url)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=8104)
    parser.add_argument('--out', default=str(HERE.parent / 'evidence' / 'design'))
    args = parser.parse_args()
    if not shutil.which('netlab'): raise SystemExit('netlab is not on PATH: run with the application venv first')
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix='poll-retry-fixture-'))
    base = 'http://127.0.0.1:%d' % args.port
    fixture = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(args.port), '--data', str(data)], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    checks = []
    def check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:400]}); print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:300]), flush=True)
    try:
        state = wait_http(base + '/api/state')
        lab = next(l for l in state['labs'] if l['name'] == LAB)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={'width': 1366, 'height': 768})
            errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
            design_polls = {'n': 0}; mode = {'fail_once': False, 'fail_all': False, 'failed': 0}
            def handle(route):
                url = route.request.url
                if route.request.method == 'GET' and re.search(r'/api/labs/[^/]+/design$', url):
                    design_polls['n'] += 1
                    if (mode['fail_once'] and design_polls['n'] == 2) or mode['fail_all']:
                        mode['failed'] += 1; mode['fail_once'] = False
                        route.fulfill(status=500, content_type='application/json', body='{"detail":"injected"}'); return
                route.continue_()
            page.route('**/api/labs/**', handle)
            page.goto(base + '/#lab=' + lab['id'] + '&view=design')
            page.wait_for_selector('#design-view:not([hidden])', timeout=15000)
            page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=15000)
            # A design to generate: OSPF + BGP through the guided controls, saved.
            for module in ('ospf', 'bgp'):
                box = page.locator('input[name="design-module"][value="%s"]' % module)
                if not box.is_checked(): box.check()
            page.fill('#design-bgp-as', '65010'); page.locator('#design-bgp-as').dispatch_event('change')
            page.click('#design-save')
            page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Unsaved")', timeout=15000)
            # A: one failed poll.
            design_polls['n'] = 0; mode['fail_once'] = True
            page.click('#design-generate')
            page.wait_for_function('() => (document.getElementById("design-detail")?.textContent || "").includes("attempt 1 of 5")', timeout=30000)
            detail = page.locator('#design-detail').text_content()
            check('A: the state line names the failed check and the retry', 'attempt 1 of 5' in detail and 'Trying again' in detail, detail)
            check('A: the header still reads Generating (the plan may well be generating)', 'Generating' in (page.locator('#design-state').text_content() or ''))
            page.screenshot(path=str(out / 'poll-retry-A-attempt.png'))
            page.wait_for_function('() => (document.getElementById("design-state")?.textContent || "").includes("Plan ready to review")', timeout=180000)
            check('A: the plan reaches Plan ready to review without a reload', True)
            check('A: the retry notice is gone once a poll succeeded', 'attempt' not in (page.locator('#design-detail').text_content() or ''), page.locator('#design-detail').text_content())
            page.screenshot(path=str(out / 'poll-retry-A-ready.png'))
            # B: every poll fails after the generation started.
            design_polls['n'] = 0; mode['failed'] = 0
            page.click('#design-generate')
            page.wait_for_function('() => (document.getElementById("design-state")?.textContent || "").includes("Generating")', timeout=30000)
            mode['fail_all'] = True
            page.wait_for_function('() => (document.getElementById("design-state")?.textContent || "").includes("Plan progress unknown")', timeout=120000)
            failed_at_stop = mode['failed']
            check('B: after the retries the state reads Plan progress unknown with the way out', 'after 5 retries' in (page.locator('#design-detail').text_content() or '') and 'Reload the page' in (page.locator('#design-detail').text_content() or ''), page.locator('#design-detail').text_content())
            check('B: six failed polls (the first, then five retries) were made before giving up', failed_at_stop == 6, 'failed polls: %d' % failed_at_stop)
            page.screenshot(path=str(out / 'poll-retry-B-unknown.png'))
            polls_before = design_polls['n']; page.wait_for_timeout(15000)
            # The 4 s heartbeat refreshes /api/state, not the design; the design watch must stay stopped.
            check('B: no further design polls for 15 s (the watch stayed stopped)', design_polls['n'] == polls_before, 'polls %d -> %d' % (polls_before, design_polls['n']))
            mode['fail_all'] = False
            # A deliberate step (Generate plan again) loads afresh; the running or finished generation shows again.
            page.click('#design-generate')
            page.wait_for_function('() => /Generating|Plan ready to review|already being generated/.test(document.getElementById("design-state")?.textContent || "")', timeout=30000)
            check('B: Generate plan again loads the design afresh (progress is watched again or the plan is ready)', True, page.locator('#design-state').text_content())
            page.wait_for_function('() => (document.getElementById("design-state")?.textContent || "").includes("Plan ready to review")', timeout=180000)
            check('no page errors', not errors, json.dumps(errors)[:300])
            browser.close()
    finally:
        fixture.terminate()
        try: fixture.wait(timeout=10)
        except subprocess.TimeoutExpired: fixture.kill()
        shutil.rmtree(data, ignore_errors=True)
    record = {'finished': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'checks': checks}
    (out / 'poll-retry.json').write_text(json.dumps(record, indent=1))
    failed = [c for c in checks if not c['ok']]
    print('%d checks, %d failed' % (len(checks), len(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
