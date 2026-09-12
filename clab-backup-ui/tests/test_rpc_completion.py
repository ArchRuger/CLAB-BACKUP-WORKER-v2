"""Real SSH ordering regressions for the discovery and Git gateway clients."""
import base64
import hashlib
import json
import socket
import threading
import unittest
from unittest.mock import patch

import paramiko
from app.discovery import inspect_host
from app.git_progress import remote_git
from test_discovery_ssh import InspectionServer


class RPCCompletionTests(unittest.TestCase):
    def serve(self, kind, payload, status=0, stderr=b'', early_status=True):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0)); listener.listen(1); listener.settimeout(3)
        port = listener.getsockname()[1]
        server = InspectionServer(); key = paramiko.RSAKey.generate(1024)
        active = []
        def run():
            transport = None
            try:
                connection, _ = listener.accept()
                transport = paramiko.Transport(connection); active.append(transport)
                transport.add_server_key(key); transport.start_server(server=server)
                channel = transport.accept(3)
                if channel and server.request.wait(3):
                    channel.settimeout(3)
                    if kind == 'git':
                        while channel.recv(65536): pass
                    # The old clients incorrectly considered status to mean EOF.
                    if status is not None and early_status: channel.send_exit_status(status)
                    if early_status: threading.Event().wait(.15)
                    if stderr: channel.sendall_stderr(stderr)
                    for offset in range(0, len(payload), 4096):
                        channel.sendall(payload[offset:offset+4096])
                    if status is not None and not early_status: channel.send_exit_status(status)
                    channel.shutdown_write()
                    threading.Event().wait(.05)
            except (EOFError, OSError, paramiko.SSHException): pass
            finally:
                if transport: transport.close()
                listener.close()
        thread = threading.Thread(target=run, daemon=True); thread.start()
        def cleanup():
            for transport in active: transport.close()
            listener.close(); thread.join(4)
            self.assertFalse(thread.is_alive())
        self.addCleanup(cleanup)
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        return dict(enabled=True, address='127.0.0.1', port=port, username='fixture',
                    password='fixture', auth='password', command_mode='helper', fingerprint=fingerprint)

    def test_discovery_waits_for_delayed_stdout_after_exit_status(self):
        data = {'lab': [{'lab_name': 'lab', 'name': 'clab-lab-r1', 'state': 'running'}]}
        host = self.serve('discovery', json.dumps(data).encode())
        result, fingerprint = inspect_host(host)
        self.assertIn('lab', result)
        self.assertEqual(fingerprint, host['fingerprint'])

    def test_git_waits_for_large_delayed_stdout_after_exit_status(self):
        result = {'status': 'committed', 'message': 'x' * (160 * 1024)}
        host = self.serve('git', json.dumps({'result': result}).encode())
        self.assertEqual(remote_git(host, {'mode': 'list'}), result)

    def test_both_clients_reject_missing_and_failed_exit_status(self):
        for kind in ('discovery', 'git'):
            for status in (None, 1):
                with self.subTest(kind=kind, status=status):
                    host = self.serve(kind, b'{"result":{}}' if kind == 'git' else b'{}', status=status)
                    with self.assertRaises(ValueError):
                        remote_git(host, {'mode': 'list'}) if kind == 'git' else inspect_host(host)

    def test_git_stderr_counts_toward_bounded_response(self):
        host = self.serve('git', b'{"result":{}}', stderr=b'private-stderr' * 200, early_status=False)
        with patch('app.git_progress.MAX_WIRE', 1000):
            with self.assertRaisesRegex(ValueError, 'response exceeded') as error:
                remote_git(host, {'mode': 'list'})
        self.assertNotIn('private-stderr', str(error.exception))
