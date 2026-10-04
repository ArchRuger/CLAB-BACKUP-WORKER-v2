"""Helpers of the L2 live browser pass: the integration scripts' Session, pointed at the REAL manager.

Run with ~/pw-venv/bin/python (Playwright and paramiko are installed there). The device and GitHub helpers are l1lib's.
Evidence goes to docs/git-redesign/evidence/live/ (L2_SHOTS overrides the screenshot folder).
"""
import os
import pathlib
import re
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT / 'docs/git-redesign/evidence/live'
os.environ.setdefault('I1_SHOTS', os.environ.get('L2_SHOTS', str(EVIDENCE)))
sys.path.insert(0, str(ROOT / 'docs/git-redesign/tools/integration'))
sys.path.insert(0, str(HERE))
import common  # noqa: E402
from common import Session, expect  # noqa: E402,F401
import l1lib  # noqa: E402
from l1lib import (mgr, sh, gh, gh_tree, github, checkout, vmgit, trim, set_description, description_of, descriptions,  # noqa: E402,F401
                   show_descriptions, containers_up, cli, IFACE, DEVICES, CONTAINERS, REPO, CHECKOUT, now)

BASE = 'http://127.0.0.1:8081'
ROOT_BINDING = None


def lab_ids():
    state = mgr.call('GET', '/api/state')[1]
    return {l['name']: l['id'] for l in state['labs']}


def lab_id(name):
    return lab_ids()[name]


class Live(Session):
    """A Session on the real manager: lab ids come from /api/state, not from a fixture."""

    def __init__(self, base=BASE, viewport=(1440, 900), headed=False):
        super().__init__(base, headed, viewport)

    def lab_id(self, name):
        return lab_id(name)

    def fixture_state(self):
        raise RuntimeError('no fixture on the real manager')

    def open_lab(self, name, view='topology'):
        super().open_lab(name, view)

    def state(self):
        return self.page.request.get(self.base + '/api/state').json()

    def lab(self, name):
        return [l for l in self.state()['labs'] if l['name'] == name][0]

    def git(self, name):
        return self.page.request.get('%s/api/labs/%s/git' % (self.base, lab_id(name))).json()

    def prefix(self, name):
        binding = self.git(name).get('binding')
        return binding and binding['repository'].get('prefix')

    def jobs(self, name, **match):
        out = [j for j in self.state()['git_jobs'] if j.get('lab_id') == lab_id(name)]
        for key, want in match.items():
            out = [j for j in out if j.get(key) == want]
        return out

    def panel(self):
        return self.page.locator('#save-panel-body').inner_text()

    def say(self, line):
        print(('[%s] ' % now()) + line, flush=True)

    def waiting(self, name):
        return [j for j in self.jobs(name) if j['status'] in ('review_pending', 'committed', 'push_pending') and not j.get('pushed')]

    def open_chip(self):
        if not self.visible('#save-panel'):
            self.click('#save-chip')
        expect(self.page.locator('#save-panel')).to_be_visible()

    def close_panels(self):
        if self.visible('#save-panel') or self.visible('#load-panel') or self.visible('#save-drawer'):
            self.page.keyboard.press('Escape')
            self.page.wait_for_timeout(200)

    def wait_quiet(self, name, timeout=120):
        """No save/load/operation of the lab is running (the chip does not read Saving/Loading)."""
        end = time.time() + timeout
        while time.time() < end:
            busy = [j for j in self.state()['git_jobs'] if j['status'] in ('queued', 'capturing', 'exporting', 'pushing')]
            restore = [j for j in self.state().get('restore_jobs', []) if j['status'] not in common_end]
            if not busy and not restore:
                return True
            time.sleep(1)
        raise AssertionError('the manager stayed busy')


common_end = ('succeeded', 'partial', 'needs_attention', 'failed', 'preflight_failed', 'interrupted')


def report(session, group):
    print('\n=== %s: %d checks, %d failed' % (group, len(session.checks), len([c for c in session.checks if not c[1]])))
    for name, ok, note in session.checks:
        print(('PASS ' if ok else 'FAIL ') + name + ((' :: ' + note) if note and not ok else ''))


def move_on_map(s, node, dx=60, dy=40):
    """Moves one device on the lab's map the way a person does: Edit map, drag, Save map, back to the lab."""
    p = s.page
    s.click('#map-edit', count=False)
    p.wait_for_url('**/map-editor.html#lab=*', timeout=15000)
    p.wait_for_selector('.react-flow__node', timeout=30000)
    p.wait_for_timeout(1500)
    target = p.locator('[data-testid="rf__node-%s"]' % node)
    for attempt in range(4):
        box = target.bounding_box()
        p.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        p.mouse.down()
        p.wait_for_timeout(150)
        p.mouse.move(box['x'] + box['width'] / 2 + dx, box['y'] + box['height'] / 2 + dy, steps=20)
        p.wait_for_timeout(150)
        p.mouse.up()
        p.wait_for_timeout(600)
        if p.inner_text('#map-status') == 'Unsaved changes':
            break
    p.wait_for_function('() => document.getElementById("map-status").textContent === "Unsaved changes"', timeout=10000)
    p.wait_for_timeout(1200)   # a person does not press Save map within the drag's last frame (a first run saved the old place)
    s.click('#map-save', count=False)
    p.wait_for_function('() => document.getElementById("map-status").textContent === "Saved in the manager"', timeout=15000)
    s.click('#map-back', count=False)
    p.wait_for_selector('#lab-content:not([hidden])')
    p.wait_for_function("document.getElementById('save-chip-text').textContent.length>0")
    s.record_toasts()


def entries(s):
    return s.page.locator('#save-drawer-content details.diff-file > summary').all_inner_texts()


def changed_lines(s, limit=8):
    """The + and - lines of the open What changed drawer (the entries are opened; context lines are not copied)."""
    out = s.page.evaluate("""()=>[...document.querySelectorAll('#save-drawer-content details.diff-file')].map(d=>({name:d.querySelector('summary').textContent.trim().replace(/\\s+/g,' '),
        lines:[...d.querySelectorAll('.diff-add,.diff-del,.add,.del,[class*=add],[class*=del]')].map(e=>e.textContent.trim()).filter(Boolean).slice(0,8)}))""")
    return out
