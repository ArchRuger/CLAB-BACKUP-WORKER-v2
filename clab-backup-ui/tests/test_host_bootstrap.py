"""VM setup seed (host-bootstrap.json): the setup side writer and the manager side merge."""
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import paramiko

from app.main import create_app
from app.discovery import (BOOTSTRAP_FILE, BOOTSTRAP_WAITING, PinnedHostKey, consume_host_bootstrap,
                           host_key_policy, parse_inspect)
from app.store import Store

SEED_MODULE = Path(__file__).resolve().parents[2]/'deploy'/'host_bootstrap_seed.py'
spec = importlib.util.spec_from_file_location('host_bootstrap_seed', SEED_MODULE)
seed_writer = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed_writer)

SECRET = 'setup-created-secret-9f3'
SETUP_KEY = 'SHA256:' + 'A' * 43
OTHER_KEY = 'SHA256:' + 'B' * 43


def seed(**changes):
    data = {'schema': 1, 'created': '2026-09-23T10:00:00+00:00',
            'host': {'address': '127.0.0.1', 'port': 22, 'username': 'clab-discovery', 'auth': 'password',
                     'command_mode': 'helper', 'enabled': True},
            'password': SECRET, 'fingerprint': SETUP_KEY}
    host = changes.pop('host', None)
    if host: data['host'] = {**data['host'], **host}
    data.update(changes)
    return data


class FakeKey:
    def __init__(self, blob): self.blob = blob
    def asbytes(self): return self.blob
    def get_name(self): return 'ssh-ed25519'


class ManagerBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.service = self.app.state.discovery

    def tearDown(self):
        self.app.state.git_progress.close()
        self.service.close(); self.app.state.runner.close(); self.app.state.node_services.close()
        self.client.close(); self.tmp.cleanup()

    def write(self, data):
        path = self.root/BOOTSTRAP_FILE
        path.write_text(data if isinstance(data, str) else json.dumps(data))
        os.chmod(path, 0o600)
        return path

    def events(self):
        return [e for e in self.store.events() if e['action'] == 'discovery.bootstrap']

    def assert_no_secret_on_disk(self):
        for name in ('state.enc', 'events.jsonl'):
            path = self.root/name
            if path.exists(): self.assertNotIn(SECRET.encode(), path.read_bytes())

    def test_seed_is_merged_encrypted_and_deleted(self):
        path = self.write(seed())
        self.service.consume_bootstrap()
        host = self.store.state['host']
        self.assertEqual((host['address'], host['port'], host['username'], host['auth'], host['command_mode'], host['enabled']),
                         ('127.0.0.1', 22, 'clab-discovery', 'password', 'helper', True))
        self.assertEqual(host['password'], SECRET)
        self.assertEqual(host['fingerprint'], '')
        self.assertTrue(host['bootstrap_pending'])
        self.assertEqual(host['bootstrap_fingerprint'], SETUP_KEY)
        self.assertEqual(host['bootstrap_at'], '2026-09-23T10:00:00+00:00')
        self.assertFalse(path.exists())
        self.assertEqual(Store(self.tmp.name).state['host']['password'], SECRET)
        self.assertEqual([e['message'] for e in self.events()], ['VM connection prefilled from setup'])
        self.assert_no_secret_on_disk()

    def test_invalid_seeds_are_ignored_removed_and_logged(self):
        bad = ['{not json', json.dumps([1]), seed(schema=2), seed(schema=True), seed(extra='x'),
               seed(password=''), seed(password=7), seed(fingerprint='MD5:aa'), seed(created='yesterday'),
               seed(host={'port': 0}), seed(host={'port': True}), seed(host={'port': '22'}),
               seed(host={'auth': 'key'}), seed(host={'command_mode': 'shell'}), seed(host={'enabled': 'yes'}),
               seed(host={'address': 'http://vm'}), seed(host={'address': '-oProxyCommand=x'}),
               seed(host={'username': ''}), seed(host={'username': '{{ x }}'})]
        for index, data in enumerate(bad):
            path = self.write(data)
            self.service.consume_bootstrap()
            self.assertFalse(path.exists(), index)
            self.assertNotIn('host', self.store.state, index)
        warnings = self.events()
        self.assertEqual(len(warnings), len(bad))
        self.assertTrue(all(e['level'] == 'warning' and e['message'].startswith('VM setup seed ignored') for e in warnings))
        self.assert_no_secret_on_disk()

    def test_symlinked_or_oversized_seed_is_refused(self):
        target = self.root/'elsewhere.json'; target.write_text(json.dumps(seed()))
        (self.root/BOOTSTRAP_FILE).symlink_to(target)
        self.service.consume_bootstrap()
        self.assertNotIn('host', self.store.state)
        self.assertFalse((self.root/BOOTSTRAP_FILE).is_symlink())
        self.assertTrue(target.exists(), 'unlink removes the link, never its target')
        self.write(json.dumps(seed()) + ' ' * (70 * 1024))
        self.service.consume_bootstrap()
        self.assertNotIn('host', self.store.state)

    def test_pending_blocks_background_discovery_until_the_student_confirms(self):
        self.write(seed())
        with patch('app.discovery.inspect_host') as inspect:
            result = self.service.refresh()
            self.service.refresh(wait=True)
            inspect.assert_not_called()
        self.assertFalse(result['connected'])
        self.assertEqual(result['error'], BOOTSTRAP_WAITING)
        self.assertTrue(result['host']['bootstrap_pending'])
        self.assertTrue(self.client.get('/api/discovery').json()['host']['bootstrap_pending'])

    def test_blank_password_save_keeps_seed_password_and_first_connection_pins(self):
        self.write(seed()); self.service.consume_bootstrap()
        r = self.client.put('/api/host', json=dict(address='127.0.0.1', port=22, username='clab-discovery',
                                                   auth='password', password='', command_mode='helper', enabled=True))
        self.assertEqual(r.status_code, 200, r.text)
        host = self.store.state['host']
        self.assertEqual(host['password'], SECRET)
        self.assertNotIn('bootstrap_pending', host)
        self.assertEqual(host['bootstrap_verify'], SETUP_KEY)
        self.assertFalse(r.json()['host']['bootstrap_pending'])
        with patch('app.discovery.inspect_host', return_value=(parse_inspect(b'{}'), SETUP_KEY)) as inspect:
            result = self.service.refresh(wait=True)
        self.assertEqual(inspect.call_args[0][0]['bootstrap_verify'], SETUP_KEY)
        self.assertTrue(result['connected'])
        host = self.store.state['host']
        self.assertEqual(host['fingerprint'], SETUP_KEY)
        self.assertNotIn('bootstrap_verify', host)
        self.assertEqual(host['bootstrap_fingerprint'], SETUP_KEY)

    def test_a_different_key_on_the_first_connection_is_reported_not_trusted(self):
        self.write(seed()); self.service.consume_bootstrap()
        self.client.put('/api/host', json=dict(address='127.0.0.1', port=22, username='clab-discovery'))
        policy = host_key_policy(self.store.state['host'])
        client = paramiko.SSHClient()
        with self.assertRaisesRegex(ValueError, 'does not match the key recorded by VM setup'):
            policy.missing_host_key(client, '127.0.0.1', FakeKey(b'another-host-key'))
        # The error travels to the dialog through the normal discovery error; nothing is pinned.
        error = ValueError('VM SSH host key does not match the key recorded by VM setup. Verify the VM before trusting it.')
        with patch('app.discovery.inspect_host', side_effect=error):
            result = self.service.refresh(wait=True)
        self.assertIn('recorded by VM setup', result['error'])
        self.assertEqual(self.store.state['host']['fingerprint'], '')
        self.assertEqual(self.store.state['host']['bootstrap_verify'], SETUP_KEY)
        # A second plain save keeps expecting setup's key; only the explicit override drops it.
        self.client.put('/api/host', json=dict(address='127.0.0.1', port=22, username='clab-discovery'))
        self.assertEqual(self.store.state['host']['bootstrap_verify'], SETUP_KEY)
        self.client.put('/api/host', json=dict(address='127.0.0.1', port=22, username='clab-discovery', reset_fingerprint=True))
        self.assertNotIn('bootstrap_verify', self.store.state['host'])
        self.assertEqual(host_key_policy(self.store.state['host']).expected, '')

    def test_matching_key_passes_the_setup_expectation(self):
        blob = b'the-vm-host-key'
        first = PinnedHostKey(''); first.missing_host_key(paramiko.SSHClient(), 'vm', FakeKey(blob))
        policy = host_key_policy({'bootstrap_verify': first.fingerprint})
        policy.missing_host_key(paramiko.SSHClient(), 'vm', FakeKey(blob))
        self.assertEqual(policy.fingerprint, first.fingerprint)
        self.assertEqual(host_key_policy({'fingerprint': OTHER_KEY, 'bootstrap_verify': SETUP_KEY}).expected, OTHER_KEY)

    def test_a_seed_never_replaces_a_pinned_fingerprint(self):
        self.store.state['host'] = dict(address='127.0.0.1', port=22, username='clab-discovery', auth='password',
                                        password='old', fingerprint=OTHER_KEY, enabled=True, command_mode='helper')
        self.write(seed()); self.service.consume_bootstrap()
        host = self.store.state['host']
        self.assertEqual(host['fingerprint'], OTHER_KEY)
        self.assertEqual(host['password'], SECRET)
        self.assertFalse(host['bootstrap_pending'])
        self.assertEqual(host['bootstrap_fingerprint'], SETUP_KEY)
        public = self.client.get('/api/discovery').json()['host']
        self.assertEqual((public['fingerprint'], public['bootstrap_fingerprint']), (OTHER_KEY, SETUP_KEY))
        self.assertIn('differs from the key recorded by setup', self.events()[-1]['message'])
        self.assertEqual(self.events()[-1]['level'], 'warning')
        with patch('app.discovery.inspect_host', return_value=(parse_inspect(b'{}'), OTHER_KEY)) as inspect:
            self.service.refresh(wait=True)
        inspect.assert_called_once()
        self.assertEqual(host_key_policy(inspect.call_args[0][0]).expected, OTHER_KEY)

    def test_a_pin_for_another_endpoint_is_not_carried_over(self):
        self.store.state['host'] = dict(address='192.0.2.5', port=22, username='clab-discovery', auth='password',
                                        password='old', fingerprint=OTHER_KEY, enabled=True, command_mode='helper')
        self.write(seed()); self.service.consume_bootstrap()
        self.assertEqual(self.store.state['host']['fingerprint'], '')
        self.assertTrue(self.store.state['host']['bootstrap_pending'])

    def test_changing_the_endpoint_on_save_drops_the_setup_record(self):
        self.write(seed()); self.service.consume_bootstrap()
        r = self.client.put('/api/host', json=dict(address='192.0.2.9', port=22, username='clab-discovery'))
        self.assertEqual(r.status_code, 400, 'another endpoint needs its password typed')
        r = self.client.put('/api/host', json=dict(address='192.0.2.9', port=22, username='clab-discovery', password='typed'))
        self.assertEqual(r.status_code, 200, r.text)
        host = self.store.state['host']
        for key in ('bootstrap_pending', 'bootstrap_verify', 'bootstrap_fingerprint', 'bootstrap_at'):
            self.assertNotIn(key, host)

    def test_public_views_never_carry_the_password_or_seed(self):
        self.write(seed()); self.service.consume_bootstrap()
        for url in ('/api/state', '/api/discovery'):
            body = self.client.get(url).text
            self.assertNotIn(SECRET, body)
            self.assertNotIn('bootstrap_verify', body)
        public = self.client.get('/api/state').json()['discovery']['host']
        self.assertEqual({k for k in public if k.startswith('bootstrap_') or k == 'password_saved'},
                         {'bootstrap_pending', 'bootstrap_at', 'bootstrap_fingerprint', 'password_saved'})
        self.assertTrue(public['password_saved'])
        self.assertNotIn('password', public)
        self.client.put('/api/host', json=dict(address='127.0.0.1', port=22, username='clab-discovery'))
        self.assertNotIn(SECRET, self.client.get('/api/state').text)

    def test_undeletable_seed_is_not_loaded_twice_in_one_process(self):
        self.write(seed())
        with patch('app.discovery.os.unlink', side_effect=PermissionError('denied')):
            self.service.consume_bootstrap()
            revision = self.store.state['host']['revision']
            self.store.state['host']['password'] = 'typed-later'
            self.service.consume_bootstrap(); self.service.refresh()
        self.assertEqual(self.store.state['host']['revision'], revision)
        self.assertEqual(self.store.state['host']['password'], 'typed-later')
        messages = [e['message'] for e in self.events()]
        self.assertEqual(messages.count('VM connection prefilled from setup'), 1)
        self.assertTrue(any('could not be removed' in m for m in messages))

    def test_pending_git_saves_block_an_identity_change(self):
        self.store.state['host'] = dict(address='192.0.2.5', port=22, username='clab-discovery', auth='password',
                                        password='old', fingerprint=OTHER_KEY, enabled=True, command_mode='helper')
        self.store.state['git_jobs'] = [{'id': 'j', 'lab_id': 'l', 'status': 'committed'}]
        path = self.write(seed()); self.service.consume_bootstrap()
        self.assertEqual(self.store.state['host']['address'], '192.0.2.5')
        self.assertEqual(self.store.state['host']['password'], 'old')
        self.assertFalse(path.exists())
        self.assertIn('finish pending Git saves', self.events()[-1]['message'])

    def test_discovery_start_consumes_the_seed_without_connecting(self):
        path = self.write(seed())
        with patch('app.discovery.inspect_host') as inspect:
            self.service.start(); self.service.close()
            inspect.assert_not_called()
        self.assertFalse(path.exists())
        self.assertTrue(self.store.state['host']['bootstrap_pending'])

    def test_module_function_accepts_an_explicit_data_directory(self):
        other = tempfile.TemporaryDirectory(); self.addCleanup(other.cleanup)
        (Path(other.name)/BOOTSTRAP_FILE).write_text(json.dumps(seed()))
        self.assertIsNone(consume_host_bootstrap(self.store, other.name))
        self.assertEqual(self.store.state['host']['password'], SECRET)
        self.assertIsNone(consume_host_bootstrap(self.store))


class SeedWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_parse_keygen_output(self):
        line = '256 SHA256:' + 'x' * 43 + ' root@vm (ED25519)\n'
        self.assertEqual(seed_writer.parse_keygen(line), 'SHA256:' + 'x' * 43)
        self.assertEqual(seed_writer.parse_keygen('3072 SHA256:' + 'a/b+' * 10 + 'abc no comment (RSA)'), 'SHA256:' + 'a/b+' * 10 + 'abc')
        for text in ('', 'ssh-keygen: not a key file', '256 MD5:aa:bb root (ED25519)', '256 SHA256:short root (ED25519)'):
            self.assertEqual(seed_writer.parse_keygen(text), '')

    def test_public_key_fingerprint_matches_the_manager(self):
        key = paramiko.RSAKey.generate(1024)
        line = f'{key.get_name()} {key.get_base64()} root@vm\n'
        policy = PinnedHostKey(''); policy.missing_host_key(paramiko.SSHClient(), 'vm', key)
        self.assertEqual(seed_writer.fingerprint_of_public_key(line), policy.fingerprint)
        self.assertEqual(seed_writer.fingerprint_of_public_key('garbage'), '')

    def test_host_fingerprint_prefers_ed25519_and_falls_back_to_the_file(self):
        key = paramiko.RSAKey.generate(1024)
        rsa = self.dir/'ssh_host_rsa_key.pub'; rsa.write_text(f'{key.get_name()} {key.get_base64()} root@vm\n')
        ed = self.dir/'ssh_host_ed25519_key.pub'; ed.write_text('ssh-ed25519 AAAA root@vm\n')
        calls = []
        def run(argv, **kwargs):
            calls.append(argv[-1])
            class Result: returncode = 0; stdout = '256 SHA256:' + 'E' * 43 + ' root@vm (ED25519)\n' if argv[-1] == str(ed) else ''
            return Result()
        self.assertEqual(seed_writer.host_fingerprint((str(rsa), str(ed)), run=run), 'SHA256:' + 'E' * 43)
        self.assertEqual(calls, [str(ed)])
        failing = lambda argv, **kwargs: (_ for _ in ()).throw(OSError('no ssh-keygen'))
        policy = PinnedHostKey(''); policy.missing_host_key(paramiko.SSHClient(), 'vm', key)
        self.assertEqual(seed_writer.host_fingerprint((str(rsa)[:-4],), run=failing), policy.fingerprint)
        self.assertEqual(seed_writer.host_fingerprint((str(self.dir/'missing.pub'),), run=run), '')

    def test_atomic_write_mode_and_no_chown_without_root(self):
        data = seed_writer.build_seed('pw', 2222, SETUP_KEY)
        with patch.object(seed_writer.os, 'geteuid', return_value=1000), patch.object(seed_writer.os, 'fchown') as chown:
            target = seed_writer.write_seed(str(self.dir), data)
        chown.assert_not_called()
        self.assertEqual(stat.S_IMODE(os.stat(target).st_mode), 0o600)
        self.assertEqual(json.loads(Path(target).read_text()), data)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [seed_writer.SEED_NAME])
        with patch.object(seed_writer.os, 'geteuid', return_value=0), patch.object(seed_writer.os, 'fchown') as chown:
            seed_writer.write_seed(str(self.dir), data)
        self.assertEqual(chown.call_args[0][1:], (10001, 10001))

    def test_failed_replace_leaves_no_temporary_file_and_keeps_the_old_seed(self):
        seed_writer.write_seed(str(self.dir), seed_writer.build_seed('first', 22, ''))
        with patch.object(seed_writer.os, 'replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                seed_writer.write_seed(str(self.dir), seed_writer.build_seed('second', 22, ''))
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [seed_writer.SEED_NAME])
        self.assertEqual(json.loads((self.dir/seed_writer.SEED_NAME).read_text())['password'], 'first')

    def test_missing_or_unsafe_data_directory(self):
        self.assertIsNone(seed_writer.write_seed(str(self.dir/'absent'), seed_writer.build_seed('pw', 22, '')))
        (self.dir/'link').symlink_to(self.dir)
        with self.assertRaises(seed_writer.SeedError):
            seed_writer.write_seed(str(self.dir/'link'), seed_writer.build_seed('pw', 22, ''))
        with self.assertRaises(seed_writer.SeedError): seed_writer.build_seed('pw', 0, '')

    def test_password_comes_from_stdin_only(self):
        self.assertEqual(seed_writer.read_password(io.StringIO('pa:ss word\n')), 'pa:ss word')
        for bad in ('', '\n', 'two\nlines\n', 'x' * 4097, 'nul\x00'):
            with self.assertRaises(seed_writer.SeedError): seed_writer.read_password(io.StringIO(bad))

    def test_main_writes_a_seed_the_manager_accepts(self):
        key = paramiko.RSAKey.generate(1024)
        pub = self.dir/'ssh_host_rsa_key.pub'; pub.write_text(f'{key.get_name()} {key.get_base64()} root@vm\n')
        data = self.dir/'data'; data.mkdir(mode=0o700)
        output = io.StringIO()
        with patch('sys.stdout', output):
            status = seed_writer.main(['--data-dir', str(data), '--port', '2200', '--host-key', str(pub)], stdin=io.StringIO(SECRET + '\n'))
        self.assertEqual(status, 0)
        self.assertNotIn(SECRET, output.getvalue())
        with patch('sys.stdout', output):
            self.assertEqual(seed_writer.main(['--data-dir', str(self.dir/'none')], stdin=io.StringIO('pw\n')), 2)
        self.assertNotIn(SECRET, output.getvalue())
        manager = self.dir/'manager'
        store = Store(manager)
        (data/seed_writer.SEED_NAME).replace(manager/BOOTSTRAP_FILE)
        self.assertIsNone(consume_host_bootstrap(store))
        policy = PinnedHostKey(''); policy.missing_host_key(paramiko.SSHClient(), 'vm', key)
        self.assertEqual((store.state['host']['port'], store.state['host']['password'], store.state['host']['bootstrap_fingerprint']),
                         (2200, SECRET, policy.fingerprint))


if __name__ == '__main__':
    unittest.main()
