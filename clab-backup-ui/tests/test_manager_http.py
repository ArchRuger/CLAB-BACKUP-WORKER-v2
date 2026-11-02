"""docs/sign-on/tools/manager_http.py: the standard-library client of the live tools (sign-on REVIEW R15; BUILD.md S11).

Standard library only (this file runs with the system python3 in CI's first group). A small HTTPS server with a
throw-away certificate (made with the `openssl` command) plays the manager: it checks the same-origin headers the
guard expects, signs in with a username and password, sets a `Secure` session cookie and refuses everything else with
the manager's 401 body. Nothing here touches a real manager and no password is printed.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('manager_http', ROOT/'docs'/'sign-on'/'tools'/'manager_http.py')
manager_http = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager_http)

USER, PASSWORD = 'tester', 'a long throw-away password for the test server'


def make_certificate(directory, name, san):
    cert, key = Path(directory)/f'{name}.pem', Path(directory)/f'{name}.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', f'/CN={name}',
                    '-addext', f'subjectAltName={san}', '-keyout', str(key), '-out', str(cert)],
                   check=True, capture_output=True)
    return cert, key


def make_chain(directory):
    """A CA-issued installation, as `setup-tls.sh --cert` installs it: root -> intermediate -> two leaves (the manager's and
    another one, `evil`, from the same CA). Returns paths: `leaf` and `evil` (certificate, key) pairs, `fullchain` (leaf +
    intermediate, the file of `tls/cert.pem`), `bundle` (leaf + intermediate + root), `evil_fullchain`."""
    d = Path(directory)
    def run(*args, **kwargs): subprocess.run(args, check=True, capture_output=True, **kwargs)
    def request(name, subject):
        run('openssl', 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-subj', f'/CN={subject}', '-keyout', str(d/f'{name}.key'), '-out', str(d/f'{name}.csr'))
    def sign(name, issuer, extensions):
        (d/f'{name}.ext').write_text(extensions)
        run('openssl', 'x509', '-req', '-in', str(d/f'{name}.csr'), '-CA', str(d/f'{issuer}.pem'), '-CAkey', str(d/f'{issuer}.key'),
            '-CAcreateserial', '-days', '2', '-extfile', str(d/f'{name}.ext'), '-out', str(d/f'{name}.pem'))
    run('openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=root', '-addext', 'basicConstraints=critical,CA:TRUE',
        '-addext', 'keyUsage=critical,keyCertSign,cRLSign', '-keyout', str(d/'root.key'), '-out', str(d/'root.pem'))
    request('inter', 'inter')
    sign('inter', 'root', 'basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n')
    for name, san in (('leaf', 'IP:127.0.0.1,DNS:manager.example'), ('evil', 'IP:127.0.0.1,DNS:evil.example')):
        request(name, name)
        sign(name, 'inter', f'basicConstraints=CA:FALSE\nsubjectAltName={san}\n')
    join = lambda out, *names: (d/out).write_text(''.join((d/f'{n}.pem').read_text() for n in names))
    join('fullchain.pem', 'leaf', 'inter'); join('bundle.pem', 'leaf', 'inter', 'root'); join('evil_fullchain.pem', 'evil', 'inter')
    join('evil_bundle.pem', 'evil', 'inter', 'root')
    return {key: d/name for key, name in (('leaf', 'leaf.pem'), ('leaf_key', 'leaf.key'), ('evil', 'evil.pem'), ('evil_key', 'evil.key'),
                                           ('fullchain', 'fullchain.pem'), ('bundle', 'bundle.pem'), ('evil_fullchain', 'evil_fullchain.pem'),
                                           ('evil_bundle', 'evil_bundle.pem'), ('root', 'root.pem'))}


class FakeManager:
    """The manager as the helper sees it: sessions in a set, a log of what arrived."""
    def __init__(self, cert, key):
        outer = self
        self.sessions, self.seen, self.signins, self.drop_next, self.always_drop = set(), [], 0, False, False

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def reply(self, status, body, headers=()):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                for key, value in headers: self.send_header(key, value)
                self.end_headers()
                self.wfile.write(raw)

            def body(self):
                size = int(self.headers.get('Content-Length', '0'))
                return self.rfile.read(size) if size else b''

            def cookie(self):
                for part in (self.headers.get('Cookie') or '').split(';'):
                    key, _, value = part.strip().partition('=')
                    if key == 'clab_session': return value
                return None

            def handle_any(self):
                raw = self.body()
                outer.seen.append(dict(method=self.command, path=self.path, origin=self.headers.get('Origin'), body=raw,
                                       content_type=self.headers.get('Content-Type'), cookie=self.cookie(), host=self.headers.get('Host')))
                if self.path == '/api/session' and self.command == 'POST':
                    data = json.loads(raw or b'{}')
                    if data.get('username') == USER and data.get('password') == PASSWORD:
                        outer.signins += 1
                        sid = 'sid%d' % outer.signins
                        outer.sessions.add(sid)
                        return self.reply(200, {'user': {'name': USER, 'role': 'admin', 'must_change_password': False}},
                                          [('Set-Cookie', f'clab_session={sid}; Path=/; HttpOnly; Secure; SameSite=Strict')])
                    return self.reply(401, {'detail': {'code': 'invalid_credentials', 'message': 'Wrong username or password.'}})
                if outer.drop_next or outer.always_drop:
                    outer.drop_next = False
                    outer.sessions.clear()
                if self.cookie() not in outer.sessions:
                    return self.reply(401, {'detail': {'code': 'signed_out', 'message': 'Sign in.'}})
                own = 'https://' + (self.headers.get('Host') or '')
                if self.headers.get('Origin', own) != own:
                    return self.reply(403, {'detail': 'Use this manager from its own browser page.'})
                if self.command != 'GET' and not raw:
                    return self.reply(413, {'detail': 'content length is required.'})
                if self.path == '/api/text':
                    return self.send_plain()
                return self.reply(200, {'path': self.path, 'method': self.command, 'echo': json.loads(raw) if raw else None})

            def send_plain(self):
                raw = b'not json at all'
                self.send_response(502); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = handle_any

            def log_message(self, *args): pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f'https://127.0.0.1:{self.server.server_address[1]}'

    def stop(self):
        self.server.shutdown(); self.server.server_close()


@unittest.skipUnless(shutil.which('openssl'), 'needs the openssl command')
class ManagerHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.cert, cls.key = make_certificate(cls.dir.name, 'good', 'IP:127.0.0.1,DNS:localhost')
        cls.named_cert, cls.named_key = make_certificate(cls.dir.name, 'named', 'DNS:manager.example.test')
        cls.other_cert, _ = make_certificate(cls.dir.name, 'other', 'IP:127.0.0.1')

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def setUp(self):
        self.fake = FakeManager(self.cert, self.key)
        self.addCleanup(self.fake.stop)
        self.env = patch.dict(os.environ, {'CLAB_USER': USER, 'CLAB_PASSWORD': PASSWORD}); self.env.start(); self.addCleanup(self.env.stop)

    def manager(self, **kwargs):
        kwargs.setdefault('pin', str(self.cert))
        return manager_http.Manager(self.fake.base, **kwargs)

    # ---- the connection ----
    def test_a_pinned_certificate_is_trusted_without_a_name_check(self):
        named = FakeManager(self.named_cert, self.named_key)
        self.addCleanup(named.stop)
        status, body = manager_http.Manager(named.base, pin=str(self.named_cert)).get('/api/state')
        self.assertEqual(status, 200, body)

    def test_a_ca_issued_chain_is_pinned_by_its_leaf_not_trusted_as_a_store(self):
        # setup-tls.sh --cert installs the full chain, leaf first. The pin is the leaf (the first certificate of the file):
        # the chain file must work, and a CA bundle that also holds the root must not trust the CA's other certificates.
        chain = make_chain(self.dir.name)
        genuine, impostor = FakeManager(chain['fullchain'], chain['leaf_key']), FakeManager(chain['evil_fullchain'], chain['evil_key'])
        self.addCleanup(genuine.stop); self.addCleanup(impostor.stop)
        self.assertEqual(manager_http.Manager(genuine.base, pin=str(chain['fullchain'])).get('/api/state')[0], 200,
                         'leaf + intermediate (no self-signed root in the file) must be accepted for its own leaf')
        self.assertEqual(manager_http.Manager(genuine.base, pin=str(chain['bundle'])).get('/api/state')[0], 200)
        for pin in (chain['fullchain'], chain['bundle']):
            with self.subTest(pin=pin.name), self.assertRaises(manager_http.ManagerError) as raised:
                manager_http.Manager(impostor.base, pin=str(pin)).get('/api/state')
            self.assertIn('certificate', str(raised.exception).lower())
        self.assertEqual(impostor.seen, [], 'no password reaches a server that is not the pinned one')
        self.assertEqual(impostor.signins, 0)

    def test_cafile_checks_the_name_but_a_matching_certificate_passes(self):
        self.assertEqual(self.manager(pin=None, cafile=str(self.cert)).get('/api/state')[0], 200)
        named = FakeManager(self.named_cert, self.named_key)
        self.addCleanup(named.stop)
        with self.assertRaises(manager_http.ManagerError) as raised:
            manager_http.Manager(named.base, cafile=str(self.named_cert)).get('/api/state')
        self.assertIn('certificate', str(raised.exception).lower())

    def test_another_certificate_than_the_pinned_one_is_refused(self):
        with self.assertRaises(manager_http.ManagerError) as raised:
            self.manager(pin=str(self.other_cert)).get('/api/state')
        self.assertIn('certificate', str(raised.exception).lower())
        self.assertEqual(self.fake.seen, [], 'nothing, not even the sign-in, is sent over an untrusted connection')

    def test_without_a_pin_or_a_cafile_the_system_store_decides_and_a_self_signed_certificate_fails(self):
        with patch.object(manager_http, 'INSTALLED_CERTIFICATE', Path(self.dir.name)/'absent.pem'):
            with self.assertRaises(manager_http.ManagerError):
                manager_http.Manager(self.fake.base).get('/api/state')

    def test_the_installed_certificate_is_the_default_pin_when_it_is_readable(self):
        with patch.object(manager_http, 'INSTALLED_CERTIFICATE', self.cert):
            self.assertEqual(manager_http.Manager(self.fake.base).get('/api/state')[0], 200)

    def test_plain_http_is_refused(self):
        for base in ('http://127.0.0.1:8081', 'ftp://x', '127.0.0.1:8443', ''):
            with self.subTest(base=base), self.assertRaises(ValueError):
                manager_http.Manager(base)

    def test_a_proxy_in_the_environment_is_not_used(self):
        env = {'https_proxy': 'http://127.0.0.1:9', 'HTTPS_PROXY': 'http://127.0.0.1:9', 'no_proxy': '', 'NO_PROXY': ''}
        with patch.dict(os.environ, env):
            self.assertEqual(self.manager().get('/api/state')[0], 200)

    def test_a_manager_that_does_not_answer_is_one_clean_error(self):
        self.fake.stop()
        with self.assertRaises(manager_http.ManagerError) as raised:
            self.manager(timeout=3).get('/api/state')
        self.assertIn('Cannot reach the manager', str(raised.exception))

    # ---- the session ----
    def test_it_signs_in_once_and_keeps_the_cookie_for_every_later_request(self):
        m = self.manager()
        for _ in range(3): self.assertEqual(m.get('/api/state')[0], 200)
        self.assertEqual(self.fake.signins, 1)
        self.assertEqual({seen['cookie'] for seen in self.fake.seen if seen['path'] == '/api/state'}, {'sid1'})

    def test_it_signs_in_again_once_when_the_session_was_ended(self):
        m = self.manager()
        m.get('/api/state')
        self.fake.drop_next = True
        self.assertEqual(m.get('/api/state')[0], 200)
        self.assertEqual(self.fake.signins, 2)

    def test_a_session_that_keeps_ending_is_returned_as_a_401_not_looped(self):
        m = self.manager()
        m.get('/api/state')
        self.fake.always_drop = True
        status, body = m.get('/api/state')
        self.assertEqual(self.fake.signins, 2, 'one new sign-in, then the 401 is returned')
        self.assertEqual(status, 401)
        self.assertEqual(body['detail']['code'], 'signed_out')

    def test_the_same_origin_headers_and_a_body_on_every_mutation(self):
        m = self.manager()
        m.post('/api/discovery/refresh')
        m.request('DELETE', '/api/labs/x')
        m.put('/api/host', {'address': '127.0.0.1'})
        mutating = [seen for seen in self.fake.seen if seen['method'] != 'GET' and seen['path'] != '/api/session']
        self.assertEqual(len(mutating), 3)
        for seen in mutating:
            self.assertEqual(seen['origin'], self.fake.base)
            self.assertEqual(seen['content_type'], 'application/json')
            self.assertTrue(seen['body'])
        self.assertEqual(json.loads(mutating[0]['body']), {})
        self.assertEqual(json.loads(mutating[2]['body']), {'address': '127.0.0.1'})
        self.assertTrue(all(seen['origin'] == self.fake.base for seen in self.fake.seen if seen['method'] == 'GET'))

    def test_answers_are_status_and_parsed_body_and_a_non_json_body_is_kept_as_raw(self):
        m = self.manager()
        status, body = m.get('/api/text')
        self.assertEqual((status, body), (502, {'raw': 'not json at all'}))
        status, body = m.post('/api/anything', {'a': 1})
        self.assertEqual((status, body['echo']), (200, {'a': 1}))

    def test_call_keeps_the_signature_of_the_old_mgr_client(self):
        m = self.manager()
        self.assertEqual(m.call('GET', '/api/state', None, timeout=20)[0], 200)
        self.assertEqual(m.call('POST', '/api/x', {'k': 'v'}, timeout=20)[1]['echo'], {'k': 'v'})

    # ---- credentials ----
    def test_credentials_come_from_the_environment_first(self):
        self.assertEqual(self.manager().get('/api/state')[0], 200)

    def test_without_the_environment_the_password_is_asked_for_on_the_terminal_and_never_echoed(self):
        with patch.dict(os.environ, {'CLAB_USER': '', 'CLAB_PASSWORD': ''}), \
                patch.object(manager_http.getpass, 'getpass', return_value=PASSWORD) as asked, \
                patch('builtins.input', return_value=USER), patch.object(manager_http.sys.stdin, 'isatty', return_value=True):
            self.assertEqual(self.manager().get('/api/state')[0], 200)
        asked.assert_called_once()

    def test_without_a_terminal_and_without_the_environment_it_says_what_to_set(self):
        with patch.dict(os.environ, {'CLAB_USER': '', 'CLAB_PASSWORD': ''}), patch.object(manager_http.sys.stdin, 'isatty', return_value=False):
            with self.assertRaises(manager_http.ManagerError) as raised:
                self.manager().get('/api/state')
        self.assertIn('CLAB_USER', str(raised.exception))
        self.assertIn('CLAB_PASSWORD', str(raised.exception))

    def test_a_wrong_password_is_refused_and_the_password_is_in_no_message(self):
        secret = 'the wrong password nobody may see'
        with patch.dict(os.environ, {'CLAB_PASSWORD': secret}):
            with self.assertRaises(manager_http.ManagerError) as raised:
                self.manager().get('/api/state')
        self.assertNotIn(secret, str(raised.exception))
        self.assertNotIn(secret, repr(self.manager(password=secret)))
        self.assertIn('Wrong username or password', str(raised.exception))

    # ---- the command line ----
    def test_there_is_no_password_option(self):
        parser = manager_http.argument_parser()
        text = io.StringIO()
        with contextlib.redirect_stderr(text), self.assertRaises(SystemExit) as stop:
            parser.parse_args(['--password', 'x', 'GET', '/api/state'])
        self.assertEqual(stop.exception.code, 2)
        self.assertNotIn('--password', parser.format_help())
        self.assertNotIn('--user', parser.format_help().replace('CLAB_USER', ''))

    def test_the_command_line_prints_the_status_and_the_json_answer(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = manager_http.main(['--base', self.fake.base, '--pin', str(self.cert), 'GET', '/api/state'])
        self.assertEqual(code, 0)
        self.assertTrue(out.getvalue().startswith('HTTP 200\n'))
        self.assertIn('"path": "/api/state"', out.getvalue())
        self.assertNotIn(PASSWORD, out.getvalue())

    def test_a_browser_context_gets_the_session_cookie_and_accepts_the_managers_own_certificate(self):
        class Context:
            cookies = []
            def add_cookies(self, cookies): self.cookies += cookies
        class Browser:
            options = None
            def new_context(self, **options):
                self.options = options
                self.context = Context()
                return self.context
        browser = Browser()
        context = manager_http.playwright_context(browser, self.manager(), viewport={'width': 1440, 'height': 900})
        self.assertIs(context, browser.context)
        self.assertEqual(browser.options, {'viewport': {'width': 1440, 'height': 900}, 'ignore_https_errors': True})
        [cookie] = context.cookies
        self.assertEqual((cookie['name'], cookie['value'], cookie['url']), ('clab_session', 'sid1', self.fake.base))
        self.assertTrue(cookie['httpOnly'] and cookie['secure'])
        self.assertEqual(cookie['sameSite'], 'Strict')

    def test_from_args_reads_the_manager_environment_variable_for_the_base(self):
        parser = manager_http.argument_parser()
        with patch.dict(os.environ, {'MANAGER': self.fake.base}):
            args = parser.parse_args(['--pin', str(self.cert), 'GET', '/api/state'])
            self.assertEqual(manager_http.Manager.from_args(args).base, self.fake.base)


if __name__ == '__main__':
    unittest.main()
