import base64
import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
import zipfile

from fastapi import HTTPException

from app import __version__
from app.git_progress import GitProgress, captured_snapshot, decoded_snapshot, pending_progress, PROTOCOL, version_label, resolve_version_path
from app.store import Store
import test_discovery as discovery_tests


class VersionPathTests(unittest.TestCase):
    """Labelling and path resolution for saved versions across folders."""
    def test_version_label_names_the_folder_and_state(self):
        self.assertEqual(version_label('reference/broken-01/latest'), 'reference/broken-01 · latest')
        self.assertEqual(version_label('work/baseline'), 'work · baseline')
        self.assertEqual(version_label('work/checkpoints/attempt-1'), 'work · checkpoint · attempt-1')
        self.assertEqual(version_label('latest'), 'latest')

    def test_resolve_version_path_handles_relative_and_full_paths(self):
        binding = {'repository': {'prefix': 'labs/work'}}
        self.assertEqual(resolve_version_path(binding, 'latest'), 'labs/work/latest')          # bare -> connected folder
        self.assertEqual(resolve_version_path(binding, 'checkpoints/try1'), 'labs/work/checkpoints/try1')
        self.assertEqual(resolve_version_path(binding, 'reference/broken/latest'), 'reference/broken/latest')  # full -> unchanged
        for bad in ('reference/notasnapshot', '../etc/latest', 'reference/.git/latest', ''):
            with self.assertRaises(HTTPException, msg=bad):
                resolve_version_path(binding, bad)


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

    def review_and_upload(self, job, expect=200):
        """The student's explicit decision after the review: the only way a save is uploaded."""
        response = self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': True, 'reviewed': True})
        self.assertEqual(response.status_code, expect, response.text)
        return self.run_save(job)

    def capture_with_restore(self, lab_id=None, **kwargs):
        """A capture that also carries a hierarchical restore-grade artifact per node."""
        lab_id = lab_id or self.lab['id']; lab = self.store.lab(lab_id)
        job_id = uuid.uuid4().hex
        folder = self.store.root/'backups'/lab_id/'history'/job_id
        folder.mkdir(parents=True)
        nodes = []
        for index, node in enumerate(lab['nodes']):
            if kwargs.get('node_names') and node['name'] not in kwargs['node_names']: continue
            (folder/f'n{index}.set').write_text(f'set system host-name h{index}\n', encoding='utf-8')
            (folder/f'n{index}.jcfg').write_text(f'system {{\n    host-name h{index};\n}}\n', encoding='utf-8')
            # A restore artifact only exists for Junos; the snapshot derives the format
            # from the platform, so pin a Junos platform for this fixture capture.
            nodes.append(dict(name=node['name'], status='succeeded', file=f'n{index}.set',
                              restore_file=f'n{index}.jcfg', restore_format='junos-hierarchical',
                              platform='juniper_cjunosevolved', short_name='r'+str(index+1)))
        job = dict(id=job_id, lab_id=lab_id, lab_name=lab['name'], operation='backup', status='succeeded',
                   created='2026-09-11T10:00:00+00:00', finished='2026-09-11T10:01:00+00:00', nodes=nodes)
        if kwargs.get('progress_context'): job['progress_context'] = copy.deepcopy(kwargs['progress_context'])
        if kwargs.get('progress_id'): job['progress_id'] = kwargs['progress_id']
        self.store.state['jobs'].insert(0, job); self.store.save()
        return copy.deepcopy(job)

    def test_restore_artifact_is_included_and_roundtrips(self):
        backup = self.capture_with_restore()
        snapshot = captured_snapshot(self.store, backup)
        manifest = snapshot['manifest']
        self.assertEqual(manifest['schema'], 2)
        self.assertEqual(manifest['restore_capable_nodes'], len(backup['nodes']))
        entry = manifest['files'][0]
        self.assertIn('restore_artifact', entry)
        self.assertTrue(entry['restore_capable'])
        self.assertEqual(entry['restore_format'], 'junos-hierarchical')
        self.assertIn(entry['restore_artifact'], snapshot['files'])
        # A full validation round-trip keeps every artifact and matches the manifest keys.
        _, files = decoded_snapshot({'snapshot': snapshot})
        self.assertIn(entry['restore_artifact'], files)
        self.assertIn('host-name', files[entry['restore_artifact']].decode('utf-8'))

    def test_legacy_capture_without_artifact_is_not_restore_capable(self):
        snapshot = captured_snapshot(self.store, self.capture())
        self.assertEqual(snapshot['manifest']['restore_capable_nodes'], 0)
        self.assertFalse(any(f.get('restore_capable') for f in snapshot['manifest']['files']))
        # decode still succeeds (backward compatible) and exposes no restore files.
        _, files = decoded_snapshot({'snapshot': snapshot})
        self.assertFalse(any(name.endswith('.jcfg') for name in files))

    def test_version_route_reports_restore_capability(self):
        job, _ = self.save()
        with patch.object(self.app.state.runner, 'submit', side_effect=self.capture_with_restore):
            self.progress.execute(job['id'])
        version = self.client.post(self.url+'/version', json=dict(commit='b'*40, path='latest'))
        self.assertEqual(version.status_code, 200, version.text)
        body = version.json()
        self.assertTrue(body['restore_supported'])
        self.assertTrue(body['restore_nodes'])

    def test_fresh_save_uses_complete_capture_and_persists_provenance(self):
        job, _ = self.save()
        outcome, submit = self.run_save(job)
        self.assertEqual(outcome['status'], 'review_pending')
        self.assertFalse(outcome['pushed'])
        self.assertFalse(any(r['mode'] == 'push' for r in self.sent))
        self.assertEqual(submit.call_args.kwargs['node_names'], self.names)
        outcome, again = self.review_and_upload(job); again.assert_not_called()
        self.assertEqual(outcome['status'], 'synced')
        self.assertTrue(outcome['pushed'])
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
        self.assertEqual(outcome['status'], 'review_pending'); submit.assert_not_called()
        outcome, submit = self.review_and_upload(job)
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
        outcome, submit = self.review_and_upload(job)
        self.assertEqual(outcome['status'], 'push_pending'); submit.assert_not_called()
        self.push_error = ''
        # The review is recorded with the first upload attempt: repeating a failed upload needs no second one.
        self.assertEqual(self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': True}).status_code, 200)
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
        # Nothing was committed yet, so there is nothing to review: the retry saves on the VM and waits.
        self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': True})
        outcome, submit = self.run_save(job); submit.assert_not_called()
        published = [r for r in self.sent if r['mode'] == 'publish']
        self.assertEqual(first, published[-1])
        self.assertEqual(outcome['status'], 'review_pending')
        self.assertFalse(any(r['mode'] == 'push' for r in self.sent))
        outcome, submit = self.review_and_upload(job); submit.assert_not_called()
        self.assertEqual(first, [r for r in self.sent if r['mode'] == 'publish'][-1])
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
        self.assertEqual(outcome['status'], 'review_pending')
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
            self.run_save(newest)
            outcome, _ = self.review_and_upload(newest)
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

    def test_the_review_is_mandatory_even_for_a_saved_opt_out_and_an_old_page(self):
        # A binding saved before the review became mandatory says False; a page loaded before the
        # release still sends False. Neither uploads a save without the review.
        with self.store.lock:
            self.store.lab(self.lab['id'])['git_binding']['review_before_push'] = False; self.store.save()
        job, _ = self.save(); outcome, _ = self.run_save(job)
        self.assertEqual(outcome['status'], 'review_pending')
        self.assertFalse(any(r['mode'] == 'push' for r in self.sent))
        for body in ({'push': True}, {'push': True, 'reviewed': False}, {}):
            refused = self.client.post('/api/git/jobs/'+job['id']+'/retry', json=body)
            self.assertEqual(refused.status_code, 409, refused.text)
            self.assertIn('Review the changes', refused.json()['detail'])
        current = self.client.get('/api/git/jobs/'+job['id']).json()
        self.assertEqual(current['status'], 'review_pending', 'a refused upload changes nothing and reports nothing as saved')
        self.assertFalse(current['pushed']); self.assertFalse(any(r['mode'] == 'push' for r in self.sent))
        self.dispatch.reset_mock()
        # Declining the review: the save stays on the VM, and keeping it there needs no review.
        self.assertEqual(self.client.post('/api/git/jobs/'+job['id']+'/retry', json={'push': False}).status_code, 200)
        outcome, _ = self.run_save(job)
        self.assertEqual(outcome['status'], 'review_pending'); self.assertFalse(any(r['mode'] == 'push' for r in self.sent))
        outcome, submit = self.review_and_upload(job); submit.assert_not_called()
        self.assertEqual(outcome['status'], 'synced'); self.assertTrue(outcome['reviewed'])
        self.assertEqual(sum(r['mode'] == 'push' for r in self.sent), 1)
        # A new binding records the review as on, whatever the request says.
        response = self.client.put(self.url, json=dict(binding_id=self.repo['id'], node_names=self.names, review_before_push=False))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIs(self.store.lab(self.lab['id'])['git_binding']['review_before_push'], True)

    def test_baseline_requires_complete_selected_capture_and_conditions(self):
        response = self.client.post(self.url+'/save', json=dict(request_id=uuid.uuid4().hex, target='baseline'))
        self.assertEqual(response.status_code, 400)
        backup = self.capture()
        job, _ = self.save(target='baseline', backup_job_id=backup['id'], replace_baseline=True, expected_baseline='c'*64)
        outcome, submit = self.run_save(job); submit.assert_not_called()
        self.assertEqual(outcome['status'], 'review_pending')
        outcome, submit = self.review_and_upload(job); submit.assert_not_called()
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
        self.assertEqual(outcome['status'], 'review_pending')
        outcome, submit = self.review_and_upload(job); submit.assert_not_called()
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


class GitPlacesTests(GitProgressTests):
    """Repository browsing, changing a lab's folder, new folders and connecting a repository by URL."""

    def remote(self, host, request, stopping=None):
        if not hasattr(self, 'registry'): self.registry = [self.repo]
        mode = request['mode']
        if mode == 'list':
            self.sent.append(copy.deepcopy(request))
            return dict(protocol=PROTOCOL, version=__version__, repositories=[dict(r) for r in self.registry])
        if mode == 'browse':
            self.sent.append(copy.deepcopy(request))
            repo = next(r for r in self.registry if r['id'] == request['binding_id'])
            return dict(repository=repo, head='a'*40, files=[dict(path='README.md', size=12), dict(path='bgp/latest/r1.cfg', size=30), dict(path='bgp/latest/manifest.json', size=200)],
                        truncated=False, saved={'latest': 1789128000, 'baseline': None, 'checkpoints': None},
                        folders=[dict(id=r['id'], label=r['label'], prefix=r['prefix']) for r in self.registry if r['path'] == repo['path']])
        if mode in ('register-prefix', 'connect'):
            self.sent.append(copy.deepcopy(request))
            if self.publish_error: raise ValueError(self.publish_error)
            prefix = request['prefix']
            existing = next((r for r in self.registry if r['prefix'] == prefix and (mode == 'register-prefix' or r.get('push_url') == request['url'])), None)
            if existing: return dict(existing)
            created = dict(self.repo, id=mode + '-' + (prefix or 'root'), prefix=prefix, revision='rev-' + (prefix or 'root'), label='Bens lab / ' + (prefix or 'root'))
            if mode == 'connect': created.update(push_url=request['url'], path='/home/ben/labs/' + request['url'].rsplit('/', 1)[-1].removesuffix('.git'), label=request['url'].rsplit('/', 1)[-1])
            self.registry.append(created)
            return dict(created)
        if mode == 'move':
            self.sent.append(copy.deepcopy(request))
            if self.publish_error: raise ValueError(self.publish_error)
            return dict(status='committed', commit='c'*40, pushed=False, changed_files=['latest/r1.cfg', 'bgp/latest/r1.cfg'], snapshot_path='bgp/latest', message='Saved in the VM repository; not pushed.')
        if mode == 'status':
            self.sent.append(copy.deepcopy(request))
            repo = next((r for r in self.registry if r['id'] == request.get('binding_id')), self.repo)
            return dict(repository=repo, ready=True, head='a'*40, baseline_revision='', latest_manifest=None)
        return super().remote(host, request, stopping)

    def test_tree_reports_committed_files_and_which_lab_owns_each_folder(self):
        response = self.client.get('/api/git/repositories/bens-lab/tree')
        self.assertEqual(response.status_code, 200, response.text)
        tree = response.json()
        self.assertEqual([f['path'] for f in tree['files']], ['README.md', 'bgp/latest/r1.cfg', 'bgp/latest/manifest.json'])
        self.assertEqual(tree['folders'][0]['lab'], dict(id=self.lab['id'], name=self.lab['name']))
        self.assertEqual(tree['saved']['latest'], 1789128000); self.assertEqual(tree['head'], 'a'*40)
        browse = next(r for r in self.sent if r['mode'] == 'browse')
        self.assertEqual((browse['binding_id'], browse['revision']), ('bens-lab', 'binding-1'))
        self.assertEqual(self.client.get('/api/git/repositories/missing/tree').status_code, 404)

    def test_new_folder_registers_a_sibling_prefix_after_validation(self):
        response = self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix='/courses/eth/'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['repository']['prefix'], 'courses/eth')
        request = next(r for r in self.sent if r['mode'] == 'register-prefix')
        self.assertEqual((request['prefix'], request['binding_id'], request['revision']), ('courses/eth', 'bens-lab', 'binding-1'))
        for bad in ('../eth', 'eth/.git', 'a b', 'x' * 501):
            self.assertIn(self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix=bad)).status_code, (400, 422), bad)
        self.assertEqual(len([r for r in self.sent if r['mode'] == 'register-prefix']), 1)
        catalog = self.client.get('/api/git/repositories').json()['repositories']
        self.assertIn('courses/eth', [r['prefix'] for r in catalog])

    def test_changing_the_folder_rebinds_the_lab_and_moves_files_without_recapturing(self):
        self.assertEqual(self.client.post(self.url + '/destination', json=dict(prefix='')).status_code, 409)
        response = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        self.assertEqual(response.status_code, 200, response.text)
        binding = self.store.lab(self.lab['id'])['git_binding']
        self.assertEqual(binding['binding_id'], 'register-prefix-bgp'); self.assertEqual(binding['repository']['prefix'], 'bgp')
        self.assertEqual(binding['node_names'], self.names)
        job = response.json()['job']
        self.assertEqual(job['target'], 'move'); self.assertEqual(job['status'], 'queued')
        with patch.object(self.app.state.runner, 'submit', side_effect=AssertionError('a move never captures devices')):
            self.progress.execute(job['id'])
        outcome = self.client.get('/api/git/jobs/' + job['id']).json()
        self.assertEqual(outcome['status'], 'synced', outcome); self.assertEqual(outcome['commit'], 'b'*40)
        move = next(r for r in self.sent if r['mode'] == 'move')
        self.assertEqual((move['source_prefix'], move['expected_head'], move['binding_id'], move['push']), ('', 'a'*40, 'register-prefix-bgp', False))
        self.assertTrue(next(r for r in self.sent if r['mode'] == 'register-prefix')['retire'])
        self.assertEqual(move['message'], 'Move ' + self.lab['name'] + ' progress to bgp/')
        self.assertFalse([r for r in self.sent if r['mode'] == 'publish'])
        self.assertEqual(next(r for r in self.sent if r['mode'] == 'push')['operation_id'], job['id'])
        again = self.client.post(self.url + '/destination', json=dict(prefix='bgp'))
        self.assertEqual(again.status_code, 409); self.assertIn('already saves', again.text)
        self.assertNotIn('binding_digest', json.dumps(self.client.get('/api/state').json()))

    def test_a_pending_save_blocks_folder_changes_and_moves_stay_recoverable(self):
        job, _ = self.save()
        self.assertEqual(self.client.post(self.url + '/destination', json=dict(prefix='bgp')).status_code, 409)
        self.progress.update(job['id'], status='synced', pushed=True)  # the save finished; nothing pending
        self.publish_error = 'The repository changed since it was selected. Refresh status and retry the move.'
        response = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        self.assertEqual(response.status_code, 409, response.text)
        self.publish_error = ''
        response = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        self.assertEqual(response.status_code, 200, response.text)
        self.publish_error = 'The current folder has unsaved edits. Resolve them as the repository owner before moving.'
        self.progress.execute(response.json()['job']['id'])
        outcome = self.client.get('/api/git/jobs/' + response.json()['job']['id']).json()
        self.assertEqual(outcome['status'], 'export_pending' if outcome.get('backup_job_id') else 'failed', outcome)
        self.assertIn('unsaved edits', outcome['message'])

    def test_connecting_by_url_needs_the_exposure_acknowledgement_and_binds_the_lab(self):
        url = ' https://github.com/ben/Course-Labs '
        refused = self.client.post(self.url + '/connect', json=dict(url=url, prefix='bgp'))
        self.assertEqual(refused.status_code, 400); self.assertFalse([r for r in self.sent if r['mode'] == 'connect'])
        response = self.client.post(self.url + '/connect', json=dict(url=url, prefix='bgp', acknowledge=True))
        self.assertEqual(response.status_code, 200, response.text)
        sent = next(r for r in self.sent if r['mode'] == 'connect')
        self.assertEqual((sent['url'], sent['prefix']), ('https://github.com/ben/Course-Labs', 'bgp')); self.assertNotIn('binding_id', sent)
        binding = self.store.lab(self.lab['id'])['git_binding']
        self.assertEqual(binding['repository']['push_url'], 'https://github.com/ben/Course-Labs'); self.assertEqual(binding['node_names'], self.names)
        other = self.register(discovery_tests.YAML.replace(b'name: training', b'name: other-lab'))
        conflict = self.client.post('/api/labs/' + other['id'] + '/git/connect', json=dict(url=url, prefix='bgp', acknowledge=True))
        self.assertEqual(conflict.status_code, 409); self.assertIn('another lab', conflict.text)
        self.assertEqual(self.client.post(self.url + '/connect', json=dict(url='', prefix='', acknowledge=True)).status_code, 422)
        self.publish_error = 'The VM account is not signed in to GitHub.'
        failed = self.client.post(self.url + '/connect', json=dict(url='https://github.com/ben/Other', prefix='', acknowledge=True))
        self.assertEqual(failed.status_code, 409); self.assertIn('not signed in', failed.text)
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['repository']['push_url'], 'https://github.com/ben/Course-Labs')


# The subclass only adds scenarios; the inherited scenarios already run once above.
for _name in [n for n in dir(GitProgressTests) if n.startswith('test_')]:
    setattr(GitPlacesTests, _name, None)
