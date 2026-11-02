"""First-run bootstrap and recovery (DESIGN.md 9.2, 9.5, 3.3; BUILD.md S1a).

Unit level: the setup code, its file and its normalisation, read_setup_code's refusals, the recovery
command, complete_setup, and Store.reset keeping users and the audit files. The route-level cases
(setup mode's answers, POST /api/setup, the container log line from create_app, the 404 after setup)
are S1b's part of this file.
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import accounts, recover
from app.accounts import (Accounts, AccountError, SETUP_ALPHABET, CODE_LENGTH, generate_code, format_code, normalize_code,
                          code_matches, write_setup_code, read_setup_code, delete_setup_code)
from app.store import Store

HASH = accounts.hash_password('correct horse battery staple', {'n': 2**14, 'r': 8, 'p': 1})


def no_secret_in_logs(root, *secrets, captured=''):
    text = captured + ''.join(p.read_text() for p in Path(root).glob('*.jsonl*'))
    for secret in secrets:
        if secret and secret in text: raise AssertionError('a secret reached a log')
        if secret and normalize_code(secret) in normalize_code(text): raise AssertionError('a secret reached a log (normalised)')


class SetupCodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_code_alphabet_length_and_groups(self):
        self.assertEqual(SETUP_ALPHABET, 'abcdefghjkmnpqrstuvwxyz23456789')
        self.assertEqual(len(set(SETUP_ALPHABET)), 31)
        for banned in '0o1li': self.assertNotIn(banned, SETUP_ALPHABET)
        self.assertEqual(CODE_LENGTH, 24)
        codes = {generate_code() for _ in range(20)}
        self.assertEqual(len(codes), 20)
        for code in codes:
            self.assertEqual(len(code), 24); self.assertTrue(set(code) <= set(SETUP_ALPHABET))
        self.assertRegex(format_code('abcdefghjkmnpqrstuvwxyz2'), r'^[a-z2-9]{6}-[a-z2-9]{6}-[a-z2-9]{6}-[a-z2-9]{6}$')
        self.assertEqual(format_code('abcdefghjkmnpqrstuvwxyz2'), 'abcdef-ghjkmn-pqrstu-vwxyz2')

    def test_matching_forgives_how_a_code_was_copied(self):
        code = 'abcdef-ghjkmn-pqrstu-vwxyz2'
        for typed in (code, code.upper(), 'abcdefghjkmnpqrstuvwxyz2', 'abcdef ghjkmn pqrstu vwxyz2', ' abcdef-ghjkmn- pqrstu-vwxyz2 \n', 'ABCDEF-GHJKMN-PQRSTU-VWXYZ2'):
            self.assertEqual(normalize_code(typed), 'abcdefghjkmnpqrstuvwxyz2', repr(typed))
            self.assertTrue(code_matches(code, typed), repr(typed))
        for wrong in ('abcdef-ghjkmn-pqrstu-vwxyz3', 'abcdef-ghjkmn-pqrstu-vwxyz', '', None, 'abcdef_ghjkmn_pqrstu_vwxyz2'):
            self.assertFalse(code_matches(code, wrong), repr(wrong))
        self.assertEqual(normalize_code(None), '')
        with patch('app.accounts.hmac.compare_digest', return_value=True) as compare:
            self.assertTrue(code_matches(code, 'anything'))
            compare.assert_called_once()

    def test_write_setup_code_writes_a_0600_file_with_two_lines(self):
        code = write_setup_code(self.root, 'setup')
        path = self.root/'setup-code'
        self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')
        lines = path.read_text().splitlines()
        self.assertEqual(lines, ['mode=setup', 'code=' + code])
        self.assertRegex(code, r'^[a-z2-9]{6}-[a-z2-9]{6}-[a-z2-9]{6}-[a-z2-9]{6}$')
        self.assertEqual(read_setup_code(self.root), ('setup', code))
        second = write_setup_code(self.root, 'recover')
        self.assertNotEqual(second, code, 'a new code each time')
        self.assertEqual(read_setup_code(self.root), ('recover', second))
        self.assertFalse(list(self.root.glob('*.tmp')))
        delete_setup_code(self.root)
        self.assertIsNone(read_setup_code(self.root))
        delete_setup_code(self.root)   # absent is fine

    def test_read_setup_code_refuses_what_design_9_2_lists(self):
        path = self.root/'setup-code'
        self.assertIsNone(read_setup_code(self.root), 'absent')
        code = write_setup_code(self.root, 'setup')
        os.chmod(path, 0o640)
        self.assertIsNone(read_setup_code(self.root), 'wider than 0600')
        os.chmod(path, 0o600)
        self.assertEqual(read_setup_code(self.root), ('setup', code))
        target = self.root/'elsewhere'; target.write_text(path.read_text()); os.chmod(target, 0o600)
        path.unlink(); path.symlink_to(target)
        self.assertIsNone(read_setup_code(self.root), 'a symlink')
        path.unlink()
        for label, text in {
            'no mode': 'code=' + code + '\n', 'bad mode': 'mode=open\ncode=' + code + '\n', 'no code': 'mode=setup\n',
            'short code': 'mode=setup\ncode=abcdef\n', 'bad symbol': 'mode=setup\ncode=' + code[:-1] + '0\n', 'empty': '',
            'not key=value': 'setup\n' + code + '\n', 'binary': 'mode=setup\ncode=\x00\x01\n',
        }.items():
            Store.atomic(path, text.encode())
            self.assertIsNone(read_setup_code(self.root), label)
        Store.atomic(path, ('MODE=setup\ncode=' + code + '\n').encode())
        self.assertIsNone(read_setup_code(self.root), 'keys are exact')
        Store.atomic(path, ('mode=setup\ncode=' + code.upper() + '\n').encode())
        self.assertEqual(read_setup_code(self.root), ('setup', code.upper()), 'the file text is returned as written; matching normalises')
        path.unlink(); path.mkdir()
        self.assertIsNone(read_setup_code(self.root), 'a directory')

    def test_a_recover_file_older_than_15_minutes_is_deleted_and_reported(self):
        path = self.root/'setup-code'
        code = write_setup_code(self.root, 'recover')
        old = time.time() - 14*60
        os.utime(path, (old, old))
        self.assertEqual(read_setup_code(self.root), ('recover', code), 'fourteen minutes is still valid')
        older = time.time() - 16*60
        os.utime(path, (older, older))
        expired = []
        self.assertIsNone(read_setup_code(self.root, on_expired=lambda: expired.append(1)))
        self.assertEqual(expired, [1]); self.assertFalse(path.exists())
        self.assertIsNone(read_setup_code(self.root, on_expired=lambda: expired.append(2)))
        self.assertEqual(expired, [1], 'reported once')
        code = write_setup_code(self.root, 'setup')
        os.utime(path, (older, older))
        self.assertEqual(read_setup_code(self.root), ('setup', code), 'a setup code is valid until used')
        self.assertEqual(accounts.RECOVER_TTL, 900)

    def test_the_accounts_object_audits_recover_expired(self):
        store = Store(self.tmp.name)
        service = Accounts(store)
        write_setup_code(self.root, 'recover')
        older = time.time() - 16*60; os.utime(self.root/'setup-code', (older, older))
        self.assertIsNone(service.read_setup_code())
        entry, = [json.loads(l) for l in (self.root/'audit.jsonl').read_text().splitlines()]
        self.assertEqual((entry['event'], entry['actor'], entry['outcome']), ('recover.expired', '-', 'ok'))

    def test_the_container_log_line_names_the_file_and_the_command_never_the_code(self):
        code = write_setup_code(self.root, 'setup')
        line = accounts.setup_log_line(self.root, '8443', 'lab.example')
        self.assertEqual(line, f'Setup required: open https://lab.example:8443/setup and enter the code from {self.root}/setup-code '
                               '(on the VM: sudo cat /srv/containerlab-node-manager/data/setup-code).')
        self.assertNotIn(code, line); self.assertNotIn(normalize_code(code), normalize_code(line))
        self.assertIn("the VM's address", accounts.setup_log_line(self.root, 8443, ''))


class RecoverCommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        store = Store(self.tmp.name)
        with store.lock:
            store.state['users'] = {'root': accounts.new_record('root', 'admin', HASH, created_by='setup', must_change_password=False)}
            store.save()
        self.state_before = (self.root/'state.enc').read_bytes()

    def run_recover(self, **env):
        out = io.StringIO()
        with patch('app.store.Store.__init__', side_effect=AssertionError('app.recover must not construct a Store')):
            with patch.dict(os.environ, {'DATA_DIR': str(self.root), **env}):
                code = recover.main(out=out)
        return code, out.getvalue()

    def test_refuses_in_setup_mode_and_touches_nothing(self):
        setup_code = write_setup_code(self.root, 'setup')
        before = (self.root/'setup-code').read_text()
        code, output = self.run_recover()
        self.assertEqual(code, 1)
        self.assertEqual(output, f'The manager is in setup mode: use the setup code in {self.root}/setup-code.\n')
        self.assertEqual((self.root/'setup-code').read_text(), before)
        self.assertFalse((self.root/'audit.jsonl').exists())
        self.assertNotIn(setup_code, output)
        # Even a setup file the reader refuses (wrong mode bits) is not replaced by a recovery file.
        os.chmod(self.root/'setup-code', 0o644)
        self.assertEqual(self.run_recover()[0], 1)
        self.assertEqual((self.root/'setup-code').read_text(), before)

    def test_writes_a_0600_recover_file_prints_the_code_and_its_validity_and_nothing_else(self):
        code, output = self.run_recover()
        self.assertEqual(code, 0)
        lines = output.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r'^Recovery code: [a-z2-9]{6}-[a-z2-9]{6}-[a-z2-9]{6}-[a-z2-9]{6}$')
        self.assertEqual(lines[1], 'Valid for 15 minutes. Create one new administrator on the setup page; existing accounts are not changed.')
        self.assertNotIn('http', output); self.assertNotIn('/setup', output)
        path = self.root/'setup-code'
        self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')
        printed = lines[0].split(': ')[1]
        self.assertEqual(path.read_text().splitlines(), ['mode=recover', 'code=' + printed])
        self.assertEqual(read_setup_code(self.root), ('recover', printed))
        entry, = [json.loads(l) for l in (self.root/'audit.jsonl').read_text().splitlines()]
        self.assertEqual({k: entry[k] for k in ('event', 'actor', 'source', 'outcome', 'target', 'detail')},
                         {'event': 'recover.requested', 'actor': '-', 'source': '-', 'outcome': 'ok', 'target': '', 'detail': ''})
        self.assertEqual((self.root/'state.enc').read_bytes(), self.state_before, 'state.enc is never opened for writing')
        self.assertEqual(json.loads(Store(self.tmp.name).cipher.decrypt(self.state_before))['users']['root']['password'], HASH)
        no_secret_in_logs(self.root, printed)
        # A second run replaces the code; an expired recovery file is reported on the way.
        older = time.time() - 16*60; os.utime(path, (older, older))
        code, output = self.run_recover()
        self.assertEqual(code, 0)
        self.assertEqual([e['event'] for e in (json.loads(l) for l in (self.root/'audit.jsonl').read_text().splitlines())],
                         ['recover.requested', 'recover.expired', 'recover.requested'])

    def test_a_failed_audit_append_does_not_hide_the_code(self):
        err = io.StringIO()
        with patch('app.store.Store.append_audit', side_effect=OSError('disk fixture')):
            with patch.dict(os.environ, {'DATA_DIR': str(self.root)}):
                out = io.StringIO(); code = recover.main(out=out, err=err)
        self.assertEqual(code, 0)
        self.assertEqual(len(out.getvalue().splitlines()), 2)
        self.assertIn('audit', err.getvalue().lower()); self.assertNotIn('disk fixture', err.getvalue())

    def test_python_dash_m_app_recover_reads_data_dir(self):
        env = dict(os.environ, DATA_DIR=str(self.root))
        result = subprocess.run([sys.executable, '-m', 'app.recover'], cwd=Path(__file__).resolve().parents[1], env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 2)
        self.assertEqual(result.stderr, '')
        self.assertEqual(read_setup_code(self.root)[0], 'recover')
        write_setup_code(self.root, 'setup')
        result = subprocess.run([sys.executable, '-m', 'app.recover'], cwd=Path(__file__).resolve().parents[1], env=env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1)
        self.assertIn('setup mode', result.stdout)


class CompleteSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.tmp.name)
        self.calls = []
        store = self.store
        class Index:
            def set_user(_, record): self.calls.append(('set_user', record['name'], store.lock._is_owned(), (self.root/'setup-code').exists(),
                                                        record['name'] in json.loads(store.cipher.decrypt(store.path.read_bytes())).get('users', {})))
            def count(_, name): return 0
        self.accounts = Accounts(self.store, Index())

    def audit(self):
        path = self.root/'audit.jsonl'
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def test_setup_creates_the_first_admin_deletes_the_file_and_audits_in_one_block(self):
        code = write_setup_code(self.root, 'setup')
        record = self.accounts.complete_setup('root', HASH, code=code, mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
        self.assertEqual((record['role'], record['created_by'], record['must_change_password'], record['known_sources'], record['disabled']),
                         ('admin', 'setup', False, ['203.0.113.0/24'], False))
        self.assertIsNotNone(record['last_signin'], 'the setup sign-in counts')
        self.assertFalse((self.root/'setup-code').exists())
        self.assertEqual(self.calls, [('set_user', 'root', True, True, True)], 'index under the lock, after the save, before the file is deleted')
        entry = self.audit()[-1]
        self.assertEqual({k: entry[k] for k in ('event', 'actor', 'source', 'outcome', 'detail')},
                         {'event': 'setup', 'actor': 'root', 'source': '203.0.113.9', 'outcome': 'ok', 'detail': 'setup'})
        self.assertEqual(Store(self.tmp.name).state['users']['root']['password'], HASH)

    def test_recovery_creates_one_new_admin_and_never_overwrites(self):
        code = write_setup_code(self.root, 'setup')
        first = self.accounts.complete_setup('root', HASH, code=code, mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
        code = write_setup_code(self.root, 'recover')
        with self.assertRaises(AccountError) as refused:
            self.accounts.complete_setup('root', 'scrypt$other', code=code, mode='recover', source='203.0.113.9', prefix='203.0.113.0/24')
        self.assertEqual(refused.exception.status, 409)
        self.assertEqual(refused.exception.detail, {'code': 'exists', 'message': 'That name already exists. Choose a new name for the recovery administrator.'})
        self.assertIs(self.store.state['users']['root'], first); self.assertEqual(first['password'], HASH)
        self.assertTrue((self.root/'setup-code').exists(), 'nothing written: the file stays')
        self.assertEqual([e['event'] for e in self.audit()], ['setup'])
        second = self.accounts.complete_setup('rescue', HASH, code=code, mode='recover', source='198.51.100.7', prefix='198.51.100.0/24')
        self.assertEqual((second['role'], second['created_by'], second['must_change_password']), ('admin', 'recover', False))
        self.assertEqual(self.store.state['users']['root'], first, 'existing users are untouched')
        self.assertFalse((self.root/'setup-code').exists())
        self.assertEqual(self.audit()[-1]['detail'], 'recover')
        with self.assertRaises(AccountError) as bad: self.accounts.complete_setup('Bad Name', HASH, code=code, mode='recover', source='x', prefix='y')
        self.assertEqual((bad.exception.status, bad.exception.detail['code']), (422, 'invalid_name'))

    def test_a_failed_save_keeps_the_file_and_the_record_out_of_memory(self):
        code = write_setup_code(self.root, 'setup')
        with patch.object(self.store, 'atomic', side_effect=OSError('disk fixture')):
            with self.assertRaises(OSError):
                self.accounts.complete_setup('root', HASH, code=code, mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
        self.assertTrue((self.root/'setup-code').exists())
        self.assertEqual(self.store.state.get('users', {}), {})
        self.assertEqual(self.calls, []); self.assertEqual(self.audit(), [])

    def test_one_code_creates_one_admin_when_two_submits_overlap(self):
        # Two requests past the route's code check inside the hash window: the second finds the file gone under
        # store.lock and is refused setup_closed; DESIGN 9.2 (valid until used) and 9.5 (exactly one admin).
        code = write_setup_code(self.root, 'setup')
        self.accounts.complete_setup('first', HASH, code=code, mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
        with self.assertRaises(AccountError) as refused:
            self.accounts.complete_setup('second', HASH, code=code, mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
        self.assertEqual((refused.exception.status, refused.exception.detail),
                         (404, {'code': 'setup_closed', 'message': 'Setup is closed. Sign in, or ask the VM administrator to run the recovery command.'}))
        self.assertEqual(sorted(self.store.state['users']), ['first'])
        self.assertEqual([e['event'] for e in self.audit()], ['setup'])
        self.assertEqual([c[1] for c in self.calls], ['first'])

    def test_the_code_and_the_mode_are_checked_again_under_the_lock(self):
        code = write_setup_code(self.root, 'setup')
        for wrong in (code[:-1] + ('a' if code[-1] != 'a' else 'b'), '', None):
            with self.assertRaises(AccountError) as refused:
                self.accounts.complete_setup('root', HASH, code=wrong, mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
            self.assertEqual((refused.exception.status, refused.exception.code), (404, 'setup_closed'))
        with self.assertRaises(AccountError) as refused:
            self.accounts.complete_setup('root', HASH, code=code, mode='recover', source='203.0.113.9', prefix='203.0.113.0/24')
        self.assertEqual(refused.exception.code, 'setup_closed', 'the file says setup; a caller that read recover is stale')
        self.assertEqual(self.store.state.get('users', {}), {}); self.assertTrue((self.root/'setup-code').exists())
        self.assertEqual(self.calls, []); self.assertEqual(self.audit(), [])
        self.accounts.complete_setup('root', HASH, code=code.upper().replace('-', ' '), mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
        self.assertEqual(sorted(self.store.state['users']), ['root'])

    def test_a_setup_file_left_while_users_exist_creates_nobody(self):
        code = write_setup_code(self.root, 'setup')
        self.accounts.complete_setup('root', HASH, code=code, mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
        Store.atomic(self.root/'setup-code', f'mode=setup\ncode={code}\n'.encode('utf8'))   # a restored /data, a failed unlink
        with self.assertRaises(AccountError) as refused:
            self.accounts.complete_setup('second', HASH, code=code, mode='setup', source='203.0.113.9', prefix='203.0.113.0/24')
        self.assertEqual((refused.exception.status, refused.exception.code), (404, 'setup_closed'))
        self.assertEqual(sorted(self.store.state['users']), ['root'])
        self.assertIsNone(self.accounts.read_setup_code(), 'the accounts object does not report a setup file once users exist')
        self.assertFalse((self.root/'setup-code').exists(), 'and removes it')
        code = write_setup_code(self.root, 'recover')
        self.assertEqual(self.accounts.read_setup_code(), ('recover', code), 'a recovery file is not stale')


class ResetKeepsUsersTests(unittest.TestCase):
    def test_reset_keeps_users_and_both_audit_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp); root = Path(tmp)
            with store.lock:
                store.state['users'] = {'root': accounts.new_record('root', 'admin', HASH, created_by='setup', must_change_password=False)}
                store.state['labs'] = [{'id': 'lab', 'name': 'Lab'}]
                store.save()
            store.audit('setup', actor='root', source='::1', outcome='ok', detail='setup')
            store.audit_failure('signin.failed', actor='-', source='::1', outcome='failed', detail='invalid_credentials count=1')
            (root/'backups').mkdir(); (root/'backups'/'x').write_text('x')
            store.reset()
            self.assertEqual(store.state['labs'], [])
            self.assertEqual(store.state['users']['root']['password'], HASH)
            self.assertEqual(Store(tmp).state['users']['root']['name'], 'root')
            self.assertEqual(len((root/'audit.jsonl').read_text().splitlines()), 1)
            self.assertEqual(len((root/'audit-failures.jsonl').read_text().splitlines()), 1)
            self.assertFalse((root/'backups').exists())


if __name__ == '__main__':
    unittest.main()


# ---- route level (BUILD.md S1b): setup mode, POST /api/setup, the log line from create_app, recovery through the routes ----
import logging
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import create_app, APP
from session_fixture import SignedInClient, PASSWORD, NAME, assert_not_logged, setup_code

HTML = {'Accept': 'text/html,application/xhtml+xml,*/*;q=0.8'}
SETUP_HTML = (APP/'static'/'setup.html').is_file()


def close_app(app):
    for name in ('design_apply', 'network_design', 'telemetry_retirement', 'restore', 'git_progress', 'operations', 'discovery',
                 'readiness', 'node_services', 'runner'):
        getattr(app.state, name).close()


class SetupModeRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        with self.assertLogs('app.main', level='WARNING') as captured:
            with patch.dict('os.environ', {'UI_PORT': '9443', 'UI_ALLOWED_HOSTS': ' Lab.Example.edu:8443, other.example'}):
                self.app = create_app(self.tmp.name)
        self.addCleanup(close_app, self.app)
        self.captured = '\n'.join(captured.output)
        self.client = TestClient(self.app); self.addCleanup(self.client.close)
        self.code = setup_code(self.app)

    def audit(self, name='audit.jsonl'):
        path = self.root/name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_create_app_writes_the_file_and_logs_the_line_without_the_code(self):
        path = self.root/'setup-code'
        self.assertEqual(oct(path.stat().st_mode & 0o777), '0o600')
        self.assertEqual(path.read_text().splitlines()[0], 'mode=setup')
        self.assertRegex(self.code, r'^[a-z2-9]{6}-[a-z2-9]{6}-[a-z2-9]{6}-[a-z2-9]{6}$')
        self.assertIn(f'Setup required: open https://lab.example.edu:9443/setup and enter the code from {path} '
                      '(on the VM: sudo cat /srv/containerlab-node-manager/data/setup-code).', self.captured)
        self.assertNotIn(self.code, self.captured); self.assertNotIn(normalize_code(self.code), normalize_code(self.captured))
        self.assertTrue(self.app.state.sessions.setup_mode())
        # A restart in setup mode regenerates the code; without UI_PORT and UI_ALLOWED_HOSTS the line says 8443 and the VM's address.
        with self.assertLogs('app.main', level='WARNING') as again:
            with patch.dict('os.environ', {'UI_PORT': '', 'UI_ALLOWED_HOSTS': ''}): other = create_app(self.tmp.name)
        self.addCleanup(close_app, other)
        self.assertNotEqual(setup_code(other), self.code)
        self.assertIn("open https://the VM's address:8443/setup", '\n'.join(again.output))
        assert_not_logged(self.app, self.code, setup_code(other), captured=self.captured + '\n'.join(again.output))

    def test_what_answers_in_setup_mode(self):
        for path in ('/', '/login', '/student-guide', '/static/app.js'):
            response = self.client.get(path, headers=HTML, follow_redirects=False)
            self.assertEqual((response.status_code, response.headers['location']), (302, '/setup'), path)
        for method, path in (('GET', '/api/state'), ('POST', '/api/session'), ('GET', '/api/session'), ('DELETE', '/api/session'), ('GET', '/api/users'), ('GET', '/static/app.js')):
            response = self.client.request(method, path, json={} if method != 'GET' else None)
            self.assertEqual(response.status_code, 503, (method, path))
            self.assertEqual(response.json()['detail'], {'code': 'setup_required', 'message': 'This manager is not set up yet. Open /setup to create the first administrator.'})
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with self.client.websocket_connect('/api/terminal', headers={'Origin': 'http://testserver'}): pass
        self.assertEqual((ctx.exception.code, ctx.exception.reason), (1008, 'setup_required'))
        self.assertEqual(self.client.get('/api/health').json(), {'ready': True})
        served = self.client.get('/setup', headers=HTML, follow_redirects=False)
        self.assertEqual(served.status_code, 200 if SETUP_HTML else 404, 'the gate serves /setup; the page itself is S7')
        self.assertEqual(self.client.get('/static/fabric-mark.svg').status_code, 200)
        self.assertNotIn(self.client.get('/static/login.css').status_code, (302, 503), 'an exempt asset reaches the mount')
        self.assertEqual(self.audit(), []); self.assertEqual(self.audit('audit-failures.jsonl'), [])

    def test_post_setup_creates_the_admin_deletes_the_file_and_signs_in(self):
        wrong = self.client.post('/api/setup', json={'code': 'abcdef-abcdef-abcdef-abcdef', 'username': 'root', 'password': PASSWORD})
        self.assertEqual((wrong.status_code, wrong.json()['detail']), (401, {'code': 'invalid_code', 'message': 'That setup code is not right. On the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code'}))
        bad_name = self.client.post('/api/setup', json={'code': self.code, 'username': 'Root!', 'password': PASSWORD})
        self.assertEqual((bad_name.status_code, bad_name.json()['detail']['code']), (422, 'invalid_name')); self.assertIn('message', bad_name.json()['detail'])
        weak = self.client.post('/api/setup', json={'code': self.code, 'username': 'root', 'password': 'root'})
        self.assertEqual((weak.status_code, weak.json()['detail']), (422, {'code': 'weak_password', 'reasons': ['too_short', 'equals_name'], 'message': 'Use at least 12 characters. Choose a password that is not your username.'}))
        self.assertEqual(self.client.post('/api/setup', json={'code': self.code, 'username': 'root', 'password': PASSWORD, 'role': 'admin'}).status_code, 422, "extra='forbid'")
        self.assertTrue((self.root/'setup-code').exists(), 'nothing consumed the code')
        typed = ' ' + self.code.upper().replace('-', '') [:12] + ' ' + self.code.upper().replace('-', '')[12:] + '\n'
        done = self.client.post('/api/setup', json={'code': typed, 'username': 'Root', 'password': PASSWORD})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()['user'], {'name': 'root', 'role': 'admin', 'must_change_password': False})
        self.assertIn('clab_session', done.headers['set-cookie'])
        self.assertFalse((self.root/'setup-code').exists())
        self.assertFalse(self.app.state.sessions.setup_mode())
        self.assertEqual(self.client.get('/api/state').status_code, 200)
        record = self.app.state.store.state['users']['root']
        self.assertEqual((record['created_by'], record['must_change_password'], record['known_sources']), ('setup', False, []))
        self.assertIsNotNone(record['last_signin'])
        self.assertEqual(self.client.get('/setup', headers=HTML, follow_redirects=False).status_code, 302, 'a live session is sent home')
        anonymous = TestClient(self.app); self.addCleanup(anonymous.close)
        self.assertEqual(anonymous.get('/setup', headers=HTML).status_code, 404)
        closed = anonymous.post('/api/setup', json={'code': self.code, 'username': 'second', 'password': PASSWORD})
        self.assertEqual((closed.status_code, closed.json()['detail']), (404, {'code': 'setup_closed', 'message': 'Setup is closed. Sign in, or ask the VM administrator to run the recovery command.'}))
        self.app.state.sessions.flush_failures(force=True)
        self.assertEqual([(e['event'], e['actor'], e['detail']) for e in self.audit('audit-failures.jsonl')],
                         [('setup.failed', '-', 'invalid_code count=1'), ('setup.failed', '-', 'invalid_name count=1'), ('setup.failed', '-', 'weak_password count=1')])
        self.assertEqual([(e['event'], e['actor'], e['detail']) for e in self.audit() if e['event'] in ('setup', 'signin')], [('setup', 'root', 'setup')])
        self.assertEqual([e for e in self.app.state.store.events() if e['action'] == 'api.request' and '/api/setup' in e['message']], [], 'no api.request for POST /api/setup (R8)')
        assert_not_logged(self.app, self.code, PASSWORD, self.client.cookies.get('clab_session'), captured=self.captured)

    def test_the_setup_route_is_throttled_like_a_sign_in(self):
        with patch.object(self.app.state.sessions, 'check', return_value=7):
            response = self.client.post('/api/setup', json={'code': self.code, 'username': 'root', 'password': PASSWORD})
        self.assertEqual((response.status_code, response.headers['retry-after'], response.json()['detail']), (429, '7', {'code': 'throttled', 'retry_after': 7, 'message': 'Too many sign-in attempts. Try again in 7 s.'}))
        self.assertTrue((self.root/'setup-code').exists())


class StaleSetupFileTests(unittest.TestCase):
    """A `mode=setup` file beside existing users (a restored /data, a failed unlink after the save) is removed by the
    next create_app and ignored, and removed, at run time; it never serves the page or creates an administrator."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.path = self.root/'setup-code'
        app = create_app(self.tmp.name)
        self.code = setup_code(app); self.saved = self.path.read_bytes()
        SignedInClient(app).close(); close_app(app)

    def restore_file(self):
        self.path.write_bytes(self.saved); self.path.chmod(0o600)

    def test_a_restart_removes_the_leftover_file_and_the_route_stays_closed(self):
        self.restore_file()
        with self.assertNoLogs('app.main', level='WARNING'):
            app = create_app(self.tmp.name)
        self.addCleanup(close_app, app)
        self.assertFalse(self.path.exists(), 'a restart with users removes a mode=setup file')
        self.assertFalse(app.state.sessions.setup_mode())
        anonymous = TestClient(app); self.addCleanup(anonymous.close)
        refused = anonymous.post('/api/setup', json={'code': self.code, 'username': 'second', 'password': PASSWORD})
        self.assertEqual((refused.status_code, refused.json()['detail']['code']), (404, 'setup_closed'))
        self.assertEqual(anonymous.get('/setup', headers=HTML).status_code, 404)
        self.assertEqual(sorted(app.state.store.state['users']), [NAME])

    def test_a_file_that_appears_at_run_time_is_ignored_and_removed(self):
        app = create_app(self.tmp.name); self.addCleanup(close_app, app)
        anonymous = TestClient(app); self.addCleanup(anonymous.close)
        self.restore_file()
        self.assertEqual(anonymous.get('/setup', headers=HTML).status_code, 404)
        self.assertFalse(self.path.exists())
        self.restore_file()
        refused = anonymous.post('/api/setup', json={'code': self.code, 'username': 'second', 'password': PASSWORD})
        self.assertEqual((refused.status_code, refused.json()['detail']['code']), (404, 'setup_closed'))
        self.assertFalse(self.path.exists())
        self.assertEqual(sorted(app.state.store.state['users']), [NAME])
        self.assertEqual([e for e in (json.loads(l) for l in (self.root/'audit.jsonl').read_text().splitlines()) if e['event'] == 'setup'][1:], [])

    def test_two_overlapping_submits_of_one_code_create_one_admin(self):
        # Through the route: both pass the first read and the code comparison, the hash is awaited, the second is
        # refused under store.lock. A fixed name shows the double-click case: one 200, one 404 setup_closed, never 409.
        import asyncio, httpx
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        app = create_app(tmp.name); self.addCleanup(close_app, app); code = setup_code(app)
        def client(address):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(address, 4242)), base_url='http://testserver')
        async def go(names):
            async with client('198.51.100.9') as a, client('198.51.100.10') as b:
                return await asyncio.gather(a.post('/api/setup', json={'code': code, 'username': names[0], 'password': PASSWORD}),
                                            b.post('/api/setup', json={'code': code, 'username': names[1], 'password': PASSWORD + ' two'}))
        first, second = asyncio.run(go(('first', 'second')))
        statuses = sorted((first.status_code, second.status_code))
        self.assertEqual(statuses, [200, 404], (first.text, second.text))
        refused = first if first.status_code == 404 else second
        self.assertEqual(refused.json()['detail']['code'], 'setup_closed')
        self.assertEqual(len(app.state.store.state['users']), 1, 'one setup code created more than one administrator')
        self.assertFalse((Path(tmp.name)/'setup-code').exists())
        entries = [json.loads(l) for l in (Path(tmp.name)/'audit.jsonl').read_text().splitlines()]
        self.assertEqual([e['event'] for e in entries if e['event'] == 'setup'], ['setup'])
        app.state.sessions.flush_failures(force=True)
        failures = Path(tmp.name)/'audit-failures.jsonl'
        # The lost race ran its hash with the right code: it is neither a name collision (`exists`) nor a failed setup,
        # and the vocabulary of DESIGN 10.2 has no word for it, so it leaves no failure entry; the one `setup ok` line
        # above is the record (second verification round: `setup_closed` was written, outside AUDIT_REASONS).
        self.assertFalse(failures.exists() and failures.read_text().strip(),
                         'the lost race of a double click is neither a name collision nor a failed setup')
        assert_not_logged(app, code, PASSWORD, PASSWORD + ' two')


class RecoveryRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = create_app(self.tmp.name); self.addCleanup(close_app, self.app)
        self.client = SignedInClient(self.app); self.addCleanup(self.client.close)
        self.anonymous = TestClient(self.app); self.addCleanup(self.anonymous.close)

    def recover(self):
        out = io.StringIO(); err = io.StringIO()
        self.assertEqual(recover.main(root=str(self.root), out=out, err=err), 0, err.getvalue())
        return out.getvalue().splitlines()[0].split(': ', 1)[1]

    def audit(self):
        return [json.loads(line) for line in (self.root/'audit.jsonl').read_text().splitlines()]

    def test_recovery_creates_one_new_admin_and_never_overwrites(self):
        self.assertEqual(self.anonymous.get('/setup', headers=HTML).status_code, 404)
        code = self.recover()
        served = self.anonymous.get('/setup', headers=HTML, follow_redirects=False)
        self.assertEqual(served.status_code, 200 if SETUP_HTML else 404)
        self.assertEqual(self.client.get('/setup', headers=HTML, follow_redirects=False).status_code, 302, 'a live session is sent home')
        before = dict(self.app.state.store.state['users'][NAME])
        taken = self.anonymous.post('/api/setup', json={'code': code, 'username': NAME, 'password': 'a different passphrase'})
        self.assertEqual((taken.status_code, taken.json()['detail']), (409, {'code': 'exists', 'message': 'That name already exists. Choose a new name for the recovery administrator.'}))
        self.assertEqual(self.app.state.store.state['users'][NAME], before); self.assertTrue((self.root/'setup-code').exists())
        self.assertEqual(self.client.get('/api/state').status_code, 200, 'the existing admin session is untouched')
        made = self.anonymous.post('/api/setup', json={'code': code, 'username': 'rescue', 'password': 'a different passphrase'})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()['user'], {'name': 'rescue', 'role': 'admin', 'must_change_password': False})
        self.assertEqual(self.app.state.store.state['users']['rescue']['created_by'], 'recover')
        self.assertEqual(self.app.state.store.state['users'][NAME], before)
        self.assertFalse((self.root/'setup-code').exists())
        self.assertEqual(self.anonymous.get('/api/users').status_code, 200)
        self.assertEqual([(e['event'], e['actor'], e['detail']) for e in self.audit() if e['event'] == 'recover.requested' or e['actor'] == 'rescue'], [('recover.requested', '-', ''), ('setup', 'rescue', 'recover')])
        self.app.state.sessions.flush_failures(force=True)
        self.assertEqual([(e['event'], e['actor'], e['detail']) for e in json.loads('[' + ','.join((self.root/'audit-failures.jsonl').read_text().splitlines()) + ']')], [('setup.failed', NAME, 'exists count=1')])
        assert_not_logged(self.app, code, 'a different passphrase', PASSWORD, self.anonymous.cookies.get('clab_session'))

    def test_a_sixteen_minute_old_recover_file_is_refused_and_deleted(self):
        code = self.recover()
        path = self.root/'setup-code'; old = time.time() - 16*60; os.utime(path, (old, old))
        response = self.anonymous.post('/api/setup', json={'code': code, 'username': 'rescue', 'password': 'a different passphrase'})
        self.assertEqual((response.status_code, response.json()['detail']['code']), (404, 'setup_closed'))
        self.assertFalse(path.exists())
        self.assertEqual([e['event'] for e in self.audit() if e['event'].startswith('recover.')], ['recover.requested', 'recover.expired'])
        self.assertEqual(self.anonymous.get('/setup', headers=HTML).status_code, 404)
        self.assertNotIn('rescue', self.app.state.store.state['users'])
