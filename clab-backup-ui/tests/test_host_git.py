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
