#!/usr/bin/env python3
"""Sign-on browser check (docs/sign-on/UI.md 9.2, BUILD.md S11): sign-in, the restricted change, sign-out, the
cross-site link, an operator and the People page, at 1440, 1280, 760 and 390 px.

It starts its own fixture (docs/redesign/tools/fixture_manager.py --signed-out) on --port with a fresh
FIXTURE_DATA, signs in through the real pages with the fixture accounts it reads from a private credentials file,
writes screenshots and report.json into --out and stops the fixture. This is FIXTURE evidence: the real application
with scripted VM answers on a scratch data directory. It says nothing about a live VM, TLS or a device.

    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers clab-backup-ui/.venv/bin/python docs/sign-on/tools/check_signon.py \\
        [--port 8871] [--out DIR] [--viewport 1440 ...] [--only NAME ...]

Rules (clab-browser-qa): every wait is on a UI condition, never on network idleness or a fixed delay; the console and
every failed request are captured and fail the run unless the check declared that exact response expected (a 401 of
the sign-in page's own question, the 403 an operator is meant to get, ...); nothing secret is printed or saved.
Exit status: 0 all assertions held, 1 an assertion, console error or unexpected failed request, 2 the check itself
could not run (no fixture, no browser).
"""
import argparse
import datetime
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
FIXTURE = REPO / 'docs' / 'redesign' / 'tools' / 'fixture_manager.py'
VIEWPORTS = [(1440, 900), (1280, 800), (760, 1024), (390, 844)]
LAB_NAME = 'BGP_TheoryToPractice'
ENDED = 'Your session ended. Sign in again.'
OWN_RESET = 'Use Manager ▾ › Change password… for your own account.'
LAST_ADMIN = 'The last administrator stays.'
_TICK = threading.Event()


def pause(seconds):
    """Only the fixture's start-up polling waits on a clock; the browser is always waited on by condition."""
    _TICK.wait(seconds)


# ------------------------------------------------------------------ pure helpers (tested without a browser)

def scrub(text, secrets_list=()):
    """Replace every known secret, any session cookie value and any 'password=...' pair with ***."""
    out = str(text)
    for secret in sorted((s for s in secrets_list if s and len(s) >= 8), key=len, reverse=True):
        out = out.replace(secret, '***')
    out = re.sub(r'(clab_session|clab_capture_owner)=[^;\s"\']+', r'\1=***', out)
    out = re.sub(r'(?i)\b(password|passwd|secret)\s*[=:]\s*\S+', r'\1=***', out)
    return out


def scrub_log(text):
    """The fixture prints its random passwords; the saved copy of its log does not keep them."""
    return '\n'.join(re.sub(r'(?i)(password)\s+\S+', r'\1 ***', line) for line in str(text).splitlines()) + '\n'


def port_in_use(port):
    """True when something already listens on 127.0.0.1:<port>."""
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex(('127.0.0.1', port)) == 0


def is_fixture(base):
    """True only when the server at `base` is a fixture_manager.py: it answers its own control route with the request log
    ({requests, counts}). /api/health proves nothing, any manager answers it."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base + '/__fixture/requests', timeout=2) as response:
            found = json.loads(response.read().decode() or 'null')
    except (OSError, ValueError):
        return False
    return isinstance(found, dict) and isinstance(found.get('requests'), list) and isinstance(found.get('counts'), dict)


def throttle_sentence(text):
    return re.fullmatch(r'Too many sign-in attempts\. Try again in \d+ s\.', str(text)) is not None


def lab_address(base, lab, view):
    return f'{base}/#lab={lab}&view={view}'


def login_address(base, lab, view):
    """The gate sends the path as next; the browser keeps the fragment (UI.md 9.2, REVIEW U7)."""
    return f'{base}/login?next=%2F#lab={lab}&view={view}'


def lab_id_from_log(text, name):
    found = re.search(r'^\s*' + re.escape(name) + r': ([0-9a-f]{32})\s*$', str(text), re.M)
    return found.group(1) if found else None


def chip_expected(width):
    return width >= 1280


def argument_parser():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--port', type=int, default=8871, help='port of the fixture this check starts (default 8871)')
    parser.add_argument('--out', default='', help='directory for screenshots and report.json (default docs/sign-on/evidence/<date>)')
    parser.add_argument('--viewport', type=int, action='append', choices=[w for w, _ in VIEWPORTS], help='run only this width (repeatable; default all four)')
    parser.add_argument('--only', action='append', default=[], help='run only the scenarios whose name contains this text (repeatable)')
    parser.add_argument('--startup-timeout', type=float, default=180.0, help='seconds to wait for the fixture')
    return parser


def parse_args(argv=None):
    return argument_parser().parse_args(argv)


def chosen_viewports(args):
    wanted = set(args.viewport or [w for w, _ in VIEWPORTS])
    return [pair for pair in VIEWPORTS if pair[0] in wanted]


def evidence_dir(args):
    if args.out:
        return Path(args.out)
    return REPO / 'docs' / 'sign-on' / 'evidence' / datetime.date.today().isoformat()


class Monitor:
    """What one browser context saw go wrong. An error response is a failure unless it was declared expected as
    (status, method, path regex); the console line Chromium prints for it is expected exactly then."""

    def __init__(self, allow=()):
        self.allow = [(int(status), method.upper(), re.compile(path)) for status, method, path in allow]
        self._failed, self._expected, self._console, self._pages, self._aborted = [], [], [], [], []
        self._tolerated = set()

    @staticmethod
    def _path(url):
        return re.sub(r'^[a-z]+://[^/]+', '', str(url)).split('?')[0].split('#')[0] or '/'

    def _is_allowed(self, status, method, url):
        path = self._path(url)
        return any(s == status and m == method.upper() and rx.search(path) for s, m, rx in self.allow)

    def response(self, status, method, url):
        if status < 400:
            return
        label = f'{status} {method.upper()} {self._path(url)}'
        if self._is_allowed(status, method, url):
            self._expected.append(label)
            self._tolerated.add((status, str(url).split('?')[0]))
        else:
            self._failed.append(label)

    def request_failed(self, method, url, failure):
        label = f'{method.upper()} {self._path(url)} {failure}'
        # A fetch still in flight when the page navigates away is cancelled by the browser, not by the manager.
        (self._aborted if 'ERR_ABORTED' in str(failure) else self._failed).append(label)

    def console(self, kind, text, url=''):
        if kind != 'error':
            return
        resource = re.search(r'^Failed to load resource: .*status of (\d+)', str(text))
        if resource and (int(resource.group(1)), str(url).split('?')[0]) in self._tolerated:
            return
        self._console.append(f'{text} [{self._path(url)}]' if url else str(text))

    def page_error(self, text):
        self._pages.append(str(text))

    def findings(self):
        return {'failed_requests': list(self._failed), 'console_errors': list(self._console), 'page_errors': list(self._pages),
                'expected': list(self._expected), 'aborted': list(self._aborted)}

    def failed(self):
        return bool(self._failed or self._console or self._pages)


class Report:
    def __init__(self, secrets=()):
        self._secrets = list(secrets)
        self._viewport = ''
        self._checks, self._crashes, self._monitor, self._shots, self._notes = [], [], [], [], []
        self._env = {}

    def _s(self, text):
        return scrub(text, self._secrets)

    def add_secret(self, value):
        if value:
            self._secrets.append(value)

    def environment(self, **facts):
        self._env.update({key: self._s(value) for key, value in facts.items()})

    def begin(self, viewport):
        self._viewport = viewport

    def check(self, name, ok, detail=''):
        item = {'viewport': self._viewport, 'name': self._s(name), 'ok': bool(ok), 'detail': self._s(detail) if not ok else ''}
        self._checks.append(item)
        print(('ok   ' if ok else 'FAIL ') + f'[{self._viewport}] {item["name"]}' + (f' :: {item["detail"]}' if not ok and detail != '' else ''), flush=True)
        return bool(ok)

    def crash(self, scenario, error):
        item = {'viewport': self._viewport, 'name': self._s(f'scenario crashed: {scenario}'), 'ok': False, 'detail': self._s(f'{type(error).__name__}: {error}')[:600]}
        self._crashes.append(item)
        print(f'FAIL [{self._viewport}] {item["name"]} :: {item["detail"]}', flush=True)

    def absorb(self, scenario, monitor):
        found = monitor.findings()
        entry = {'viewport': self._viewport, 'scenario': scenario, **{key: [self._s(v) for v in values] for key, values in found.items()}}
        self._monitor.append(entry)
        for key in ('failed_requests', 'console_errors', 'page_errors'):
            for line in entry[key]:
                print(f'FAIL [{self._viewport}] {scenario}: {key[:-1].replace("_", " ")}: {line}', flush=True)

    def shot(self, name):
        self._shots.append(name)

    def note(self, text):
        self._notes.append(self._s(text))

    def failures(self):
        return [item for item in self._checks + self._crashes if not item['ok']]

    def monitor_failed(self):
        return any(entry['failed_requests'] or entry['console_errors'] or entry['page_errors'] for entry in self._monitor)

    def passed(self):
        return not self.failures() and not self.monitor_failed()

    def as_dict(self):
        views = {}
        for item in self._checks + self._crashes:
            views.setdefault(item['viewport'], []).append({key: item[key] for key in ('name', 'ok', 'detail')})
        return {
            'passed': self.passed(),
            'evidence': 'FIXTURE evidence: the real application on a scratch FIXTURE_DATA with scripted VM answers, driven in Chromium. Not a VM, not TLS, not a device.',
            'environment': dict(self._env),
            'notes': list(self._notes),
            'counts': {'checks': len(self._checks), 'failed': len(self.failures()), 'screenshots': len(self._shots)},
            'viewports': views,
            'failures': [{key: item[key] for key in ('viewport', 'name', 'detail')} for item in self.failures()],
            'monitor': self._monitor,
            'screenshots': list(self._shots),
        }

    def write(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / 'report.json'
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as handle:
            json.dump(self.as_dict(), handle, indent=2)
            handle.write('\n')
        os.chmod(path, 0o600)
        return path


# ------------------------------------------------------------------ the fixture process

class Fixture:
    """fixture_manager.py --signed-out on its own port, scratch data and a private credentials file."""

    def __init__(self, port):
        self.port = port
        self.base = f'http://127.0.0.1:{port}'
        self.work = Path(tempfile.mkdtemp(prefix='check-signon-'))
        os.chmod(self.work, 0o700)
        self.data = self.work / 'data'
        self.data.mkdir()
        self.credentials_path = self.work / 'credentials.json'
        self.log_path = self.work / 'fixture.log'
        self.process = None

    def start(self, timeout):
        if port_in_use(self.port):
            raise RuntimeError(f'port {self.port} is already in use by another server; this check starts its own fixture and drives nothing else. Choose a free --port.')
        env = dict(os.environ, FIXTURE_DATA=str(self.data))
        log = open(self.log_path, 'w')
        self.process = subprocess.Popen([sys.executable, str(FIXTURE), '--port', str(self.port), '--signed-out', '--credentials-file', str(self.credentials_path)],
                                        env=env, stdout=log, stderr=subprocess.STDOUT)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        waited = 0.0
        while waited < timeout:
            if self.process.poll() is not None:
                raise RuntimeError('the fixture exited before it was ready:\n' + scrub_log(self.log_text())[-1500:])
            try:
                if opener.open(self.base + '/api/health', timeout=2).status == 200 and self.credentials_path.exists() and is_fixture(self.base):
                    return
            except OSError:
                pass
            pause(0.5)
            waited += 0.5
        raise RuntimeError(f'the fixture did not answer on {self.base} in {timeout:.0f} s')

    def log_text(self):
        try:
            return self.log_path.read_text()
        except OSError:
            return ''

    def credentials(self):
        return json.loads(self.credentials_path.read_text())

    def stop(self):
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        shutil.rmtree(self.work, ignore_errors=True)


# ------------------------------------------------------------------ browser machinery

class Env:
    """Everything a scenario needs: the browser, the accounts, and the contexts it opened (closed afterwards)."""

    def __init__(self, browser, base, admin, operator, lab, out, report):
        self.browser, self.base, self.admin, self.operator, self.lab, self.out, self.report = browser, base, admin, operator, lab, Path(out), report
        self.vp = (1440, 900)
        self.contexts, self.monitors = [], []
        self.people = {}

    @property
    def tag(self):
        return str(self.vp[0])

    def open(self, allow=()):
        context = self.browser.new_context(viewport={'width': self.vp[0], 'height': self.vp[1]})
        context.set_default_timeout(20000)
        monitor = Monitor(allow)
        context.on('response', lambda r: monitor.response(r.status, r.request.method, r.url))
        context.on('requestfailed', lambda r: monitor.request_failed(r.method, r.url, r.failure or ''))
        context.on('console', lambda m: monitor.console(m.type, m.text, (m.location or {}).get('url', '')))
        context.on('page', lambda p: p.on('pageerror', lambda e: monitor.page_error(str(e))))
        self.contexts.append(context)
        self.monitors.append(monitor)
        return context, context.new_page(), monitor

    def api_sign_in(self, context, who):
        answer = context.request.post(self.base + '/api/session', data={'username': who['name'], 'password': who['password']}, headers={'Origin': self.base})
        if answer.status != 200:
            raise RuntimeError(f'API sign-in of {who["name"]} answered HTTP {answer.status}')

    def shot(self, page, name):
        path = self.out / f'signon-{self.tag}-{name}.png'
        page.screenshot(path=str(path))
        self.report.shot(path.name)

    def check(self, name, ok, detail=''):
        return self.report.check(name, ok, detail)

    def finish_scenario(self, scenario):
        for monitor in self.monitors:
            self.report.absorb(scenario, monitor)
        for context in self.contexts:
            try:
                context.close()
            except Exception:  # noqa: BLE001 - a context that cannot close must not hide the result
                pass
        self.contexts, self.monitors = [], []


def sign_in_form(page, who, enter=False):
    page.fill('#signin-user', who['name'])
    page.fill('#signin-password', who['password'])
    if enter:
        page.press('#signin-password', 'Enter')
    else:
        page.click('#signin-submit')


def form_ready(page):
    page.wait_for_selector('#signin-form:not([hidden])')


def focused_id(page):
    return page.evaluate('() => document.activeElement && document.activeElement.id')


def no_horizontal_scroll(page):
    return page.evaluate('() => document.documentElement.scrollWidth <= window.innerWidth')


def within_viewport(page, selector, vp):
    box = page.locator(selector).bounding_box()
    return bool(box) and box['x'] >= 0 and box['y'] >= 0 and box['x'] + box['width'] <= vp[0] and box['y'] + box['height'] <= vp[1]


# ------------------------------------------------------------------ scenarios

def scenario_sign_in_and_next(env):
    """Signed-out visit of a lab and tab: /login with next and the hash; wrong password; sign-in lands back; keyboard."""
    context, page, _ = env.open(allow=[(401, 'GET', r'/api/session$'), (401, 'POST', r'/api/session$')])
    page.goto(lab_address(env.base, env.lab, 'devices'))
    form_ready(page)
    env.check('signed out: the address is /login?next=%2F with the lab and tab kept in the fragment', page.url == login_address(env.base, env.lab, 'devices'), page.url)
    env.check('the checking line is gone and the form is shown', page.locator('#signin-checking').is_hidden() and page.locator('#signin-form').is_visible())
    env.check('the card is inside the viewport', within_viewport(page, '#signin-card', env.vp), str(page.locator('#signin-card').bounding_box()))
    env.check('no horizontal scroll on the sign-in page', no_horizontal_scroll(page))
    env.check('the brand and the heading are visible', page.locator('.brand').is_visible() and page.locator('#signin-title').is_visible())
    env.check('focus is on the username field', focused_id(page) == 'signin-user', str(focused_id(page)))
    order = []
    for _ in range(3):
        page.keyboard.press('Tab')
        order.append(focused_id(page))
    env.check('Tab order: username, password, Show, Sign in', order == ['signin-password', 'signin-show', 'signin-submit'], str(order))
    env.shot(page, 'login')
    # Wrong password: the sentence, the name kept, the password emptied and focused.
    page.fill('#signin-user', env.operator['name'])
    page.fill('#signin-password', 'not-the-password-0')
    page.click('#signin-submit')
    page.wait_for_function("() => document.getElementById('signin-error').textContent !== ''")
    env.check('a wrong password says so', page.inner_text('#signin-error') == 'Wrong username or password.', page.inner_text('#signin-error'))
    env.check('the name stays, the password is empty and focused', page.input_value('#signin-user') == env.operator['name'] and page.input_value('#signin-password') == '' and focused_id(page) == 'signin-password')
    env.shot(page, 'login-error')
    sign_in_form(page, env.admin)
    page.wait_for_url(lab_address(env.base, env.lab, 'devices'))
    page.wait_for_selector('#tab-devices[aria-selected="true"]')
    env.check('signed in: back on the same lab and tab', page.url == lab_address(env.base, env.lab, 'devices'), page.url)
    page.wait_for_function("() => document.getElementById('account-chip') !== null && document.getElementById('account-chip').textContent !== ''")
    chip = page.locator('#account-chip')
    if chip_expected(env.vp[0]):
        env.check('the account chip shows the name', chip.is_visible() and chip.inner_text() == env.admin['name'], chip.inner_text())
    else:
        env.check('the account chip is hidden at this width', chip.is_hidden())
    env.check('no horizontal scroll on the application', no_horizontal_scroll(page))


def scenario_operator(env):
    """The operator: sign-in with Enter, the open redirect, the menu, the People page and Diagnostics refused."""
    context, page, _ = env.open(allow=[(401, 'GET', r'/api/session$'), (403, 'GET', r'/api/debug$')])
    page.goto(env.base + '/login?next=//example.org')
    form_ready(page)
    sign_in_form(page, env.operator, enter=True)
    page.wait_for_url(env.base + '/')
    env.check('next=//example.org is ignored: the person lands on /', page.url == env.base + '/', page.url)
    page.wait_for_function("() => document.getElementById('manager-diagnostics').hidden === true")
    page.click('#manager-button')
    page.wait_for_selector('#account-signout', state='visible')
    env.check('operator: People and sign-ins is hidden', page.locator('#account-users').is_hidden())
    env.check('operator: Diagnostics is hidden', page.locator('#manager-diagnostics').is_hidden())
    for item, label in (('vm-settings', 'VM connection'), ('manager-settings', 'Manager settings')):
        node = page.locator('#' + item)
        env.check(f'operator: {label} is disabled and says Administrators only',
                  node.is_disabled() and node.get_attribute('title') == 'Administrators only' and node.locator('.menu-reason').inner_text() == 'Administrators only',
                  f'disabled={node.is_disabled()} title={node.get_attribute("title")}')
    env.check('operator: Change password and Sign out are offered', page.locator('#account-password').is_visible() and page.locator('#account-signout').is_visible())
    env.shot(page, 'manager-menu-operator')
    # Keyboard: ArrowDown reaches the two account actions and lands only on usable items; Escape returns to the button.
    page.keyboard.press('Escape')
    page.focus('#manager-button')
    page.keyboard.press('Enter')
    page.wait_for_selector('#account-signout', state='visible')
    seen = []
    for _ in range(60):
        page.keyboard.press('ArrowDown')
        current = focused_id(page)
        seen.append(current)
        if current == 'account-signout':
            break
    env.check('keyboard: ArrowDown reaches Change password and Sign out', 'account-password' in seen and seen[-1] == 'account-signout', str(seen[-6:]))
    env.check('keyboard: it never lands on a hidden or disabled item', not any(i in seen for i in ('account-users', 'manager-diagnostics', 'vm-settings', 'manager-settings')), str(seen))
    page.keyboard.press('Escape')
    page.wait_for_function("() => document.activeElement && document.activeElement.id === 'manager-button'")
    env.check('keyboard: Escape returns focus to the Manager button', focused_id(page) == 'manager-button')
    # The administrators' pages say so.
    page.goto(env.base + '/static/users.html')
    page.wait_for_selector('#users-forbidden:not([hidden])')
    env.check('operator: the People page shows only the refusal', page.locator('#users-card').is_hidden() and page.locator('#audit-card').is_hidden())
    env.shot(page, 'users-operator')
    page.goto(env.base + '/static/debug.html')
    page.wait_for_function("() => /Administrators only/.test(document.getElementById('debug-status').textContent)")
    env.check('operator: Diagnostics says Administrators only', 'Administrators only' in page.inner_text('#debug-status'), page.inner_text('#debug-status'))
    answer = context.request.get(env.base + '/api/users')
    env.check('operator: GET /api/users is refused (403)', answer.status == 403, str(answer.status))
    answer = context.request.get(env.base + '/api/audit')
    env.check('operator: GET /api/audit is refused (403)', answer.status == 403, str(answer.status))


def scenario_throttle(env):
    """Repeated wrong passwords: the sentence, the countdown and (at 1440 and 390) its end."""
    context, page, _ = env.open(allow=[(401, 'GET', r'/api/session$'), (401, 'POST', r'/api/session$'), (429, 'POST', r'/api/session$')])
    page.goto(env.base + '/login')
    form_ready(page)
    name = 'slowdown-' + env.tag
    text = ''
    for attempt in range(1, 9):
        page.fill('#signin-user', name)
        page.fill('#signin-password', 'wrong-password-%d' % attempt)
        page.click('#signin-submit')
        page.wait_for_function("() => document.getElementById('signin-error').textContent !== ''")
        text = page.evaluate("() => document.getElementById('signin-error').textContent")
        if throttle_sentence(text):
            break
    env.check('repeated failures end in the throttle sentence (textContent)', throttle_sentence(text), text)
    first = page.inner_text('#signin-wait-said') if page.locator('#signin-wait-said').count() else ''
    page.wait_for_function("() => document.getElementById('signin-wait').textContent !== document.getElementById('signin-wait-said').textContent")
    env.check('the spoken number stays while the shown one counts down', page.evaluate("() => document.getElementById('signin-wait-said').textContent") == first)
    env.check('Sign in is disabled while it counts', page.locator('#signin-submit').is_disabled())
    env.shot(page, 'login-throttled')
    if env.vp[0] in (1440, 390):
        page.wait_for_function("() => !document.getElementById('signin-submit').disabled", timeout=60000)
        env.check('after the countdown Sign in works again, the error is empty and the reason says so',
                  page.inner_text('#signin-error') == '' and page.inner_text('#signin-reason') == 'You can sign in again.', page.inner_text('#signin-reason'))
    else:
        env.report.note('throttle countdown end (30 s) checked at 1440 and 390 only')


def scenario_people_admin(env):
    """The People page as the administrator: the own-row rules, adding a person, the audit table."""
    context, page, _ = env.open()
    env.api_sign_in(context, env.admin)
    page.goto(env.base + '/static/users.html')
    page.wait_for_selector('#users-add:not([disabled])')
    names = page.locator('#users-rows tr td:first-child').all_inner_texts()
    env.check('the page lists the administrator and the operator', env.admin['name'] in names and env.operator['name'] in names, str(names))
    own = {action: page.locator(f'#users-rows button[data-user="{env.admin["name"]}"][data-action="{action}"]') for action in ('role', 'reset', 'active')}
    env.check('own row: Reset password is disabled with the Manager menu sentence', own['reset'].is_disabled() and own['reset'].get_attribute('title') == OWN_RESET, str(own['reset'].get_attribute('title')))
    env.check('the only administrator: Deactivate and Change role are disabled with the sentence',
              own['active'].is_disabled() and own['active'].get_attribute('title') == LAST_ADMIN and own['role'].is_disabled() and own['role'].get_attribute('title') == LAST_ADMIN)
    other = [page.locator(f'#users-rows button[data-user="{env.operator["name"]}"][data-action="{action}"]') for action in ('role', 'reset', 'active')]
    env.check("the operator's three actions are enabled", all(button.is_enabled() for button in other))
    env.check('no horizontal scroll on the People page', no_horizontal_scroll(page))
    # Add a person through the dialog.
    first, second = f'pat-{env.tag}', f'sam-{env.tag}'
    pw_first, pw_second = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
    env.report.add_secret(pw_first)
    env.report.add_secret(pw_second)
    page.click('#users-add')
    page.wait_for_selector('#user-dialog[open]')
    page.fill('#user-name', first)
    page.fill('#user-password', pw_first)
    page.fill('#user-confirm', pw_first)
    page.click('#user-submit')
    page.wait_for_function("(name) => document.getElementById('toast').textContent === name + ' added.'", arg=first)
    page.wait_for_selector(f'#users-rows button[data-user="{first}"][data-action="role"]')
    env.check('add a person: the toast and the new row', page.locator(f'#users-rows button[data-user="{first}"][data-action="reset"]').is_enabled())
    env.check('the add dialog is closed and kept no password', page.locator('#user-dialog').evaluate('d => !d.open') and page.input_value('#user-password') == '')
    env.shot(page, 'users-admin')
    # A second person without the dialog, for the sign-out-from-the-change-view check.
    made = page.evaluate("""async ([name, password]) => {
        const r = await fetch('/api/users', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, role: 'operator', password})});
        return r.status;
    }""", [second, pw_second])
    env.check('a second person is created', made in (200, 201), str(made))
    env.people[env.tag] = {'first': {'name': first, 'password': pw_first}, 'second': {'name': second, 'password': pw_second}}
    # The audit table lists this run's sign-ins: the operator's failed attempt and the throttled one.
    page.click('#audit-apply')
    page.wait_for_function("() => /events? shown/.test(document.getElementById('audit-status').textContent)")
    rows = page.locator('#audit-rows tr').evaluate_all("rows => rows.map(r => [...r.children].map(c => c.textContent))")
    failed = [r for r in rows if len(r) == 6 and r[1] == env.operator['name'] and r[2] == 'Sign-in attempt' and r[3] == 'Failed']
    throttled = [r for r in rows if len(r) == 6 and r[3] == 'Throttled']
    added = [r for r in rows if len(r) == 6 and r[2] == 'Person added' and r[5].endswith('for ' + first)]
    env.check("the audit table shows the operator's failed sign-in", bool(failed), f'{len(rows)} rows')
    env.check('the audit table shows a throttled row', bool(throttled), f'{len(rows)} rows')
    env.check('the audit table shows the person just added', bool(added), f'{len(rows)} rows')


def scenario_forced_change(env):
    """A person with an administrator-set password: the change view on the sign-in page, its rules, its Sign out."""
    people = env.people.get(env.tag)
    if not people:
        raise RuntimeError('the People scenario did not create the people this one needs')
    # (1) change the password and land on next.
    context, page, _ = env.open(allow=[(401, 'GET', r'/api/session$')])
    posts = []
    context.on('request', lambda r: posts.append(r.url) if r.method == 'POST' and r.url.endswith('/api/session/password') else None)
    page.goto(env.base + '/')
    form_ready(page)
    sign_in_form(page, people['first'])
    page.wait_for_selector('#signin-change:not([hidden])')
    env.check('forced change: the change view is shown without a Current password field', page.locator('#change-current-field').is_hidden() and page.locator('#signin-card').is_hidden())
    env.shot(page, 'login-change')
    page.fill('#change-new', 'short')
    page.fill('#change-confirm', 'short')
    page.click('#change-submit')
    page.wait_for_function("() => document.getElementById('change-error').textContent !== ''")
    env.check('a weak password gets its sentence and no request', page.inner_text('#change-error') == 'Use at least 12 characters.' and not posts, f'{page.inner_text("#change-error")!r} posts={len(posts)}')
    fresh = secrets.token_urlsafe(18)
    env.report.add_secret(fresh)
    page.fill('#change-new', fresh)
    page.fill('#change-confirm', fresh)
    page.click('#change-submit')
    page.wait_for_url(env.base + '/')
    page.wait_for_selector('#manager-button', state='visible')
    env.check('a good password lands on next and Home renders', page.url == env.base + '/' and page.locator('#manager-button').is_visible(), page.url)
    state = context.request.get(env.base + '/api/state')
    env.check('GET /api/state is 200 after the change', state.status == 200, str(state.status))
    # (2) a restricted session: the gate's answers, the Current password field after a reload, Sign out.
    context, page, _ = env.open(allow=[(401, 'GET', r'/api/session$')])
    page.goto(env.base + '/')
    form_ready(page)
    sign_in_form(page, people['second'])
    page.wait_for_selector('#signin-change:not([hidden])')
    plain = context.request.get(env.base + '/static/style.css', max_redirects=0)
    body = {}
    try:
        body = plain.json()
    except Exception:  # noqa: BLE001
        pass
    env.check('restricted session: a non-HTML request is 403 password_change_required', plain.status == 403 and body.get('detail', {}).get('code') == 'password_change_required', f'{plain.status} {body}')
    for path, expected in (('/static/style.css', '/login?change=1&next=%2Fstatic%2Fstyle.css'), ('/', '/login?change=1&next=%2F')):
        nav = context.request.get(env.base + path, max_redirects=0, headers={'Accept': 'text/html'})
        where = (nav.headers.get('location') or '').replace(env.base, '')
        env.check(f'restricted session: a navigation to {path} is 302 {expected}', nav.status == 302 and where == expected, f'{nav.status} {where}')
    page.goto(env.base + '/login')
    page.wait_for_selector('#signin-change:not([hidden])')
    page.wait_for_selector('#change-current-field:not([hidden])')
    env.check('reloading /login as a restricted session shows the Current password field', page.locator('#change-current').is_visible())
    page.click('#change-signout')
    form_ready(page)
    after = context.request.get(env.base + '/api/session')
    env.check('Sign out from the change view returns to the form and ends the session', page.locator('#signin-form').is_visible() and after.status == 401, str(after.status))
    env.check('the change view kept nothing the person typed', page.input_value('#signin-password') == '' and page.input_value('#change-new') == '')


def scenario_cross_site(env):
    """Arrival from another site with a live session: Strict cookie not sent, /login checks, then moves on to next."""
    context, page, _ = env.open()
    env.api_sign_in(context, env.admin)
    target = lab_address(env.base, env.lab, 'devices')
    context.add_init_script("""(() => {
        if (location.pathname !== '/login') return;
        try { sessionStorage.setItem('loginSeen', '1'); } catch (e) {}
        document.addEventListener('DOMContentLoaded', () => {
            const form = document.getElementById('signin-form');
            const note = () => { if (!form.hidden) { try { sessionStorage.setItem('formShown', '1'); } catch (e) {} } };
            note();
            new MutationObserver(note).observe(form, {attributes: true, attributeFilter: ['hidden']});
        });
    })();""")
    context.route('http://other-site.test/**', lambda route: route.fulfill(status=200, content_type='text/html', body=f'<!doctype html><title>elsewhere</title><a id="go" href="{target}">open the manager</a>'))
    page.goto('http://other-site.test/')
    page.click('#go')
    page.wait_for_url(target)
    env.check('cross-site arrival: the person ends on the lab and tab they asked for', page.url == target, page.url)
    page.wait_for_selector('#tab-devices[aria-selected="true"]')
    seen = page.evaluate("() => [sessionStorage.getItem('loginSeen'), sessionStorage.getItem('formShown')]")
    env.check('the gate sent the browser through /login (Strict cookie not sent)', seen[0] == '1', str(seen))
    env.check('the sign-in form was never shown', seen[1] is None, str(seen))


def scenario_sign_out(env):
    """Sign out: back on /login with no next, the session gone, and Back shows nothing of the application."""
    context, page, _ = env.open(allow=[(401, 'GET', r'/api/session$'), (401, 'GET', r'/api/'), (401, 'POST', r'/api/')])
    env.api_sign_in(context, env.admin)
    page.goto(env.base + '/static/users.html')
    page.wait_for_selector('#users-add:not([disabled])')
    page.click('.workspace-back')
    page.wait_for_url(env.base + '/')
    page.wait_for_selector('#manager-button', state='visible')
    cleared = []
    page.on('response', lambda r: cleared.append(r.all_headers().get('set-cookie', '')) if r.request.method == 'DELETE' and r.url.endswith('/api/session') else None)
    page.click('#manager-button')
    page.click('#account-signout')
    page.wait_for_url(env.base + '/login')
    form_ready(page)
    env.check('signed out: /login with no next parameter and the form shown', page.url == env.base + '/login' and page.locator('#signin-form').is_visible(), page.url)
    state = context.request.get(env.base + '/api/state')
    env.check('GET /api/state answers 401 after sign-out', state.status == 401, str(state.status))
    env.check('the sign-out response cleared the session cookie', bool(cleared) and 'clab_session' in cleared[0] and 'clab_capture_owner' in cleared[0], 'cleared=%d' % len(cleared))
    env.shot(page, 'signed-out')
    page.go_back()
    page.wait_for_url(re.compile(r'/login'))
    shown = page.evaluate("() => ({labs: document.querySelectorAll('article.lab-card').length, chip: !!(document.getElementById('account-chip') && !document.getElementById('account-chip').hidden), rows: document.querySelectorAll('#users-rows tr').length})")
    env.check('Back from the sign-in page shows nothing of the application', shown == {'labs': 0, 'chip': False, 'rows': 0} and '/login' in page.url, f'{shown} {page.url}')


SCENARIOS = [
    ('sign-in and next', scenario_sign_in_and_next),
    ('operator', scenario_operator),
    ('throttle', scenario_throttle),
    ('people (administrator)', scenario_people_admin),
    ('forced password change', scenario_forced_change),
    ('cross-site arrival', scenario_cross_site),
    ('sign-out', scenario_sign_out),
]


def application_commit():
    try:
        head = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True, timeout=20).stdout.strip()
        dirty = subprocess.run(['git', '-C', str(REPO), 'status', '--porcelain', '--', 'clab-backup-ui/app'], capture_output=True, text=True, timeout=20).stdout.strip()
        return head + (' (app/ has uncommitted changes)' if dirty else '')
    except (OSError, subprocess.SubprocessError):
        return 'unknown'


def main(argv=None):
    args = parse_args(argv)
    out = evidence_dir(args)
    out.mkdir(parents=True, exist_ok=True)
    report = Report()
    fixture = Fixture(args.port)
    previous = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        try:
            fixture.start(args.startup_timeout)
        except (RuntimeError, OSError) as error:
            print('check_signon: ' + scrub(str(error)), file=sys.stderr)
            return 2
        credentials = fixture.credentials()
        admin, operator = credentials['admin'], credentials['operator']
        for who in (admin, operator):
            report.add_secret(who['password'])
        lab = lab_id_from_log(fixture.log_text(), LAB_NAME)
        if not lab:
            print(f'check_signon: the fixture log does not list the lab {LAB_NAME}', file=sys.stderr)
            return 2
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            print('check_signon: Playwright is not installed for this Python (use clab-backup-ui/.venv/bin/python)', file=sys.stderr)
            return 2
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Exception as error:  # noqa: BLE001
                print('check_signon: Chromium did not start (set PLAYWRIGHT_BROWSERS_PATH): ' + scrub(str(error))[:300], file=sys.stderr)
                return 2
            report.environment(browser='Chromium ' + browser.version, application_commit=application_commit(), base=fixture.base, port=str(args.port),
                               date=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), python=sys.version.split()[0])
            for vp in chosen_viewports(args):
                label = f'{vp[0]}x{vp[1]}'
                report.begin(label)
                print(f'== {label}', flush=True)
                env = Env(browser, fixture.base, admin, operator, lab, out, report)
                env.vp = vp
                for name, scenario in SCENARIOS:
                    if args.only and not any(part in name for part in args.only):
                        continue
                    try:
                        scenario(env)
                    except Exception as error:  # noqa: BLE001 - one scenario failing must not hide the others
                        report.crash(name, error)
                    finally:
                        env.finish_scenario(name)
            browser.close()
        (out / 'fixture.log').write_text(scrub_log(fixture.log_text()))
        path = report.write(out)
        data = report.as_dict()
        print(f"check_signon: {data['counts']['checks']} checks, {data['counts']['failed']} failed, {len(report.as_dict()['monitor'])} monitored browser contexts; report {path}", flush=True)
        if not report.passed():
            print('check_signon: FAILED', file=sys.stderr)
            return 1
        print('check_signon: all assertions held (fixture evidence)')
        return 0
    except KeyboardInterrupt:
        print('check_signon: interrupted', file=sys.stderr)
        return 130
    finally:
        signal.signal(signal.SIGTERM, previous)
        fixture.stop()


if __name__ == '__main__':
    sys.exit(main())
