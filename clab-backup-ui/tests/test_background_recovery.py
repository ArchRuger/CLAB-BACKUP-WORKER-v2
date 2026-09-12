import tempfile
from unittest.mock import Mock, patch
import unittest

from app.discovery import Discovery
from app.lab_operations import LabOperations
from app.runner import Runner
from app.store import Store


class BackgroundRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.discovery = Discovery(self.store); self.addCleanup(self.discovery.close)
        self.operations = LabOperations(self.store, self.discovery); self.addCleanup(self.operations.close)
        self.runner = Runner(self.store); self.addCleanup(self.runner.close)

    def test_discovery_loop_retries_after_storage_failure(self):
        self.discovery.wake = Mock()
        with patch.object(self.discovery.stopping, 'is_set', side_effect=[False, False, True]), \
             patch.object(self.discovery, 'refresh', side_effect=[OSError('disk unavailable'), {}]) as refresh:
            self.discovery.loop()
        self.assertEqual(refresh.call_count, 2)

    def test_scheduler_retries_after_queue_storage_failure(self):
        self.store.state['labs'] = [{'id': 'lab', 'interval': 5, 'next_run': 1}]
        with patch.object(self.runner.stopping, 'wait', side_effect=[False, False, True]), \
             patch.object(self.runner, 'submit', side_effect=[OSError('disk unavailable'), {}]) as submit:
            self.runner.tick()
        self.assertEqual(submit.call_count, 2)

    def test_scheduler_defers_even_when_audit_log_is_unwritable(self):
        lab = {'id': 'lab', 'interval': 5, 'next_run': 1}
        self.store.state['labs'] = [lab]
        with patch.object(self.runner.stopping, 'wait', side_effect=[False, True]), \
             patch.object(self.runner, 'submit', side_effect=ValueError('VM unavailable')), \
             patch.object(self.store, 'event', side_effect=OSError('log unavailable')):
            self.runner.tick()
        self.assertGreater(lab['next_run'], 1)

    def test_finished_operation_releases_busy_guard_when_event_log_fails(self):
        job = dict(id='operation', lab_id='', status='queued')
        self.store.state['operations'] = [job]
        with patch('app.lab_operations.remote', return_value={'exit_code': 0}), \
             patch.object(self.store, 'event', side_effect=OSError('log unavailable')), \
             patch.object(self.discovery, 'refresh'):
            self.operations.execute(job['id'], {}, {})
        self.assertEqual(job['status'], 'succeeded')
        self.assertEqual(self.operations.active, set())
        self.operations.guard()

    def test_failed_operation_storage_write_still_releases_guard(self):
        job = dict(id='operation', lab_id='', status='queued')
        self.store.state['operations'] = [job]
        with patch('app.lab_operations.remote') as remote, \
             patch.object(self.store, 'save', side_effect=OSError('disk unavailable')), \
             patch.object(self.store, 'event', side_effect=OSError('log unavailable')), \
             patch.object(self.discovery, 'refresh'):
            self.operations.execute(job['id'], {}, {})
        remote.assert_not_called()
        self.assertNotIn(job['status'], ('queued', 'running'))
        self.assertEqual(self.operations.active, set())

    def test_log_write_failure_is_reported_without_failing_successful_mutation(self):
        with patch('app.store.os.open', side_effect=OSError('private disk detail')):
            entry = self.store.event('fixture', 'Completed action')
        self.assertEqual(entry['action'], 'fixture')
        self.assertTrue(self.store.event_error)
        self.store.event('fixture.recovered', 'Logging recovered')
        self.assertFalse(self.store.event_error)
