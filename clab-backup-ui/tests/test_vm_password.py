import copy
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from app.discovery import inspect_host
from app.lab_operations import remote
from app.store import Store
import test_discovery as discovery_tests


class VMPasswordTests(unittest.TestCase):
    setUp = discovery_tests.DiscoveryTests.setUp
    host = discovery_tests.DiscoveryTests.host

    def tearDown(self):
        self.app.state.operations.close()
        discovery_tests.DiscoveryTests.tearDown(self)

    def test_key_migration_requires_password_and_preserves_vm_identity(self):
        self.store.state['host'] = dict(address='127.0.0.1', port=22, username='fixture',
            auth='key', private_key='old-private-secret', passphrase='old-passphrase',
            fingerprint='SHA256:verified', enabled=True, command_mode='helper')
        original = copy.deepcopy(self.store.state['host'])
        r = self.client.put('/api/host', json=dict(address='127.0.0.1', username='fixture'))
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.store.state['host'], original)
        self.host(password='new-password')
        saved = Store(self.tmp.name).state['host']
        self.assertEqual(saved['fingerprint'], 'SHA256:verified')
        self.assertEqual(saved['password'], 'new-password')
        self.assertNotIn('private_key', saved)
        self.assertNotIn('passphrase', saved)
        for path in ('state.enc', 'events.jsonl'):
            raw = (Path(self.tmp.name)/path).read_bytes()
            for secret in (b'new-password', b'old-private-secret', b'old-passphrase'):
                self.assertNotIn(secret, raw)

    def test_password_rotation_blank_save_and_changed_account(self):
        self.host(password='first'); self.host(password='second'); self.host(password='')
        self.assertEqual(Store(self.tmp.name).state['host']['password'], 'second')
        for change in ({'address':'192.0.2.2'}, {'username':'different'}, {'port':2222}):
            data = dict(address='127.0.0.1', username='fixture', password='')
            data.update(change)
            self.assertEqual(self.client.put('/api/host', json=data).status_code, 400)
        public = self.client.get('/api/state').text
        self.assertNotIn('second', public)

    def test_api_rejects_key_authentication_and_secret_fields(self):
        self.host()
        original = copy.deepcopy(self.store.state['host'])
        for change in ({'auth':'key'}, {'private_key':'sensitive'}, {'passphrase':'sensitive'}):
            data = dict(address='127.0.0.1', username='fixture', password='sensitive')
            data.update(change)
            response = self.client.put('/api/host', json=data)
            self.assertIn(response.status_code, (400, 422))
            self.assertNotIn('sensitive', response.text)
            self.assertEqual(self.store.state['host'], original)

    def test_legacy_key_never_attempts_network_authentication(self):
        host = dict(auth='key', enabled=True, fingerprint='SHA256:verified')
        with patch('app.discovery.paramiko.SSHClient') as client:
            for call in (lambda: inspect_host(host), lambda: remote(host, {'mode':'capabilities'})):
                with self.assertRaisesRegex(ValueError, 'VM password setup required'):
                    call()
            client.assert_not_called()


class SSHPolicyTests(unittest.TestCase):
    def test_effective_policy_rejects_conflicting_restrictions(self):
        root = Path(__file__).resolve().parents[2]/'deploy'
        import runpy
        expected = runpy.run_path(str(root/'verify-ssh-password.py'))['EXPECTED']
        for key in (None, *expected):
            value = dict(expected)
            if key: value[key] = 'incorrect'
            result = subprocess.run([sys.executable, str(root/'verify-ssh-password.py')],
                input='\n'.join(f'{k} {v}' for k,v in value.items()), text=True, capture_output=True)
            self.assertEqual(result.returncode == 0, key is None, key)

    def test_policy_scope_is_only_dedicated_account(self):
        policy = (Path(__file__).resolve().parents[2]/'deploy/clab-manager-password.conf').read_text()
        lines = [line.strip() for line in policy.splitlines() if line.strip() and not line.startswith('#')]
        self.assertEqual(lines[0], 'Match User clab-discovery')
        self.assertEqual(lines[-1], 'Match all')
        self.assertNotIn('PermitUserEnvironment no', lines)  # Global-only; verified, never changed.
