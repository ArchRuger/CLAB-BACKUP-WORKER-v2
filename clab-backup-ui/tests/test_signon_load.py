"""Sign-in throttling and load (sign-on DESIGN.md 8, 13.1; REVIEW R5, R6, R7; BUILD.md S1b).

The three levels are driven through the Sessions object on a fake clock; the load case drives the real app
through one shared TestClient portal from fifty threads.
"""
import asyncio
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app import accounts, sessions as sessions_module
from app.main import create_app
from app.sessions import Sessions, source_key, FIRST_DELAY, DELAY_CAP, L1_FREE, L2_THRESHOLD, L3_TOKENS, L3_REFILL
from app.store import Store
from session_fixture import SignedInClient, PASSWORD, NAME, assert_not_logged

FAMILIAR = '203.0.113.7'       # a source whose prefix is in the victim's known_sources
STRANGER = '198.51.100.9'


def close_app(app):
    for name in ('design_apply', 'network_design', 'telemetry_retirement', 'restore', 'git_progress', 'operations', 'discovery',
                 'readiness', 'node_services', 'runner'):
        getattr(app.state, name).close()


class ThrottleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.sessions = Sessions(self.store)
        self.now = [10_000.0]; self.sessions.clock = lambda: self.now[0]
        users = {name: accounts.new_record(name, 'operator', accounts.DUMMY_HASH, created_by='root', must_change_password=False) for name in ('victim', 'alice', 'root')}
        self.sessions.load_users(users)

    def advance(self, seconds): self.now[0] += seconds

    def throttled(self):
        self.sessions.flush_failures(force=True)
        path = Path(self.tmp.name)/'audit-failures.jsonl'
        return [e for e in (json.loads(l) for l in path.read_text().splitlines())] if path.exists() else []

    def test_l1_five_free_then_doubling_to_the_cap_and_a_success_clears_only_the_pair(self):
        check = lambda: self.sessions.check(FAMILIAR, 'victim', True)
        for _ in range(L1_FREE):
            self.assertEqual(check(), 0); self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
        expected = FIRST_DELAY
        for step in range(7):
            self.assertEqual(check(), expected, step)
            self.advance(expected - 1); self.assertEqual(check(), 1, step)
            self.advance(1); self.assertEqual(check(), 0, step)
            self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
            expected = min(DELAY_CAP, expected * 2)
        self.assertEqual(check(), DELAY_CAP, 'capped at 15 min')
        # Another pair of the same source is free; another source of the same name is free (L3 is not consulted: familiar).
        self.assertEqual(self.sessions.check(FAMILIAR, 'alice', True), 0)
        self.assertEqual(self.sessions.check(STRANGER, 'victim', True), 0)
        self.sessions.success(FAMILIAR, 'victim')
        self.assertEqual(check(), 0, 'a success clears the pair')
        entries = [e for e in self.throttled() if e['event'] == 'signin.throttled']
        self.assertTrue(entries and all(e['outcome'] == 'throttled' and e['actor'] == 'victim' and e['source'] == FAMILIAR for e in entries), entries)
        self.assertTrue(all(e['detail'].startswith('pair count=') for e in entries), [e['detail'] for e in entries])
        failed = sum(int(e['detail'].split('count=')[1]) for e in self.throttled() if e['event'] == 'signin.failed')
        self.assertEqual(failed, L1_FREE + 7, 'throttled attempts change no counter and are not failures')

    def test_l1_an_idle_pair_is_pruned_after_an_hour(self):
        for _ in range(L1_FREE): self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
        self.assertEqual(self.sessions.check(FAMILIAR, 'victim', True), FIRST_DELAY)
        self.advance(3601); self.sessions.sweep()
        self.assertEqual(self.sessions.pairs, {})
        self.assertEqual(self.sessions.check(FAMILIAR, 'victim', True), 0)

    def test_l2_a_hundred_failures_in_the_window_then_doubling_and_a_success_removes_only_its_name(self):
        names = [f'guess{i:03d}' for i in range(L2_THRESHOLD + 1)]
        for name in names[:L2_THRESHOLD - 1]:
            self.assertEqual(self.sessions.check(STRANGER, name, False), 0); self.sessions.failure(STRANGER, name, False, 'invalid_credentials')
        self.assertEqual(self.sessions.check(STRANGER, names[99], False), 0, '99 records: free')
        self.sessions.failure(STRANGER, names[99], False, 'invalid_credentials')
        self.assertEqual(self.sessions.check(STRANGER, names[100], False), FIRST_DELAY, 'the 100th record delays the source')
        self.assertEqual(self.sessions.check(FAMILIAR, names[100], False), 0, 'another source is free')
        self.advance(FIRST_DELAY)
        self.assertEqual(self.sessions.check(STRANGER, names[100], False), 0)
        self.sessions.failure(STRANGER, names[100], False, 'invalid_credentials')
        self.assertEqual(self.sessions.check(STRANGER, 'anyone', False), FIRST_DELAY * 2, 'doubled')
        # A success of (S, N) removes only S's records for N: 101 → 100 keeps the delay, 100 → 99 ends it.
        self.sessions.success(STRANGER, names[0])
        self.assertEqual(self.sessions.check(STRANGER, 'anyone', False), FIRST_DELAY * 2)
        self.sessions.success(STRANGER, names[1])
        self.assertEqual(self.sessions.check(STRANGER, 'anyone', False), 0)
        self.assertEqual(len(self.sessions.sources[STRANGER]['window']), 99)
        entries = [e for e in self.throttled() if e['event'] == 'signin.throttled']
        self.assertTrue(all(e['actor'] == '-' and e['detail'].startswith('source count=') for e in entries), entries)

    def test_l2_the_window_slides_and_a_source_holds_at_most_200_records(self):
        for i in range(250): self.sessions.failure(STRANGER, f'n{i}', False, 'invalid_credentials')
        self.assertEqual(len(self.sessions.sources[STRANGER]['window']), 200)
        self.advance(901)
        self.assertEqual(self.sessions.check(STRANGER, 'x', False), 0, 'records older than 15 min drop; the delay ends')
        self.sessions.sweep(); self.assertNotIn(STRANGER, self.sessions.sources)

    def test_thirty_students_behind_one_nat_making_ordinary_typos_all_sign_in(self):
        nat = '192.0.2.44'
        for i in range(30):
            name = f'student{i:02d}'
            for _ in range(3):
                self.assertEqual(self.sessions.check(nat, name, False), 0, name); self.sessions.failure(nat, name, False, 'invalid_credentials')
            self.assertEqual(self.sessions.check(nat, name, False), 0, name); self.sessions.success(nat, name)
        self.assertEqual(self.sessions.pairs, {})
        self.assertEqual(self.sessions.check(nat, 'student31', False), 0)

    def test_l3_a_distributed_attack_on_one_name_never_locks_the_familiar_source_out(self):
        for i in range(L3_TOKENS):
            source = f'198.51.{i}.9'
            self.assertEqual(self.sessions.check(source, 'victim', False), 0, i); self.sessions.failure(source, 'victim', False, 'invalid_credentials')
        fresh = self.sessions.check('198.51.200.1', 'victim', False)
        self.assertTrue(0 < fresh <= L3_REFILL, fresh)
        self.assertEqual(self.sessions.check(FAMILIAR, 'victim', True), 0, 'the familiar source never consults L3')
        self.sessions.success(FAMILIAR, 'victim')
        self.assertTrue(0 < self.sessions.check('198.51.200.2', 'victim', False) <= L3_REFILL, 'a success refills nothing')
        self.advance(L3_REFILL)
        self.assertEqual(self.sessions.check('198.51.200.3', 'victim', False), 0, 'one token back every 30 s')
        self.sessions.failure('198.51.200.3', 'victim', False, 'invalid_credentials')
        self.assertTrue(0 < self.sessions.check('198.51.200.4', 'victim', False) <= L3_REFILL)
        entries = [e for e in self.throttled() if e['event'] == 'signin.throttled']
        self.assertTrue(entries and all(e['actor'] == 'victim' and e['detail'].startswith('name count=') and ' retry_after=' in e['detail'] for e in entries), entries)
        # Full buckets are pruned; an attacked name's bucket stays while it refills.
        self.advance(L3_REFILL * L3_TOKENS); self.sessions.sweep()
        self.assertEqual(self.sessions.names, {})

    # An attempt that passed `check` is in flight until `failure`, `success` or `release` settles it, and every
    # level counts it as if it had failed: a burst sent at once cannot pass the levels before the first answer.
    def test_l1_counts_the_attempts_in_flight_so_a_burst_cannot_pass_before_the_first_answer(self):
        check = lambda: self.sessions.check(FAMILIAR, 'victim', True)
        for step in range(L1_FREE): self.assertEqual(check(), 0, step)
        self.assertEqual(check(), FIRST_DELAY, 'the sixth attempt is refused while five are in flight')
        for _ in range(L1_FREE): self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
        self.assertEqual(check(), FIRST_DELAY, 'settling the five as failures changes nothing')
        failed = sum(int(e['detail'].split('count=')[1]) for e in self.throttled() if e['event'] == 'signin.failed')
        throttled = sum(int(e['detail'].split('count=')[1].split()[0]) for e in self.throttled() if e['event'] == 'signin.throttled')
        self.assertEqual((failed, throttled), (L1_FREE, 2), 'an attempt in flight is counted once, as the failure it became')
        self.sessions.success(FAMILIAR, 'victim')
        for step in range(L1_FREE): self.assertEqual(check(), 0, step)
        for _ in range(L1_FREE - 1): self.sessions.success(FAMILIAR, 'victim')
        self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
        self.assertEqual(check(), 0, 'the successes settled their reservations; one failure stands')

    def test_a_released_reservation_changes_no_counter(self):
        # The executor's `busy` refusal comes after `check`: the attempt ran no verify and must leave no trace (8.2).
        for step in range(3 * L1_FREE):
            self.assertEqual(self.sessions.check(STRANGER, 'victim', False), 0, step)
            self.sessions.release(STRANGER, 'victim', False)
        self.assertEqual(self.sessions.check(STRANGER, 'victim', False), 0)
        self.sessions.release(STRANGER, 'victim', False)
        self.assertEqual(self.sessions.check('198.51.200.1', 'victim', False), 0, 'no L3 token was spent either')
        self.sessions.release('198.51.200.1', 'victim', False)
        self.sessions.release('198.51.200.1', 'victim', False)   # one release too many is harmless
        for _ in range(L1_FREE): self.sessions.failure(STRANGER, 'victim', False, 'invalid_credentials')
        self.assertEqual(self.sessions.check(STRANGER, 'victim', False), FIRST_DELAY)

    def test_l2_counts_the_attempts_in_flight_from_one_source(self):
        for i in range(L2_THRESHOLD):
            self.assertEqual(self.sessions.check(STRANGER, f'guess{i:03d}', False), 0, i)
        self.assertEqual(self.sessions.check(STRANGER, 'guess100', False), FIRST_DELAY, 'a hundred in flight delay the source')
        self.assertEqual(self.sessions.check(FAMILIAR, 'guess100', False), 0, 'another source is free')
        for i in range(L2_THRESHOLD): self.sessions.success(STRANGER, f'guess{i:03d}')
        self.assertEqual(self.sessions.check(STRANGER, 'guess101', False), 0, 'the successes settled every reservation')

    # Once the last failure is older than the current delay, the reservation alone must hold the level: a burst sent
    # then verifies one attempt, never VERIFY_LIMIT (second verification round on 8.2). An attempt in flight is the
    # failure it may become, dated now, so while one is in flight every other attempt waits the delay that failure
    # would start; `last` still never moves on a reservation, so a released one restarts nothing.
    def test_l1_after_the_delay_has_run_out_one_attempt_at_a_time_is_in_flight(self):
        check = lambda: self.sessions.check(FAMILIAR, 'victim', True)
        for _ in range(L1_FREE):
            self.assertEqual(check(), 0); self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
        self.advance(DELAY_CAP + 1)
        answers = [check() for _ in range(20)]
        self.assertEqual(answers.count(0), 1, answers)
        self.assertEqual(set(answers) - {0}, {FIRST_DELAY * 2}, 'the others wait the delay a sixth failure would start, counted from now')
        self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
        self.assertEqual(check(), FIRST_DELAY * 2, 'the sixth failure started its delay now')
        self.advance(FIRST_DELAY * 2 + 1)
        self.assertEqual(check(), 0); self.assertEqual(check(), FIRST_DELAY * 4)
        self.sessions.release(FAMILIAR, 'victim', True)
        self.assertEqual(check(), 0, 'a released reservation restarts no delay: the next attempt may proceed')
        self.sessions.release(FAMILIAR, 'victim', True)

    def test_l1_at_its_cap_a_burst_after_fifteen_minutes_verifies_one(self):
        check = lambda: self.sessions.check(FAMILIAR, 'victim', True)
        delay = 0
        for step in range(L1_FREE + 6):   # five free, then 30, 60, 120, 240, 480 and 900 s, each waited out
            self.advance(delay + 1)
            self.assertEqual(check(), 0, step); self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
            delay = min(DELAY_CAP, FIRST_DELAY * 2 ** (step + 1 - L1_FREE)) if step + 1 >= L1_FREE else 0
        self.assertEqual(check(), DELAY_CAP)
        self.advance(DELAY_CAP + 1)
        answers = [check() for _ in range(20)]
        self.assertEqual((answers.count(0), set(answers) - {0}), (1, {DELAY_CAP}), answers)
        self.sessions.failure(FAMILIAR, 'victim', True, 'invalid_credentials')
        self.assertEqual(check(), DELAY_CAP, 'one failure per fifteen minutes once capped')
        throttled = [e for e in self.throttled() if e['event'] == 'signin.throttled']
        self.assertEqual(sum(int(e['detail'].split('count=')[1].split()[0]) for e in throttled), 21)
        self.assertTrue(all(e['detail'].startswith('pair count=') for e in throttled), throttled)

    def test_l2_after_the_source_delay_has_run_out_one_attempt_at_a_time_is_in_flight(self):
        for i in range(L2_THRESHOLD):
            self.assertEqual(self.sessions.check(STRANGER, f'guess{i:03d}', False), 0, i)
            self.sessions.failure(STRANGER, f'guess{i:03d}', False, 'invalid_credentials')
        self.assertEqual(self.sessions.check(STRANGER, 'other000', False), FIRST_DELAY)
        self.advance(FIRST_DELAY + 1)
        answers = [self.sessions.check(STRANGER, f'other{i:03d}', False) for i in range(20)]
        self.assertEqual((answers.count(0), set(answers) - {0}), (1, {FIRST_DELAY}), answers)
        self.sessions.failure(STRANGER, 'other000', False, 'invalid_credentials')
        self.assertEqual(self.sessions.check(STRANGER, 'other020', False), FIRST_DELAY * 2, 'the failure doubled the source delay, counted from now')
        self.advance(FIRST_DELAY * 2 + 1)
        self.assertEqual(self.sessions.check(STRANGER, 'other021', False), 0)
        self.assertEqual(self.sessions.check(STRANGER, 'other022', False), FIRST_DELAY * 2)
        self.sessions.release(STRANGER, 'other021', False)
        self.assertEqual(self.sessions.check(STRANGER, 'other022', False), 0, 'a released reservation restarts no delay')
        self.sessions.release(STRANGER, 'other022', False)
        self.assertEqual(sorted(set(e['detail'].split(' count=')[0] for e in self.throttled() if e['event'] == 'signin.throttled')), ['source'])

    def test_l3_tokens_are_held_by_the_attempts_in_flight_from_unfamiliar_sources(self):
        for i in range(L3_TOKENS):
            self.assertEqual(self.sessions.check(f'198.51.{i}.9', 'victim', False), 0, i)
        held = self.sessions.check('198.51.200.1', 'victim', False)
        self.assertTrue(0 < held <= L3_REFILL, held)
        self.assertEqual(self.sessions.check(FAMILIAR, 'victim', True), 0, 'the familiar source never consults L3')
        self.sessions.release(FAMILIAR, 'victim', True)
        for i in range(5): self.sessions.failure(f'198.51.{i}.9', 'victim', False, 'invalid_credentials')
        for i in range(5, L3_TOKENS): self.sessions.success(f'198.51.{i}.9', 'victim')
        for i in range(5):
            self.assertEqual(self.sessions.check(f'198.51.{100 + i}.9', 'victim', False), 0, 'five failed and spent, five succeeded and gave their token back')
        again = self.sessions.check('198.51.200.2', 'victim', False)
        self.assertTrue(0 < again <= L3_REFILL, again)
        entries = [e for e in self.throttled() if e['event'] == 'signin.throttled']
        self.assertTrue(entries and all(e['detail'].startswith('name count=') for e in entries), entries)

    def test_an_insider_cannot_reset_their_counters_by_signing_in_as_themselves(self):
        insider = '10.0.0.5'
        for _ in range(L1_FREE):
            self.sessions.failure(insider, 'root', True, 'invalid_credentials')
            self.sessions.success(insider, 'alice')
        self.assertEqual(self.sessions.check(insider, 'root', True), FIRST_DELAY)
        self.assertEqual(self.sessions.check(insider, 'alice', True), 0)
        self.assertEqual([record[1] for record in self.sessions.sources[insider]['window']], ['root'] * L1_FREE)

    def test_an_ipv4_mapped_address_keys_like_its_ipv4_address_and_an_ipv6_host_shares_its_64(self):
        for _ in range(L1_FREE - 2): self.sessions.failure('::ffff:203.0.113.7', 'victim', True, 'invalid_credentials')
        for _ in range(2): self.sessions.failure('203.0.113.7', 'victim', True, 'invalid_credentials')
        self.assertEqual(self.sessions.check('::ffff:203.0.113.7', 'victim', True), FIRST_DELAY)
        self.assertEqual(set(self.sessions.pairs), {('203.0.113.7', 'victim')})
        for _ in range(L1_FREE): self.sessions.failure('2001:db8:1:2::9', 'root', True, 'invalid_credentials')
        self.assertEqual(self.sessions.check('2001:db8:1:2:ffff::1', 'root', True), FIRST_DELAY, 'the /64 is the key')
        self.assertEqual(source_key('2001:db8:1:2:ffff::1'), '2001:db8:1:2::/64')

    def test_the_tables_are_bounded_and_evict_the_oldest_activity(self):
        with patch.object(sessions_module, 'LEVEL_LIMIT', 50):
            for i in range(60):
                self.advance(1); self.sessions.failure(f'10.1.{i // 256}.{i % 256}', f'name{i}', False, 'invalid_credentials')
            self.assertEqual(len(self.sessions.pairs), 50); self.assertEqual(len(self.sessions.sources), 50); self.assertEqual(len(self.sessions.names), 50)
            self.assertNotIn(('10.1.0.0', 'name0'), self.sessions.pairs); self.assertIn(('10.1.0.59', 'name59'), self.sessions.pairs)
        for _ in range(3): self.sessions.failure(STRANGER, 'victim', True, 'invalid_credentials')
        self.assertEqual(self.sessions.check(STRANGER, 'victim', True), 0, "the attacker's own entries are the newest and stay")


def browser(app, address):
    """A cookie-less client whose requests come from `address`, on the event loop of the enclosing asyncio.run."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(address, 4242)), base_url='http://testserver')


class ConcurrentBurstTests(unittest.TestCase):
    """The verify is awaited; attempts sent at once must not all pass the levels before the first one is counted."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name); self.addCleanup(close_app, self.app)
        SignedInClient(self.app).close()   # the admin `tester`, set up from the TestClient's own source
        self.calls = []; real = accounts._scrypt
        def counting(*args, **kwargs):
            self.calls.append(1); return real(*args, **kwargs)
        patcher = patch('app.accounts._scrypt', counting); patcher.start(); self.addCleanup(patcher.stop)

    def burst(self, addresses, name=NAME):
        async def go():
            clients = [browser(self.app, address) for address in addresses]
            try:
                return await asyncio.gather(*[client.post('/api/session', json={'username': name, 'password': f'wrong guess {i:04d}'}) for i, client in enumerate(clients)])
            finally:
                for client in clients: await client.aclose()
        return [response.status_code for response in asyncio.run(go())]

    def test_twenty_wrong_sign_ins_at_once_from_one_address_verify_at_most_five(self):
        statuses = self.burst([STRANGER] * 20)
        self.assertEqual(sorted(set(statuses)), [401, 429], statuses)
        self.assertLessEqual(statuses.count(401), L1_FREE, statuses)
        self.assertEqual(len(self.calls), statuses.count(401), 'one scrypt per verified attempt and none for a throttled one')
        with self.app.state.sessions.lock:
            pair = self.app.state.sessions.pairs[(STRANGER, NAME)]
        self.assertEqual((pair['failures'], pair['inflight']), (statuses.count(401), 0), 'every attempt settled')

    def test_twenty_wrong_sign_ins_at_once_from_twenty_new_addresses_verify_at_most_ten(self):
        statuses = self.burst([f'203.0.113.{i}' for i in range(1, 21)])
        self.assertLessEqual(statuses.count(401), L3_TOKENS, statuses)
        self.assertEqual(statuses.count(401) + statuses.count(429), 20, statuses)
        self.assertEqual(len(self.calls), statuses.count(401))
        # Six bursts thirty seconds apart: the ten tokens plus one back per window, never forty guesses a minute.
        clock = [self.app.state.sessions.clock()]; self.app.state.sessions.clock = lambda: clock[0]
        verified = statuses.count(401); host = 100
        for window in range(5):
            clock[0] += L3_REFILL
            verified += self.burst([f'203.0.{host + window}.{i}' for i in range(1, 21)]).count(401)
        self.assertLessEqual(verified, L3_TOKENS + 5, verified)
        assert_not_logged(self.app, PASSWORD, 'wrong guess 0000')

    def attempts(self, address, pairs):
        """Sign-ins sent at once from one address: `pairs` are (name, password); the statuses in order."""
        async def go():
            client = browser(self.app, address)
            try: return await asyncio.gather(*[client.post('/api/session', json={'username': n, 'password': p}) for n, p in pairs])
            finally: await client.aclose()
        return [response.status_code for response in asyncio.run(go())]

    def test_an_insider_at_the_capped_delay_gets_one_guess_per_fifteen_minutes_not_twenty(self):
        # A source on the admin's own /24 is familiar, so L3 never applies and L1 alone holds. The pair is walked to
        # its cap one failure at a time; after the fifteen minutes a burst of nineteen verifies one attempt and the
        # eighteen others answer 429 with the full delay (second verification round on 8.2).
        clock = [self.app.state.sessions.clock()]; self.app.state.sessions.clock = lambda: clock[0]
        insider = '203.0.113.77'
        self.assertEqual(self.attempts(insider, [(NAME, PASSWORD)]), [200], 'one success makes the /24 familiar')
        self.assertEqual(self.attempts(insider, [(NAME, f'wrong {i}') for i in range(L1_FREE)]).count(401), L1_FREE)
        for delay in (30, 60, 120, 240, 480):
            clock[0] += delay + 1
            self.assertEqual(self.attempts(insider, [(NAME, 'wrong again')]), [401], delay)
        clock[0] += DELAY_CAP + 1
        self.calls.clear()
        statuses = self.attempts(insider, [(NAME, f'burst {i}') for i in range(19)])
        self.assertEqual((statuses.count(401), statuses.count(429)), (1, 18), statuses)
        self.assertEqual(len(self.calls), 1, 'one scrypt for the one verified attempt')
        self.app.state.sessions.flush_failures(force=True)
        entries = [json.loads(l) for l in (Path(self.tmp.name)/'audit-failures.jsonl').read_text().splitlines()]
        throttled = [e for e in entries if e['event'] == 'signin.throttled']
        self.assertTrue(throttled and all(e['detail'].startswith('pair count=') and e['detail'].endswith(f'retry_after={DELAY_CAP}') for e in throttled), throttled)
        assert_not_logged(self.app, PASSWORD, 'burst 0', 'wrong again')

    def test_a_password_spray_from_one_source_gets_one_guess_per_delay_once_the_source_is_delayed(self):
        # A hundred failures with distinct names delay the source (L2); after the thirty seconds a burst of nineteen
        # new names verifies one attempt, and the next delay is doubled from that failure.
        clock = [self.app.state.sessions.clock()]; self.app.state.sessions.clock = lambda: clock[0]
        sprayer = '198.51.100.40'; verified = 0
        for start in range(0, L2_THRESHOLD, 10):
            verified += self.attempts(sprayer, [(f'nobody{i:03d}', 'x' * 12) for i in range(start, start + 10)]).count(401)
        self.assertEqual(verified, L2_THRESHOLD)
        with self.app.state.sessions.lock: delay = self.app.state.sessions.sources[sprayer]['delay']
        self.assertEqual(delay, FIRST_DELAY)
        clock[0] += FIRST_DELAY + 1
        self.calls.clear()
        statuses = self.attempts(sprayer, [(f'other{i:03d}', 'x' * 12) for i in range(19)])
        self.assertEqual((statuses.count(401), statuses.count(429)), (1, 18), statuses)
        self.assertEqual(len(self.calls), 1)
        with self.app.state.sessions.lock: entry = self.app.state.sessions.sources[sprayer]
        self.assertEqual((entry['delay'], entry['inflight']), (FIRST_DELAY * 2, 0))


class LoadTests(unittest.TestCase):
    def test_fifty_concurrent_sign_ins_while_api_state_still_answers(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        app = create_app(tmp.name); self.addCleanup(close_app, app)
        loader = SignedInClient(app, role='operator', name='loader', password='the load test operator'); loader.close()
        with SignedInClient(app) as client:
            # Fifty cookie-less clients on the one event loop of the entered client (the shared portal), as fifty
            # browsers would be; the admin's own session is left alone by the eviction of the loader's.
            from fastapi.testclient import TestClient
            browsers = [TestClient(app) for _ in range(50)]
            for browser in browsers: browser.portal = client.portal; self.addCleanup(browser.close)
            baseline = []
            for _ in range(5):
                started = time.monotonic(); self.assertEqual(client.get('/api/state').status_code, 200); baseline.append(time.monotonic() - started)
            results = []; latencies = []; polls = []; go = threading.Event(); stop = threading.Event()
            def attempt(browser):
                go.wait(); response = browser.post('/api/session', json={'username': 'loader', 'password': 'the load test operator'})
                results.append((response.status_code, response.json().get('detail', {}).get('code') if response.status_code != 200 else 'ok'))
            def poll():
                go.wait()
                while not stop.is_set():
                    started = time.monotonic(); response = client.get('/api/state'); latencies.append(time.monotonic() - started); polls.append(response.status_code)
            workers = [threading.Thread(target=attempt, args=(browser,)) for browser in browsers]; poller = threading.Thread(target=poll)
            for worker in workers: worker.start()
            poller.start(); go.set()
            for worker in workers: worker.join(timeout=60)
            stop.set(); poller.join(timeout=10)
            self.assertEqual(len(results), 50)
            self.assertEqual(set(polls), {200})
            self.assertTrue(all(r in ((200, 'ok'), (429, 'throttled')) for r in results), results)
            self.assertGreaterEqual(sum(1 for r in results if r[0] == 200), 1)
            self.assertTrue(latencies, 'the poll ran during the burst')
            self.assertLess(max(latencies), 1.0, f'GET /api/state during the burst: max {max(latencies):.3f}s, baseline {max(baseline):.3f}s')
            self.assertLessEqual(app.state.sessions.count('loader'), 32)
            assert_not_logged(app, PASSWORD, 'the load test operator', client.cookies.get('clab_session'))


if __name__ == '__main__':
    unittest.main()
