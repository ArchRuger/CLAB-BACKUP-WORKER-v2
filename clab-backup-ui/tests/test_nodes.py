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
from app.inventory import IMAGE_DEFAULT_CREDENTIALS


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
        with patch('app.node_services.connect'):
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
        with patch('app.node_services.connect') as connect:
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

        with patch('app.node_services.connect', side_effect=fake_connect):
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
