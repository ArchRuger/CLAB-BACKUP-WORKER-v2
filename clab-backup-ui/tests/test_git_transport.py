import json
import socket
import threading
import unittest
from unittest.mock import Mock, patch

from app.git_progress import remote_git


class GitTransportTests(unittest.TestCase):
    def channel(self, envelope, code=0, chunks=None):
        channel = Mock()
        raw = json.dumps(envelope).encode()
        # The exit status is visible from the first poll; only stream EOF (an
        # empty recv) may end the read, exactly as OpenSSH can deliver them.
        channel.recv.side_effect = list(chunks if chunks is not None else [raw]) + [b'']
        channel.recv_stderr_ready.return_value = False
        channel.exit_status_ready.return_value = True
        channel.recv_exit_status.return_value = code
        client = Mock(); client.get_transport.return_value.open_session.return_value = channel
        return client, channel

    def test_exit_status_before_fragmented_tail_waits_for_eof(self):
        envelope = {'result': {'snapshot': {'files': {'node.cfg': 'B' * 200000}}}}
        raw = json.dumps(envelope).encode()
        pieces = [raw[:7], socket.timeout(), raw[7:65536], socket.timeout(), raw[65536:]]
        client, channel = self.channel(envelope, chunks=pieces)
        with patch('app.git_progress.paramiko.SSHClient', return_value=client):
            self.assertEqual(remote_git(self.host(), {'mode': 'read-version'}), envelope['result'])
        self.assertEqual(channel.recv.call_count, len(pieces) + 1)
        channel.recv_ready.assert_not_called()

    def test_eof_is_required_even_when_status_arrives_first(self):
        # A truncated envelope must not be parsed just because the status is ready.
        client, channel = self.channel({'result': {}}, chunks=[b'{"result": {'])
        with patch('app.git_progress.paramiko.SSHClient', return_value=client):
            with self.assertRaisesRegex(ValueError, 'matching Git helper'): remote_git(self.host(), {'mode': 'list'})
        client.close.assert_called_once()

    def host(self):
        return dict(enabled=True, address='vm.example.invalid', port=22, username='clab-discovery',
                    auth='password', password='fixture-vm-secret', fingerprint='SHA256:fixture')

    def test_large_rpc_uses_pinned_password_channel_and_fixed_command(self):
        request = {'mode': 'publish', 'snapshot': {'files': {'node.cfg': 'A' * 180000}}}
        client, channel = self.channel({'result': {'status': 'committed'}})
        with patch('app.git_progress.paramiko.SSHClient', return_value=client):
            self.assertEqual(remote_git(self.host(), request)['status'], 'committed')
        client.set_missing_host_key_policy.assert_called_once()
        options = client.connect.call_args.kwargs
        self.assertEqual(options['password'], 'fixture-vm-secret')
        self.assertFalse(options['allow_agent']); self.assertFalse(options['look_for_keys'])
        channel.exec_command.assert_called_once_with('clab-manager-git')
        payload = channel.sendall.call_args.args[0]
        self.assertEqual(json.loads(payload), request)
        self.assertNotIn(b'fixture-vm-secret', payload)
        channel.shutdown_write.assert_called_once(); client.close.assert_called_once()

    def test_error_and_invalid_response_close_connection(self):
        for envelope, code, message in (({'error': 'Repository needs attention.'}, 1, 'Repository needs attention'),
                                        ({'result': []}, 0, 'unavailable')):
            with self.subTest(envelope=envelope):
                client, channel = self.channel(envelope, code)
                with patch('app.git_progress.paramiko.SSHClient', return_value=client):
                    with self.assertRaisesRegex(ValueError, message): remote_git(self.host(), {'mode': 'list'})
                client.close.assert_called_once()

    def test_response_limit_and_shutdown_interrupt_are_bounded(self):
        client, channel = self.channel({'result': {'message': 'x' * 300}})
        with patch('app.git_progress.paramiko.SSHClient', return_value=client), patch('app.git_progress.MAX_WIRE', 100):
            with self.assertRaisesRegex(ValueError, 'response exceeded'): remote_git(self.host(), {'mode': 'list'})
        client.close.assert_called_once()
        client, channel = self.channel({'result': {}}); stopped = threading.Event(); stopped.set()
        with patch('app.git_progress.paramiko.SSHClient', return_value=client):
            with self.assertRaisesRegex(ValueError, 'interrupted'): remote_git(self.host(), {'mode': 'list'}, stopped)
        client.close.assert_called_once()

    def test_oversized_request_is_rejected_before_connecting(self):
        with patch('app.git_progress.MAX_WIRE', 50), patch('app.git_progress.paramiko.SSHClient') as client:
            with self.assertRaisesRegex(ValueError, 'transfer limit'):
                remote_git(self.host(), {'mode': 'publish', 'value': 'x' * 100})
        client.assert_not_called()
