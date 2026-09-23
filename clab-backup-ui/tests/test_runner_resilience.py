import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.lab_operations import RESTORE_BUSY
from app.runner import GIT_TIMEOUT, JOB_CAP, Runner, filename, protected_job_ids, trim_jobs, trim_jobs_per_lab
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

    # B-001: 'jobs' is bounded like 'operations' already is, and never drops a queued/running entry.
    def test_trim_jobs_caps_newest_first_storage_but_keeps_protected_older_entries(self):
        jobs = [dict(id=str(i), status='succeeded') for i in range(5)]
        jobs[3]['status'] = 'running'  # older than the newest-2 window, but must survive
        trimmed = trim_jobs(jobs, 2, lambda j: j['status'] in ('queued', 'running'), True)
        # Newest two (indices 0, 1) first, then the protected older survivor, in original order.
        self.assertEqual([j['id'] for j in trimmed], ['0', '1', '3'])

    def test_trim_jobs_caps_newest_last_storage_but_keeps_protected_older_entries(self):
        jobs = [dict(id=str(i), status='synced') for i in range(5)]
        jobs[1]['status'] = 'review_pending'  # older than the newest-2 window, but must survive
        trimmed = trim_jobs(jobs, 2, lambda j: j['status'] != 'synced', False)
        self.assertEqual([j['id'] for j in trimmed], ['1', '3', '4'])

    def test_trim_jobs_is_a_no_op_at_or_under_the_cap(self):
        jobs = [dict(id=str(i), status='succeeded') for i in range(3)]
        self.assertEqual(trim_jobs(jobs, 3, lambda j: False, True), jobs)
        self.assertIs(trim_jobs(jobs, 5, lambda j: False, True), jobs)

    # B-001 (risk review 2, item 2): 'jobs' is capped per lab_id, so one lab's own schedule never
    # evicts another lab's history.
    def test_trim_jobs_per_lab_keeps_each_labs_own_newest_window(self):
        jobs = ([dict(id=f'a{i}', lab_id='A', status='succeeded') for i in range(4)] +
                [dict(id=f'b{i}', lab_id='B', status='succeeded') for i in range(2)])
        # Interleave by recency (newest first overall): a3,b1,a2,b0,a1,a0 (a lab's own jobs stay in order).
        ordered = [jobs[3], jobs[5], jobs[2], jobs[4], jobs[1], jobs[0]]
        trimmed = trim_jobs_per_lab(ordered, 2, lambda j: False)
        # Each lab keeps only its own newest two, in their original relative order.
        self.assertEqual([j['id'] for j in trimmed], ['a3', 'b1', 'a2', 'b0'])

    def test_trim_jobs_per_lab_keeps_a_protected_entry_past_its_labs_own_window(self):
        jobs = [dict(id=str(i), lab_id='A', status='succeeded') for i in range(4)]
        jobs[3]['status'] = 'running'  # oldest of lab A, but must survive regardless of window
        trimmed = trim_jobs_per_lab(jobs, 2, lambda j: j['status'] == 'running')
        self.assertEqual([j['id'] for j in trimmed], ['0', '1', '3'])

    def test_protected_job_ids_covers_pending_git_saves_and_busy_or_interrupted_restores(self):
        busy_status = next(iter(RESTORE_BUSY))
        terminal_status = 'succeeded'  # not in RESTORE_BUSY and not 'interrupted'
        state = {
            'git_jobs': [dict(id='g1', status='export_pending', backup_job_id='b1'),   # pending: protect b1
                        dict(id='g2', status='synced', backup_job_id='b2')],           # not pending: b2 unprotected
            'restore_jobs': [dict(id='r1', status=busy_status, pre_backup_job_id='b3', post_backup_job_id=''),
                             dict(id='r2', status='interrupted', pre_backup_job_id='b4', post_backup_job_id='b4b'),
                             dict(id='r3', status=terminal_status, pre_backup_job_id='b5', post_backup_job_id='b5b')],
        }
        self.assertEqual(protected_job_ids(state), {'b1', 'b3', 'b4', 'b4b'})

    def test_submit_caps_stored_jobs_at_the_newest_and_keeps_downloadable_files(self):
        finished = []
        with patch('app.runner.JOB_CAP', 3):
            for _ in range(5):
                job = self.queue()
                self.execute(job)
                finished.append(job)
        stored_ids = [j['id'] for j in self.store.state['jobs']]
        self.assertEqual(len(self.store.state['jobs']), 3)
        # Newest-first storage: the three most recently submitted jobs survive.
        self.assertEqual(stored_ids, [finished[4]['id'], finished[3]['id'], finished[2]['id']])
        # The dropped jobs' backup files on disk are untouched; only the bookkeeping record went.
        self.assertEqual(self.artifact(finished[0]).read_text(encoding='utf8'), 'hostname fixture-router\n')
        durable = Store(self.tmp.name)
        self.assertEqual(len(durable.state['jobs']), 3)

    def test_stored_state_over_the_cap_is_trimmed_at_the_next_append_not_at_load(self):
        # Compatibility: a state saved before this cap existed can hold more than JOB_CAP jobs for
        # a lab; nothing shrinks it until the next append to that list (Store.__init__ never trims
        # on load, and a bare store.save() elsewhere never trims either).
        with patch('app.runner.JOB_CAP', 2):
            self.store.state['jobs'] = [dict(id=str(i), lab_id=self.lab['id'], status='succeeded') for i in range(4)]
            self.store.save()
            reloaded = Store(self.tmp.name)
            self.assertEqual(len(reloaded.state['jobs']), 4)
            job = self.queue()
            self.execute(job)
        self.assertEqual(len(self.store.state['jobs']), 2)

    # B-003: the scheduler thread is joined on close(), unlike before this fix.
    def test_close_joins_the_scheduler_thread(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        runner = Runner(Store(tmp.name))
        runner.start()
        thread = runner.scheduler
        self.assertTrue(thread.is_alive())
        runner.close()
        self.assertFalse(thread.is_alive())

    def test_close_without_start_does_not_raise(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        runner = Runner(Store(tmp.name))
        runner.close()  # never started; must not raise "cannot join thread before it is started"

    # B-004: the post-backup git commands share a bounded deadline with the ansible-playbook run.
    def test_git_commands_run_with_the_shared_bounded_timeout(self):
        job = self.queue()
        with patch('app.runner.subprocess.Popen', side_effect=self.ansible_result), \
             patch('app.runner.subprocess.run', return_value=SimpleNamespace(stdout='', returncode=0)) as git:
            self.runner.execute(job['id'], copy.deepcopy(self.lab), [copy.deepcopy(self.node)], 'backup')
        self.assertTrue(git.call_args_list)
        for call in git.call_args_list:
            self.assertEqual(call.kwargs.get('timeout'), GIT_TIMEOUT)

    def test_git_timeout_fails_the_history_step_without_hanging_the_job(self):
        job = self.queue()
        with patch('app.runner.subprocess.Popen', side_effect=self.ansible_result), \
             patch('app.runner.subprocess.run',
                   side_effect=subprocess.TimeoutExpired(cmd=['git', 'add', '--all'], timeout=GIT_TIMEOUT)):
            self.runner.execute(job['id'], copy.deepcopy(self.lab), [copy.deepcopy(self.node)], 'backup')
        saved = self.current(job)
        self.assertNotIn(saved['status'], ('queued', 'running'))
        self.assertIn('timed out', saved['message'])
        # The configuration capture itself is unaffected by the history step timing out.
        self.assertEqual(self.artifact(job).read_text(encoding='utf8'), 'hostname fixture-router\n')

    def test_git_timeout_clears_a_stale_lock_so_the_next_backups_git_step_succeeds(self):
        # Real git throughout (only the ansible-playbook launch is faked): a clean filter that
        # sleeps stands in for any stall while git holds .git/index.lock, exactly as a hung
        # process would (mirrors the risk review's git_lock.py reproducer through the real pipeline).
        original_popen = subprocess.Popen
        def local_popen(args, **kwargs):
            return self.ansible_result(args, **kwargs) if args[0] == 'ansible-playbook' else original_popen(args, **kwargs)
        latest = self.store.root/'backups'/self.lab['id']/'latest'
        job1 = self.queue()
        with patch('app.runner.subprocess.Popen', side_effect=local_popen):
            self.runner.execute(job1['id'], copy.deepcopy(self.lab), [copy.deepcopy(self.node)], 'backup')
        self.assertEqual(self.current(job1)['status'], 'succeeded')   # a real first commit exists
        (latest/'.git/info/attributes').write_text('*.cfg filter=slow\n')
        subprocess.run(['git', '-C', str(latest), 'config', 'filter.slow.clean', 'sleep 5; cat'], check=True)
        job2 = self.queue()
        with patch('app.runner.subprocess.Popen', side_effect=local_popen), patch('app.runner.GIT_TIMEOUT', 1):
            self.runner.execute(job2['id'], copy.deepcopy(self.lab), [copy.deepcopy(self.node)], 'backup')
        self.assertFalse((latest/'.git/index.lock').exists())   # the lock this timeout left is cleared
        saved2 = self.current(job2)
        self.assertIn('timed out', saved2['message'])
        self.assertIn('cleared', saved2['message'])
        (latest/'.git/info/attributes').write_text('')   # the stalling filter itself is not this test's subject
        job3 = self.queue()
        with patch('app.runner.subprocess.Popen', side_effect=local_popen):
            self.runner.execute(job3['id'], copy.deepcopy(self.lab), [copy.deepcopy(self.node)], 'backup')
        # Not blocked by anything job 2's timeout left behind: 'succeeded', not the 'partial'/git-commit-
        # failed outcome a leftover index.lock would cause (job 3 captures the same, unchanged
        # configuration as job 1, so there is nothing new to commit; a real HEAD still exists).
        self.assertEqual(self.current(job3)['status'], 'succeeded')
        count = subprocess.check_output(['git', '-C', str(latest), 'rev-list', '--count', 'HEAD'], text=True).strip()
        self.assertEqual(count, '1')

    # B-001 (risk review 2, item 2): the per-lab cap on 'jobs' means one lab's own schedule never
    # evicts another, unrelated lab's history.
    def test_submit_caps_are_per_lab_not_global(self):
        other = dict(id='other', name='other-lab', nodes=[self.node], profiles=[], defaults={},
                     interval=0, next_run=None)
        self.store.state['labs'].append(other)
        with patch('app.runner.node_available', return_value=True), patch.object(self.runner.pool, 'submit'):
            other_job = self.runner.submit(other['id'])
        with self.store.lock:
            next(j for j in self.store.state['jobs'] if j['id'] == other_job['id'])['status'] = 'succeeded'
        with patch('app.runner.JOB_CAP', 2):
            for _ in range(4):
                job = self.queue(); self.execute(job)
        ids = [j['id'] for j in self.store.state['jobs']]
        self.assertIn(other_job['id'], ids, "another lab's only job must survive this lab's own cap")
        self.assertEqual(sum(j['lab_id'] == self.lab['id'] for j in self.store.state['jobs']), 2)
