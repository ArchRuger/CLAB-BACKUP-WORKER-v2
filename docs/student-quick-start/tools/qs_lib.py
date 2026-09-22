"""Shared Playwright/API helpers for the student quick-start scenario captures.

Thin, reusable layer over the real page flows (modelled on
docs/save-location-fix/tools/qa_lib.py) so each scenario script stays short and every screenshot
and evidence record is produced the same way. Nothing here talks to the Store directly; every call
either drives the real page or issues the same same-origin request the page itself issues.
"""
import json
import pathlib
import time

BASE = 'http://127.0.0.1:8081'
VIEWPORT = {'width': 1366, 'height': 900}
DEVICE_SCALE_FACTOR = 2
FINAL_GIT_JOB_STATES = ('synced', 'unchanged', 'committed', 'review_pending', 'push_pending',
                        'export_pending', 'failed', 'capture_incomplete', 'dismissed', 'interrupted')
ACTIVE_RESTORE_STATES = ('queued', 'preflight', 'backing_up', 'applying', 'confirming', 'verifying')

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
    """Wait for the page to go quiet before a screenshot: network idle, then a fixed pause so a
    just-opened dialog has finished animating and any poll-driven re-render has landed."""
    try:
        page.wait_for_load_state('networkidle', timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(extra_ms)


def api(page, method, path, body=None):
    """Same-origin fetch from inside the page context (what the page itself would send)."""
    script = """(args) => fetch(args.path, {
        method: args.method,
        headers: args.body !== null ? {'Content-Type': 'application/json'} : undefined,
        body: args.body !== null ? JSON.stringify(args.body) : undefined
    }).then(async r => ({status: r.status, body: await r.json().catch(() => null)}))"""
    return page.evaluate(script, {'path': path, 'method': method, 'body': body})


def poll_git_job(page, job_id, timeout=180):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = api(page, 'GET', f'/api/git/jobs/{job_id}')['body']
        if job and job.get('status') in FINAL_GIT_JOB_STATES:
            break
        time.sleep(2)
    return job


def poll_restore_job(page, job_id, timeout=900):
    deadline = time.time() + timeout
    job = None
    while time.time() < deadline:
        job = api(page, 'GET', f'/api/restore/jobs/{job_id}')['body']
        if job and job.get('status') not in ACTIVE_RESTORE_STATES:
            break
        time.sleep(4)
    return job


def upload_review(page, timeout=30000):
    """Click "Upload these changes" in an open review dialog; returns (job_id, retry_response)."""
    import re
    with page.expect_response(
        lambda r: r.request.method == 'POST' and re.search(r'/api/git/jobs/[0-9a-f]+/retry$', r.url),
        timeout=timeout,
    ) as resp_info:
        page.click('#git-review-push')
    retry_resp = resp_info.value.json()
    return retry_resp.get('id'), retry_resp


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

    def write(self):
        finished_utc = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        payload = {
            'scenario': self.scenario_title,
            'manager_base': BASE,
            'started_utc': self.started_utc,
            'finished_utc': finished_utc,
            'steps': self.steps,
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
        with open(self.evidence_md, 'w') as fh:
            fh.write('\n'.join(lines) + '\n')
