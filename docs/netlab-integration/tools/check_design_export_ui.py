#!/usr/bin/env python3
"""Drive *Export plan to Git…* of the Design tab in Chromium against a running manager and a lab that is bound to a
repository and has a succeeded plan: open the dialog, name the checkpoint, submit, follow the job to its mandatory
review, upload it through the review dialog's own button (the only sender of the reviewed retry), then prove through
the API that the repository holds the design version as its own checkpoint and that the restore never offers it.

    PATH="$PWD/clab-backup-ui/.venv/bin:$PATH" clab-backup-ui/.venv/bin/python \\
        docs/netlab-integration/tools/check_design_export_ui.py --url http://192.168.132.132:8081 --lab restore-square \\
        [--checkpoint design-<plan>] [--no-upload] [--shots DIR]

Exit 0 when every check passed; 2 when the lab has no plan or no repository binding; 1 on a failed check.
"""
import argparse
import json
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent


class Stop(Exception):
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
        node = self.page.locator(selector).first
        return (node.text_content() or '') if node.count() else ''


def call(base, path, method='GET', body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method, headers={'Content-Type': 'application/json', 'Origin': base})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b'null')
    except urllib.error.HTTPError as error:
        try: return error.code, json.loads(error.read() or b'{}')
        except json.JSONDecodeError: return error.code, {}


def wait_job(base, job_id, wanted, timeout=300):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        status, job = call(base, '/api/git/jobs/' + job_id)
        if status == 200:
            last = job
            if job.get('status') in wanted: return job
            if job.get('status') in ('failed', 'capture_incomplete', 'dismissed'): return job
        time.sleep(2)
    return last


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default='http://127.0.0.1:8081')
    parser.add_argument('--lab', default='restore-square')
    parser.add_argument('--checkpoint', default='')
    parser.add_argument('--no-upload', action='store_true', help='stop at the review; do not upload')
    parser.add_argument('--shots', default=str(HERE.parent / 'evidence' / 'shots'))
    args = parser.parse_args()
    base = args.url.rstrip('/')
    shots = Path(args.shots); shots.mkdir(parents=True, exist_ok=True)
    status, state = call(base, '/api/state')
    if status != 200: print('manager not reachable at ' + base); return 2
    lab = next((l for l in state.get('labs', []) if l.get('name') == args.lab), None)
    if not lab: print('lab not found: ' + args.lab); return 2
    generation = (lab.get('design') or {}).get('generation') or {}
    if generation.get('status') != 'succeeded': print('no succeeded plan on this lab'); return 2
    if not lab.get('git_binding'): print('the lab is not bound to a repository'); return 2
    checkpoint = args.checkpoint or ('design-' + generation['id'][:12] + '-' + secrets.token_hex(2))
    print('manager %s (%s), lab %s, plan %s, checkpoint %s' % (base, state.get('version'), lab['id'], generation['id'][:12], checkpoint))
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1280, 'height': 900})
        r = Run(page, shots)
        code = 0
        try:
            page.goto(base + '/#lab=' + lab['id'] + '&view=design')
            page.wait_for_selector('#design-view:not([hidden])', timeout=20000)
            page.wait_for_function('() => !document.getElementById("design-export-git").disabled', timeout=20000)
            r.check('Export plan to Git is offered for the succeeded plan of a bound lab', page.locator('#design-export-git').is_enabled())
            page.click('#design-export-git')
            page.wait_for_selector('#design-export-git-dialog[open]', timeout=5000)
            destination = r.text('#design-export-git-destination')
            r.check('the dialog names the repository and the checkpoint folder', 'checkpoints/' in destination, destination[:200])
            r.check('the dialog says what the export is and is not', 'never a backup' in r.text('#design-export-git-dialog').lower() or 'not a backup' in r.text('#design-export-git-dialog').lower(), r.text('#design-export-git-dialog')[:300])
            page.fill('#design-export-git-checkpoint', checkpoint)
            page.fill('#design-export-git-note', 'Design export check ' + time.strftime('%H:%M'))
            r.shot('design-export-01-dialog')
            with page.expect_response(lambda resp: resp.url.endswith('/git') and resp.request.method == 'POST', timeout=30000) as info:
                page.click('#design-export-git-confirm')
            response = info.value
            r.check('the export request is accepted', response.status == 200, response.status)
            if response.status != 200: raise Stop(1, 'refused: ' + str(response.json()))
            job = response.json()
            r.check('the job is a design export with the checkpoint destination', job.get('kind') == 'design' and job.get('checkpoint') == checkpoint and 'checkpoints/' + checkpoint in (job.get('destination') or {}).get('path', ''), json.dumps({k: job.get(k) for k in ('kind', 'checkpoint', 'destination', 'status')})[:300])
            job = wait_job(base, job['id'], ('review_pending', 'committed', 'unchanged'))
            r.check('the export saved on the VM and stopped for the review', job and job.get('status') == 'review_pending', job and (job.get('status'), job.get('message')))
            page.wait_for_selector('#git-review-push', timeout=60000)
            r.check('the review dialog opened by itself and names the design export', 'design export' in r.text('dialog[open]').lower(), r.text('dialog[open]')[:200])
            r.check('the review lists the plan files under the checkpoint folder', any(n in r.text('dialog[open]') for n in ('network-intent.yml', 'plan.json')), r.text('dialog[open]')[:300])
            r.shot('design-export-02-review')
            if args.no_upload:
                page.keyboard.press('Escape')
                r.note('stopped at the review as asked; the export stays saved on the VM and pending')
            else:
                page.click('#git-review-push')
                job = wait_job(base, job['id'], ('synced', 'committed', 'push_pending'))
                r.check('the reviewed upload finished', job and job.get('status') == 'synced' and job.get('pushed') is True, job and (job.get('status'), job.get('message')))
                page.wait_for_timeout(1500)
                r.shot('design-export-03-uploaded')
                status, history = call(base, '/api/labs/%s/git/history' % lab['id'])
                version = next((v for v in (history or {}).get('versions', []) if v.get('path', '').endswith('checkpoints/' + checkpoint)), None)
                r.check('the repository history lists the design checkpoint', bool(version), json.dumps(version)[:300] if version else str(history)[:300])
                if version:
                    status, detail = call(base, '/api/labs/%s/git/version' % lab['id'], 'POST', {'commit': version.get('commit', ''), 'path': version.get('path', '')})
                    manifest = ((detail or {}).get('snapshot') or {}).get('manifest') or (detail or {}).get('manifest') or {}
                    r.check('the saved manifest is a network-design manifest without device rows', manifest.get('kind') == 'network-design' and not manifest.get('node_names') and all(not row.get('node') for row in manifest.get('files', [])), json.dumps({k: manifest.get(k) for k in ('kind', 'node_names', 'restore_capable_nodes')}))
                    r.check('the restore has no candidate in it', manifest.get('restore_capable_nodes', 0) == 0 and (detail or {}).get('restore_capable_nodes', 0) == 0, str({k: (detail or {}).get(k) for k in ('restore_capable_nodes',)}))
        except Stop as stop:
            print('STOP (%d): %s' % (stop.code, stop), flush=True); code = stop.code
        finally:
            browser.close()
    failed = [c for c in r.checks if not c['ok']]
    print('%d of %d checks passed; %d console errors; %d page errors.' % (len(r.checks) - len(failed), len(r.checks), len(r.console), len(r.pageerrors)))
    if r.shots: print('screenshots: ' + ', '.join(p.name for p in r.shots))
    return code or (1 if failed or r.pageerrors else 0)


if __name__ == '__main__':
    sys.exit(main())
