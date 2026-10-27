"""Shared Playwright/API helpers for the student quick-start scenario captures (current UI, release 1.31.6).

Thin layer over the real page flows so each scenario script stays short and every screenshot and evidence
record is produced the same way. Nothing here talks to the Store directly; every call either drives the real
page or issues the same same-origin request the page itself issues (read only).

Run with the Playwright interpreter:  /home/archtop/pw-venv/bin/python docs/student-quick-start/tools/capture_scenario_a.py
Waits are explicit UI conditions (a selector, a visible text), never network-idle: the page polls.
"""
import json
import pathlib
import re
import time

BASE = 'http://127.0.0.1:8081'
VIEWPORT = {'width': 1366, 'height': 900}
DEVICE_SCALE_FACTOR = 2

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent  # docs/student-quick-start


def new_context(playwright, headless=True):
    """One Chromium browser + context configured per the guide's screenshot rules."""
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(
        viewport=VIEWPORT,
        device_scale_factor=DEVICE_SCALE_FACTOR,
        color_scheme='light',
        has_touch=False,
    )
    page = context.new_page()
    return browser, context, page


def settle(page, extra_ms=600):
    """A short fixed pause so a just-opened dialog has finished animating and a poll-driven re-render has
    landed. Always call it after waiting for the real condition; it is not a substitute for one."""
    page.wait_for_timeout(extra_ms)


def api(page, method, path, body=None):
    """Same-origin fetch from inside the page context (what the page itself would send)."""
    script = """(args) => fetch(args.path, {
        method: args.method,
        headers: args.body !== null ? {'Content-Type': 'application/json'} : undefined,
        body: args.body !== null ? JSON.stringify(args.body) : undefined
    }).then(async r => ({status: r.status, body: await r.json().catch(() => null)}))"""
    return page.evaluate(script, {'path': path, 'method': method, 'body': body})


def manager_busy():
    """Names what other work holds the manager's shared guard (`operation_busy`), or [] when it is idle.
    Other campaign workers share this manager: a restore, a save or a lab operation of theirs makes every
    deploy, save and load of ours wait ("Wait for the current lab operation to finish.")."""
    import urllib.request
    with urllib.request.urlopen(BASE + '/api/state', timeout=20) as resp:
        d = json.load(resp)
    busy = []
    for o in d.get('operations', []):
        if o.get('status') in ('queued', 'running', 'stopping'):
            busy.append(f"operation {o.get('action')} {o.get('name')}")
    for j in d.get('restore_jobs', []):
        if j.get('status') in ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying', 'rechecking'):
            busy.append(f"load {j.get('id', '')[:6]}")
    for j in d.get('git_jobs', []):
        if j.get('status') in ('queued', 'capturing', 'exporting', 'pushing', 'updating', 'moving'):
            busy.append(f"save {j.get('id', '')[:6]} ({j.get('status')})")
    for j in d.get('design_jobs', []):
        if j.get('status') in ('queued', 'applying', 'running'):
            busy.append('design apply')
    return busy


def wait_idle(timeout=900, quiet=6):
    """Wait until the manager has been idle for `quiet` seconds (see manager_busy). Returns the seconds waited."""
    t0 = time.time()
    idle_since = None
    while time.time() - t0 < timeout:
        if manager_busy():
            idle_since = None
        elif idle_since is None:
            idle_since = time.time()
        elif time.time() - idle_since >= quiet:
            return round(time.time() - t0 - quiet, 1)
        time.sleep(2)
    raise TimeoutError('the manager stayed busy: ' + ', '.join(manager_busy()))


def wait_text(page, selector, pattern, timeout=60, interval=1.0):
    """Poll an element's text until it matches the regex; returns the text or raises TimeoutError.
    (page.wait_for_function cannot be used: the page's CSP forbids unsafe-eval.)"""
    deadline = time.time() + timeout
    last = ''
    while time.time() < deadline:
        loc = page.locator(selector)
        if loc.count():
            try:
                last = loc.first.inner_text(timeout=2000)
            except Exception:
                last = ''
            if re.search(pattern, last):
                return last
        page.wait_for_timeout(int(interval * 1000))
    raise TimeoutError(f'{selector!r} never matched {pattern!r}; last text {last!r}')


class StepRecorder:
    """Accumulates one JSON-serialisable record per numbered step and writes the JSON + Markdown
    evidence files the guide requires."""

    def __init__(self, screenshots_dir, evidence_json, evidence_md, scenario_title, prefix='a'):
        self.screenshots_dir = pathlib.Path(screenshots_dir)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.evidence_json = pathlib.Path(evidence_json)
        self.evidence_md = pathlib.Path(evidence_md)
        self.scenario_title = scenario_title
        self.prefix = prefix  # screenshot filename prefix: "a" for Scenario A, "b" for Scenario B, etc.
        self.steps = []
        self.started_utc = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    def new_step(self, step, title):
        record = {
            'step': step,
            'title': title,
            'actions': [],
            'observed': {},
            'screenshots': [],
            'device_evidence': {},
            'remote_evidence': {},
            'result': 'PASS',
            'notes': [],
        }
        self.steps.append(record)
        return record

    def shoot_full(self, page, record, name):
        """Full-page screenshot named <prefix><step>-<name>-full.png."""
        filename = f"{self.prefix}{record['step']}-{name}-full.png"
        path = self.screenshots_dir / filename
        page.screenshot(path=str(path), full_page=True)
        record['screenshots'].append({'file': filename, 'element': 'full-page', 'callouts': []})
        return path

    def shoot_element(self, locator, record, name, label=None, callouts=None):
        """Element screenshot named <prefix><step>-<name>.png, with recorded bounding boxes for callouts."""
        filename = f"{self.prefix}{record['step']}-{name}.png"
        path = self.screenshots_dir / filename
        locator.screenshot(path=str(path))
        box = None
        try:
            box = locator.bounding_box()
        except Exception:
            box = None
        entry_callouts = list(callouts or [])
        if box is not None:
            entry_callouts.append({'label': label or name, 'box': box})
        record['screenshots'].append({'file': filename, 'element': label or name, 'callouts': entry_callouts})
        return path

    def shoot_clip(self, page, record, name, clip, label=None, callouts=None):
        """Screenshot of a fixed viewport region named <prefix><step>-<name>.png: for third-party
        embedded UI (the lab builder's React panels) where no stable selector survives a rebuild,
        but a fixed-width side panel's screen position is known."""
        filename = f"{self.prefix}{record['step']}-{name}.png"
        path = self.screenshots_dir / filename
        page.screenshot(path=str(path), clip=clip)
        entry_callouts = list(callouts or [])
        if label:
            entry_callouts.append({'label': label, 'box': clip})
        record['screenshots'].append({'file': filename, 'element': label or name, 'callouts': entry_callouts})
        return path

    def bbox_of(self, locator, label):
        """Bounding box dict for a named control, for a callout list, without a screenshot."""
        try:
            box = locator.bounding_box()
        except Exception:
            box = None
        return {'label': label, 'box': box}

    def fail(self, record, message, page=None, name='failure'):
        record['result'] = 'FAIL'
        record['notes'].append(message)
        if page is not None:
            try:
                self.shoot_full(page, record, name)
            except Exception as exc:
                record['notes'].append(f'could not capture failure screenshot: {exc}')
        self.write()
        raise RuntimeError(f"Step {record['step']} ({record['title']}) FAILED: {message}")

    @staticmethod
    def scrub(value):
        """Evidence keeps controlled text only: a device's password hash (shown by the save review's diff) is cut."""
        if isinstance(value, str):
            return re.sub(r'(secret|password) (sha512|5|7|0) \S+', r'\1 \2 <hash>', re.sub(r'\$6\$\S+', '<hash>', value))
        if isinstance(value, list):
            return [StepRecorder.scrub(v) for v in value]
        if isinstance(value, dict):
            return {k: StepRecorder.scrub(v) for k, v in value.items()}
        return value

    def write(self):
        finished_utc = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        payload = {
            'scenario': self.scenario_title,
            'manager_base': BASE,
            'started_utc': self.started_utc,
            'finished_utc': finished_utc,
            'steps': self.scrub(self.steps),
        }
        with open(self.evidence_json, 'w') as fh:
            json.dump(payload, fh, indent=1)
            fh.write('\n')
        self._write_markdown(payload)

    def _write_markdown(self, payload):
        lines = [f"# {self.scenario_title} — evidence", '',
                 f"Manager: `{payload['manager_base']}`  ", f"Run: {payload['started_utc']} — {payload['finished_utc']}", '']
        for step in payload['steps']:
            lines.append(f"## Step {step['step']}: {step['title']} — {step['result']}")
            if step['actions']:
                lines.append('')
                lines.append('Actions:')
                for a in step['actions']:
                    lines.append(f"- {a}")
            if step['observed']:
                lines.append('')
                lines.append('Observed:')
                for k, v in step['observed'].items():
                    lines.append(f"- **{k}**: {v}")
            if step['device_evidence']:
                lines.append('')
                lines.append('Device evidence (eos.py, direct SSH):')
                for k, v in step['device_evidence'].items():
                    lines.append(f"- **{k}**: {v}")
            if step['remote_evidence']:
                lines.append('')
                lines.append('Remote evidence (GitHub):')
                for k, v in step['remote_evidence'].items():
                    lines.append(f"- **{k}**: {v}")
            if step['screenshots']:
                lines.append('')
                lines.append('Screenshots:')
                for s in step['screenshots']:
                    lines.append(f"- `{s['file']}` ({s['element']})")
            if step['notes']:
                lines.append('')
                lines.append('Notes:')
                for n in step['notes']:
                    lines.append(f"- {n}")
            lines.append('')
        text = '\n'.join(lines).replace('\r', '')
        text = '\n'.join(line.rstrip() for line in text.split('\n'))
        with open(self.evidence_md, 'w') as fh:
            fh.write(text + '\n')
