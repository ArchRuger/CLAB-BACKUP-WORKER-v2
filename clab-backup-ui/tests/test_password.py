"""Password hashing and policy (DESIGN.md 4; BUILD.md S1a).

Unit level: the hash string and its parser, verify, rehash, DUMMY_HASH, the policy and its sentences,
maxmem on every call, the executor and the busy bound. The route-level cases (one scrypt per sign-in
through POST /api/session, the 429 of the 21st queued verify) are S1b's part of this file.
"""
import asyncio
import hashlib
import hmac
import threading
import time
import unicodedata
import unittest
from pathlib import Path
from unittest.mock import patch

from app import accounts
from app.accounts import (PARAMS, DUMMY_HASH, MAXMEM, SCRYPT_EXECUTOR, VERIFY_LIMIT, COMMON_PASSWORDS,
                          hash_password, verify_password, parse_hash, needs_rehash, check_name, check_password,
                          message_for, REASON_SENTENCES, Busy)

FAST = {'n': 2**14, 'r': 8, 'p': 1}   # the smallest n the parser accepts: a quick hash for the cases that need many


def no_secret_in(text, *secrets):
    for secret in secrets:
        if secret and secret in text: raise AssertionError('a secret reached a log or an output')


class HashStringTests(unittest.TestCase):
    def test_hash_string_has_six_parts_with_the_shipped_parameters(self):
        text = hash_password('correct horse battery staple')
        parts = text.split('$')
        self.assertEqual(len(parts), 6)
        self.assertEqual(parts[0], 'scrypt')
        self.assertEqual([int(parts[1]), int(parts[2]), int(parts[3])], [PARAMS['n'], PARAMS['r'], PARAMS['p']])
        self.assertEqual(PARAMS, {'n': 2**15, 'r': 8, 'p': 1})
        for part in parts[4:]:
            self.assertNotIn('=', part, 'URL-safe base64 without padding')
            self.assertRegex(part, r'^[A-Za-z0-9_-]+$')
        parsed = parse_hash(text)
        self.assertEqual(len(parsed['salt']), 32)
        self.assertEqual(len(parsed['hash']), 32)

    def test_round_trip_and_wrong_password(self):
        text = hash_password('correct horse battery staple', FAST)
        self.assertTrue(verify_password(text, 'correct horse battery staple'))
        self.assertFalse(verify_password(text, 'correct horse battery stapl'))
        self.assertFalse(verify_password(text, ''))
        self.assertNotEqual(hash_password('correct horse battery staple', FAST), text, 'a fresh salt every time')

    def test_every_malformed_case_of_design_4_2_fails_to_parse(self):
        good = hash_password('correct horse battery staple', FAST)
        n, r, p, salt, digest = good.split('$')[1:]
        def build(n=n, r=r, p=p, salt=salt, digest=digest, algo='scrypt'):
            return '$'.join([algo, n, r, p, salt, digest])
        cases = {
            'empty': '', 'none': None, 'not a string': 42,
            'five parts': good.rsplit('$', 1)[0], 'seven parts': good + '$x',
            'other algorithm': build(algo='argon2'), 'upper-case algorithm': build(algo='SCRYPT'),
            'n not a power of two': build(n='24576'), 'n too small': build(n=str(2**13)), 'n too large': build(n=str(2**21)),
            'n negative': build(n='-16384'), 'n with sign': build(n='+16384'), 'n with space': build(n=' 16384'),
            'n with leading zero': build(n='016384'), 'n not decimal': build(n='0x4000'), 'n empty': build(n=''),
            'r zero': build(r='0'), 'r too large': build(r='33'), 'p zero': build(p='0'), 'p too large': build(p='17'),
            'salt too short': build(salt=accounts._b64(b'x'*15)), 'salt too long': build(salt=accounts._b64(b'x'*65)),
            'salt with padding': build(salt=salt+'=='), 'salt not base64': build(salt=salt[:-1]+'$'),
            'salt standard alphabet': build(salt=salt[:-2]+'+/'), 'salt non-canonical': build(salt=salt[:-1]+('B' if salt[-1]!='B' else 'C')),
            'hash too short': build(digest=accounts._b64(b'y'*31)), 'hash too long': build(digest=accounts._b64(b'y'*33)),
            'hash empty': build(digest=''), 'salt empty': build(salt=''),
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.assertIsNone(parse_hash(text), label)
        self.assertIsNotNone(parse_hash(good))
        self.assertIsNotNone(parse_hash(build(salt=accounts._b64(b'x'*16))), 'a 16-byte salt is the lower bound')
        self.assertIsNotNone(parse_hash(build(salt=accounts._b64(b'x'*64))), 'a 64-byte salt is the upper bound')

    def test_parameters_that_exceed_maxmem_are_a_malformed_string_and_never_a_crash(self):
        # hashlib.scrypt needs 128*r*(n+p+2) bytes and raises ValueError above maxmem; a string inside the ranges of
        # 4.2 but above that bound would otherwise pass the parser and crash the verify: a 500 that no level counts.
        good = hash_password('correct horse battery staple', FAST)
        _, _, _, salt, digest = good.split('$')[1:]
        def build(n, r, p):
            return '$'.join(['scrypt', str(n), str(r), str(p), salt, digest])
        for n, r, p in ((2**16, 8, 1), (2**14, 32, 1), (2**20, 1, 1), (2**19, 1, 1), (2**15, 16, 1)):
            with self.subTest((n, r, p)):
                self.assertGreater(128*r*(n+p+2), MAXMEM)
                self.assertIsNone(parse_hash(build(n, r, p)))
        for n, r, p in ((2**15, 8, 1), (2**16, 4, 1), (2**14, 31, 1), (2**15, 8, 16)):
            with self.subTest((n, r, p)):
                self.assertLessEqual(128*r*(n+p+2), MAXMEM)
                self.assertIsNotNone(parse_hash(build(n, r, p)))
        self.assertLessEqual(128*PARAMS['r']*(PARAMS['n']+PARAMS['p']+2), MAXMEM, 'the shipped parameters fit')
        with patch('app.accounts.hashlib.scrypt', wraps=hashlib.scrypt) as scrypt:
            self.assertFalse(verify_password(build(2**16, 8, 1), 'correct horse battery staple'))
            self.assertEqual(scrypt.call_count, 1, 'the dummy is verified instead')
            self.assertEqual(scrypt.call_args.kwargs['n'], PARAMS['n'])
        self.assertFalse(needs_rehash(build(2**16, 8, 1)))

    def test_n_must_stay_under_two_to_the_sixteen_r_and_every_accepted_string_verifies(self):
        # OpenSSL also refuses N >= 2**(16 r) (hashlib raises ValueError) below the memory bound: with r=1 every n from
        # 2**16 up is inside the ranges of 4.2 and under MAXMEM, so the parser must refuse it too, or a stored string
        # would turn a sign-in into a 500 that no level counts (second verification round).
        good = hash_password('correct horse battery staple', FAST)
        _, _, _, salt, digest = good.split('$')[1:]
        def build(n, r, p):
            return '$'.join(['scrypt', str(n), str(r), str(p), salt, digest])
        for n, r, p in ((2**16, 1, 1), (2**17, 1, 1), (2**18, 1, 1), (2**18, 1, 16)):
            with self.subTest((n, r, p)):
                self.assertLessEqual(128*r*(n+p+2), MAXMEM, 'inside the memory bound: only the 16 r rule refuses it')
                with self.assertRaises(ValueError): hashlib.scrypt(b'x', salt=b'y'*16, n=n, r=r, p=p, dklen=32, maxmem=MAXMEM)
                self.assertIsNone(parse_hash(build(n, r, p)))
        accepted = ((2**14, 1, 1), (2**15, 1, 1), (2**15, 1, 16), (2**16, 2, 1), (2**17, 2, 1), (2**14, 8, 16), (2**16, 4, 1), (2**14, 31, 1))
        for n, r, p in accepted:
            with self.subTest((n, r, p)):
                self.assertIsNotNone(parse_hash(build(n, r, p)))
                # Every string the parser accepts is one hashlib verifies: a wrong password answers False, never a raise.
                self.assertFalse(verify_password(build(n, r, p), 'not the password'))

    def test_a_verify_that_hashlib_refuses_anyway_answers_false_after_the_dummy_and_never_raises(self):
        # The parser is the rule; should a build of OpenSSL refuse more, the verify still answers like a bad record.
        good = hash_password('correct horse battery staple', FAST)
        real = hashlib.scrypt; calls = []
        def refusing(*args, **kwargs):
            calls.append(kwargs['n'])
            if len(calls) == 1: raise ValueError('[digital envelope routines] memory limit exceeded')
            return real(*args, **kwargs)
        with patch('app.accounts.hashlib.scrypt', refusing):
            self.assertFalse(verify_password(good, 'correct horse battery staple'))
        self.assertEqual(calls, [FAST['n'], PARAMS['n']], 'the refused call did no work; the dummy is verified instead')

    def test_a_record_that_does_not_parse_never_verifies_but_still_costs_one_scrypt(self):
        for bad in (None, '', 'scrypt$x', 'plain-text-password', 'scrypt$16384$8$1$$'):
            with patch('app.accounts.hashlib.scrypt', wraps=hashlib.scrypt) as scrypt:
                self.assertFalse(verify_password(bad, 'correct horse battery staple'))
                self.assertEqual(scrypt.call_count, 1, 'DUMMY_HASH is verified instead')
                self.assertEqual(scrypt.call_args.kwargs['n'], PARAMS['n'])

    def test_dummy_hash_parses_with_the_shipped_parameters_and_never_verifies_the_empty_password(self):
        parsed = parse_hash(DUMMY_HASH)
        self.assertIsNotNone(parsed)
        self.assertEqual((parsed['n'], parsed['r'], parsed['p']), (PARAMS['n'], PARAMS['r'], PARAMS['p']))
        self.assertFalse(verify_password(DUMMY_HASH, ''))

    def test_verify_uses_compare_digest(self):
        text = hash_password('correct horse battery staple', FAST)
        with patch('app.accounts.hmac.compare_digest', wraps=hmac.compare_digest) as compare:
            self.assertTrue(verify_password(text, 'correct horse battery staple'))
            self.assertEqual(compare.call_count, 1)
            a, b = compare.call_args.args
            self.assertEqual(len(a), 32); self.assertEqual(len(b), 32)
        with patch('app.accounts.hmac.compare_digest', return_value=False):
            self.assertFalse(verify_password(text, 'correct horse battery staple'), 'the decision is compare_digest\'s')

    def test_maxmem_is_passed_on_every_call_and_one_verify_takes_under_500_ms(self):
        with patch('app.accounts.hashlib.scrypt', wraps=hashlib.scrypt) as scrypt:
            text = hash_password('correct horse battery staple')
            verify_password(text, 'correct horse battery staple')
            verify_password(None, 'correct horse battery staple')
            self.assertEqual(scrypt.call_count, 3)
            for call in scrypt.call_args_list:
                self.assertEqual(call.kwargs['maxmem'], 64*1024*1024)
                self.assertEqual(call.kwargs['dklen'], 32)
        self.assertEqual(MAXMEM, 64*1024*1024)
        # The default maxmem refuses the shipped parameters (DESIGN 4.1): without the keyword the call would raise.
        with self.assertRaises(ValueError):
            hashlib.scrypt(b'x', salt=b'y'*32, n=PARAMS['n'], r=PARAMS['r'], p=PARAMS['p'], dklen=32)
        started = time.perf_counter()
        self.assertTrue(verify_password(text, 'correct horse battery staple'))
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 0.5, f'one verify with the shipped parameters took {elapsed:.3f}s')

    def test_passwords_are_nfkc_normalised_before_hashing_so_both_spellings_verify(self):
        composed = 'café au lait, s\'il vous plaît'
        decomposed = unicodedata.normalize('NFD', composed)
        self.assertNotEqual(composed, decomposed)
        text = hash_password(composed, FAST)
        self.assertTrue(verify_password(text, decomposed))

    def test_the_hash_string_never_contains_the_password(self):
        text = hash_password('correct horse battery staple', FAST)
        no_secret_in(text, 'correct horse battery staple', 'correct')


class RehashTests(unittest.TestCase):
    def test_needs_rehash_when_parameters_differ_and_not_otherwise(self):
        self.assertTrue(needs_rehash(hash_password('correct horse battery staple', FAST)))
        self.assertFalse(needs_rehash(hash_password('correct horse battery staple')))
        self.assertFalse(needs_rehash('not a hash'), 'a record that does not parse cannot sign in, so it is never rehashed')
        self.assertFalse(needs_rehash(None))

    def test_rehash_writes_the_shipped_parameters_without_moving_password_changed(self):
        import tempfile
        from app.store import Store
        from app.accounts import Accounts
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            service = Accounts(store)
            old = hash_password('correct horse battery staple', FAST)
            record = accounts.new_record('tester', 'admin', old, created_by='setup', must_change_password=False)
            stamp = record['password_changed']
            with store.lock:
                store.state['users'] = {'tester': record}
                store.save()
            with patch.object(accounts, 'PARAMS', FAST):
                self.assertFalse(service.rehash('tester', 'correct horse battery staple'), 'nothing to do when the parameters match')
            self.assertTrue(service.rehash('tester', 'correct horse battery staple'))
            saved = Store(tmp).state['users']['tester']
            self.assertNotEqual(saved['password'], old)
            self.assertFalse(needs_rehash(saved['password']))
            self.assertTrue(verify_password(saved['password'], 'correct horse battery staple'))
            self.assertEqual(saved['password_changed'], stamp, 'the password did not change; sessions stay valid')
            self.assertFalse(service.rehash('nobody', 'correct horse battery staple'))


class PolicyTests(unittest.TestCase):
    def test_name_rule(self):
        for good in ('ab', 'a1', 'student.01', 'jane_doe', 'x-y', 'a'*32, '0zero'):
            self.assertTrue(check_name(good), good)
        for bad in ('a', '', 'A1', 'Jane', '-ab', '.ab', '_ab', 'a'*33, 'jane doe', 'jane@x', 'üser', 'ab\n', None, 12):
            self.assertFalse(check_name(bad), repr(bad))

    def test_every_reason_code_with_its_sentence(self):
        self.assertEqual(check_password('tester', 'correct horse battery staple'), [])
        self.assertEqual(check_password('tester', 'short'), ['too_short'])
        self.assertEqual(check_password('tester', 'x'*129), ['too_long'])
        self.assertEqual(check_password('tester', 'x'*128), [])
        self.assertEqual(check_password('tester', 'x'*12), [])
        self.assertEqual(check_password('tester', 'x'*11), ['too_short'])
        self.assertEqual(check_password('tester', 'Tester-and-more-chars'), ['equals_name'], 'the name inside the password, case-insensitively')
        self.assertEqual(check_password('tester', 'TESTER'), ['too_short', 'equals_name'])
        self.assertEqual(check_password('tester', 'qwertyuiop'), ['too_short', 'common'])
        self.assertEqual(check_password('tester', 'minecraft'), ['too_short', 'common'])
        self.assertEqual(check_password('tester', 'MINECRAFT'), ['too_short', 'common'], 'the deny-list is case-insensitive')
        self.assertEqual(check_password('tester', '1234567890'), ['too_short', 'common'])
        self.assertEqual(check_password('ab', 'a reasonably long phrase'), ['equals_name'], 'a two-letter name inside the password')
        self.assertEqual(check_password('', 'a reasonably long phrase'), [], 'no name, no name rule')
        self.assertEqual(REASON_SENTENCES, {
            'too_short': 'Use at least 12 characters.',
            'too_long': 'Use at most 128 characters.',
            'equals_name': 'Choose a password that is not your username.',
            'common': 'That password is too common. Choose another.',
        })
        self.assertEqual(message_for(['common', 'too_short']), 'Use at least 12 characters. That password is too common. Choose another.',
                         'joined by one space in the order of DESIGN 7.4')
        self.assertEqual(message_for(['too_long']), 'Use at most 128 characters.')

    def test_weak_password_detail_joins_the_sentences(self):
        detail = accounts.detail(422, 'weak_password', reasons=['too_short', 'equals_name'])
        self.assertEqual(detail, {'code': 'weak_password', 'reasons': ['too_short', 'equals_name'],
                                  'message': 'Use at least 12 characters. Choose a password that is not your username.'})

    def test_deny_list_is_the_published_top_100_frozen(self):
        self.assertIsInstance(COMMON_PASSWORDS, frozenset)
        self.assertGreaterEqual(len(COMMON_PASSWORDS), 100)
        self.assertLessEqual(len(COMMON_PASSWORDS), 101)
        for word in ('123456', 'password', 'qwerty', 'letmein', 'trustno1', 'iloveyou', '1qaz2wsx', 'matrix'):
            self.assertIn(word, COMMON_PASSWORDS)
        self.assertTrue(all(word == word.lower() for word in COMMON_PASSWORDS), 'stored lowercase, compared casefolded')
        import inspect
        source = inspect.getsource(accounts)
        self.assertIn('SecLists', source, 'the list names its source')
        self.assertRegex(source, r'10-million-password-list-top-100', 'and the file it was copied from')

    def test_length_counts_unicode_code_points_after_nfkc(self):
        self.assertEqual(check_password('tester', 'ｆｕｌｌｗｉｄｔｈ１２３'), [], 'twelve full-width characters fold to twelve code points')
        self.assertEqual(check_password('tester', 'ｆｕｌｌｗｉｄｔｈ１２'), ['too_short'], 'eleven do not')
        self.assertEqual(check_password('tester', 'ﬁ' * 6), [], 'six ligatures fold to twelve letters')
        self.assertEqual(check_password('tester', 'é' * 11), ['too_short'])
        self.assertEqual(check_password('tester', '            '), [], 'whitespace is kept, not stripped: twelve spaces pass the length rule')
        self.assertEqual(check_password('tester', '  padded phrase  '), [])

    def test_every_message_of_design_7_4_is_present(self):
        expect = {
            (401, 'signed_out', ''): 'Your session ended. Sign in again.',
            (401, 'invalid_credentials', 'POST /api/session'): 'Wrong username or password.',
            (401, 'invalid_credentials', 'POST /api/session/password'): 'The current password is not right.',
            (401, 'invalid_code', 'POST /api/setup'): 'That setup code is not right. On the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code',
            (403, 'admin_required', ''): 'Administrators only.',
            (403, 'password_change_required', ''): 'Choose your own password before you continue.',
            (404, 'setup_closed', 'POST /api/setup'): 'Setup is closed. Sign in, or ask the VM administrator to run the recovery command.',
            (404, 'user_not_found', ''): 'No account has that name.',
            (409, 'exists', 'POST /api/users'): 'That name already exists.',
            (409, 'exists', 'POST /api/setup'): 'That name already exists. Choose a new name for the recovery administrator.',
            (409, 'last_admin', ''): 'The last administrator stays.',
            (409, 'self_change', 'PATCH /api/users/{name} disabled'): 'You cannot deactivate your own account. Sign out instead.',
            (409, 'self_change', 'PATCH /api/users/{name} role'): 'You cannot change your own role. Ask another administrator.',
            (409, 'self_change', 'DELETE /api/users/{name}'): 'You cannot remove your own account. Ask another administrator.',
            (409, 'self_change', 'POST /api/users/{name}/password'): 'Use Manager ▾ › Change password… for your own account.',
            (422, 'invalid_name', ''): 'Use lowercase letters, digits, dot, dash or underscore, 2 to 32 characters.',
            (429, 'throttled', ''): 'Too many sign-in attempts. Try again in {n} s.',
            (503, 'setup_required', ''): 'This manager is not set up yet. Open /setup to create the first administrator.',
        }
        self.assertEqual(accounts.MESSAGES, expect)
        self.assertEqual(accounts.message(401, 'invalid_credentials', 'POST /api/session'), 'Wrong username or password.')
        self.assertEqual(accounts.message(409, 'last_admin', 'DELETE /api/users/{name}'), 'The last administrator stays.', 'a route falls back to the generic sentence')
        self.assertEqual(accounts.detail(429, 'throttled', retry_after=30), {'code': 'throttled', 'retry_after': 30, 'message': 'Too many sign-in attempts. Try again in 30 s.'})
        self.assertEqual(accounts.detail(429, 'throttled', retry_after=2)['message'], 'Too many sign-in attempts. Try again in 2 s.')
        with self.assertRaises(KeyError): accounts.message(418, 'teapot')
        error = accounts.AccountError(409, 'self_change', 'DELETE /api/users/{name}')
        self.assertEqual((error.status, error.detail), (409, {'code': 'self_change', 'message': 'You cannot remove your own account. Ask another administrator.'}))


class ExecutorTests(unittest.TestCase):
    def test_every_scrypt_call_of_the_awaitables_runs_on_a_scrypt_executor_thread(self):
        threads = []
        real = hashlib.scrypt
        def recording(*args, **kwargs):
            threads.append(threading.current_thread().name)
            return real(*args, **kwargs)
        async def run():
            text = await accounts.ahash('correct horse battery staple')
            self.assertTrue(await accounts.averify(text, 'correct horse battery staple'))
            self.assertFalse(await accounts.averify(text, 'wrong password here'))
            self.assertFalse(await accounts.averify(None, 'wrong password here'))
        with patch.object(accounts, 'PARAMS', FAST), patch('app.accounts.hashlib.scrypt', side_effect=recording):
            asyncio.run(run())
        self.assertEqual(len(threads), 4)
        self.assertTrue(all(name.startswith('scrypt') for name in threads), threads)
        self.assertEqual(SCRYPT_EXECUTOR._max_workers, 4)
        self.assertEqual(SCRYPT_EXECUTOR._thread_name_prefix, 'scrypt')
        self.assertEqual(accounts.pending, 0)

    def test_the_21st_queued_verify_is_refused_as_busy_while_20_are_held(self):
        self.assertEqual(VERIFY_LIMIT, 20)
        gate = threading.Event()
        def held(hash_string, password):
            gate.wait(10); return True
        async def run():
            with patch.object(accounts, 'verify_password', side_effect=held):
                tasks = [asyncio.ensure_future(accounts.averify('x', 'y')) for _ in range(20)]
                await asyncio.sleep(0.05)
                self.assertEqual(accounts.pending, 20)
                with self.assertRaises(Busy):
                    await accounts.averify('x', 'y')
                self.assertEqual(accounts.pending, 20, 'a refused attempt counts nothing')
                gate.set()
                results = await asyncio.gather(*tasks)
            self.assertEqual(results, [True]*20)
            self.assertEqual(accounts.pending, 0)
            self.assertTrue(await accounts.averify(hash_password('correct horse battery staple', FAST), 'correct horse battery staple'))
        asyncio.run(run())

    def test_a_failing_verify_releases_its_slot(self):
        async def run():
            with patch.object(accounts, 'verify_password', side_effect=RuntimeError('fixture')):
                with self.assertRaises(RuntimeError): await accounts.averify('x', 'y')
            self.assertEqual(accounts.pending, 0)
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()


# ---- route level (BUILD.md S1b): one scrypt per POST /api/session, the busy bound through the route, rehash on sign-in ----
import tempfile
from fastapi.testclient import TestClient
from app.main import create_app
from session_fixture import SignedInClient, PASSWORD, NAME, sign_in, assert_not_logged


def close_app(app):
    for name in ('design_apply', 'network_design', 'telemetry_retirement', 'restore', 'git_progress', 'operations', 'discovery',
                 'readiness', 'node_services', 'runner'):
        getattr(app.state, name).close()


class SignInRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name); self.addCleanup(close_app, self.app)
        self.client = SignedInClient(self.app); self.addCleanup(self.client.close)

    def test_exactly_one_scrypt_per_attempt_whatever_the_name_and_none_when_throttled(self):
        anonymous = TestClient(self.app); self.addCleanup(anonymous.close)
        calls = []; real = accounts._scrypt
        def counting(*args, **kwargs):
            calls.append(threading.current_thread().name); return real(*args, **kwargs)
        with patch('app.accounts._scrypt', counting):
            for name, password, status in (('nobody', 'whatever', 401), (NAME, 'wrong passphrase', 401), (NAME, PASSWORD, 200), ('NOT a name', 'x', 401)):
                calls.clear()
                self.assertEqual(anonymous.post('/api/session', json={'username': name, 'password': password}).status_code, status, name)
                self.assertEqual(len(calls), 1, name); self.assertTrue(calls[0].startswith('scrypt'), calls)
            calls.clear()
            with patch.object(self.app.state.sessions, 'check', return_value=3):
                self.assertEqual(anonymous.post('/api/session', json={'username': NAME, 'password': PASSWORD}).status_code, 429)
            self.assertEqual(calls, [])
        assert_not_logged(self.app, PASSWORD, 'wrong passphrase', anonymous.cookies.get('clab_session'))

    def test_the_21st_queued_verify_is_refused_busy_through_the_route_while_20_are_held(self):
        # Twenty people, each their own (source, name) pair: the throttle counts an attempt in flight on its pair
        # (8.2), so twenty held verifies of one pair could never fill the executor; the bound under test is 4.1's.
        gate = threading.Event(); real = accounts.verify_password
        def held(hash_string, password):
            gate.wait(30); return real(hash_string, password)
        people = [(f'held{i:02d}', 'the held verify passphrase') for i in range(20)]
        with SignedInClient(self.app) as client:
            for name, password in people:
                self.assertEqual(client.post('/api/users', json={'name': name, 'role': 'operator', 'password': password}).status_code, 200)
        with SignedInClient(self.app) as client, patch('app.accounts.verify_password', held):
            browsers = [TestClient(self.app) for _ in range(21)]
            for browser in browsers: browser.portal = client.portal; self.addCleanup(browser.close)
            results = []
            def attempt(browser, name, password): results.append(browser.post('/api/session', json={'username': name, 'password': password}))
            threads = [threading.Thread(target=attempt, args=(browser, name, password)) for browser, (name, password) in zip(browsers[:20], people)]
            for thread in threads: thread.start()
            for _ in range(500):
                if accounts.pending >= VERIFY_LIMIT: break
                time.sleep(0.01)
            self.assertEqual(accounts.pending, VERIFY_LIMIT)
            refused = browsers[20].post('/api/session', json={'username': NAME, 'password': PASSWORD})
            self.assertEqual(refused.status_code, 429, refused.text)
            self.assertEqual(refused.json()['detail'], {'code': 'throttled', 'retry_after': 2, 'message': 'Too many sign-in attempts. Try again in 2 s.'})
            self.assertEqual(refused.headers['retry-after'], '2')
            gate.set()
            for thread in threads: thread.join(timeout=60)
            self.assertEqual([r.status_code for r in results], [200] * 20)
            self.assertEqual(accounts.pending, 0)
        self.app.state.sessions.flush_failures(force=True)
        text = (Path(self.tmp.name)/'audit-failures.jsonl').read_text()
        self.assertIn('"signin.throttled"', text); self.assertIn('busy count=1 retry_after=2', text)

    def test_rehash_on_sign_in_keeps_the_stamp_and_the_session(self):
        store = self.app.state.store
        with store.lock:
            record = store.state['users'][NAME]
            record['password'] = hash_password(PASSWORD, FAST); stamp = record['password_changed']; store.save()
        self.app.state.sessions.set_user(record)
        anonymous = TestClient(self.app); self.addCleanup(anonymous.close)
        self.assertEqual(sign_in(anonymous)['user']['name'], NAME)
        saved = store.state['users'][NAME]
        self.assertEqual((parse_hash(saved['password'])['n'], saved['password_changed']), (PARAMS['n'], stamp))
        self.assertEqual(anonymous.get('/api/state').status_code, 200)
        self.assertEqual(self.client.get('/api/state').status_code, 200, 'the other session survives: the password did not change')
