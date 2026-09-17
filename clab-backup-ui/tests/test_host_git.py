import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import uuid
from contextlib import redirect_stdout
from types import SimpleNamespace

from app import host_git
from app.host_git import GitRepository, checked_url, snapshot


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class HostGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.repo = self.base / 'repo'; self.repo.mkdir()
        self.remote = self.base / 'remote.git'; self.home = self.base / 'home'; self.home.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '0'}
        self.git = shutil.which('git')
        self.raw('init', '--bare', str(self.remote))
        self.raw('init', '-b', 'main'); self.raw('config', 'user.name', 'Fixture Ben'); self.raw('config', 'user.email', 'ben@example.invalid')
        self.raw('config', 'core.autocrlf', 'false')
        (self.repo / 'README.md').write_text('Existing lab\n')
        self.raw('add', 'README.md'); self.raw('commit', '-m', 'Initial lab')
        self.raw('remote', 'add', 'origin', str(self.remote)); self.raw('push', '-u', 'origin', 'main')
        self.binding = {'id': uuid.uuid4().hex, 'label': 'Ben BGP', 'owner': 'ben', 'path': str(self.repo), 'home': str(self.home),
                        'remote': 'origin', 'branch': 'main', 'prefix': '', 'push_url': str(self.remote), 'revision': 'a' * 64}
        self.worker = GitRepository(self.binding, git=self.git, allow_local=True, env=self.env)

    def raw(self, *args):
        result = subprocess.run([self.git, *args], cwd=self.repo, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stdout.decode().strip()

    def request(self, mode, **kwargs):
        return {'mode': mode, 'binding_id': self.binding['id'], 'revision': self.binding['revision'], **kwargs}

    def capture(self, text='router bgp 65001\n', **metadata):
        raw = text.encode(); name = 'PE1.cfg'
        return {'manifest': {'schema': 1, 'lab_id': 'bgp', 'lab_name': 'BGP', 'backup_job_id': uuid.uuid4().hex,
                             'captured_at': '2026-09-11T00:00:00Z', 'topology_digest': 'a' * 64, 'topology_provenance': 'captured',
                             'node_names': ['PE1'], 'excluded_nodes': [], 'files': [dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), node='PE1', platform='eos', format='running-config')], **metadata},
                'files': {name: base64.b64encode(raw).decode()}}

    def publish(self, capture=None, **options):
        req = self.request('publish', operation_id=uuid.uuid4().hex, expected_head=self.raw('rev-parse', 'HEAD'),
                           target='latest', push=False, snapshot=capture or self.capture())
        req.update(options)
        return req, self.worker.dispatch(req)

    def test_publish_push_unchanged_read_compare_and_restart(self):
        (self.repo / 'README.md').write_text('Unstaged user notes\n')
        req, result = self.publish(push=True)
        self.assertEqual(result['status'], 'synced', result)
        self.assertEqual(result['snapshot_path'], 'latest')
        self.assertEqual(self.raw('show', 'HEAD:README.md'), 'Existing lab')
        self.assertEqual(self.worker.dispatch(req)['commit'], result['commit'])
        _, same = self.publish(push=True)
        self.assertEqual(same['commit'], result['commit']); self.assertTrue(same['pushed'])
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD'), '2')
        version = self.worker.dispatch(self.request('read-version', commit=result['commit'], path='latest'))
        self.assertEqual(version['snapshot']['files'], req['snapshot']['files'])
        changes = self.worker.dispatch(self.request('compare', operation_id=req['operation_id']))
        self.assertEqual(changes['files'][0]['status'], 'added')
        self.assertEqual(changes['files'][0]['after'], 'router bgp 65001\n')
        restarted = GitRepository(self.binding, git=self.git, allow_local=True, env=self.env)
        self.assertEqual(restarted.dispatch(req)['commit'], result['commit'])
        self.assertEqual(len(restarted.dispatch(self.request('history'))['versions']), 1)

    def capture_schema2(self, text='router bgp 65001\n', restore='system {\n    host-name PE1;\n}\n'):
        """A schema-2 snapshot: a config file plus its hierarchical restore artifact."""
        raw = text.encode(); rr = restore.encode()
        return {'manifest': {'schema': 2, 'lab_id': 'bgp', 'lab_name': 'BGP', 'backup_job_id': uuid.uuid4().hex,
                             'captured_at': '2026-09-16T00:00:00Z', 'topology_digest': 'a' * 64, 'topology_provenance': 'captured',
                             'node_names': ['PE1'], 'excluded_nodes': [], 'restore_capable_nodes': 1,
                             'files': [dict(path='PE1.cfg', size=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                                            node='PE1', platform='juniper_cjunosevolved', format='junos-display-set',
                                            restore_artifact='PE1.jcfg', restore_size=len(rr), restore_sha256=hashlib.sha256(rr).hexdigest(),
                                            restore_format='junos-hierarchical', restore_capable=True)]},
                'files': {'PE1.cfg': base64.b64encode(raw).decode(), 'PE1.jcfg': base64.b64encode(rr).decode()}}

    def test_schema2_restore_artifact_is_published_and_read_back(self):
        req, result = self.publish(self.capture_schema2(), push=False)
        self.assertEqual(result['status'], 'committed', result)
        # Both the config and its restore artifact are committed in the checkout.
        self.assertEqual((self.repo / 'latest/PE1.jcfg').read_text(), 'system {\n    host-name PE1;\n}\n')
        self.assertIn('latest/PE1.jcfg', result['changed_files'])
        # read-version returns both files and the helper's own validation passed.
        version = self.worker.dispatch(self.request('read-version', commit=result['commit'], path='latest'))
        self.assertEqual(set(version['snapshot']['files']), {'PE1.cfg', 'PE1.jcfg'})
        self.assertEqual(version['snapshot']['manifest']['schema'], 2)

    def test_schema2_second_save_and_checkpoint_accept_the_folder_s_own_restore_artifacts(self):
        """Regression (found live on 1.28.0): the destination check listed only each manifest entry's `path`,
        so the `.jcfg` restore artifacts of the previous save looked like foreign files and every second
        save or checkpoint into a Junos folder was refused as "files outside its manager manifest"."""
        _, first = self.publish(self.capture_schema2(), push=False)
        self.assertEqual(first['status'], 'committed', first)
        _, second = self.publish(self.capture_schema2('router bgp 65002\n', 'system {\n    host-name PE1-v2;\n}\n'), push=False)
        self.assertEqual(second['status'], 'committed', second)
        self.assertEqual(sorted(second['changed_files']), ['latest/PE1.cfg', 'latest/PE1.jcfg', 'latest/manifest.json'])
        self.assertEqual((self.repo / 'latest/PE1.jcfg').read_text(), 'system {\n    host-name PE1-v2;\n}\n')
        _, checkpoint = self.publish(self.capture_schema2('router bgp 65002\n', 'system {\n    host-name PE1-v2;\n}\n'), target='checkpoint', checkpoint='after-fix', push=False)
        self.assertEqual(checkpoint['status'], 'committed', checkpoint)
        self.assertTrue((self.repo / 'checkpoints/after-fix/PE1.jcfg').exists())
        # A later capture without the artifact (schema 1) is not "removing a device": the stale artifact
        # leaves the folder with the manifest that no longer references it.
        _, downgraded = self.publish(self.capture('router bgp 65003\n'), push=False)
        self.assertEqual(downgraded['status'], 'committed', downgraded)
        self.assertFalse((self.repo / 'latest/PE1.jcfg').exists())
        self.assertIn('latest/PE1.jcfg', downgraded['changed_files'])
        _, again = self.publish(self.capture('router bgp 65004\n'), push=False)
        self.assertEqual(again['status'], 'committed', again)

    def test_schema2_rejects_a_missing_or_tampered_restore_artifact(self):
        capture = self.capture_schema2()
        capture['files'].pop('PE1.jcfg')  # manifest still references it
        with self.assertRaises(ValueError): snapshot(capture)
        capture = self.capture_schema2()
        capture['manifest']['files'][0]['restore_sha256'] = '0' * 64
        with self.assertRaises(ValueError): snapshot(capture)

    def test_baseline_does_not_rewind_latest_and_replace_is_conditional(self):
        self.publish(self.capture('latest\n'))
        _, base = self.publish(self.capture('baseline\n'), target='baseline')
        self.assertEqual(base['status'], 'committed', base)
        self.assertEqual((self.repo / 'latest/PE1.cfg').read_text(), 'latest\n')
        revision = self.worker.dispatch(self.request('status'))['baseline_revision']
        _, refused = self.publish(self.capture('new baseline\n'), target='baseline')
        self.assertEqual(refused['status'], 'needs_attention')
        _, replaced = self.publish(self.capture('new baseline\n'), target='baseline', replace_baseline=True, expected_baseline=revision)
        self.assertEqual(replaced['status'], 'committed', replaced)
        _, checkpoint = self.publish(target='checkpoint', checkpoint='peering-working')
        self.assertEqual(checkpoint['status'], 'committed', checkpoint)
        _, duplicate = self.publish(target='checkpoint', checkpoint='peering-working')
        self.assertEqual(duplicate['status'], 'needs_attention')

    def test_staged_work_blocked_then_same_operation_can_retry(self):
        (self.repo / 'notes.txt').write_text('personal\n'); self.raw('add', 'notes.txt')
        req, result = self.publish()
        self.assertEqual(result['status'], 'needs_attention'); self.assertFalse((self.repo / 'latest').exists())
        self.raw('reset', '--', 'notes.txt')
        result = self.worker.dispatch(req)
        self.assertEqual(result['status'], 'committed', result)
        self.assertFalse(self.raw('ls-tree', 'HEAD', 'notes.txt'))

    def test_missing_identity_fails_before_export_and_original_save_retries(self):
        self.raw('config', '--unset', 'user.name')
        self.raw('config', '--unset', 'user.email')
        self.raw('config', 'user.useConfigOnly', 'true')
        req, result = self.publish()
        self.assertEqual(result['status'], 'needs_attention')
        self.assertIn('commit identity', result['message'])
        self.assertFalse((self.repo / 'latest').exists())
        self.assertEqual(self.raw('diff', '--cached', '--name-only'), '')
        self.raw('config', 'user.name', 'Fixed Author')
        self.raw('config', 'user.email', 'fixed@example.invalid')
        retry = self.worker.dispatch(req)
        self.assertEqual(retry['status'], 'committed', retry)
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD'), '2')

    def test_push_preflight_does_not_publish_local_commit(self):
        self.publish()
        before = self.raw('ls-remote', 'origin', 'refs/heads/main')
        self.worker.check_push_access()
        self.assertEqual(before, self.raw('ls-remote', 'origin', 'refs/heads/main'))
        self.assertNotIn(self.raw('rev-parse', 'HEAD'), before)

    def test_registration_keeps_pending_revision_when_only_head_changed(self):
        self.binding['anchor'] = self.raw('rev-parse', 'HEAD')
        old = self.worker.registration()
        self.publish()
        self.binding['anchor'] = self.raw('rev-parse', 'HEAD')
        same = self.worker.registration(old)
        self.assertEqual(same['revision'], old['revision'])
        self.assertEqual(same['anchor'], old['anchor'])
        self.binding['branch'] = 'another-branch'
        changed = self.worker.registration(old)
        self.assertNotEqual(changed['revision'], old['revision'])

    def test_push_preflight_failure_has_actionable_message_without_git_stderr(self):
        with patch.object(self.worker, 'run', return_value=(128, b'sensitive credentials')):
            with self.assertRaisesRegex(ValueError, 'registered Linux owner') as error:
                self.worker.check_push_access()
        self.assertNotIn('sensitive', str(error.exception))

    def test_prewrite_retry_adopts_owner_committed_and_published_repair(self):
        (self.repo / 'notes.txt').write_text('Owner notes\n'); self.raw('add', 'notes.txt')
        req, result = self.publish()
        self.assertEqual(result['status'], 'needs_attention'); self.assertFalse((self.repo / 'latest').exists())
        journal = self.worker.load_journal(req['operation_id'])
        self.assertFalse(journal.get('parent')); self.assertFalse(journal.get('expected'))
        self.raw('commit', '-m', 'Finish owner work'); self.raw('push')
        repaired_head = self.raw('rev-parse', 'HEAD')
        self.assertNotEqual(repaired_head, req['expected_head'])
        retried = self.worker.dispatch(req)
        self.assertEqual(retried['status'], 'committed', retried)
        journal = self.worker.load_journal(req['operation_id'])
        self.assertEqual(journal['parent'], repaired_head)
        self.assertEqual(self.raw('show', 'HEAD:notes.txt'), 'Owner notes')
        self.assertEqual(json.loads((self.repo / 'latest/manifest.json').read_text())['backup_job_id'], req['snapshot']['manifest']['backup_job_id'])
        self.assertEqual(len(list((self.repo / '.git/clab-manager/snapshots').glob('*.json'))), 1)
        pushed = self.worker.dispatch(self.request('push', operation_id=req['operation_id']))
        self.assertEqual(pushed['status'], 'synced', pushed)

    def test_foreign_ancestors_never_pushed(self):
        (self.repo / 'personal.txt').write_text('foreign\n'); self.raw('add', 'personal.txt'); self.raw('commit', '-m', 'Unpublished personal work')
        _, result = self.publish(push=True)
        self.assertEqual(result['status'], 'needs_attention', result); self.assertIsNotNone(result['commit'])
        self.assertIn('outside manager saves', result['message'])
        remote = subprocess.check_output([self.git, '--git-dir', str(self.remote), 'rev-parse', 'main'], env=self.env).decode().strip()
        self.assertNotEqual(remote, result['commit'])

    def test_failed_push_is_retryable_without_new_commit(self):
        original = self.worker.remote_head
        with patch.object(self.worker, 'remote_head', side_effect=ValueError('Remote unavailable.')):
            req, failed = self.publish(push=True)
        self.assertEqual(failed['status'], 'needs_attention'); self.assertIsNotNone(failed['commit'])
        result = self.worker.dispatch(self.request('push', operation_id=req['operation_id']))
        self.assertEqual(result['status'], 'synced', result); self.assertEqual(result['commit'], failed['commit'])
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD'), '2')

    def test_interrupted_commit_recovers_and_refuses_changed_artifact(self):
        original = self.worker.run
        def stop(*args, **kwargs):
            if args[0] == 'commit': raise ValueError('Simulated signing failure.')
            return original(*args, **kwargs)
        with patch.object(self.worker, 'run', side_effect=stop): req, result = self.publish()
        self.assertEqual(result['status'], 'needs_attention'); self.assertTrue((self.repo / 'latest/PE1.cfg').exists())
        result = self.worker.dispatch(req)
        self.assertEqual(result['status'], 'committed', result)
        with patch.object(self.worker, 'run', side_effect=stop): req, result = self.publish(self.capture('new config\n'))
        (self.repo / 'latest/PE1.cfg').write_text('Owner edited this\n')
        result = self.worker.dispatch(req)
        self.assertEqual(result['status'], 'needs_attention'); self.assertIn('edited after saving', result['message'])
        self.assertEqual((self.repo / 'latest/PE1.cfg').read_text(), 'Owner edited this\n')

    def test_lost_commit_response_reconciles_journal(self):
        req, result = self.publish()
        journal = self.worker.load_journal(req['operation_id']); journal.update(commit=None, verified=False, status='needs_attention')
        self.worker.save_journal(journal)
        recovered = self.worker.dispatch(req)
        self.assertEqual(recovered['commit'], result['commit']); self.assertEqual(recovered['status'], 'committed')
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD'), '2')

    def test_dirty_managed_destination_unknown_files_and_binding_change_fail_closed(self):
        self.publish()
        (self.repo / 'latest/PE1.cfg').write_text('Owner change\n')
        _, result = self.publish(self.capture('desired\n'))
        self.assertEqual(result['status'], 'needs_attention'); self.assertEqual((self.repo / 'latest/PE1.cfg').read_text(), 'Owner change\n')
        req = self.request('status'); req['revision'] = 'b' * 64
        with self.assertRaises(ValueError): self.worker.dispatch(req)
        self.raw('remote', 'set-url', 'origin', str(self.base / 'other.git'))
        self.assertFalse(self.worker.dispatch(self.request('status'))['ready'])

    def test_snapshot_checksum_traversal_and_remote_tokens_rejected(self):
        capture = self.capture(); capture['manifest']['files'][0]['sha256'] = '0' * 64
        with self.assertRaises(ValueError): snapshot(capture)
        capture = self.capture(); capture['manifest']['files'][0]['path'] = '../README.md'
        with self.assertRaises(ValueError): snapshot(capture)
        for url in ('https://token@github.com/owner/repo', 'git@github.com:owner/repo', 'file:///tmp/repo', 'https://example.com/r?token=secret'):
            with self.assertRaises(ValueError): checked_url(url)
        self.assertEqual(checked_url('https://github.com/ben/lab.git'), 'https://github.com/ben/lab.git')

    def test_push_newest_marks_older_pending_save_synced(self):
        older, first = self.publish(self.capture('first\n'))
        newer, second = self.publish(self.capture('second\n'), push=True)
        self.assertEqual(second['status'], 'synced', second)
        self.assertIn(older['operation_id'], second['synced_operations'])
        self.assertTrue(self.worker.load_journal(older['operation_id'])['pushed'])
        retry = self.worker.dispatch(self.request('push', operation_id=older['operation_id']))
        self.assertTrue(retry['pushed']); self.assertEqual(retry['commit'], first['commit'])

    def test_remote_advance_blocks_push_and_update_is_fast_forward_only(self):
        # An independent checkout represents another editor advancing the remote.
        other = self.base / 'other'
        subprocess.check_call([self.git, 'clone', '-b', 'main', str(self.remote), str(other)], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def other_git(*args):
            return subprocess.check_output([self.git, '-c', 'user.name=Other', '-c', 'user.email=other@example.invalid', *args], cwd=other, env=self.env, stderr=subprocess.DEVNULL).decode().strip()
        (other / 'notes.txt').write_text('Remote edit\n'); other_git('add', 'notes.txt'); other_git('commit', '-m', 'Remote change'); other_git('push')
        head = self.raw('rev-parse', 'HEAD')
        result = self.worker.dispatch(self.request('update', expected_head=head))
        self.assertEqual(result['status'], 'updated'); self.assertTrue((self.repo / 'notes.txt').exists())
        req, local = self.publish(self.capture('local\n'))
        (other / 'notes.txt').write_text('Another remote edit\n'); other_git('add', 'notes.txt'); other_git('commit', '-m', 'Another remote change'); other_git('push')
        result = self.worker.dispatch(self.request('push', operation_id=req['operation_id']))
        self.assertEqual(result['status'], 'needs_attention'); self.assertIn('advanced or diverged', result['message'])
        with self.assertRaisesRegex(ValueError, 'diverged'):
            self.worker.dispatch(self.request('update', expected_head=local['commit']))
        self.assertEqual(self.raw('rev-parse', 'HEAD'), local['commit'])

    def test_removal_requires_review_and_unchanged_requires_valid_existing_files(self):
        capture = self.capture(); other = b'node two\n'
        capture['files']['PE2.cfg'] = base64.b64encode(other).decode()
        capture['manifest']['files'].append(dict(path='PE2.cfg', size=len(other), sha256=hashlib.sha256(other).hexdigest(), node='PE2', platform='eos', format='running-config'))
        capture['manifest']['node_names'].append('PE2')
        _, first = self.publish(capture)
        self.assertEqual(first['status'], 'committed', first)
        _, blocked = self.publish()
        self.assertEqual(blocked['status'], 'needs_attention'); self.assertTrue((self.repo / 'latest/PE2.cfg').exists())
        _, removed = self.publish(allow_removed=True)
        self.assertEqual(removed['status'], 'committed', removed); self.assertFalse((self.repo / 'latest/PE2.cfg').exists())
        (self.repo / 'latest/PE1.cfg').write_text('Manual committed config\n')
        self.raw('add', 'latest/PE1.cfg'); self.raw('commit', '-m', 'Manual snapshot change')
        _, result = self.publish()
        self.assertEqual(result['status'], 'needs_attention'); self.assertIn('manifest', result['message'])

    def test_git_clean_filter_cannot_silently_change_exported_bytes(self):
        (self.repo / '.gitattributes').write_text('latest/*.cfg text eol=lf\n')
        self.raw('add', '.gitattributes'); self.raw('commit', '-m', 'Text normalization policy'); self.raw('push')
        req, result = self.publish(self.capture('line one\r\nline two\r\n'), push=True)
        self.assertEqual(result['status'], 'needs_attention'); self.assertIn('filters changed', result['message'])
        self.assertIsNone(result['commit']); self.assertFalse(result['pushed'])
        self.assertTrue(self.worker.load_journal(req['operation_id'])['expected'])

    def test_manager_safe_long_and_underscore_filenames(self):
        capture = self.capture(); value = capture['files'].pop('PE1.cfg')
        long_name = '_' + 'n' * 110 + '.cfg'
        capture['files'][long_name] = value; capture['manifest']['files'][0]['path'] = long_name
        req, result = self.publish(capture)
        self.assertEqual(result['status'], 'committed', result)
        restored = self.worker.dispatch(self.request('read-version', commit=result['commit'], path='latest'))
        self.assertEqual(restored['snapshot']['files'][long_name], value)

    def test_unchanged_foreign_published_head_can_reconcile_without_push(self):
        self.publish(push=True)
        (self.repo / 'README.md').write_text('Owner updated notes\n')
        self.raw('add', 'README.md'); self.raw('commit', '-m', 'Owner notes'); self.raw('push')
        req, result = self.publish()
        self.assertEqual(result['status'], 'unchanged'); self.assertFalse(self.worker.load_journal(req['operation_id'])['verified'])
        original = self.worker.run
        def no_push(*args, **kwargs):
            self.assertNotEqual(args[0], 'push', 'Reconciliation must not issue a push for foreign history')
            return original(*args, **kwargs)
        with patch.object(self.worker, 'run', side_effect=no_push): result = self.worker.dispatch(self.request('push', operation_id=req['operation_id']))
        self.assertTrue(result['pushed']); self.assertEqual(result['status'], 'synced')

    def test_push_retry_revalidates_commit_after_interrupted_verification(self):
        req, result = self.publish()
        journal = self.worker.load_journal(req['operation_id']); journal.update(verified=False, status='needs_attention')
        self.worker.save_journal(journal)
        retried = self.worker.dispatch(self.request('push', operation_id=req['operation_id']))
        self.assertEqual(retried['status'], 'synced', retried); self.assertEqual(retried['commit'], result['commit'])
        req, result = self.publish(self.capture('next\n'))
        journal = self.worker.load_journal(req['operation_id']); journal.update(verified=False, status='needs_attention')
        journal['expected']['latest/PE1.cfg'] = base64.b64encode(b'Unapproved tree\n').decode()
        self.worker.save_journal(journal)
        refused = self.worker.dispatch(self.request('push', operation_id=req['operation_id']))
        self.assertEqual(refused['status'], 'needs_attention'); self.assertFalse(refused['pushed'])

    def test_unchanged_comparison_does_not_repeat_previous_commit_changes(self):
        first, saved = self.publish()
        changes = self.worker.dispatch(self.request('compare', operation_id=first['operation_id']))
        self.assertEqual(len(changes['files']), 1)
        unchanged, same = self.publish()
        self.assertEqual(same['commit'], saved['commit']); self.assertEqual(same['status'], 'unchanged')
        result = self.worker.dispatch(self.request('compare', operation_id=unchanged['operation_id']))
        self.assertEqual(result, {'files': []})


class HostGitProductionDispatchTests(unittest.TestCase):
    def setUp(self):
        self.binding = dict(id='a' * 32, revision='b' * 64, label='Ben lab', owner='ben', uid=1001, gid=1001,
                            home='/home/ben', path='/home/ben/lab', remote='origin', push_url='https://example.invalid/ben/lab',
                            branch='main', prefix='', anchor='c' * 40)

    def invoke(self, request, drop, construct):
        stdin = SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode()))
        output = io.StringIO()
        with patch.object(host_git, 'os', SimpleNamespace(name='posix', geteuid=lambda: 0)), \
             patch.object(host_git.sys, 'argv', ['host_git.py']), patch.object(host_git.sys, 'stdin', stdin), \
             patch.object(host_git, 'root_file'), patch.object(host_git, 'load_registry', return_value={'repositories': [self.binding]}), \
             patch.object(host_git, 'drop_owner', side_effect=drop), patch.object(host_git, 'GitRepository', side_effect=construct), \
             redirect_stdout(output):
            host_git.main()
        return json.loads(output.getvalue())['result']

    def test_production_drops_owner_before_constructing_worker(self):
        order = []
        def drop(binding):
            self.assertEqual(binding['uid'], 1001); order.append('drop')
        def construct(binding):
            self.assertEqual(order, ['drop']); order.append('construct')
            descriptor = GitRepository.descriptor(SimpleNamespace(binding=binding))
            return SimpleNamespace(dispatch=lambda request: {'repository': descriptor})
        result = self.invoke({'mode': 'status', 'binding_id': self.binding['id'], 'revision': self.binding['revision']}, drop, construct)
        self.assertEqual(order, ['drop', 'construct'])
        self.assertFalse(set(result['repository']) & {'home', 'uid', 'gid', 'anchor', '_approved_revisions'})

    def test_public_listing_never_opens_repositories_or_exposes_owner_internals(self):
        def forbidden(_): self.fail('A public listing must not open a repository or drop into its account.')
        result = self.invoke({'mode': 'list'}, forbidden, forbidden)
        self.assertEqual(result['protocol'], 'clab-manager-git-v1')
        self.assertFalse(set(result['repositories'][0]) & {'home', 'uid', 'gid', 'anchor', '_approved_revisions'})


if __name__ == '__main__': unittest.main()


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class HostGitPlacesTests(HostGitTests):
    """Folder browsing, moving a lab between folders, and UI-driven registration."""

    def account(self, owner):
        return SimpleNamespace(pw_name=owner, pw_uid=1000, pw_gid=1000, pw_dir=str(self.home))

    def sibling(self, prefix, label=None):
        binding = {'id': uuid.uuid4().hex, 'label': label or ('repo / ' + prefix), 'owner': 'ben', 'path': str(self.repo), 'home': str(self.home),
                   'remote': 'origin', 'branch': 'main', 'prefix': prefix, 'push_url': str(self.remote), 'revision': hashlib.sha256(prefix.encode()).hexdigest()}
        return binding, GitRepository(binding, git=self.git, allow_local=True, env=self.env)

    def test_clone_url_accepts_clone_urls_and_resolves_github_page_links(self):
        self.assertEqual(host_git.clone_url('https://github.com/Owner/Lab-Repo'), 'https://github.com/Owner/Lab-Repo.git')
        self.assertEqual(host_git.clone_url('https://github.com/Owner/Lab-Repo.git'), 'https://github.com/Owner/Lab-Repo.git')
        self.assertEqual(host_git.clone_url('https://github.com/Owner/Lab-Repo/tree/main/bgp'), 'https://github.com/Owner/Lab-Repo.git')
        self.assertEqual(host_git.clone_url('https://gitlab.example.com/team/lab.git'), 'https://gitlab.example.com/team/lab.git')
        for bad in ('http://github.com/Owner/Lab', 'https://github.com/Owner', 'https://github.com/Owner/Lab?x=1', 'https://user:token@github.com/Owner/Lab.git',
                    'https://github.com/Owner/Lab.git#frag', 'https://github.com/O wner/Lab', 'git@github.com:Owner/Lab.git', '', None, 'https://github.com/../x'):
            with self.assertRaises(ValueError, msg=repr(bad)): host_git.clone_url(bad)
        self.assertTrue(host_git.same_repository('https://github.com/Owner/Lab.git', 'https://github.com/owner/lab/'))
        self.assertFalse(host_git.same_repository('https://gitlab.example.com/a.git', 'https://gitlab.example.com/a'))
        self.assertEqual(host_git.repository_name('https://github.com/Owner/Lab-Repo.git'), 'Lab-Repo')

    def test_browse_lists_committed_files_only_and_marks_lab_folders(self):
        (self.repo / 'scratch.txt').write_text('not committed\n')
        self.publish(push=True)
        self.binding['_siblings'] = [{'id': self.binding['id'], 'label': 'Ben BGP', 'prefix': ''}, {'id': 'other', 'label': 'repo / eth', 'prefix': 'eth'}]
        result = self.worker.dispatch(self.request('browse'))
        paths = [f['path'] for f in result['files']]
        self.assertEqual(paths, ['README.md', 'latest/PE1.cfg', 'latest/manifest.json'])
        self.assertNotIn('scratch.txt', paths)
        self.assertEqual(next(f for f in result['files'] if f['path'] == 'latest/PE1.cfg')['size'], len('router bgp 65001\n'))
        self.assertIsInstance(result['saved']['latest'], int); self.assertIsNone(result['saved']['baseline'])
        self.assertEqual([f['prefix'] for f in result['folders']], ['', 'eth'])
        self.assertFalse(result['truncated']); self.assertEqual(result['head'], self.raw('rev-parse', 'HEAD'))
        self.assertNotIn('_siblings', self.worker.registration())

    def test_read_version_reaches_a_sibling_folder_without_rebinding(self):
        import base64
        other_binding, other = self.sibling('bgp')
        req = {'mode': 'publish', 'binding_id': other_binding['id'], 'revision': other_binding['revision'],
               'operation_id': uuid.uuid4().hex, 'expected_head': self.raw('rev-parse', 'HEAD'),
               'target': 'latest', 'push': False, 'snapshot': self.capture('sibling config\n')}
        result = other.dispatch(req)
        self.assertEqual(result['status'], 'committed', result)
        # The main binding (prefix '') can read the sibling folder's latest snapshot directly.
        version = self.worker.dispatch(self.request('read-version', commit=result['commit'], path='bgp/latest'))
        self.assertEqual(set(version['snapshot']['files']), {'PE1.cfg'})
        self.assertIn('sibling config', base64.b64decode(version['snapshot']['files']['PE1.cfg']).decode())
        # Non-snapshot folders and traversal are still refused.
        for bad in ('bgp/notasnapshot', 'bgp/../etc', 'bgp/.git/config'):
            with self.assertRaises(ValueError, msg=bad):
                self.worker.dispatch(self.request('read-version', commit=result['commit'], path=bad))

    def test_history_lists_saved_folders_across_the_checkout_with_full_paths(self):
        self.publish(push=False)  # connected folder (prefix '') -> latest/
        other_binding, other = self.sibling('bgp')
        req = {'mode': 'publish', 'binding_id': other_binding['id'], 'revision': other_binding['revision'],
               'operation_id': uuid.uuid4().hex, 'expected_head': self.raw('rev-parse', 'HEAD'),
               'target': 'latest', 'push': False, 'snapshot': self.capture('bgp state\n')}
        other.dispatch(req)
        hist = self.worker.dispatch(self.request('history'))
        by_path = {v['path']: v for v in hist['versions']}
        self.assertIn('latest', by_path)          # the connected folder's own latest
        self.assertIn('bgp/latest', by_path)       # a sibling folder, by its full repository path
        self.assertTrue(by_path['latest']['connected'])
        self.assertFalse(by_path['bgp/latest']['connected'])

    def test_register_validates_the_checkout_like_the_wizard(self):
        binding = {'id': uuid.uuid4().hex, 'label': 'repo / bgp', 'owner': 'ben', 'path': str(self.repo), 'home': str(self.home),
                   'remote': 'origin', 'branch': '', 'push_url': '', 'prefix': 'bgp', 'revision': ''}
        result = GitRepository(binding, git=self.git, allow_local=True, env=self.env).register(None)
        self.assertEqual(result['branch'], 'main'); self.assertEqual(result['push_url'], str(self.remote))
        self.assertEqual(result['anchor'], self.raw('rev-parse', 'HEAD')); self.assertRegex(result['revision'], r'^[0-9a-f]{64}$')
        (self.repo / 'README.md').write_text('local edit\n'); self.raw('commit', '-am', 'ahead of remote')
        binding.update(branch='', push_url='', revision='')
        with self.assertRaisesRegex(ValueError, 'synchronize'):
            GitRepository(binding, git=self.git, allow_local=True, env=self.env).register(None)

    def test_planning_refuses_overlap_and_reuses_identical_folders(self):
        config = {'repositories': [dict(self.binding, prefix='bgp', uid=1000, gid=1000, revision='r-bgp')]}
        req = {'binding_id': self.binding['id'], 'revision': 'r-bgp'}
        existing, planned = host_git.plan_prefix(config, dict(req, prefix='bgp'), self.account)
        self.assertIs(existing, config['repositories'][0]); self.assertIsNone(planned)
        for prefix in ('', 'bgp/edge'):
            with self.assertRaisesRegex(ValueError, 'cannot overlap'): host_git.plan_prefix(config, dict(req, prefix=prefix), self.account)
        with self.assertRaisesRegex(ValueError, 'binding changed'): host_git.plan_prefix(config, dict(req, revision='stale', prefix='eth'), self.account)
        with self.assertRaises(ValueError): host_git.plan_prefix(config, dict(req, prefix='../eth'), self.account)
        existing, planned = host_git.plan_prefix(config, dict(req, prefix='courses/eth'), self.account)
        self.assertIsNone(existing); self.assertEqual(planned['prefix'], 'courses/eth'); self.assertEqual(planned['label'], 'repo / courses/eth')
        rooted = {'repositories': [dict(self.binding, prefix='', uid=1000, gid=1000, revision='r-root')]}
        with self.assertRaisesRegex(ValueError, 'cannot overlap'): host_git.plan_prefix(rooted, dict(req, revision='r-root', prefix='bgp'), self.account)
        self.assertEqual(host_git.plan_prefix(rooted, dict(req, revision='r-root', prefix='bgp', retire=True), self.account)[1]['prefix'], 'bgp')
        with patch.object(host_git, 'REGISTRY', self.base / 'registry.json'):
            registered = host_git.register_prefix(rooted, dict(req, revision='r-root', prefix='bgp', retire=True), lambda binding, work: dict(binding, branch='main', push_url=str(self.remote), revision='r-bgp', anchor='a' * 40), lookup=self.account)
            self.assertEqual(registered['prefix'], 'bgp'); self.assertNotIn('anchor', registered)
            self.assertEqual([b['prefix'] for b in json.loads((self.base / 'registry.json').read_text())['repositories']], ['bgp'])
            self.assertEqual([b['prefix'] for b in rooted['repositories']], ['bgp'])
        self.assertEqual((planned['owner'], planned['uid'], planned['path'], planned['remote'], planned['branch']), ('ben', 1000, str(self.repo), 'origin', ''))
        with patch.object(host_git, 'ENGINEER', self.base / 'missing-engineer.json'):
            url = 'https://github.com/Owner/Course-Labs.git'
            config = {'repositories': [dict(self.binding, uid=1000, gid=1000, push_url=url, prefix='bgp', revision='r')]}
            existing, planned, resolved = host_git.plan_connect(config, {'url': 'https://github.com/owner/course-labs/tree/main', 'prefix': 'bgp'}, self.account)
            self.assertIs(existing, config['repositories'][0]); self.assertTrue(host_git.same_repository(resolved, url))
            existing, planned, _ = host_git.plan_connect(config, {'url': url, 'prefix': 'eth'}, self.account)
            self.assertIsNone(existing); self.assertEqual(planned['path'], str(self.repo)); self.assertTrue(planned['_pending'])
            with self.assertRaisesRegex(ValueError, 'cannot overlap'): host_git.plan_connect(config, {'url': url, 'prefix': ''}, self.account)
            existing, planned, _ = host_git.plan_connect(config, {'url': 'https://github.com/Owner/Other-Lab', 'prefix': ''}, self.account)
            self.assertEqual(planned['path'], str(self.home / 'labs' / 'Other-Lab')); self.assertEqual(planned['label'], 'Other-Lab')
            with self.assertRaisesRegex(ValueError, 'No VM account'): host_git.plan_connect({'repositories': []}, {'url': url, 'prefix': ''}, self.account)
            with self.assertRaisesRegex(ValueError, 'Several VM accounts'):
                host_git.plan_connect({'repositories': [dict(self.binding, uid=1, gid=1, revision='a'), dict(self.binding, id='x', owner='alice', uid=2, gid=2, revision='b')]}, {'url': url, 'prefix': ''}, self.account)

    def test_move_relocates_every_saved_folder_in_one_pushed_commit(self):
        old_binding, old = self.sibling('old'); new_binding, new = self.sibling('new')
        def publish(worker, binding, **options):
            req = {'mode': 'publish', 'binding_id': binding['id'], 'revision': binding['revision'], 'operation_id': uuid.uuid4().hex,
                   'expected_head': self.raw('rev-parse', 'HEAD'), 'target': 'latest', 'push': True, 'snapshot': self.capture()}
            req.update(options); return worker.dispatch(req)
        self.assertEqual(publish(old, old_binding)['status'], 'synced')
        self.assertEqual(publish(old, old_binding, target='checkpoint', checkpoint='peering', snapshot=self.capture('peering\n'))['status'], 'synced')
        (self.repo / 'README.md').write_text('Course notes\n'); self.raw('commit', '-am', 'course notes'); self.raw('push')
        req = {'mode': 'move', 'binding_id': new_binding['id'], 'revision': new_binding['revision'], 'operation_id': uuid.uuid4().hex,
               'expected_head': self.raw('rev-parse', 'HEAD'), 'source_prefix': 'old', 'push': True, 'message': 'Move BGP progress to new/'}
        before = int(self.raw('rev-list', '--count', 'HEAD'))
        result = new.dispatch(req)
        self.assertEqual(result['status'], 'synced', result); self.assertTrue(result['pushed'])
        self.assertEqual(int(self.raw('rev-list', '--count', 'HEAD')), before + 1)
        self.assertEqual(self.raw('ls-remote', 'origin', 'refs/heads/main').split()[0], result['commit'])
        self.assertEqual(self.raw('ls-tree', '-r', '--name-only', 'HEAD', '--', 'old'), '')
        self.assertEqual(sorted(self.raw('ls-tree', '-r', '--name-only', 'HEAD', '--', 'new').splitlines()),
                         ['new/checkpoints/peering/PE1.cfg', 'new/checkpoints/peering/manifest.json', 'new/latest/PE1.cfg', 'new/latest/manifest.json'])
        self.assertEqual((self.repo / 'new/checkpoints/peering/PE1.cfg').read_text(), 'peering\n')
        self.assertFalse((self.repo / 'old').exists()); self.assertEqual(self.raw('show', 'HEAD:README.md'), 'Course notes')
        self.assertIn('Move BGP progress to new/', self.raw('log', '-1', '--format=%s'))
        self.assertEqual(new.dispatch(req)['commit'], result['commit'])
        self.assertEqual(len(new.dispatch({'mode': 'history', 'binding_id': new_binding['id'], 'revision': new_binding['revision']})['versions']), 2)
        again = dict(req, operation_id=uuid.uuid4().hex, expected_head=self.raw('rev-parse', 'HEAD'))
        self.assertEqual(new.dispatch(again)['status'], 'needs_attention'); self.assertIn('no saved files', new.dispatch(again)['message'])

    def test_move_refuses_dirty_source_and_occupied_destination(self):
        old_binding, old = self.sibling('old'); new_binding, new = self.sibling('new')
        req = {'mode': 'publish', 'binding_id': old_binding['id'], 'revision': old_binding['revision'], 'operation_id': uuid.uuid4().hex,
               'expected_head': self.raw('rev-parse', 'HEAD'), 'target': 'latest', 'push': True, 'snapshot': self.capture()}
        self.assertEqual(old.dispatch(req)['status'], 'synced')
        move = lambda **o: new.dispatch({'mode': 'move', 'binding_id': new_binding['id'], 'revision': new_binding['revision'], 'operation_id': uuid.uuid4().hex,
                                         'expected_head': self.raw('rev-parse', 'HEAD'), 'source_prefix': 'old', 'push': False, 'message': 'Move', **o})
        (self.repo / 'old/latest/PE1.cfg').write_text('edited by hand\n')
        self.assertIn('unsaved edits', move()['message'])
        self.raw('checkout', '--', 'old/latest/PE1.cfg')
        (self.repo / 'new/latest').mkdir(parents=True); (self.repo / 'new/latest/PE1.cfg').write_text('occupied\n')
        self.raw('add', 'new'); self.raw('commit', '-m', 'occupied'); self.raw('push')
        self.assertIn('already contains saved files', move()['message'])
        with self.assertRaisesRegex(ValueError, 'binding changed'): new.dispatch({'mode': 'move', 'binding_id': 'x', 'revision': 'y'})
        with self.assertRaisesRegex(ValueError, 'different folder'): move(source_prefix='new')

    def test_tools_run_before_the_checkout_exists(self):
        import sys
        binding = {'id': uuid.uuid4().hex, 'label': 'later', 'owner': 'ben', 'path': str(self.home / 'labs' / 'later'), 'home': str(self.home),
                   'remote': 'origin', 'branch': '', 'push_url': '', 'prefix': '', 'revision': '', '_pending': True}
        worker = GitRepository(binding, git=self.git, allow_local=True, env=self.env, gh=str(self.base / 'no-gh'))
        code, raw = worker.tool([sys.executable, '-c', 'import os; print(os.getcwd())'])
        self.assertEqual(code, 0); self.assertEqual(Path(raw.decode().strip()).resolve(), self.home.resolve())
        with self.assertRaisesRegex(ValueError, 'GitHub CLI is not installed'):
            worker.connect('https://github.com/Owner/Private-Lab.git')
        self.assertFalse((self.home / 'labs' / 'later').exists(), 'nothing is cloned before the GitHub checks pass')

    def test_connect_clones_or_adopts_a_checkout_and_registers_it(self):
        env = dict(self.env, GIT_AUTHOR_NAME='Ben', GIT_AUTHOR_EMAIL='ben@example.invalid', GIT_COMMITTER_NAME='Ben', GIT_COMMITTER_EMAIL='ben@example.invalid')
        self.raw('--git-dir', str(self.remote), 'symbolic-ref', 'HEAD', 'refs/heads/main')  # GitHub always has a default branch
        path = self.home / 'labs' / 'remote'
        binding = {'id': uuid.uuid4().hex, 'label': 'remote', 'owner': 'ben', 'path': str(path), 'home': str(self.home), 'remote': 'origin',
                   'branch': '', 'push_url': '', 'prefix': '', 'revision': '', '_pending': True}
        result = GitRepository(binding, git=self.git, allow_local=True, env=env).connect(str(self.remote))
        self.assertTrue((path / '.git').is_dir()); self.assertEqual(result['branch'], 'main'); self.assertEqual(result['push_url'], str(self.remote))
        self.assertNotIn('_pending', result); self.assertEqual(result['anchor'], self.raw('rev-parse', 'HEAD'))
        adopted = {'id': uuid.uuid4().hex, 'label': 'existing', 'owner': 'ben', 'path': str(self.repo), 'home': str(self.home), 'remote': 'origin',
                   'branch': '', 'push_url': '', 'prefix': 'bgp', 'revision': '', '_pending': True}
        self.assertEqual(GitRepository(adopted, git=self.git, allow_local=True, env=env).connect(str(self.remote))['prefix'], 'bgp')
        other = self.base / 'other.git'; self.raw('init', '--bare', str(other))
        with self.assertRaisesRegex(ValueError, 'different repository'):
            GitRepository(dict(adopted, id='z'), git=self.git, allow_local=True, env=env).connect(str(other))
        occupied = self.home / 'labs' / 'occupied'; occupied.mkdir(parents=True); (occupied / 'notes.txt').write_text('x')
        with self.assertRaisesRegex(ValueError, 'not a Git checkout'):
            GitRepository(dict(binding, id='q', path=str(occupied)), git=self.git, allow_local=True, env=env).connect(str(self.remote))
        missing = {'id': uuid.uuid4().hex, 'label': 'noid', 'owner': 'ben', 'path': str(self.home / 'labs' / 'noid'), 'home': str(self.home),
                   'remote': 'origin', 'branch': '', 'push_url': '', 'prefix': '', 'revision': '', '_pending': True}
        with self.assertRaisesRegex(ValueError, 'commit identity'):
            GitRepository(missing, git=self.git, allow_local=True, env=self.env).connect(str(self.remote))
