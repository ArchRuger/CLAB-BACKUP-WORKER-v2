"""The audit log (DESIGN.md 10; BUILD.md S1a).

Unit level: the two files and their rotation, the entry fields, the one vocabulary, per-minute summing
(FailureBuckets, the pure component Sessions wraps under its lock), the actor rule, audit_entries,
the actor on events.jsonl. The route-level cases (GET /api/audit, the forbidden bucket from
require_admin, no api.request event for the sign-in routes, assert_not_logged after a sign-in) are
S1b's part of this file; the users.js label-map case runs once S9's file exists.
"""
import json
import os
import re
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app import accounts
from app.accounts import AUDIT_EVENTS, AUDIT_OUTCOMES, AUDIT_REASONS, FailureBuckets, write_failure_entries
from app.store import Store

USERS_JS = Path(__file__).resolve().parents[1]/'app'/'static'/'users.js'


class StoreAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.root = Path(self.tmp.name)

    def lines(self, name):
        path = self.root/name
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_audit_entry_fields_file_and_mode(self):
        entry = self.store.audit('user.created', actor='root', source='203.0.113.9', outcome='ok', target='jane', detail='role=operator')
        self.assertEqual(list(entry), ['time', 'event', 'actor', 'source', 'outcome', 'target', 'detail'])
        self.assertEqual(self.lines('audit.jsonl'), [entry])
        self.assertEqual(oct((self.root/'audit.jsonl').stat().st_mode & 0o777), '0o600')
        self.assertFalse((self.root/'audit-failures.jsonl').exists())
        datetime.fromisoformat(entry['time'])
        short = self.store.audit('signout', actor='root', source='203.0.113.9', outcome='ok')
        self.assertEqual((short['target'], short['detail']), ('', ''))

    def test_audit_failure_goes_to_its_own_file(self):
        entry = self.store.audit_failure('signin.failed', actor='-', source='203.0.113.9', outcome='failed', detail='invalid_credentials count=3')
        self.assertEqual(list(entry), ['time', 'event', 'actor', 'source', 'outcome', 'target', 'detail'])
        self.assertEqual(self.lines('audit-failures.jsonl'), [entry])
        self.assertEqual(self.lines('audit.jsonl'), [])
        self.assertEqual(oct((self.root/'audit-failures.jsonl').stat().st_mode & 0o777), '0o600')

    def test_detail_is_bounded_to_200_characters(self):
        entry = self.store.audit('signin', actor='root', source='::1', outcome='ok', detail='x'*500)
        self.assertEqual(len(entry['detail']), 200)
        self.assertEqual(len(self.lines('audit.jsonl')[0]['detail']), 200)

    def test_each_file_rotates_on_its_own_five_mebibytes_times_four(self):
        self.assertEqual(Store.ROTATE_BYTES, 5*1024*1024)
        with patch.object(Store, 'ROTATE_BYTES', 300):
            for index in range(12): self.store.audit('signin', actor='root', source='203.0.113.9', outcome='ok', detail=f'n{index}')
            names = sorted(p.name for p in self.root.glob('audit.jsonl*'))
            self.assertEqual(names, ['audit.jsonl', 'audit.jsonl.1', 'audit.jsonl.2', 'audit.jsonl.3'])
            self.assertFalse(list(self.root.glob('audit-failures.jsonl*')), 'the other file did not move')
            for index in range(12): self.store.audit_failure('signin.failed', actor='-', source='203.0.113.9', outcome='failed', detail=f'invalid_credentials count={index}')
            self.assertEqual(sorted(p.name for p in self.root.glob('audit-failures.jsonl*')),
                             ['audit-failures.jsonl', 'audit-failures.jsonl.1', 'audit-failures.jsonl.2', 'audit-failures.jsonl.3'])
            self.assertEqual(sorted(p.name for p in self.root.glob('audit.jsonl*')), names, 'and the first did not move again')
            self.assertFalse(list(self.root.glob('events.jsonl.*')), 'events.jsonl keeps its own rotation')
        kept = sum(len(p.read_text().splitlines()) for p in self.root.glob('audit*.jsonl*'))
        active = sum(len((self.root/name).read_text().splitlines()) for name in ('audit.jsonl', 'audit-failures.jsonl'))
        self.assertGreater(kept, active, 'the rotations hold entries of their own')
        entries, total = self.store.audit_entries(100, 0)
        self.assertEqual(total, kept, 'audit_entries reads the rotations of both files')
        self.assertEqual(len(entries), kept)

    def test_each_file_has_its_own_write_failure_flag_and_warns_once(self):
        real = os.open
        def failing(path, *args, **kwargs):
            if str(path).endswith('audit-failures.jsonl'): raise OSError('disk fixture')
            return real(path, *args, **kwargs)
        with patch('app.store.os.open', side_effect=failing):
            with self.assertLogs('app.store', level='WARNING') as captured:
                self.store.audit_failure('signin.failed', actor='-', source='::1', outcome='failed', detail='invalid_credentials count=1')
                self.store.audit_failure('signin.failed', actor='-', source='::1', outcome='failed', detail='invalid_credentials count=1')
            self.assertEqual(len(captured.records), 1)
            self.assertTrue(self.store.audit_failures_error)
            self.store.audit('signin', actor='root', source='::1', outcome='ok')
            self.assertFalse(self.store.audit_error)
            self.assertFalse(self.store.event_error)
        self.store.audit_failure('signin.failed', actor='-', source='::1', outcome='failed', detail='invalid_credentials count=1')
        self.assertFalse(self.store.audit_failures_error)
        self.assertNotIn('disk fixture', ''.join(captured.output), 'no filesystem diagnostics in the warning')

    def test_append_audit_needs_no_store(self):
        fresh = Path(self.tmp.name)/'other'
        fresh.mkdir()
        entry = Store.audit_entry('recover.requested', actor='-', source='-', outcome='ok')
        Store.append_audit(fresh, entry)
        self.assertEqual([json.loads(l) for l in (fresh/'audit.jsonl').read_text().splitlines()], [entry])
        self.assertFalse((fresh/'state.key').exists()); self.assertFalse((fresh/'state.enc').exists())
        self.assertEqual(oct((fresh/'audit.jsonl').stat().st_mode & 0o777), '0o600')

    def test_audit_entries_merges_both_files_and_the_extra_newest_first(self):
        times = ['2026-11-01T10:00:0%d+00:00' % i for i in range(6)]
        with patch('app.store.Store.now', side_effect=[times[0], times[2], times[4]]):
            self.store.audit('signin', actor='root', source='203.0.113.9', outcome='ok')
            self.store.audit('user.created', actor='root', source='203.0.113.9', outcome='ok', target='jane', detail='role=operator')
            self.store.audit('forbidden', actor='jane', source='203.0.113.10', outcome='failed', target='/api/users', detail='admin_required count=3')
        with patch('app.store.Store.now', side_effect=[times[1], times[3]]):
            self.store.audit_failure('signin.failed', actor='-', source='198.51.100.7', outcome='failed', detail='invalid_credentials count=50')
            self.store.audit_failure('signin.throttled', actor='jane', source='198.51.100.7', outcome='throttled', detail='pair count=4 retry_after=60')
        extra = [Store.audit_entry('signin.failed', actor='-', source='198.51.100.8', outcome='failed', detail='invalid_credentials count=2', time=times[5])]
        entries, total = self.store.audit_entries(100, 0, extra=extra)
        self.assertEqual(total, 6)
        self.assertEqual([e['time'] for e in entries], list(reversed(times)))
        page, total = self.store.audit_entries(2, 1)
        self.assertEqual(total, 5); self.assertEqual([e['time'] for e in page], [times[3], times[2]])
        self.assertEqual(self.store.audit_entries(100, 0, event='signin.failed', extra=extra)[1], 2)
        self.assertEqual(self.store.audit_entries(100, 0, event='signin.failed,signin.throttled')[1], 2, 'a comma list')
        self.assertEqual(self.store.audit_entries(100, 0, event='signin.failed, signin.throttled')[1], 2, 'spaces around the comma are forgiven')
        self.assertEqual(self.store.audit_entries(100, 0, event='signin_failed')[1], 0, 'an unknown code matches nothing')
        self.assertEqual(self.store.audit_entries(100, 0, actor='-')[1], 1)
        self.assertEqual(self.store.audit_entries(100, 0, actor='jane')[1], 2)
        self.assertEqual(self.store.audit_entries(100, 0, outcome='failed')[1], 2)
        self.assertEqual(self.store.audit_entries(100, 0, since=times[3])[1], 2)
        self.assertEqual(self.store.audit_entries(100, 0, since='not a time')[1], 5, 'an unparsable since filters nothing')
        self.assertEqual(self.store.audit_entries(100, 0, address='198.51.100.7')[1], 2)
        self.assertEqual(self.store.audit_entries(100, 0, address='198.51.100.')[1], 2, 'a prefix matches')
        self.assertEqual(self.store.audit_entries(100, 0, address='203.0.113.10')[1], 1)
        self.assertEqual(self.store.audit_entries(0, 0)[0], [])
        (self.root/'audit.jsonl').write_text((self.root/'audit.jsonl').read_text() + 'not json\n')
        self.assertEqual(self.store.audit_entries(100, 0)[1], 5, 'a damaged line is skipped')

    def test_events_gain_actor_and_never_source(self):
        entry = self.store.event('api.request', 'POST /api/labs -> 200')
        self.assertEqual(entry['actor'], '-')
        self.assertNotIn('source', entry)
        self.store.event('api.request', 'POST /api/labs -> 200', actor='root')
        self.store.event('terminal.open', 'r1', actor='jane', lab_id='lab1')
        for line in (self.root/'events.jsonl').read_text().splitlines():
            parsed = json.loads(line)
            self.assertIn('actor', parsed); self.assertNotIn('source', parsed)
            self.assertEqual(list(parsed), ['time', 'action', 'message', 'level', 'lab_id', 'job_id', 'node', 'actor'])
        self.assertEqual([e['actor'] for e in self.store.events()], ['jane', 'root', '-', '-'], 'worker.start carries the default too')
        self.assertEqual(len(self.store.events(actor='root')), 1)
        self.assertEqual(len(self.store.events(actor='-')), 2)
        self.assertEqual(len(self.store.events('lab1')), 1, 'positional callers keep working (main.py:306)')
        self.assertEqual(self.store.events(lab_id='lab1', actor='root'), [])

    def test_reset_keeps_both_audit_files_and_their_rotations(self):
        with patch.object(Store, 'ROTATE_BYTES', 200):
            for index in range(8):
                self.store.audit('signin', actor='root', source='::1', outcome='ok', detail=f'n{index}')
                self.store.audit_failure('signin.failed', actor='-', source='::1', outcome='failed', detail=f'invalid_credentials count={index}')
        before = {p.name: p.read_bytes() for p in self.root.glob('audit*.jsonl*')}
        self.assertEqual(len(before), 8)
        self.store.event('old.log', 'old history')
        self.store.reset()
        after = {p.name: p.read_bytes() for p in self.root.glob('audit*.jsonl*')}
        self.assertEqual(after, before)
        self.assertFalse((self.root/'events.jsonl').exists(), 'the operational log was moved aside, as before')
        self.assertFalse((self.root/'.reset-pending').exists())


class VocabularyTests(unittest.TestCase):
    EVENTS = ('setup', 'setup.failed', 'recover.requested', 'recover.expired', 'signin', 'signin.failed', 'signin.throttled',
              'signout', 'session.expired', 'session.ended', 'password.changed', 'user.created', 'user.deleted', 'user.disabled',
              'user.enabled', 'user.role', 'user.password_reset', 'forbidden', 'manager.reset')
    REASONS = ('setup', 'recover', 'invalid_code', 'weak_password', 'invalid_name', 'exists', 'invalid_credentials', 'disabled',
               'bad_record', 'pair', 'source', 'name', 'busy', 'idle', 'absolute', 'user_disabled', 'user_deleted',
               'password_reset', 'password_changed', 'evicted', 'admin_required')

    def test_the_one_vocabulary_of_design_10_2(self):
        self.assertEqual(AUDIT_EVENTS, self.EVENTS)
        self.assertEqual(AUDIT_OUTCOMES, ('ok', 'failed', 'throttled'))
        self.assertEqual(AUDIT_REASONS, self.REASONS)
        self.assertEqual(len(AUDIT_REASONS), 21)
        self.assertEqual(len(set(AUDIT_EVENTS)), len(AUDIT_EVENTS))
        for token in ('count', 'retry_after', 'role'): self.assertNotIn(token, AUDIT_REASONS, 'tokens with a value are not reasons')

    @unittest.skipUnless(USERS_JS.exists(), 'app/static/users.js is S9\'s file; this case runs at integration')
    def test_users_js_labels_match_vocabulary(self):
        source = USERS_JS.read_text(encoding='utf8')
        def lift(name):
            match = re.search(name + r'\s*=\s*(\{.*?\})\s*;', source, re.S)
            self.assertIsNotNone(match, name + ' is not a JSON object literal in users.js')
            return json.loads(match.group(1))
        self.assertEqual(set(lift('AUDIT_EVENT_LABELS')), set(AUDIT_EVENTS))
        self.assertEqual(set(lift('AUDIT_OUTCOME_LABELS')), set(AUDIT_OUTCOMES))
        details = set(lift('AUDIT_DETAIL_LABELS'))
        self.assertTrue(set(AUDIT_REASONS) <= details, set(AUDIT_REASONS) - details)
        self.assertTrue(details - set(AUDIT_REASONS) <= {'count', 'retry_after', 'role'}, details - set(AUDIT_REASONS))


class FailureBucketTests(unittest.TestCase):
    T0 = datetime(2026, 11, 1, 10, 0, 5, tzinfo=timezone.utc).timestamp()

    def test_fifty_failures_under_fifty_unknown_names_in_one_minute_are_one_entry(self):
        buckets = FailureBuckets()
        for index in range(50):
            overflow = buckets.add('signin.failed', '198.51.100.7', '-', 'invalid_credentials', now=self.T0 + index)
            self.assertEqual(overflow, [])
        open_entries = buckets.open_entries()
        self.assertEqual(len(open_entries), 1, 'visible before the minute closes')
        entry = open_entries[0]
        self.assertEqual(entry, {'time': datetime.fromtimestamp(self.T0, timezone.utc).isoformat(timespec='microseconds'), 'event': 'signin.failed', 'actor': '-',
                                 'source': '198.51.100.7', 'outcome': 'failed', 'target': '', 'detail': 'invalid_credentials count=50'})
        self.assertEqual(buckets.flush(now=self.T0 + 54), [], 'the minute has not passed')
        self.assertEqual(buckets.flush(now=self.T0 + 55), [entry], 'closed once the UTC minute passed')
        self.assertEqual(buckets.open_entries(), [])
        self.assertEqual(buckets.flush(now=self.T0 + 55), [])

    def test_buckets_are_per_event_source_actor_target_reason_and_minute(self):
        buckets = FailureBuckets()
        buckets.add('signin.failed', 'S1', '-', 'invalid_credentials', now=self.T0)
        buckets.add('signin.failed', 'S1', 'jane', 'invalid_credentials', now=self.T0)
        buckets.add('signin.failed', 'S1', 'jane', 'disabled', now=self.T0)
        buckets.add('signin.failed', 'S2', 'jane', 'invalid_credentials', now=self.T0)
        buckets.add('setup.failed', 'S1', '-', 'invalid_code', now=self.T0)
        buckets.add('signin.failed', 'S1', '-', 'invalid_credentials', now=self.T0 + 60)
        buckets.add('forbidden', 'S1', 'jane', 'admin_required', target='/api/users', now=self.T0)
        buckets.add('forbidden', 'S1', 'jane', 'admin_required', target='/api/users/{name}', now=self.T0)
        self.assertEqual(len(buckets.open_entries()), 8)
        buckets.add('signin.throttled', 'S1', '-', 'pair', retry_after=30, now=self.T0)
        buckets.add('signin.throttled', 'S1', '-', 'pair', retry_after=120, now=self.T0 + 1)
        buckets.add('signin.throttled', 'S1', '-', 'pair', retry_after=60, now=self.T0 + 2)
        throttled = [e for e in buckets.open_entries() if e['event'] == 'signin.throttled']
        self.assertEqual(len(throttled), 1)
        self.assertEqual((throttled[0]['outcome'], throttled[0]['detail']), ('throttled', 'pair count=3 retry_after=120'))
        forbidden = [e for e in buckets.open_entries() if e['event'] == 'forbidden']
        self.assertEqual({(e['target'], e['detail'], e['outcome']) for e in forbidden},
                         {('/api/users', 'admin_required count=1', 'failed'), ('/api/users/{name}', 'admin_required count=1', 'failed')})
        closed = buckets.flush(now=self.T0 + 60)
        self.assertEqual(len(closed), 8, 'the first minute closes; the second stays open')
        self.assertEqual(len(buckets.open_entries()), 1)
        forced = buckets.flush(force=True, now=self.T0 + 61)
        self.assertEqual(len(forced), 1); self.assertEqual(buckets.open_entries(), [])

    def test_thirty_forbidden_requests_by_one_operator_in_one_minute_are_one_entry_with_the_route_template(self):
        buckets = FailureBuckets()
        for index in range(30): buckets.add('forbidden', '203.0.113.10', 'jane', 'admin_required', target='/api/users', now=self.T0 + index)
        entry, = buckets.open_entries()
        self.assertEqual((entry['event'], entry['actor'], entry['target'], entry['detail'], entry['outcome']),
                         ('forbidden', 'jane', '/api/users', 'admin_required count=30', 'failed'))

    def test_the_bound_flushes_the_oldest_bucket(self):
        buckets = FailureBuckets(limit=3)
        self.assertEqual(buckets.add('signin.failed', 'S1', '-', 'invalid_credentials', now=self.T0), [])
        self.assertEqual(buckets.add('signin.failed', 'S2', '-', 'invalid_credentials', now=self.T0 + 1), [])
        self.assertEqual(buckets.add('signin.failed', 'S3', '-', 'invalid_credentials', now=self.T0 + 2), [])
        overflow = buckets.add('signin.failed', 'S4', '-', 'invalid_credentials', now=self.T0 + 3)
        self.assertEqual([e['source'] for e in overflow], ['S1'])
        self.assertEqual(sorted(e['source'] for e in buckets.open_entries()), ['S2', 'S3', 'S4'])
        self.assertEqual(buckets.add('signin.failed', 'S2', '-', 'invalid_credentials', now=self.T0 + 4), [], 'an existing bucket grows without eviction')

    def test_write_failure_entries_routes_forbidden_to_the_security_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            buckets = FailureBuckets()
            buckets.add('signin.failed', 'S1', '-', 'invalid_credentials', now=self.T0)
            buckets.add('signin.throttled', 'S1', '-', 'source', retry_after=30, now=self.T0)
            buckets.add('setup.failed', 'S1', '-', 'invalid_code', now=self.T0)
            buckets.add('forbidden', 'S1', 'jane', 'admin_required', target='/api/audit', now=self.T0)
            write_failure_entries(store, buckets.flush(force=True))
            security = [json.loads(l) for l in (Path(tmp)/'audit.jsonl').read_text().splitlines()]
            failures = [json.loads(l) for l in (Path(tmp)/'audit-failures.jsonl').read_text().splitlines()]
            self.assertEqual([e['event'] for e in security], ['forbidden'])
            self.assertEqual(sorted(e['event'] for e in failures), ['setup.failed', 'signin.failed', 'signin.throttled'])
            self.assertEqual(security[0]['time'], datetime.fromtimestamp(self.T0, timezone.utc).isoformat(timespec='microseconds'), 'the time of the first failure')
            for entry in security + failures:
                self.assertIn(entry['event'], AUDIT_EVENTS); self.assertIn(entry['outcome'], AUDIT_OUTCOMES)
                self.assertIn(entry['detail'].split()[0], AUDIT_REASONS)

    def test_a_submitted_name_that_is_not_a_record_never_reaches_a_bucket_or_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            users = {'root': {'name': 'root'}}
            secret = 'correct horse battery staple'
            buckets = FailureBuckets()
            buckets.add('signin.failed', 'S1', accounts.failure_actor(users, secret), 'invalid_credentials', now=self.T0)
            buckets.add('signin.throttled', 'S1', accounts.failure_actor(users, secret), 'pair', retry_after=30, now=self.T0)
            buckets.add('setup.failed', 'S1', accounts.failure_actor(users, secret), 'invalid_code', now=self.T0)
            buckets.add('signin.failed', 'S1', accounts.failure_actor(users, 'root'), 'invalid_credentials', now=self.T0)
            self.assertNotIn(secret, json.dumps(buckets.open_entries()))
            write_failure_entries(store, buckets.flush(force=True))
            text = ''.join(p.read_text() for p in Path(tmp).glob('*.jsonl*'))
            self.assertNotIn(secret, text)
            self.assertIn('"actor": "root"', text)


if __name__ == '__main__':
    unittest.main()
