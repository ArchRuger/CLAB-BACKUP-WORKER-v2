import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.runner import Runner, filename
from app.store import Store


class RunnerResilienceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.node = dict(name='r1', platform='cisco_xrv9k', address='192.0.2.1', port=22,
                         username='fixture', password='device-fixture', enabled=True)
        self.lab = dict(id='lab', name='fixture', nodes=[self.node], profiles=[], defaults={},
                        interval=5, next_run=123)
        self.store.state['labs'] = [self.lab]
        self.store.save()
        self.runner = Runner(self.store)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.runner.close)

    def queue(self):
        with patch('app.runner.node_available', return_value=True), patch.object(self.runner.pool, 'submit') as dispatched:
            job = self.runner.submit(self.lab['id'])
            dispatched.assert_called_once()
        return job

    def ansible_result(self, args, **kwargs):
        self.assertEqual(args[0], 'ansible-playbook')
        path = Path(kwargs['env']['BACKUP_EVENT_FILE'])
        path.write_text(json.dumps(dict(host='node_0', status='ok', task='Capture config',
                                        stdout='hostname fixture-router\n')) + '\n', encoding='utf8')
        return SimpleNamespace(poll=lambda: 0, returncode=0)

    def execute(self, job):
        with patch('app.runner.subprocess.Popen', side_effect=self.ansible_result) as process, \
             patch('app.runner.subprocess.run', return_value=SimpleNamespace(stdout='', returncode=0)):
            self.runner.execute(job['id'], copy.deepcopy(self.lab), [copy.deepcopy(self.node)], 'backup')
        return process

    def current(self, job):
        return next(j for j in self.store.state['jobs'] if j['id'] == job['id'])

    def artifact(self, job):
        return self.store.root/'backups'/self.lab['id']/'history'/job['id']/filename(self.node)

    def test_unavailable_event_log_does_not_orphan_or_fail_capture(self):
        with patch.object(self.store, 'event', side_effect=OSError('Event file unavailable')):
            job = self.queue()
            process = self.execute(job)
        process.assert_called_once()
        self.assertEqual(self.current(job)['status'], 'succeeded')
        self.assertEqual(self.artifact(job).read_text(encoding='utf8'), 'hostname fixture-router\n')
        self.assertEqual(Store(self.tmp.name).state['jobs'][0]['status'], 'succeeded')

    def test_initial_state_write_failure_finishes_without_starting_device_process(self):
        job = self.queue()
        persist = self.store.save
        calls = 0

        def first_write_fails():
            nonlocal calls
            calls += 1
            if calls == 1: raise OSError('Sensitive internal storage diagnostic')
            persist()

        with patch.object(self.store, 'save', side_effect=first_write_fails):
            process = self.execute(job)
        process.assert_not_called()
        saved = self.current(job)
        self.assertEqual(saved['status'], 'interrupted')
        self.assertEqual(saved['nodes'][0]['status'], 'interrupted')
        self.assertNotIn('Sensitive', json.dumps(saved))
        self.assertEqual(Store(self.tmp.name).state['jobs'][0]['status'], 'interrupted')

    def test_persistent_initial_write_failure_unblocks_memory_and_restart_recovers(self):
        job = self.queue()
        with patch.object(self.store, 'save', side_effect=OSError('Persistent storage unavailable')):
            process = self.execute(job)
            self.assertEqual(self.current(job)['status'], 'interrupted')
            durable = json.loads(self.store.cipher.decrypt(self.store.path.read_bytes()))
            self.assertEqual(durable['jobs'][0]['status'], 'queued')
        process.assert_not_called()
        self.assertEqual(Store(self.tmp.name).state['jobs'][0]['status'], 'interrupted')

    def test_terminal_write_failure_retains_files_and_never_leaves_running_job(self):
        job = self.queue()
        persist = self.store.save

        def terminal_writes_fail():
            if self.current(job)['status'] not in ('queued', 'running'):
                raise OSError('Terminal result cannot be persisted')
            persist()

        with patch.object(self.store, 'save', side_effect=terminal_writes_fail):
            process = self.execute(job)
            self.assertEqual(self.current(job)['status'], 'interrupted')
            durable = json.loads(self.store.cipher.decrypt(self.store.path.read_bytes()))
            self.assertEqual(durable['jobs'][0]['status'], 'running')
        process.assert_called_once()
        self.assertEqual(self.artifact(job).read_text(encoding='utf8'), 'hostname fixture-router\n')
        self.assertEqual(Store(self.tmp.name).state['jobs'][0]['status'], 'interrupted')

    def test_queue_write_failure_rolls_back_job_schedule_and_dispatch(self):
        with patch('app.runner.node_available', return_value=True), \
             patch.object(self.runner.pool, 'submit') as dispatched, \
             patch.object(self.store, 'save', side_effect=OSError('Queue write failed')):
            with self.assertRaises(OSError): self.runner.submit(self.lab['id'])
        dispatched.assert_not_called()
        self.assertEqual(self.store.state['jobs'], [])
        self.assertEqual(self.lab['next_run'], 123)
        durable = Store(self.tmp.name)
        self.assertEqual(durable.state['jobs'], [])
        self.assertEqual(durable.state['labs'][0]['next_run'], 123)
