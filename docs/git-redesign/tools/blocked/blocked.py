"""The "try to get blocked" pass (PROMPT section 9 item 4): shared pieces. Fixture evidence only.

Each attack script starts its own fixture manager on a fresh data directory (ports 8191 to 8199), drives the real page in
Chromium through the integration helpers (docs/git-redesign/tools/integration/common.py, folder_flow.py) and writes what it
saw as JSON lines: one `tried` line per attack (what was done, what the page said, whether anything refused, was greyed
out without a reason, dead-ended, said something untrue, showed a raw helper or Python sentence, did nothing, or logged an
error), and a screenshot for every suspect under docs/git-redesign/evidence/blocked/.

    ~/pw-venv/bin/python docs/git-redesign/tools/blocked/<attack>.py --port 8191
"""
import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / 'docs/git-redesign/evidence/blocked'
SHOTS = Path(os.environ.get('BLOCKED_SHOTS', '/tmp/blocked-shots'))
os.environ.setdefault('I1_SHOTS', str(SHOTS))
sys.path.insert(0, str(HERE.parent / 'integration'))

from common import Session, expect, wait_until  # noqa: E402,F401

PYTHON = '/home/archtop/projects/clab-manager/clab-backup-ui/.venv/bin/python'
RAW = re.compile(r'Traceback|Exception|KeyError|TypeError|undefined|\bNone\b|null|NaN|\[object |registration|prefix|overlap|'
                 r'binding|ValueError|HTTPException|Internal Server Error|/api/', re.I)


def arguments(doc):
    parser = argparse.ArgumentParser(description=doc)
    parser.add_argument('--port', type=int, default=8191)
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--out', default='')
    parser.add_argument('--width', type=int, default=1440)
    parser.add_argument('--height', type=int, default=900)
    return parser.parse_args()


@contextmanager
def fixture(port, classic=False):
    """A fixture manager of our own on `port` with a fresh data directory; stopped by its PID only."""
    data = tempfile.mkdtemp(prefix='blocked-%d-' % port)
    log = open(os.path.join(data, 'fixture.log'), 'w')
    args = [PYTHON, str(ROOT / 'docs/redesign/tools/fixture_manager.py'), '--port', str(port), '--data', data] + (['--classic'] if classic else [])
    proc = subprocess.Popen(args, cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ, FIXTURE_DATA=data))
    base = 'http://127.0.0.1:%d' % port
    try:
        end = time.time() + 120
        while time.time() < end:
            if proc.poll() is not None: raise RuntimeError('fixture exited; see ' + log.name)
            try:
                with urllib.request.urlopen(base + '/fixture/state', timeout=2) as answer:
                    if answer.status == 200: break
            except Exception: time.sleep(0.5)
        else: raise RuntimeError('fixture did not start on ' + base)
        yield base, data
    finally:
        proc.send_signal(signal.SIGINT)
        try: proc.wait(timeout=15)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
        log.close()


class Pass:
    """The record of one attack script: `tried` lines, suspects with a screenshot."""

    def __init__(self, s, name, out=''):
        self.s = s; self.name = name; self.rows = []
        self.out = Path(out) if out else SHOTS / (name + '.jsonl')
        SHOTS.mkdir(parents=True, exist_ok=True); EVIDENCE.mkdir(parents=True, exist_ok=True)
        self.out.write_text('')

    def page_text(self, selector='#save-drawer'):
        loc = self.s.page.locator(selector)
        return loc.first.inner_text() if loc.count() and loc.first.is_visible() else ''

    def tried(self, attack, said='', ok=True, kind='', note='', shot=False, request=''):
        """One attack. `kind` names the finding class when `ok` is false: refusal, greyed, dead-end, untrue, raw, nothing, error."""
        errors = list(self.s.errors); self.s.errors.clear()
        if errors and ok: ok, kind, note = False, 'error', '; '.join(errors[:4])
        row = dict(script=self.name, attack=attack, said=said, ok=bool(ok), kind=kind, note=note, request=request, errors=errors[:6])
        if not ok or shot:
            safe = re.sub(r'[^A-Za-z0-9_-]+', '-', self.name + '-' + attack)[:90].strip('-')
            path = (EVIDENCE if not ok else SHOTS) / (safe + '.png')
            try: self.s.page.screenshot(path=str(path), full_page=False); row['shot'] = str(path.relative_to(ROOT) if not ok else path)
            except Exception as exc: row['shot'] = 'failed: %s' % exc
        self.rows.append(row)
        with self.out.open('a') as stream: stream.write(json.dumps(row) + '\n')
        print(('ok   ' if ok else 'FIND ') + attack + (' :: ' + kind + ' :: ' + note if not ok else '') + ((' :: ' + said[:160]) if said else ''), flush=True)
        return ok

    def raw_check(self, text):
        """A raw helper or Python sentence, or the plumbing words, in what the person reads."""
        hit = RAW.search(text or '')
        return hit.group(0) if hit else ''

    def summary(self):
        bad = [r for r in self.rows if not r['ok']]
        print('\n%s: %d attacks, %d suspects' % (self.name, len(self.rows), len(bad)))
        return 0


def settle_question3(s, P=None, label=''):
    """After Save here: when the chooser asks question 3 (a save of this lab waits), answer Move and keep (it is a question, not a
    refusal; the attack is about the folder). Returns the question's sentence or ''."""
    p = s.page
    p.wait_for_timeout(1500)
    keep = p.locator('#folder-foot [data-folder-pending="keep"]')
    if keep.count() and keep.is_visible():
        said = p.locator('#folder-answer').inner_text()
        if P: P.tried(label + ': question 3 first (a save of this lab waits)', said)
        keep.click()
        return said
    return ''
