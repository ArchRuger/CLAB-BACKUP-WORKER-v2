import base64
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
import zipfile

from app import __version__
from app.git_progress import GitProgress, captured_snapshot, decoded_snapshot, pending_progress, PROTOCOL
from app.store import Store
import test_discovery as discovery_tests


class GitProgressTests(unittest.TestCase):
    setUp_base = discovery_tests.DiscoveryTests.setUp
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host

    def setUp(self):
        self.setUp_base()
        self.progress = self.app.state.git_progress
        self.host(); self.store.state['host']['fingerprint'] = 'SHA256:fixture'
        self.lab = self.register(); self.url = '/api/labs/' + self.lab['id'] + '/git'
        self.repo = dict(id='bens-lab', label='Bens lab', owner='ben', path='/home/ben/labs/bgp',
                         remote='origin', branch='main', prefix='', revision='binding-1')
        self.sent = []; self.snapshots = {}; self.publish_error = ''; self.push_error = ''
        self.helper = patch('app.git_progress.remote_git', side_effect=self.remote).start()
        self.addCleanup(patch.stopall)
        self.dispatch = patch.object(self.progress.pool, 'submit').start()
        self.names = [n['name'] for n in self.store.lab(self.lab['id'])['nodes']]
        response = self.client.put(self.url, json=dict(binding_id=self.repo['id'], node_names=self.names))
        self.assertEqual(response.status_code, 200, response.text)

    def tearDown(self):
        self.app.state.operations.close()
        discovery_tests.DiscoveryTests.tearDown(self)

    def remote(self, host, request, stopping=None):
        self.sent.append(copy.deepcopy(request))
        mode = request['mode']
        if mode == 'list': return dict(protocol=PROTOCOL, version=__version__, repositories=[self.repo])
        if mode == 'status': return dict(repository=self.repo, ready=True, head='a'*40, baseline_revision='', latest_manifest=None)
        if mode == 'publish':
            if self.publish_error: raise ValueError(self.publish_error)
            self.snapshots[request['operation_id']] = copy.deepcopy(request['snapshot'])
            return dict(status='synced' if request['push'] else 'committed', commit='b'*40,
                        pushed=request['push'], changed_files=list(request['snapshot']['files']), snapshot_path=request['target'])
        if mode == 'push':
            if self.push_error: raise ValueError(self.push_error)
            return dict(status='synced', commit='b'*40, pushed=True, changed_files=[], snapshot_path='latest')
        if mode == 'read-version': return {'snapshot': next(iter(self.snapshots.values()))}
        if mode == 'history': return dict(commits=[dict(commit='b'*40, message='Saved', time=1)], versions=[dict(name='latest', path='latest', commit='b'*40)])
        if mode == 'compare': return {'files': [dict(name='r1.cfg', status='added', before='', after='hostname r1\n')]}
        if mode == 'update': return {'updated': True}
        raise AssertionError(mode)

    def capture(self, lab_id=None, **kwargs):
        lab_id = lab_id or self.lab['id']; lab = self.store.lab(lab_id)
        job_id = uuid.uuid4().hex
        folder = self.store.root/'backups'/lab_id/'history'/job_id
        folder.mkdir(parents=True)
        nodes = []
        for index, node in enumerate(lab['nodes']):
            if kwargs.get('node_names') and node['name'] not in kwargs['node_names']: continue
            name = f'node-{index}.cfg'
            (folder/name).write_text('hostname router-' + str(index) + '\n', encoding='utf-8')
            nodes.append(dict(name=node['name'], status='succeeded', file=name, platform=node['platform'], short_name='r'+str(index+1)))
        job = dict(id=job_id, lab_id=lab_id, lab_name=lab['name'], operation='backup', status='succeeded',
                   created='2026-09-11T10:00:00+00:00', finished='2026-09-11T10:01:00+00:00', nodes=nodes)
        if kwargs.get('progress_context'): job['progress_context'] = copy.deepcopy(kwargs['progress_context'])
        if kwargs.get('progress_id'): job['progress_id'] = kwargs['progress_id']
        self.store.state['jobs'].insert(0, job); self.store.save()
        return copy.deepcopy(job)

    def save(self, **fields):
        data = dict(request_id=uuid.uuid4().hex, target='latest', push=True)
        data.update(fields)
        result = self.client.post(self.url+'/save', json=data)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json(), data

    def run_save(self, job):
        with patch.object(self.app.state.runner, 'submit', side_effect=self.capture) as submit:
            self.progress.execute(job['id'])
        return self.client.get('/api/git/jobs/'+job['id']).json(), submit

    def test_fresh_save_uses_complete_capture_and_persists_provenance(self):
        job, _ = self.save()
        outcome, submit = self.run_save(job)
        self.assertEqual(outcome['status'], 'synced')
        self.assertTrue(outcome['pushed'])
        self.assertEqual(submit.call_args.kwargs['node_names'], self.names)
        request = next(r for r in self.sent if r['mode'] == 'publish')
        self.assertEqual(request['snapshot']['manifest']['topology_provenance'], 'captured')
        self.assertEqual(request['snapshot']['manifest']['node_names'], sorted(self.names))
        self.assertNotIn('host-secret', json.dumps(request))
        self.assertEqual(request['expected_head'], 'a'*40)
        saved = Store(self.tmp.name)
        self.assertEqual(saved.state['git_jobs'][0]['commit'], 'b'*40)
        public = self.client.get('/api/state').json()
        self.assertNotIn('snapshot_digest', public['git_jobs'][0])
        self.assertNotIn('hostname router-', json.dumps(public))

    def test_idempotent_requests_reject_changed_intent(self):
        job, data = self.save()
        again = self.client.post(self.url+'/save', json=data)
        self.assertEqual(again.json()['id'], job['id'])
        self.assertEqual(self.dispatch.call_count, 1)
        data['push'] = False
        self.assertEqual(self.client.post(self.url+'/save', json=data).status_code, 409)

    def test_partial_capture_keeps_git_untouched(self):
        backup = self.capture(); self.store.state['jobs'][0]['status'] = 'partial'
        self.store.state['jobs'][0]['nodes'][0]['status'] = 'failed'
        job, _ = self.save()
        with patch.object(self.app.state.runner, 'submit', return_value=backup): self.progress.execute(job['id'])
        outcome = self.client.get('/api/git/jobs/'+job['id']).json()
        self.assertEqual(outcome['status'], 'capture_incomplete')
        self.assertFalse(any(r['mode'] == 'publish' for r in self.sent))

    def test_internal_git_failure_does_not_invalidate_good_artifacts(self):
        backup = self.capture(); self.store.state['jobs'][0]['status'] = 'partial'
        self.store.state['jobs'][0]['message'] = 'Internal Git commit failed'
        result = captured_snapshot(self.store, self.store.state['jobs'][0])
        self.assertEqual(len(result['files']), 2)
        self.assertEqual(result['manifest']['topology_provenance'], 'unknown')
        self.assertIsNone(result['manifest']['topology_digest'])
        job, _ = self.save(backup_job_id=backup['id'])
        outcome, submit = self.run_save(job)
        self.assertEqual(outcome['status'], 'synced'); submit.assert_not_called()

    def test_missing_file_stops_export_and_size_and_hash_checks(self):
        backup = self.capture()
        from app.downloads import stored_path
        stored_path(self.store, backup, backup['nodes'][0]).unlink()
        with self.assertRaisesRegex(ValueError, 'missing'): captured_snapshot(self.store, backup)
        backup = self.capture(); snapshot = captured_snapshot(self.store, backup)
        snapshot['files'][next(iter(snapshot['files']))] = base64.b64encode(b'tampered').decode()
        with self.assertRaisesRegex(ValueError, 'integrity'): decoded_snapshot({'snapshot': snapshot})

    def test_local_commit_and_push_retry_do_not_recapture_or_republish(self):
        job, _ = self.save(push=False)
        outcome, _ = self.run_save(job)
        self.assertEqual(outcome['status'], 'committed')
        self.push_error = 'Network unavailable'
        self.assertEqual(self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': True}).status_code, 200)
        outcome, submit = self.run_save(job)
        self.assertEqual(outcome['status'], 'push_pending'); submit.assert_not_called()
        self.push_error = ''
        self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': True})
        outcome, submit = self.run_save(job)
        self.assertEqual(outcome['status'], 'synced'); submit.assert_not_called()
        self.assertEqual(sum(r['mode'] == 'publish' for r in self.sent), 1)

    def test_lost_publication_reply_replays_exact_body_then_pushes(self):
        job, _ = self.save(push=False)
        self.publish_error = 'Reply lost'
        outcome, _ = self.run_save(job)
        self.assertEqual(outcome['status'], 'export_pending')
        first = next(r for r in self.sent if r['mode'] == 'publish')
        self.publish_error = ''
        self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': True})
        outcome, submit = self.run_save(job); submit.assert_not_called()
        published = [r for r in self.sent if r['mode'] == 'publish']
        self.assertEqual(first, published[-1])
        self.assertEqual(outcome['status'], 'synced')

    def test_save_and_push_with_lost_reply_can_retry_export_locally(self):
        job, _ = self.save(push=True)
        first_reply = True
        original_remote = self.remote

        def lose_publication_reply(host, request, stopping=None):
            nonlocal first_reply
            result = original_remote(host, request, stopping)
            if request['mode'] == 'publish' and first_reply:
                first_reply = False
                raise ValueError('Reply lost after the local commit was saved')
            return result

        with patch('app.git_progress.remote_git', side_effect=lose_publication_reply):
            outcome, submit = self.run_save(job)
            self.assertEqual(outcome['status'], 'export_pending')
            self.assertEqual(submit.call_count, 1)
            self.assertIn(job['id'], self.snapshots)
            first = next(r for r in self.sent if r['mode'] == 'publish')
            self.assertFalse(first['push'])
            response = self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': False})
            self.assertEqual(response.status_code, 200, response.text)
            outcome, submit = self.run_save(job)

        submit.assert_not_called()
        self.assertEqual(outcome['status'], 'committed')
        self.assertFalse(outcome['pushed'])
        self.assertEqual(first, [r for r in self.sent if r['mode'] == 'publish'][-1])
        self.assertFalse(any(r['mode'] == 'push' for r in self.sent))

    def test_child_capture_survives_failed_parent_link_write_and_retries(self):
        job, _ = self.save(push=False)
        persist = self.store.save
        failed = False

        def fail_first_parent_link():
            nonlocal failed
            parent = self.progress.get_job(job['id'])
            if parent.get('backup_job_id') and not failed:
                failed = True
                raise OSError('Interrupted parent backup-ID write')
            persist()

        with patch.object(self.store, 'save', side_effect=fail_first_parent_link):
            outcome, submit = self.run_save(job)
        self.assertTrue(failed)
        self.assertEqual(submit.call_count, 1)
        child = next(b for b in self.store.state['jobs'] if b.get('progress_id') == job['id'])
        self.assertEqual(outcome['backup_job_id'], child['id'])
        self.assertEqual(outcome['status'], 'export_pending')
        self.assertTrue(pending_progress(self.store.state))
        self.assertFalse(any(r['mode'] == 'publish' for r in self.sent))
        loaded = Store(self.tmp.name)
        self.assertEqual(loaded.state['git_jobs'][0]['backup_job_id'], child['id'])
        self.assertTrue(pending_progress(loaded.state))

        response = self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': False})
        self.assertEqual(response.status_code, 200, response.text)
        outcome, submit = self.run_save(job)
        submit.assert_not_called()
        self.assertEqual(outcome['status'], 'committed')
        exported = next(r for r in self.sent if r['mode'] == 'publish')
        self.assertEqual(exported['snapshot']['manifest']['backup_job_id'], child['id'])

    def test_restart_recovers_child_from_legacy_failed_parent_without_recapture(self):
        job, _ = self.save(push=False)
        child = self.capture(progress_id=job['id'], node_names=self.names,
                             progress_context=self.progress.get_job(job['id'])['capture_context'])
        self.progress.update(job['id'], status='failed', backup_job_id='')
        loaded = Store(self.tmp.name)
        restarted = GitProgress(loaded, self.app.state.runner)
        try:
            restored = restarted.get_job(job['id'])
            self.assertEqual(restored['status'], 'interrupted')
            self.assertEqual(restored['backup_job_id'], child['id'])
            self.assertTrue(pending_progress(loaded.state))
            restarted.update(job['id'], status='queued', retry=True, retry_push=False)
            with patch.object(self.app.state.runner, 'submit') as submit:
                restarted.execute(job['id'])
            submit.assert_not_called()
            self.assertEqual(restored['status'], 'committed')
            exported = next(r for r in self.sent if r['mode'] == 'publish')
            self.assertEqual(exported['snapshot']['manifest']['backup_job_id'], child['id'])
        finally:
            restarted.close()

    def test_verified_push_reconciles_only_named_ancestors_of_same_binding(self):
        ancestor, _ = self.save(push=False)
        self.run_save(ancestor)
        reference = self.progress.get_job(ancestor['id'])
        foreign = {**copy.deepcopy(reference), 'id': uuid.uuid4().hex,
                   'binding_digest': 'different-binding', 'status': 'committed'}
        dismissed = {**copy.deepcopy(reference), 'id': uuid.uuid4().hex, 'status': 'dismissed'}
        unverified = {**copy.deepcopy(reference), 'id': uuid.uuid4().hex, 'status': 'committed'}
        self.store.state['git_jobs'].extend([foreign, dismissed, unverified])
        self.store.save()
        newest, _ = self.save(push=True)
        original_remote = self.remote

        def verify_ancestor_ids(host, request, stopping=None):
            result = original_remote(host, request, stopping)
            if request['mode'] == 'push':
                result['synced_operations'] = [ancestor['id'], foreign['id'], dismissed['id'], newest['id']]
            return result

        with patch('app.git_progress.remote_git', side_effect=verify_ancestor_ids):
            outcome, _ = self.run_save(newest)
        self.assertEqual(outcome['status'], 'synced')
        self.assertEqual(reference['status'], 'synced')
        self.assertTrue(reference['pushed'])
        self.assertEqual(foreign['status'], 'committed')
        self.assertFalse(foreign['pushed'])
        self.assertEqual(dismissed['status'], 'dismissed')
        self.assertEqual(unverified['status'], 'committed')
        self.assertFalse(unverified['pushed'])
        durable = {j['id']: j for j in Store(self.tmp.name).state['git_jobs']}
        self.assertEqual(durable[ancestor['id']]['status'], 'synced')
        self.assertEqual(durable[foreign['id']]['status'], 'committed')
        self.assertEqual(durable[unverified['id']]['status'], 'committed')

    def test_review_before_push_and_diff_are_explicit(self):
        response = self.client.put(self.url, json=dict(binding_id=self.repo['id'], node_names=self.names, review_before_push=True))
        self.assertEqual(response.status_code, 200)
        job, _ = self.save(); outcome, _ = self.run_save(job)
        self.assertEqual(outcome['status'], 'review_pending')
        self.assertFalse(next(r for r in self.sent if r['mode'] == 'publish')['push'])
        diff = self.client.post(self.url+'/compare', json={'job_id': job['id']})
        self.assertEqual(diff.status_code, 200, diff.text)
        self.assertEqual(diff.json()['files'][0]['status'], 'added')

    def test_baseline_requires_complete_selected_capture_and_conditions(self):
        response = self.client.post(self.url+'/save', json=dict(request_id=uuid.uuid4().hex, target='baseline'))
        self.assertEqual(response.status_code, 400)
        backup = self.capture()
        job, _ = self.save(target='baseline', backup_job_id=backup['id'], replace_baseline=True, expected_baseline='c'*64)
        outcome, submit = self.run_save(job); submit.assert_not_called()
        self.assertEqual(outcome['status'], 'synced')
        request = next(r for r in self.sent if r['mode'] == 'publish')
        self.assertTrue(request['replace_baseline']); self.assertEqual(request['expected_baseline'], 'c'*64)

    def test_pending_guards_and_explicit_dismissal(self):
        job, _ = self.save(push=False); self.run_save(job)
        self.assertTrue(pending_progress(self.store.state))
        self.assertEqual(self.client.post('/api/manager/reset', json={'confirmation': 'RESET'}).status_code, 409)
        self.assertEqual(self.client.post(self.url+'/unlink', json={}).status_code, 409)
        self.assertEqual(self.client.request('DELETE', '/api/labs/'+self.lab['id'], json={'name': self.lab['name']}).status_code, 409)
        self.assertEqual(self.client.post('/api/git/jobs/'+job['id']+'/dismiss', json={'acknowledge': False}).status_code, 400)
        self.assertEqual(self.client.post('/api/git/jobs/'+job['id']+'/dismiss', json={'acknowledge': True}).status_code, 200)
        self.assertFalse(pending_progress(self.store.state))
        self.assertTrue((self.store.root/'backups'/self.lab['id']/'history').exists())
        self.assertEqual(self.client.post(self.url+'/unlink', json={}).status_code, 200)

    def test_pending_host_password_rotation_allowed_identity_change_blocked(self):
        job, _ = self.save(push=False); self.run_save(job)
        settings = dict(address='127.0.0.1', port=22, username='fixture', password='rotated', enabled=True)
        self.assertEqual(self.client.put('/api/host', json=settings).status_code, 200)
        settings['address'] = '192.0.2.44'
        self.assertEqual(self.client.put('/api/host', json=settings).status_code, 409)

    def test_restart_retains_capture_for_retry(self):
        job, _ = self.save(); self.publish_error = 'Unavailable'; self.run_save(job)
        self.progress.update(job['id'], status='exporting')
        loaded = Store(self.tmp.name); restarted = GitProgress(loaded, self.app.state.runner)
        try:
            restored = loaded.state['git_jobs'][0]
            self.assertEqual(restored['status'], 'interrupted')
            self.assertTrue(restored['backup_job_id']); self.assertTrue(restored['snapshot_digest'])
        finally: restarted.close()

    def test_version_view_download_and_path_validation(self):
        job, _ = self.save(); self.run_save(job)
        data = dict(commit='b'*40, path='latest')
        response = self.client.post(self.url+'/version', json=data)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['restore_supported'])
        response = self.client.post(self.url+'/version/download', json=data)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertIn('manifest.json', archive.namelist())
            self.assertEqual(len(archive.namelist()), 3)
        for path in ('../outside', '.git/config', 'latest/../../escape', 'checkpoints/../../x'):
            self.assertEqual(self.client.post(self.url+'/version', json={**data, 'path': path}).status_code, 400)

    def test_active_save_blocks_mutations_and_capture_can_ignore_own_reservation(self):
        job, _ = self.save()
        self.assertEqual(self.client.post(self.url+'/unlink', json={}).status_code, 409)
        self.assertEqual(self.client.put('/api/host', json=dict(address='127.0.0.1', username='fixture', password='new')).status_code, 409)
        with patch('app.runner.node_available', return_value=True), patch.object(self.app.state.runner.pool, 'submit'):
            for node in self.store.lab(self.lab['id'])['nodes']:
                node.update(username='device', password='fixture')
            with self.assertRaisesRegex(ValueError, 'operation'): self.app.state.runner.submit(self.lab['id'])
            child = self.app.state.runner.submit(self.lab['id'], node_names=self.names, progress_id=job['id'], progress_context={'node_names': self.names})
            self.assertEqual(child['progress_id'], job['id'])
            self.assertEqual(child['progress_context']['node_names'], self.names)

    def test_failed_request_persistence_does_not_dispatch(self):
        before = len(self.store.state['git_jobs'])
        with patch.object(self.store, 'save', side_effect=OSError('disk')):
            response = self.client.post(self.url+'/save', json=dict(request_id=uuid.uuid4().hex))
            self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.store.state['git_jobs']), before)
        self.dispatch.assert_not_called()

    def test_persistent_worker_write_failure_can_be_retried_after_storage_recovers(self):
        backup = self.capture()
        job, _ = self.save(backup_job_id=backup['id'])
        with patch.object(self.store, 'save', side_effect=OSError('disk unavailable')):
            self.progress.execute(job['id'])
        current = self.progress.get_job(job['id'])
        self.assertNotIn(current['status'], ('queued', 'capturing', 'exporting', 'pushing'))
        self.assertEqual(current['backup_job_id'], backup['id'])
        retry = self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': True})
        self.assertEqual(retry.status_code, 200, retry.text)
        outcome, submit = self.run_save(job)
        submit.assert_not_called()
        self.assertEqual(outcome['status'], 'synced')

    def test_update_storage_failure_does_not_leave_active_marker(self):
        persist = self.store.save
        def writes_fail_after_reservation():
            if self.store.state['git_jobs'] and self.store.state['git_jobs'][-1]['status'] != 'exporting':
                raise OSError('disk unavailable')
            persist()
        with patch.object(self.store, 'save', side_effect=writes_fail_after_reservation):
            # HTTP failure is appropriate: the result was not durably recorded.
            with self.assertRaises(OSError): self.client.post(self.url+'/update', json={})
        self.assertEqual(self.store.state['git_jobs'][-1]['status'], 'dismissed')
        self.progress.idle()
