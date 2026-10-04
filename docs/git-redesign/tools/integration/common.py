"""Shared pieces of the integration browser scripts (fixture evidence only).

Each script drives the real page of the fixture manager (docs/redesign/tools/fixture_manager.py) in Chromium at
1440x900 and requires the page's console and page errors to be empty. A response with status 400 or above for a
request the page really made is an error too, unless the step that provokes it names it with `expect_status`.

    FIXTURE_DATA=$(mktemp -d) clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8161
    ~/pw-venv/bin/python docs/git-redesign/tools/integration/<script>.py --base http://127.0.0.1:8161
"""
import argparse
import json
import os
import re
import sys
import time
from contextlib import contextmanager

from playwright.sync_api import sync_playwright, expect  # noqa: F401  (expect is re-exported)

SHOTS = os.environ.get('I1_SHOTS', '/tmp/i1-shots')


def arguments(description=''):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--base', default='http://127.0.0.1:8161')
    parser.add_argument('--headed', action='store_true')
    return parser.parse_args()


class Session:
    """One browser page with error collection, a click counter and the fixture's control routes."""

    def __init__(self, base, headed=False, viewport=(1440, 900)):
        self.base = base.rstrip('/')
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch(headless=not headed)
        self.context = self.browser.new_context(viewport={'width': viewport[0], 'height': viewport[1]})
        self.page = self.context.new_page()
        self.errors = []
        self.allowed = []          # (status, url regex) a step expects
        self.clicks = 0
        self.typed = 0
        self.checks = []           # (name, ok, note)
        self.page.on('console', self._console)
        self.page.on('pageerror', lambda error: self.errors.append('pageerror: ' + str(error)))
        self.page.on('response', self._response)
        self.sent = []             # every request with a body the browser sent: "POST /api/… {…}"
        self.page.on('request', lambda r: self.sent.append('%s %s %s' % (r.method, r.url.replace(self.base, ''), (r.post_data or '')[:400])) if r.method != 'GET' else None)
        os.makedirs(SHOTS, exist_ok=True)

    # ---- errors ----
    def _expected(self, status, url):
        return any(status == s and re.search(pattern, url) for s, pattern in self.allowed)

    def _console(self, message):
        if message.type != 'error':
            return
        text = message.text
        location = (message.location or {}).get('url', '')
        match = re.search(r'status of (\d{3})', text)
        if match and self._expected(int(match.group(1)), location):
            return
        self.errors.append('console: ' + text + (' @ ' + location if location else ''))

    def _response(self, response):
        if response.status >= 400 and not self._expected(response.status, response.url):
            self.errors.append('http %d %s %s' % (response.status, response.request.method, response.url))

    @contextmanager
    def expect_status(self, status, pattern):
        """The step inside provokes this answer on purpose (a 409 after a save landed, a refused address)."""
        entry = (status, pattern)
        self.allowed.append(entry)
        try:
            yield
        finally:
            self.page.wait_for_timeout(150)
            self.allowed.remove(entry)

    # ---- fixture control ----
    def fixture_state(self):
        return self.page.request.get(self.base + '/fixture/state').json()

    def switch(self, **values):
        answer = self.page.request.post(self.base + '/fixture/switch', data=values)
        assert answer.ok, answer.text()
        return answer.json()

    def switch_raw(self, values):
        answer = self.page.request.post(self.base + '/fixture/switch', data=values)
        assert answer.ok, answer.text()
        return answer.json()

    def action(self, name, **values):
        answer = self.page.request.post(self.base + '/fixture/action', data={'action': name, **values})
        assert answer.ok, answer.text()
        return answer.json()

    def lab_id(self, name):
        return self.fixture_state()['labs'][name]

    def api_state(self):
        return self.page.request.get(self.base + '/api/state').json()

    # ---- navigation and counted input ----
    def open_lab(self, name, view='topology'):
        self.page.goto('%s/#lab=%s&view=%s' % (self.base, self.lab_id(name), view))
        self.page.reload()
        self.page.wait_for_selector('#lab-content:not([hidden])')
        expect(self.page.locator('#title')).to_have_text(name)
        self.wait_js("document.getElementById('save-chip-text').textContent.length>0")
        self.record_toasts()

    def record_toasts(self):
        """Every toast the page shows is kept (a toast lasts five seconds; a check that looks later must still see it)."""
        self.page.evaluate("""(()=>{if(window.__toasts)return;window.__toasts=[];const shown=notify;
          notify=function(message){window.__toasts.push(String(message));return shown(message);};})()""")
        self._toast_mark = 0

    def calls(self, pattern=''):
        """The requests with a body the browser sent ("POST /api/labs/…/git/place {…}"), optionally filtered."""
        return [c for c in self.sent if re.search(pattern, c)]

    def toasts(self):
        """The toasts since the last wait_toast (or since the page was opened)."""
        return self.page.evaluate('window.__toasts||[]')[self._toast_mark:]

    def wait_js(self, expression, timeout=20000, what=''):
        """Waits until `expression` is true in the page (polled from here: the page's CSP allows no evaluated string in a timer)."""
        end = time.time() + timeout / 1000
        while time.time() < end:
            if self.page.evaluate(expression):
                return True
            self.page.wait_for_timeout(100)
        raise AssertionError('timed out waiting for ' + (what or expression))

    def click(self, selector, count=True, **kwargs):
        locator = self.page.locator(selector) if isinstance(selector, str) else selector
        locator.click(**kwargs)
        if count:
            self.clicks += 1

    def fill(self, selector, text):
        self.page.locator(selector).fill(text)
        self.typed += 1

    def reset_counts(self):
        self.clicks = 0
        self.typed = 0

    def chip(self):
        return self.page.locator('#save-chip-text').inner_text()

    def wait_chip(self, pattern, timeout=30000):
        expect(self.page.locator('#save-chip-text')).to_have_text(re.compile(pattern), timeout=timeout)

    def toast(self):
        toast = self.page.locator('#toast')
        return toast.inner_text() if toast.is_visible() else ''

    def wait_toast(self, pattern, timeout=30000):
        """Waits for a toast matching `pattern` among those shown since the last call, and moves the mark past it."""
        end = time.time() + timeout / 1000
        while time.time() < end:
            shown = self.page.evaluate('window.__toasts||[]')
            for index in range(self._toast_mark, len(shown)):
                if re.search(pattern, shown[index]):
                    self._toast_mark = index + 1
                    return shown[index]
            self.page.wait_for_timeout(150)
        raise AssertionError('no toast matching /%s/; shown since the last one: %r' % (pattern, self.toasts()))

    def text(self, selector):
        return self.page.locator(selector).inner_text()

    def visible(self, selector):
        locator = self.page.locator(selector)
        return locator.count() > 0 and locator.first.is_visible()

    def focused(self):
        return self.page.evaluate("(()=>{const a=document.activeElement;return a?(a.id||a.tagName+'.'+a.className):'';})()")

    def shot(self, name):
        path = os.path.join(SHOTS, name + '.png')
        self.page.screenshot(path=path)
        return path

    # ---- results ----
    def check(self, name, ok, note=''):
        self.checks.append((name, bool(ok), str(note)))
        print(('PASS ' if ok else 'FAIL ') + name + ((' :: ' + str(note)) if note and not ok else ''), flush=True)
        return bool(ok)

    def equal(self, name, got, want):
        return self.check(name, got == want, 'got %r, want %r' % (got, want))

    def match(self, name, got, pattern):
        return self.check(name, re.search(pattern, got or '') is not None, 'got %r, want /%s/' % (got, pattern))

    def no_errors(self, name):
        ok = self.check(name + ': no console, page or request errors', not self.errors, '; '.join(self.errors[:6]))
        self.errors.clear()
        return ok

    def inline_styles(self):
        """Elements with a style attribute inside the manager page (none is allowed on `/`)."""
        return self.page.evaluate("[...document.querySelectorAll('[style]')].map(e=>(e.id||e.tagName)+':'+e.getAttribute('style'))")

    def finish(self):
        self.browser.close()
        self._pw.stop()
        failed = [c for c in self.checks if not c[1]]
        print('\n%d checks, %d failed' % (len(self.checks), len(failed)))
        for name, _, note in failed:
            print('  FAIL ' + name + ' :: ' + note)
        return 1 if failed else 0


def wait_until(predicate, timeout=30, step=0.25, what='condition'):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    raise AssertionError('timed out waiting for ' + what)


def dump(value):
    return json.dumps(value, indent=1, sort_keys=True)
