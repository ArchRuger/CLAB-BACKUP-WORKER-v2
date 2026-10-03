#!/usr/bin/env python3
"""Drive the *Apply to devices* dialog of the Network design tab on a real running manager.

Companion to `check_design_live.py` (plan generation) and `check_design_ui.py` (the tab against the
fixture manager): this one is `design_apply.py` / `docs/netlab-integration/PROVISIONING.md` §4-5, the
review → apply → ownership flow. It never spawns its own manager: point it at one that is already up
(a VM or the fixture manager) with `--url`, and at a lab that already has a succeeded plan.

Without `--apply` (the default) nothing on any device changes: the dialog is opened, the chosen devices
are reviewed (a real, read-only connection to each), and the dialog is closed again. With `--apply` the
selected devices are actually changed, through the manager's own mandatory pre-change backup and timed
recovery — do not point `--apply` at a lab whose devices matter unless that is exactly what you mean.

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-integration/tools/check_design_apply_ui.py --url http://127.0.0.1:8080 --lab restore-square \\
        [--targets ceos] [--apply] [--minutes 3] [--viewport 1280x900] [--shots DIR]

Exit status: 2 when the newest plan is not `succeeded` or the *Apply to devices…* button is disabled for
another reason; 3 when the review reports a chosen device as not ready to apply (including a review
request that fails outright); 1 when a structural assertion fails or an unexpected console/page error is
seen; 0 otherwise.
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
HANDLED = 'Failed to load resource: the server responded with a status of '
TERMINAL_JOB = ('succeeded', 'partial', 'failed', 'needs_attention', 'interrupted')
SETTLED_OK = ('verified', 'verify_mismatch', 'applied')
COUNTS_RE = re.compile(r'Added (\d+) . Removed (\d+) . Stale (\d+) . Conflicts (\d+) . Expected (\d+)')
PROTECTED_RE = re.compile(r'Protected settings left out \((\d+)\)')


class Stop(Exception):
    """Raised to leave the run early with the exit code and reason the spec calls for (2 or 3)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Run:
    def __init__(self, page, shots):
        self.page, self.shots_dir = page, shots
        self.console, self.pageerrors, self.checks, self.shots = [], [], [], []
        page.on('console', lambda m: self.console.append({'type': m.type, 'text': m.text}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.pageerrors.append(str(e)))

    def check(self, name, ok, detail=''):
        self.checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:300]})
        print(('  ok   ' if ok else '  FAIL ') + name + ('' if ok else ': ' + str(detail)[:200]), flush=True)

    def note(self, message):
        print('  note ' + message, flush=True)

    def shot(self, name):
        path = self.shots_dir / (name + '.png')
        self.page.screenshot(path=str(path), full_page=True)
        self.shots.append(path)

    def text(self, selector):
        # A selector that currently matches nothing must not make Playwright wait for it to appear
        # (the hidden-node pitfall of `check_design_ui.py`'s own `text()`): guard with count() first.
        node = self.page.locator(selector).first
        return (node.text_content() or '') if node.count() else ''


def call(base, path, method='GET', body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method, headers={'Content-Type': 'application/json', 'Origin': base})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b'null')
    except urllib.error.HTTPError as error:
        try: return error.code, json.loads(error.read() or b'{}')
        except json.JSONDecodeError: return error.code, {}


def choose_rows(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('#design-apply-choose-body label')).map(label => {
        const input = label.querySelector('input[name="design-apply-target"]');
        const small = label.querySelector('small');
        return {name: input ? input.value : '', disabled: !!(input && input.disabled), reason: small ? small.textContent : ''};
    })""")


def review_articles(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('#design-apply-review-body article.design-apply-device')).map(a => {
        const h4 = a.querySelector('h4');
        const name = h4 && h4.childNodes.length ? (h4.childNodes[0].textContent || '').trim() : '';
        return {name, text: a.textContent || '', diffPres: a.querySelectorAll('pre.design-apply-diff').length};
    })""")


def progress_rows(page):
    return page.evaluate("""() => Array.from(document.querySelectorAll('#design-apply-progress-body table tbody tr')).map(tr =>
        Array.from(tr.children).map(td => (td.textContent || '').trim()))""")


def set_targets(page, wanted):
    """Tick exactly `wanted` among the enabled checkboxes; leave the disabled ones (host, blocked) alone."""
    boxes = page.locator('#design-apply-choose-body input[name="design-apply-target"]')
    for i in range(boxes.count()):
        box = boxes.nth(i)
        if box.is_disabled(): continue
        value = box.get_attribute('value') or ''
        if value in wanted: box.check()
        else: box.uncheck()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://127.0.0.1:8081', help='the running manager to drive')
    parser.add_argument('--lab', default='restore-square')
    parser.add_argument('--targets', default='ceos', help='comma-separated device names to review (and, with --apply, apply to)')
    parser.add_argument('--apply', action='store_true', help='actually submit the apply job (changes devices); default is review-only')
    parser.add_argument('--minutes', type=int, default=3, help='recovery window in minutes, used only with --apply')
    parser.add_argument('--viewport', default='1280x900', help='WIDTHxHEIGHT, e.g. 390x844 for a phone')
    parser.add_argument('--shots', default=str(HERE.parent / 'evidence' / 'shots'))
    args = parser.parse_args()
    width, height = (int(v) for v in args.viewport.lower().split('x', 1))
    targets = [t.strip() for t in args.targets.split(',') if t.strip()]
    shots = Path(args.shots); shots.mkdir(parents=True, exist_ok=True)

    status, state = call(args.url, '/api/state')
    if status != 200: raise SystemExit('the manager at %s did not answer /api/state (status %s)' % (args.url, status))
    lab = next((l for l in state['labs'] if l['name'] == args.lab), None)
    if lab is None: raise SystemExit('no lab named %r on %s' % (args.lab, args.url))
    lab_id = lab['id']
    print('manager %s (%s), lab %s = %s' % (args.url, state.get('version'), args.lab, lab_id), flush=True)

    exit_code = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        chromium_version = browser.version
        page = browser.new_page(viewport={'width': width, 'height': height})
        r = Run(page, shots)
        try:
            page.goto(args.url + '/#lab=' + lab_id + '&view=design')
            page.wait_for_selector('#design-view:not([hidden])', timeout=15000)
            page.wait_for_function('() => !(document.getElementById("design-state")?.textContent || "").includes("Loading")', timeout=15000)

            # --- 1. the newest plan must be succeeded and the Apply button enabled --------------------
            plan_status = r.text('#design-plan-status')
            r.check('a plan has been generated for this lab', plan_status.startswith('Plan generated'), plan_status)
            if not plan_status.startswith('Plan generated'):
                raise Stop(2, 'the newest plan is not succeeded: ' + (plan_status or '(no #design-plan-status text)'))
            apply_button = page.locator('#design-apply')
            disabled = apply_button.get_attribute('disabled') is not None
            reason = apply_button.get_attribute('title') or ''
            r.check('#design-apply is enabled', not disabled, reason)
            if disabled: raise Stop(2, 'Apply to devices… is disabled: ' + reason)
            r.shot('design-apply-01-plan')

            # --- 2. open the dialog; the choose step lists the lab's devices, a support host disabled -
            apply_button.click()
            page.wait_for_selector('#design-apply-dialog[open]', timeout=10000)
            r.check('the choose step is shown', page.locator('#design-apply-choose-step:not([hidden])').count() == 1)
            rows = {row['name']: row for row in choose_rows(page) if row['name']}
            r.check('the choose step lists the lab\'s devices', len(rows) > 0, sorted(rows))
            if 'host1' in rows:
                host = rows['host1']
                r.check('host1 (a support host) is listed disabled with a reason', host['disabled'] and bool(host['reason']), host['reason'])
            else:
                r.note('host1 is not a device of this plan; skipping the support-host assertion (expected for restore-square, not every lab)')
            r.shot('design-apply-02-choose')

            # --- 5 (checked here, while the dialog is easiest to open and close): the dialog must not --
            # --- add horizontal overflow beyond the shell's own width at this viewport ----------------
            with_dialog = page.evaluate('() => document.documentElement.scrollWidth')
            page.keyboard.press('Escape')
            page.wait_for_function('() => !document.getElementById("design-apply-dialog")?.open', timeout=5000)
            without_dialog = page.evaluate('() => document.documentElement.scrollWidth')
            page.click('#tab-topology'); page.wait_for_timeout(300)
            shell_width = page.evaluate('() => document.documentElement.scrollWidth')
            page.click('#tab-advanced'); page.wait_for_selector('#design-view', state='visible', timeout=5000); page.wait_for_timeout(300)
            r.check('the Apply dialog adds no horizontal overflow beyond the shell at %dx%d' % (width, height),
                    with_dialog <= shell_width, 'with_dialog=%s without_dialog=%s shell=%s' % (with_dialog, without_dialog, shell_width))
            apply_button.click()
            page.wait_for_selector('#design-apply-dialog[open]', timeout=10000)
            page.wait_for_selector('#design-apply-choose-step:not([hidden])', timeout=10000)

            # --- 3. tick the requested targets, review, and read the per-device blocks -----------------
            selectable = [t for t in targets if t in rows and not rows[t]['disabled']]
            missing = [t for t in targets if t not in rows]
            blocked = [t for t in targets if t in rows and rows[t]['disabled']]
            if missing: r.check('every requested target is a device of this plan', False, 'missing: ' + ', '.join(missing))
            if blocked: r.check('every requested target is selectable', False, 'disabled: ' + ', '.join(blocked) + ' (' + '; '.join(rows[t]['reason'] for t in blocked) + ')')
            if not selectable: raise Stop(3, 'none of the requested target device(s) %s can be selected for review' % (targets,))
            set_targets(page, set(selectable))

            with page.expect_response(lambda resp: resp.url.endswith('/review') and resp.request.method == 'POST', timeout=185000) as review_info:
                page.click('#design-apply-review-run')
            review_response = review_info.value
            if review_response.status != 200:
                try: detail = review_response.json().get('detail', '')
                except Exception: detail = review_response.text()
                raise Stop(3, 'the review request failed (%s): %s' % (review_response.status, detail))
            review = review_response.json()
            page.wait_for_selector('#design-apply-review-step:not([hidden])', timeout=15000)

            for row in review.get('targets', []):
                name = row.get('name', '')
                if not row.get('eligible') or not row.get('ready'):
                    raise Stop(3, '%s is not ready to apply: %s' % (name, row.get('reason') or '(no reason given)'))

            articles = {a['name']: a for a in review_articles(page) if a['name']}
            for row in review.get('targets', []):
                name, counts = row['name'], row.get('counts') or {}
                article = articles.get(name) or {}
                text = article.get('text', '')
                r.check('%s is listed in the rendered review' % name, bool(text), sorted(articles))
                if row.get('no_op'):
                    print('  counts %s: already matches the plan (no_op)' % name, flush=True)
                    r.check('%s shows "already matches the plan"' % name, 'Already matches the plan.' in text, text[:200])
                    continue
                print('  counts %s: added=%s removed=%s stale=%s conflicts=%s expected=%s protected=%s diff_lines=%s' % (
                    name, counts.get('added', 0), counts.get('removals', 0), counts.get('stale', 0), counts.get('conflicts', 0),
                    counts.get('expected', 0), len(row.get('protected') or []), len(row.get('diff') or [])), flush=True)
                m = COUNTS_RE.search(text)
                r.check('%s shows Added/Removed/Stale/Conflicts/Expected matching the review' % name,
                        bool(m) and [int(g) for g in m.groups()] == [counts.get('added', 0), counts.get('removals', 0), counts.get('stale', 0),
                                                                      counts.get('conflicts', 0), counts.get('expected', 0)], text[:250])
                if row.get('protected'):
                    pm = PROTECTED_RE.search(text)
                    r.check('%s lists its protected settings (%d)' % (name, len(row['protected'])), bool(pm) and int(pm.group(1)) == len(row['protected']), text[:250])
                if row.get('diff'):
                    r.check('%s shows a diff' % name, article.get('diffPres', 0) >= 1, 'diff lines=%d diffPres=%s' % (len(row['diff']), article.get('diffPres')))
                else:
                    r.check('%s shows "No differences."' % name, 'No differences.' in text, text[:200])
            r.shot('design-apply-03-review')

            ack, run_button = page.locator('#design-apply-ack'), page.locator('#design-apply-run')
            r.check('Apply is disabled before the acknowledgement is ticked', run_button.get_attribute('disabled') is not None)
            applicable = review.get('applicable') or []
            # This tool never ticks a take-over checkbox (deciding to replace someone's manual configuration
            # is a human call), so any ready target that still has a conflict is, by definition, unresolved.
            unresolved = [t['name'] for t in review.get('targets', []) if t.get('ready') and (t.get('counts') or {}).get('conflicts')]

            if not args.apply:
                # --- 4 (without --apply): Apply stays gated on the acknowledgement, then Close --------
                ack.check()
                should_enable = bool(applicable) and not unresolved
                still_disabled = run_button.get_attribute('disabled') is not None
                r.check('Apply enables once acknowledged (unless a conflict is still unresolved)', still_disabled != should_enable,
                        'expected_enabled=%s unresolved=%s' % (should_enable, unresolved))
                page.locator('[data-design-apply-close][aria-label="Close"]').click()
                page.wait_for_function('() => !document.getElementById("design-apply-dialog")?.open', timeout=5000)
                r.check('the dialog closes without applying anything', page.locator('#design-apply-dialog[open]').count() == 0)
                last = r.text('#design-apply-last')
                r.check('the plan card\'s last-apply line still renders', page.locator('#design-apply-last').count() == 1)
                if last.strip(): r.note('last-apply line: ' + last.strip()[:200])
            else:
                # --- 4 (with --apply): actually submit, follow progress, then check the ownership -----
                if unresolved: raise Stop(3, 'conflict(s) on %s are not resolved; refusing to take over settings automatically' % (unresolved,))
                if not applicable: raise Stop(3, 'nothing in this review is applicable (every target ineligible, unreachable or a no-op)')
                page.fill('#design-apply-minutes', str(args.minutes))
                ack.check()
                r.check('Apply is enabled once acknowledged', run_button.get_attribute('disabled') is None)
                with page.expect_response(lambda resp: resp.url.endswith('/design/apply') and resp.request.method == 'POST', timeout=30000) as apply_info:
                    run_button.click()
                apply_response = apply_info.value
                r.check('the apply request is accepted', apply_response.status == 200, apply_response.status)
                job = apply_response.json()
                job_id = job['id']
                page.wait_for_selector('#design-apply-progress-step:not([hidden])', timeout=10000)
                page.wait_for_function(
                    '() => { const t=(document.getElementById("design-apply-progress-body")?.textContent||"").trim(); return t && !t.startsWith("Applying"); }',
                    timeout=600000)
                status, job = call(args.url, '/api/design/apply/jobs/' + job_id)
                r.check('the apply job finished', status == 200 and job.get('status') in TERMINAL_JOB, job.get('status') if status == 200 else status)
                print('  job %s: %s — %s' % (job_id, job.get('status'), job.get('message')), flush=True)
                for t in job.get('targets', []):
                    print('  device %s: %s — %s' % (t.get('name'), t.get('status'), t.get('message')), flush=True)
                rendered = progress_rows(page)
                r.check('the progress table lists every target device', len(rendered) == len(job.get('targets', [])), rendered)
                r.shot('design-apply-04-progress')
                # The dialog is modal: close it before anything outside it is clicked.
                page.locator('[data-design-apply-close][aria-label="Close"]').click()
                page.wait_for_function('() => !document.getElementById("design-apply-dialog").open', timeout=10000)
                r.check('the dialog closes after the apply', page.locator('#design-apply-dialog[open]').count() == 0)

                details = page.locator('#design-advanced-details')
                if not details.evaluate('el => el.open'): details.locator('summary').first.click()
                page.wait_for_function('() => (document.getElementById("design-ownership")?.textContent || "").trim().length > 0', timeout=15000)
                ownership_text = r.text('#design-ownership')
                r.check('the ownership ledger loaded without an error', 'Could not load owned settings.' not in ownership_text, ownership_text[:200])
                succeeded_now = [t['name'] for t in job.get('targets', []) if t.get('status') in SETTLED_OK]
                for name in selectable:
                    present = bool(re.search(re.escape(name) + r'\s*—\s*\d+\s*setting', ownership_text))
                    if name in succeeded_now or present:
                        r.check('%s appears in the ownership ledger with a statement count' % name, present, ownership_text[:300])
                    else:
                        r.note('%s did not apply cleanly and has no prior ledger entry; ownership check skipped' % name)
                r.shot('design-apply-05-ownership')

        except Stop as stop:
            print('STOP (%d): %s' % (stop.code, stop), flush=True)
            exit_code = stop.code
        finally:
            browser.close()

        handled = [e for e in r.console if e['text'].startswith(HANDLED)]
        real = [e for e in r.console if e not in handled]
        failed = [c for c in r.checks if not c['ok']]
        print('', flush=True)
        print('%d of %d checks passed; %d console errors (%d handled HTTP responses); %d page errors. Chromium %s.' % (
            len(r.checks) - len(failed), len(r.checks), len(real), len(handled), len(r.pageerrors), chromium_version), flush=True)
        if failed: print('failed: ' + '; '.join(c['name'] for c in failed), flush=True)
        if real: print('console errors: ' + '; '.join(e['text'][:200] for e in real), flush=True)
        if r.pageerrors: print('page errors: ' + '; '.join(e[:200] for e in r.pageerrors), flush=True)
        print('screenshots: ' + ', '.join(p.name for p in r.shots), flush=True)
        if exit_code: return exit_code
        return 1 if failed or real or r.pageerrors else 0


if __name__ == '__main__':
    sys.exit(main())
