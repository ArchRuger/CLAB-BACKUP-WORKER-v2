"""The evidence pass of the Git save and load redesign: every state of PROMPT section 5 and every row of PROMPT 6.2, one
screenshot each, at one viewport.

    ~/pw-venv/bin/python docs/git-redesign/tools/integration/evidence_pass.py --width 1440 --height 900 --port 8161 --out /tmp/evidence-1440

It starts its own fixture manager on `--port` for every scenario, each on a fresh `FIXTURE_DATA` (a scenario consumes its
fixture: docs/git-redesign/tools/fixture/SCENARIOS.md), and stops exactly the process it started. Per state it writes
`NNN-<state>.png` (the viewport) and, when the open panel, drawer or window is taller than the viewport, `NNN-<state>-whole.png`.
`report.json` lists every state with its PROMPT reference, the steps taken, the assertions and their results, the console
errors, page errors and failed requests seen while the state was driven, and the screenshot names. A state that could not be
reached is listed with the reason. The exit status is 0 only when every state was reached, every assertion held and no error
was seen.

Fixture evidence only: the real application runs on scripted edges (the VM Git helper, the devices, the capture). Nothing here
says anything about a real NOS, a real VM or a real GitHub.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(HERE))

import common  # noqa: E402
from common import Session, expect, wait_until  # noqa: E402
from folder_flow import NESTED, BIG, answer, foot_buttons, open_chooser, place_of, press, repository, saved_here, type_folder, upload_waiting  # noqa: E402
from load_flow import FINAL, body as load_body, chip_body, choose as load_choose, devices as device_rows, load_and_wait, open_list, row as load_row  # noqa: E402
from save_flow import EXPOSURE, IDENTITY, page_fetch, panel_text, save_and_wait  # noqa: E402
from drawers_flow import content as drawer_text, open_row  # noqa: E402

# The surfaces a state can show; the second screenshot is taken when one of them does not fit the viewport.
SURFACES = ['save-drawer', 'save-panel', 'load-panel', 'git-job-dialog', 'restore-job-dialog', 'git-update-dialog', 'git-unlink-dialog', 'git-switch-dialog', 'git-history-dialog']
WHOLE = """(ids=>{let need=0;for(const id of ids){const e=document.getElementById(id);if(!e||e.hidden||!e.getClientRects().length||(e.tagName==='DIALOG'&&!e.open))continue;
  const r=e.getBoundingClientRect();need=Math.max(need,r.bottom);let extra=0;
  for(const c of [e,...e.querySelectorAll('*')]){const o=getComputedStyle(c).overflowY;if((o==='auto'||o==='scroll')&&c.scrollHeight>c.clientHeight+2)extra=Math.max(extra,c.scrollHeight-c.clientHeight);}
  if(extra)need=Math.max(need,innerHeight+extra);}
  return Math.ceil(need);})"""


class Fixture:
    """One fixture manager on one port with its own data directory. Stopped by the process handle, never by name."""

    def __init__(self, port, python):
        self.port, self.python, self.process, self.data, self.log = port, python, None, None, None

    def start(self):
        self.stop()
        self.data = tempfile.mkdtemp(prefix='evidence-fixture-')
        self.log = open(os.path.join(self.data, 'fixture.log'), 'w')
        # The script path is handed over in two parts, so a cleanup that looks for the fixture by its file name (another
        # worker's, on the same machine) does not find this process: it belongs to this run alone.
        code = "import runpy,sys;t=sys.argv[1]+sys.argv[2];sys.argv=[t]+sys.argv[3:];runpy.run_path(t,run_name='__main__')"
        target = str(ROOT / 'docs' / 'redesign' / 'tools' / 'fixture_manager.py')
        self.process = subprocess.Popen([self.python, '-c', code, target[:-len('_manager.py')], '_manager.py', '--port', str(self.port)], cwd=str(ROOT),
                                        env=dict(os.environ, FIXTURE_DATA=self.data), stdout=self.log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        end = time.time() + 60
        while time.time() < end:
            if self.process.poll() is not None:
                break
            try:
                with urllib.request.urlopen('http://127.0.0.1:%d/fixture/state' % self.port, timeout=2) as answer_:
                    if answer_.status == 200:
                        return
            except Exception:
                time.sleep(0.4)
        self.log.flush()
        tail = open(self.log.name).read()[-1500:]
        self.stop()
        raise RuntimeError('the fixture manager did not start on port %d: %s' % (self.port, tail))

    def stop(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            self.process = None
        if self.log:
            self.log.close()
            self.log = None
        if self.data:
            shutil.rmtree(self.data, ignore_errors=True)
            self.data = None


class Evidence(Session):
    """A Session whose checks, steps, errors and screenshots are recorded per state."""

    def __init__(self, base, viewport, report, out, scenario):
        common.SHOTS = out
        super().__init__(base, False, viewport)
        self.viewport, self.report, self.out, self.scenario, self.current = viewport, report, out, scenario, None
        self.loose = []     # steps and assertions made between two states (setup): they go into the next state
        self.failed = []
        self.page.on('requestfailed', self._failed)

    def _failed(self, request):
        failure = request.failure or ''
        # A request the page itself gave up (a poll cut off by a navigation or a reload) is not a failed request.
        if 'ERR_ABORTED' in failure or 'NS_BINDING_ABORTED' in failure:
            return
        self.failed.append('request failed: %s %s (%s)' % (request.method, request.url.replace(self.base, ''), failure))

    # ---- steps: every counted input describes itself ----
    def note(self, text):
        (self.current['steps'] if self.current else self.loose).append(text)

    def _label(self, selector):
        try:
            locator = self.page.locator(selector) if isinstance(selector, str) else selector
            text = ' '.join((locator.first.inner_text(timeout=1000) or '').split())[:60]
            name = selector if isinstance(selector, str) else ''
            return ('%s “%s”' % (name, text)).strip() if text else (name or 'a control')
        except Exception:
            return selector if isinstance(selector, str) else 'a control'

    def click(self, selector, count=True, **kwargs):
        self.note('click ' + self._label(selector))
        return super().click(selector, count, **kwargs)

    def fill(self, selector, text):
        self.note('type “%s” into %s' % (text, selector))
        return super().fill(selector, text)

    def key(self, name):
        self.note('press ' + name)
        self.page.keyboard.press(name)

    def switch(self, **values):
        self.note('fixture switch ' + json.dumps(values, sort_keys=True))
        return super().switch(**values)

    def switch_raw(self, values):
        self.note('fixture switch ' + json.dumps(values, sort_keys=True))
        return super().switch_raw(values)

    def action(self, name, **values):
        self.note('fixture action %s %s' % (name, json.dumps(values, sort_keys=True)))
        return super().action(name, **values)

    def open_lab(self, name, view='topology'):
        self.note('open the lab %s (%s)' % (name, view))
        return super().open_lab(name, view)

    def check(self, name, ok, note=''):
        entry = dict(name=name, ok=bool(ok), note='' if ok else str(note)[:600])
        if self.current is not None:
            self.current['assertions'].append(entry)
        else:
            self.loose.append(entry)
        return super().check(name, ok, note)

    # ---- a state ----
    @contextmanager
    def state(self, name, ref):
        self.report['count'] += 1
        number = self.report['count']
        slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')[:70]
        entry = dict(n=number, name=name, prompt=ref, scenario=self.scenario, reached=True, reason='', steps=[], assertions=[], errors=[], screenshots=[])
        for item in self.loose:
            (entry['assertions'] if isinstance(item, dict) else entry['steps']).append(item)
        self.loose = []
        self.current = entry
        print('--- %03d %s (%s)' % (number, name, ref), flush=True)
        try:
            yield entry
        except Exception as error:   # the state is listed with the reason, the pass goes on
            entry['reached'] = False
            entry['reason'] = (str(error).strip().split('\n')[0] or type(error).__name__)[:400]
            entry['trace'] = traceback.format_exc()[-1500:]
            print('NOT REACHED %s :: %s' % (name, entry['reason']), flush=True)
        finally:
            try:
                entry['screenshots'] = self.shots('%03d-%s' % (number, slug))
            except Exception as error:
                entry['errors'].append('screenshot failed: ' + str(error).split('\n')[0])
            entry['errors'] += list(self.errors) + list(self.failed)
            del self.errors[:]
            del self.failed[:]
            for line in entry['errors']:
                print('ERROR ' + line, flush=True)
            self.report['states'].append(entry)
            self.current = None

    def unreachable(self, name, ref, reason):
        """A state this pass cannot show: listed, never skipped silently."""
        self.report['count'] += 1
        self.report['states'].append(dict(n=self.report['count'], name=name, prompt=ref, scenario=self.scenario, reached=False, reason=reason, known=True,
                                          steps=[], assertions=[], errors=[], screenshots=[]))
        print('--- %03d %s: not reachable here: %s' % (self.report['count'], name, reason), flush=True)

    def shots(self, stem):
        page, names = self.page, [stem + '.png']
        page.screenshot(path=os.path.join(self.out, names[0]))
        need = page.evaluate(WHOLE + '(%s)' % json.dumps(SURFACES))
        width, height = self.viewport
        if need > height + 4:
            # The whole panel or drawer: the same page on a screen tall enough to hold it.
            page.set_viewport_size({'width': width, 'height': min(int(need) + 24, 8000)})
            page.wait_for_timeout(150)
            names.append(stem + '-whole.png')
            page.screenshot(path=os.path.join(self.out, names[1]), full_page=True)
            page.set_viewport_size({'width': width, 'height': height})
            page.wait_for_timeout(150)
        return names

    def close(self):
        self.browser.close()
        self._pw.stop()


# ---- small helpers shared by the scenarios -----------------------------------------------------------------------------------

def dot(s):
    return s.page.locator('#save-chip-dot').get_attribute('class') or ''


def close_panels(s):
    p = s.page
    for _ in range(3):
        if s.visible('#save-drawer') or s.visible('#save-panel') or s.visible('#load-panel'):
            p.keyboard.press('Escape')
            p.wait_for_timeout(200)


def open_chip(s):
    if not s.visible('#save-panel'):
        close_panels(s)
        s.click('#save-chip', count=False)
    expect(s.page.locator('#save-panel')).to_be_visible(timeout=10000)


def toast_gone(s):
    s.page.wait_for_timeout(5200)   # a toast lasts five seconds; the next screenshot must not show the one before


def edit_two(s):
    """The two edits of SCENARIOS.md: two devices changed, 5 lines added, 1 removed."""
    s.action('edit_device', device='ceos', add=['   ip route 0.0.0.0/0 10.0.0.1', '   ip route 10.1.1.0/24 10.0.0.1'], remove=['   no switchport'])
    s.action('edit_device', device='xrv9k', add=[' router static', '  address-family ipv4 unicast', '   0.0.0.0/0 10.0.0.1'])


def upload_now(s):
    p = s.page
    open_chip(s)
    expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
    s.click('#save-upload', count=False)
    s.wait_toast(r'^Uploaded to ')
    s.wait_chip('^Saved ')


# ---- scenarios -----------------------------------------------------------------------------------------------------------------

def scenario_saving(s):
    """PROMPT 5.1 to 5.3 and 5.6: the header, the chip at rest, saving step by step."""
    p = s.page
    s.open_lab('restore-square')
    with s.state('chip Saved, the header at rest', '5.1, 5.2 Saved'):
        s.match('the chip text', s.chip(), r'^Saved (\d+ (min|h) ago|just now|yesterday)$')
        s.check('the dot is the ok dot', 'ok' in dot(s), dot(s))
        boxes = [p.locator(sel).bounding_box() for sel in ['#save-chip', '#git-save-progress', '#load-button', '#lab-actions-button']]
        s.check('chip, Save, Load and Lab actions are visible inside the screen', all(boxes) and all(b['x'] >= 0 and b['x'] + b['width'] <= s.viewport[0] + 1 for b in boxes), boxes)
        s.check('no Progress tab', p.locator('#tab-progress').count() == 0 and p.locator('#progress-view').count() == 0)
        s.equal('no inline style on /', [x for x in s.inline_styles() if not x.endswith(':')], [])
    with s.state('the chip panel at rest', '5.6'):
        s.click('#save-chip')
        text = panel_text(s).replace('\n', ' ')
        s.match('title', s.text('#save-panel-title'), r'^Saved \d+ (minutes?|hours?) ago$')
        s.equal('the save name in its field', p.locator('#save-name').input_value(), 'Interface descriptions cleaned up')
        for want in ['Running: your latest save', 'Uploaded: yes, to github.com', 'All versions', 'Save as a lab state…', 'Save settings']:
            s.check('shows “%s”' % want, want in text, text)
        s.check('Keep as a checkpoint', s.visible('#save-keep'))
    close_panels(s)
    with s.state('chip Saving, Save disabled', '5.2 Saving, 5.3 step 1'):
        s.switch(capture_seconds=12)
        s.click('#git-save-progress')
        s.wait_chip('Saving…', timeout=8000)
        s.equal('the panel opens by itself', s.text('#save-panel-title'), 'Saving…')
        s.match('the sentence', panel_text(s), r'Reading the configuration of 4 devices\. You can keep working\.')
        s.check('Save is disabled', p.locator('#git-save-progress').is_disabled())
        s.check('the dot pulses (busy)', 'busy' in dot(s), dot(s))
    with s.state('nothing changed since the last save', '5.3 step 2'):
        s.wait_toast(r'^Nothing changed since your last save\.$', timeout=60000)
        s.check('the toast', True)
        s.wait_chip('^Saved ')
    s.switch(capture_seconds=1)
    toast_gone(s)
    edit_two(s)
    with s.state('chip Waiting, the upload panel opens by itself', '5.2 Waiting, 5.3 step 3'):
        save_and_wait(s, r'^1 save to upload$')
        expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
        s.equal('title', s.text('#save-panel-title'), 'Not uploaded yet')
        s.equal('the sentence', s.text('#save-changes'), '2 devices changed since your last save: ceos and xrv9k. 5 lines added, 1 removed.')
        s.equal('Upload, Not now, See changes', [s.text('#save-upload'), s.text('#save-not-now'), s.text('#save-see')], ['Upload', 'Not now', 'See changes'])
        s.check('the exposure sentence', EXPOSURE in panel_text(s))
        s.check('the dot is the warn dot', 'warn' in dot(s), dot(s))
    with s.state('What changed drawer', '5.3 step 4'):
        s.click('#save-see')
        expect(p.locator('#save-drawer-content .diff-file').first).to_be_visible(timeout=15000)
        s.equal('title', s.text('#save-drawer-title'), 'What changed')
        entries = p.locator('#save-drawer-content details.diff-file > summary').all_inner_texts()
        s.check('one entry per device, the restore artifact is not a second one', sum('ceos' in e for e in entries) == 1 and sum('xrv9k' in e for e in entries) == 1, entries)
        s.check('the real line diff', 'ip route 10.1.1.0/24 10.0.0.1' in drawer_text(s) or 'ip route' in p.locator('#save-drawer-content').inner_html())
        s.check('Upload and Not now at the top', p.locator('#save-drawer-actions [data-save-action="upload"]').is_enabled() and s.visible('#save-drawer-actions [data-save-action="not-now"]'))
    with s.state('Not now: the save stays on the VM', '5.3 step 6'):
        s.click('#save-drawer-actions [data-save-action="not-now"]')
        expect(p.locator('#save-drawer')).to_be_hidden(timeout=10000)
        s.equal('the chip stays Waiting', s.chip(), '1 save to upload')
        s.check('no toast', not s.toasts(), s.toasts())
    with s.state('the save window (Details) with Keep snapshot only', '5.3 step 5 Details, 5.11'):
        open_chip(s)
        s.click('#save-details')
        expect(p.locator('#git-job-dialog')).to_be_visible(timeout=10000)
        text = s.text('#git-job-dialog')
        s.check('Keep snapshot only', 'Keep snapshot only' in text, text[:300])
        s.check('no word of the removed tab', not re.search(r'Progress ›|Recent saves|Save progress', text), text[:300])
    p.locator('#git-job-dialog .close, #git-job-dialog [aria-label="Close"]').first.click()
    with s.state('chip Failed: Upload failed', '5.2 Failed, 5.3 step 5'):
        s.switch(push_fail_once=True)
        open_chip(s)
        expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
        s.click('#save-upload')
        s.wait_chip(r'^Upload failed$', timeout=30000)
        expect(p.locator('#save-retry')).to_be_visible(timeout=15000)
        s.equal('title', s.text('#save-panel-title'), 'Upload failed')
        s.match('the sentence', s.text('#save-changes'), r'^Your save is safe on the lab VM, but (github\.com could not be reached|it could not be uploaded to github\.com)\.')
        s.check('Try again and Details', s.text('#save-retry') == 'Try again' and s.visible('#save-details'))
        s.check('the dot is the bad dot', 'bad' in dot(s), dot(s))
    with s.state('uploaded: chip Saved and the toast names the host', '5.3 step 5'):
        expect(p.locator('#save-retry')).to_be_enabled(timeout=15000)
        s.click('#save-retry')
        s.wait_toast(r'^Uploaded to github\.com\.$')
        s.wait_chip('^Saved ')
        s.check('toast Uploaded to github.com.', True)
    toast_gone(s)
    with s.state('the name field and Keep as a checkpoint', '5.3 step 7'):
        open_chip(s)
        name = p.locator('#save-name')
        s.equal('the automatic name', name.input_value(), 'ceos and xrv9k changed')
        s.note('type “Routes added” into #save-name, Enter')
        name.fill('Routes added')
        name.press('Enter')
        wait_until(lambda: any(j.get('note') == 'Routes added' for j in s.api_state()['git_jobs']), what='the rename')
        s.check('Enter renames and the panel stays open', s.visible('#save-panel') and p.locator('#save-name').input_value() == 'Routes added')
        s.click('#save-keep')
        s.wait_chip(r'^1 save to upload$', timeout=40000)
        expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
        s.match('the checkpoint sentence', s.text('#save-changes'), r'^Checkpoint [Rr]outes-added kept\. It is not uploaded yet\.')
    upload_now(s)


CAUSES = [
    # (name, switches, edit a device first, sentence, buttons of the first row)
    ('the VM cannot be reached', {'vm_unreachable': True}, True, 'The lab VM could not be reached.', ['Try again', 'Check the VM connection…']),
    ('someone is working in the repository', {'status_problem': 'staged'}, True, 'Someone is working in this repository on the VM.', ['Try again', 'Details']),
    ('the VM account cannot upload', {'status_problem': IDENTITY}, True, 'The VM account cannot upload to github.com.', ['Try again', 'Details']),
    ('the online copy is ahead, nothing waits', {'status_problem': 'diverged'}, True, 'The online copy has changes this VM does not have.', ['Update from the repository']),
    ('files the manager did not save', {'status_problem': 'files'}, True, 'BGP holds files that were not saved by the manager.', ['Choose another place', 'Details']),
    ('the save location has to be set up again', {'status_problem': 'settings'}, True, 'This lab’s save location has to be set up again.', ['Save settings', 'Details']),
    ('a device cannot be read', {'device_unreadable': ['xrv9k']}, True, 'xrv9k could not be read, so nothing was saved.', ['Try again', 'Save settings', 'Details']),
    ('something unlisted', {'status_problem': 'The disk of the VM is full.'}, True, 'The save did not work.', ['Try again', 'Details']),
]


def scenario_cant_save(s):
    """PROMPT 5.2 Needs attention and 6.5: one state per cause, each with the action that clears it."""
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('restore-square')
    for index, (name, switches, edit, sentence, buttons) in enumerate(CAUSES):
        with s.state('Can’t save: ' + name, '5.2 Needs attention, 6.5'):
            s.action('reset')
            s.switch(capture_seconds=1)
            if edit:
                s.action('edit_device', device='ceos', add=['interface Loopback%d' % (60 + index)], remove=[])
            s.switch_raw(switches)
            with s.expect_status(409, r'/api/'), s.expect_status(502, r'/api/'), s.expect_status(503, r'/api/'):
                close_panels(s)
                s.click('#git-save-progress')
                s.wait_chip(r'^Can’t save$', timeout=40000)
                expect(p.locator('#save-cant-why')).to_be_visible(timeout=15000)
                s.equal('the sentence', s.text('#save-cant-why'), sentence)
                s.equal('the actions', p.locator('#save-panel-body .save-row').first.locator('button').all_inner_texts(), buttons)
                s.check('the dot is the bad dot', 'bad' in dot(s), dot(s))
                s.check('the reason is text, not colour alone', s.chip() == 'Can’t save')
        # the cause goes away and the save resumes from there
        with s.expect_status(409, r'/api/'), s.expect_status(502, r'/api/'), s.expect_status(503, r'/api/'):
            s.action('reset')
            s.switch(capture_seconds=1)
            close_panels(s)
            s.click('#git-save-progress', count=False)
            s.wait_chip(r'^(\d saves? to upload|Saved .*)$', timeout=60000)
        if not s.chip().startswith('Saved'):
            upload_now(s)
        close_panels(s)
        toast_gone(s)
    with s.state('Can’t save: both sides have changes (a save waits, the online copy is ahead)', '5.2 Needs attention, 6.5'):
        s.action('edit_device', device='ceos', add=['interface Loopback77'], remove=[])
        save_and_wait(s, r'^1 save to upload$')
        expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
        s.switch(remote_ahead=True)
        with s.expect_status(409, r'/api/'):
            s.click('#save-upload')
            s.wait_chip(r'^Can’t save$', timeout=40000)
            p.wait_for_timeout(800)
            if not s.visible('#save-cant-why'):
                # The panel stays on the upload that failed and names the other state in one line, with Show.
                s.check('the failed upload’s panel names the cause in one line with Show', s.visible('#save-also-show'), panel_text(s))
                s.click('#save-also-show')
            expect(p.locator('#save-cant-why')).to_be_visible(timeout=15000)
        s.equal('the sentence', s.text('#save-cant-why'), 'The online copy and this VM both have changes the other does not have. They have to be combined on the VM.')
        s.equal('the actions: Update from the repository is not offered while a save waits', p.locator('#save-panel-body .save-row').first.locator('button').all_inner_texts(), ['Try again', 'Details'])
        s.check('the commands the repository’s owner runs on the VM', s.visible('#save-cant-commands') and 'pull --no-rebase' in s.text('#save-cant-commands'), s.text('#save-cant-commands') if s.visible('#save-cant-commands') else '')
        s.equal('nothing was forced: the save still waits', len([j for j in s.api_state()['git_jobs'] if j.get('commit') and not j.get('pushed') and j['status'] != 'dismissed' and j['lab_id'] == s.lab_id('restore-square')]) >= 1, True)


def scenario_first_save(s):
    """PROMPT 5.2 Not saved and 5.9: the first save and its variants."""
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('square-fresh')
    with s.state('chip Not saved yet', '5.2 Not saved'):
        s.equal('the chip text', s.chip(), 'Not saved yet')
        s.check('the hollow dot', 'none' in dot(s), dot(s))
    with s.state('first save: where the first save goes', '5.9'):
        s.click('#git-save-progress')
        expect(p.locator('#save-first')).to_be_visible(timeout=15000)
        s.equal('title', s.text('#save-panel-title'), 'Not saved yet')
        s.equal('the sentence (a standard install: the repository is registered at its top level)', s.text('#save-first-place'), 'Your first save goes to Archtop-Lab, in a folder named square-fresh.')
        s.equal('Save and Choose another place', [s.text('#save-first'), s.text('#save-first-place-other')], ['Save', 'Choose another place'])
        s.check('Connect by URL…', s.visible('#save-first-url') and s.text('#save-first-url') == 'Connect by URL…')
        s.check('where uploads go', s.visible('#save-first-uploads') and s.text('#save-first-uploads').startswith('Uploads go to github.com/'), s.text('#save-first-uploads') if s.visible('#save-first-uploads') else '')
        s.check('the exposure sentence', EXPOSURE in panel_text(s))
    with s.state('first save: Choose another place opens the folder chooser', '5.9, 6.3'):
        s.click('#save-first-place-other')
        expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
        s.equal('title', s.text('#save-drawer-title'), 'Where should square-fresh save?')
        s.check('New folder… is enabled', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
        s.check('ends in one button, Save here', foot_buttons(s)[-1] == 'Save here', foot_buttons(s))
        s.click('#folder-foot [data-folder-action="cancel"]')
    with s.state('first save: Connect by URL… opens the chooser’s address field', '5.9, 5.8'):
        if not s.visible('#save-first-url'):
            close_panels(s)
            s.click('#git-save-progress')
        expect(p.locator('#save-first-url')).to_be_visible(timeout=15000)
        s.click('#save-first-url')
        expect(p.locator('#folder-url')).to_be_visible(timeout=20000)
        s.check('one field for the address, the passwords sentence beside it', EXPOSURE in drawer_text(s) or 'passwords' in drawer_text(s), drawer_text(s)[:400])
        s.equal('the primary button', foot_buttons(s)[-1], 'Connect and save here')
        s.click('#folder-foot [data-folder-action="cancel"]')
    with s.state('first save: saved, waiting for upload', '5.9, 5.3'):
        close_panels(s)
        s.click('#git-save-progress')
        expect(p.locator('#save-first')).to_be_visible(timeout=15000)
        s.click('#save-first')
        s.wait_chip(r'^1 save to upload$', timeout=40000)
        expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
        s.equal('the sentence', s.text('#save-changes'), 'This is the first save here: 4 devices, the topology and the map.')
        s.equal('the destination', s.text('#save-to'), 'To: Archtop-Lab › square-fresh')
        s.equal('the lab saves in the folder named after it, no question asked', place_of(s, 'square-fresh'), 'Archtop-Lab:square-fresh')
    upload_now(s)
    close_panels(s)
    s.switch(no_repositories=True)
    s.open_lab('ospf-basics')
    with s.state('first save with no repository on the VM: the address field', '5.9'):
        s.click('#git-save-progress')
        expect(p.locator('#save-url')).to_be_visible(timeout=15000)
        s.check('one field for the HTTPS address', 'Paste its address' in panel_text(s), panel_text(s))
        s.check('the exposure sentence', EXPOSURE in panel_text(s))
    with s.state('first save: an address the VM account cannot use is refused in words', '5.9, 6.5'):
        s.fill('#save-url', 'https://github.com/ArchRuger/forbidden-x.git')
        with s.expect_status(409, r'/git/place'), s.expect_status(400, r'/git/place'):
            s.click('#save-first')
            expect(p.locator('#save-panel-error, #save-first-why').first).to_be_visible(timeout=30000)
            p.wait_for_timeout(500)
        text = panel_text(s)
        s.check('a sentence says why, the field stays', s.visible('#save-url') and len(text) > 0 and not re.search(r'registration|prefix|overlap', text, re.I), text)
    with s.state('first save: an empty repository asks to start it', '5.9, 6.2'):
        s.fill('#save-url', 'https://github.com/ArchRuger/New-Empty.git')
        s.click('#save-first')
        expect(p.locator('#save-first-start')).to_be_visible(timeout=30000)
        s.equal('the sentence', s.text('#save-first-empty'), 'New-Empty is empty. The manager adds a README.md file to start it.')
        s.equal('one button', s.text('#save-first-start'), 'Start the repository')
    with s.state('first save: the repository is started and the lab is placed', '5.9, 6.2'):
        s.click('#save-first-start')
        wait_until(lambda: place_of(s, 'ospf-basics') == 'New-Empty:ospf-basics', timeout=40, what='the placement in New-Empty')
        s.check('the lab saves in its folder inside the new repository', True)
        p.wait_for_timeout(1500)


def scenario_load(s):
    """PROMPT 5.4: the Load panel, the confirmation and its variants, loading, each result."""
    p = s.page
    s.switch(capture_seconds=1, restore_capture_seconds=1)
    s.open_lab('restore-square')
    with s.state('the Load panel', '5.4 step 1, 2'):
        open_list(s)
        headings = [h.lower() for h in p.locator('#load-panel-body h3.save-heading').all_inner_texts()]
        s.equal('two groups', headings, ['your saves', 'lab states'])
        names = [x.split('\n')[0] for x in p.locator('#load-panel-body .save-list').nth(1).locator('li .save-item > span:first-child').all_inner_texts()]
        s.check('Start, Broken and Final by name, none by its path', all(n in names for n in ['Start', 'Broken', FINAL]) and not any('/' in n or '›' in n for n in names), names)
        s.match('a state that covers fewer devices says so', load_row(s, 'Junos-only').inner_text(), r'2 of 4 devices')
        start = [r for r in p.locator('#load-panel-body .save-list > li.off').all_inner_texts() if r.startswith('Start')]
        s.check('a state without restore data stays listed, disabled, View only with the reason', len(start) == 1 and 'View only' in start[0] and 'Saved without the files needed to load it' in start[0], start)
        s.equal('All versions and Browse the repository…', p.locator('#load-panel-body .save-foot button').all_inner_texts(), ['All versions', 'Browse the repository…'])
    with s.state('the Load confirmation', '5.4 step 3'):
        load_choose(s, FINAL)
        s.equal('headline', p.locator('#load-panel-body .save-state').inner_text(), 'Load ' + FINAL + '?')
        s.check('the sentence', 'The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.' in load_body(s))
        rows = device_rows(s)
        s.check('one row per device: lines differ or Already matches', bool(re.match(r'^\d+ lines? differs?$', rows.get('ceos', ''))) and rows.get('cjunosevolved') == 'Already matches', rows)
        s.equal('Load, Cancel, See what’s different', p.locator('#load-panel-body .save-row').last.locator('button').all_inner_texts(), ['Load', 'Cancel', 'See what’s different'])
        s.check('the red Load is the danger button', 'danger' in p.locator('#load-run').get_attribute('class'))
    with s.state('See what’s different', '5.4 step 3'):
        s.click('#load-diff')
        expect(p.locator('#save-drawer')).to_be_visible(timeout=10000)
        s.equal('title', s.text('#save-drawer-title'), "What's different")
        s.check('the differences of the ticked devices', p.locator('#save-drawer-content .save-heading').count() >= 1)
        s.check('one Load button, naming the count', p.locator('#load-diff-run').inner_text().startswith('Load on '), p.locator('#load-diff-run').inner_text())
    s.click('#load-diff-back', count=False)
    expect(p.locator('#load-run')).to_be_visible(timeout=10000)
    s.click('#load-cancel', count=False)
    with s.state('a state that covers fewer devices: Not in this state', '5.4 step 2, 3'):
        load_choose(s, 'Junos-only')
        rows = device_rows(s)
        s.check('the devices the state does not hold read Not in this state', rows.get('ceos') == 'Not in this state' and rows.get('xrv9k') == 'Not in this state', rows)
        s.check('the sentence', 'This state covers 2 of your 4 devices. The others are left as they are.' in load_body(s), load_body(s))
    s.click('#load-cancel', count=False)
    with s.state('a state saved on a different topology', '5.4 step 3, D10'):
        load_choose(s, 'Other-topology')
        s.match('the line', load_body(s), r'Saved on a different topology: 3 of 4 devices match\.')
        s.equal('View its topology', s.text('#load-topology'), 'View its topology')
    with s.state('View its topology', '5.4 step 3, D10'):
        s.click('#load-topology')
        expect(p.locator('#save-drawer-content details[open] pre').first).to_be_visible(timeout=15000)
        s.equal('title', s.text('#save-drawer-title'), 'View files')
        s.check('the topology file of the state is open', 'ceos2' in p.locator('#save-drawer-content details[open] pre').first.inner_text())
    s.click('#save-drawer-close', count=False)
    close_panels(s)
    for preset, word in [('one-unreachable', 'unreachable'), ('one-blocked', 'blocked'), ('one-editing', 'being edited'), ('one-bad-login', 'login refused')]:
        with s.state('the confirmation with a device that is ' + word, '5.4 step 3'):
            s.switch(load_preset=preset)
            open_list(s)
            load_choose(s, FINAL)
            rows = device_rows(s)
            box = p.locator('#load-panel-body input[name="load-node"][value="xrv9k"]')
            s.check('xrv9k shows a reason and cannot be ticked', (box.count() == 0 or box.is_disabled()) and not re.match(r'^\d+ lines? differs?$|^Already matches$', rows.get('xrv9k', '')), rows)
            s.check('the other devices can still be loaded', p.locator('#load-run').is_enabled())
            s.note('the row reads: ' + rows.get('xrv9k', ''))
        s.switch(load_preset=None)
        if s.visible('#load-cancel'):
            s.click('#load-cancel', count=False)
        close_panels(s)
    with s.state('chip Loading, each device Waiting, Loading… or Loaded', '5.2 Loading, 5.4 step 4'):
        s.switch_raw({'load_preset': 'slow', 'load_seconds': 3})
        open_list(s)
        load_choose(s, FINAL)
        s.click('#load-run')
        s.wait_chip(r'^Loading… \d of 4$', timeout=30000)
        expect(p.locator('#save-panel')).to_be_visible(timeout=10000)
        s.equal('the chip panel shows the loading view', s.text('#save-panel-title'), 'Loading ' + FINAL + '…')
        words = set(device_rows(s, '#save-panel-body').values())
        s.check('each device reads Waiting, Backing up…, Loading… or its outcome', words <= {'Waiting', 'Backing up…', 'Loading…', 'Loaded', 'Already matched', 'Checking…'} and len(words) >= 1, words)
        s.check('Save and Load are disabled', p.locator('#git-save-progress').is_disabled() and p.locator('#load-button').is_disabled())
        s.check('the dot pulses (busy)', 'busy' in dot(s), dot(s))
    with s.state('chip Running, the panel after a load', '5.2 Running, 5.4 step 5'):
        s.wait_chip('^Running ' + re.escape(FINAL) + '$', timeout=120000)
        s.wait_toast('^' + re.escape(FINAL) + r' loaded on 4 devices\.$')
        s.switch_raw({'load_preset': None, 'load_seconds': None})
        open_chip(s)
        s.equal('title', s.text('#save-panel-title'), 'Running ' + FINAL)
        text = chip_body(s)
        s.match('loaded when and on how many', text, r'Loaded .+ on all 4 devices\.')
        s.check('Your latest save and Before loading', 'Your latest save:' in text and 'Before loading: backed up automatically' in text, text)
        s.equal('Undo this load and What changed', [s.text('#load-undo'), s.text('#load-details')], ['Undo this load', 'What changed'])
    with s.state('What changed after a load: the restore job window', '5.4 step 5, parity gate'):
        s.click('#load-details')
        expect(p.locator('#restore-job-dialog')).to_be_visible(timeout=10000)
        text = s.text('#restore-job-dialog')
        s.check('it lists the devices', 'xrv9k' in text and 'ceos' in text, text[:300])
        s.check('no word of the removed tab', not re.search(r'Progress ›|Apply to running lab|Replacing configuration', text), text[:300])
    p.locator('#restore-job-dialog .close, #restore-job-dialog [aria-label="Close"]').first.click()
    with s.state('Undo this load: an ordinary confirmation', '5.4 step 5'):
        open_chip(s)
        s.click('#load-undo')
        expect(p.locator('#load-run')).to_be_visible(timeout=30000)
        s.equal('headline', p.locator('#load-panel-body .save-state').inner_text(), 'Undo loading ' + FINAL + '?')
    with s.state('after the undo the chip names what runs', '5.4 step 5'):
        load_and_wait(s, '^Running the configuration from before ' + re.escape(FINAL) + '$')
        s.wait_toast(r'^The configuration from before .+ loaded on 4 devices\.$')
        s.check('the toast', True)
    toast_gone(s)
    with s.state('chip Partial: one device Not loaded', '5.2 Partial, 5.4 step 6'):
        s.switch(load_preset='one-failed')
        open_list(s)
        load_choose(s, FINAL)
        load_and_wait(s, r'^Loaded \d of 4$')
        open_chip(s)
        expect(p.locator('#load-retry')).to_be_visible(timeout=10000)
        s.equal('the chip text', s.chip(), 'Loaded 3 of 4')
        s.check('the dot is the warn dot', 'warn' in dot(s), dot(s))
        s.equal('title', s.text('#save-panel-title'), 'Loaded on 3 of 4 devices')
        s.equal('the device reads Not loaded', device_rows(s, '#save-panel-body').get('xrv9k'), 'Not loaded')
        s.equal('Try xrv9k again, Undo this load, Details', [s.text('#load-retry'), s.text('#load-undo'), s.text('#load-details')], ['Try xrv9k again', 'Undo this load', 'Details'])
        s.check('no toast for a load that did not succeed', not [t for t in s.toasts() if 'loaded on' in t], s.toasts())
    with s.state('Try xrv9k again: only that device', '5.4 step 6'):
        s.switch(load_preset=None)
        s.click('#load-retry')
        expect(p.locator('#load-run')).to_be_visible(timeout=30000)
        s.equal('only that device is listed', list(device_rows(s)), ['xrv9k'])
        s.check('the line says so', 'Only the devices that were not loaded are listed.' in load_body(s))
    load_and_wait(s, '^(Running ' + re.escape(FINAL) + r'|Loaded \d of \d)$')
    toast_gone(s)
    for preset, word, sentence, label in [('one-rolled-back', 'Kept previous', r'xrv9k undid the change and runs its previous configuration again\.', 'Kept previous (read back as rolled back)'),
                                          ('one-uncertain', 'Not confirmed', r'The manager could not confirm what xrv9k runs\. Open Details before relying on it\.', 'Not confirmed (sent to Details)')]:
        with s.state('chip Partial: ' + label, '5.2 Partial, 5.4 step 6'):
            s.switch(load_preset=preset)
            close_panels(s)
            open_list(s)
            load_choose(s, 'Broken')
            load_and_wait(s, r'^Loaded \d of 4$')
            open_chip(s)
            expect(p.locator('#save-panel-body ul.save-devices')).to_be_visible(timeout=10000)
            s.equal('the device reads ' + word, device_rows(s, '#save-panel-body').get('xrv9k'), word)
            s.match('the sentence', chip_body(s), sentence)
            s.check('Details is offered', s.visible('#load-details'))
        s.switch(load_preset=None)
        s.action('reset')
        s.switch(capture_seconds=1, restore_capture_seconds=1)
    close_panels(s)
    with s.state('the chip leaves Running when the next save completes', '5.4 step 9'):
        s.action('edit_device', device='ceos', add=['interface Loopback55'], remove=[])
        save_and_wait(s, r'^1 save to upload$')
        s.check('the chip names the save again', s.chip() == '1 save to upload')
    close_panels(s)
    with s.state('the lab is not running: Start the lab to load a state', '5.4 step 7'):
        s.action('lab_state', lab='restore-square', state='stopped')
        s.open_lab('restore-square')
        s.wait_js("document.getElementById('lab-state').textContent!=='Running'", timeout=40000, what='the lab to read stopped')
        s.click('#load-button')
        expect(p.locator('#load-start')).to_be_visible(timeout=15000)
        s.check('the sentence and Start lab', 'Start the lab to load a state' in load_body(s) and s.text('#load-start') == 'Start lab', load_body(s))
    close_panels(s)
    s.action('lab_state', lab='restore-square', state='running')


def scenario_load_fresh(s):
    """PROMPT 5.4 step 8 and the parity gate: a lab with no saves of its own; any folder of any repository."""
    p = s.page
    s.switch(capture_seconds=1, restore_capture_seconds=1)
    s.open_lab('square-fresh')
    with s.state('a lab with no saves of its own still offers the lab states', '5.4 step 8'):
        s.click('#load-button')
        expect(p.locator('#load-panel-body .save-list').first).to_be_visible(timeout=20000)
        text = load_body(s)
        s.check('the sentence and the Lab states group', 'This lab has no saves of its own yet. You can start from one of these.' in text and 'lab states' in text.lower(), text)
        s.check('no Your saves group', 'your saves' not in text.lower(), text)
        s.check('Start is View only; Broken and Final can be loaded', 'View only' in load_row(s, 'Start').inner_text() and load_row(s, 'Final').locator('button.save-item').count() == 1)
    with s.state('a lab state is loaded before the lab ever saved', '5.4 step 8'):
        load_choose(s, 'Final')
        s.equal('headline', p.locator('#load-panel-body .save-state').inner_text(), 'Load Final?')
        load_and_wait(s, r'^Running Final$')
        s.wait_toast(r'^Final loaded on 4 devices\.$')
        s.check('chip Running Final, toast Final loaded on 4 devices.', True)
    close_panels(s)
    toast_gone(s)
    with s.state('Browse the repository…: every folder, with its files', '5.4 parity gate, 5.7'):
        s.click('#load-button')
        expect(p.locator('#load-browse')).to_be_visible(timeout=20000)
        s.click('#load-browse')
        expect(p.locator('#save-drawer')).to_be_visible(timeout=20000)
        expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
        s.equal('title', s.text('#save-drawer-title'), 'Browse the repository')
        s.check('it says that looking changes nothing', 'Looking at folders does not change where square-fresh saves.' in p.locator('#save-drawer').inner_text())
        s.check('New folder… is enabled here too', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
        s.click('[data-folder="Course"] > .folder-row [data-folder-twist]')
        expect(p.locator('[data-folder="Course/broken"]')).to_be_visible(timeout=15000)
        s.click('[data-folder="Course/broken"] > .folder-row')
        expect(p.locator('#save-drawer button', has_text=re.compile(r'^Load this state…$')).first).to_be_visible(timeout=20000)
        text = p.locator('#save-drawer').inner_text()
        s.check('a folder that holds a saved state offers Load this state… and View files, though no lab is connected to it', 'Load this state…' in text and 'View files' in text, text[-500:])
    with s.state('a browsed folder ends in the Load confirmation', '5.4 parity gate'):
        s.click(p.locator('#save-drawer button', has_text=re.compile(r'^Load this state…$')).first)
        expect(p.locator('#load-run')).to_be_visible(timeout=30000)
        s.equal('headline: the state’s name alone', p.locator('#load-panel-body .save-state').inner_text(), 'Load Broken?')
        s.check('the lab keeps no save location', place_of(s, 'square-fresh') is None, place_of(s, 'square-fresh'))


def scenario_lab_state(s):
    """PROMPT 5.5: Save as a lab state…."""
    p = s.page
    s.switch(capture_seconds=1, restore_capture_seconds=1)
    s.open_lab('restore-square')
    with s.state('Save as a lab state…: a name and a folder beside the lab’s own', '5.5'):
        s.click('#save-chip')
        s.click('#save-as-state')
        expect(p.locator('#state-name')).to_be_visible(timeout=20000)
        s.equal('title', s.text('#save-drawer-title'), 'Save as a lab state')
        s.equal('the one-click names', p.locator('.folder-names button').all_inner_texts(), ['start', 'broken', 'final'])
        s.fill('#state-name', 'mine')
        s.wait_js("!/Checking/.test(document.getElementById('folder-answer').textContent)&&document.getElementById('folder-path').value==='BGP/mine'&&!document.querySelector('#folder-foot [data-folder-primary][disabled]')")
        s.equal('the result line', s.text('#folder-result').replace('\n', ' '), 'The state is saved in Nested-Labs › BGP/mine')
        s.check('New folder… is enabled', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
    with s.state('a lab state is saved and waits for upload like any save', '5.5'):
        s.click('#folder-foot [data-folder-action="save"]')
        s.wait_toast(r'^State Mine saved in BGP/mine\.$')
        s.wait_chip(r'^1 save to upload$', timeout=40000)
        open_chip(s)
        expect(p.locator('#save-upload')).to_be_enabled(timeout=20000)
        s.equal('the same upload sentence as any save', s.text('#save-changes'), 'This is the first save here: 4 devices, the topology and the map.')
        s.equal('its destination', s.text('#save-to'), 'To: Nested-Labs › BGP/mine')
        s.equal('the lab’s own save location did not change', place_of(s, 'restore-square'), 'Nested-Labs:BGP')
    upload_now(s)
    close_panels(s)
    toast_gone(s)
    with s.state('the new state is listed under Lab states by its name', '5.5, 5.4 step 1'):
        s.click('#load-button')
        expect(p.locator('#load-panel-body .save-list').first).to_be_visible(timeout=20000)
        names = [x.split('\n')[0] for x in p.locator('#load-panel-body .save-list').nth(1).locator('li .save-item > span:first-child').all_inner_texts()]
        s.check('Mine is a lab state', 'Mine' in names, names)
    close_panels(s)
    with s.state('a name that exists: one question, Replace it or Use another name', '5.5'):
        s.click('#save-chip')
        s.click('#save-as-state')
        expect(p.locator('#state-name')).to_be_visible(timeout=20000)
        s.click('.folder-names [data-state-name="start"]')
        s.wait_js("!/Checking/.test(document.getElementById('folder-answer').textContent)&&document.getElementById('folder-path').value==='BGP/start'")
        s.equal('the question', s.text('#folder-answer'), '“Start” already exists here.')
        s.equal('its answers', foot_buttons(s), ['Cancel', 'Replace it', 'Use another name'])
    with s.state('Replace it: the state is written again, complete', '5.5'):
        expect(p.locator('#folder-foot [data-folder-choice="take"]')).to_be_enabled(timeout=20000)
        s.click('#folder-foot [data-folder-choice="take"]')
        s.wait_toast(r'^State Start saved in BGP/start\.$')
        s.wait_chip(r'^1 save to upload$', timeout=40000)
        s.check('saved', True)
    upload_now(s)
    close_panels(s)
    toast_gone(s)
    with s.state('the lab’s own folder: the state goes into a folder inside it, and the drawer says so', '5.5'):
        s.click('#save-chip')
        s.click('#save-as-state')
        expect(p.locator('#state-name')).to_be_visible(timeout=20000)
        s.fill('#state-name', 'Inside')
        s.wait_js("document.getElementById('folder-path').value==='BGP/Inside'&&!/Checking/.test(document.getElementById('folder-answer').textContent)")
        s.equal('offered beside the lab’s own saves', s.text('#folder-result').replace('\n', ' '), 'The state is saved in Nested-Labs › BGP/Inside')
        s.fill('#folder-path', 'BGP')
        s.wait_js("(()=>{const r=document.getElementById('folder-result');return !!r&&/BGP\\/Inside/.test(r.textContent)&&!/Checking/.test(document.getElementById('folder-answer').textContent);})()", what='the answer for the lab’s own folder')
        s.equal('the lab’s own folder itself is never the state’s folder: the result line', s.text('#folder-result').replace('\n', ' '), 'The state is saved in Nested-Labs › BGP/Inside')
        s.wait_js("/so the state is saved in/.test(document.getElementById('folder-answer').textContent)", what='the sentence for the lab’s own folder')
        s.equal('the drawer says so', s.text('#folder-answer').strip(), 'BGP is a lab’s save folder, so the state is saved in BGP/Inside.')
    s.click('#folder-foot [data-folder-action="cancel"]', count=False)
    close_panels(s)
    with s.state('All versions offers Save as a lab state… too', '5.5, 5.7'):
        s.click('#save-chip')
        s.click('#save-all')
        expect(p.locator('#save-drawer-content [data-save-action="state"]')).to_be_visible(timeout=20000)
        s.click('#save-drawer-content [data-save-action="state"]')
        expect(p.locator('#state-name')).to_be_visible(timeout=20000)
        s.check('with Back to All versions', s.visible('#save-drawer-back'))
    close_panels(s)
    s.open_lab('square-fresh')
    with s.state('a lab without a save location: the chooser asks which repository', '5.5'):
        s.click('#save-chip')
        expect(p.locator('#save-panel')).to_be_visible(timeout=10000)
        if s.visible('#save-as-state'):
            s.click('#save-as-state')
            expect(p.locator('#state-name')).to_be_visible(timeout=20000)
            expect(p.locator('#folder-repo option').first).to_be_attached(timeout=20000)
            offered = p.locator('#folder-repo option').all_inner_texts()
            s.check('the repositories of the VM are offered', len(offered) >= 2 and 'Archtop-Lab' in offered and 'Nested-Labs' in offered, offered)
            s.fill('#state-name', 'mine')
            s.wait_js("!/Checking/.test(document.getElementById('folder-answer').textContent)&&/mine$/.test(document.getElementById('folder-path').value)")
            chosen = p.locator('#folder-repo option:checked').inner_text()
            s.match('the result line names the repository and a folder', s.text('#folder-result').replace('\n', ' '), r'^The state is saved in %s › .*mine$' % re.escape(chosen))
            s.check('the lab still has no save location', place_of(s, 'square-fresh') is None)
        else:
            s.check('Save as a lab state… is offered to a lab that never saved', False, panel_text(s))


def scenario_drawers(s):
    """PROMPT 5.7 and 5.8: All versions and Save settings."""
    p = s.page
    s.switch(capture_seconds=1, restore_capture_seconds=1)
    s.open_lab('restore-square')
    with s.state('All versions', '5.7'):
        s.click('#save-chip')
        s.click('#save-all')
        expect(p.locator('#save-drawer-content .save-list').first).to_be_visible(timeout=20000)
        s.equal('title', s.text('#save-drawer-title'), 'All versions')
        s.equal('the groups', [h.lower() for h in p.locator('#save-drawer-content h3.save-heading').all_inner_texts()], ['your saves', 'checkpoints', 'starting point', 'lab states'])
        folds = p.locator('#save-drawer-content > details > summary').all_inner_texts()
        s.check('other labs and everything else are folded', any(f.startswith('Other labs in this repository') for f in folds), folds)
        s.equal('it ends with Full history… and Browse the repository…', p.locator('#save-drawer-content .save-foot button').all_inner_texts(), ['Full history…', 'Browse the repository…'])
    with s.state('All versions: a lab state opens in place', '5.7'):
        row = open_row(s, 'Broken')
        s.equal('its actions', row.locator('button[data-save-action]').all_inner_texts(), ['Load this state…', 'See what’s different', 'View files', 'Download ZIP'])
    with s.state('All versions: your own save also offers Keep as a checkpoint and Use as starting point…', '5.7'):
        row = open_row(s, 'Interface descriptions cleaned up')
        actions = row.locator('button[data-save-action]').all_inner_texts()
        s.check('the actions (the newest save has nothing to be different from)', all(a in actions for a in ['Load this state…', 'View files', 'Download ZIP', 'Keep as a checkpoint', 'Use as starting point…']), actions)
    with s.state('All versions: Use as starting point… with its replace review', '5.7'):
        row = open_row(s, 'Interface descriptions cleaned up') if 'open' not in (p.locator('#save-drawer-content .save-list > li.open').first.get_attribute('class') or '') else p.locator('#save-drawer-content .save-list > li.open').first
        s.click(row.locator('[data-save-action="baseline"]'))
        p.wait_for_timeout(1500)
        text = drawer_text(s)
        s.check('it asks before the starting point is replaced', bool(re.search(r'starting point', text, re.I)) and (row.locator('[data-save-action="baseline-confirm"]').count() == 1 or 'Replace' in text), text[:600])
    with s.state('All versions: a design export is view and download only', '5.7'):
        row = open_row(s, 'plan-sept')
        s.check('Load this state… is disabled with the reason', row.locator('[data-save-action="load"]').is_disabled() and 'Design plan: view and download only' in row.inner_text(), row.inner_text())
    with s.state('All versions: View files (topology and map included)', '5.7'):
        row = open_row(s, 'Broken')
        s.click(row.locator('[data-save-action="files"]'))
        expect(p.locator('#save-drawer-content details').first).to_be_visible(timeout=15000)
        s.equal('title, with Back', [s.text('#save-drawer-title'), s.visible('#save-drawer-back')], ['View files', True])
        s.check('devices, the topology file and the map', 'Topology file' in drawer_text(s) and 'Map' in drawer_text(s) and 'ceos' in drawer_text(s), drawer_text(s)[:300])
    s.click('#save-drawer-back', count=False)
    expect(p.locator('#save-drawer-content .save-list').first).to_be_visible(timeout=20000)
    with s.state('All versions: See what’s different (saved against saved)', '5.7'):
        row = open_row(s, 'Broken')
        s.click(row.locator('[data-save-action="different"]'))
        expect(p.locator('#save-drawer-title')).to_have_text('Different from your latest save', timeout=15000)
        expect(p.locator('#save-drawer-content .diff-file, #save-drawer-content .save-note').first).to_be_visible(timeout=15000)
        s.check('with Back', s.visible('#save-drawer-back'))
    s.click('#save-drawer-back', count=False)
    expect(p.locator('#save-drawer-content .save-list').first).to_be_visible(timeout=20000)
    with s.state('All versions: Download ZIP', '5.7'):
        row = open_row(s, 'Broken')
        s.note('click Download ZIP')
        with p.expect_download() as download:
            row.locator('[data-save-action="zip"]').click()
        s.check('a ZIP file is downloaded', download.value.suggested_filename.endswith('.zip'), download.value.suggested_filename)
    with s.state('All versions: Full history…', '5.7'):
        s.click(p.locator('#save-drawer-content .save-foot button', has_text='Full history…'))
        p.wait_for_timeout(1500)
        shown = s.visible('#git-history-dialog') or s.text('#save-drawer-title') != 'All versions'
        s.check('the full history opens', shown, s.text('#save-drawer-title'))
        text = s.text('#git-history-dialog') if s.visible('#git-history-dialog') else drawer_text(s)
        s.check('it lists commits', len(text) > 40, text[:200])
    if s.visible('#git-history-dialog'):
        p.locator('#git-history-dialog .close, #git-history-dialog [aria-label="Close"]').first.click()
    elif s.visible('#save-drawer-back'):
        s.click('#save-drawer-back', count=False)
    with s.state('All versions: Browse the repository…', '5.7'):
        if not s.visible('#save-drawer'):
            s.click('#save-chip', count=False)
            s.click('#save-all', count=False)
        expect(p.locator('#save-drawer-content .save-foot button').first).to_be_visible(timeout=20000)
        s.click(p.locator('#save-drawer-content .save-foot button', has_text='Browse the repository…'))
        expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
        s.check('the repository as a tree, with Back', s.visible('#save-drawer-back'))
    with s.state('All versions: Load this state… ends in the Load confirmation', '5.7, 5.4 parity gate'):
        s.click('#save-drawer-back', count=False)
        expect(p.locator('#save-drawer-content .save-list').first).to_be_visible(timeout=20000)
        row = open_row(s, 'Broken')
        s.click(row.locator('[data-save-action="load"]'))
        expect(p.locator('#load-run')).to_be_visible(timeout=30000)
        s.check('the drawer closed and the confirmation shows', not s.visible('#save-drawer') and p.locator('#load-panel-body .save-state').inner_text() == 'Load Broken?')
    close_panels(s)
    with s.state('Save settings', '5.8'):
        s.click('#save-chip')
        s.click('#save-settings')
        expect(p.locator('#save-drawer-content .save-settings')).to_be_visible(timeout=20000)
        expect(p.locator('#save-drawer-content input[name="git-node"]').first).to_be_visible(timeout=20000)
        s.equal('title', s.text('#save-drawer-title'), 'Save settings')
        text = drawer_text(s)
        for want in ['Save location', 'Change folder…', 'Use a different repository…', 'Connect by URL…', 'Disconnect this lab…', 'Save settings']:
            s.check('has ' + want, want.lower() in text.lower(), text[:300])
        ticks = p.locator('#save-drawer-content input[name="git-node"]')
        s.check('the devices included in every save, as tick boxes', ticks.count() == 4 and all(ticks.nth(i).is_checked() for i in range(4)))
        s.check('where the lab saves: repository and folder', 'Nested-Labs' in text and 'BGP' in text, text[:200])
    with s.state('Save settings: the folded Git details', '5.8'):
        s.click('#save-git-details > summary')
        s.equal('Refresh status and Update from the repository', p.locator('#save-git-details .save-row button').all_inner_texts(), ['Refresh status', 'Update from the repository'])
        s.check('the online repository is named', 'github.com' in s.text('#save-git-details'), s.text('#save-git-details')[:400])
    with s.state('Save settings: Update from the repository', '5.8, 6.5'):
        s.click('#save-git-details [data-git-repo-action="update"]')
        expect(p.locator('#git-update-dialog')).to_be_visible(timeout=10000)
        s.check('it asks first', s.visible('#git-update-confirm'))
    p.locator('#git-update-confirm').click()
    s.wait_toast(r'(?i)up to date|updated', timeout=30000)
    toast_gone(s)
    with s.state('Save settings: Change folder… opens the folder chooser', '5.8, 6.3'):
        if not s.visible('#save-drawer-content .save-settings'):
            s.click('#save-chip', count=False)
            s.click('#save-settings', count=False)
        expect(p.locator('#save-drawer-content [data-save-action="folder"]')).to_be_visible(timeout=20000)
        s.click('#save-drawer-content [data-save-action="folder"]')
        expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
        s.check('inside the drawer, with Back', s.visible('#save-drawer-back') and s.text('#save-drawer-title') == 'Where should restore-square save?')
        s.check('folders that hold saves say whose they are', bool(re.search(r'saves here|This lab|Lab state', p.locator('#folder-tree').inner_text())), p.locator('#folder-tree').inner_text()[:400])
    s.click('#save-drawer-back', count=False)
    expect(p.locator('#save-drawer-content .save-settings')).to_be_visible(timeout=20000)
    with s.state('Save settings: Use a different repository…', '5.8'):
        s.click('#save-drawer-content [data-git-repo-action="switch"]')
        expect(p.locator('#git-switch-dialog')).to_be_visible(timeout=15000)
        text = s.text('#git-switch-dialog')
        s.check('the other repositories of the VM are offered, the lab’s own is not', 'Archtop-Lab' in p.locator('#git-switch-id').inner_text() and 'Nested-Labs' not in p.locator('#git-switch-id').inner_text(), p.locator('#git-switch-id').inner_text())
        s.check('no word of the removed tab', not re.search(r'Progress|Save location card', text), text[:300])
    with s.state('Save settings: a different repository leads to the folder chooser for it', '5.8, 6.3'):
        p.locator('#git-switch-id').select_option(label='Archtop-Lab')
        s.click('#git-switch-choose')
        expect(p.locator('#folder-tree')).to_be_visible(timeout=20000)
        s.equal('the chooser shows that repository', p.locator('#folder-repo option:checked').inner_text(), 'Archtop-Lab')
        s.check('nothing was changed yet', place_of(s, 'restore-square') == 'Nested-Labs:BGP', place_of(s, 'restore-square'))
    s.click('#folder-foot [data-folder-action="cancel"]', count=False)
    close_panels(s)
    with s.state('Save settings: Connect by URL…', '5.8'):
        s.click('#save-chip')
        s.click('#save-settings')
        expect(p.locator('#save-drawer-content [data-git-repo-action="connect"]')).to_be_visible(timeout=20000)
        s.click('#save-drawer-content [data-git-repo-action="connect"]')
        expect(p.locator('#folder-url')).to_be_visible(timeout=20000)
        s.equal('the primary button', foot_buttons(s)[-1], 'Connect and save here')
        s.check('Back to the settings', s.visible('#save-drawer-back'))
    close_panels(s)
    with s.state('Save settings: a device left out', '5.8'):
        s.click('#save-chip')
        s.click('#save-settings')
        expect(p.locator('#save-drawer-content input[name="git-node"]').first).to_be_visible(timeout=20000)
        s.note('untick the fourth device')
        p.locator('#save-drawer-content input[name="git-node"]').nth(3).uncheck()
        s.check('the sentence about the device left out', 'is no longer included. Its saved file is removed with the next save; older versions keep it.' in drawer_text(s), drawer_text(s)[:600])
        s.click('#save-drawer-content [data-save-action="save-settings"]')
        s.wait_toast(r'^Save settings updated\.$')
        wait_until(lambda: len([l for l in s.api_state()['labs'] if l['name'] == 'restore-square'][0]['git_binding']['node_names']) == 3, what='the selection')
        s.check('the selection is saved', True)
    close_panels(s)
    s.open_lab('edge-lab')
    with s.state('Save settings: Disconnect this lab…', '5.8'):
        s.click('#save-chip')
        s.click('#save-settings')
        expect(p.locator('#save-drawer-content [data-git-repo-action="unlink"]')).to_be_visible(timeout=20000)
        s.click('#save-drawer-content [data-git-repo-action="unlink"]')
        expect(p.locator('#git-unlink-dialog')).to_be_visible(timeout=10000)
        text = s.text('#git-unlink-dialog')
        s.check('it asks first, in words without the removed tab', s.visible('#git-unlink-confirm') and not re.search(r'Progress|upload first', text), text[:400])
    with s.state('Save settings: disconnected; Save asks where to save again', '5.8, 5.9'):
        s.click('#git-unlink-confirm')
        wait_until(lambda: not [l for l in s.api_state()['labs'] if l['name'] == 'edge-lab'][0].get('git_binding'), what='the disconnect')
        s.check('the lab has no save location', place_of(s, 'edge-lab') is None)
        close_panels(s)
        p.wait_for_timeout(4500)
        s.match('the chip still names the lab’s last save (its saves stay in the repository)', s.chip(), r'^Saved ')
        s.click('#git-save-progress')
        expect(p.locator('#save-first, #save-url').first).to_be_visible(timeout=15000)
        s.check('Save shows the first-save view', s.visible('#save-first'))


def scenario_folders(s):
    """PROMPT 6.2 row by row, the three questions, New folder… at each level, 6.3 and the one refusal that is the VM's (6.5)."""
    p = s.page
    s.switch(capture_seconds=1)
    s.open_lab('shared-b')
    ref = '6.2'

    def choose(folder, registration=NESTED):
        open_chooser(s)
        repository(s, registration)
        s.note('type the folder ' + folder)
        type_folder(s, folder)
        return answer(s)

    with s.state('row 1: a folder that does not exist', ref + ' row 1'):
        s.click('#git-save-progress')
        expect(p.locator('#save-first-place-other')).to_be_visible(timeout=15000)
        text = choose('brand-new/deeper')
        s.equal('the sentence', text, 'brand-new/deeper is new. It appears in the repository with the first save.')
        s.equal('listed as New in the tree', p.locator('[data-folder="brand-new/deeper"] .git-tag.pending').inner_text(), 'New')
        s.equal('one button, Save here', foot_buttons(s), ['Cancel', 'Save here'])
    with s.state('row 1: it is created and used', ref + ' row 1'):
        press(s, '#folder-foot [data-folder-action="save"]')
        saved_here(s, 'shared-b', 'Nested-Labs:brand-new/deeper', 'a folder that does not exist')
        s.wait_chip(r'^1 save to upload$', timeout=40000)
        s.check('the first save follows the choice by itself', True)
    upload_waiting(s)
    with s.state('row 2: an existing folder with ordinary files and no saved state', ref + ' row 2'):
        text = choose('notes')
        s.equal('no question, no refusal', [text, s.visible('#folder-refused')], ['', False])
        s.equal('one button, Save here', foot_buttons(s), ['Cancel', 'Save here'])
        s.check('the line that brings the saved files along is offered', p.locator('#folder-move input').count() == 1 and s.text('#folder-move').strip() == 'Bring this lab’s saved files along')
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:notes', 'ordinary files')
    with s.state('row 3: the repository’s top level', ref + ' row 3'):
        open_chooser(s)
        s.click('#folder-tree > [data-folder=""] > .folder-row')
        s.equal('the sentence', answer(s), 'shared-b will save at the top level of Nested-Labs.')
        s.equal('one button, Save here', foot_buttons(s), ['Cancel', 'Save here'])
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:', 'the top level')
    for folder, where in [('BGP/edge/inner', 'inside'), ('BGP-beside', 'beside'), ('BGP/exercises', 'inside a lab folder, ordinary files')]:
        with s.state('row 4: a folder %s another lab’s folder (%s)' % (where, folder), ref + ' row 4'):
            choose(folder)
            s.check('no refusal', not s.visible('#folder-refused'))
            s.equal('one button, Save here: nesting is allowed', foot_buttons(s), ['Cancel', 'Save here'])
            press(s, '#folder-foot [data-folder-action="save"]')
            saved_here(s, 'shared-b', 'Nested-Labs:' + folder, folder)
    with s.state('row 5 (question 1): the very folder another lab saves to', ref + ' row 5'):
        text = choose('shared')
        s.equal('the question', text, 'shared-a saves here too.')
        s.equal('its two answers', foot_buttons(s), ['Cancel', 'Save in shared/shared-b', 'Use this folder anyway'])
        s.check('the note says what Use this folder anyway does', 'shared-a is disconnected from it' in s.text('#folder-answer-note'), s.text('#folder-answer-note'))
        s.check('the tree marks whose folder it is', 'shared-a saves here' in p.locator('#folder-tree').inner_text(), p.locator('#folder-tree').inner_text()[:500])
        s.check('New folder… is enabled while the question is asked', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
    with s.state('row 5: Save in shared/shared-b (suggested)', ref + ' row 5'):
        press(s, '#folder-foot [data-folder-choice="beside"]')
        saved_here(s, 'shared-b', 'Nested-Labs:shared/shared-b', 'question 1, beside')
        s.equal('the other lab keeps its folder', place_of(s, 'shared-a'), 'Nested-Labs:shared')
    with s.state('row 6 (question 2): a folder that holds a lab state', ref + ' row 6'):
        text = choose('BGP/start')
        s.equal('the question', text, 'This folder holds the state “Start”.')
        s.equal('its two answers', foot_buttons(s), ['Cancel', 'Save beside it in BGP/start/shared-b', 'Replace it'])
        s.check('the tree marks the state', 'Lab state: Start' in p.locator('#folder-tree').inner_text() or 'Start' in p.locator('[data-folder="BGP/start"]').inner_text(), p.locator('#folder-tree').inner_text()[:500])
        s.check('New folder… is enabled while the question is asked', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
    with s.state('row 6: Save beside it (suggested)', ref + ' row 6'):
        press(s, '#folder-foot [data-folder-choice="beside"]')
        saved_here(s, 'shared-b', 'Nested-Labs:BGP/start/shared-b', 'question 2, beside')
    with s.state('row 6: Replace it', ref + ' row 6'):
        text = choose('BGP/broken')
        s.equal('the question', text, 'This folder holds the state “Broken”.')
        press(s, '#folder-foot [data-folder-choice="take"]')
        saved_here(s, 'shared-b', 'Nested-Labs:BGP/broken', 'question 2, Replace it')
    with s.state('row 7: a folder that is part of a saved state', ref + ' row 7'):
        text = choose('shared/shared-b/checkpoints/x')
        s.match('the chooser says the lab folder above is used', text, r'^shared/shared-b/checkpoints/x is part of a saved state, so shared-b saves in shared/shared-b, the lab folder above it\.')
        s.equal('the result line shows the folder that is used', s.text('#folder-result').replace('\n', ' '), 'Saves go to Nested-Labs › shared/shared-b')
    press(s, '#folder-foot [data-folder-primary]')
    saved_here(s, 'shared-b', 'Nested-Labs:shared/shared-b', 'part of a saved state')
    with s.state('row 7: part of another lab’s saved state: said, then question 1', ref + ' row 7'):
        text = choose('BGP/latest')
        s.match('said, then the question for the folder above', text, r'^BGP/latest is part of a saved state, so shared-b saves in BGP, the lab folder above it\. restore-square saves here too\.$')
        s.check('buttons, not a refusal', foot_buttons(s)[1].startswith('Save in BGP/shared-b') and not s.visible('#folder-refused'), foot_buttons(s))
    s.click('#folder-foot [data-folder-action="cancel"]', count=False)
    with s.state('row 8: a name with characters that are not safe in a path', ref + ' row 8'):
        open_chooser(s)
        s.fill('#folder-path', 'My Lab: A/B')
        s.equal('corrected as typed', p.locator('#folder-path').input_value(), 'My-Lab-A/B')
        answer(s)
        s.equal('the result is shown', s.text('#folder-result').replace('\n', ' '), 'Saves go to Nested-Labs › My-Lab-A/B')
        s.check('no refusal', not s.visible('#folder-refused'))
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:My-Lab-A/B', 'unsafe characters')
    with s.state('row 10: a folder registered on the VM that no lab uses', ref + ' row 10'):
        open_chooser(s)
        s.check('it is not in the tree', p.locator('[data-folder="old-lab-folder"]').count() == 0)
        s.check('the words registration, prefix and overlap are nowhere in the chooser', not re.search(r'registration|prefix|overlap', p.locator('#save-drawer').inner_text(), re.I))
        s.note('type the folder old-lab-folder')
        type_folder(s, 'old-lab-folder')
        s.equal('free like any new folder', answer(s), 'old-lab-folder is new. It appears in the repository with the first save.')
    press(s, '#folder-foot [data-folder-action="save"]')
    saved_here(s, 'shared-b', 'Nested-Labs:old-lab-folder', 'a registered folder no lab uses')
    for parent, name, want, level in [('', 'top-new', 'top-new', 'at the top level'), ('BGP', 'in-lab', 'BGP/in-lab', 'inside a lab folder'), ('BGP/edge', 'in-nested', 'BGP/edge/in-nested', 'inside a nested lab folder')]:
        with s.state('New folder… ' + level, ref + ' New folder'):
            open_chooser(s)
            row = '#folder-tree > [data-folder=""] > .folder-row' if not parent else '[data-folder="%s"] > .folder-row' % parent
            if parent and p.locator(row).count() == 0:
                p.locator('[data-folder="BGP"] > .folder-row [data-folder-twist]').click()
            s.click(row)
            s.check('New folder… is enabled', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
            s.click('.folder-chooser [data-folder-action="new"]')
            s.fill('#folder-new', name)
            s.click('.folder-new [data-folder-action="new-add"]')
            expect(p.locator('[data-folder="%s"]' % want)).to_be_visible(timeout=15000)
            s.equal('the folder is made where the person is, and selected', p.locator('#folder-path').input_value(), want)
            s.equal('said as planned, never as in the repository', answer(s), want + ' is new. It appears in the repository with the first save.')
            s.check('no refusal', not s.visible('#folder-refused'))
        s.click('#folder-foot [data-folder-action="cancel"]', count=False)
    with s.state('New folder… inside a saved state: made in the lab folder above, and said so', ref + ' New folder'):
        open_chooser(s)
        s.note('type the folder BGP/start/latest')
        type_folder(s, 'BGP/start/latest')
        s.match('typing a part of a saved state: the chooser says the lab folder above is used', answer(s), r'^BGP/start/latest is part of a saved state, so shared-b saves in BGP/start, the lab folder above it\.')
        s.check('New folder… is enabled', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
        s.click('.folder-chooser [data-folder-action="new"]')
        s.fill('#folder-new', 'extra')
        s.click('.folder-new [data-folder-action="new-add"]')
        s.wait_js("document.getElementById('folder-path').value.includes('extra')")
        s.equal('the new folder is made in the lab folder above the saved state', p.locator('#folder-path').input_value(), 'BGP/start/extra')
        s.check('no refusal', not s.visible('#folder-refused'))
    s.click('#folder-foot [data-folder-action="cancel"]', count=False)
    edit = [d for d in s.fixture_state()['devices'] if d.startswith('clab-shared-b-')][0]

    def waiting_save(line):
        s.action('edit_device', device=edit, add=[line], remove=[])
        close_panels(s)
        s.click('#git-save-progress', count=False)
        s.wait_chip(r'^\d saves? to upload$', timeout=40000)
        expect(p.locator('#save-upload')).to_be_enabled(timeout=15000)
        s.click('#save-not-now', count=False)

    with s.state('row 9 (question 3): a folder change while a save waits for upload', ref + ' row 9'):
        waiting_save('interface Loopback41')
        choose('moved-1')
        s.click('#folder-foot [data-folder-action="save"]')
        expect(p.locator('#folder-foot [data-folder-pending="keep"]')).to_be_visible(timeout=15000)
        s.equal('the question', s.text('#folder-answer'), '1 save of shared-b is waiting for upload.')
        s.equal('its two answers', foot_buttons(s), ['Cancel', 'Upload it, then move', 'Move and keep that save on the VM only'])
        s.check('New folder… is enabled while the question is asked', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
        s.check('never a refusal', not s.visible('#folder-refused'))
    with s.state('row 9: Move and keep that save on the VM only', ref + ' row 9'):
        s.click('#folder-foot [data-folder-pending="keep"]')
        saved_here(s, 'shared-b', 'Nested-Labs:moved-1', 'question 3, keep')
        s.wait_chip(r'^2 saves to upload$', timeout=40000)
        s.check('the save keeps waiting and the move waits with it', True)
    upload_waiting(s)
    with s.state('row 9: Upload it, then move', ref + ' row 9'):
        waiting_save('interface Loopback42')
        choose('moved-2')
        press(s, '#folder-foot [data-folder-action="save"]')
        expect(p.locator('#folder-foot [data-folder-pending="upload"]')).to_be_enabled(timeout=20000)
        s.match('the note carries the upload sentence before the click', s.text('#folder-answer-note'), r'device changed since your last save')
        s.click('#folder-foot [data-folder-pending="upload"]')
        saved_here(s, 'shared-b', 'Nested-Labs:moved-2', 'question 3, upload')
        s.wait_chip('^Saved ', timeout=40000)
        s.check('the waiting save was uploaded before the move', all(j.get('pushed') for j in s.api_state()['git_jobs'] if j.get('lab_id') == s.lab_id('shared-b') and j.get('target') == 'latest'))
    with s.state('row 5: Use this folder anyway disconnects the other lab from the folder', ref + ' row 5'):
        choose('shared')
        press(s, '#folder-foot [data-folder-choice="take"]')
        saved_here(s, 'shared-b', 'Nested-Labs:shared', 'question 1, take')
        s.equal('the other lab is disconnected from it', place_of(s, 'shared-a'), None)
    with s.state('a placement only the VM can refuse: said like the chip, with the action that clears it', '6.5'):
        choose('refused-then-fine')
        s.switch(remote_ahead=True)
        with s.expect_status(409, r'/git/place$'):
            press(s, '#folder-foot [data-folder-action="save"]')
            expect(p.locator('#folder-refused')).to_be_visible(timeout=20000)
        s.equal('the cause in the chip’s words', s.text('#folder-refused'), 'The online copy has changes this VM does not have.')
        s.check('Update from the repository, Try again and Details; New folder… still enabled', s.visible('[data-folder-action="update"]') and s.visible('[data-folder-action="again"]') and s.visible('#folder-refused-details')
                and p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
        s.check('it is not a folder rule: no word about registrations', not re.search(r'registration|prefix|overlap', p.locator('#save-drawer').inner_text(), re.I))
    s.switch(remote_ahead=None)
    s.click('[data-folder-action="again"]', count=False)
    saved_here(s, 'shared-b', 'Nested-Labs:refused-then-fine', 'Try again after the cause is gone')
    with s.state('a large repository: every folder is offered, any typed path can be used', '6.2, 6.3'):
        open_chooser(s)
        repository(s, BIG)
        s.check('New folder… is enabled', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
        s.check('a folder beyond the 4000th file is in the tree', p.locator('[data-folder="zz-states"]').count() == 1)
        s.note('type the folder zz-states/start')
        type_folder(s, 'zz-states/start')
        s.equal('a state beyond the listing is known', answer(s), 'This folder holds the state “Start”.')
    s.click('#folder-foot [data-folder-action="cancel"]', count=False)
    close_panels(s)
    s.open_lab('square-fresh')
    with s.state('the folder chooser on a standard install (the repository registered at its top level)', '6.1, 6.3'):
        s.click('#git-save-progress')
        expect(p.locator('#save-first-place-other')).to_be_visible(timeout=15000)
        open_chooser(s)
        repository(s, 'Archtop-Lab')
        s.note('type the folder Course/latest')
        type_folder(s, 'Course/latest')
        text = answer(s)
        s.check('part of a saved state or a free folder, never a refusal', not s.visible('#folder-refused') and foot_buttons(s)[0] == 'Cancel' and len(foot_buttons(s)) >= 2, [text, foot_buttons(s)])
        s.check('New folder… is enabled', p.locator('.folder-chooser [data-folder-action="new"]').is_enabled())
        s.check('lab states are marked by name in the tree', bool(re.search(r'Lab state', p.locator('#folder-tree').inner_text())) or p.locator('#folder-tree .git-tag').count() > 0, p.locator('#folder-tree').inner_text()[:400])


def scenario_old_addresses(s):
    """PROMPT 5.11: the removed Progress tab's addresses."""
    p = s.page

    def go(lab, view):
        s.note('follow the address #lab=<%s>&view=%s' % (lab, view))
        p.goto('about:blank')
        p.goto('%s/#lab=%s&view=%s' % (s.base, s.lab_id(lab), view))
        p.wait_for_selector('#lab-content:not([hidden])')
        expect(p.locator('#title')).to_have_text(lab)

    tab = lambda: p.locator('#lab-content [data-tab][aria-selected="true"]').get_attribute('id')
    for view in ['progress', 'git']:
        with s.state('old address view=%s: the default tab with the save panel' % view, '5.11'):
            go('restore-square', view)
            expect(p.locator('#save-panel')).to_be_visible(timeout=20000)
            s.equal('the default tab', tab(), 'tab-topology')
            s.check('the save panel is open', p.locator('#save-chip').get_attribute('aria-expanded') == 'true')
            s.match('the address is the tab it resolves to', p.evaluate('location.hash'), r'^#lab=[^&]+&view=topology$')
            s.check('there is no Progress tab', p.locator('#tab-progress').count() == 0 and p.locator('#progress-view').count() == 0)
        p.keyboard.press('Escape')
        p.wait_for_timeout(6500)
        with s.state('old address view=%s: a poll does not open the panel again' % view, '5.11'):
            s.check('the panel stays closed', not s.visible('#save-panel'))
    with s.state('old address of a lab without a save location: the first-save view', '5.11, 5.9'):
        go('square-fresh', 'progress')
        expect(p.locator('#save-panel')).to_be_visible(timeout=20000)
        s.equal('the default tab', tab(), 'tab-topology')
        s.check('the first-save view', s.visible('#save-first') or s.visible('#save-first-url'), panel_text(s)[:300])
    for view, title in [('save-location', 'Save settings'), ('saved-versions', 'All versions')]:
        with s.state('old address view=%s opens %s' % (view, title), '5.11'):
            go('restore-square', view)
            expect(p.locator('#save-drawer')).to_be_visible(timeout=20000)
            expect(p.locator('#save-drawer-title')).to_have_text(title, timeout=20000)
            s.equal('the drawer and the default tab', [s.text('#save-drawer-title'), tab()], [title, 'tab-topology'])
        p.keyboard.press('Escape')
    with s.state('the old controls’ homes: every lab tab keeps the header', '5.1, 5.11'):
        go('restore-square', 'devices')
        seen = []
        for name in ['topology', 'devices', 'tools', 'advanced']:
            s.click('#tab-' + name)
            seen.append(all(s.visible(sel) for sel in ['#save-chip', '#git-save-progress', '#load-button', '#lab-actions-button']))
        s.check('chip, Save, Load and Lab actions on every tab', all(seen), seen)
        s.equal('the tabs', p.locator('#lab-content [role="tab"][data-tab]').all_inner_texts(), ['Topology', 'Devices', 'Tools', 'Advanced'])


SCENARIOS = [('saving', scenario_saving), ('cant-save', scenario_cant_save), ('first-save', scenario_first_save), ('load', scenario_load), ('load-fresh', scenario_load_fresh),
             ('lab-state', scenario_lab_state), ('drawers', scenario_drawers), ('folders', scenario_folders), ('old-addresses', scenario_old_addresses)]


def fixture_python():
    for candidate in [os.environ.get('FIXTURE_PYTHON'), str(ROOT / 'clab-backup-ui' / '.venv' / 'bin' / 'python'), os.path.expanduser('~/projects/clab-manager/clab-backup-ui/.venv/bin/python')]:
        if candidate and os.path.exists(candidate):
            return candidate
    return sys.executable


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--width', type=int, default=1440)
    parser.add_argument('--height', type=int, default=900)
    parser.add_argument('--port', type=int, default=8161)
    parser.add_argument('--out', required=True, help='the folder for the screenshots and report.json (created; keep it outside the repository unless it is evidence to commit)')
    parser.add_argument('--only', default='', help='scenario names, comma separated: ' + ', '.join(name for name, _ in SCENARIOS))
    parser.add_argument('--fixture-python', default=fixture_python(), help='the Python that runs the fixture manager (the application\'s virtual environment)')
    args = parser.parse_args()
    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    wanted = [x for x in args.only.split(',') if x]
    unknown = [x for x in wanted if x not in dict(SCENARIOS)]
    if unknown:
        parser.error('unknown scenario: ' + ', '.join(unknown))
    commit = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    report = dict(kind='fixture evidence (scripted VM helper, devices and capture; no real NOS, VM or GitHub)', viewport=[args.width, args.height], port=args.port, commit=commit,
                  started=time.strftime('%Y-%m-%dT%H:%M:%S%z'), count=0, states=[], scenarios=[])
    fixture = Fixture(args.port, args.fixture_python)
    try:
        for name, run in SCENARIOS:
            if wanted and name not in wanted:
                continue
            print('\n=== scenario %s: %s' % (name, (run.__doc__ or '').strip()), flush=True)
            entry = dict(name=name, about=(run.__doc__ or '').strip(), completed=False, reason='')
            report['scenarios'].append(entry)
            session = None
            try:
                fixture.start()
                session = Evidence('http://127.0.0.1:%d' % args.port, (args.width, args.height), report, out, name)
                run(session)
                entry['completed'] = True
            except Exception as error:   # outside a state: the fixture, the browser or a step between two states
                entry['reason'] = (str(error).strip().split('\n')[0] or type(error).__name__)[:400]
                entry['trace'] = traceback.format_exc()[-2000:]
                print('SCENARIO STOPPED %s :: %s' % (name, entry['reason']), flush=True)
            finally:
                if session is not None:
                    if session.loose or session.errors or session.failed:
                        entry['after_last_state'] = dict(steps=[x for x in session.loose if not isinstance(x, dict)], assertions=[x for x in session.loose if isinstance(x, dict)],
                                                         errors=list(session.errors) + list(session.failed))
                    try:
                        session.close()
                    except Exception:
                        pass
                fixture.stop()
    finally:
        fixture.stop()
    states = report['states']
    failed = [(st['name'], a['name'], a['note']) for st in states for a in st['assertions'] if not a['ok']]
    failed += [(sc['name'], a['name'], a['note']) for sc in report['scenarios'] for a in sc.get('after_last_state', {}).get('assertions', []) if not a['ok']]
    errors = [(st['name'], e) for st in states for e in st['errors']] + [(sc['name'], e) for sc in report['scenarios'] for e in sc.get('after_last_state', {}).get('errors', [])]
    unreached = [(st['name'], st['reason']) for st in states if not st['reached']]
    stopped = [(sc['name'], sc['reason']) for sc in report['scenarios'] if not sc['completed']]
    report['finished'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    report['summary'] = dict(states=len(states), reached=len(states) - len(unreached), assertions=sum(len(st['assertions']) for st in states), failed_assertions=len(failed),
                             errors=len(errors), not_reached=[dict(state=n, reason=r) for n, r in unreached], scenarios_stopped=[dict(scenario=n, reason=r) for n, r in stopped],
                             screenshots=sum(len(st['screenshots']) for st in states))
    with open(os.path.join(out, 'report.json'), 'w') as handle:
        json.dump(report, handle, indent=1, ensure_ascii=False)
    print('\n%d states, %d reached, %d assertions, %d failed, %d errors, %d screenshots -> %s' % (len(states), len(states) - len(unreached), report['summary']['assertions'], len(failed), len(errors),
                                                                                                report['summary']['screenshots'], out))
    for name, check, note in failed:
        print('  FAIL %s :: %s :: %s' % (name, check, note))
    for name, error in errors:
        print('  ERROR %s :: %s' % (name, error))
    for name, reason in unreached:
        print('  NOT REACHED %s :: %s' % (name, reason))
    for name, reason in stopped:
        print('  SCENARIO STOPPED %s :: %s' % (name, reason))
    return 1 if failed or errors or unreached or stopped else 0


if __name__ == '__main__':
    sys.exit(main())
