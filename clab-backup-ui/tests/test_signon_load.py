"""Sign-in throttling and load (sign-on DESIGN.md 8, 13.1; REVIEW R5, R6, R7; BUILD.md S1b).

The three levels are driven through the Sessions object on a fake clock; the load case drives the real app
through one shared TestClient portal from fifty threads.
"""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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
