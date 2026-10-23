import copy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import create_app
from app.node_readiness import login_state
from app.inventory import IMAGE_DEFAULT_CREDENTIALS


class CliStream:
    def __init__(self, data=b''):
        self.data = data

    def read(self, size):
        return self.data[:size]

    def close(self):
        pass


class CliTransport:
    def __init__(self):
        self.closed = threading.Event()

    def close(self):
        self.closed.set()


class CliClient:
    """Stands in for the SSH client after connect(): records the command and answers (or not)."""
    def __init__(self, output=b'', error=None):
        self.output = output; self.error = error; self.commands = []; self.transport = CliTransport()

    def get_transport(self):
        return self.transport

    def exec_command(self, command, timeout=None):
        self.commands.append(command)
        if self.error: raise self.error
        return CliStream(), CliStream(self.output), CliStream()

    def close(self):
        pass


class HungCliClient(CliClient):
    """The device accepted the SSH session but never answers the exec request; only closing the transport ends the wait
    (it gives up by itself after `limit`, so a missing deadline fails the test instead of hanging it)."""
    def __init__(self, limit=3):
        super().__init__(); self.limit = limit; self.waiting = threading.Event()

    def exec_command(self, command, timeout=None):
        self.commands.append(command); self.waiting.set()
        self.transport.closed.wait(self.limit)
        raise OSError('Channel closed.')


class NodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.auth = {'Authorization': 'Bearer ' + self.app.state.store.token}
        self.lab = {'id': 'lab', 'name': 'Example', 'profiles': [], 'defaults': {}, 'interval': 30,
                    'next_run': 123456, 'nodes': [
                        {'name': name, 'address': '192.0.2.1', 'port': 22, 'platform': platform,
                         'username': 'user', 'password': 'never-log-this', 'profile_id': '', 'enabled': enabled}
                        for name, platform, enabled in [('r1', 'arista_ceos', True), ('r2', 'arista_ceos', False), ('linux', '', False)]]}
        self.app.state.store.state['labs'].append(self.lab)
        self.services = self.app.state.node_services

    def tearDown(self):
        self.services.close()
        self.app.state.runner.close()
        self.client.close()
        self.tmp.cleanup()

    def post(self, path, data):
        return self.client.post(path, headers=self.auth, json=data)

    def test_targeted_backup_preserves_schedule_and_ignores_other_readiness(self):
        self.lab['nodes'][0]['password'] = ''
        with patch.object(self.app.state.runner.pool, 'submit') as submit:
            result = self.post('/api/labs/lab/jobs', {'operation': 'backup', 'node_names': ['r2']})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual([n['name'] for n in result.json()['nodes']], ['r2'])
            self.assertEqual(self.lab['next_run'], 123456)
            self.assertEqual(submit.call_args.args[3][0]['name'], 'r2')
        self.assertNotIn('never-log-this', result.text)

    def test_invalid_targets_never_submit(self):
        with patch.object(self.app.state.runner.pool, 'submit') as submit:
            for names in [[], ['missing'], ['r1', 'r1'], ['linux']]:
                response = self.post('/api/labs/lab/jobs', {'node_names': names})
                self.assertEqual(response.status_code, 400, response.text)
            submit.assert_not_called()

    def test_resource_monitoring_removed_without_destroying_existing_state(self):
        self.lab['monitor_host'] = 'legacy-host'
        self.lab['nodes'][0]['container_name'] = 'legacy-container'
        self.app.state.store.save()
        state = self.client.get('/api/state', headers=self.auth).json()
        self.assertNotIn('monitoring_enabled', state)
        self.assertNotIn('monitor_host', state['labs'][0])
        self.assertNotIn('container_name', state['labs'][0]['nodes'][0])
        health = self.client.get('/api/labs/lab/health', headers=self.auth).json()
        self.assertEqual(set(health), {'nodes'})
        self.assertEqual(set(health['nodes'][0]), {'name', 'ssh', 'backup'})
        self.assertEqual(self.post('/api/monitoring/report', {'host': 'host', 'containers': []}).status_code, 404)
        response = self.client.put('/api/labs/lab/monitoring', headers=self.auth, json={'host': 'host'})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.lab['monitor_host'], 'legacy-host')
        self.assertEqual(self.lab['nodes'][0]['password'], 'never-log-this')
        self.assertEqual(self.lab['next_run'], 123456)

    def test_linux_profile_and_sanitized_login_check(self):
        self.lab['nodes'][2]['password'] = ''
        response = self.client.post('/api/labs/lab/profiles', headers=self.auth,
            data={'label': 'Linux', 'platform': 'ssh', 'username': 'root', 'auth': 'password', 'password': 'secret'})
        self.assertEqual(response.status_code, 200, response.text)
        # A generic default supports imported Linux nodes without assigning NOS.
        public = self.client.get('/api/state', headers=self.auth).json()
        self.assertTrue(public['labs'][0]['nodes'][2]['ssh_ready'])
        self.assertFalse(public['labs'][0]['nodes'][2]['enabled'])
        with patch('app.node_services.connect', side_effect=ValueError('never-log-this')):
            result = self.post('/api/labs/lab/ssh-check', {'name': 'linux'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['status'], 'failed')
        self.assertNotIn('never-log-this', result.text)
        self.assertNotIn('never-log-this', self.client.get('/api/logs', headers=self.auth).text)
        self.assertFalse(self.services.clients)
        with patch('app.node_services.connect'), patch('app.node_services.cli_answers', return_value=True):
            self.assertEqual(self.post('/api/labs/lab/ssh-check', {'name': 'linux'}).json()['status'], 'reachable')

    def test_linux_image_default_login_no_credential_profile_needed(self):
        multitool = next(iter(IMAGE_DEFAULT_CREDENTIALS))
        username, password = IMAGE_DEFAULT_CREDENTIALS[multitool]
        self.lab['nodes'].append({'name': 'host1', 'address': '172.20.20.105', 'port': 22, 'platform': '',
                                  'image': multitool + ':latest', 'username': '', 'password': '',
                                  'profile_id': '', 'enabled': False})
        public = self.client.get('/api/state', headers=self.auth).json()
        row = next(n for n in public['labs'][0]['nodes'] if n['name'] == 'host1')
        self.assertEqual(row['image'], multitool + ':latest')
        self.assertEqual(row['credential_source'], 'default')
        self.assertTrue(row['login_configured'])
        self.assertFalse(row['inventory_credentials'])
        # Backups stay disabled (no NOS platform); the reason is not "needs credentials".
        self.assertEqual(row['readiness'], 'Choose NOS')
        self.assertNotEqual(row['readiness'], 'Needs credentials')
        with patch('app.node_services.connect') as connect, patch('app.node_services.cli_answers', return_value=True):
            result = self.post('/api/labs/lab/ssh-check', {'name': 'host1'})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['status'], 'reachable')
        used = connect.call_args.args[2]
        self.assertEqual((used['username'], used['password']), (username, password))
        self.assertNotIn(password, result.text)
        self.assertNotIn(password, self.client.get('/api/logs', headers=self.auth).text)

    def test_a_different_linux_image_still_needs_credentials(self):
        self.lab['nodes'].append({'name': 'host2', 'address': '172.20.20.106', 'port': 22, 'platform': '',
                                  'image': 'ghcr.io/library/alpine:latest', 'username': '', 'password': '',
                                  'profile_id': '', 'enabled': False})
        public = self.client.get('/api/state', headers=self.auth).json()
        row = next(n for n in public['labs'][0]['nodes'] if n['name'] == 'host2')
        self.assertEqual(row['credential_source'], '')
        self.assertFalse(row['login_configured'])
        result = self.post('/api/labs/lab/ssh-check', {'name': 'host2'})
        self.assertEqual(result.status_code, 400)

    def ticket(self):
        result = self.post('/api/labs/lab/terminal-ticket', {'name': 'r1'})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()['ticket']

    def test_terminal_rejects_origin_invalid_expired_and_reused_ticket(self):
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/terminal', headers={'origin': 'http://evil.test'}):
                pass
        key = self.ticket()
        entry = self.services.tickets[key]
        self.services.tickets[key] = (time.monotonic()-1, *entry[1:])
        for token in ['invalid', key, key]:
            with self.client.websocket_connect('/api/terminal', headers={'origin': 'http://testserver'}) as ws:
                ws.send_json({'ticket': token})
                with self.assertRaises(WebSocketDisconnect) as ctx:
                    ws.receive_json()
                self.assertEqual(ctx.exception.code, 1008)

    def test_terminal_roundtrip_resize_and_cleanup(self):
        key = self.ticket()
        channel = MagicMock()
        channel.closed = False
        channel.recv_ready.side_effect = [True] + [False]*100
        channel.recv.return_value = b'router# '
        channel.exit_status_ready.return_value = False
        client = MagicMock()
        client.invoke_shell.return_value = channel
        with patch('app.node_services.paramiko.SSHClient', return_value=client), patch('app.node_services.connect'):
            with self.client.websocket_connect('/api/terminal', headers={'origin': 'http://testserver'}) as ws:
                ws.send_json({'ticket': key})
                self.assertEqual(ws.receive_json()['message'], 'Connected')
                self.assertEqual(ws.receive_bytes(), b'router# ')
                ws.send_json({'type': 'resize', 'cols': 120, 'rows': 40})
                ws.send_json({'type': 'input', 'data': 'show version\r'})
                ws.send_json({'type': 'invalid'})
                self.assertEqual(ws.receive_json()['type'], 'error')
        channel.resize_pty.assert_called_once_with(width=120, height=40)
        channel.sendall.assert_called_once_with(b'show version\r')
        client.close.assert_called()
        self.assertFalse(self.services.clients)
        self.assertNotIn(key, self.services.tickets)
        logs = self.client.get('/api/logs', headers=self.auth).text
        self.assertIn('terminal.open', logs)
        self.assertNotIn('show version', logs)
        self.assertNotIn(key, logs)

    def test_terminal_close_is_logged_only_for_a_session_that_opened(self):
        # L-23: a failed login or shell start leaves no terminal.open, so it must leave no terminal.close.
        for failure in ('connect', 'invoke_shell'):
            key = self.ticket()
            client = MagicMock()
            if failure == 'invoke_shell':
                client.invoke_shell.side_effect = OSError('shell refused')
            connect = MagicMock(side_effect=ValueError('login refused')) if failure == 'connect' else MagicMock()
            with patch('app.node_services.paramiko.SSHClient', return_value=client), patch('app.node_services.connect', connect):
                with self.client.websocket_connect('/api/terminal', headers={'origin': 'http://testserver'}) as ws:
                    ws.send_json({'ticket': key})
                    self.assertEqual(ws.receive_json()['type'], 'error')
            client.close.assert_called()
            self.assertFalse(self.services.clients, 'the reserved client is still released')
            logs = self.client.get('/api/logs', headers=self.auth).text
            self.assertNotIn('terminal.open', logs, failure)
            self.assertNotIn('terminal.close', logs, failure)

    def test_session_limit(self):
        clients = [self.services.reserve() for _ in range(32)]
        self.assertEqual(self.post('/api/labs/lab/ssh-check', {'name': 'r1'}).status_code, 429)
        for client in clients:
            self.services.release(client)

    def test_ssh_check_all_skips_ineligible_nodes_with_a_reason_and_bounds_concurrency(self):
        # Six eligible nodes plus one of each ineligible reason ssh-check-all reports.
        self.lab['nodes'] = [
            {'name': f'n{i}', 'address': f'192.0.2.{i}', 'port': 22, 'platform': 'arista_ceos',
             'username': 'user', 'password': 'never-log-this', 'profile_id': '', 'enabled': True}
            for i in range(1, 7)
        ] + [
            {'name': 'off', 'address': '192.0.2.20', 'port': 22, 'platform': 'arista_ceos',
             'username': 'user', 'password': 'never-log-this', 'profile_id': '', 'enabled': False},
            {'name': 'noaddr', 'address': '', 'port': 22, 'platform': 'arista_ceos',
             'username': 'user', 'password': 'never-log-this', 'profile_id': '', 'enabled': True},
            # No platform (and no image): effective_credentials() finds neither a profile, saved
            # credentials nor a containerlab/image default, so this one is truly "needs credentials".
            {'name': 'nocreds', 'address': '192.0.2.21', 'port': 22, 'platform': '',
             'username': '', 'password': '', 'profile_id': '', 'enabled': True},
        ]
        lock = threading.Lock(); counters = {'concurrent': 0, 'peak': 0}
        release = threading.Event()

        def fake_connect(client, node, creds):
            with lock:
                counters['concurrent'] += 1; counters['peak'] = max(counters['peak'], counters['concurrent'])
            release.wait(2)
            with lock:
                counters['concurrent'] -= 1
            if node['name'] == 'n6':
                raise ValueError('never-log-this-either')

        with patch('app.node_services.connect', side_effect=fake_connect), patch('app.node_services.cli_answers', return_value=True):
            result = self.post('/api/labs/lab/ssh-check-all', {})
            self.assertEqual(result.status_code, 200, result.text)
            body = result.json()
            # 'off' is excluded from backups only; its login is still tested (a Linux host
            # such as the multitool is never backed up but has a working login).
            self.assertEqual(body['started'], 7)
            self.assertIn('at', body)
            self.assertEqual(sorted(body['skipped'], key=lambda s: s['name']), [
                {'name': 'noaddr', 'reason': 'no address'},
                {'name': 'nocreds', 'reason': 'needs credentials'},
            ])
            deadline = time.monotonic() + 2
            while counters['peak'] < 4 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(counters['peak'], 4, 'ssh-check-all never opens more than 4 SSH sessions at once')
            release.set()
            deadline = time.monotonic() + 2
            while self.services.checking_all and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertFalse(self.services.checking_all)
        health = {row['name']: row['ssh'] for row in self.client.get('/api/labs/lab/health', headers=self.auth).json()['nodes']}
        for i in range(1, 6):
            self.assertEqual(health[f'n{i}']['status'], 'reachable', f"n6 failing did not stop n{i}")
        self.assertEqual(health['n6']['status'], 'failed')
        self.assertEqual(health['off']['status'], 'reachable', 'excluded from backups, but its login is still tested')
        for name in ('noaddr', 'nocreds'):
            self.assertIsNone(health[name], f'{name} was skipped, never attempted')
        self.assertNotIn('never-log-this-either', self.client.get('/api/logs', headers=self.auth).text)

    def test_test_login_asks_the_cli_and_marks_reachable_only_on_a_real_answer(self):
        # M-11: authenticating over SSH is not readiness; show version (or the generic command for a
        # node without a platform) must answer, the same check the readiness monitor's probe makes.
        from app.node_services import REACHABLE_MESSAGE
        for name, command in (('r1', 'show version'), ('linux', 'echo readiness-check')):
            cli = CliClient(b'Arista cEOSLab\nSoftware image version: 4.35.0F\n')
            with patch('app.node_services.paramiko.SSHClient', return_value=cli), patch('app.node_services.connect'):
                result = self.post('/api/labs/lab/ssh-check', {'name': name}).json()
            self.assertEqual(result['status'], 'reachable', name)
            self.assertEqual(cli.commands, [command], name)
        for output, error in ((b'', None), (b'% System is not yet ready. Please try again later.\n', None), (b'', TimeoutError('slow'))):
            cli = CliClient(output, error)
            with patch('app.node_services.paramiko.SSHClient', return_value=cli), patch('app.node_services.connect'):
                response = self.post('/api/labs/lab/ssh-check', {'name': 'r1'})
            result = response.json()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(result['status'], 'booting', 'a login that authenticates while the CLI is starting is not ready')
            self.assertIn('CLI', result['message']); self.assertNotEqual(result['message'], REACHABLE_MESSAGE)
            stored = self.services.checks[('lab', 'r1')]
            self.assertEqual(stored['status'], 'booting')
            # In a lab linked to a VM deployment (where readiness is monitored) Open CLI waits for a real answer,
            # and the monitor's own probe (which skips only 'reachable' nodes) will replace this result.
            shown = login_state({'deployment_name': 'clab-demo'}, self.lab['nodes'][0], True, stored)
            self.assertEqual(shown['status'], 'booting', 'Open CLI is not offered before the CLI answers')
        self.assertFalse(self.services.clients)
        logs = self.client.get('/api/logs', headers=self.auth).text
        self.assertNotIn('never-log-this', logs); self.assertNotIn('not yet ready', logs)

    def test_test_login_counts_any_real_answer_from_a_node_without_a_platform(self):
        # N2 (M-11 follow-up): a NOS kind outside the supported four is stored with platform '' and asked the generic shell
        # command; its CLI rejects it, and that rejection is an answering CLI (before M-11 a manual Test login made such a
        # node ready, after it nothing could). The monitor's probe and Test login / Test logins decide every case alike.
        from app.node_readiness import ReadinessMonitor
        monitor = ReadinessMonitor(self.app.state.store, self.services, None)
        self.addCleanup(monitor.close)
        rejecting = (b"           ^\n% Invalid input detected at '^' marker.\n\nrouter#", b'error: unknown command: echo\n')
        cases = [('linux', b'readiness-check\n', 'reachable')] + [('linux', output, 'reachable') for output in rejecting] + [
            ('linux', b'', 'booting'), ('linux', b'% System is not yet ready. Please try again later.\n', 'booting'),
            ('linux', b'error: could not connect to agent\n', 'booting'), ('linux', b'Waiting for editing of configuration\n', 'booting'),
            ('r1', rejecting[0], 'booting'), ('r1', b'% System is not yet ready\n', 'booting'), ('r1', b'Arista cEOSLab\n', 'reachable')]
        for name, output, expected in cases:
            node = next(n for n in self.lab['nodes'] if n['name'] == name)
            with patch('app.node_services.paramiko.SSHClient', return_value=CliClient(output)), patch('app.node_services.connect'), \
                 patch('app.node_readiness.connect'):
                manual = self.post('/api/labs/lab/ssh-check', {'name': name}).json()
                probed = monitor.ssh_probe(node, {'username': 'user', 'password': 'x'})
            self.assertEqual((manual['status'], probed), (expected, expected), (name, output))
        self.services.checks.clear()
        with patch('app.node_services.paramiko.SSHClient', return_value=CliClient(rejecting[0])), patch('app.node_services.connect'):
            self.assertEqual(self.post('/api/labs/lab/ssh-check-all', {}).status_code, 200)
            deadline = time.monotonic() + 3
            while (self.services.checking_all or len(self.services.checks) < 3) and time.monotonic() < deadline:
                time.sleep(0.01)
        bulk = {k[1]: v['status'] for k, v in self.services.checks.items()}
        self.assertEqual(bulk, {'r1': 'booting', 'r2': 'booting', 'linux': 'reachable'}, 'Test logins applies the same rule')
        self.assertFalse(self.services.clients)

    def test_a_hung_exec_ends_test_login_as_booting_within_the_cli_timeout_and_frees_the_node(self):
        # N3 (M-11 follow-up): Test login runs the CLI check in the request thread while the node's 'checking' key and an SSH
        # client slot are held. A device that accepts the session but never answers the exec request used to hold both
        # until it gave up, and every further Test login of that node answered 409 'already running'.
        hung = HungCliClient()
        outcome = {}
        def first():
            with patch('app.node_services.paramiko.SSHClient', return_value=hung), patch('app.node_services.connect'):
                started = time.monotonic()
                outcome['response'] = self.post('/api/labs/lab/ssh-check', {'name': 'r1'})
                outcome['elapsed'] = time.monotonic() - started
        with patch('app.node_services.CLI_TIMEOUT', 0.5):
            worker = threading.Thread(target=first); worker.start()
            self.assertTrue(hung.waiting.wait(2))
            self.assertEqual(self.post('/api/labs/lab/ssh-check', {'name': 'r1'}).status_code, 409, 'still inside the deadline')
            worker.join(5)
        self.assertLess(outcome['elapsed'], 2, 'the hung exec ends at the stated CLI_TIMEOUT, not when the device gives up')
        self.assertEqual(outcome['response'].status_code, 200)
        self.assertEqual(outcome['response'].json()['status'], 'booting', 'a silent CLI is never ready')
        self.assertTrue(hung.transport.closed.is_set())
        self.assertNotIn(('lab', 'r1'), self.services.checking); self.assertFalse(self.services.clients)
        with patch('app.node_services.paramiko.SSHClient', return_value=CliClient(b'Arista cEOSLab\n')), patch('app.node_services.connect'):
            again = self.post('/api/labs/lab/ssh-check', {'name': 'r1'})
        self.assertEqual((again.status_code, again.json()['status']), (200, 'reachable'), 'the node is free for the next Test login')

    def test_booting_message_promises_a_recheck_only_for_a_lab_linked_to_a_vm_deployment(self):
        # M-11 follow-up: ReadinessMonitor.scan() skips a lab with no deployment_name (an inventory import),
        # so "the manager keeps checking" would be false there; the per-node route and Test logins agree.
        from app.node_services import BOOTING_MESSAGE
        def bulk_messages():
            self.services.checks.clear()
            with patch('app.node_services.paramiko.SSHClient', return_value=CliClient(b'')), patch('app.node_services.connect'):
                self.assertEqual(self.post('/api/labs/lab/ssh-check-all', {}).status_code, 200)
                deadline = time.monotonic() + 3
                while (self.services.checking_all or len(self.services.checks) < 3) and time.monotonic() < deadline:
                    time.sleep(0.01)
            return {k[1]: v['message'] for k, v in self.services.checks.items()}
        def single_message():
            with patch('app.node_services.paramiko.SSHClient', return_value=CliClient(b'')), patch('app.node_services.connect'):
                return self.post('/api/labs/lab/ssh-check', {'name': 'r1'}).json()['message']
        self.assertFalse(self.lab.get('deployment_name'))
        unlinked = single_message()
        self.assertNotIn('keeps checking', unlinked)
        self.assertNotEqual(unlinked, BOOTING_MESSAGE)
        self.assertIn('Test login', unlinked)
        self.assertEqual(set(bulk_messages().values()), {unlinked}, 'Test logins words it exactly as Test login does')
        self.lab['deployment_name'] = 'clab-demo'
        with patch('app.node_services.node_available', return_value=True):     # a linked node needs fresh discovery
            self.assertEqual(single_message(), BOOTING_MESSAGE)
            self.assertIn('keeps checking', BOOTING_MESSAGE)
            self.assertEqual(set(bulk_messages().values()), {BOOTING_MESSAGE})

    def test_test_logins_and_test_login_give_the_same_outcome(self):
        def bulk_run(cli):
            self.services.checks.clear()
            with patch('app.node_services.paramiko.SSHClient', return_value=cli), patch('app.node_services.connect'):
                self.assertEqual(self.post('/api/labs/lab/ssh-check-all', {}).status_code, 200)
                deadline = time.monotonic() + 3
                while (self.services.checking_all or len(self.services.checks) < 3) and time.monotonic() < deadline:
                    time.sleep(0.01)
            return {k[1]: (v['status'], v['message']) for k, v in self.services.checks.items()}
        with patch('app.node_services.paramiko.SSHClient', return_value=CliClient(b'')), patch('app.node_services.connect'):
            single = self.post('/api/labs/lab/ssh-check', {'name': 'r1'}).json()
        self.assertEqual(single['status'], 'booting')
        silent = bulk_run(CliClient(b''))
        self.assertEqual(silent['r1'], (single['status'], single['message']))
        self.assertEqual({status for status, _ in silent.values()}, {'booting'})
        answered = bulk_run(CliClient(b'Arista cEOSLab\n'))
        self.assertEqual({status for status, _ in answered.values()}, {'reachable'})
        self.assertEqual(set(answered), {'r1', 'r2', 'linux'})

    def test_ssh_check_all_is_debounced_against_itself_and_against_a_manual_check(self):
        release = threading.Event()
        with patch('app.node_services.connect', side_effect=lambda *a: release.wait(2)):
            first = self.post('/api/labs/lab/ssh-check-all', {})
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(first.json()['started'], 3, 'every node with an address and credentials is tested, whatever its backup flag')
            second = self.post('/api/labs/lab/ssh-check-all', {})
            self.assertEqual(second.status_code, 409)
            deadline = time.monotonic() + 2
            while not self.services.checking and time.monotonic() < deadline:
                time.sleep(0.01)
            manual = self.post('/api/labs/lab/ssh-check', {'name': 'r1'})
            self.assertEqual(manual.status_code, 409, "a manual check for a node the bulk run is already testing is blocked too")
            release.set()
            deadline = time.monotonic() + 2
            while self.services.checking_all and time.monotonic() < deadline:
                time.sleep(0.01)
            # Still patched: a real connect() here would leave a background probe running past teardown.
            third = self.post('/api/labs/lab/ssh-check-all', {})
            self.assertEqual(third.status_code, 200, 'the debounce clears once the run finishes')
            deadline = time.monotonic() + 2
            while self.services.checking_all and time.monotonic() < deadline:
                time.sleep(0.01)
        self.assertFalse(self.services.checking_all)

    def test_ssh_check_all_reports_nothing_started_when_every_node_is_skipped(self):
        # The backup flag never decides eligibility: only a missing address does here.
        for node in self.lab['nodes']:
            node['enabled'] = False
            node['address'] = ''
        result = self.post('/api/labs/lab/ssh-check-all', {})
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body['started'], 0)
        self.assertEqual({s['name'] for s in body['skipped']}, {'r1', 'r2', 'linux'})
        self.assertEqual({s['reason'] for s in body['skipped']}, {'no address'})
        self.assertFalse(self.services.checking_all, 'nothing was started, so the debounce clears immediately')

    def test_lab_builder_styles_are_scoped_to_its_document_and_only_its_assets_are_cached(self):
        builder = self.client.get('/static/lab-builder.html'); policy = builder.headers['content-security-policy']
        self.assertEqual(builder.status_code, 200)
        self.assertIn("style-src 'self' 'unsafe-inline'", policy); self.assertIn("script-src 'self';", policy)
        for refused in ('unsafe-eval', 'blob:', 'worker-src', 'http:', 'https:'): self.assertNotIn(refused, policy)
        self.assertEqual(builder.headers['cache-control'], 'no-store')
        # The map editor is the same editor over an existing lab's map: the same policy, nothing wider.
        editor = self.client.get('/static/map-editor.html'); self.assertEqual(editor.status_code, 200)
        self.assertEqual(editor.headers['content-security-policy'], policy)
        for other in ('/', '/static/map-editor-page.js', '/static/lab-builder-page.js', '/static/lab-builder.css', '/static/lab-builder/manifest.json'):
            response = self.client.get(other)
            self.assertNotIn('unsafe-inline', response.headers['content-security-policy'], other); self.assertEqual(response.headers['cache-control'], 'no-store', other)
        asset = self.client.get('/static/lab-builder/assets/main.js')
        self.assertEqual(asset.headers['cache-control'], 'public, max-age=31536000, immutable'); self.assertNotIn('unsafe-inline', asset.headers['content-security-policy'])
        self.assertEqual(self.client.get('/static/lab-builder/assets/absent.js').headers['cache-control'], 'no-store')

    def test_terminal_styles_are_scoped_to_terminal_document(self):
        terminal = self.client.get('/static/terminal.html')
        dashboard = self.client.get('/')
        self.assertIn("style-src 'self' 'unsafe-inline'", terminal.headers['content-security-policy'])
        self.assertIn("script-src 'self';", terminal.headers['content-security-policy'])
        self.assertNotIn('unsafe-inline', dashboard.headers['content-security-policy'])


# ---------------------------------------------------------------------------------------------------------------------
# C04 S1a: the serial console of the vrnetlab kinds (docs/parity-campaign/C04-DESIGN.md §2.2–2.4, §5). Everything below is
# new; the SSH tests above are the proof that the SSH branch of the ticket route and the socket did not change.

import socket
import socketserver
from app import inventory as app_inventory, node_services as console_module
from app.node_services import (CONSOLE_HELD, CONSOLE_KIND_UNKNOWN, CONSOLE_LIMIT, CONSOLE_LIMIT_SENTENCE, CONSOLE_NO_ADDRESS,
                               CONSOLE_NONE, CONSOLE_NOT_RUNNING, CONSOLE_OPEN_HERE, CONSOLE_RESTARTING, CONSOLE_STARTING,
                               CONSOLE_UNHEALTHY, CONSOLE_UNLINKED, CONSOLE_UNREACHABLE, CONSOLE_YOUNG, console_gate)
from app.node_console import BINARY, DO, ECHO, IAC, SGA, WILL

LIVE_NEGOTIATION = bytes([IAC, WILL, ECHO, IAC, WILL, SGA, IAC, WILL, BINARY, IAC, DO, BINARY])
LIVE_REPLIES = bytes([IAC, DO, ECHO, IAC, DO, SGA, IAC, DO, BINARY, IAC, WILL, BINARY])


class FakeConsole:
    """An in-process stand-in for qemu's telnet chardev on 127.0.0.1:0: sends `greeting` on accept (after `delay`),
    then each item of `script`, records every byte a client sends, counts connections and can close its side."""
    def __init__(self, greeting=LIVE_NEGOTIATION, script=(), delay=0.0, chatty=0.0):
        self.greeting = greeting; self.script = list(script); self.delay = delay; self.chatty = chatty
        self.received = {}; self.connections = 0; self.lock = threading.Lock(); self.sockets = []; self.closed = threading.Event()
        self.got = threading.Condition(self.lock)
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                with fake.lock:
                    fake.connections += 1; index = fake.connections; fake.received[index] = b''; fake.sockets.append(self.request)
                if fake.delay: time.sleep(fake.delay)
                try:
                    if fake.greeting: self.request.sendall(fake.greeting)
                    for item in fake.script:
                        time.sleep(0.05); self.request.sendall(item)
                    self.request.settimeout(0.1)
                    while not fake.closed.is_set():
                        try: data = self.request.recv(4096)
                        except socket.timeout:
                            if fake.chatty:
                                try: self.request.sendall(b'tick\r\n')
                                except OSError: return
                                time.sleep(fake.chatty)
                            continue
                        if not data: return
                        with fake.got:
                            fake.received[index] += data; fake.got.notify_all()
                except OSError:
                    return

        self.server = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True); self.thread.start()

    def wait_received(self, index, length, timeout=5):
        deadline = time.monotonic() + timeout
        with self.got:
            while len(self.received.get(index, b'')) < length:
                remaining = deadline - time.monotonic()
                if remaining <= 0: break
                self.got.wait(remaining)
            return self.received.get(index, b'')

    def close_clients(self):
        self.closed.set()
        for sock in self.sockets:
            try: sock.shutdown(socket.SHUT_RDWR)
            except OSError: pass

    def stop(self):
        self.close_clients(); self.server.shutdown(); self.server.server_close()


class ConsoleTests(unittest.TestCase):
    ORIGIN = {'origin': 'http://testserver'}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.auth = {'Authorization': 'Bearer ' + self.app.state.store.token}
        self.store = self.app.state.store
        self.services = self.app.state.node_services
        now = time.time()
        self.lab = {'id': 'lab', 'name': 'Example', 'profiles': [], 'defaults': {}, 'interval': 30, 'next_run': 123456,
                    'deployment_name': 'example', 'container_prefix': 'clab',
                    'nodes': [self.device('r1', 'juniper_vjunosswitch'), self.device('ceos', 'arista_ceos'),
                              {**self.device('inv', ''), 'definition_node': '', 'short_name': ''}]}
        self.store.state['labs'].append(self.lab)
        self.store.state['host'] = {**self.store.state.get('host', {}), 'enabled': True}
        self.store.state['discovery'] = {'ok': True, 'checked_epoch': now, 'inspected_epoch': now - 600, 'labs': {}}
        self.node = self.lab['nodes'][0]
        self.console = None

    def tearDown(self):
        if self.console is not None: self.console.stop()
        self.services.close()
        self.app.state.runner.close()
        self.client.close()
        self.tmp.cleanup()

    @staticmethod
    def device(name, kind):
        return {'name': name, 'short_name': name, 'definition_node': name, 'kind': kind, 'address': '127.0.0.1', 'port': 22,
                'platform': kind, 'username': '', 'password': '', 'profile_id': '', 'enabled': bool(kind), 'endpoint_mode': 'auto',
                'discovered': True, 'runtime_state': 'running', 'runtime_status': 'Up 2 hours (healthy)', 'discovered_address': '127.0.0.1'}

    def serve(self, **kwargs):
        """Start the fake console and route the vJunos-switch kind at its port (console_port reads the table at call time)."""
        self.console = FakeConsole(**kwargs)
        patcher = patch.dict(app_inventory.CONSOLE_PORTS, {'juniper_vjunosswitch': self.console.port}); patcher.start(); self.addCleanup(patcher.stop)
        return self.console

    def ticket(self, name='r1', protocol='console'):
        body = {'name': name, 'protocol': protocol} if protocol else {'name': name}
        return self.client.post('/api/labs/lab/terminal-ticket', headers=self.auth, json=body)

    def key(self, name='r1'):
        result = self.ticket(name); self.assertEqual(result.status_code, 200, result.text)
        return result.json()['ticket']

    def gate(self, node=None):
        with self.store.lock: return console_gate(self.store.state, self.lab, node or self.node)

    def logs(self):
        return self.client.get('/api/logs', headers=self.auth).text

    def read_until(self, ws, expected):
        """Collect binary frames until their concatenation is `expected`."""
        got = b''
        while len(got) < len(expected): got += ws.receive_bytes()
        self.assertEqual(got, expected)

    def test_console_ticket_refuses_each_cause_with_its_sentence(self):
        self.serve()
        cases = []
        def refused(status, key, sentence, name='r1'):
            result = self.ticket(name)
            self.assertEqual((result.status_code, result.json()['detail']), (status, sentence), name)
            node = next(n for n in self.lab['nodes'] if n['name'] == name)
            self.assertEqual(self.gate(node), (status, key, sentence), 'the gate and the ticket agree: the public row carries the same key')
            cases.append(key)
        refused(400, 'none', CONSOLE_NONE.format(device='ceos', kind='arista_ceos'), name='ceos')
        refused(409, 'kind_unknown', CONSOLE_KIND_UNKNOWN.format(device='inv'), name='inv')
        node = self.node; sentence = lambda template: template.format(device='r1')
        with patch.dict(node, runtime_state='exited'): refused(409, 'not_running', sentence(CONSOLE_NOT_RUNNING))
        with patch.dict(self.lab, deployment_name=''): refused(409, 'unlinked', sentence(CONSOLE_UNLINKED))
        with patch.dict(node, definition_node='', short_name=''): refused(409, 'unlinked', CONSOLE_UNLINKED.format(device='r1'))
        with patch.dict(node, discovered_address=''): refused(409, 'no_address', sentence(CONSOLE_NO_ADDRESS))
        with patch.dict(self.store.state, operations=[{'id': 'op', 'lab_id': 'lab', 'action': 'restart-node', 'node': 'r1', 'status': 'running'}]):
            refused(409, 'restarting', sentence(CONSOLE_RESTARTING))
        with patch.dict(node, runtime_status='Up 3 minutes (health: starting)'): refused(409, 'starting', sentence(CONSOLE_STARTING))
        with patch.dict(node, runtime_status='Up 23 minutes (unhealthy)'): refused(409, 'unhealthy', sentence(CONSOLE_UNHEALTHY))
        with patch.dict(node, runtime_status='Up 30 seconds'), patch.dict(self.store.state['discovery'], inspected_epoch=time.time() - 10):
            refused(409, 'young', sentence(CONSOLE_YOUNG))
        # A stale discovery pass reads as not running, never as a free console.
        with patch.dict(self.store.state['discovery'], checked_epoch=time.time() - 3600): refused(409, 'not_running', sentence(CONSOLE_NOT_RUNNING))
        self.assertEqual(cases, ['none', 'kind_unknown', 'not_running', 'unlinked', 'unlinked', 'no_address', 'restarting', 'starting', 'unhealthy', 'young', 'not_running'])
        self.assertEqual(self.console.connections, 0, 'a refusal never connects')
        # The inspection time counts: the same status seen 200 s ago is past the settle floor.
        with patch.dict(node, runtime_status='Up 30 seconds'), patch.dict(self.store.state['discovery'], inspected_epoch=time.time() - 200):
            self.assertIsNone(self.gate()); self.assertEqual(self.ticket().status_code, 200)
        result = self.ticket(); self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual((body['protocol'], body['endpoint'], body['expires_in']), ('console', f'127.0.0.1:{self.console.port}', 30))
        self.assertEqual(self.services.tickets[body['ticket']][1:], ('lab', 'r1', 'console'))
        self.assertIsNone(self.gate())
        # The SSH ticket of the same device still needs credentials, and its body without a protocol is still SSH.
        with patch.dict(node, profile_id='gone'):
            self.assertEqual(self.ticket(protocol='').status_code, 400)
            self.assertEqual(self.ticket(protocol='ssh').status_code, 400)
        ssh = self.ticket(protocol=''); self.assertEqual(ssh.status_code, 200, ssh.text)
        self.assertEqual((ssh.json()['protocol'], ssh.json()['endpoint']), ('ssh', '127.0.0.1:22'))
        self.assertEqual(self.services.tickets[ssh.json()['ticket']][1:], ('lab', 'r1', 'ssh'))
        self.assertEqual(self.ticket(protocol='telnet').status_code, 422)
        self.assertEqual(self.ticket(name='missing').status_code, 404)
        self.assertFalse(self.services.clients)

    def test_console_roundtrip_strips_iac_answers_options_and_ignores_resize(self):
        self.serve(script=[b'login: ', b'\xff\xff\xff\xfb\x01x'])   # one literal 0xFF, a stray WILL ECHO, x
        key = self.key()
        with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
            ws.send_json({'ticket': key})
            self.assertEqual(ws.receive_json(), {'type': 'status', 'message': 'Connected'})
            self.read_until(ws, b'login: \xffx')
            ws.send_json({'type': 'resize', 'cols': 120, 'rows': 40})
            ws.send_json({'type': 'input', 'data': 'admin\r'})
            self.assertEqual(self.console.wait_received(1, len(LIVE_REPLIES) + 6), LIVE_REPLIES + b'admin\r')
            self.assertEqual(set(self.services.consoles), {('lab', 'r1')})
            self.assertFalse(self.services.clients, 'a console is not an SSH client')
            self.console.close_clients()
            self.assertEqual(ws.receive_json(), {'type': 'status', 'message': 'The console closed: the device stopped or restarted.'})
            with self.assertRaises(WebSocketDisconnect): ws.receive_json()
        deadline = time.monotonic() + 2
        while self.services.consoles and time.monotonic() < deadline: time.sleep(0.02)
        self.assertEqual(self.services.consoles, {})
        self.assertNotIn(key, self.services.tickets)
        logs = self.logs()
        self.assertIn('console.open', logs); self.assertIn('console.close', logs)
        self.assertIn('Serial console opened', logs)
        opened = [e for e in json.loads(logs)['events'] if e['action'] in ('console.open', 'console.close')]
        self.assertEqual([(e['action'], e['lab_id'], e['node']) for e in opened], [('console.close', 'lab', 'r1'), ('console.open', 'lab', 'r1')])
        for secret in ('admin', key, '127.0.0.1', 'login', str(self.console.port)):
            self.assertNotIn(secret, logs, secret)

    def test_console_second_open_for_the_same_device_is_refused_without_connecting(self):
        self.serve()
        first = self.key()
        with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
            ws.send_json({'ticket': first})
            self.assertEqual(ws.receive_json()['message'], 'Connected')
            opened_at = self.services.consoles[('lab', 'r1')]['opened']
            second = self.key()   # the ticket passes: the per-device check is the socket's
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as other:
                other.send_json({'ticket': second})
                frame = other.receive_json()
                self.assertEqual(frame['type'], 'error')
                self.assertEqual(frame['message'], CONSOLE_OPEN_HERE.format(device='r1', time=time.strftime('%H:%M', time.gmtime(opened_at))))
                self.assertRegex(frame['message'], r'since \d\d:\d\d UTC')
                with self.assertRaises(WebSocketDisconnect): other.receive_json()
            time.sleep(0.1)
            self.assertEqual(self.console.connections, 1, 'the refused open never connected')
            self.assertIn(('lab', 'r1'), self.services.consoles, 'the refused open never pops the first record')
            self.assertEqual(self.services.consoles[('lab', 'r1')]['opened'], opened_at)
            ws.send_json({'type': 'input', 'data': 'still here\r'})
            self.assertEqual(self.console.wait_received(1, len(LIVE_REPLIES) + 11), LIVE_REPLIES + b'still here\r')
        time.sleep(0.1)
        logs = json.loads(self.logs())['events']
        self.assertEqual(sum(e['action'] == 'console.open' for e in logs), 1)
        self.assertEqual(sum(e['action'] == 'console.close' for e in logs), 1)

    def test_console_held_by_an_outside_client_is_reported_within_the_probe_timeout_and_left(self):
        self.serve(greeting=b'')   # accepts and sends nothing: the launcher, or a client outside this manager, holds it
        key = self.key()
        with patch.object(console_module, 'CONSOLE_PROBE_TIMEOUT', 0.3):
            started = time.monotonic()
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                ws.send_json({'ticket': key})
                frame = ws.receive_json()
            elapsed = time.monotonic() - started
        self.assertEqual(frame, {'type': 'error', 'message': CONSOLE_HELD.format(device='r1')})
        self.assertLess(elapsed, 2)
        # The server sees EOF: its handler's recv returns b'', it leaves, and the server closes its socket (fileno -1).
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and (not self.console.sockets or self.console.sockets[0].fileno() != -1): time.sleep(0.02)
        self.assertEqual(self.console.connections, 1)
        self.assertEqual(self.console.sockets[0].fileno(), -1, 'the manager left the held console')
        self.assertEqual(self.console.received[1], b'', 'nothing was written before the first byte arrived')
        self.assertEqual(self.services.consoles, {})
        logs = self.logs()
        self.assertNotIn('console.open', logs); self.assertNotIn('console.close', logs)

    def test_console_connect_failure_limit_and_socket_time_refusals(self):
        self.serve()
        unused = socket.socket(); unused.bind(('127.0.0.1', 0)); port = unused.getsockname()[1]; unused.close()
        with patch.dict(app_inventory.CONSOLE_PORTS, {'juniper_vjunosswitch': port}):
            key = self.key()
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                ws.send_json({'ticket': key})
                frame = ws.receive_json()
        self.assertEqual(frame, {'type': 'error', 'message': CONSOLE_UNREACHABLE.format(device='r1', port=port)})
        self.assertIn('in use by another client', frame['message']); self.assertIn('stopping or restarting', frame['message'])
        # Eight records already held: the ninth is refused before any connect.
        sentinels = {('other', f'n{i}'): {'opened': time.time(), 'writer': None} for i in range(CONSOLE_LIMIT)}
        with patch.dict(self.services.consoles, sentinels):
            key = self.key()
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                ws.send_json({'ticket': key})
                self.assertEqual(ws.receive_json(), {'type': 'error', 'message': CONSOLE_LIMIT_SENTENCE})
        self.assertEqual(self.console.connections, 0)
        # A device that stopped between the ticket and the socket: the gate's sentence, verbatim, not 'Session ended.'
        key = self.key()
        with patch.dict(self.node, runtime_state='exited'):
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                ws.send_json({'ticket': key})
                self.assertEqual(ws.receive_json(), {'type': 'error', 'message': CONSOLE_NOT_RUNNING.format(device='r1')})
        key = self.key()
        with patch.dict(self.node, runtime_status='Up 1 minute (health: starting)'):
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                ws.send_json({'ticket': key})
                self.assertEqual(ws.receive_json(), {'type': 'error', 'message': CONSOLE_STARTING.format(device='r1')})
        self.assertEqual(self.console.connections, 0)
        self.assertEqual(self.services.consoles, {})
        logs = self.logs()
        self.assertNotIn('console.', logs)

    def wait_released(self):
        deadline = time.monotonic() + 3
        while self.services.consoles and time.monotonic() < deadline: time.sleep(0.02)
        self.assertEqual(self.services.consoles, {}, 'the slot is released')

    def test_console_total_time_cap_ends_the_session_while_the_device_keeps_sending(self):
        self.serve(chatty=0.05)
        key = self.key()
        with patch.object(console_module, 'CONSOLE_TOTAL', 0.8):
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                ws.send_json({'ticket': key})
                self.assertEqual(ws.receive_json()['message'], 'Connected')
                frame = None
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    message = ws.receive()
                    if message.get('text') and json.loads(message['text']).get('type') == 'status':
                        frame = json.loads(message['text']); break
                self.assertEqual(frame, {'type': 'status', 'message': 'Session timeout. Reconnect to continue.'})
        self.wait_released()

    def test_console_bad_frames_end_the_session_generically_and_write_nothing(self):
        bad = {'input that is not text': {'type': 'input', 'data': 5},
               'input over 16384 bytes': {'type': 'input', 'data': 'x' * 16385},
               'a message over 20000 characters': {'type': 'input', 'data': 'y' * 20001},
               'a resize outside the limits': {'type': 'resize', 'cols': 1, 'rows': 1},
               'an unknown type': {'type': 'bogus'}}
        for label, payload in bad.items():
            with self.subTest(label):
                self.serve(); self.services.consoles.clear()
                key = self.key()
                with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                    ws.send_json({'ticket': key})
                    self.assertEqual(ws.receive_json()['message'], 'Connected')
                    ws.send_json(payload)
                    frame = ws.receive_json()
                    while frame.get('type') == 'status': frame = ws.receive_json()
                    self.assertEqual(frame, {'type': 'error', 'message': 'Session ended.'})
                self.wait_released()
                time.sleep(0.2)
                self.assertEqual(self.console.received[1], LIVE_REPLIES, 'only the negotiation answers reached the device, nothing from the bad frame')
                self.console.stop(); self.console = None
                self.services.tickets.clear()

    def test_console_valid_resize_is_accepted_and_ignored_at_the_bounds(self):
        self.serve()
        key = self.key()
        with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
            ws.send_json({'ticket': key})
            self.assertEqual(ws.receive_json()['message'], 'Connected')
            for cols, rows in ((20, 5), (400, 150)): ws.send_json({'type': 'resize', 'cols': cols, 'rows': rows})
            ws.send_json({'type': 'input', 'data': 'ok\r'})
            self.assertEqual(self.console.wait_received(1, len(LIVE_REPLIES) + 3), LIVE_REPLIES + b'ok\r', 'only the input was written')

    def test_console_nine_concurrent_opens_never_exceed_the_cap(self):
        self.serve(delay=0.8)   # the negotiation arrives late: every socket is inside the connect-and-probe window at once
        for i in range(2, 10): self.lab['nodes'].append(self.device(f'r{i}', 'juniper_vjunosswitch'))
        keys = [self.key(f'r{i}') for i in range(1, 10)]
        sockets = []
        try:
            for key in keys:
                ws = self.client.websocket_connect('/api/terminal', headers=self.ORIGIN).__enter__()
                ws.send_json({'ticket': key}); sockets.append(ws)
            frames = [ws.receive_json() for ws in sockets]
        finally:
            for ws in sockets:
                try: ws.__exit__(None, None, None)
                except Exception: pass
        errors = [f for f in frames if f['type'] == 'error']
        self.assertEqual(len(errors), 1, frames)
        self.assertEqual(errors[0]['message'], CONSOLE_LIMIT_SENTENCE)
        self.assertEqual(sum(f == {'type': 'status', 'message': 'Connected'} for f in frames), CONSOLE_LIMIT)
        self.assertLessEqual(self.console.connections, CONSOLE_LIMIT)
        deadline = time.monotonic() + 3
        while self.services.consoles and time.monotonic() < deadline: time.sleep(0.02)
        self.assertEqual(self.services.consoles, {})

    def test_console_idle_clock_counts_browser_input_only(self):
        self.serve(chatty=0.05)   # the device prints every 50 ms; the browser never types
        key = self.key()
        with patch.object(console_module, 'CONSOLE_IDLE', 0.8):
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                ws.send_json({'ticket': key})
                self.assertEqual(ws.receive_json()['message'], 'Connected')
                started = time.monotonic(); frame = None; chunks = 0
                while time.monotonic() - started < 5:
                    message = ws.receive()
                    if 'bytes' in message and message['bytes'] is not None: chunks += 1; continue
                    if message.get('text'):
                        frame = json.loads(message['text']); break
                    if message['type'] == 'websocket.close': break
        self.assertEqual(frame, {'type': 'status', 'message': 'Session timeout. Reconnect to continue.'})
        self.assertGreater(chunks, 2, 'the device was printing while the session idled')
        self.assertLess(time.monotonic() - started, 4)

    def test_console_terminal_rejects_origin_invalid_expired_and_reused_ticket(self):
        self.serve()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/api/terminal', headers={'origin': 'http://evil.test'}):
                pass
        key = self.key()
        entry = self.services.tickets[key]
        self.services.tickets[key] = (time.monotonic() - 1, *entry[1:])
        for token in ['invalid', key, key]:
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
                ws.send_json({'ticket': token})
                with self.assertRaises(WebSocketDisconnect) as ctx:
                    ws.receive_json()
                self.assertEqual(ctx.exception.code, 1008)
        # A served ticket is single-use as well.
        key = self.key()
        with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
            ws.send_json({'ticket': key})
            self.assertEqual(ws.receive_json()['message'], 'Connected')
            with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as again:
                again.send_json({'ticket': key})
                with self.assertRaises(WebSocketDisconnect) as ctx: again.receive_json()
                self.assertEqual(ctx.exception.code, 1008)
        self.assertEqual(self.console.connections, 1)

    def test_console_close_shuts_open_sessions_and_the_sentences_carry_no_address(self):
        for sentence in (CONSOLE_KIND_UNKNOWN, CONSOLE_NONE, CONSOLE_UNLINKED, CONSOLE_NOT_RUNNING, CONSOLE_NO_ADDRESS, CONSOLE_RESTARTING,
                         CONSOLE_STARTING, CONSOLE_UNHEALTHY, CONSOLE_YOUNG, CONSOLE_OPEN_HERE, CONSOLE_HELD, CONSOLE_UNREACHABLE, CONSOLE_LIMIT_SENTENCE):
            self.assertNotIn('{address}', sentence)
        self.assertIn('{port}', CONSOLE_UNREACHABLE)
        self.serve()
        key = self.key()
        with self.client.websocket_connect('/api/terminal', headers=self.ORIGIN) as ws:
            ws.send_json({'ticket': key})
            self.assertEqual(ws.receive_json()['message'], 'Connected')
            self.assertEqual(len(self.services.consoles), 1)
            self.services.close()
            frame = ws.receive_json()
            self.assertIn(frame['message'], ('The console closed: the device stopped or restarted.', 'Session ended.'))
        self.assertEqual(self.services.consoles, {})
