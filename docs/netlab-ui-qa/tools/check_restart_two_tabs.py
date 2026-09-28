#!/usr/bin/env python3
"""Adversarial Restart device checks on a real running manager: two tabs, repeated clicks, and a review
that went stale because another lab operation ran after it. Uses a cheap device (host1 by default) so
the restarts themselves take a fraction of a second.

  1. Tab A and tab B each open *Restart device…* for the same device (both reviews are valid).
  2. Tab A confirms with a double click: exactly one job is created (the second click lands on a
     disabled button while the first request is in flight).
  3. After that job finished, tab B confirms its older review: the manager refuses it ("Another lab
     operation ran after this review. Review the restart again."), no second job exists, the device's
     container was not restarted a second time, and tab B's dialog shows the reason and stays usable
     (Cancel closes it; a fresh review then works).
  4. Two tabs racing at the same moment (both confirm within milliseconds): at most one job runs; the
     loser sees "Wait for the current lab operation to finish." or the stale-review refusal.

Before each step that opens a menu the tool waits until the page's own busy() reads false (the manager is one
process with one busy guard, so another lab's operation would otherwise make a step look stuck); the waits are
recorded. A control that still stays unavailable is a failed check and the JSON record is written anyway.

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-ui-qa/tools/check_restart_two_tabs.py --url http://127.0.0.1:8081 --lab restore-square --device host1

Exit status 1 when a check failed or an unexpected console/page error was seen; 0 otherwise.
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_restart_device import call, docker_inspect, follow_job, open_map_menu, review_open, review_text  # noqa: E402

HERE = Path(__file__).resolve().parent
HANDLED = 'Failed to load resource: the server responded with a status of '


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def restart_jobs(base, lab_id, node_name):
    status, jobs = call(base, '/api/operations')
    return [j for j in jobs if j.get('lab_id') == lab_id and j.get('action') == 'restart-node' and j.get('node') == node_name] if status == 200 else []


def error_text(page):
    return page.evaluate("() => document.querySelector('#operation-review .form-error')?.textContent || ''")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://127.0.0.1:8081')
    parser.add_argument('--lab', default='restore-square')
    parser.add_argument('--device', default='host1')
    parser.add_argument('--out', default=str(HERE.parent / 'evidence' / 'restart'))
    args = parser.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    status, state = call(args.url, '/api/state')
    lab = next((l for l in state['labs'] if l['name'] == args.lab), None)
    node = next((n for n in lab['nodes'] if (n.get('short_name') or n['name']) == args.device), None) if lab else None
    if not node: raise SystemExit('no lab/device')
    checks = []; console = []; errors = []
    def check(name, ok, detail=''):
        checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:400]}); print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:300]), flush=True)
    record = {'started': now(), 'manager': state.get('version'), 'device': node['name'], 'steps': {}}
    def wait_idle(page, budget=90):
        # Seconds until the page's own busy() (app.js) reads false, or the budget when it never does.
        t0 = time.monotonic()
        try: page.wait_for_function("() => typeof busy === 'function' && !busy()", timeout=budget * 1000)
        except PlaywrightTimeout: pass
        return round(time.monotonic() - t0, 1)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        def tab():
            page = browser.new_page(viewport={'width': 1366, 'height': 768})
            page.on('console', lambda m: console.append(m.text) if m.type == 'error' else None)
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(args.url + '/#lab=' + lab['id'] + '&view=topology')
            page.wait_for_selector('#topology-map [data-map-node="%s"]' % node['name'], timeout=30000); page.wait_for_timeout(1000)
            return page
        a, b = tab(), tab()
        before = docker_inspect([node['name']])[node['name']]; jobs_before = len(restart_jobs(args.url, lab['id'], node['name']))
        # Every step runs inside one guard: a control that stays unavailable (the manager busy with another lab's
        # operation, a menu opened while the tab still read a finished job as running) is recorded as a failed check
        # and the record is still written, instead of the run aborting without it (TOOL-004, TOOL-005).
        record['steps']['idle_before_start'] = max(wait_idle(a), wait_idle(b))
        try:
            # 1. Two valid reviews.
            open_map_menu(a, node['name']).click(); review_open(a)
            open_map_menu(b, node['name']).click(); review_open(b)
            check('two tabs can each open a review for the same device', 'Restart ' in review_text(a) and 'Restart ' in review_text(b))
            # 2. Double click in A.
            a.locator('#op-confirm').dblclick()
            a.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=20000)
            time.sleep(1.5)
            jobs = restart_jobs(args.url, lab['id'], node['name'])
            check('a double click creates exactly one job', len(jobs) == jobs_before + 1, 'jobs: %d before, %d now' % (jobs_before, len(jobs)))
            job = follow_job(args.url, jobs[0]['id']) if jobs else None
            check('the job succeeded', bool(job) and job['status'] == 'succeeded', job and job.get('message'))
            after_first = docker_inspect([node['name']])[node['name']]
            check('the device restarted once (new start time, same id)', after_first['id'] == before['id'] and after_first['started'] > before['started'], json.dumps(after_first))
            record['steps']['double_click'] = {'jobs': len(jobs), 'job': job and {k: job.get(k) for k in ('id', 'status', 'message', 'created', 'finished')}, 'before': before, 'after': after_first}
            # 3. B confirms its stale review.
            b.click('#op-confirm')
            for _ in range(20):
                if error_text(b): break
                b.wait_for_timeout(500)
            text = error_text(b)
            check('the older review is refused with the reason', 'ran after this review' in text, text)
            check('the refused tab keeps its dialog open with the reason inline', b.evaluate("() => document.getElementById('operation-review').open"))
            b.screenshot(path=str(out / 'two-tabs-stale-review.png'))
            time.sleep(1.5)
            after_stale = docker_inspect([node['name']])[node['name']]
            check('no second job and no second restart', len(restart_jobs(args.url, lab['id'], node['name'])) == jobs_before + 1 and after_stale['started'] == after_first['started'], json.dumps(after_stale))
            check('Cancel closes the refused dialog', b.click('#op-cancel') or b.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=5000) or True)
            record['steps']['stale_review'] = {'error': text, 'after': after_stale}
            # A fresh review from B works.
            # The page decides the menu's Restart entry from its own last state poll (4 s apart); a menu opened while
            # that poll still showed the finished job as running keeps the entry disabled until it is reopened. Wait
            # until the tab itself reports idle, the way a student would see the entry enabled, and record the wait.
            record['steps']['idle_waits'] = [wait_idle(b), None]
            open_map_menu(b, node['name']).click(); review_open(b)
            check('a fresh review after the refusal is offered again', 'Restart ' in review_text(b))
            b.click('#op-cancel'); b.wait_for_selector('dialog#operation-review[open]', state='hidden', timeout=5000)
            # 4. Both confirm at the same moment.
            record['steps']['idle_waits'][1] = max(wait_idle(a), wait_idle(b))
            open_map_menu(a, node['name']).click(); review_open(a)
            open_map_menu(b, node['name']).click(); review_open(b)
            jobs_now = len(restart_jobs(args.url, lab['id'], node['name'])); start_before = docker_inspect([node['name']])[node['name']]['started']
            a.evaluate("() => document.getElementById('op-confirm').click()"); b.evaluate("() => document.getElementById('op-confirm').click()")
            time.sleep(3)
            jobs = restart_jobs(args.url, lab['id'], node['name'])
            for j in jobs[:2]: follow_job(args.url, j['id'], timeout=60)
            time.sleep(1)
            texts = [error_text(a), error_text(b)]
            opens = [a.evaluate("() => document.getElementById('operation-review').open"), b.evaluate("() => document.getElementById('operation-review').open")]
            check('two simultaneous confirmations start at most one job', len(jobs) - jobs_now <= 1, 'new jobs: %d' % (len(jobs) - jobs_now))
            check('the loser sees a busy or stale refusal, the winner\'s dialog closed', sum(opens) == 1 and any(('Wait for the current lab operation' in t) or ('ran after this review' in t) for t in texts), json.dumps({'errors': texts, 'open': opens}))
            record['steps']['race'] = {'new_jobs': len(jobs) - jobs_now, 'errors': texts, 'open': opens, 'started_before': start_before, 'started_after': docker_inspect([node['name']])[node['name']]['started']}
        except PlaywrightTimeout as exc:
            check('every step ran without a stuck control', False, 'a control stayed unavailable: ' + str(exc).splitlines()[0][:200])
        for page in (a, b):
            if page.evaluate("() => document.getElementById('operation-review')?.open"): page.click('#op-cancel')
        unexpected = [c for c in console if not c.startswith(HANDLED)]
        check('no unexpected console errors', not unexpected, json.dumps(unexpected)[:400]); check('no page errors', not errors, json.dumps(errors)[:400])
        browser.close()
    record['checks'] = checks; record['finished'] = now()
    (out / ('two-tabs-%s-%s.json' % (args.device, record['started'].replace(':', '')))).write_text(json.dumps(record, indent=1))
    failed = [c for c in checks if not c['ok']]
    print('%d checks, %d failed' % (len(checks), len(failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
