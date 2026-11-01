"""The account model (DESIGN.md 3; BUILD.md S1a).

Unit level: the record, public_user, known_sources, uniqueness, the last-admin and self-change rules
under store.lock, the user index refreshed inside the writing block after the save. The route-level
cases (every 4xx of the users routes with its message, the role change effective on the next
request) are S1b's part of this file.
"""
import json
import tempfile
import unittest
from unittest.mock import patch

from app import accounts
from app.accounts import Accounts, AccountError, new_record, public_user, remember_source, is_last_admin
from app.store import Store

HASH = accounts.hash_password('correct horse battery staple', {'n': 2**14, 'r': 8, 'p': 1})


class FakeSessions:
    """Records the index calls with the facts the design pins: under store.lock, after the save."""
    def __init__(self, store):
        self.store = store; self.calls = []; self.live = {}
    def saved_users(self):
        return json.loads(self.store.cipher.decrypt(self.store.path.read_bytes())).get('users', {})
    def _note(self, kind, *args, **kwargs):
        self.calls.append(dict(kind=kind, args=args, kwargs=kwargs, locked=self.store.lock._is_owned(), saved=self.saved_users()))
    def set_user(self, record): self._note('set_user', record['name'], dict(record))
    def drop_user(self, name): self._note('drop_user', name)
    def end_user(self, name, reason, keep=None): self._note('end_user', name, reason, keep=keep); return 2
    def rotate(self, session_id, password_changed): self._note('rotate', session_id, password_changed); return 'rotated-id'
    def count(self, name): return self.live.get(name, 0)


class AccountModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.sessions = FakeSessions(self.store)
        self.accounts = Accounts(self.store, self.sessions)

    def audit(self):
        path = self.store.root/'audit.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def admin(self, name='root', **kwargs):
        return self.accounts.create(name, 'admin', HASH, actor='setup', source='203.0.113.9', created_by='setup', must_change_password=False, **kwargs)

    def test_new_record_shape(self):
        record = new_record('jane', 'operator', HASH, created_by='root', must_change_password=True)
        self.assertEqual(set(record), {'name', 'role', 'password', 'disabled', 'must_change_password', 'created', 'created_by', 'password_changed', 'last_signin', 'known_sources'})
        self.assertEqual((record['name'], record['role'], record['password'], record['disabled'], record['must_change_password'], record['created_by']),
                         ('jane', 'operator', HASH, False, True, 'root'))
        self.assertIsNone(record['last_signin'])
        self.assertEqual(record['known_sources'], [])
        self.assertEqual(record['created'], record['password_changed'])
        self.assertRegex(record['created'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+\+00:00$')
        with self.assertRaises(ValueError): new_record('jane', 'owner', HASH, created_by='root', must_change_password=True)
        with self.assertRaises(ValueError): new_record('Jane', 'admin', HASH, created_by='root', must_change_password=True)

    def test_public_user_copies_the_allowlist_and_nothing_else(self):
        record = new_record('jane', 'operator', HASH, created_by='root', must_change_password=True, known_sources=['203.0.113.0/24'])
        record['extra'] = 'never copied'
        shown = public_user(record, sessions=3)
        self.assertEqual(set(shown), {'name', 'role', 'disabled', 'must_change_password', 'created', 'created_by', 'password_changed', 'last_signin', 'sessions'})
        self.assertEqual(shown['sessions'], 3)
        self.assertNotIn('scrypt$', json.dumps(shown))
        self.assertNotIn('203.0.113', json.dumps(shown))
        self.sessions.live['jane'] = 2
        self.assertEqual(self.accounts.public_user(record)['sessions'], 2, 'the Accounts object asks the sessions for the count')
        record['password'] = 'not a hash'
        self.assertIsNone(public_user(record)['password_changed'], 'a record whose string does not parse is shown with password_changed: null')

    def test_known_sources_keeps_eight_distinct_prefixes_newest_last(self):
        record = new_record('jane', 'operator', HASH, created_by='root', must_change_password=False)
        for index in range(8): remember_source(record, f'203.0.{index}.0/24')
        self.assertEqual(len(record['known_sources']), 8)
        remember_source(record, '203.0.0.0/24')
        self.assertEqual(record['known_sources'][-1], '203.0.0.0/24', 'a known prefix moves to the end')
        self.assertEqual(len(record['known_sources']), 8)
        for index in range(7): remember_source(record, '203.0.0.0/24')
        self.assertEqual(len(set(record['known_sources'])), 8, 'eight sign-ins from one classroom never push a home prefix out')
        remember_source(record, '2001:db8:1:2::/64')
        self.assertEqual(record['known_sources'][0], '203.0.2.0/24', 'the oldest distinct prefix leaves')
        self.assertEqual(record['known_sources'][-1], '2001:db8:1:2::/64')
        self.assertEqual(len(record['known_sources']), 8)
        self.assertEqual(accounts.KNOWN_SOURCES, 8)

    def test_create_refuses_an_existing_name_without_writing(self):
        self.admin()
        before = self.sessions.saved_users()
        with self.assertRaises(AccountError) as refused:
            self.accounts.create('root', 'operator', HASH, actor='root', source='203.0.113.9')
        self.assertEqual(refused.exception.status, 409)
        self.assertEqual(refused.exception.detail, {'code': 'exists', 'message': 'That name already exists.'})
        self.assertEqual(self.sessions.saved_users(), before)
        self.assertEqual(len(self.sessions.calls), 1)
        for bad in ('Root', 'a', 'jane doe'):
            with self.assertRaises(AccountError) as refused: self.accounts.create(bad, 'operator', HASH, actor='root')
            self.assertEqual((refused.exception.status, refused.exception.detail['code']), (422, 'invalid_name'))
        with self.assertRaises(ValueError): self.accounts.create('jane', 'owner', HASH, actor='root')

    def test_create_by_an_admin_sets_must_change_and_audits_inside_the_lock_after_the_save(self):
        self.admin()
        record = self.accounts.create('jane', 'operator', HASH, actor='root', source='203.0.113.9')
        self.assertEqual((record['created_by'], record['must_change_password'], record['known_sources']), ('root', True, []))
        self.assertIs(self.store.state['users']['jane'], record)
        call = self.sessions.calls[-1]
        self.assertEqual((call['kind'], call['args'][0]), ('set_user', 'jane'))
        self.assertTrue(call['locked'], 'the index is refreshed under store.lock')
        self.assertIn('jane', call['saved'], 'after the state save')
        entry = self.audit()[-1]
        self.assertEqual({k: entry[k] for k in ('event', 'actor', 'source', 'outcome', 'target', 'detail')},
                         {'event': 'user.created', 'actor': 'root', 'source': '203.0.113.9', 'outcome': 'ok', 'target': 'jane', 'detail': 'role=operator'})

    def test_a_failed_save_leaves_no_record_in_memory(self):
        self.admin()
        with patch.object(self.store, 'atomic', side_effect=OSError('disk fixture')):
            with self.assertRaises(OSError): self.accounts.create('jane', 'operator', HASH, actor='root')
        self.assertNotIn('jane', self.store.state['users'])
        self.assertNotIn('jane', self.sessions.saved_users())
        self.assertEqual([c['kind'] for c in self.sessions.calls], ['set_user'], 'no index call for a record the state did not take')
        self.assertEqual([e['event'] for e in self.audit()], ['user.created'])

    def test_last_admin_rule_under_the_lock(self):
        self.admin()
        self.accounts.create('jane', 'operator', HASH, actor='root')
        checks = []
        real = accounts.is_last_admin
        def recording(users, name):
            checks.append(self.store.lock._is_owned()); return real(users, name)
        with patch.object(accounts, 'is_last_admin', side_effect=recording):
            for call in (lambda: self.accounts.update('root', actor='jane', disabled=True),
                         lambda: self.accounts.update('root', actor='jane', role='operator'),
                         lambda: self.accounts.delete('root', actor='jane')):
                with self.assertRaises(AccountError) as refused: call()
                self.assertEqual(refused.exception.status, 409)
                self.assertEqual(refused.exception.detail, {'code': 'last_admin', 'message': 'The last administrator stays.'})
        self.assertEqual(checks, [True, True, True], 'the rule is checked under store.lock')
        self.assertEqual(self.store.state['users']['root']['role'], 'admin')
        self.assertFalse(self.store.state['users']['root']['disabled'])
        # A second enabled admin frees the first; a disabled one does not.
        self.accounts.create('second', 'admin', HASH, actor='root')
        self.accounts.update('second', actor='root', disabled=True)
        with self.assertRaises(AccountError): self.accounts.update('root', actor='second', disabled=True)
        self.accounts.update('second', actor='root', disabled=False)
        self.accounts.update('root', actor='second', role='operator')
        self.assertEqual(self.store.state['users']['root']['role'], 'operator')
        self.assertTrue(is_last_admin(self.store.state['users'], 'second'))
        self.assertFalse(is_last_admin(self.store.state['users'], 'root'))
        self.assertFalse(is_last_admin(self.store.state['users'], 'nobody'))

    def test_self_change_rules_with_their_sentences(self):
        self.admin(); self.accounts.create('second', 'admin', HASH, actor='root')
        cases = [
            (lambda: self.accounts.update('root', actor='root', disabled=True), 'You cannot deactivate your own account. Sign out instead.'),
            (lambda: self.accounts.update('root', actor='root', role='operator'), 'You cannot change your own role. Ask another administrator.'),
            (lambda: self.accounts.update('root', actor='root', role='admin'), 'You cannot change your own role. Ask another administrator.'),
            (lambda: self.accounts.delete('root', actor='root'), 'You cannot remove your own account. Ask another administrator.'),
            (lambda: self.accounts.reset_password('root', HASH, actor='root'), 'Use Manager ▾ › Change password… for your own account.'),
        ]
        for call, sentence in cases:
            with self.assertRaises(AccountError) as refused: call()
            self.assertEqual(refused.exception.status, 409)
            self.assertEqual(refused.exception.detail, {'code': 'self_change', 'message': sentence})
        self.assertEqual([e['event'] for e in self.audit()], ['user.created', 'user.created'], 'a refusal writes nothing')
        self.accounts.update('root', actor='root', disabled=False)   # enabling the own record is not a change of state

    def test_update_disables_enables_and_changes_the_role_with_audit_and_sessions(self):
        self.admin(); self.accounts.create('jane', 'operator', HASH, actor='root')
        self.sessions.calls.clear()
        record = self.accounts.update('jane', actor='root', source='203.0.113.9', disabled=True)
        self.assertTrue(record['disabled'])
        kinds = [(c['kind'], c['args']) for c in self.sessions.calls]
        self.assertEqual(kinds[0][0], 'set_user'); self.assertEqual(kinds[1], ('end_user', ('jane', 'user_disabled')))
        self.assertTrue(all(c['locked'] and c['saved']['jane']['disabled'] for c in self.sessions.calls))
        self.accounts.update('jane', actor='root', disabled=False)
        self.accounts.update('jane', actor='root', role='admin')
        self.accounts.update('jane', actor='root', role='operator', disabled=True)
        events = [(e['event'], e['target'], e['detail']) for e in self.audit()[2:]]
        self.assertEqual(events, [('user.disabled', 'jane', ''), ('user.enabled', 'jane', ''), ('user.role', 'jane', 'role=admin'),
                                  ('user.role', 'jane', 'role=operator'), ('user.disabled', 'jane', '')])
        self.assertEqual([c['args'] for c in self.sessions.calls if c['kind'] == 'end_user'], [('jane', 'user_disabled'), ('jane', 'user_disabled')],
                         'sessions end when the flag is set, not when the role changes')
        with self.assertRaises(AccountError) as missing: self.accounts.update('nobody', actor='root', disabled=True)
        self.assertEqual((missing.exception.status, missing.exception.detail), (404, {'code': 'user_not_found', 'message': 'No account has that name.'}))
        with self.assertRaises(ValueError): self.accounts.update('jane', actor='root', role='owner')

    def test_delete_drops_the_index_entry_and_ends_sessions(self):
        self.admin(); self.accounts.create('jane', 'operator', HASH, actor='root')
        self.sessions.calls.clear()
        self.accounts.delete('jane', actor='root', source='203.0.113.9')
        self.assertNotIn('jane', self.store.state['users'])
        self.assertEqual([(c['kind'], c['args']) for c in self.sessions.calls], [('drop_user', ('jane',)), ('end_user', ('jane', 'user_deleted'))])
        self.assertTrue(all(c['locked'] and 'jane' not in c['saved'] for c in self.sessions.calls))
        self.assertEqual(self.audit()[-1]['event'], 'user.deleted')
        with self.assertRaises(AccountError) as missing: self.accounts.delete('jane', actor='root')
        self.assertEqual(missing.exception.status, 404)

    def test_admin_reset_sets_must_change_moves_the_stamp_and_ends_every_session(self):
        self.admin(); record = self.accounts.create('jane', 'operator', HASH, actor='root')
        before = record['password_changed']
        new_hash = accounts.hash_password('another long passphrase', {'n': 2**14, 'r': 8, 'p': 1})
        self.sessions.calls.clear()
        with patch('app.accounts.now', return_value='2030-01-01T00:00:00.000000+00:00'):
            shown = self.accounts.reset_password('jane', new_hash, actor='root', source='203.0.113.9')
        self.assertEqual(record['password'], new_hash)
        self.assertTrue(record['must_change_password'])
        self.assertNotEqual(record['password_changed'], before)
        self.assertEqual(record['password_changed'], '2030-01-01T00:00:00.000000+00:00')
        self.assertIs(shown, record)
        self.assertEqual([(c['kind'], c['args']) for c in self.sessions.calls], [('set_user', ('jane', dict(record))), ('end_user', ('jane', 'password_reset'))])
        self.assertEqual(self.audit()[-1]['event'], 'user.password_reset')
        with self.assertRaises(AccountError): self.accounts.reset_password('nobody', new_hash, actor='root')

    def test_own_change_rotates_before_set_user_and_keeps_the_new_id(self):
        self.admin()
        record = self.store.state['users']['root']; record['must_change_password'] = True
        new_hash = accounts.hash_password('another long passphrase', {'n': 2**14, 'r': 8, 'p': 1})
        self.sessions.calls.clear()
        new_id = self.accounts.change_password('root', new_hash, session_id='old-id', source='203.0.113.9')
        self.assertEqual(new_id, 'rotated-id')
        self.assertFalse(record['must_change_password'])
        self.assertEqual(record['password'], new_hash)
        self.assertEqual([(c['kind'], c['args'], c['kwargs']) for c in self.sessions.calls],
                         [('rotate', ('old-id', record['password_changed']), {}), ('set_user', ('root', dict(record)), {}),
                          ('end_user', ('root', 'password_changed'), {'keep': 'rotated-id'})])
        self.assertTrue(all(c['locked'] and c['saved']['root']['password'] == new_hash for c in self.sessions.calls))
        entry = self.audit()[-1]
        self.assertEqual((entry['event'], entry['actor'], entry['outcome']), ('password.changed', 'root', 'ok'))

    def test_record_signin_updates_last_signin_and_known_sources_in_one_save(self):
        record = self.admin()
        self.assertIsNone(record['last_signin'])
        saves = []
        real = self.store.save
        with patch.object(self.store, 'save', side_effect=lambda: (saves.append(1), real())):
            self.accounts.record_signin('root', '203.0.113.0/24', '203.0.113.9')
        self.assertEqual(len(saves), 1)
        self.assertIsNotNone(record['last_signin'])
        self.assertEqual(record['known_sources'], ['203.0.113.0/24'])
        saved = self.sessions.saved_users()['root']
        self.assertEqual(saved['known_sources'], ['203.0.113.0/24'])
        entry = self.audit()[-1]
        self.assertEqual((entry['event'], entry['actor'], entry['source'], entry['outcome']), ('signin', 'root', '203.0.113.9', 'ok'))

    def test_failure_actor_is_the_name_only_for_an_existing_record(self):
        self.admin()
        self.assertEqual(accounts.failure_actor(self.store.state['users'], 'root'), 'root')
        self.assertEqual(accounts.failure_actor(self.store.state['users'], 'correct horse battery staple'), '-')
        self.assertEqual(accounts.failure_actor(self.store.state['users'], 'Root'), '-', 'compared exactly')
        self.assertEqual(accounts.failure_actor({}, ''), '-')

    def test_no_record_is_ever_overwritten(self):
        record = self.admin()
        with self.assertRaises(AccountError): self.accounts.create('root', 'admin', 'scrypt$other', actor='setup')
        with self.assertRaises(AccountError): self.accounts.complete_setup('root', 'scrypt$other', mode='recover', source='203.0.113.9', prefix='203.0.113.0/24')
        self.assertIs(self.store.state['users']['root'], record)
        self.assertEqual(record['password'], HASH)

    def test_users_are_read_lazily_from_an_old_state(self):
        with self.store.lock:
            self.store.state.pop('users', None); self.store.save()
        self.assertEqual(self.accounts.users(), {})
        self.assertIsNone(self.accounts.record('root'))


if __name__ == '__main__':
    unittest.main()


# ---- route level (BUILD.md S1b): the users routes through the real app ----
from app.main import create_app
from session_fixture import SignedInClient, PASSWORD, NAME, sign_in, sign_out, assert_not_logged


def close_app(app):
    for name in ('design_apply', 'network_design', 'telemetry_retirement', 'restore', 'git_progress', 'operations', 'discovery',
                 'readiness', 'node_services', 'runner'):
        getattr(app.state, name).close()


class UsersRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name); self.addCleanup(close_app, self.app)
        self.client = SignedInClient(self.app); self.addCleanup(self.client.close)

    def create(self, name, role='operator', password='a password nobody guesses', expect=200):
        response = self.client.post('/api/users', json={'name': name, 'role': role, 'password': password})
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def test_public_user_fields_and_nothing_more(self):
        user = self.create('olivia')['user']
        self.assertEqual(set(user), {'name', 'role', 'disabled', 'must_change_password', 'created', 'created_by', 'password_changed', 'last_signin', 'sessions'})
        self.assertEqual((user['name'], user['role'], user['disabled'], user['must_change_password'], user['created_by'], user['last_signin'], user['sessions']), ('olivia', 'operator', False, True, NAME, None, 0))
        listed = self.client.get('/api/users')
        self.assertEqual([u['name'] for u in listed.json()['users']], ['olivia', NAME])
        mine = next(u for u in listed.json()['users'] if u['name'] == NAME)
        self.assertEqual((mine['sessions'], mine['created_by']), (1, 'setup')); self.assertIsNotNone(mine['last_signin'])
        for secret in ('"password"', 'known_sources', 'scrypt$'): self.assertNotIn(secret, listed.text)

    def test_every_4xx_of_the_users_routes_carries_its_sentence(self):
        self.create('olivia')
        cases = [
            ('POST', '/api/users', {'name': 'olivia', 'role': 'operator', 'password': 'a password nobody guesses'}, 409, 'exists', 'That name already exists.'),
            ('POST', '/api/users', {'name': 'Olivia!', 'role': 'operator', 'password': 'a password nobody guesses'}, 422, 'invalid_name', 'Use lowercase letters, digits, dot, dash or underscore, 2 to 32 characters.'),
            ('POST', '/api/users', {'name': 'kim', 'role': 'operator', 'password': 'kim'}, 422, 'weak_password', 'Use at least 12 characters. Choose a password that is not your username.'),
            ('POST', '/api/users', {'name': 'kim', 'role': 'operator', 'password': 'password'}, 422, 'weak_password', 'Use at least 12 characters. That password is too common. Choose another.'),
            ('PATCH', '/api/users/nobody', {'disabled': True}, 404, 'user_not_found', 'No account has that name.'),
            ('DELETE', '/api/users/nobody', {}, 404, 'user_not_found', 'No account has that name.'),
            ('POST', '/api/users/nobody/password', {'password': 'a password nobody guesses'}, 404, 'user_not_found', 'No account has that name.'),
            ('PATCH', f'/api/users/{NAME}', {'disabled': True}, 409, 'self_change', 'You cannot deactivate your own account. Sign out instead.'),
            ('PATCH', f'/api/users/{NAME}', {'role': 'operator'}, 409, 'self_change', 'You cannot change your own role. Ask another administrator.'),
            ('DELETE', f'/api/users/{NAME}', {}, 409, 'self_change', 'You cannot remove your own account. Ask another administrator.'),
            ('POST', f'/api/users/{NAME}/password', {'password': 'a password nobody guesses'}, 409, 'self_change', 'Use Manager ▾ › Change password… for your own account.'),
            ('POST', '/api/users/olivia/password', {'password': 'olivia'}, 422, 'weak_password', 'Use at least 12 characters. Choose a password that is not your username.'),
        ]
        for method, path, body, status, code, message in cases:
            response = self.client.request(method, path, json=body)
            self.assertEqual(response.status_code, status, (method, path, response.text))
            self.assertEqual((response.json()['detail']['code'], response.json()['detail']['message']), (code, message), (method, path))
        for method, path, body in (('POST', '/api/users', {'name': 'kim', 'role': 'owner', 'password': 'a password nobody guesses'}),
                                   ('PATCH', '/api/users/olivia', {'role': 'owner'}),
                                   ('POST', '/api/users', {'name': 'kim', 'role': 'operator', 'password': 'a password nobody guesses', 'disabled': True}),
                                   ('PATCH', '/api/users/olivia', {'name': 'renamed'}), ('DELETE', '/api/users/olivia', {'force': True})):
            self.assertEqual(self.client.request(method, path, json=body).status_code, 422, (method, path, "extra='forbid' and the role values"))
        self.assertEqual(self.client.request('DELETE', '/api/users/olivia').status_code, 413, 'a mutating request needs a body')
        self.assertIn('olivia', self.app.state.store.state['users'])

    def test_the_last_admin_stays_through_the_route(self):
        self.create('second', role='admin', password='another administrator one')
        second = SignedInClient(self.app, name='second', password='another administrator one'); self.addCleanup(second.close)
        changed = second.post('/api/session/password', json={'current': 'another administrator one', 'password': 'another administrator two'})
        self.assertEqual(changed.status_code, 200, changed.text)
        # Two admins: each may demote the other only while the other is not the last one. `second` demotes tester;
        # now `second` is the last admin and tester, an operator, is refused everything admin-only.
        self.assertEqual(second.patch(f'/api/users/{NAME}', json={'role': 'operator'}).status_code, 200)
        self.assertEqual(self.client.get('/api/users').status_code, 403, 'the role change takes effect on the next request')
        self.assertEqual(self.client.get('/api/state').json()['user']['role'], 'operator')
        # A direct model call with a third-party actor shows the rule itself; through HTTP no enabled admin remains to be the actor.
        with self.assertRaises(AccountError) as ctx: self.app.state.accounts.update('second', actor='someone-else', disabled=True)
        self.assertEqual((ctx.exception.status, ctx.exception.detail), (409, {'code': 'last_admin', 'message': 'The last administrator stays.'}))
        with self.assertRaises(AccountError) as ctx: self.app.state.accounts.delete('second', actor='someone-else')
        self.assertEqual(ctx.exception.code, 'last_admin')
        self.assertEqual(second.patch(f'/api/users/{NAME}', json={'role': 'admin'}).status_code, 200)
        self.assertEqual(self.client.get('/api/users').status_code, 200)
        self.assertEqual(second.patch(f'/api/users/{NAME}', json={'disabled': True}).json()['user']['disabled'], True)
        self.assertEqual(self.client.get('/api/state').status_code, 401, 'disabled: every session ended')
        self.assertEqual(second.request('DELETE', f'/api/users/{NAME}', json={}).json(), {'deleted': True})
        self.assertNotIn(NAME, self.app.state.store.state['users'])
        assert_not_logged(self.app, PASSWORD, 'another administrator one', 'another administrator two', second.cookies.get('clab_session'))

    def test_an_admin_reset_restricts_the_user_and_an_operator_is_refused_everything_here(self):
        self.create('olivia')
        operator = SignedInClient(self.app, role='operator', name='olivia', password='a password nobody guesses'); self.addCleanup(operator.close)
        for method, path, body in (('GET', '/api/users', None), ('POST', '/api/users', {'name': 'x1', 'role': 'operator', 'password': 'a password nobody guesses'}),
                                   ('PATCH', '/api/users/olivia', {'disabled': False}), ('DELETE', '/api/users/olivia', {}), ('POST', '/api/users/olivia/password', {'password': 'a password nobody guesses'}), ('GET', '/api/audit', None)):
            response = operator.request(method, path, json=body)
            self.assertEqual((response.status_code, response.json()['detail']), (403, {'code': 'admin_required', 'message': 'Administrators only.'}), (method, path))
        reset = self.client.post('/api/users/olivia/password', json={'password': 'the admin set this one'})
        self.assertEqual((reset.status_code, reset.json()['user']['must_change_password'], reset.json()['user']['sessions']), (200, True, 0))
        self.assertEqual(operator.get('/api/state').status_code, 401)
        self.assertEqual(sign_in(operator, 'olivia', 'the admin set this one')['user']['must_change_password'], True)
        self.assertEqual(operator.get('/api/state').status_code, 403)
        self.assertEqual([(e['event'], e['target']) for e in self.app.state.store.audit_entries(50, 0, event='user.password_reset')[0]], [('user.password_reset', 'olivia')])
