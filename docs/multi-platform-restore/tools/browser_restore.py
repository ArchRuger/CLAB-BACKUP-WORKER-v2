#!/usr/bin/env python3
"""Browser acceptance of *Replace running configuration* against the RUNNING manager and the real lab.

The student's path, not the API: lab card -> Progress tab -> Saved versions -> "Apply to running
lab..." -> review dialog -> acknowledgement -> progress -> result. While the job runs the dialog is
closed and reopened from the lab banner, and the page is reloaded once, because a student does both.
Checks are printed as ok / FAIL / n/a lines and written, with what the page said, the identity of the
running build and the devices' own answer before and after (tools/readback.py), to a JSON evidence file.
A check that could not be exercised in a run is recorded as "n/a", never as a pass.

    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/browser_restore.py \\
        --row Latest --nodes ceos vjunos-switch --drift --viewport desktop --evidence evidence/NN-browser.json

    --row          visible name of the Saved versions row (e.g. "Latest", or a folder's name)
    --via row|view row: the row's own "Apply to running lab..." (repository FOLDER source);
                   view: the row's View dialog and its "Apply to running lab..." (commit-pinned GIT VERSION source)
    --nodes        short device names to restore; every other eligible device is unticked
    --drift        first put the chosen devices on configuration B (lab/drift/<node>-B.cli); the run then
                   requires the devices themselves to say B before and A after, and the job to say no_op false
    --expect       final per-device badge text expected (default "Replaced and verified")
    --expect-disabled N   the review must list at least N devices that cannot be restored, each with a reason
    --bystanders   devices that are drifted to B as well but NOT selected: afterwards they must still run B, untouched
                   (they are left on B: restore them afterwards)
    --review-only  stop after checking the review dialog (nothing is changed)
    --again        after the result: take a backup from the page, drift again, and restore once more in the same session
    --show-job ID  only open an existing job's result in the page and record its badges and help lines
    --saved DIR    saved folder of the repository checkout for the independent whole-configuration comparison

It changes real devices: run it only as the lab's single operator. Needs playwright (in the app's
virtual environment on the development VM).
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

from manager_restore import build_identity, readback

LAB = 'restore-square'
ROOT = pathlib.Path(__file__).resolve().parents[3]
TOOLS = pathlib.Path(__file__).resolve().parent
VIEWPORTS = {'desktop': {'width': 1366, 'height': 900}, 'tablet': {'width': 768, 'height': 1024},
             'narrow': {'width': 390, 'height': 844}}
ACTIVE = ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')
results, failed = [], []


def check(name, ok, detail=None):
    """ok is True, False, or None for "could not be exercised in this run" (recorded, never counted as a pass)."""
    print(('n/a  ' if ok is None else 'ok   ' if ok else 'FAIL ') + name + (f' :: {detail}' if detail and not ok else ''), flush=True)
    results.append({'check': name, 'ok': ok, 'detail': str(detail)[:600]})
    if ok is False:
        failed.append(name)


def _same_boot(before, after):
    """No NOS restart between two tools/readback.py answers: Junos gives an absolute boot time (must be equal);
    cEOS (age of PID 1) and IOS XR (uptime) give seconds up, which must not have gone down."""
    if not before or not after or not before.get('boot') or not after.get('boot'):
        return False
    if 'booted' in before['boot']:
        return before['boot'] == after['boot']
    return bool(before.get('up_seconds')) and bool(after.get('up_seconds')) and after['up_seconds'] >= before['up_seconds'] - 90


def drift(nodes):
    for node in nodes:
        subprocess.run([sys.executable, str(TOOLS / 'nodecli.py'), node, '--tag', 'drift-b', '--timeout', '240', '--file',
                        str(ROOT / 'docs/multi-platform-restore/lab/drift' / f'{node}-B.cli')],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8081')
    parser.add_argument('--row', default='Latest')
    parser.add_argument('--via', choices=['row', 'view'], default='row')
    parser.add_argument('--nodes', nargs='*', default=[])
    parser.add_argument('--drift', action='store_true')
    parser.add_argument('--bystanders', nargs='*', default=[])
    parser.add_argument('--viewport', choices=sorted(VIEWPORTS), default='desktop')
    parser.add_argument('--expect', default='Replaced and verified')
    parser.add_argument('--expect-disabled', type=int, default=0)
    parser.add_argument('--review-only', action='store_true')
    parser.add_argument('--again', action='store_true')
    parser.add_argument('--show-job')
    parser.add_argument('--saved')
    parser.add_argument('--evidence')
    parser.add_argument('--shots')
    parser.add_argument('--timeout', type=int, default=900, help='seconds to wait for the job to end')
    args = parser.parse_args()
    version = json.load(urllib.request.urlopen(args.base + '/api/state', timeout=20))['version']
    record = {'manager_version': version, 'build': build_identity(), 'viewport': args.viewport, 'row': args.row, 'via': args.via,
              'nodes': args.nodes, 'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'runs': []}
    wanted = ['clab-%s-%s' % (LAB, n) for n in args.nodes]

    def shot(page, name):
        if args.shots:
            page.screenshot(path=f'{args.shots}/{args.viewport}-{name}.png', full_page=False)

    def open_lab(page, reload=False):
        # The manager reopens the lab the student had open, so after a reload the lab view is already
        # there and no lab card exists; on a first visit the card is clicked.
        page.reload() if reload else page.goto(args.base + '/')
        page.wait_for_selector('article.lab-card, #tab-progress', state='visible', timeout=30000)
        if page.locator('article.lab-card').count():
            page.click(f'article.lab-card:has(h3:text-is("{LAB}")) [data-lab]')
        page.click('#tab-progress')

    def job_status(page, job_id):
        return page.evaluate('(id) => fetch("/api/restore/jobs/" + id).then(r => r.json()).then(j => j.status)', job_id)

    def open_review(page, run):
        page.wait_for_selector('#git-saved-versions [data-git-version-action]', timeout=60000)
        row = page.locator(f'#git-saved-versions li.git-version-row:has(.git-version-name strong:text-is("{args.row}"))').first
        check('the Saved versions list has the row', row.count() > 0, args.row)
        if args.via == 'row':
            button = row.locator('[data-git-version-action="apply"]')
            check('the saved version offers "Apply to running lab..." (folder source)', button.count() > 0)
            button.click()
        else:
            row.locator('[data-git-version-action="view"]').click()
            page.wait_for_selector('#git-version-restore', timeout=120000)
            check('the saved version\'s View dialog offers "Apply to running lab..." (commit-pinned Git version source)', True)
            page.click('#git-version-restore')
        page.wait_for_selector('#restore-review-dialog[open] fieldset.restore-targets', timeout=240000)
        review = page.locator('#restore-review-dialog').inner_text()
        run['review_text'] = review
        return review

    def review_checks(page, run, review, page_width):
        check('the review names the dialog, the lab and the source', 'Replace running configuration' in review and LAB in review and 'Source:' in review, review[:300])
        check('the review promises the backup, no reboot and the automatic undo', 'backed up first' in review and 'not rebooted' in review and 'minutes' in review)
        devices = page.evaluate('''() => [...document.querySelectorAll('#restore-review-dialog [name="restore-node"]')].map(i =>
            ({name: i.value, disabled: i.disabled, checked: i.checked, text: i.closest('label').innerText.replace(/\\s+/g, ' ')}))''')
        run['review_devices'] = devices
        by_name = {d['name']: d for d in devices}
        if wanted:
            check('every chosen device is listed and can be selected', all(w in by_name and not by_name[w]['disabled'] for w in wanted),
                  [d for d in devices if d['name'] in wanted])
        disabled = [d for d in devices if d['disabled']]
        if args.expect_disabled:
            check(f'at least {args.expect_disabled} device(s) that cannot be restored are listed, disabled, unticked, each with a reason',
                  len(disabled) >= args.expect_disabled and all('Skipped — ' in d['text'] and len(d['text'].split('Skipped — ')[1]) > 8 and not d['checked'] for d in disabled),
                  [d['text'] for d in disabled])
            check('with nothing eligible the Replace button is disabled', bool(any(not d['disabled'] for d in devices)) or page.is_disabled('#restore-run'))
        else:
            check('a device that cannot be restored is listed, disabled, with a reason',
                  None if not disabled else all('Skipped — ' in d['text'] for d in disabled), [d['text'] for d in disabled])
        with_dialog = page.evaluate('() => document.documentElement.scrollWidth')
        check('opening the review adds no horizontal page scroll', with_dialog <= page_width, (page_width, with_dialog))
        overflowing = page.evaluate('''() => [...document.querySelectorAll('#restore-review-dialog *')].filter(e => {
            const r = e.getBoundingClientRect(); return r.width > 0 && r.right > window.innerWidth + 1; }).length''')
        check('nothing inside the review overflows the viewport', overflowing == 0, overflowing)
        return devices

    def show_result(page, run, job_id, label):
        page.evaluate('(id) => restoreShowJob(id)', job_id)
        page.wait_for_selector('#restore-job-dialog[open] #restore-job-detail .restore-target-row', timeout=30000)
        collapsed = page.locator('#restore-job-dialog').inner_text()
        check('the result leads with the outcome and keeps the details collapsed', 'Backup taken before' not in collapsed and 'Configuration' in collapsed, collapsed[:200])
        page.click('#restore-job-dialog details.restore-job-details > summary')   # a student opens Details
        final = page.locator('#restore-job-dialog').inner_text()
        run['final_text'] = final
        shot(page, label + '-result')
        badges = page.evaluate('''() => [...document.querySelectorAll('#restore-job-detail .restore-target-row')].map(r =>
            ({device: r.querySelector('strong')?.innerText, badge: r.querySelector('.badge')?.innerText, cls: r.querySelector('.badge')?.className,
              help: [...r.querySelectorAll('.form-help')].map(p => p.innerText)}))''')
        run['final_badges'] = badges
        if not args.show_job:
            check(f'every chosen device ends as "{args.expect}"', len(badges) == len(wanted) and all(b['badge'] == args.expect for b in badges), badges)
            check('the result names both safety backups under Details', 'Backup taken before the change' in final and
                  ('Backup taken after the change' in final or args.expect != 'Replaced and verified'))
        check('no "undefined" or raw markup in the result', 'undefined' not in final and '<' not in final, final[:300])
        page.keyboard.press('Escape')

    def restore_once(page, run, page_width, label):
        before = readback(args.nodes)
        run['device_readback_before'] = before
        if args.drift:
            check(f'{label}: the devices themselves say B is active before the restore',
                  bool(before) and all(n.get('active') == 'B' for n in before.get('nodes', {}).values()),
                  {k: v.get('active') for k, v in (before or {}).get('nodes', {}).items()})
        review = open_review(page, run)
        shot(page, label + '-review')
        devices = review_checks(page, run, review, page_width)
        for device in devices:
            if not device['disabled'] and device['name'] not in wanted:
                page.uncheck(f'#restore-review-dialog [name="restore-node"][value="{device["name"]}"]')
        # The acknowledgement is mandatory: without it nothing is sent.
        page.click('#restore-run')
        page.wait_for_function('() => (document.querySelector("#restore-review-dialog .form-error")?.textContent || "").trim().length > 0', timeout=10000)
        refusal = page.locator('#restore-review-dialog .form-error').inner_text()
        check('without the acknowledgement the page refuses and says why', 'Tick the box' in refusal, refusal)
        check('the review is still open after the refusal', page.locator('#restore-review-dialog[open]').count() == 1)
        # Keyboard: focus the acknowledgement, Space ticks it, Enter on the button starts the change.
        page.focus('#restore-ack')
        page.keyboard.press('Space')
        check('Space ticks the acknowledgement', page.is_checked('#restore-ack'))
        page.focus('#restore-run')
        focused = page.evaluate('() => document.activeElement && document.activeElement.id')
        check('the Replace button takes keyboard focus', focused == 'restore-run', focused)
        with page.expect_response(lambda r: r.request.method == 'POST' and re.search(r'/api/labs/[0-9a-f]+/restore$', r.url), timeout=120000) as started:
            page.keyboard.press('Enter')
        submitted = started.value.json()
        job_id = submitted.get('id')          # the job THIS page started, never "the newest job"
        run['job_id'], run['submitted_source'] = job_id, submitted.get('source')
        check('the page started a job and the job names the expected source type',
              bool(job_id) and (submitted.get('source') or {}).get('type') == ('folder' if args.via == 'row' else 'git'), submitted.get('source'))
        page.wait_for_selector('#restore-job-dialog[open] #restore-job-detail .restore-target-row', timeout=120000)
        shot(page, label + '-progress')
        check('progress shows one row per chosen device', page.locator('#restore-job-detail .restore-target-row').count() == len(wanted))
        # Close, and reopen from the lab banner WHILE it runs. A job that is already over cannot show that.
        page.locator('#restore-job-dialog [data-op-close]').first.click()
        status_at_reopen = job_status(page, job_id)
        run['job_status_when_reopening'] = status_at_reopen
        if status_at_reopen in ACTIVE:
            try:
                page.wait_for_selector('#banner-restore:not([hidden])', timeout=15000)
                page.click('#banner-restore')
                page.wait_for_selector('#restore-job-dialog[open]', timeout=15000)
                check('the running change is reopened from the lab banner', True)
            except Exception as exc:
                still = job_status(page, job_id)
                check('the running change is reopened from the lab banner', None if still not in ACTIVE else False, type(exc).__name__)
        else:
            check('the running change is reopened from the lab banner', None, 'the job had already ended: ' + status_at_reopen)
        # Reload in the middle: the job belongs to the manager, not to the page.
        run['job_status_when_reloading'] = job_status(page, job_id)
        open_lab(page, reload=True)
        check('after a reload the page is back in the same lab', LAB in page.locator('body').inner_text()[:4000])
        deadline, job = time.time() + args.timeout, None
        while time.time() < deadline:
            job = page.evaluate('(id) => fetch("/api/restore/jobs/" + id).then(r => r.json())', job_id)
            if job['status'] not in ACTIVE:
                break
            time.sleep(2)
        run['job'] = job
        check('the job ended', bool(job) and job['status'] not in ACTIVE, job and job['status'])
        if args.drift and args.expect == 'Replaced and verified':
            check('the job says it really changed every chosen device (no_op false)', all(t.get('no_op') is False for t in job['targets']),
                  [(t['name'], t.get('no_op')) for t in job['targets']])
        show_result(page, run, job_id, label)
        after = readback(args.nodes, args.saved)
        run['device_readback_after'] = after
        nodes = (after or {}).get('nodes', {})
        if args.expect == 'Replaced and verified':
            check(f'{label}: the devices themselves say A is active and nothing is pending',
                  bool(nodes) and all(n.get('active') == 'A' and not n.get('pending_confirmation') for n in nodes.values()),
                  {k: (v.get('active'), v.get('pending_confirmation')) for k, v in nodes.items()})
            if args.saved:
                check(f'{label}: independent whole-configuration comparison with the saved state: 0 missing, 0 extra',
                      all(n.get('compared_with_saved', {}).get('missing') == 0 and n['compared_with_saved'].get('extra') == 0 for n in nodes.values()),
                      {k: v.get('compared_with_saved') for k, v in nodes.items()})
        earlier = (before or {}).get('nodes', {})
        check(f'{label}: the NOS boot identity of every chosen device is unchanged (no reboot)',
              bool(nodes) and all(_same_boot(earlier.get(k), v) for k, v in nodes.items()),
              {k: (earlier.get(k, {}).get('boot'), v.get('boot')) for k, v in nodes.items()})

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport=VIEWPORTS[args.viewport]).new_page()   # fresh context: no cached assets
        errors, broken = [], []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console', lambda m: errors.append(m.text) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        page.on('response', lambda r: broken.append(f'{r.status} {r.url}') if r.status >= 400 and '/static/' in r.url else None)
        if args.drift and not (args.review_only or args.show_job):
            drift(args.nodes + args.bystanders)
        open_lab(page)
        stamp = page.evaluate('() => [...document.scripts].map(s => s.src).find(s => s.includes("/static/restore.js")) || ""')
        check('the page loads restore.js of the running release', stamp.endswith('?v=' + version), stamp)
        if args.show_job:
            run = {'label': 'show-job', 'job_id': args.show_job}
            record['runs'].append(run)
            run['job'] = page.evaluate('(id) => fetch("/api/restore/jobs/" + id).then(r => r.json())', args.show_job)
            show_result(page, run, args.show_job, 'show-job')
        else:
            page.wait_for_selector('#git-saved-versions [data-git-version-action]', timeout=60000)
            page_width = page.evaluate('() => document.documentElement.scrollWidth')
            record['page_scroll_width_before_dialog'] = page_width
            if page_width > VIEWPORTS[args.viewport]['width'] + 1:
                # The manager's own layout (the lab list) is wider than a phone; its verification tool covers
                # 1366 px and up. That is the page's business, recorded here, not this feature's.
                record['note'] = f'the Progress tab itself is {page_width}px wide at this viewport, before any restore dialog'
            if args.review_only:
                run = {'label': 'review-only'}
                record['runs'].append(run)
                review_checks(page, run, open_review(page, run), page_width)
                shot(page, 'review-only')
                page.keyboard.press('Escape')
            else:
                run = {'label': 'first'}
                record['runs'].append(run)
                restore_once(page, run, page_width, 'first')
                if args.again:
                    # A backup taken from the page after the restore, then the same student restores again.
                    page.evaluate("() => startJob('backup')")
                    deadline, newest = time.time() + 300, None
                    while time.time() < deadline:
                        newest = page.evaluate('() => fetch("/api/state").then(r => r.json()).then(s => s.jobs[0])')
                        if newest and newest.get('operation') == 'backup' and newest['status'] not in ('queued', 'running'):
                            break
                        time.sleep(2)
                    record['backup_between'] = {k: newest.get(k) for k in ('id', 'status', 'source')} if newest else None
                    check('a backup taken from the page after the restore succeeds', bool(newest) and newest['status'] == 'succeeded', newest and newest.get('status'))
                    if args.drift:
                        drift(args.nodes)
                    page.click('#tab-progress')
                    run = {'label': 'again'}
                    record['runs'].append(run)
                    restore_once(page, run, page_width, 'again')
        if args.bystanders and not (args.review_only or args.show_job):
            others = readback(args.bystanders)
            record['bystanders_readback_after'] = others
            jobs = [run.get('job') or {} for run in record['runs']]
            check('the devices that were not selected still run B and nothing is pending on them',
                  bool(others) and all(n.get('active') == 'B' and not n.get('pending_confirmation') for n in others['nodes'].values()),
                  {k: (v.get('active'), v.get('pending_confirmation')) for k, v in (others or {}).get('nodes', {}).items()})
            check('the job lists only the selected devices', all(sorted(t['name'] for t in job.get('targets', [])) == sorted(wanted) for job in jobs),
                  [[t['name'] for t in job.get('targets', [])] for job in jobs])
        check('no page or console errors', not errors, errors[:5])
        check('no static asset failed to load', not broken, broken[:5])
        record['console_errors'] = errors[:20]
        browser.close()

    record.update(checks=results, failed=failed, not_exercised=[r['check'] for r in results if r['ok'] is None],
                  finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    if args.evidence:
        with open(args.evidence, 'w') as handle:
            json.dump(record, handle, indent=1)
            handle.write('\n')
    passed = sum(1 for r in results if r['ok'] is True)
    print(f'{passed} passed, {len(failed)} failed, {len(record["not_exercised"])} not exercised')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
