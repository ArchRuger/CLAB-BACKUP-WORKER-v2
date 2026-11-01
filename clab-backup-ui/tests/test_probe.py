"""`python -m app.probe <name> [arg]` (docs/sign-on/EXPOSURE.md 6.1 and 9 item 5, DESIGN.md 6.7, REVIEW R16; slice S3).

The health check's only way to read a manager fact other than `GET /api/health`: one JSON line on stdout, nothing
on stderr, exit 0 for an answer, 1 for `{"error": …}`, 2 for an unknown name or a bad argument. A probe never
constructs a `Store`, never writes, never logs and never prints a secret; the three that need the saved state decrypt
`state.enc` read-only. Every test uses a fresh temporary data directory written with Fernet directly.
"""
import contextlib
import io
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = 'vm-Secret-pass-42'
FINGERPRINT = 'SHA256:' + 'A' * 43
TOKEN = 'f' * 64
NODE_SECRET = 'node-Secret-77'


def sample_state():
    return {'version': 1,
            'host': {'address': '192.0.2.10', 'port': 22, 'username': 'clab-discovery', 'auth': 'password',
                     'command_mode': 'helper', 'enabled': True, 'fingerprint': FINGERPRINT, 'password': PASSWORD,
                     'bootstrap_pending': True, 'bootstrap_fingerprint': FINGERPRINT, 'bootstrap_at': 'x'},
            'discovery': {'ok': True, 'checked_epoch': time.time(), 'checked_at': '2026-11-01T10:00:00+00:00'},
            'labs': [{'id': 'a', 'name': 'One', 'nodes': [{'name': 'r1', 'password': NODE_SECRET}], 'profiles': [],
                      'git_binding': {'repository': 'r', 'folder': 'f', 'url': 'https://example.invalid/x.git', 'binding_id': 'b1'}},
                     {'id': 'b', 'name': 'Two', 'nodes': [], 'profiles': [], 'git_binding': None},
                     {'id': 'c', 'name': 'Three', 'nodes': [], 'profiles': [], 'git_binding': {'binding_id': 'b2'}}],
            'jobs': []}


def snapshot(root):
    """Every path under root with its type, size, mode and mtime: a probe must leave it exactly as it was."""
    items = {}
    for path in sorted(Path(root).rglob('*')):
        info = path.lstat()
        items[str(path.relative_to(root))] = (path.is_dir(), info.st_size, info.st_mode, info.st_mtime_ns)
    return items


class ProbeCase(unittest.TestCase):
    def setUp(self):
        from app import probe
        self.probe = probe
        self.dir = Path(tempfile.mkdtemp(prefix='probe-test-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.data = self.dir / 'data'
        self.data.mkdir(mode=0o700)
        env = mock.patch.dict(os.environ, {'DATA_DIR': str(self.data)})
        env.start(); self.addCleanup(env.stop)
        for key in ('CAPTURE_PROVIDER', 'CAPTURE_EDGESHARK_URL', 'CAPTURE_SESSION_URL', 'CAPTURE_SESSION_TOKEN'):
            os.environ.pop(key, None)
        # A Store must never be constructed: make any attempt fail loudly.
        import app.store
        guard = mock.patch.object(app.store.Store, '__init__', side_effect=AssertionError('a probe constructed a Store'))
        guard.start(); self.addCleanup(guard.stop)

    def write_state(self, state=None, key=None):
        key = key or Fernet.generate_key()
        (self.data / 'state.key').write_bytes(key)
        (self.data / 'state.enc').write_bytes(Fernet(key).encrypt(json.dumps(sample_state() if state is None else state).encode()))
        return key

    def run_probe(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        before = snapshot(self.dir)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = self.probe.main(list(argv))
        self.assertEqual(snapshot(self.dir), before, 'a probe changed the data directory')
        return code, out.getvalue(), err.getvalue()

    def answer(self, *argv, code=0):
        status, out, err = self.run_probe(*argv)
        self.assertEqual(err, '')
        self.assertEqual(status, code, out)
        self.assertTrue(out.endswith('\n'))
        self.assertEqual(out.count('\n'), 1, out)
        value = json.loads(out)
        self.assert_short(value)
        for secret in (PASSWORD, FINGERPRINT, TOKEN, NODE_SECRET, 'scrypt$'):
            self.assertNotIn(secret, out)
        return value

    def assert_short(self, value):
        if isinstance(value, str): self.assertLessEqual(len(value), 600)
        elif isinstance(value, dict): [self.assert_short(v) for v in value.values()]
        elif isinstance(value, list): [self.assert_short(v) for v in value]


class Arguments(ProbeCase):
    def assert_usage(self, *argv):
        code, out, err = self.run_probe(*argv)
        self.assertEqual((code, out), (2, ''), argv)
        self.assertTrue(err.startswith('usage: python -m app.probe '), err)
        self.assertEqual(err.count('\n'), 1, err)

    def test_unknown_or_missing_name(self):
        for argv in ((), ('nope',), ('--help',), ('state',), ('Browse', '/srv'), ('',)):
            with self.subTest(argv=argv): self.assert_usage(*argv)

    def test_argument_counts(self):
        for argv in (('browse',), ('browse', '/srv', '/x'), ('design-engine', 'x'), ('capture', 'x'),
                     ('vm-connection', ''), ('git-registry', 'list')):
            with self.subTest(argv=argv): self.assert_usage(*argv)

    def test_browse_paths_are_validated_before_any_read(self):
        self.write_state()
        with mock.patch('app.lab_operations.remote') as remote:
            for path in ('srv', 'relative/x', '/srv/../etc', '/srv/..', '/a\x01b', '/a\x7f', '/a\nb', '/' + 'x' * 600, '~/x'):
                with self.subTest(path=path): self.assert_usage('browse', path)
        remote.assert_not_called()

    def test_main_entry_point_exits_with_the_code(self):
        result = subprocess.run([sys.executable, '-m', 'app.probe', 'nope'], cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertTrue(result.stderr.startswith('usage: python -m app.probe '))


class StateReader(ProbeCase):
    def test_reads_the_document_read_only(self):
        self.write_state()
        before = snapshot(self.dir)
        state = self.probe.read_state()
        self.assertEqual(state['host']['address'], '192.0.2.10')
        self.assertEqual(snapshot(self.dir), before)

    def test_data_dir_is_create_apps(self):
        # Only the name is computed here: a test never reads /data.
        self.assertEqual(self.probe.data_dir(), self.data)
        os.environ.pop('DATA_DIR')
        self.assertEqual(self.probe.data_dir(), Path('/data'))   # main.py:51, os.environ.get('DATA_DIR', '/data')

    def test_unreadable_cases(self):
        cases = {'no files': lambda: None,
                 'no key': lambda: (self.write_state(), (self.data / 'state.key').unlink()),
                 'no state': lambda: (self.write_state(), (self.data / 'state.enc').unlink()),
                 'wrong key': lambda: (self.write_state(), (self.data / 'state.key').write_bytes(Fernet.generate_key())),
                 'garbage key': lambda: (self.write_state(), (self.data / 'state.key').write_bytes(b'nonsense')),
                 'garbage state': lambda: (self.write_state(), (self.data / 'state.enc').write_bytes(b'nonsense')),
                 'not a dict': lambda: self.write_state([1, 2]),
                 'labs not a list': lambda: self.write_state({'labs': {}}),
                 'state is a directory': lambda: (self.write_state(), (self.data / 'state.enc').unlink(), (self.data / 'state.enc').mkdir())}
        for label, prepare in cases.items():
            with self.subTest(label):
                for name in ('state.key', 'state.enc'):
                    target = self.data / name
                    if target.is_dir(): target.rmdir()
                    elif target.exists(): target.unlink()
                prepare()
                with self.assertRaises(self.probe.ProbeError) as error: self.probe.read_state()
                self.assertEqual(str(error.exception), 'state unreadable')
                for name in ('vm-connection', 'git-registry'):
                    self.assertEqual(self.answer(name, code=1), {'error': 'state unreadable'})
                self.assertEqual(self.answer('browse', '', code=1), {'error': 'state unreadable'})

    def test_size_limit(self):
        self.write_state()
        size = (self.data / 'state.enc').stat().st_size
        with mock.patch.object(self.probe, 'MAX_STATE', size - 1):
            with self.assertRaises(self.probe.ProbeError) as error: self.probe.read_state()
        self.assertEqual(str(error.exception), 'state unreadable')
        with mock.patch.object(self.probe, 'MAX_STATE', size):
            self.assertIsInstance(self.probe.read_state(), dict)

    def test_reset_pending_wins(self):
        self.write_state()
        (self.data / '.reset-pending').mkdir()
        with mock.patch('app.lab_operations.remote') as remote, mock.patch('app.git_progress.remote_git') as remote_git:
            for argv in (('vm-connection',), ('git-registry',), ('browse', '')):
                with self.subTest(argv=argv):
                    self.assertEqual(self.answer(*argv, code=1), {'error': 'reset pending'})
        remote.assert_not_called(); remote_git.assert_not_called()


class DesignEngine(ProbeCase):
    def test_prints_engine_status_in_order(self):
        value = {'available': True, 'version': '26.9', 'path': '/usr/local/bin/netlab', 'diagnostic': ''}
        with mock.patch('app.design_engine.engine_status', return_value=dict(reversed(list(value.items())))):
            code, out, err = self.run_probe('design-engine')
        self.assertEqual((code, err), (0, ''))
        self.assertEqual(out, json.dumps(value) + '\n')

    def test_real_engine_status_shape_and_no_state_needed(self):
        value = self.answer('design-engine')
        self.assertEqual(list(value), ['available', 'version', 'path', 'diagnostic'])
        self.assertIsInstance(value['available'], bool)

    def test_unavailable(self):
        with mock.patch('app.design_engine.engine_status',
                        return_value={'available': False, 'version': '', 'path': '', 'diagnostic': 'x' * 900}):
            value = self.answer('design-engine')
        self.assertEqual(value['diagnostic'], 'x' * 600)


class VmConnection(ProbeCase):
    def test_prints_the_flags_and_never_the_secrets(self):
        self.write_state()
        value = self.answer('vm-connection')
        self.assertEqual(value, {'configured': True, 'connected': True,
                                 'host': {'address': '192.0.2.10', 'port': 22, 'username': 'clab-discovery', 'auth': 'password',
                                          'command_mode': 'helper', 'enabled': True, 'fingerprint_saved': True},
                                 'checked_at': '2026-11-01T10:00:00+00:00'})
        self.assertEqual(list(value), ['configured', 'connected', 'host', 'checked_at'])
        self.assertEqual(list(value['host']), ['address', 'port', 'username', 'auth', 'command_mode', 'enabled', 'fingerprint_saved'])

    def test_no_host(self):
        state = sample_state(); del state['host']; state['discovery'] = {}
        self.write_state(state)
        self.assertEqual(self.answer('vm-connection'), {'configured': False, 'connected': False, 'host': None, 'checked_at': None})
        state['host'] = {}
        self.write_state(state)
        self.assertEqual(self.answer('vm-connection')['host'], None)

    def test_stale_or_disabled_is_not_connected(self):
        state = sample_state(); state['discovery']['checked_epoch'] = time.time() - 3600
        self.write_state(state)
        self.assertIs(self.answer('vm-connection')['connected'], False)
        state = sample_state(); state['host']['enabled'] = False
        self.write_state(state)
        value = self.answer('vm-connection')
        self.assertEqual((value['connected'], value['host']['enabled']), (False, False))

    def test_odd_stored_values_keep_the_types(self):
        state = sample_state()
        state['host'].update(enabled='yes', fingerprint='', port='22', address=None, username=7)
        state['host'].pop('auth')
        state['discovery'] = {'ok': True, 'checked_at': 12}
        self.write_state(state)
        host = self.answer('vm-connection')['host']
        self.assertEqual(host, {'address': '', 'port': 0, 'username': '', 'auth': '', 'command_mode': 'helper',
                                'enabled': False, 'fingerprint_saved': False})
        self.assertIsNone(self.answer('vm-connection')['checked_at'])

    def test_long_address_is_capped(self):
        state = sample_state(); state['host']['address'] = 'a' * 700
        self.write_state(state)
        self.assertEqual(len(self.answer('vm-connection')['host']['address']), 600)


class Browse(ProbeCase):
    def setUp(self):
        super().setUp()
        self.write_state()

    def test_roots(self):
        result = {'path': '', 'entries': [{'name': '/srv/labs', 'path': '/srv/labs', 'directory': True}]}
        with mock.patch('app.lab_operations.remote', return_value=result) as remote:
            value = self.answer('browse', '')
        self.assertEqual(value, result)
        host, request = remote.call_args.args
        self.assertEqual(request, {'mode': 'browse', 'path': ''})
        self.assertEqual(remote.call_args.kwargs, {'timeout': 25})
        self.assertEqual(host['password'], PASSWORD)   # the manager's own client gets the saved connection

    def test_folder_entries_are_normalised(self):
        entries = [{'name': 'lab1', 'path': '/srv/labs/lab1', 'directory': True, 'kind': 'directory', 'extra': 'x'},
                   {'name': 'a.clab.yml', 'path': '/srv/labs/a.clab.yml', 'directory': False, 'size': 3},
                   {'name': 'odd', 'path': '/srv/labs/odd', 'directory': 'yes'},
                   'not an entry', {'name': 1, 'path': '/x'}, {'name': 'x'},
                   {'name': 'long', 'path': '/srv/labs/' + 'l' * 700, 'directory': True}]
        with mock.patch('app.lab_operations.remote', return_value={'path': '/srv/labs', 'parent': '/srv', 'entries': entries}):
            value = self.answer('browse', '/srv/labs')
        self.assertEqual(value, {'path': '/srv/labs', 'entries': [
            {'name': 'lab1', 'path': '/srv/labs/lab1', 'directory': True},
            {'name': 'a.clab.yml', 'path': '/srv/labs/a.clab.yml', 'directory': False},
            {'name': 'odd', 'path': '/srv/labs/odd', 'directory': False}]})
        self.assertEqual(list(value), ['path', 'entries'])

    def test_at_most_500_entries(self):
        entries = [{'name': f'd{i}', 'path': f'/srv/d{i}', 'directory': True} for i in range(700)]
        with mock.patch('app.lab_operations.remote', return_value={'path': '/srv', 'entries': entries}):
            self.assertEqual(len(self.answer('browse', '/srv')['entries']), 500)

    def test_helper_sentence_is_passed_through_scrub(self):
        cases = {ValueError('Choose a project directory.'): 'Choose a project directory.',
                 ValueError('Path is outside trusted roots.'): 'Path is outside trusted roots.',
                 ValueError('failed for ' + PASSWORD + ' and ' + NODE_SECRET): 'failed for [redacted] and [redacted]',
                 ValueError('Unknown request mode.'): "This VM's manager tools need an update; ask your instructor or administrator.",
                 ValueError('x' * 1000): 'x' * 600,
                 OSError('connect to 192.0.2.10 failed ' + PASSWORD): 'Cannot reach the VM operations helper. Check setup and SSH settings.',
                 RuntimeError(PASSWORD): 'Cannot reach the VM operations helper. Check setup and SSH settings.',
                 type('SSHException', (Exception,), {})('auth'): 'Cannot reach the VM operations helper. Check setup and SSH settings.'}
        for error, sentence in cases.items():
            with self.subTest(error=repr(error)[:60]), mock.patch('app.lab_operations.remote', side_effect=error):
                self.assertEqual(self.answer('browse', '/srv/labs', code=1), {'error': sentence})

    def helper_error(self, text):
        failure = ValueError(text); failure.from_helper = True   # as lab_operations.remote marks the helper's own line
        return failure

    def test_managers_fixed_sentences_reach_the_check_verbatim(self):
        # scrub()'s line rule would replace any sentence that says "password " with "[sensitive output omitted]"; the
        # manager's own sentences hold no secret, and the password-setup one is the only way forward for the operator.
        from app.discovery import vm_password
        with self.assertRaises(ValueError) as setup: vm_password({})
        sentence = str(setup.exception)
        self.assertIn('password ', sentence)
        state = sample_state(); state['host'].pop('password')
        self.write_state(state)
        self.assertEqual(self.answer('browse', '', code=1), {'error': sentence})   # the real client raises it
        self.write_state()
        for text in (sentence, 'This does not indicate a wrong password; discovery uses the same account.'):
            with self.subTest(text=text), mock.patch('app.lab_operations.remote', side_effect=ValueError(text)):
                self.assertEqual(self.answer('browse', '/srv/labs', code=1), {'error': text})

    def test_helper_lines_are_scrubbed_whole(self):
        cases = {'enable password: hunter2 rejected': '[sensitive output omitted]',
                 'failed for ' + PASSWORD: 'failed for [redacted]',
                 '\x1b[31mPath is outside trusted roots.\x1b[0m': 'Path is outside trusted roots.',
                 'Unknown request mode.': "This VM's manager tools need an update; ask your instructor or administrator."}
        for text, sentence in cases.items():
            with self.subTest(text=text), mock.patch('app.lab_operations.remote', side_effect=self.helper_error(text)):
                self.assertEqual(self.answer('browse', '/srv/labs', code=1), {'error': sentence})

    def test_unusable_answers(self):
        for result in (None, [], 'x', {'path': '/srv'}, {'path': '/srv', 'entries': {}}):
            with self.subTest(result=result), mock.patch('app.lab_operations.remote', return_value=result):
                self.assertEqual(self.answer('browse', '/srv', code=1),
                                 {'error': 'The VM operations helper returned an answer the manager cannot use.'})

    def test_helper_path_is_printed_as_the_helper_answered(self):
        with mock.patch('app.lab_operations.remote', return_value={'path': '/srv/labs', 'entries': []}):
            self.assertEqual(self.answer('browse', '/srv/labs/'), {'path': '/srv/labs', 'entries': []})
        with mock.patch('app.lab_operations.remote', return_value={'entries': []}):
            self.assertEqual(self.answer('browse', '/srv/labs'), {'path': '', 'entries': []})

    def test_no_connection_answers_the_managers_sentence(self):
        state = sample_state(); state['host']['enabled'] = False
        self.write_state(state)
        self.assertEqual(self.answer('browse', '', code=1), {'error': 'Configure and enable the VM connection first.'})

    def test_real_client_unreachable_vm(self):
        """The manager's own client against a closed loopback port: the fixed sentence, no traceback, no secret."""
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        state = sample_state(); state['host'].update(address='127.0.0.1', port=port)
        self.write_state(state)
        self.assertEqual(self.answer('browse', '', code=1),
                         {'error': 'Cannot reach the VM operations helper. Check setup and SSH settings.'})

    def test_paramiko_logging_never_reaches_stderr(self):
        def noisy(*args, **kwargs):
            logging.getLogger('paramiko.transport').error('Exception (client): %s', PASSWORD)
            import warnings; warnings.warn('deprecated ' + PASSWORD)
            raise OSError('x')
        with mock.patch('app.lab_operations.remote', side_effect=noisy):
            self.answer('browse', '/srv', code=1)
        self.assertFalse(logging.root.manager.disable, 'the probe must restore logging for the rest of the process')


class GitRegistry(ProbeCase):
    def setUp(self):
        super().setUp()
        self.write_state()

    def test_counts_and_never_the_registrations(self):
        result = {'protocol': 'clab-manager-git-v1', 'version': '1.31.8',
                  'repositories': [{'owner': 'alice', 'path': '/home/alice/course', 'push_url': 'git@github.com:a/b.git', 'id': 'x'},
                                   {'owner': 'bob', 'path': '/home/bob/c', 'push_url': '', 'id': 'y'}]}
        with mock.patch('app.git_progress.remote_git', return_value=result) as remote_git:
            status, out, err = self.run_probe('git-registry')
        self.assertEqual((status, err), (0, ''))
        self.assertEqual(out, json.dumps({'protocol': 'clab-manager-git-v1', 'version': '1.31.8', 'repositories': 2, 'bound_labs': 2}) + '\n')
        for detail in ('alice', '/home/bob', 'github.com', 'b1', 'example.invalid'):
            self.assertNotIn(detail, out)
        host, request = remote_git.call_args.args
        self.assertEqual(request, {'mode': 'list'})
        self.assertEqual(remote_git.call_args.kwargs, {})
        self.assertEqual(host['fingerprint'], FINGERPRINT)

    def test_odd_fields(self):
        with mock.patch('app.git_progress.remote_git', return_value={'protocol': 5, 'repositories': []}):
            self.assertEqual(self.answer('git-registry'), {'protocol': '', 'version': '', 'repositories': 0, 'bound_labs': 2})
        with mock.patch('app.git_progress.remote_git', return_value={'protocol': 'p', 'version': 'v', 'repositories': 'x'}):
            self.assertEqual(self.answer('git-registry', code=1), {'error': 'Invalid repository list.'})

    def test_errors(self):
        from app import git_progress
        from app.discovery import vm_password
        from app.lab_operations import scrub
        fixed = next(iter(git_progress.PROBLEM_CODES))
        # The exemption matters only for a sentence scrub() would change: every such PROBLEM_CODES sentence (the push
        # preflight one says "password ") must still be printed verbatim, or the exemption is not proved.
        scrubbed = [sentence for sentence in git_progress.PROBLEM_CODES if scrub(sentence, {'labs': []}) != sentence]
        self.assertTrue(any(s.startswith('Git push preflight failed.') for s in scrubbed), scrubbed)
        with self.assertRaises(ValueError) as setup: vm_password({})
        cases = {ValueError('Install or refresh the matching Git helper on the VM.'): 'Install or refresh the matching Git helper on the VM.',
                 ValueError(fixed): fixed,
                 **{ValueError(sentence): sentence for sentence in scrubbed},
                 ValueError(str(setup.exception)): str(setup.exception),
                 ValueError('fatal: password: hunter2'): '[sensitive output omitted]',
                 ValueError('bad ' + PASSWORD): 'bad [redacted]',
                 ValueError('y' * 900): 'y' * 600,
                 OSError(PASSWORD): git_progress.VM_UNREACHABLE,
                 TimeoutError(): git_progress.VM_UNREACHABLE}
        for error, sentence in cases.items():
            with self.subTest(error=repr(error)[:60]), mock.patch('app.git_progress.remote_git', side_effect=error):
                self.assertEqual(self.answer('git-registry', code=1), {'error': sentence})

    def test_no_saved_connection(self):
        state = sample_state(); state['host'] = {}
        self.write_state(state)
        self.assertEqual(self.answer('git-registry', code=1), {'error': 'Connect the VM and verify its SSH host fingerprint first.'})

    def test_password_setup_sentence_from_the_real_client(self):
        from app.discovery import vm_password
        with self.assertRaises(ValueError) as setup: vm_password({})
        state = sample_state(); state['host']['auth'] = 'key'
        self.write_state(state)
        self.assertEqual(self.answer('git-registry', code=1), {'error': str(setup.exception)})


class Capture(ProbeCase):
    KEYS = ['enabled', 'provider', 'message', 'targets', 'ready', 'diagnostic']

    def environment(self, **values):
        patch = mock.patch.dict(os.environ, values)
        patch.start(); self.addCleanup(patch.stop)

    def test_disabled(self):
        value = self.answer('capture')
        self.assertEqual(value, {'enabled': False, 'provider': 'disabled',
                                 'message': 'Packet capture is optional. Follow Capture setup to enable it.',
                                 'targets': None, 'ready': None, 'diagnostic': ''})
        self.assertEqual(list(value), self.KEYS)

    def test_configuration_errors_are_the_message(self):
        cases = [({'CAPTURE_PROVIDER': 'wireshark'}, 'Unknown capture provider. Supported values: disabled, edgeshark.'),
                 ({'CAPTURE_PROVIDER': 'edgeshark'}, 'Run deploy/setup-capture.sh to enable browser capture, then recreate the manager.'),
                 ({'CAPTURE_PROVIDER': 'edgeshark', 'CAPTURE_EDGESHARK_URL': 'http://127.0.0.1:5001', 'CAPTURE_SESSION_TOKEN': 'short'},
                  'Run deploy/setup-capture.sh to configure the browser capture service and its token.'),
                 ({'CAPTURE_PROVIDER': 'edgeshark', 'CAPTURE_EDGESHARK_URL': 'ftp://x'},
                  'Capture URLs must be HTTP(S) service addresses without credentials, query strings or fragments.')]
        for values, message in cases:
            with self.subTest(values=values), mock.patch.dict(os.environ, values):
                self.assertEqual(self.answer('capture'), {'enabled': False, 'provider': 'disabled', 'message': message,
                                                          'targets': None, 'ready': None, 'diagnostic': ''})

    def test_route_sentences_are_the_routes_own(self):
        source = (ROOT / 'app' / 'capture.py').read_text()
        for sentence in ('Ready to discover live interfaces.', 'Packet capture is optional. Follow Capture setup to enable it.'):
            self.assertIn(repr(sentence), source)

    def enabled(self):
        self.environment(CAPTURE_PROVIDER='edgeshark', CAPTURE_EDGESHARK_URL='http://127.0.0.1:5001',
                         CAPTURE_SESSION_URL='http://127.0.0.1:5801', CAPTURE_SESSION_TOKEN=TOKEN)

    def test_enabled_counts_merged_namespaces(self):
        self.enabled()
        rows = [{'name': 'host', 'type': 'proc', 'prefix': '', 'netns': 1, 'pid': 1, 'starttime': 1, 'network-interfaces': ['eth0']},
                {'name': 'clab-manager', 'type': 'docker', 'prefix': '', 'netns': 1, 'pid': 9, 'starttime': 2, 'network-interfaces': ['eth0']},
                {'name': 'clab-x-r1', 'type': 'docker', 'prefix': '', 'netns': 2, 'pid': 10, 'starttime': 3, 'network-interfaces': ['eth1']}]
        with mock.patch('app.capture.read_discovery', return_value={'containers': rows}) as read, \
                mock.patch('app.capture_sessions.BrowserSessions.request', return_value={'ready': True, 'max_sessions': 4}) as health:
            value = self.answer('capture')
        self.assertEqual(value, {'enabled': True, 'provider': 'edgeshark', 'message': 'Ready to discover live interfaces.',
                                 'targets': 2, 'ready': True, 'diagnostic': ''})
        self.assertEqual(read.call_args.args, ('http://127.0.0.1:5001/discover/mobyshark',))
        self.assertEqual(health.call_args.args, ('GET', 'health'))

    def test_discovery_and_service_failures(self):
        self.enabled()
        from app.capture import CaptureError
        from fastapi import HTTPException
        with mock.patch('app.capture.read_discovery', side_effect=CaptureError('Edgeshark discovery timed out. Check the service and retry.')), \
                mock.patch('app.capture_sessions.BrowserSessions.request', side_effect=HTTPException(502, 'Cannot reach.')):
            value = self.answer('capture')
        self.assertEqual(value, {'enabled': True, 'provider': 'edgeshark', 'message': 'Ready to discover live interfaces.',
                                 'targets': None, 'ready': None, 'diagnostic': 'Edgeshark discovery timed out. Check the service and retry.'})

    def test_ready_must_be_a_boolean(self):
        self.enabled()
        for answer, ready in (({'ready': False}, False), ({'ready': 'yes'}, None), ({}, None)):
            with self.subTest(answer=answer), mock.patch('app.capture.read_discovery', return_value={'containers': []}), \
                    mock.patch('app.capture_sessions.BrowserSessions.request', return_value=answer):
                value = self.answer('capture')
                self.assertEqual((value['targets'], value['ready']), (0, ready))

    def test_token_and_urls_never_printed(self):
        self.environment(CAPTURE_PROVIDER='edgeshark', CAPTURE_EDGESHARK_URL='http://edgeshark.internal:5001',
                         CAPTURE_SESSION_URL='http://sessions.internal:5801', CAPTURE_SESSION_TOKEN=TOKEN)
        from app.capture import CaptureError
        error = CaptureError('leak ' + TOKEN + ' http://edgeshark.internal:5001/ http://sessions.internal:5801')
        with mock.patch('app.capture.read_discovery', side_effect=error), \
                mock.patch('app.capture_sessions.BrowserSessions.request', return_value={'ready': True}):
            status, out, err = self.run_probe('capture')
        self.assertEqual((status, err), (0, ''))
        for secret in (TOKEN, 'edgeshark.internal', 'sessions.internal'):
            self.assertNotIn(secret, out)
        self.assertIn('[redacted]', json.loads(out)['diagnostic'])

    def test_real_loopback_services(self):
        """read_discovery and the session client for real, against two loopback HTTP servers."""
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                seen.append((handler.path, handler.headers.get('Authorization', '')))
                if handler.path == '/discover/mobyshark':
                    body = {'containers': [{'name': 'clab-x-r1', 'type': 'docker', 'prefix': '', 'netns': 5, 'pid': 3,
                                            'starttime': 4, 'network-interfaces': ['eth1', 'eth2']}]}
                elif handler.path == '/health':
                    body = {'ready': True, 'max_sessions': 4}
                else:
                    handler.send_response(404); handler.end_headers(); return
                data = json.dumps(body).encode()
                handler.send_response(200); handler.send_header('Content-Type', 'application/json')
                handler.send_header('Content-Length', str(len(data))); handler.end_headers(); handler.wfile.write(data)
            def log_message(handler, *args): pass
        servers = []
        for _ in range(2):
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
            self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        self.environment(CAPTURE_PROVIDER='edgeshark', CAPTURE_EDGESHARK_URL=f'http://127.0.0.1:{servers[0].server_port}',
                         CAPTURE_SESSION_URL=f'http://127.0.0.1:{servers[1].server_port}', CAPTURE_SESSION_TOKEN=TOKEN)
        value = self.answer('capture')
        self.assertEqual((value['enabled'], value['targets'], value['ready'], value['diagnostic']), (True, 1, True, ''))
        self.assertIn(('/health', 'Bearer ' + TOKEN), seen)
        servers[1].shutdown()
        servers[1].server_close()
        value = self.answer('capture')
        self.assertEqual((value['targets'], value['ready']), (1, None))


class Deadline(ProbeCase):
    """One overall deadline below the health check's 30 s exec timeout (EXPOSURE.md 6.1 rule 2): a probe whose VM or
    capture service accepts and never answers ends with its own error line instead of being killed (and, inside the
    container, outliving the killed `docker exec` client with an open SSH session)."""
    SLOW = 6

    def setUp(self):
        super().setUp()
        self.write_state()
        for name, value in (('DEADLINE', 0.5), ('GRACE', 0.5)):
            patch = mock.patch.object(self.probe, name, value); patch.start(); self.addCleanup(patch.stop)

    def slow(self, *args, **kwargs):
        time.sleep(self.SLOW)
        return {}

    def assert_deadline(self, *argv):
        started = time.monotonic()
        value = self.answer(*argv, code=1)
        elapsed = time.monotonic() - started
        self.assertEqual(value, {'error': self.probe.DEADLINE_SENTENCE})
        self.assertLess(elapsed, 2.5)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0), 'the probe left its timer armed')
        self.assertIs(signal.getsignal(signal.SIGALRM), signal.SIG_DFL, 'the probe left its handler installed')

    def test_sentence(self):
        self.assertEqual(self.probe.DEADLINE_SENTENCE, 'The probe did not finish within 25 seconds.')

    def test_constants_leave_room_under_the_exec_timeout(self):
        # DEADLINE + GRACE, plus the interpreter's start inside `docker exec`, stays under check_install's timeout=30.
        source = (ROOT / 'app' / 'probe.py').read_text()
        self.assertIn('\nDEADLINE = 25\n', source)
        self.assertIn('\nGRACE = 3\n', source)

    def test_browse_ends_at_the_deadline(self):
        with mock.patch('app.lab_operations.remote', side_effect=self.slow):
            self.assert_deadline('browse', '')

    def test_git_registry_ends_at_the_deadline(self):
        with mock.patch('app.git_progress.remote_git', side_effect=self.slow):
            self.assert_deadline('git-registry')

    def test_capture_ends_at_the_deadline_though_its_calls_swallow_errors(self):
        # Both capture calls sit under `except …Exception`: the deadline is not an Exception, so it is never taken for
        # a failed call (which would print a partial answer and keep waiting on the next call).
        patch = mock.patch.dict(os.environ, {'CAPTURE_PROVIDER': 'edgeshark', 'CAPTURE_EDGESHARK_URL': 'http://127.0.0.1:5001',
                                             'CAPTURE_SESSION_URL': 'http://127.0.0.1:5801', 'CAPTURE_SESSION_TOKEN': TOKEN})
        patch.start(); self.addCleanup(patch.stop)
        with mock.patch('app.capture.read_discovery', return_value={'containers': []}), \
                mock.patch('app.capture_sessions.BrowserSessions.request', side_effect=self.slow):
            self.assert_deadline('capture')
        with mock.patch('app.capture.read_discovery', side_effect=self.slow), \
                mock.patch('app.capture_sessions.BrowserSessions.request', return_value={'ready': True}) as health:
            self.assert_deadline('capture')
        health.assert_not_called()

    def test_a_fast_probe_is_untouched_and_leaves_no_timer(self):
        with mock.patch('app.git_progress.remote_git', return_value={'protocol': 'p', 'version': 'v', 'repositories': []}):
            self.assertEqual(self.answer('git-registry')['repositories'], 0)
        time.sleep(0.8)   # past DEADLINE + GRACE: a timer left armed would end this process
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL), (0.0, 0.0))

    def test_previous_alarm_handler_is_restored(self):
        def mine(*args): pass
        previous = signal.signal(signal.SIGALRM, mine)
        self.addCleanup(signal.signal, signal.SIGALRM, previous)
        with mock.patch('app.lab_operations.remote', side_effect=self.slow):
            self.assertEqual(self.answer('browse', '', code=1), {'error': self.probe.DEADLINE_SENTENCE})
        self.assertIs(signal.getsignal(signal.SIGALRM), mine)

    def test_real_client_against_a_vm_that_never_answers(self):
        """paramiko's own connect (banner_timeout 8 s) against a port that accepts and stays silent."""
        import socket
        quiet = mock.patch.object(logging.getLogger('paramiko'), 'disabled', True)   # the test process's own log
        quiet.start(); self.addCleanup(quiet.stop)
        server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(8)
        self.addCleanup(server.close)
        state = sample_state(); state['host'].update(address='127.0.0.1', port=server.getsockname()[1])
        self.write_state(state)
        self.assert_deadline('browse', '')
        self.assert_deadline('git-registry')
        # As a program: the cut-short transport thread logs its own end after main() returned; nothing reaches stderr.
        code = ('import sys, time\n'
                'from app import probe\n'
                'probe.DEADLINE = 0.5\n'
                'status = probe.program(sys.argv[1:])\n'
                'time.sleep(1)\n'
                'sys.exit(status)\n')
        env = dict(os.environ, DATA_DIR=str(self.data), PYTHONPATH=str(ROOT))
        for argv in (['browse', ''], ['git-registry']):
            with self.subTest(argv=argv):
                result = subprocess.run([sys.executable, '-c', code, *argv], cwd=ROOT, capture_output=True, text=True,
                                        env=env, timeout=30)
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (1, json.dumps({'error': self.probe.DEADLINE_SENTENCE}) + '\n', ''))
        source = (ROOT / 'app' / 'probe.py').read_text()
        self.assertTrue(source.rstrip().endswith("if __name__ == '__main__':\n    sys.exit(program())"))

    def test_a_probe_that_ignores_the_deadline_is_ended_after_the_grace(self):
        """A client that swallows even the deadline (a bare `except:`) is ended by the second firing: the same one line,
        exit 1, nothing on stderr."""
        code = ('import sys, time\n'
                'from unittest import mock\n'
                'from app import probe\n'
                'probe.DEADLINE = 0.5; probe.GRACE = 0.5\n'
                'def stubborn(*a, **k):\n'
                '    while True:\n'
                '        try: time.sleep(5)\n'
                '        except BaseException: pass\n'
                'with mock.patch("app.lab_operations.remote", side_effect=stubborn):\n'
                '    sys.exit(probe.main(["browse", ""]))\n')
        env = dict(os.environ, DATA_DIR=str(self.data), PYTHONPATH=str(ROOT))
        started = time.monotonic()
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, env=env, timeout=30)
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual((result.returncode, result.stdout, result.stderr),
                         (1, json.dumps({'error': self.probe.DEADLINE_SENTENCE}) + '\n', ''))


class Isolation(ProbeCase):
    def test_unexpected_failure_is_a_fixed_sentence(self):
        with mock.patch('app.design_engine.engine_status', side_effect=KeyError(PASSWORD)):
            self.assertEqual(self.answer('design-engine', code=1), {'error': 'The probe failed unexpectedly.'})

    def test_never_imports_the_manager_or_its_store(self):
        import socket
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        state = sample_state(); state['host'].update(address='127.0.0.1', port=port)
        self.write_state(state)
        code = ('import json, sys\n'
                'from app import probe\n'
                'codes = [probe.main([name]) for name in ("design-engine", "capture", "vm-connection", "git-registry")]\n'
                'codes.append(probe.main(["browse", ""]))\n'
                'sys.stderr.write(json.dumps([codes, sorted(m for m in sys.modules if m.startswith("app."))]))\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith('CAPTURE_')}
        env.update(DATA_DIR=str(self.data), PYTHONPATH=str(ROOT))
        before = snapshot(self.dir)
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(snapshot(self.dir), before)
        codes, modules = json.loads(result.stderr)
        self.assertEqual(codes[:3], [0, 0, 0])   # git-registry and browse fail to reach the VM, which is an answer
        self.assertEqual(codes[3:], [1, 1])
        for forbidden in ('app.main', 'app.store', 'app.sessions', 'app.accounts'):
            self.assertNotIn(forbidden, modules)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 5)
        for line in lines: json.loads(line)
        for secret in (PASSWORD, FINGERPRINT, NODE_SECRET):
            self.assertNotIn(secret, result.stdout)

    def test_source_never_names_a_store_or_the_app_factory(self):
        source = (ROOT / 'app' / 'probe.py').read_text()
        for word in ('Store(', 'create_app', 'from .store', 'import store', 'from .main', 'GitProgress(', 'Captures(',
                     'Discovery(', 'LabOperations(', 'write_bytes', 'write_text', "open('w", 'os.replace', 'unlink', 'mkdir'):
            self.assertFalse(word in source, word)


if __name__ == '__main__':
    unittest.main()
