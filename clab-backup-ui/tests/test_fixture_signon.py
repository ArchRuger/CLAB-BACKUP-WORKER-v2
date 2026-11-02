"""The browser fixture under sign-on (sign-on REVIEW R15, R21; DESIGN 13.2; BUILD.md S11).

`docs/redesign/tools/fixture_manager.py` is started as a real process on a scratch data directory, as the
Playwright checks start it, in its three modes: signed in as the fixture admin (default), `--signed-out`,
and `--role operator`. The credentials it prints are random per run and are read back from the file named by
`--credentials-file`. Nothing here touches live data and nothing is added to `app/`.

Needs the application's virtual environment (FastAPI), so it is a venv test, not one of the stdlib deploy tests.
"""
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT/'docs'/'redesign'/'tools'/'fixture_manager.py'
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Running:
    """One fixture process: its port, its credentials and its printed output."""
    def __init__(self, *flags):
        self.dir = tempfile.TemporaryDirectory()
        self.port = free_port()
        self.base = f'http://127.0.0.1:{self.port}'
        self.credentials_path = Path(self.dir.name)/'credentials.json'
        self.output_path = Path(self.dir.name)/'output.txt'
        env = dict(os.environ, FIXTURE_DATA=str(Path(self.dir.name)/'data'), PYTHONUNBUFFERED='1')
        env.pop('FIXTURE_PORT', None)
        self.output = open(self.output_path, 'wb')
        self.process = subprocess.Popen(
            [sys.executable, str(FIXTURE), '--port', str(self.port), '--credentials-file', str(self.credentials_path), *flags],
            stdout=self.output, stderr=subprocess.STDOUT, env=env, cwd=self.dir.name)
        deadline = time.time() + 120
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise AssertionError('the fixture exited early:\n' + self.text()[-3000:])
            try:
                if self.call('GET', '/api/health')[0] == 200: break
            except OSError:
                time.sleep(0.3)
        else:
            raise AssertionError('the fixture did not answer in time:\n' + self.text()[-3000:])

    def text(self):
        self.output.flush()
        return self.output_path.read_text(errors='replace')

    def credentials(self):
        return json.loads(self.credentials_path.read_text())

    def call(self, method, path, body=None, cookie=None, headers=None):
        data = json.dumps({} if body is None else body).encode() if method != 'GET' else None
        sent = {'Origin': self.base, 'Accept': 'application/json'}
        if data is not None: sent['Content-Type'] = 'application/json'
        if cookie: sent['Cookie'] = cookie
        sent.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=sent)
        try:
            with OPENER.open(request, timeout=30) as response:
                return response.status, json.loads(response.read().decode() or 'null'), response.headers
        except urllib.error.HTTPError as error:
            raw = error.read().decode()
            try: parsed = json.loads(raw or 'null')
            except ValueError: parsed = {'raw': raw[:300]}
            return error.code, parsed, error.headers

    def stop(self):
        self.process.terminate()
        try: self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait()
        self.output.close()
        self.dir.cleanup()


def cookie_of(headers):
    for value in headers.get_all('Set-Cookie') or []:
        if value.startswith('clab_session=') and not value.startswith('clab_session=;') and 'Max-Age=0' not in value:
            return value.split(';', 1)[0]
    return None


class FixtureSignOnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.running = []
        try:
            cls.default = cls.start()
            cls.out = cls.start('--signed-out')
            cls.operator = cls.start('--role', 'operator')
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def start(cls, *flags):
        running = Running(*flags)
        cls.running.append(running)
        return running

    @classmethod
    def tearDownClass(cls):
        for running in cls.running: running.stop()

    # ---- credentials ----
    def test_credentials_are_an_admin_and_an_operator_with_long_random_passwords_per_run(self):
        first, second = self.default.credentials(), self.out.credentials()
        for found in (first, second):
            self.assertEqual(found['admin']['name'], 'admin')
            self.assertEqual(found['operator']['name'], 'student')
            for key in ('admin', 'operator'):
                self.assertGreaterEqual(len(found[key]['password']), 24)
            self.assertNotEqual(found['admin']['password'], found['operator']['password'])
        self.assertNotEqual(first['admin']['password'], second['admin']['password'], 'a fixed password would repeat')
        self.assertNotEqual(first['operator']['password'], second['operator']['password'])

    def test_the_credentials_file_is_private_and_the_run_prints_the_credentials(self):
        mode = stat.S_IMODE(self.default.credentials_path.stat().st_mode)
        self.assertEqual(mode, 0o600)
        found, text = self.default.credentials(), self.default.text()
        self.assertIn(found['admin']['password'], text)
        self.assertIn(found['operator']['password'], text)
        self.assertIn('admin', text)
        self.assertIn('student', text)

    def test_no_password_is_written_into_the_repository_source(self):
        text = FIXTURE.read_text()
        for found in (self.default.credentials(), self.out.credentials()):
            for key in ('admin', 'operator'):
                self.assertNotIn(found[key]['password'], text)

    # ---- default: signed in as the fixture admin ----
    def test_default_signs_requests_in_as_the_admin_without_a_cookie(self):
        status, body, _ = self.default.call('GET', '/api/session')
        self.assertEqual(status, 200, body)
        self.assertEqual(body['user'], {'name': 'admin', 'role': 'admin', 'must_change_password': False})
        self.assertEqual(self.default.call('GET', '/api/state')[0], 200)
        self.assertEqual(self.default.call('GET', '/api/users')[0], 200)

    def test_default_serves_the_application_page_instead_of_the_sign_in_redirect(self):
        request = urllib.request.Request(self.default.base + '/', headers={'Accept': 'text/html'})
        with OPENER.open(request, timeout=30) as response:
            self.assertEqual(response.status, 200)
            self.assertIn('text/html', response.headers['Content-Type'])
            self.assertEqual(response.geturl(), self.default.base + '/')

    def test_a_request_that_carries_its_own_session_cookie_is_left_alone(self):
        found = self.out.credentials()['operator']
        status, body, headers = self.out.call('POST', '/api/session', {'username': found['name'], 'password': found['password']})
        self.assertEqual(status, 200, body)
        cookie = cookie_of(headers)
        self.assertIsNotNone(cookie)
        # The default fixture adds its cookie only when the request has none: a foreign (unknown) cookie stays
        # the request's own and is therefore signed out, which proves the wrapper did not overwrite it.
        status, body, _ = self.default.call('GET', '/api/session', cookie='clab_session=not-a-session')
        self.assertEqual(status, 401, body)

    # ---- --signed-out ----
    def test_signed_out_leaves_requests_signed_out_and_sign_in_works_with_the_printed_credentials(self):
        self.assertEqual(self.out.call('GET', '/api/state')[0], 401)
        self.assertEqual(self.out.call('GET', '/api/session')[0], 401)
        found = self.out.credentials()
        status, body, headers = self.out.call('POST', '/api/session', {'username': 'admin', 'password': found['admin']['password']})
        self.assertEqual(status, 200, body)
        self.assertEqual(body['user']['role'], 'admin')
        cookie = cookie_of(headers)
        self.assertIsNotNone(cookie)
        self.assertEqual(self.out.call('GET', '/api/state', cookie=cookie)[0], 200)

    def test_the_operator_signs_in_with_the_printed_credentials_without_a_forced_change(self):
        found = self.out.credentials()['operator']
        status, body, headers = self.out.call('POST', '/api/session', {'username': found['name'], 'password': found['password']})
        self.assertEqual(status, 200, body)
        self.assertEqual(body['user'], {'name': 'student', 'role': 'operator', 'must_change_password': False})
        self.assertEqual(self.out.call('GET', '/api/users', cookie=cookie_of(headers))[0], 403)

    def test_a_wrong_password_is_refused_in_signed_out_mode(self):
        status, body, _ = self.out.call('POST', '/api/session', {'username': 'admin', 'password': 'definitely not the password'})
        self.assertEqual(status, 401, body)

    # ---- --role operator ----
    def test_role_operator_signs_requests_in_as_the_operator(self):
        status, body, _ = self.operator.call('GET', '/api/session')
        self.assertEqual(status, 200, body)
        self.assertEqual(body['user'], {'name': 'student', 'role': 'operator', 'must_change_password': False})
        self.assertEqual(self.operator.call('GET', '/api/state')[0], 200)
        self.assertEqual(self.operator.call('GET', '/api/users')[0], 403)

    # ---- the control surface of the fixture ----
    def test_fixture_control_routes_answer_in_every_mode(self):
        for running in (self.default, self.out, self.operator):
            with self.subTest(base=running.base):
                self.assertEqual(running.call('GET', '/fixture/state')[0], 200)

    def test_the_expire_route_ends_the_named_users_sessions_and_nothing_else(self):
        found = self.out.credentials()
        _, _, admin_headers = self.out.call('POST', '/api/session', {'username': 'admin', 'password': found['admin']['password']})
        _, _, student_headers = self.out.call('POST', '/api/session', {'username': 'student', 'password': found['operator']['password']})
        admin_cookie, student_cookie = cookie_of(admin_headers), cookie_of(student_headers)
        # No cookie is needed for the fixture's own route.
        status, body, _ = self.out.call('POST', '/__fixture/expire', {'name': 'student'})
        self.assertEqual(status, 200, body)
        self.assertGreaterEqual(body['ended'], 1)
        self.assertEqual(self.out.call('GET', '/api/state', cookie=student_cookie)[0], 401)
        self.assertEqual(self.out.call('GET', '/api/state', cookie=admin_cookie)[0], 200)

    def test_the_expire_route_refuses_a_missing_name_and_a_get(self):
        self.assertEqual(self.out.call('POST', '/__fixture/expire', {})[0], 422)
        self.assertEqual(self.out.call('GET', '/__fixture/expire')[0], 405)

    def test_expiring_the_default_admin_signs_the_default_requests_out_until_revived(self):
        running = self.start()
        self.assertEqual(running.call('GET', '/api/state')[0], 200)
        status, body, _ = running.call('POST', '/__fixture/expire', {'name': 'admin'})
        self.assertEqual((status, body['ended'] >= 1), (200, True), body)
        self.assertEqual(running.call('GET', '/api/state')[0], 401)
        self.assertEqual(running.call('GET', '/api/state')[0], 401, 'it stays expired')
        self.assertEqual(running.call('GET', '/fixture/state')[0], 200, 'the control routes do not depend on the session')
        status, body, _ = running.call('POST', '/__fixture/revive', {'name': 'admin'})
        self.assertEqual(status, 200, body)
        self.assertEqual(running.call('GET', '/api/state')[0], 200)

    def test_a_sign_out_in_default_mode_does_not_strand_the_fixture(self):
        running = self.start()
        self.assertEqual(running.call('DELETE', '/api/session')[0], 200)
        self.assertEqual(running.call('GET', '/api/state')[0], 200, 'the next request is signed in again')

    def test_the_request_log_lists_requests_in_order_and_resets(self):
        running = self.start('--signed-out')
        self.assertEqual(running.call('POST', '/__fixture/requests/reset', {})[0], 200)
        running.call('GET', '/api/state')
        running.call('GET', '/api/session')
        status, body, _ = running.call('GET', '/__fixture/requests')
        self.assertEqual(status, 200)
        self.assertEqual(body['requests'], ['GET /api/state', 'GET /api/session'])
        self.assertEqual(body['counts'], {'GET /api/state': 1, 'GET /api/session': 1})

    # ---- nothing of this is in the application ----
    def test_app_contains_no_fixture_code(self):
        offenders = []
        for path in sorted((ROOT/'clab-backup-ui'/'app').rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.js', '.html', '.css', '.sh'):
                text = path.read_text(errors='replace')
                if '__fixture' in text or 'FIXTURE_DATA' in text: offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == '__main__':
    unittest.main()
