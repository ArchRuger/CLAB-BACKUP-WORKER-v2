"""Open sockets follow their manager session (sign-on DESIGN.md 5.6, 6.5, 11.2, 11.3; REVIEW R9, R10; BUILD.md S2).

- The terminal, the serial console and the capture desktop socket close 1008 `signed_out` within 5 s of
  their session's end (sign-out, a disabled user, an idle expiry), whatever the device or desktop does.
- Client input renews the session at most once a minute (`sessions.touch`); the socket's own data, a resize
  and a viewer's automatic frame requests renew nothing.
- Both Origin checks stay and compare with `origin.scheme(scope)`; the capture cookie's `Secure` follows it.
- The capture owner identity sent to the service on every owner-scoped call and on the socket is
  `sha256(cookie + '\\n' + user)`, so a second person in the same browser never reaches the first person's
  desktop sessions and the first person, returning, finds theirs.

Cookie values, session ids and owner identities are compared with `assertTrue`, never printed.
"""
import hashlib
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import Response
from session_fixture import PASSWORD, SignedInClient, assert_not_logged, sign_in, sign_out
from starlette.websockets import WebSocketDisconnect
import uvicorn

import test_nodes
from app import capture_sessions
from app.capture import EdgesharkProvider
from app.capture_sessions import BrowserSessions
from app.main import create_app
from app.sessions import IDLE
from test_capture import fixture

ORIGIN = {'origin': 'http://testserver'}
WSS_TERMINAL = 'wss://testserver/api/terminal'
TOKEN = 'a' * 64


def identity(cookie, user):
    return hashlib.sha256((cookie + '\n' + user).encode()).hexdigest()


class Clock:
    """Replaces `sessions.clock` (the attribute, never time.monotonic itself)."""
    def __init__(self, sessions):
        self.now = sessions.clock(); sessions.clock = self

    def __call__(self):
        return self.now


def closes(ws, seconds=5.0):
    """Reads `ws` until it closes; answers (code, reason, elapsed) or fails when it stays open past `seconds`."""
    result = {}
    def read():
        started = time.monotonic()
        try:
            while True:
                message = ws.receive()
                if message['type'] == 'websocket.close':
                    result.update(code=message.get('code', 1000), reason=message.get('reason', ''), elapsed=time.monotonic() - started)
                    return
        except Exception as error:
            result.update(error=repr(error), elapsed=time.monotonic() - started)
    reader = threading.Thread(target=read, daemon=True); reader.start(); reader.join(seconds + 1)
    if reader.is_alive(): raise AssertionError(f'the socket stayed open for more than {seconds} s')
    if 'error' in result: raise AssertionError(result['error'])
    return result['code'], result['reason'], result['elapsed']


def wait_for(predicate, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate(): return True
        time.sleep(0.02)
    return predicate()


class Touches:
    """Counts `sessions.touch` calls for one session id."""
    def __init__(self, sessions, session_id):
        self.count = 0; real = sessions.touch
        def touch(sid):
            if sid == session_id: self.count += 1
            return real(sid)
        sessions.touch = touch


# ---- the terminal (SSH) ----------------------------------------------------------------------------------------------

class TerminalSessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.client = SignedInClient(self.app)
        self.app.state.store.state['labs'].append({
            'id': 'lab', 'name': 'Example', 'profiles': [], 'defaults': {}, 'interval': 30, 'next_run': 123456,
            'nodes': [{'name': 'r1', 'address': '192.0.2.1', 'port': 22, 'platform': 'arista_ceos', 'username': 'user',
                       'password': 'never-log-this', 'profile_id': '', 'enabled': True}]})
        self.services = self.app.state.node_services
        self.sessions = self.app.state.sessions

    def tearDown(self):
        # A socket's own clean-up releases its client and then writes terminal.close into the data directory: wait
        # for both before the directory goes, or the write races the cleanup (Directory not empty).
        wait_for(lambda: not self.services.clients)
        def settled():
            actions = [e['action'] for e in self.app.state.store.events()]
            return actions.count('terminal.open') == actions.count('terminal.close')
        wait_for(settled)
        self.services.close(); self.app.state.runner.close(); self.client.close(); self.tmp.cleanup()

    def shell(self, output=b''):
        channel = MagicMock(); channel.closed = False
        channel.recv_ready.return_value = False
        channel.exit_status_ready.return_value = False
        ssh = MagicMock(); ssh.invoke_shell.return_value = channel
        patches = [patch('app.node_services.paramiko.SSHClient', return_value=ssh), patch('app.node_services.connect')]
        for item in patches: item.start(); self.addCleanup(item.stop)
        self.addCleanup(lambda: setattr(channel, 'closed', True))   # never leave a loop running behind a failed test
        return channel, ssh

    def open(self, client):
        key = client.post('/api/labs/lab/terminal-ticket', json={'name': 'r1'}).json()['ticket']
        ws = client.websocket_connect('/api/terminal', headers=ORIGIN).__enter__()
        ws.send_json({'ticket': key})
        self.assertEqual(ws.receive_json()['message'], 'Connected')
        return ws

    def assert_signed_out(self, ws, ssh):
        code, reason, elapsed = closes(ws)
        self.assertEqual((code, reason), (1008, 'signed_out'))
        self.assertLess(elapsed, 5)
        self.assertTrue(wait_for(lambda: not self.services.clients), 'the SSH client is released')
        ssh.close.assert_called()

    def test_sign_out_closes_the_open_terminal_1008_signed_out_within_5_s(self):
        _, ssh = self.shell()
        other = SignedInClient(self.app)
        try:
            ws = self.open(other)
            self.assertEqual(sign_out(other).status_code, 200)
            self.assert_signed_out(ws, ssh)
        finally: other.close()
        events = [e['action'] for e in self.app.state.store.events()]
        self.assertIn('terminal.open', events); self.assertIn('terminal.close', events)

    def test_a_disabled_user_and_an_idle_expiry_close_the_terminal_too(self):
        _, ssh = self.shell()
        operator = SignedInClient(self.app, role='operator', name='olga')
        try:
            ws = self.open(operator)
            self.assertEqual(self.client.patch('/api/users/olga', json={'disabled': True}).status_code, 200)
            self.assert_signed_out(ws, ssh)
        finally: operator.close()
        other = SignedInClient(self.app)
        try:
            ws = self.open(other)
            clock = Clock(self.sessions); clock.now += IDLE + 1
            self.assert_signed_out(ws, ssh)
        finally: other.close()

    def test_the_own_change_keeps_the_current_sessions_terminal_and_a_later_sign_out_closes_it(self):
        # DESIGN 5.5: the current session survives the own change re-stamped; its open terminal follows the rotated
        # id (11.3) instead of dropping as signed out, renews the new session on input, and still closes on sign-out.
        channel, ssh = self.shell()
        operator = SignedInClient(self.app, role='operator', name='olga', password='her first passphrase here')
        try:
            ws = self.open(operator)
            changed = operator.post('/api/session/password', json={'current': 'her first passphrase here', 'password': 'the one she chose herself'})
            self.assertEqual(changed.status_code, 200, changed.text)
            self.assertEqual(operator.get('/api/session').status_code, 200, 'the rotated cookie works')
            self.assertFalse(wait_for(lambda: not self.services.clients, 2.5), 'the terminal dropped within 2.5 s of the own change')
            touches = Touches(self.sessions, operator.session_cookie())
            ws.send_json({'type': 'input', 'data': 'x'})
            self.assertTrue(wait_for(lambda: channel.sendall.call_count == 1))
            self.assertTrue(wait_for(lambda: touches.count == 1), 'input renews the rotated session')
            self.assertEqual(sign_out(operator).status_code, 200)
            self.assert_signed_out(ws, ssh)
        finally: operator.close()
        assert_not_logged(self.app, 'her first passphrase here', 'the one she chose herself', operator.session_cookie())

    def test_terminal_events_name_the_sockets_user(self):
        # DESIGN 10.3: the socket knows its user; terminal.open and terminal.close carry it, never '-'.
        _, ssh = self.shell()
        operator = SignedInClient(self.app, role='operator', name='olga')
        try:
            ws = self.open(operator); sign_out(operator); self.assert_signed_out(ws, ssh)
        finally: operator.close()
        self.assertTrue(wait_for(lambda: any(e['action'] == 'terminal.close' for e in self.app.state.store.events())))
        self.assertEqual([(e['action'], e['actor'], e['node']) for e in reversed(self.app.state.store.events()) if e['action'].startswith('terminal.')],
                         [('terminal.open', 'olga', 'r1'), ('terminal.close', 'olga', 'r1')])

    def test_a_terminal_whose_session_lives_stays_open(self):
        channel, _ = self.shell()
        ws = self.open(self.client)
        time.sleep(1.5)
        ws.send_json({'type': 'input', 'data': 'x'})
        self.assertTrue(wait_for(lambda: channel.sendall.call_count == 1))
        channel.closed = True
        try: ws.close()
        except Exception: pass

    def test_input_renews_the_session_at_most_once_a_minute_and_nothing_else_does(self):
        channel, _ = self.shell()
        sid = self.client.session_cookie()
        clock = Clock(self.sessions)
        ws = self.open(self.client)
        touches = Touches(self.sessions, sid)   # after the ticket's POST, which the gate renews
        sent = 0
        def type_once():
            nonlocal sent
            ws.send_json({'type': 'input', 'data': 'x'}); sent += 1
            self.assertTrue(wait_for(lambda: channel.sendall.call_count == sent))
        type_once(); type_once()
        self.assertEqual(touches.count, 1)
        ws.send_json({'type': 'resize', 'cols': 100, 'rows': 30})
        ws.send_json({'type': 'input', 'data': ''})
        self.assertTrue(wait_for(lambda: channel.resize_pty.call_count == 1))
        clock.now += 59; type_once()
        self.assertEqual(touches.count, 1, 'not again inside the minute')
        clock.now += 2; type_once()
        self.assertEqual(touches.count, 2)
        # The renewal is real: 11 h after the last touch the session resolves, and the person typed 11 h ago.
        clock.now += 11 * 3600; type_once()
        clock.now += 11 * 3600
        self.assertIsNotNone(self.sessions.resolve(sid), 'input 11 h ago keeps the session')
        self.assertEqual(touches.count, 3)
        channel.closed = True
        try: ws.close()
        except Exception: pass

    def test_device_output_never_renews_the_session(self):
        channel, _ = self.shell()
        sid = self.client.session_cookie()
        Clock(self.sessions)
        chunks = [b'line\r\n'] * 5
        channel.recv_ready.side_effect = lambda: bool(chunks)
        channel.recv.side_effect = lambda size: chunks.pop()
        ws = self.open(self.client)
        touches = Touches(self.sessions, sid)
        for _ in range(5): self.assertEqual(ws.receive_bytes(), b'line\r\n')
        self.assertEqual(touches.count, 0)
        channel.closed = True
        try: ws.close()
        except Exception: pass

    def test_origin_check_stays_and_follows_the_scheme_of_the_scope(self):
        self.shell()
        for origin in ('http://evil.test', 'https://testserver', ''):
            with self.subTest(origin=origin):
                with self.assertRaises(WebSocketDisconnect) as ctx:
                    with self.client.websocket_connect('/api/terminal', headers={'origin': origin}): pass
                self.assertEqual(ctx.exception.code, 1008)
        secure = SignedInClient(self.app, base_url='https://testserver')
        try:
            for origin in ('http://testserver', 'https://evil.test'):
                with self.subTest(origin=origin, scheme='https'):
                    with self.assertRaises(WebSocketDisconnect):
                        with secure.websocket_connect(WSS_TERMINAL, headers={'origin': origin}): pass
            # TestClient joins a relative socket path onto ws://, so the TLS case names wss:// itself.
            with secure.websocket_connect(WSS_TERMINAL, headers={'origin': 'https://testserver'}) as ws:   # accepted
                ws.send_json({'ticket': 'unknown'})
                with self.assertRaises(WebSocketDisconnect) as ctx: ws.receive_json()
            self.assertEqual(ctx.exception.code, 1008)
        finally: secure.close()
        # The comparison asks origin.scheme(scope): a scope it calls https refuses the http origin.
        with patch('app.node_services.scheme', return_value='https'):
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect('/api/terminal', headers=ORIGIN): pass

    def test_nothing_secret_reaches_a_log(self):
        _, ssh = self.shell()
        other = SignedInClient(self.app)
        try:
            cookie = other.session_cookie()
            ws = self.open(other); sign_out(other); self.assert_signed_out(ws, ssh)
        finally: other.close()
        assert_not_logged(self.app, cookie, self.client.session_cookie(), PASSWORD, 'never-log-this')


# ---- the serial console ---------------------------------------------------------------------------------------------

class ConsoleSessionTests(unittest.TestCase):
    ORIGIN = ORIGIN
    device = staticmethod(test_nodes.ConsoleTests.device)
    setUp = test_nodes.ConsoleTests.setUp
    tearDown = test_nodes.ConsoleTests.tearDown
    serve = test_nodes.ConsoleTests.serve
    ticket = test_nodes.ConsoleTests.ticket

    def open(self, client):
        key = client.post('/api/labs/lab/terminal-ticket', json={'name': 'r1', 'protocol': 'console'}).json()['ticket']
        ws = client.websocket_connect('/api/terminal', headers=ORIGIN).__enter__()
        ws.send_json({'ticket': key})
        self.assertEqual(ws.receive_json(), {'type': 'status', 'message': 'Connected'})
        return ws

    def test_sign_out_closes_the_console_1008_signed_out_within_5_s_and_frees_its_slot(self):
        self.serve()
        other = SignedInClient(self.app)
        try:
            ws = self.open(other)
            self.assertEqual(set(self.services.consoles), {('lab', 'r1')})
            sign_out(other)
            code, reason, elapsed = closes(ws)
            self.assertEqual((code, reason), (1008, 'signed_out')); self.assertLess(elapsed, 5)
        finally: other.close()
        self.assertTrue(wait_for(lambda: self.services.consoles == {}))
        self.assertTrue(wait_for(lambda: 'console.close' in self.client.get('/api/logs').text))
        self.assertEqual([(e['action'], e['actor'], e['node']) for e in reversed(self.app.state.store.events()) if e['action'].startswith('console.')],
                         [('console.open', 'tester', 'r1'), ('console.close', 'tester', 'r1')], 'the events name the socket\'s user (10.3)')

    def test_a_login_check_names_the_person_who_asked_for_it(self):
        node = self.lab['nodes'][1]; node.update(username='user', password='never-log-this')
        with patch('app.node_services.connect'), patch('app.node_services.cli_answers', return_value=True):
            self.assertEqual(self.client.post('/api/labs/lab/ssh-check', json={'name': 'ceos'}).json()['status'], 'reachable')
            self.assertEqual(self.client.post('/api/labs/lab/ssh-check-all', json={}).status_code, 200)
            self.assertTrue(wait_for(lambda: not self.services.checking_all and not self.services.checking))
        checks = [(e['node'], e['actor']) for e in reversed(self.app.state.store.events()) if e['action'] == 'ssh.check']
        self.assertEqual(checks[0], ('ceos', 'tester'), 'the route has the request in hand')
        self.assertTrue(checks[1:] and all(actor == 'tester' for _, actor in checks[1:]), f'the bulk check carries the actor of the request that started it: {checks}')

    def test_console_input_renews_at_most_once_a_minute(self):
        console = self.serve()
        sessions = self.app.state.sessions; sid = self.client.session_cookie()
        clock = Clock(sessions)
        ws = self.open(self.client)
        touches = Touches(sessions, sid)
        expected = len(test_nodes.LIVE_REPLIES)
        for step in (0, 30, 31):
            clock.now += step
            ws.send_json({'type': 'input', 'data': 'a'}); expected += 1
            self.assertEqual(len(console.wait_received(1, expected)), expected)
        self.assertEqual(touches.count, 2, 'at 0 s and at 61 s, not at 30 s')
        ws.send_json({'type': 'resize', 'cols': 100, 'rows': 30})
        time.sleep(0.2); self.assertEqual(touches.count, 2)
        console.close_clients()
        try: closes(ws)
        except AssertionError: pass


# ---- the capture desktop socket and the owner identity -------------------------------------------------------------

class Broker:
    """A synthetic capture service on loopback: owner-scoped rows, every request's owner recorded."""
    def __init__(self):
        self.rows = {}; self.owners = []; self.frames = []; self.headers = []
        broker = FastAPI()

        def auth(request):
            self.headers.append(dict(request.headers))
            if request.headers.get('authorization') != 'Bearer ' + TOKEN: raise HTTPException(403)
            who = request.headers.get('x-capture-owner', ''); self.owners.append(who)
            return who

        def own(request, sid):
            who = auth(request)
            if self.rows.get(sid) != who: raise HTTPException(404)
            return who

        @broker.get('/health')
        async def health(request: Request):
            auth(request); return {'ready': True, 'max_sessions': 4}

        @broker.post('/sessions')
        async def start(request: Request):
            who = auth(request); data = await request.json()
            sid = hashlib.sha256((who + data['request_id']).encode()).hexdigest()
            self.rows[sid] = who
            return {'id': sid}

        @broker.get('/sessions')
        async def listing(request: Request):
            who = auth(request)
            return {'sessions': [{'id': sid, 'name': 'clab-demo-r1', 'interfaces': ['eth2'], 'remaining_seconds': 7000, 'idle_seconds': 900}
                                 for sid, owner in self.rows.items() if owner == who]}

        @broker.get('/sessions/{sid}')
        async def session(sid: str, request: Request):
            own(request, sid); return {'id': sid}

        @broker.post('/sessions/{sid}/end')
        async def end(sid: str, request: Request):
            own(request, sid); self.rows.pop(sid, None); return {'ended': True}

        @broker.get('/sessions/{sid}/assets/{path:path}')
        async def asset(sid: str, path: str, request: Request):
            own(request, sid); return Response(b'export default class RFB {}', media_type='text/javascript')

        @broker.get('/sessions/{sid}/download')
        async def download(sid: str, request: Request):
            own(request, sid); return Response(b'synthetic-tar', media_type='application/x-tar')

        @broker.websocket('/sessions/{sid}/websockify')
        async def desktop(ws: WebSocket, sid: str):
            self.headers.append(dict(ws.headers))
            who = ws.headers.get('x-capture-owner', ''); self.owners.append(who)
            if ws.headers.get('authorization') != 'Bearer ' + TOKEN or self.rows.get(sid) != who:
                await ws.close(code=1008); return
            await ws.accept(subprotocol='binary' if 'binary' in ws.scope.get('subprotocols', []) else None)
            await ws.send_bytes(b'RFB 003.008\n')
            try:
                while True:
                    frame = await ws.receive_bytes(); self.frames.append(frame); await ws.send_bytes(frame)
            except Exception:
                return

        sock = socket.socket(); sock.bind(('127.0.0.1', 0)); self.port = sock.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(broker, log_level='error', access_log=False))
        self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [sock]}, daemon=True); self.thread.start()
        for _ in range(300):
            if self.server.started: break
            time.sleep(.01)

    def stop(self):
        self.server.should_exit = True; self.thread.join(5)


class CaptureSessionTests(unittest.TestCase):
    def setUp(self):
        self.broker = Broker(); self.assertTrue(self.broker.server.started)
        self.tmp = tempfile.TemporaryDirectory()
        with patch.dict('os.environ', {'CAPTURE_PROVIDER': 'disabled'}): self.app = create_app(self.tmp.name)
        self.client = SignedInClient(self.app)
        self.app.state.captures.provider = EdgesharkProvider('http://fixture')
        self.app.state.captures.sessions = BrowserSessions(f'http://127.0.0.1:{self.broker.port}', TOKEN)
        self.read = patch('app.capture.read_discovery', return_value=fixture()); self.read.start()
        self.sessions = self.app.state.sessions
        self.extra = []

    def tearDown(self):
        self.read.stop()
        for client in [self.client, *self.extra]: client.close()
        for service in ('runner', 'node_services', 'git_progress', 'operations', 'discovery'):
            getattr(self.app.state, service).close()
        self.tmp.cleanup(); self.broker.stop()

    def another(self, **kwargs):
        client = SignedInClient(self.app, **kwargs); self.extra.append(client); return client

    def launch(self, client, rid='1'):
        target = client.get('/api/capture/targets').json()['targets'][0]
        result = client.post('/api/capture/launch', json={'target_id': target['id'], 'interfaces': [target['interfaces'][0]],
                                                          'request_id': rid * 64})
        self.assertEqual(result.status_code, 200, result.status_code)
        return result.json()['id']

    def socket(self, client, sid):
        ws = client.websocket_connect(f'/api/capture/sessions/{sid}/websockify', headers=ORIGIN).__enter__()
        self.assertEqual(ws.receive_bytes(), b'RFB 003.008\n')
        return ws

    def test_sign_out_closes_the_desktop_socket_1008_signed_out_within_5_s(self):
        other = self.another()
        ws = self.socket(other, self.launch(other))
        sign_out(other)
        code, reason, elapsed = closes(ws)
        self.assertEqual((code, reason), (1008, 'signed_out')); self.assertLess(elapsed, 5)

    def test_an_idle_expiry_closes_the_desktop_socket_too(self):
        other = self.another()
        ws = self.socket(other, self.launch(other))
        clock = Clock(self.sessions); clock.now += IDLE + 1
        code, reason, _ = closes(ws)
        self.assertEqual((code, reason), (1008, 'signed_out'))

    def test_viewer_input_renews_at_most_once_a_minute_and_automatic_frames_never(self):
        sid = self.launch(self.client)
        clock = Clock(self.sessions); touches = Touches(self.sessions, self.client.session_cookie())
        ws = self.socket(self.client, sid)
        def frame(data):
            ws.send_bytes(data); self.assertEqual(ws.receive_bytes(), data)
        frame(b'RFB 003.008\n'); frame(b'\x01'); frame(b'\x00')                 # handshake: version, security, ClientInit
        frame(b'\x03\x01\x00\x00\x00\x00\x04\x00\x03\x00')                     # FramebufferUpdateRequest: the viewer's own
        frame(b'\x02\x00\x00\x01\x00\x00\x00\x00')                             # SetEncodings
        self.assertEqual(touches.count, 0)
        frame(b'\x05\x00\x00\x10\x00\x20')                                     # PointerEvent: the person
        frame(b'\x04\x01\x00\x00\x00\x00\x00\x61')                             # KeyEvent inside the minute
        self.assertEqual(touches.count, 1)
        clock.now += 61; frame(b'\x04\x00\x00\x00\x00\x00\x00\x61')
        self.assertEqual(touches.count, 2)
        clock.now += 61; frame(b'\x03\x01\x00\x00\x00\x00\x04\x00\x03\x00')
        self.assertEqual(touches.count, 2)
        ws.close()

    def test_the_origin_check_stays_and_follows_the_scheme(self):
        sid = self.launch(self.client)
        for origin in ('https://evil', 'https://testserver', ''):
            with self.subTest(origin=origin):
                with self.assertRaises(WebSocketDisconnect) as ctx:
                    with self.client.websocket_connect(f'/api/capture/sessions/{sid}/websockify', headers={'origin': origin}): pass
                self.assertEqual(ctx.exception.code, 1008)
        with patch('app.origin.scheme', return_value='https'):
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(f'/api/capture/sessions/{sid}/websockify', headers=ORIGIN): pass

    def test_the_capture_cookie_is_secure_exactly_when_origin_scheme_is_https(self):
        answer = self.client.get('/api/capture/sessions')
        cookie = answer.headers['set-cookie']
        self.assertIn('clab_capture_owner=', cookie); self.assertNotIn('Secure', cookie)
        self.assertIn('HttpOnly', cookie); self.assertIn('Path=/api/capture', cookie)
        secure = self.another(base_url='https://testserver')
        cookie = secure.get('/api/capture/sessions', headers={'origin': 'https://testserver'}).headers['set-cookie']
        self.assertIn('clab_capture_owner=', cookie); self.assertIn('Secure', cookie)
        with patch('app.origin.scheme', return_value='https'):
            fresh = self.another()
            self.assertIn('Secure', fresh.get('/api/capture/sessions').headers['set-cookie'])

    def test_every_owner_scoped_call_and_the_socket_send_sha256_of_cookie_and_user(self):
        sid = self.launch(self.client)
        cookie = self.client.cookies.get('clab_capture_owner')
        self.assertTrue(capture_sessions.TOKEN.fullmatch(cookie))
        with patch.dict(capture_sessions.VIEWER_ASSETS, {'core/rfb.js': hashlib.sha256(b'export default class RFB {}').hexdigest()}):
            self.assertEqual(self.client.get(f'/api/capture/sessions/{sid}/assets/core/rfb.js').status_code, 200)
        self.assertEqual(self.client.get(f'/api/capture/sessions/{sid}/download').content, b'synthetic-tar')
        self.assertEqual(self.client.get(f'/api/capture/sessions/{sid}').status_code, 200)
        self.assertEqual([s['id'] for s in self.client.get('/api/capture/sessions').json()['sessions']], [sid])
        ws = self.socket(self.client, sid); ws.close()
        self.assertEqual(self.client.post(f'/api/capture/sessions/{sid}/end', json={}).status_code, 200)
        self.launch(self.client, rid='2')
        self.assertEqual(self.client.post('/api/capture/sessions/end-all', json={}).json()['ended'], 1)
        expected = identity(cookie, 'tester')
        owners = [o for o in self.broker.owners if o]
        self.assertGreaterEqual(len(owners), 9)
        self.assertTrue(set(owners) == {expected}, 'every owner-scoped call names sha256(cookie, newline, user)')
        self.assertFalse(any(cookie in str(h) for h in self.broker.headers), 'the raw cookie never reaches the service')
        assert_not_logged(self.app, cookie, self.client.session_cookie())

    def test_a_second_person_in_the_same_browser_never_reaches_the_first_persons_desktops(self):
        self.another(role='operator', name='olga')        # creates olga and completes her forced change elsewhere
        sid = self.launch(self.client)
        # The next person signs in over the live session in the same browser: the owner cookie stays.
        self.assertEqual(sign_in(self.client, 'olga', PASSWORD)['user']['name'], 'olga')
        self.assertEqual(self.client.get('/api/capture/sessions').json()['sessions'], [])
        self.assertEqual(self.client.get(f'/api/capture/sessions/{sid}').status_code, 404)
        self.assertEqual(self.client.get(f'/api/capture/sessions/{sid}/download').status_code, 404)
        self.assertEqual(self.client.post(f'/api/capture/sessions/{sid}/end', json={}).status_code, 404)
        self.assertEqual(self.client.post('/api/capture/sessions/end-all', json={}).json(), {'ended': 0, 'failed': []})
        with self.assertRaises(WebSocketDisconnect):   # refused before or right after the handshake: the service knows no such owner
            with self.client.websocket_connect(f'/api/capture/sessions/{sid}/websockify', headers=ORIGIN) as ws: ws.receive_bytes()
        self.assertIn(sid, self.broker.rows, 'nothing of the first person was ended')
        # The first person, signing in again in this browser, finds the desktop session.
        sign_in(self.client, 'tester', PASSWORD)
        self.assertEqual([s['id'] for s in self.client.get('/api/capture/sessions').json()['sessions']], [sid])
        ws = self.socket(self.client, sid); ws.close()

    def test_the_capture_service_image_still_imports_with_only_its_four_manager_files(self):
        # deploy/capture/Dockerfile copies app/__init__.py, capture.py, capture_sessions.py and capture_service.py only.
        import shutil, subprocess, sys
        from pathlib import Path
        source = Path(capture_sessions.__file__).parent
        with tempfile.TemporaryDirectory() as root:
            (Path(root)/'app').mkdir()
            for name in ('__init__.py', 'capture.py', 'capture_sessions.py', 'capture_service.py'):
                shutil.copy(source/name, Path(root)/'app'/name)
            answer = subprocess.run([sys.executable, '-I', '-c', 'import sys; sys.path.insert(0, "."); import app.capture_service'], cwd=root, capture_output=True, text=True,
                                    env={'PATH': '/usr/bin:/bin'})
        self.assertEqual(answer.returncode, 0, answer.stderr[-2000:])

    def test_a_desktop_launched_before_this_release_with_the_raw_cookie_is_found_by_nobody(self):
        self.client.get('/api/capture/sessions')
        cookie = self.client.cookies.get('clab_capture_owner')
        self.broker.rows['f' * 64] = cookie
        self.assertEqual(self.client.get('/api/capture/sessions').json()['sessions'], [])


if __name__ == '__main__':
    unittest.main()
