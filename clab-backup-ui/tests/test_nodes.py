import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import create_app


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
        clients = [self.services.reserve() for _ in range(8)]
        self.assertEqual(self.post('/api/labs/lab/ssh-check', {'name': 'r1'}).status_code, 429)
        for client in clients:
            self.services.release(client)

    def test_terminal_styles_are_scoped_to_terminal_document(self):
        terminal = self.client.get('/static/terminal.html')
        dashboard = self.client.get('/')
        self.assertIn("style-src 'self' 'unsafe-inline'", terminal.headers['content-security-policy'])
        self.assertIn("script-src 'self';", terminal.headers['content-security-policy'])
        self.assertNotIn('unsafe-inline', dashboard.headers['content-security-policy'])
