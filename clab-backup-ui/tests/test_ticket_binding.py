"""The terminal ticket is bound to the session that minted it (sign-on DESIGN.md 11.1, ruling 9; BUILD.md S2).

A ticket is `(expiry, lab_id, name, protocol, session_id)`; the socket compares the fifth element with its own
session's id through `hmac.compare_digest`, so a ticket shown on a socket of another session is refused (and
burnt), and `node_services` drops the tickets of a session the moment it ends (`sessions.on_end`). A ticket
therefore outlives neither its 30 s nor its session. Session ids and ticket keys are never printed: every
comparison below is an `assertTrue` of an equality, not an `assertEqual` of two values.
"""
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from session_fixture import PASSWORD, SignedInClient, assert_not_logged, sign_out
from starlette.websockets import WebSocketDisconnect

from app import node_services
from app.main import create_app
from app.sessions import IDLE, SessionGate

ORIGIN = {'origin': 'http://testserver'}


def lab():
    return {'id': 'lab', 'name': 'Example', 'profiles': [], 'defaults': {}, 'interval': 30, 'next_run': 123456,
            'nodes': [{'name': 'r1', 'address': '192.0.2.1', 'port': 22, 'platform': 'arista_ceos',
                       'username': 'user', 'password': 'never-log-this', 'profile_id': '', 'enabled': True}]}


class TicketBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.a = SignedInClient(self.app)          # completes setup as tester: session A
        self.b = SignedInClient(self.app)          # signs in as tester again: session B, same user, another browser
        self.app.state.store.state['labs'].append(lab())
        self.services = self.app.state.node_services
        self.sessions = self.app.state.sessions

    def tearDown(self):
        self.services.close(); self.app.state.runner.close()
        self.a.close(); self.b.close(); self.tmp.cleanup()

    def ticket(self, client, **extra):
        result = client.post('/api/labs/lab/terminal-ticket', json={'name': 'r1', **extra})
        self.assertEqual(result.status_code, 200, result.status_code)
        return result.json()['ticket']

    def refused(self, client, key):
        """Presents `key` on a socket of `client`: the socket must close 1008 without any SSH work."""
        ssh = MagicMock(); connect = MagicMock()
        with patch('app.node_services.paramiko.SSHClient', ssh), patch('app.node_services.connect', connect):
            with client.websocket_connect('/api/terminal', headers=ORIGIN) as ws:
                ws.send_json({'ticket': key})
                with self.assertRaises(WebSocketDisconnect) as ctx: ws.receive_json()
        self.assertEqual(ctx.exception.code, 1008)
        ssh.assert_not_called(); connect.assert_not_called()
        self.assertFalse(self.services.clients)

    def opens(self, client, key):
        channel = MagicMock(); channel.closed = False
        channel.recv_ready.side_effect = [True] + [False] * 100
        channel.recv.return_value = b'router# '
        channel.exit_status_ready.return_value = False
        ssh = MagicMock(); ssh.invoke_shell.return_value = channel
        with patch('app.node_services.paramiko.SSHClient', return_value=ssh), patch('app.node_services.connect'):
            with client.websocket_connect('/api/terminal', headers=ORIGIN) as ws:
                ws.send_json({'ticket': key})
                self.assertEqual(ws.receive_json()['message'], 'Connected')
                self.assertEqual(ws.receive_bytes(), b'router# ')
        ssh.close.assert_called()

    def test_the_ticket_carries_the_minting_sessions_id_as_its_fifth_element(self):
        key = self.ticket(self.a)
        entry = self.services.tickets[key]
        self.assertEqual(len(entry), 5)
        self.assertEqual(entry[1:4], ('lab', 'r1', 'ssh'))
        self.assertTrue(entry[4] == self.a.session_cookie(), 'the ticket names session A')
        self.assertFalse(entry[4] == self.b.session_cookie())
        self.assertFalse(entry[4] in self.a.post('/api/labs/lab/terminal-ticket', json={'name': 'r1'}).text)
        assert_not_logged(self.app, key, self.a.session_cookie(), self.b.session_cookie(), PASSWORD)

    def test_a_ticket_minted_by_session_a_is_refused_on_a_socket_of_session_b_and_burnt(self):
        key = self.ticket(self.a)
        self.refused(self.b, key)
        self.assertFalse(key in self.services.tickets, 'a ticket shown to the wrong session is spent')
        self.refused(self.a, key)
        # The same user's own session uses its own ticket.
        self.opens(self.a, self.ticket(self.a))
        assert_not_logged(self.app, key, self.a.session_cookie(), self.b.session_cookie())

    def test_the_comparison_is_compare_digest_on_the_two_session_ids(self):
        key = self.ticket(self.a)
        seen = []
        real = node_services.hmac.compare_digest
        def recording(x, y):
            seen.append((x == self.a.session_cookie(), y == self.b.session_cookie())); return real(x, y)
        with patch('app.node_services.hmac.compare_digest', side_effect=recording):
            self.refused(self.b, key)
        self.assertEqual(seen, [(True, True)])

    def test_a_console_ticket_is_bound_the_same_way(self):
        with patch.object(node_services.NodeServices, 'console_target', return_value=('127.0.0.1', 5000)):
            key = self.ticket(self.a, protocol='console')
            self.assertTrue(self.services.tickets[key][4] == self.a.session_cookie())
            self.assertEqual(self.services.tickets[key][3], 'console')
            session = AsyncMock()
            with patch.object(node_services.NodeServices, 'console_session', session):
                with self.b.websocket_connect('/api/terminal', headers=ORIGIN) as ws:
                    ws.send_json({'ticket': key})
                    with self.assertRaises(WebSocketDisconnect) as ctx: ws.receive_json()
                self.assertEqual(ctx.exception.code, 1008)
                session.assert_not_awaited()
                mine = self.ticket(self.a, protocol='console')
                with self.a.websocket_connect('/api/terminal', headers=ORIGIN) as ws:
                    ws.send_json({'ticket': mine})
                    try: ws.receive_json()
                    except WebSocketDisconnect: pass
                self.assertEqual(session.await_count, 1)
                self.assertEqual(session.await_args.args[1:3], ('lab', 'r1'))

    def test_sign_out_drops_that_sessions_tickets_and_keeps_the_others(self):
        mine, theirs = self.ticket(self.a), self.ticket(self.b)
        self.assertEqual(sign_out(self.a).status_code, 200)
        self.assertFalse(mine in self.services.tickets)
        self.assertTrue(theirs in self.services.tickets)
        self.opens(self.b, theirs)

    def test_an_expired_session_drops_its_tickets_whether_the_gate_or_the_sweep_finds_it(self):
        for finder in ('gate', 'sweep'):
            with self.subTest(finder=finder):
                client = SignedInClient(self.app)
                try:
                    mine, theirs = self.ticket(client), self.ticket(self.b)
                    with self.sessions.lock:
                        self.sessions.sessions[client.session_cookie()]['last_seen'] -= IDLE + 1
                    if finder == 'gate': self.assertEqual(client.get('/api/state').status_code, 401)
                    else: self.sessions.sweep()
                    self.assertFalse(mine in self.services.tickets)
                    self.assertTrue(theirs in self.services.tickets)
                finally: client.close()

    def test_disabling_resetting_or_deleting_the_user_drops_its_tickets(self):
        for change in ('disable', 'reset', 'delete'):
            with self.subTest(change=change):
                operator = SignedInClient(self.app, role='operator', name='olga')
                try:
                    mine, admins = self.ticket(operator), self.ticket(self.a)
                    if change == 'disable': answer = self.a.patch('/api/users/olga', json={'disabled': True})
                    elif change == 'reset': answer = self.a.post('/api/users/olga/password', json={'password': 'a brand new staple battery'})
                    else: answer = self.a.request('DELETE', '/api/users/olga', json={})
                    self.assertEqual(answer.status_code, 200, answer.status_code)
                    self.assertFalse(mine in self.services.tickets)
                    self.assertTrue(admins in self.services.tickets)
                    # The operator's session is gone too, so the gate refuses the socket at the handshake.
                    with self.assertRaises(WebSocketDisconnect) as ctx:
                        with operator.websocket_connect('/api/terminal', headers=ORIGIN): pass
                    self.assertEqual((ctx.exception.code, ctx.exception.reason), (1008, 'signed_out'))
                finally:
                    operator.close()
                    if change != 'delete': self.a.request('DELETE', '/api/users/olga', json={})

    def test_the_ticket_still_outlives_neither_its_30_seconds(self):
        key = self.ticket(self.a)
        entry = self.services.tickets[key]
        self.services.tickets[key] = (time.monotonic() - 1, *entry[1:])
        self.refused(self.a, key)

    def test_a_ticket_of_an_older_shape_is_refused_and_never_crashes_the_socket(self):
        for shape in ((time.monotonic() + 30, 'lab', 'r1', 'ssh'), (123, 'lab', 'r1'), ()):
            with self.subTest(length=len(shape)):
                self.services.tickets['old'] = shape
                self.refused(self.a, 'old')
                self.assertFalse('old' in self.services.tickets)

    def test_without_a_session_the_route_mints_nothing_and_the_socket_refuses_before_accept(self):
        # Behind the gate every non-exempt request has a user; this proves the handlers fail closed on their own.
        def no_user(gate, scope):
            scope.setdefault('state', {})['user'] = None
            return None
        with patch.object(SessionGate, 'decide', no_user):
            answer = self.a.post('/api/labs/lab/terminal-ticket', json={'name': 'r1'})
            self.assertEqual((answer.status_code, answer.json()['detail']['code']), (401, 'signed_out'))
            self.assertFalse(self.services.tickets)
            with self.assertRaises(WebSocketDisconnect) as ctx:
                with self.a.websocket_connect('/api/terminal', headers=ORIGIN): pass
        self.assertEqual((ctx.exception.code, ctx.exception.reason), (1008, 'signed_out'))


if __name__ == '__main__':
    unittest.main()
