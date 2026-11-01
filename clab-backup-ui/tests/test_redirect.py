"""The plain-HTTP redirect listener (EXPOSURE.md 4.1, REVIEW R19 and R20; slice S3 of docs/sign-on/BUILD.md).

`app/redirect.py` is the one listener outside the gate and the guard: it holds no data and answers 301 to the
manager's own HTTPS origin after `host_allowed`, 400 for a refused Host or a request target that is not a path, 405
for any method but GET and HEAD, closes a socket 1008, and nothing else.

`app/headers.py` belongs to slice S1b. While it is absent from the checkout, the tests below install a stand-in module
that follows DESIGN.md 16.3 (`security_headers(scope, *, status=200, refusal=False)` returning a `dict[str, str]`), and
only for the duration of each test; once the real module exists it is used and the stand-in is never installed.
"""
import asyncio
import importlib
import io
import importlib.util
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REAL_HEADERS = importlib.util.find_spec('app.headers') is not None


def stand_in_security_headers(scope, *, status=200, refusal=False):
    """DESIGN.md 16.3, as far as a refusal over plain HTTP needs it."""
    values = {'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
              'Cache-Control': 'no-store',
              'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'" if refusal else "default-src 'self'"}
    if scope.get('scheme') in ('https', 'wss'):
        values['Strict-Transport-Security'] = 'max-age=15552000'
    return values


STAND_IN_SOURCE = '''
def security_headers(scope, *, status=200, refusal=False):
    values = {'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
              'Cache-Control': 'no-store',
              'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'" if refusal else "default-src 'self'"}
    if scope.get('scheme') in ('https', 'wss'):
        values['Strict-Transport-Security'] = 'max-age=15552000'
    return values
'''


class OneModule:
    def __init__(self, name, module):
        self.name, self.module = name, module

    def start(self):
        self.had, self.previous = self.name in sys.modules, sys.modules.get(self.name)
        sys.modules[self.name] = self.module

    def stop(self):
        if self.had: sys.modules[self.name] = self.previous
        else: sys.modules.pop(self.name, None)


class HeadersModule:
    """Installs the stand-in `app.headers` while the real one is absent, and records every call either way."""
    def __enter__(self):
        self.calls = []
        self.patches = []
        if REAL_HEADERS:
            module = importlib.import_module('app.headers')
        else:
            module = types.ModuleType('app.headers')
            module.security_headers = stand_in_security_headers
            import app
            # Only this one key: patch.dict(sys.modules) would also drop every module first imported meanwhile
            # (uvicorn's protocol classes among them), and a later import would build a second copy of each.
            self.patches.append(OneModule('app.headers', module))
            self.patches.append(mock.patch.object(app, 'headers', module, create=True))
        original = module.security_headers
        def recording(scope, *, status=200, refusal=False):
            self.calls.append({'status': status, 'refusal': refusal, 'scheme': scope.get('scheme')})
            return original(scope, status=status, refusal=refusal)
        self.original = original
        self.patches.append(mock.patch.object(module, 'security_headers', recording))
        for patch in self.patches: patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self.patches): patch.stop()


def scope(method='GET', raw_path=b'/', query=b'', host=b'192.0.2.10:8081', headers=None, path=None, kind='http', **extra):
    value = {'type': kind, 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'scheme': 'http' if kind == 'http' else 'ws',
             'method': method, 'path': path if path is not None else raw_path.decode('latin-1'),
             'raw_path': raw_path, 'query_string': query, 'root_path': '', 'client': ('198.51.100.7', 40000),
             'server': ('192.0.2.10', 8081),
             'headers': headers if headers is not None else ([(b'host', host)] if host is not None else [])}
    value.update(extra)
    return value


def call(app, request):
    sent = []
    async def receive():
        if request['type'] == 'lifespan':
            return receive.queue.pop(0)
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    receive.queue = [{'type': 'lifespan.startup'}, {'type': 'lifespan.shutdown'}]
    async def send(message):
        sent.append(message)
    asyncio.run(app(request, receive, send))
    return sent


def answer(sent):
    """(status, header dict with lower-case names, body bytes) of one HTTP answer; asserts its shape."""
    assert len(sent) == 2, sent
    start, body = sent
    assert start['type'] == 'http.response.start'
    assert body['type'] == 'http.response.body' and not body.get('more_body')
    names = [name for name, _ in start['headers']]
    assert all(isinstance(name, bytes) and isinstance(value, bytes) for name, value in start['headers'])
    assert names == [name.lower() for name in names], names
    assert len(names) == len(set(names)), names
    return start['status'], {name.decode(): value.decode('latin-1') for name, value in start['headers']}, body.get('body', b'')


class RedirectAnswers(unittest.TestCase):
    def setUp(self):
        self.headers = HeadersModule().__enter__()
        self.addCleanup(self.headers.__exit__)
        from app import redirect
        self.redirect = redirect
        self.app = redirect.Redirect(8443, frozenset({'manager.example.edu'}))

    def ask(self, **kwargs):
        return answer(call(self.app, scope(**kwargs)))

    def assert_refusal_shape(self, status, headers, body, code):
        self.assertEqual(body, b'')
        self.assertEqual(headers['content-length'], '0')
        self.assertNotIn('content-type', headers)
        self.assertNotIn('strict-transport-security', headers)   # plain HTTP: never HSTS
        self.assertNotIn('server', headers)
        self.assertNotIn('set-cookie', headers)
        self.assertEqual(headers['x-content-type-options'], 'nosniff')
        self.assertEqual(headers['x-frame-options'], 'DENY')
        self.assertEqual(headers['referrer-policy'], 'no-referrer')
        self.assertEqual(headers['cache-control'], 'no-store')
        self.assertEqual(headers['content-security-policy'], "default-src 'none'; frame-ancestors 'none'")
        expected = {k.lower(): v for k, v in self.headers.original(scope(), status=code, refusal=True).items()}
        for name, value in expected.items():
            self.assertEqual(headers[name], value, name)
        self.assertEqual(self.headers.calls[-1], {'status': code, 'refusal': True, 'scheme': 'http'})

    def test_redirects_to_own_https_origin(self):
        status, headers, body = self.ask(raw_path=b'/labs', query=b'x=1&y=2')
        self.assertEqual(status, 301)
        self.assertEqual(headers['location'], 'https://192.0.2.10:8443/labs?x=1&y=2')
        self.assert_refusal_shape(status, headers, body, 301)
        self.assertEqual(set(headers) - {'location'}, {k.lower() for k in self.headers.original(scope(), status=301, refusal=True)} | {'content-length'})

    def test_root_without_query_has_no_question_mark(self):
        self.assertEqual(self.ask()[1]['location'], 'https://192.0.2.10:8443/')

    def test_head_redirects_too(self):
        status, headers, body = self.ask(method='HEAD', raw_path=b'/x')
        self.assertEqual((status, headers['location'], body), (301, 'https://192.0.2.10:8443/x', b''))

    def test_name_is_the_browsers_host_without_port(self):
        cases = {b'manager.example.edu:8081': 'https://manager.example.edu:8443/',
                 b'MANAGER.Example.EDU': 'https://manager.example.edu:8443/',
                 b'[::1]:8081': 'https://[::1]:8443/',
                 b'[2001:db8::5]': 'https://[2001:db8::5]:8443/',
                 b'labvm': 'https://labvm:8443/',
                 b'printer.local:80': 'https://printer.local:8443/',
                 b'localhost:8081': 'https://localhost:8443/'}
        for host, location in cases.items():
            with self.subTest(host=host):
                status, headers, _ = self.ask(host=host)
                self.assertEqual((status, headers['location']), (301, location))

    def test_port_443_is_omitted(self):
        app = self.redirect.Redirect(443, frozenset())
        status, headers, _ = answer(call(app, scope(raw_path=b'/a', query=b'b=c')))
        self.assertEqual((status, headers['location']), (301, 'https://192.0.2.10/a?b=c'))

    def test_refused_host_is_400(self):
        cases = {'unlisted dotted name': [(b'host', b'evil.example.com')],
                 'missing': [],
                 'repeated': [(b'host', b'192.0.2.10'), (b'host', b'192.0.2.10')],
                 'repeated, other case': [(b'host', b'192.0.2.10'), (b'Host', b'192.0.2.10')],
                 'userinfo': [(b'host', b'user@192.0.2.10')],
                 'path in host': [(b'host', b'192.0.2.10/x')],
                 'unbracketed ipv6': [(b'host', b'::1')],
                 'bad port': [(b'host', b'192.0.2.10:999999')],
                 'non-ascii': [(b'host', 'café.local'.encode())],
                 'empty': [(b'host', b'')],
                 'listed name with a different suffix': [(b'host', b'manager.example.edu.evil.com')]}
        for label, headers in cases.items():
            with self.subTest(label):
                status, answer_headers, body = self.ask(headers=headers)
                self.assertEqual(status, 400)
                self.assertNotIn('location', answer_headers)
                self.assert_refusal_shape(status, answer_headers, body, 400)

    def test_target_that_is_not_a_path_is_400(self):
        for raw in (b'*', b'@evil.example/', b'http://evil.example/x', b'evil.example:443', b'', b'x/y', b'?q=1'):
            with self.subTest(raw=raw):
                status, headers, body = self.ask(raw_path=raw)
                self.assertEqual(status, 400)
                self.assertNotIn('location', headers)
                self.assert_refusal_shape(status, headers, body, 400)

    def test_missing_raw_path_is_400_never_the_decoded_path(self):
        request = scope(raw_path=b'/x')
        del request['raw_path']
        status, headers, _ = answer(call(self.app, request))
        self.assertEqual(status, 400)
        self.assertNotIn('location', headers)
        request = scope(raw_path=b'/x')
        request['raw_path'] = None
        self.assertEqual(answer(call(self.app, request))[0], 400)

    def test_bytes_a_header_cannot_carry_are_400(self):
        # h11 only lets 0x21-0x7e through a request target; the listener refuses anything else itself, whatever the
        # HTTP implementation, so a CR, LF, space, NUL, DEL or raw UTF-8 byte never reaches the Location header.
        for raw, query in ((b'/a\r\nSet-Cookie: x=1', b''), (b'/a\nb', b''), (b'/a b', b''), (b'/a\x00', b''),
                           (b'/a\x7f', b''), (b'/caf\xc3\xa9', b''), (b'/a', b'x=\r\nSet-Cookie:%20y'),
                           (b'/a', b'q=\xc3\xa9'), (b'/a', b'q=a b'), (b'/a\t', b'')):
            with self.subTest(raw=raw, query=query):
                status, headers, _ = self.ask(raw_path=raw, query=query)
                self.assertEqual(status, 400)
                self.assertNotIn('location', headers)
                self.assertNotIn('set-cookie', headers)

    def test_location_is_built_from_raw_path_and_query_unchanged(self):
        cases = [
            # (raw_path, query_string, the decoded path a careless implementation would use, Location)
            (b'/a%0d%0aSet-Cookie:%20x=1', b'', '/a\r\nSet-Cookie: x=1', 'https://192.0.2.10:8443/a%0d%0aSet-Cookie:%20x=1'),
            (b'/a%0D%0A', b'q=%0d%0a', '/a\r\n', 'https://192.0.2.10:8443/a%0D%0A?q=%0d%0a'),
            (b'/a%3Fb', b'', '/a?b', 'https://192.0.2.10:8443/a%3Fb'),
            (b'/a%3Fb', b'c=d', '/a?b', 'https://192.0.2.10:8443/a%3Fb?c=d'),
            (b'/caf%C3%A9/%E2%9C%93', b'n=%C3%A9', '/café/✓', 'https://192.0.2.10:8443/caf%C3%A9/%E2%9C%93?n=%C3%A9'),
            (b'/a%2Fb/../c', b'', '/a/b/../c', 'https://192.0.2.10:8443/a%2Fb/../c'),
            (b'//evil.example/x', b'', '//evil.example/x', 'https://192.0.2.10:8443//evil.example/x'),
            (b'/@evil.example', b'', '/@evil.example', 'https://192.0.2.10:8443/@evil.example'),
            (b'/static/app.js', b'v=1.31.8', '/static/app.js', 'https://192.0.2.10:8443/static/app.js?v=1.31.8'),
            (b'/x', b'next=%2F%23lab', '/x', 'https://192.0.2.10:8443/x?next=%2F%23lab'),
        ]
        for raw, query, decoded, location in cases:
            with self.subTest(raw=raw, query=query):
                status, headers, _ = self.ask(raw_path=raw, query=query, path=decoded)
                self.assertEqual((status, headers['location']), (301, location))
                self.assertTrue(headers['location'].startswith('https://192.0.2.10:8443/'))
                self.assertNotIn('\r', headers['location']); self.assertNotIn('\n', headers['location'])

    def test_other_methods_are_405_with_allow(self):
        for method in ('POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'TRACE', 'CONNECT', 'PROPFIND', 'get'):
            with self.subTest(method=method):
                status, headers, body = self.ask(method=method, raw_path=b'/api/session')
                self.assertEqual(status, 405)
                self.assertEqual(headers['allow'], 'GET, HEAD')
                self.assertNotIn('location', headers)
                self.assert_refusal_shape(status, headers, body, 405)

    def test_checks_run_host_then_target_then_method(self):
        self.assertEqual(self.ask(method='POST', raw_path=b'*', headers=[(b'host', b'evil.example.com')])[0], 400)
        self.assertNotIn('allow', self.ask(method='POST', raw_path=b'*', headers=[(b'host', b'evil.example.com')])[1])
        status, headers, _ = self.ask(method='POST', raw_path=b'@evil.example/')
        self.assertEqual(status, 400); self.assertNotIn('allow', headers)
        self.assertEqual(self.ask(method='POST', raw_path=b'/x')[0], 405)

    def test_websocket_is_closed_1008_before_accept(self):
        for host in (b'192.0.2.10:8081', b'evil.example.com'):
            with self.subTest(host=host):
                sent = call(self.app, scope(kind='websocket', host=host, raw_path=b'/api/nodes/x/terminal'))
                self.assertEqual(sent, [{'type': 'websocket.close', 'code': 1008}])

    def test_lifespan_passes(self):
        sent = call(self.app, {'type': 'lifespan', 'asgi': {'version': '3.0'}})
        self.assertEqual(sent, [{'type': 'lifespan.startup.complete'}, {'type': 'lifespan.shutdown.complete'}])

    def test_unknown_scope_type_sends_nothing(self):
        self.assertEqual(call(self.app, {'type': 'something-else'}), [])

    def test_request_body_is_never_read(self):
        async def receive(): raise AssertionError('the redirect read a request body')
        sent = []
        async def send(message): sent.append(message)
        asyncio.run(self.app(scope(method='POST', raw_path=b'/x'), receive, send))
        self.assertEqual(answer(sent)[0], 405)

    def test_headers_module_is_resolved_when_the_listener_is_built(self):
        # Rewritten (was test_headers_module_is_imported_lazily): the module still imports without S1b's
        # app/headers.py (no top-level import of it) and never uses allowed_hosts.HEADERS, but security_headers is now
        # looked up once, when the listener is built, never per request: a missing or broken module stops the start
        # with one error instead of answering every request 500 with a logged traceback.
        source = (ROOT / 'app' / 'redirect.py').read_text()
        top = [line for line in source.splitlines() if line.startswith(('import ', 'from '))]
        self.assertFalse([line for line in top if 'headers' in line], top)
        self.assertFalse([line for line in source.splitlines() if 'allowed_hosts.HEADERS' in line or 'import HEADERS' in line])
        import inspect
        self.assertNotIn('import', inspect.getsource(self.redirect.Redirect.answer))
        self.assertNotIn('import', inspect.getsource(self.redirect.Redirect.__call__))

    def test_a_missing_headers_module_stops_the_start_not_each_request(self):
        missing = OneModule('app.headers', None)   # import of a None entry raises ImportError
        missing.start(); self.addCleanup(missing.stop)
        with mock.patch('uvicorn.run') as run:
            with self.assertRaises(ImportError):
                self.redirect.main({'UI_HTTP_PORT': '8081'})
            with self.assertRaises(ImportError):
                self.redirect.Redirect(8443)
        run.assert_not_called()


class RedirectSettings(unittest.TestCase):
    def setUp(self):
        self.headers = HeadersModule().__enter__()   # main() builds the listener, which needs security_headers
        self.addCleanup(self.headers.__exit__)
        from app import redirect
        self.redirect = redirect

    def run_main(self, environ):
        with mock.patch('uvicorn.run') as run:
            self.redirect.main(environ)
        self.assertEqual(run.call_count, 1)
        return run.call_args

    def test_uvicorn_settings(self):
        args = self.run_main({'UI_BIND': '192.0.2.10', 'UI_PORT': '9443', 'UI_HTTP_PORT': '8081',
                              'UI_ALLOWED_HOSTS': 'manager.example.edu, other.example.org'})
        app = args.args[0]
        self.assertIsInstance(app, self.redirect.Redirect)
        self.assertEqual(app.port, 9443)
        self.assertEqual(app.allowed, frozenset({'manager.example.edu', 'other.example.org'}))
        kwargs = args.kwargs
        self.assertEqual((kwargs['host'], kwargs['port']), ('192.0.2.10', 8081))
        self.assertIs(kwargs['server_header'], False)
        self.assertIs(kwargs['proxy_headers'], False)
        self.assertIs(kwargs['access_log'], False)
        self.assertEqual(kwargs['workers'], 1)
        # Rewritten (was `== 'h11'`): still uvicorn's h11 parser, as a subclass that adds the connection deadline.
        from uvicorn.protocols.http.h11_impl import H11Protocol
        self.assertTrue(isinstance(kwargs['http'], type) and issubclass(kwargs['http'], H11Protocol), kwargs['http'])
        self.assertEqual(kwargs['http'].deadline, self.redirect.CONNECTION_DEADLINE)
        self.assertEqual(kwargs['log_level'], 'error')   # no per-request warning line either (rule 4)
        self.assertNotIn('forwarded_allow_ips', kwargs)

    def test_defaults(self):
        kwargs = self.run_main({}).kwargs
        self.assertEqual((kwargs['host'], kwargs['port']), ('0.0.0.0', 8081))
        app = self.run_main({}).args[0]
        self.assertEqual((app.port, app.allowed), (8443, frozenset()))
        self.assertEqual(self.run_main({'UI_BIND': '', 'UI_PORT': '', 'UI_HTTP_PORT': ''}).kwargs['host'], '0.0.0.0')

    def test_bad_port_values_stop_with_a_sentence(self):
        for environ in ({'UI_PORT': 'abc'}, {'UI_PORT': '0'}, {'UI_PORT': '70000'}, {'UI_HTTP_PORT': '-1'},
                        {'UI_HTTP_PORT': '65536'}, {'UI_HTTP_PORT': '8081x'}):
            with self.subTest(environ=environ), mock.patch('uvicorn.run') as run, \
                    mock.patch('sys.stderr', new_callable=io.StringIO) as stderr:
                with self.assertRaises(SystemExit) as stop:
                    self.redirect.main(environ)
                self.assertEqual(stop.exception.code, 2)
                run.assert_not_called()
                key = next(iter(environ))
                self.assertRegex(stderr.getvalue(), '^' + key + r' must be a port number from [01] to 65535\.\n$')


class RedirectProcess(unittest.TestCase):
    """The module as `python -m app.redirect` runs it in the container."""

    def environment(self, **values):
        env = {k: v for k, v in os.environ.items() if not k.startswith('UI_')}
        env.update(values)
        env['PYTHONPATH'] = str(ROOT)
        return env

    def test_disabled_waits_without_binding_and_stops_on_sigterm(self):
        # stdin from /dev/null: an inherited stdin can itself be a socket (a harness's), which is not the listener's.
        process = subprocess.Popen([sys.executable, '-m', 'app.redirect'], cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.environment(UI_HTTP_PORT='0'))
        try:
            line = process.stdout.readline()
            self.assertEqual(line, b'HTTP redirect disabled\n')
            time.sleep(0.3)
            self.assertIsNone(process.poll(), 'the disabled listener must keep running')
            inodes = {os.readlink(f'/proc/{process.pid}/fd/{fd}') for fd in os.listdir(f'/proc/{process.pid}/fd')}
            self.assertFalse([value for value in inodes if value.startswith('socket:')], inodes)
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=5), 0)
            self.assertEqual(process.stdout.read(), b'')
            self.assertEqual(process.stderr.read(), b'')
        finally:
            if process.poll() is None: process.kill(); process.wait()
            process.stdout.close(); process.stderr.close()

    def test_imports_neither_the_manager_nor_its_store(self):
        code = ('import sys, types, asyncio\n'
                'stand_in = types.ModuleType("app.headers")\n'
                'exec(' + repr(STAND_IN_SOURCE) + ', stand_in.__dict__)\n'
                'import app.redirect as r\n'
                'present = "app.headers" in sys.modules\n'
                'if not present: sys.modules["app.headers"] = stand_in\n'
                'sent = []\n'
                'async def receive(): return {"type": "http.request", "body": b""}\n'
                'async def send(m): sent.append(m)\n'
                'asyncio.run(r.Redirect(8443, frozenset())({"type": "http", "method": "GET", "raw_path": b"/", "query_string": b"",'
                ' "headers": [(b"host", b"192.0.2.10")], "scheme": "http", "path": "/"}, receive, send))\n'
                'assert sent[0]["status"] == 301, sent\n'
                'print(sorted(m for m in sys.modules if m == "app" or m.startswith("app.")))\n')
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True,
                                env=self.environment(), timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        modules = set(eval(result.stdout))
        self.assertLessEqual(modules, {'app', 'app.redirect', 'app.allowed_hosts', 'app.headers', 'app.origin'}, modules)
        for forbidden in ('fastapi', 'starlette', 'paramiko', 'cryptography'):
            self.assertNotIn(forbidden, result.stdout)


class RedirectUnderPressure(unittest.TestCase):
    """The exposed port against a client that holds sockets open (EXPOSURE.md 4.1 item 4: an exposed port must not fill
    the disk and must keep redirecting). The listener runs as a process of its own, under a descriptor limit, with the
    connection deadline shortened to one second."""

    LAUNCH = ('import sys, types\n'
              'try:\n'
              '    import app.headers\n'
              'except ImportError:\n'
              '    stand_in = types.ModuleType("app.headers")\n'
              '    exec(' + repr(STAND_IN_SOURCE) + ', stand_in.__dict__)\n'
              '    sys.modules["app.headers"] = stand_in\n'
              'import app.redirect as r\n'
              'r.CONNECTION_DEADLINE = 1.0\n'
              'r.main()\n')

    def start(self, limit):
        import resource
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0)); port = probe.getsockname()[1]
        log = open(Path(self.enterContext(TemporaryDirectory())) / 'stderr', 'w+b')
        self.addCleanup(log.close)
        env = {k: v for k, v in os.environ.items() if not k.startswith('UI_')}
        env.update(PYTHONPATH=str(ROOT), UI_BIND='127.0.0.1', UI_HTTP_PORT=str(port), UI_PORT='8443')
        process = subprocess.Popen([sys.executable, '-c', self.LAUNCH], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log,
                                   preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_NOFILE, limit))
        def stop():
            if process.poll() is None: process.kill()
            process.wait()
        self.addCleanup(stop)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if self.get(port, timeout=1) == 301: break
            except OSError:
                time.sleep(0.05)
        else:
            self.fail('the listener did not start: ' + log.read().decode(errors='replace'))
        return process, port, log

    def get(self, port, timeout=5):
        with socket.create_connection(('127.0.0.1', port), timeout=timeout) as conn:
            conn.sendall(b'GET /x HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n')
            reply = conn.recv(4096)
        return int(reply.split()[1]) if reply.startswith(b'HTTP/') else None

    def idle(self, port, count):
        sockets = []
        for _ in range(count):
            conn = socket.socket(); conn.setblocking(False)
            conn.connect_ex(('127.0.0.1', port))
            sockets.append(conn)
        def close():
            for conn in sockets: conn.close()
        self.addCleanup(close)
        return sockets

    def closed_by_server(self, conn):
        conn.settimeout(0.05)
        try:
            return conn.recv(1) == b''
        except ConnectionResetError:
            return True
        except (socket.timeout, BlockingIOError):
            return False

    def test_silent_and_trickling_connections_end_at_the_deadline(self):
        process, port, log = self.start((1024, 1024))
        silent = self.idle(port, 5)
        trickle = socket.create_connection(('127.0.0.1', port), timeout=5)
        self.addCleanup(trickle.close)
        trickle.sendall(b'GET / HTTP/1.1\r\n')
        started = time.monotonic()
        while time.monotonic() - started < 3:
            try: trickle.sendall(b'X-A: b\r\n')
            except OSError: break
            time.sleep(0.2)
        time.sleep(0.3)
        self.assertTrue(all(self.closed_by_server(conn) for conn in silent), 'a silent connection outlived the deadline')
        self.assertTrue(self.closed_by_server(trickle), 'a trickling header outlived the deadline')
        self.assertEqual(self.get(port), 301)
        self.assertIsNone(process.poll())
        log.seek(0)
        self.assertEqual(log.read(), b'')

    def test_descriptor_exhaustion_neither_floods_the_log_nor_stops_the_redirect(self):
        process, port, log = self.start((48, 48))   # soft = hard: the listener cannot raise it
        held = self.idle(port, 120)
        time.sleep(2.5)   # several accept retries while every descriptor is taken
        log.seek(0); output = log.read()
        self.assertLess(len(output), 2048, output[:2048])
        self.assertLessEqual(output.count(b'out of system resource'), 1, output[:2048])
        self.assertNotIn(b'Traceback', output)
        # Still holding all 120: the deadline frees descriptors and a fresh request is redirected.
        self.assertEqual(self.get(port, timeout=10), 301)
        self.assertIsNone(process.poll())
        self.assertEqual(len(held), 120)

    def test_soft_descriptor_limit_is_raised_to_the_hard_limit(self):
        process, port, log = self.start((64, 4096))
        limits = Path(f'/proc/{process.pid}/limits').read_text()
        row = next(line for line in limits.splitlines() if line.startswith('Max open files'))
        self.assertEqual(row.split()[3:5], ['4096', '4096'], row)


class AsyncioThrottle(unittest.TestCase):
    def test_one_line_a_minute_without_a_traceback(self):
        from app import redirect
        throttle = redirect.Throttle(every=60)
        def record(message):
            try: raise OSError(24, 'Too many open files')
            except OSError: exc_info = sys.exc_info()
            return logging.LogRecord('asyncio', logging.ERROR, __file__, 1, message, (), exc_info)
        first = record('socket.accept() out of system resource\nsocket: <x>')
        with mock.patch('time.monotonic', return_value=1000.0):
            self.assertTrue(throttle.filter(first))
            self.assertFalse(throttle.filter(record('socket.accept() out of system resource')))
        self.assertIsNone(first.exc_info)
        self.assertEqual(first.getMessage(), 'socket.accept() out of system resource ([Errno 24] Too many open files)')
        with mock.patch('time.monotonic', return_value=1059.0):
            self.assertFalse(throttle.filter(record('again')))
        with mock.patch('time.monotonic', return_value=1061.0):
            self.assertTrue(throttle.filter(record('again')))

    def test_main_installs_it_on_the_asyncio_logger(self):
        from app import redirect
        with HeadersModule(), mock.patch('uvicorn.run'):
            before = list(logging.getLogger('asyncio').filters)
            self.addCleanup(setattr, logging.getLogger('asyncio'), 'filters', before)
            redirect.main({'UI_HTTP_PORT': '8081'})
            redirect.main({'UI_HTTP_PORT': '8081'})
        added = [f for f in logging.getLogger('asyncio').filters if f not in before]
        self.assertEqual(len(added), 1, added)
        self.assertIsInstance(added[0], redirect.Throttle)


class RedirectOverRealUvicorn(unittest.TestCase):
    """Raw request bytes through uvicorn's own h11 parser: what a scanner or a crafted client can actually send."""

    @classmethod
    def setUpClass(cls):
        import uvicorn
        cls.headers = HeadersModule().__enter__()
        from app import redirect
        cls.records = []
        class Collect(logging.Handler):
            def emit(handler, record): cls.records.append(record)
        cls.collector = Collect(level=logging.DEBUG)
        settings = redirect.settings({'UI_PORT': '8443', 'UI_HTTP_PORT': '8081', 'UI_ALLOWED_HOSTS': 'manager.example.edu'})
        app, options = settings
        options = dict(options, host='127.0.0.1', port=0)
        options.pop('workers', None)
        cls.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cls.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        cls.sock.bind(('127.0.0.1', 0))
        cls.port = cls.sock.getsockname()[1]
        cls.server = uvicorn.Server(uvicorn.Config(app, **options))
        cls.thread = threading.Thread(target=cls.server.run, kwargs={'sockets': [cls.sock]}, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < deadline: time.sleep(0.02)
        assert cls.server.started, 'uvicorn did not start'
        for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
            logging.getLogger(name).addHandler(cls.collector)

    @classmethod
    def tearDownClass(cls):
        for name in ('uvicorn', 'uvicorn.error', 'uvicorn.access'):
            logging.getLogger(name).removeHandler(cls.collector)
        cls.server.should_exit = True
        cls.thread.join(10)
        cls.sock.close()
        cls.headers.__exit__()

    def raw(self, data):
        with socket.create_connection(('127.0.0.1', self.port), timeout=5) as conn:
            conn.sendall(data)
            reply = b''
            while True:
                try: chunk = conn.recv(65536)
                except (socket.timeout, ConnectionResetError): break
                if not chunk: break
                reply += chunk
        head = reply.split(b'\r\n\r\n', 1)[0].decode('latin-1').split('\r\n')
        status = int(head[0].split()[1]) if head and head[0].startswith('HTTP/') else None
        headers = {}
        for line in head[1:]:
            name, _, value = line.partition(':')
            headers.setdefault(name.strip().lower(), []).append(value.strip())
        return status, headers, reply

    def request(self, target, method=b'GET', host=b'127.0.0.1:8081', extra=b''):
        return self.raw(method + b' ' + target + b' HTTP/1.1\r\nHost: ' + host + b'\r\nConnection: close\r\n' + extra + b'\r\n')

    def test_redirect_and_exact_location(self):
        cases = {b'/': 'https://127.0.0.1:8443/',
                 b'/a%0d%0aSet-Cookie:%20x=1?q=%0D%0A': 'https://127.0.0.1:8443/a%0d%0aSet-Cookie:%20x=1?q=%0D%0A',
                 b'/a%3Fb?c=d': 'https://127.0.0.1:8443/a%3Fb?c=d',
                 b'/a%3Fb': 'https://127.0.0.1:8443/a%3Fb',
                 b'/caf%C3%A9?n=%E2%9C%93': 'https://127.0.0.1:8443/caf%C3%A9?n=%E2%9C%93',
                 b'//evil.example/x': 'https://127.0.0.1:8443//evil.example/x',
                 b'/x?': 'https://127.0.0.1:8443/x'}
        for target, location in cases.items():
            with self.subTest(target=target):
                status, headers, reply = self.request(target)
                self.assertEqual(status, 301, reply)
                self.assertEqual(headers['location'], [location])
                self.assertNotIn('set-cookie', headers)
                self.assertNotIn('server', headers)
                self.assertNotIn('strict-transport-security', headers)
                self.assertEqual(headers['content-length'], ['0'])
                self.assertTrue(reply.endswith(b'\r\n\r\n'), reply)

    def test_non_path_targets_are_400(self):
        for target in (b'@evil.example/', b'*', b'http://evil.example/x', b'evil.example:443', b'x'):
            with self.subTest(target=target):
                status, headers, reply = self.request(target)
                self.assertEqual(status, 400, reply)
                self.assertNotIn('location', headers)

    def test_connect_and_options_star_are_400(self):
        self.assertEqual(self.request(b'evil.example:443', method=b'CONNECT')[0], 400)
        self.assertEqual(self.request(b'*', method=b'OPTIONS')[0], 400)

    def test_refused_and_repeated_host_are_400(self):
        self.assertEqual(self.request(b'/', host=b'evil.example.com')[0], 400)
        self.assertEqual(self.request(b'/', host=b'manager.example.edu')[0], 301)
        self.assertEqual(self.request(b'/', extra=b'Host: 127.0.0.1\r\n')[0], 400)
        self.assertEqual(self.raw(b'GET / HTTP/1.0\r\n\r\n')[0], 400)

    def test_raw_control_and_utf8_bytes_never_reach_location(self):
        for target in (b'/caf\xc3\xa9', b'/a\x7f', b'/a\x01'):
            with self.subTest(target=target):
                status, headers, _ = self.request(target)
                self.assertEqual(status, 400)   # h11 refuses it before the app; the app would too
                self.assertNotIn('location', headers)

    def test_post_with_a_body_is_405(self):
        status, headers, _ = self.raw(b'POST /api/session HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Length: 5\r\n'
                                      b'Content-Type: application/json\r\nConnection: close\r\n\r\n{"a":')
        self.assertEqual(status, 405)
        self.assertEqual(headers['allow'], ['GET, HEAD'])

    def test_websocket_handshake_is_refused(self):
        status, headers, _ = self.raw(b'GET /api/nodes/x/terminal HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n'
                                      b'Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                                      b'Sec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1\r\n\r\n')
        self.assertEqual(status, 403)
        self.assertNotIn('location', headers)

    def test_nothing_is_logged_per_request(self):
        before = len(self.records)
        self.request(b'/')
        self.request(b'/', method=b'POST')
        self.request(b'@evil.example/')
        self.raw(b'NOT HTTP AT ALL\r\n\r\n')
        self.raw(b'GET /\x00 HTTP/1.1\r\n\r\n')
        time.sleep(0.2)
        self.assertEqual([r.getMessage() for r in self.records[before:]], [])


if __name__ == '__main__':
    unittest.main()
