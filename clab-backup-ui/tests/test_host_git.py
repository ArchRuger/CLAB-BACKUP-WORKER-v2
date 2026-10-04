import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unicodedata
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
        for key in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'): self.env.pop(key, None)
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

    def test_connect_derives_the_identity_from_a_github_account_without_a_display_name(self):
        self.raw('config', '--unset', 'user.name'); self.raw('config', '--unset', 'user.email')
        self.raw('config', 'user.useConfigOnly', 'true')
        fake_gh = self.base / 'gh'
        fake_gh.write_text('#!/bin/sh\nprintf \'328467482\\tpruger-dev\\t\\n\'\n'); fake_gh.chmod(0o755)
        worker = GitRepository(self.binding, git=self.git, allow_local=True, env=self.env, gh=str(fake_gh))
        worker.ensure_identity('https://github.com/pruger-dev/netlab-course.git')
        self.assertEqual(self.raw('config', 'user.name'), 'pruger-dev')
        self.assertEqual(self.raw('config', 'user.email'), '328467482+pruger-dev@users.noreply.github.com')
        self.raw('config', '--unset', 'user.name'); self.raw('config', '--unset', 'user.email')
        fake_gh.write_text('#!/bin/sh\nprintf \'328467482\\tpruger-dev\\tSam Colt\\n\'\n')
        worker.ensure_identity('https://github.com/pruger-dev/netlab-course.git')
        self.assertEqual(self.raw('config', 'user.name'), 'Sam Colt')

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

    def test_the_embedded_topology_and_map_are_owned_files_but_not_devices(self):
        # UI/UX changes 2, item 10: a capture's snapshot carries `<lab>.clab.yml` and its map as entries of a
        # kind; they land in the folder with the device files, a later save without them needs no removal review,
        # and a save that drops a device still does.
        capture = self.capture(); topology = b'name: BGP\ntopology:\n  nodes: {}\n'; layout = b'{"nodeAnnotations": []}'
        for name, raw, kind in (('BGP.clab.yml', topology, 'topology'), ('BGP.clab.yml.annotations.json', layout, 'annotations')):
            capture['files'][name] = base64.b64encode(raw).decode()
            capture['manifest']['files'].append(dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), kind=kind, source='vm', vm_path='/srv/labs/BGP.clab.yml'))
        capture['manifest']['schema'] = 2; capture['manifest']['topology_provenance'] = 'embedded'
        _, first = self.publish(capture)
        self.assertEqual(first['status'], 'committed', first)
        self.assertEqual(sorted(p.name for p in (self.repo / 'latest').iterdir()), ['BGP.clab.yml', 'BGP.clab.yml.annotations.json', 'PE1.cfg', 'manifest.json'])
        self.assertEqual((self.repo / 'latest/BGP.clab.yml').read_bytes(), topology)
        _, plain = self.publish(self.capture('router bgp 65002\n'))
        self.assertEqual(plain['status'], 'committed', 'a save without the embedded files needs no removal review: they are no devices')
        self.assertEqual(sorted(p.name for p in (self.repo / 'latest').iterdir()), ['PE1.cfg', 'manifest.json'], 'and the folder follows the new manifest')
        _, again = self.publish(capture)
        self.assertEqual(again['status'], 'committed')
        dropped = self.capture(); dropped['manifest']['node_names'] = []; dropped['manifest']['files'] = []; dropped['files'] = {}
        dropped['files'][ 'BGP.clab.yml'] = base64.b64encode(topology).decode()
        dropped['manifest']['files'].append(dict(path='BGP.clab.yml', size=len(topology), sha256=hashlib.sha256(topology).hexdigest(), kind='topology'))
        _, blocked = self.publish(dropped)
        self.assertEqual(blocked['status'], 'needs_attention', 'dropping the device PE1 still needs the removal review')
        self.assertIn('removes previously saved devices', blocked['message'])

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
        self.assertEqual(result['files'], [])
        # H6 adds what an upload would carry, also for a save that changed nothing: the one waiting save.
        self.assertEqual([(c['commit'], c['operation_id']) for c in result['outgoing']], [(saved['commit'], first['operation_id'])])


class HostGitDesignExportTests(unittest.TestCase):
    """A design export (`kind: network-design`) is a plan's generated files, never a configuration snapshot: it goes
    to its own checkpoint folder only and never touches `latest` or `baseline`; the two kinds never share a folder.
    The fixture methods are borrowed, not inherited, so the base class's tests do not run twice."""
    setUp = HostGitTests.setUp
    raw = HostGitTests.raw; request = HostGitTests.request; publish = HostGitTests.publish; capture = HostGitTests.capture
    if hasattr(HostGitTests, 'tearDown'): tearDown = HostGitTests.tearDown

    def test_a_capture_never_lands_on_a_hand_committed_design_manifest(self):
        latest = self.repo / 'latest'; latest.mkdir(parents=True, exist_ok=True)
        design = self.design()
        (latest / 'manifest.json').write_text(json.dumps(design['manifest']) + '\n')
        for name, data in design['files'].items(): (latest / name).write_bytes(base64.b64decode(data))
        self.raw('add', '-A'); self.raw('commit', '-q', '-m', 'a design manifest committed by hand into latest')
        req, result = self.publish()
        self.assertEqual(result['status'], 'needs_attention', result)
        self.assertIn('different kind', result['message'])
        req, result = self.publish(capture={'manifest': dict(self.capture()['manifest'], kind='Network-Design'), 'files': self.capture()['files']}, target='checkpoint', checkpoint='odd')
        self.assertEqual(result['status'], 'needs_attention', result); self.assertIn('Unsupported snapshot kind', result['message'])

    def design(self):
        raw = b'router ospf 1\n router-id 10.255.0.1\n'; intent = b'schema: 1\nmodules: [ospf]\n'
        rows = [dict(path='ceos--01-ospf.cfg', size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), artifact='network-design', kind='fragment', device='ceos', module='ospf'),
                dict(path='network-intent.yml', size=len(intent), sha256=hashlib.sha256(intent).hexdigest(), artifact='network-design', kind='intent')]
        return {'manifest': {'schema': 2, 'kind': 'network-design', 'lab_id': 'bgp', 'lab_name': 'BGP', 'generation_id': 'g' * 32, 'intent_revision': 'r1',
                             'topology_digest': 'a' * 64, 'engine_version': '26.9', 'generated_at': '2026-09-27T00:00:00Z', 'modules': ['ospf'],
                             'devices': ['ceos'], 'node_names': [], 'restore_capable_nodes': 0, 'files': rows},
                'files': {'ceos--01-ospf.cfg': base64.b64encode(raw).decode(), 'network-intent.yml': base64.b64encode(intent).decode()}}

    def test_a_design_export_writes_only_its_checkpoint_folder(self):
        req, first = self.publish()   # the lab's configuration save in latest
        self.assertEqual(first['status'], 'committed')
        latest_before = sorted(p.name for p in (self.repo / 'latest').iterdir())
        req, result = self.publish(capture=self.design(), target='checkpoint', checkpoint='design-plan1')
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(result['snapshot_path'], 'checkpoints/design-plan1')
        self.assertTrue(all(name.startswith('checkpoints/design-plan1/') for name in result['changed_files']), result['changed_files'])
        self.assertEqual(sorted(p.name for p in (self.repo / 'checkpoints/design-plan1').iterdir()), ['ceos--01-ospf.cfg', 'manifest.json', 'network-intent.yml'])
        self.assertEqual(sorted(p.name for p in (self.repo / 'latest').iterdir()), latest_before, 'latest is untouched by a design export')
        self.assertEqual(json.loads((self.repo / 'checkpoints/design-plan1/manifest.json').read_text())['kind'], 'network-design')

    def test_a_design_export_is_refused_at_latest_and_baseline(self):
        for target in ('latest', 'baseline'):
            req, result = self.publish(capture=self.design(), target=target, replace_baseline=True)
            self.assertEqual(result['status'], 'needs_attention', result)
            self.assertIn('own checkpoint folder', result['message'])
        self.assertFalse((self.repo / 'latest' / 'network-intent.yml').exists())

    def test_the_two_kinds_never_share_a_folder(self):
        req, result = self.publish(capture=self.design(), target='checkpoint', checkpoint='design-plan1')
        self.assertEqual(result['status'], 'committed')
        req, result = self.publish(target='checkpoint', checkpoint='design-plan1')   # a capture into the design's folder
        self.assertEqual(result['status'], 'needs_attention', result)
        self.assertIn('already exists', result['message'])


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

    def commit_snapshot(self, folder, text):
        """A snapshot folder written by somebody else (an instructor's clone, a plain git user): the
        manifest and its file committed under `folder` ('' = the repository root)."""
        snap = self.capture(text)
        target = self.repo / folder if folder else self.repo
        target.mkdir(parents=True, exist_ok=True)
        (target / 'PE1.cfg').write_bytes(base64.b64decode(snap['files']['PE1.cfg']))
        (target / 'manifest.json').write_text(json.dumps(snap['manifest'], indent=2) + '\n')
        self.raw('add', '-A', '--', folder or '.'); self.raw('commit', '-m', 'instructor snapshot ' + (folder or 'root'))
        return self.raw('rev-parse', 'HEAD')

    def test_base_prefix_refuses_the_snapshot_folder_names(self):
        # A lab folder is where Save progress writes latest/, baseline/ and checkpoints/<name>: those
        # names cannot be a lab folder, or the next save nests working/latest/latest.
        for bad in ('working/latest', 'latest', 'x/baseline', 'x/checkpoints', 'x/checkpoints/one'):
            with self.assertRaisesRegex(ValueError, 'Save progress writes', msg=bad): host_git.base_prefix(bad)
        with self.assertRaisesRegex(ValueError, 'working/latest'): host_git.base_prefix('working/latest')
        with self.assertRaisesRegex(ValueError, 'repository root'): host_git.base_prefix('latest')
        for good in ('course/latest/working', 'Week-01/BGP/Final-State', 'checkpoints-2026', ''):
            self.assertEqual(host_git.base_prefix(good), good)
        config = {'repositories': [dict(self.binding, prefix='bgp', uid=1000, gid=1000, revision='r-bgp')]}
        req = {'binding_id': self.binding['id'], 'revision': 'r-bgp'}
        with self.assertRaisesRegex(ValueError, 'Save progress writes'): host_git.plan_prefix(config, dict(req, prefix='working/latest'), self.account)
        with patch.object(host_git, 'ENGINEER', self.base / 'missing-engineer.json'):
            with self.assertRaisesRegex(ValueError, 'Save progress writes'):
                host_git.plan_connect(config, {'url': 'https://github.com/Owner/Other-Lab', 'prefix': 'working/latest'}, self.account)
        # A registration an older release made at `x/latest` stays selectable and repairable: the rule
        # applies to a new lab folder only (so a legacy binding can be re-selected, repaired and moved on).
        legacy = dict(self.binding, id='legacy', prefix='working/latest', uid=1000, gid=1000, revision='r-legacy')
        config['repositories'].append(legacy)
        self.assertIs(host_git.plan_prefix(config, {'binding_id': 'legacy', 'revision': 'r-legacy', 'prefix': 'working/latest'}, self.account)[0], legacy)
        self.assertIs(host_git.plan_prefix(config, dict(req, prefix='working/latest'), self.account)[0], legacy)
        with patch.object(host_git, 'ENGINEER', self.base / 'missing-engineer.json'):
            url = str(self.remote)
            for b in config['repositories']: b['push_url'] = 'https://github.com/Owner/Course-Labs.git'
            self.assertIs(host_git.plan_connect(config, {'url': 'https://github.com/Owner/Course-Labs', 'prefix': 'working/latest'}, self.account)[0], legacy)
        # Moving that lab one level up (its documented recovery) is an ordinary, allowed registration.
        self.assertEqual(host_git.plan_prefix(config, {'binding_id': 'legacy', 'revision': 'r-legacy', 'prefix': 'working', 'retire': True}, self.account)[1]['prefix'], 'working')

    def test_read_version_and_history_reach_any_manifest_folder(self):
        self.publish(push=False)  # this lab's own latest/
        final = self.commit_snapshot('Final', 'final state\n')
        self.commit_snapshot('Final/latest', 'legacy layout under Final\n')
        self.commit_snapshot('course/lab/reference/solution', 'nested solution\n')
        head = self.commit_snapshot('', 'root snapshot\n')
        (self.repo / 'notes').mkdir(); (self.repo / 'notes' / 'PE1.jcfg').write_text('no manifest here\n')
        self.raw('add', 'notes'); self.raw('commit', '-m', 'a restore-looking file without a manifest'); head = self.raw('rev-parse', 'HEAD')
        read = lambda path, commit=head: base64.b64decode(self.worker.dispatch(self.request('read-version', commit=commit, path=path))['snapshot']['files']['PE1.cfg']).decode()
        # Exact paths, nothing substituted: Final and Final/latest are two different snapshots.
        self.assertEqual(read('Final'), 'final state\n'); self.assertEqual(read('Final/latest'), 'legacy layout under Final\n')
        self.assertEqual(read('course/lab/reference/solution'), 'nested solution\n')
        self.assertEqual(read(''), 'root snapshot\n'); self.assertEqual(read('/'), 'root snapshot\n')
        self.assertEqual(read('Final', final), 'final state\n')
        self.assertEqual(read('/Final'), 'final state\n')  # the browser's wire form carries one leading slash
        hist = self.worker.dispatch(self.request('history'))
        by_path = {v['path']: v['connected'] for v in hist['versions']}
        self.assertEqual(by_path, {'latest': True, 'Final': False, 'Final/latest': False, 'course/lab/reference/solution': False, '': False})
        self.assertEqual([v['path'] for v in hist['versions']][0], 'latest')
        # A folder without a manifest is not a snapshot, whatever its files are called; unsafe paths stay refused.
        with self.assertRaisesRegex(ValueError, 'manifest.json'): self.worker.dispatch(self.request('read-version', commit=head, path='notes'))
        for bad in ('Final/../etc', '.git/config', 'Final/.git'):
            with self.assertRaisesRegex(ValueError, 'snapshot path|traversal', msg=bad): self.worker.dispatch(self.request('read-version', commit=head, path=bad))
        # The cap bounds the other folders, never this lab's own rows.
        # H3 lists with sizes (`ls-tree -r -l -z`); the stand-in answers in that form.
        listing = '\0'.join(f'100644 blob {"0" * 40}      10\t{p}' for p in [f'aaa/{i:04d}/manifest.json' for i in range(520)] + ['latest/manifest.json']) + '\0'
        with patch.object(self.worker, 'run', side_effect=lambda *a, **k: listing if a[:1] == ('ls-tree',) else GitRepository.run(self.worker, *a, **k)):
            capped = self.worker.dispatch(self.request('history'))['versions']
        self.assertEqual(len(capped), 501); self.assertEqual(capped[0]['path'], 'latest'); self.assertTrue(capped[0]['connected'])
        (self.repo / 'Final' / 'manifest.json').write_text('{not json')
        self.raw('commit', '-am', 'corrupt manifest'); head = self.raw('rev-parse', 'HEAD')
        with self.assertRaisesRegex(ValueError, 'manifest is invalid'): self.worker.dispatch(self.request('read-version', commit=head, path='Final'))

    def test_publish_ignores_a_nested_legacy_folder_but_not_foreign_files(self):
        self.publish(push=False)
        nested = self.commit_snapshot('latest/latest', 'nested by the old bug\n')
        before = self.raw('ls-tree', '-r', '--name-only', 'HEAD', '--', 'latest/latest')
        req, result = self.publish(self.capture('second save\n'))
        self.assertEqual(result['status'], 'committed', result)
        self.assertEqual(sorted(result['changed_files']), ['latest/PE1.cfg', 'latest/manifest.json'])
        self.assertEqual(self.raw('ls-tree', '-r', '--name-only', 'HEAD', '--', 'latest/latest'), before)
        self.assertEqual(self.raw('rev-parse', 'HEAD:latest/latest'), self.raw('rev-parse', nested + ':latest/latest'))
        (self.repo / 'latest' / 'stray.txt').write_text('somebody else\n'); self.raw('add', 'latest/stray.txt'); self.raw('commit', '-m', 'stray')
        req, result = self.publish(self.capture('third save\n'))
        self.assertEqual(result['status'], 'needs_attention'); self.assertIn('outside its manager manifest', result['message'])
        # A destination that holds only somebody's subdirectory and no manifest is not adopted either.
        other_binding, other = self.sibling('notes')
        (self.repo / 'notes' / 'latest' / 'lesson').mkdir(parents=True); (self.repo / 'notes' / 'latest' / 'lesson' / 'a.txt').write_text('x\n')
        self.raw('add', 'notes'); self.raw('commit', '-m', 'notes')
        result = other.dispatch({'mode': 'publish', 'binding_id': other_binding['id'], 'revision': other_binding['revision'], 'operation_id': uuid.uuid4().hex,
                                 'expected_head': self.raw('rev-parse', 'HEAD'), 'target': 'latest', 'push': False, 'snapshot': self.capture()})
        self.assertEqual(result['status'], 'needs_attention'); self.assertIn('not an empty manager snapshot folder', result['message'])

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

    def test_planning_refuses_a_collision_and_reuses_identical_folders(self):
        config = {'repositories': [dict(self.binding, prefix='bgp', uid=1000, gid=1000, revision='r-bgp')]}
        req = {'binding_id': self.binding['id'], 'revision': 'r-bgp'}
        existing, planned = host_git.plan_prefix(config, dict(req, prefix='bgp'), self.account)
        self.assertIs(existing, config['repositories'][0]); self.assertIsNone(planned)
        # Lab folders may sit above (the top level) or inside another; only one inside its saved state collides.
        for prefix in ('', 'bgp/edge'):
            existing, planned = host_git.plan_prefix(config, dict(req, prefix=prefix), self.account)
            self.assertIsNone(existing); self.assertEqual(planned['prefix'], prefix)
        for prefix, state in (('bgp/latest/edge', 'bgp/latest'), ('bgp/checkpoints/a/b', 'bgp/checkpoints')):
            with self.assertRaisesRegex(ValueError, '^The folder ' + prefix + ' is inside ' + state + ', where the lab folder bgp keeps its saves; choose a folder above that saved state\\.$'):
                host_git.plan_prefix(config, dict(req, prefix=prefix), self.account)
        with self.assertRaisesRegex(ValueError, 'binding changed'): host_git.plan_prefix(config, dict(req, revision='stale', prefix='eth'), self.account)
        with self.assertRaises(ValueError): host_git.plan_prefix(config, dict(req, prefix='../eth'), self.account)
        existing, planned = host_git.plan_prefix(config, dict(req, prefix='courses/eth'), self.account)
        self.assertIsNone(existing); self.assertEqual(planned['prefix'], 'courses/eth'); self.assertEqual(planned['label'], 'repo / courses/eth')
        rooted = {'repositories': [dict(self.binding, prefix='', uid=1000, gid=1000, revision='r-root')]}
        # The owner's defect: a repository registered at its top level takes a lab folder without retiring the root.
        self.assertEqual(host_git.plan_prefix(rooted, dict(req, revision='r-root', prefix='bgp'), self.account)[1]['prefix'], 'bgp')
        with self.assertRaisesRegex(ValueError, 'is inside latest, where the lab folder at the repository top level keeps its saves'):
            host_git.plan_prefix(rooted, dict(req, revision='r-root', prefix='latest/notes'), self.account)
        self.assertEqual(host_git.plan_prefix(rooted, dict(req, revision='r-root', prefix='bgp', retire=True), self.account)[1]['prefix'], 'bgp')
        # retire skips the source: a folder that collides with the top-level registration is planned only when it is retired.
        self.assertEqual(host_git.plan_prefix(rooted, dict(req, revision='r-root', prefix='latest/notes', retire=True), self.account)[1]['prefix'], 'latest/notes')
        with self.assertRaisesRegex(ValueError, 'is inside latest, where the lab folder at the repository top level keeps its saves'):
            host_git.plan_prefix(rooted, dict(req, revision='r-root', prefix='latest/notes'), self.account)
        # The registry write reloads git.json under its lock (audit L-1): here the registry as it is now is `rooted`.
        (self.base / 'registry.json').write_text(json.dumps(rooted))
        with patch.object(host_git, 'REGISTRY', self.base / 'registry.json'), patch.object(host_git, 'load_registry', return_value=rooted):
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
            existing, planned, _ = host_git.plan_connect(config, {'url': url, 'prefix': ''}, self.account)
            self.assertIsNone(existing); self.assertEqual((planned['path'], planned['prefix']), (str(self.repo), ''), 'the top level beside a lab folder is a folder of its own')
            with self.assertRaisesRegex(ValueError, 'The folder bgp/baseline/x is inside bgp/baseline, where the lab folder bgp keeps its saves'):
                host_git.plan_connect(config, {'url': url, 'prefix': 'bgp/baseline/x'}, self.account)
            existing, planned, _ = host_git.plan_connect(config, {'url': 'https://github.com/Owner/Other-Lab', 'prefix': ''}, self.account)
            self.assertEqual(planned['path'], str(self.home / 'labs' / 'Other-Lab')); self.assertEqual(planned['label'], 'Other-Lab')
            with self.assertRaisesRegex(ValueError, 'No VM account'): host_git.plan_connect({'repositories': []}, {'url': url, 'prefix': ''}, self.account)
            with self.assertRaisesRegex(ValueError, 'Several VM accounts'):
                host_git.plan_connect({'repositories': [dict(self.binding, uid=1, gid=1, revision='a'), dict(self.binding, id='x', owner='alice', uid=2, gid=2, revision='b')]}, {'url': url, 'prefix': ''}, self.account)

    def test_a_checkout_registered_at_its_top_level_takes_a_lab_folder_and_both_save_independently(self):
        # The owner's defect (1.30.59): guided setup registered the checkout at its top level, and the first save
        # of UX-TEST-003 into a folder of its name was refused. Real Git, the real registration and real saves.
        registry = self.base / 'git.json'; root = dict(self.binding, uid=1000, gid=1000)
        registry.write_text(json.dumps({'repositories': [root]}))
        owner = lambda binding, work: GitRepository(binding, git=self.git, allow_local=True, env=self.env).register(None)
        with patch.object(host_git, 'REGISTRY', registry), patch.object(host_git, 'load_registry', lambda: json.loads(registry.read_text())):
            created = host_git.register_prefix(host_git.load_registry(), {'binding_id': root['id'], 'revision': root['revision'], 'prefix': 'UX-TEST-003'}, owner, lookup=self.account)
            self.assertEqual(created['prefix'], 'UX-TEST-003')
            saved = {b['prefix']: b for b in json.loads(registry.read_text())['repositories']}
            self.assertEqual(sorted(saved), ['', 'UX-TEST-003'], 'the top-level registration is kept: no retire was asked')
            self.assertEqual(saved['']['revision'], root['revision'])
            # A folder inside the saved state of either is still refused, and nothing is registered.
            for prefix, message in (('UX-TEST-003/latest/notes', 'is inside UX-TEST-003/latest, where the lab folder UX-TEST-003 keeps'),
                                    ('latest/notes', 'is inside latest, where the lab folder at the repository top level keeps')):
                with self.assertRaisesRegex(ValueError, message):
                    host_git.register_prefix(host_git.load_registry(), {'binding_id': root['id'], 'revision': root['revision'], 'prefix': prefix}, owner, lookup=self.account)
            self.assertEqual(sorted(b['prefix'] for b in json.loads(registry.read_text())['repositories']), ['', 'UX-TEST-003'])
        lab = GitRepository(saved['UX-TEST-003'], git=self.git, allow_local=True, env=self.env)
        def publish(worker, binding, text):
            result = worker.dispatch({'mode': 'publish', 'binding_id': binding['id'], 'revision': binding['revision'], 'operation_id': uuid.uuid4().hex,
                                      'expected_head': self.raw('rev-parse', 'HEAD'), 'target': 'latest', 'push': True, 'snapshot': self.capture(text)})
            self.assertEqual(result['status'], 'synced', result); return result
        tree = lambda folder: self.raw('ls-tree', '-r', 'HEAD', '--', folder)
        first = publish(lab, saved['UX-TEST-003'], 'ux first\n')
        self.assertEqual(sorted(first['changed_files']), ['UX-TEST-003/latest/PE1.cfg', 'UX-TEST-003/latest/manifest.json'])
        lab_files = tree('UX-TEST-003')
        top = publish(self.worker, self.binding, 'top level\n')
        self.assertEqual(sorted(top['changed_files']), ['latest/PE1.cfg', 'latest/manifest.json'])
        self.assertEqual(tree('UX-TEST-003'), lab_files, 'a save at the top level leaves the lab folder below it untouched')
        top_files = tree('latest')
        publish(lab, saved['UX-TEST-003'], 'ux second\n')
        self.assertEqual(tree('latest'), top_files, 'a save into the lab folder leaves the top level\'s saves untouched')
        self.assertEqual(self.raw('show', 'HEAD:UX-TEST-003/latest/PE1.cfg'), 'ux second'); self.assertEqual(self.raw('show', 'HEAD:latest/PE1.cfg'), 'top level')
        self.assertEqual(self.raw('ls-remote', 'origin', 'refs/heads/main').split()[0], self.raw('rev-parse', 'HEAD'))
        for worker, binding in ((self.worker, self.binding), (lab, saved['UX-TEST-003'])):
            status = worker.dispatch({'mode': 'status', 'binding_id': binding['id'], 'revision': binding['revision']})
            self.assertTrue(status['ready'], status); self.assertEqual(status['problem'], '')

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


class RegistryRaceTests(unittest.TestCase):
    """Audit L-1: git.json is read-modify-written by the root helper and by setup-git.sh while an owner's Git
    (clone, push check) runs for minutes. A registration saved meanwhile must never be lost."""
    URL = 'https://github.com/Owner/Course.git'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.registry = self.base / 'git.json'; self.home = self.base / 'home'
        for target, value in (('REGISTRY', self.registry), ('load_registry', lambda: json.loads(self.registry.read_text())),
                              ('ENGINEER', self.base / 'missing-engineer.json')):
            patcher = patch.object(host_git, target, value); patcher.start(); self.addCleanup(patcher.stop)

    def account(self, owner):
        return SimpleNamespace(pw_name=owner, pw_uid=1000, pw_gid=1000, pw_dir=str(self.home))

    def binding(self, prefix, revision=None, **extra):
        return dict({'id': uuid.uuid4().hex, 'label': 'Course / ' + prefix, 'owner': 'ben', 'uid': 1000, 'gid': 1000, 'home': str(self.home),
                     'path': str(self.home / 'labs' / 'Course'), 'remote': 'origin', 'prefix': prefix, 'branch': 'main',
                     'push_url': self.URL, 'revision': revision or hashlib.sha256(prefix.encode()).hexdigest(), 'anchor': 'a' * 40}, **extra)

    def write(self, *bindings): self.registry.write_text(json.dumps({'repositories': list(bindings)}))

    def saved(self): return {b['prefix']: b for b in json.loads(self.registry.read_text())['repositories']}

    def owner_git(self, meanwhile):
        # The owner's Git runs unlocked; `meanwhile` is what another root process saves during it.
        def run(binding, work):
            meanwhile()
            return dict(binding, branch='main', push_url=self.URL, revision='r-' + binding['prefix'], anchor='a' * 40)
        return run

    def test_a_folder_registration_keeps_what_setup_git_saved_while_the_owner_git_ran(self):
        bgp = self.binding('bgp'); ospf = self.binding('ospf'); self.write(bgp)
        config = host_git.load_registry()
        result = host_git.register_prefix(config, {'binding_id': bgp['id'], 'revision': bgp['revision'], 'prefix': 'eth'},
                                          self.owner_git(lambda: self.write(bgp, ospf)), lookup=self.account)
        self.assertEqual(result['prefix'], 'eth')
        self.assertEqual(sorted(self.saved()), ['bgp', 'eth', 'ospf'])

    def test_a_pasted_url_connection_keeps_what_setup_git_saved_while_the_clone_ran(self):
        bgp = self.binding('bgp'); ospf = self.binding('ospf'); self.write(bgp)
        result = host_git.connect(host_git.load_registry(), {'url': self.URL, 'prefix': 'eth'},
                                  self.owner_git(lambda: self.write(bgp, ospf)), lookup=self.account)
        self.assertEqual(result['prefix'], 'eth')
        self.assertEqual(sorted(self.saved()), ['bgp', 'eth', 'ospf'])

    def test_setup_git_keeps_what_the_manager_saved_while_its_push_check_ran(self):
        # setup-git.sh loads at start, forks the owner child, then saves through save_registration.
        bgp = self.binding('bgp'); eth = self.binding('eth'); self.write(bgp)
        startup = host_git.load_registry(); self.write(bgp, eth)
        ospf = self.binding('ospf'); self.assertNotIn(ospf['id'], [b['id'] for b in startup['repositories']])
        self.assertEqual(host_git.save_registration(dict(ospf, _pending=True))['prefix'], 'ospf')
        self.assertEqual(sorted(self.saved()), ['bgp', 'eth', 'ospf']); self.assertNotIn('_pending', self.saved()['ospf'])
        # Re-registering an existing folder keeps its ID and replaces only that entry.
        self.assertEqual(host_git.save_registration(dict(bgp, label='Renamed'))['id'], bgp['id'])
        self.assertEqual(self.saved()['bgp']['label'], 'Renamed'); self.assertEqual(sorted(self.saved()), ['bgp', 'eth', 'ospf'])

    def test_a_move_does_not_retire_a_registration_that_changed_meanwhile(self):
        root = self.binding('', revision='r-root'); self.write(root)
        changed = dict(root, revision='r-admin')
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            host_git.register_prefix(host_git.load_registry(), {'binding_id': root['id'], 'revision': 'r-root', 'prefix': 'bgp', 'retire': True},
                                     self.owner_git(lambda: self.write(changed)), lookup=self.account)
        self.assertEqual(self.saved(), {'': changed})
        # Unchanged meanwhile, the move still retires the old folder (the behaviour before the lock).
        self.write(root)
        host_git.register_prefix(host_git.load_registry(), {'binding_id': root['id'], 'revision': 'r-root', 'prefix': 'bgp', 'retire': True},
                                 self.owner_git(lambda: None), lookup=self.account)
        self.assertEqual(sorted(self.saved()), ['bgp'])

    def test_a_move_into_an_existing_folder_never_answers_with_a_copy_that_changed_meanwhile(self):
        # Review follow-up G5: setup-git.sh re-registered the target folder after this helper loaded git.json. Answering
        # with the startup copy would bind the lab to a revision every later call refuses ("binding changed").
        ospf = self.binding('ospf', revision='r-ospf'); bgp = self.binding('bgp', revision='r-bgp'); self.write(ospf, bgp)
        startup = host_git.load_registry()
        readmin = dict(bgp, revision='r-admin', label='Course / bgp (again)'); self.write(ospf, readmin)
        request = {'binding_id': ospf['id'], 'revision': 'r-ospf', 'prefix': 'bgp', 'retire': True}
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            host_git.register_prefix(startup, request, self.owner_git(lambda: None), lookup=self.account)
        self.assertEqual(self.saved(), {'ospf': ospf, 'bgp': readmin}, 'nothing was retired')
        # Asked again, the helper starts from git.json as it is now and the move goes through.
        result = host_git.register_prefix(host_git.load_registry(), request, self.owner_git(lambda: None), lookup=self.account)
        self.assertEqual((result['id'], result['revision'], result['label']), (bgp['id'], 'r-admin', readmin['label']))
        self.assertEqual(sorted(self.saved()), ['bgp'])

    def test_a_colliding_folder_saved_meanwhile_refuses_the_registration_and_writes_nothing(self):
        # A legacy registration inside the new folder's saved state (eth/latest/core), or the very same folder, saved
        # while the owner's Git ran: nothing is registered.
        bgp = self.binding('bgp'); self.write(bgp)
        for meanwhile in (self.binding('eth/latest/core'), self.binding('eth')):
            self.write(bgp)
            with self.assertRaisesRegex(ValueError, 'saved meanwhile'):
                host_git.register_prefix(host_git.load_registry(), {'binding_id': bgp['id'], 'revision': bgp['revision'], 'prefix': 'eth'},
                                         self.owner_git(lambda: self.write(bgp, meanwhile)), lookup=self.account)
            self.assertEqual(sorted(self.saved()), sorted(['bgp', meanwhile['prefix']]))
        # The identical top-level folder saved meanwhile: colliding('', '') is False by design, the equality test refuses.
        self.write(bgp); top = self.binding('')
        with self.assertRaisesRegex(ValueError, 'saved meanwhile'):
            host_git.register_prefix(host_git.load_registry(), {'binding_id': bgp['id'], 'revision': bgp['revision'], 'prefix': ''},
                                     self.owner_git(lambda: self.write(bgp, top)), lookup=self.account)
        self.assertEqual(sorted(self.saved()), ['', 'bgp']); self.assertEqual(self.saved()['']['id'], top['id'])
        # A folder merely nested in it (eth/core) does not collide: both are kept.
        self.write(bgp); nested = self.binding('eth/core')
        result = host_git.register_prefix(host_git.load_registry(), {'binding_id': bgp['id'], 'revision': bgp['revision'], 'prefix': 'eth'},
                                          self.owner_git(lambda: self.write(bgp, nested)), lookup=self.account)
        self.assertEqual(result['prefix'], 'eth'); self.assertEqual(sorted(self.saved()), ['bgp', 'eth', 'eth/core'])

    @unittest.skipUnless(os.name == 'posix', 'flock')
    def test_the_registry_write_waits_for_the_lock_and_gives_up_with_a_clear_message(self):
        import fcntl
        bgp = self.binding('bgp'); self.write(bgp)
        with open(str(self.registry) + '.lock', 'a') as held, patch.object(host_git, 'REGISTRY_WAIT', 0.3):
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaisesRegex(ValueError, 'Another Git registration'): host_git.save_registration(self.binding('eth'))
            self.assertEqual(sorted(self.saved()), ['bgp'])
            fcntl.flock(held, fcntl.LOCK_UN)
            host_git.save_registration(self.binding('eth'))
        self.assertEqual(sorted(self.saved()), ['bgp', 'eth'])

    def test_setup_git_writes_the_registry_only_under_the_shared_lock(self):
        script = (Path(__file__).resolve().parents[2] / 'deploy' / 'setup-git.sh').read_text()
        self.assertFalse('h.atomic_json(h.REGISTRY,registry)\n    print(' in script, 'setup-git.sh writes back the registry it loaded at start')
        self.assertTrue('h.save_registration(binding)' in script, 'setup-git.sh must save through the locked merge')
        self.assertTrue('with h.registry_lock():' in script, 'setup-git.sh --refresh must create the registry under the lock')


class CollisionRuleTests(unittest.TestCase):
    """DESIGN.md 2.2/2.3 (H1): two lab folders write the same files only when one lies inside a folder the other
    writes its saves into (latest, baseline, checkpoints). Inside, above and beside are allowed."""

    def test_colliding_is_exactly_the_saved_state_rule_in_both_directions(self):
        allowed = [('', 'UX-TEST-003'), ('', 'a/b'), ('bgp/edge', 'bgp'), ('bgp', 'bgp/edge'), ('bgp', 'eth'), ('a/b', 'a/c'),
                   ('x', 'x/latest-notes'), ('x', 'x/checkpoints2'), ('x', 'x/baselines/w'), ('latest-x', ''), ('course/latest/working', 'course/lab'),
                   ('', ''), ('x', 'x')]  # the same folder is not a collision: callers test equality themselves
        colliding = [('x', 'x/latest'), ('x', 'x/latest/w'), ('x', 'x/baseline/w'), ('x', 'x/checkpoints'), ('x', 'x/checkpoints/a/b'),
                     ('latest/foo', ''), ('baseline', ''), ('checkpoints/a', ''), ('a/checkpoints/x/y', 'a')]
        for a, b in allowed:
            for first, second in ((a, b), (b, a)):
                self.assertFalse(host_git.colliding(first, second), (first, second))
        for a, b in colliding:
            for first, second in ((a, b), (b, a)):
                self.assertTrue(host_git.colliding(first, second), (first, second))

    def test_the_refusal_names_both_folders_and_never_says_overlap(self):
        self.assertEqual(host_git.collision_message('x/latest/w', 'x'),
                         'The folder x/latest/w is inside x/latest, where the lab folder x keeps its saves; choose a folder above that saved state.')
        self.assertEqual(host_git.collision_message('latest/foo', ''),
                         'The folder latest/foo is inside latest, where the lab folder at the repository top level keeps its saves; choose a folder above that saved state.')
        self.assertEqual(host_git.collision_message('x', 'x/checkpoints/a/b'),
                         'The lab folder x/checkpoints/a/b is inside x/checkpoints, where x would keep its saves; choose another folder for this lab.')
        self.assertEqual(host_git.collision_message('', 'baseline/w'),
                         'The lab folder baseline/w is inside baseline, where a lab folder at the repository top level would keep its saves; choose another folder for this lab.')
        self.assertFalse(hasattr(host_git, 'overlapping'), 'the overlap rule is gone')
        # A legacy registration that IS the saved-state folder "is" it, in both directions, never "is inside" it.
        self.assertEqual(host_git.collision_message('x/latest', 'x'),
                         'The folder x/latest is where the lab folder x keeps its saves; choose a folder above that saved state.')
        self.assertEqual(host_git.collision_message('x', 'x/latest'),
                         'The lab folder x/latest is where x would keep its saves; choose another folder for this lab.')
        self.assertEqual(host_git.collision_message('', 'checkpoints'),
                         'The lab folder checkpoints is where a lab folder at the repository top level would keep its saves; choose another folder for this lab.')

    def test_check_collision_compares_only_folders_of_the_same_checkout_and_skips_the_retired_source(self):
        root = {'path': '/home/ben/labs/Course', 'prefix': ''}; other = {'path': '/home/ben/labs/Other', 'prefix': 'x'}
        config = {'repositories': [root, other]}
        host_git.check_collision(config, '/home/ben/labs/Course', 'UX-TEST-003')
        host_git.check_collision(config, '/home/ben/labs/Course', 'x/latest/w')  # x is a lab folder of another checkout
        with self.assertRaisesRegex(ValueError, 'is inside latest'): host_git.check_collision(config, '/home/ben/labs/Course', 'latest/w')
        host_git.check_collision(config, '/home/ben/labs/Course', 'latest/w', ignore=root)


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class HelperRedesignTests(unittest.TestCase):
    """The Git save and load redesign's helper changes H2 to H7 (docs/git-redesign/DESIGN.md 2.3, REVIEW.md F4, F7 to
    F10, F13), against real Git with temporary remotes. The fixture methods are borrowed, so the base tests do not rerun."""
    setUp = HostGitTests.setUp
    raw = HostGitTests.raw; request = HostGitTests.request; publish = HostGitTests.publish
    capture = HostGitTests.capture; capture_schema2 = HostGitTests.capture_schema2
    account = HostGitPlacesTests.account; sibling = HostGitPlacesTests.sibling

    # ---- shared fixtures -------------------------------------------------------------------------------------------
    def factory(self, binding, **kwargs):
        return GitRepository(binding, git=self.git, allow_local=True, env=self.env, **kwargs)

    def owner(self, binding, work):
        """run_as_owner without the fork: the work runs in-process and its answer crosses JSON as through the pipe."""
        return json.loads(json.dumps({'r': work()}))['r']

    def registry(self, *bindings):
        path = self.base / 'git.json'; path.write_text(json.dumps({'repositories': list(bindings)}))
        for target, value in (('REGISTRY', path), ('load_registry', lambda: json.loads(path.read_text())), ('GitRepository', self.factory)):
            patcher = patch.object(host_git, target, value); patcher.start(); self.addCleanup(patcher.stop)
        return path

    def saved(self): return {b['prefix']: b for b in json.loads((self.base / 'git.json').read_text())['repositories']}

    def root(self, **extra): return dict(self.binding, uid=1000, gid=1000, **extra)

    def other(self):
        """An independent clone: another editor of the online copy."""
        other = self.base / ('other-' + uuid.uuid4().hex[:6])
        subprocess.check_call([self.git, 'clone', '-q', '-b', 'main', str(self.remote), str(other)], env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return lambda *args: subprocess.check_output([self.git, '-c', 'user.name=Other', '-c', 'user.email=o@example.invalid', *args], cwd=other, env=self.env, stderr=subprocess.DEVNULL).decode().strip()

    def remote_main(self):
        return subprocess.check_output([self.git, '--git-dir', str(self.remote), 'rev-parse', 'main'], env=self.env).decode().strip()

    def register(self, prefix, **extra):
        root = self.saved()['']
        return host_git.register_prefix(host_git.load_registry(), dict({'binding_id': root['id'], 'revision': root['revision'], 'prefix': prefix}, **extra), self.owner, lookup=self.account)

    # ---- H2 --------------------------------------------------------------------------------------------------------
    def test_h2_a_further_folder_registers_while_a_save_waits_and_its_upload_carries_both(self):
        self.registry(self.root())
        req, waiting = self.publish()
        self.assertEqual(waiting['status'], 'committed')
        self.assertNotEqual(self.remote_main(), waiting['commit'])
        created = self.register('bgp')
        self.assertEqual(created['prefix'], 'bgp'); self.assertEqual(sorted(self.saved()), ['', 'bgp'])
        self.assertNotIn('_registered', self.saved()['bgp']); self.assertNotIn('_approved_revisions', self.saved()['bgp'])
        self.assertEqual(self.saved()['bgp']['anchor'], waiting['commit'], 'the anchor is the HEAD it was checked at')
        bgp = dict(self.saved()['bgp'])
        bgp['_approved_revisions'] = [b['revision'] for b in self.saved().values()]   # as main() builds them
        result = self.factory(bgp).dispatch({'mode': 'publish', 'binding_id': bgp['id'], 'revision': bgp['revision'], 'operation_id': uuid.uuid4().hex,
                                             'expected_head': waiting['commit'], 'target': 'latest', 'push': True, 'snapshot': self.capture('bgp\n')})
        self.assertEqual(result['status'], 'synced', result); self.assertEqual(self.remote_main(), result['commit'])

    def test_h2_the_first_folder_of_a_checkout_still_needs_it_synchronized(self):
        self.publish()
        fresh = dict(self.binding, id=uuid.uuid4().hex, prefix='bgp', branch='', push_url='', revision='')
        with self.assertRaisesRegex(ValueError, '^' + host_git.NOT_SYNCHRONIZED + '$'): self.factory(fresh).register(None)
        self.assertEqual(host_git.NOT_SYNCHRONIZED, 'Before linking, synchronize the current branch with its existing remote branch using your ordinary Git login.')

    def test_h2_a_commit_made_by_hand_between_the_remote_and_head_refuses(self):
        self.registry(self.root()); self.publish()
        (self.repo / 'notes.txt').write_text('hand\n'); self.raw('add', 'notes.txt'); self.raw('commit', '-m', 'by hand')
        with self.assertRaisesRegex(ValueError, '^This checkout has commits that were not made by manager saves\\.$'): self.register('bgp')
        self.assertEqual(sorted(self.saved()), [''], 'nothing was registered')

    def test_h2_a_diverged_branch_a_rewritten_remote_and_a_remote_ahead_refuse(self):
        self.registry(self.root())
        other = self.other()
        (self.base / other('rev-parse', '--show-toplevel') / 'x.txt').write_text('remote\n'); other('add', 'x.txt'); other('commit', '-m', 'remote ahead'); other('push', '-q')
        for label in ('remote ahead of the VM', 'diverged'):
            with self.assertRaisesRegex(ValueError, '^The online copy of this repository has changes this VM does not have\\.$', msg=label): self.register('bgp')
            self.publish()   # the second round: a waiting save on the old base, the remote elsewhere
        # Rewritten: the online branch replaced by an unrelated history.
        other('checkout', '-q', '--orphan', 'rewritten'); other('commit', '-q', '-m', 'rewritten', '--allow-empty'); other('push', '-q', '--force', 'origin', 'rewritten:main')
        with self.assertRaisesRegex(ValueError, 'online copy of this repository has changes'): self.register('bgp')
        self.assertEqual(sorted(self.saved()), [''])

    def test_h2_a_remote_commit_missing_here_refuses_even_when_the_fetch_fails(self):
        self.registry(self.root())
        other = self.other()
        other('commit', '-q', '--allow-empty', '-m', 'remote only'); other('push', '-q')
        missing = subprocess.run([self.git, 'cat-file', '-e', self.remote_main()], cwd=self.repo, env=self.env).returncode
        self.assertNotEqual(missing, 0, 'the remote commit is not in the checkout')
        with patch.object(GitRepository, 'fetch_remote', lambda worker, check=True: (1, b'')):
            with self.assertRaisesRegex(ValueError, 'online copy of this repository has changes'): self.register('bgp')

    def test_h2_a_request_cannot_bring_its_own_approval_or_further(self):
        # The only registration of the checkout is on another branch: nothing approves, whatever the request says.
        self.registry(self.root(branch='elsewhere')); _, waiting = self.publish()
        hostile = {'further': True, '_registered': [{'revision': self.binding['revision'], 'branch': 'main', 'push_url': str(self.remote)}],
                   '_approved_revisions': [self.binding['revision']], 'approved_revisions': [self.binding['revision']], 'anchor': waiting['commit']}
        with self.assertRaisesRegex(ValueError, '^' + host_git.NOT_SYNCHRONIZED + '$'): self.register('bgp', **hostile)
        self.assertEqual(sorted(self.saved()), [''])
        _, planned = host_git.plan_prefix(host_git.load_registry(), dict({'binding_id': self.binding['id'], 'revision': self.binding['revision'], 'prefix': 'bgp'}, **hostile), self.account)
        self.assertFalse(set(planned) & set(hostile), 'nothing of the request enters the planned registration')

    def test_h2_connect_for_a_known_checkout_takes_a_further_folder_while_a_save_waits(self):
        self.registry(self.root()); self.publish()
        with patch.object(host_git, 'clone_url', lambda value: value), patch.object(host_git, 'ENGINEER', self.base / 'none.json'):
            result = host_git.connect(host_git.load_registry(), {'url': str(self.remote), 'prefix': 'ospf'}, self.owner, lookup=self.account)
        self.assertEqual(result['prefix'], 'ospf'); self.assertEqual(sorted(self.saved()), ['', 'ospf'])

    def test_h2_root_builds_the_list_from_git_json_and_the_child_filters_it(self):
        mine = self.root(); other_owner = dict(mine, id='o', uid=2000, revision='r-o'); other_path = dict(mine, id='p', path='/elsewhere', revision='r-p')
        side = dict(mine, id='s', prefix='s', branch='dev', revision='r-dev'); retired = dict(mine, id='t', prefix='t', revision='r-t')
        config = {'repositories': [mine, other_owner, other_path, side, retired]}
        planned = dict(mine, id='new', prefix='bgp')
        self.assertEqual([r['revision'] for r in host_git.registered_revisions(config, planned, 't')], [mine['revision'], 'r-dev'])
        worker = self.factory(dict(planned, branch='main', _registered=host_git.registered_revisions(config, planned)))
        self.assertTrue(worker.further()); self.assertEqual(worker.binding['_approved_revisions'], [mine['revision'], 'r-t'])
        lonely = self.factory(dict(planned, branch='main', _registered=[{'revision': 'r-dev', 'branch': 'dev', 'push_url': str(self.remote)}]))
        self.assertFalse(lonely.further()); self.assertEqual(lonely.binding['_approved_revisions'], [])

    def setup_child(self, registry, old, **changes):
        """deploy/setup-git.sh's child exactly: root builds the binding (the folder's own id when it is registered) and
        `_registered` from git.json, the child calls `GitRepository(binding).register(old)`."""
        binding = {k: old[k] for k in ('id', 'label', 'owner', 'uid', 'gid', 'home', 'path', 'remote', 'prefix')}
        binding.update(branch='', push_url='', revision='', **changes)
        binding['_registered'] = host_git.registered_revisions(registry, binding)
        return self.factory(binding).register(old)

    def test_h2_setup_git_re_registers_an_existing_folder_through_the_same_method(self):
        script = (Path(__file__).resolve().parents[2] / 'deploy' / 'setup-git.sh').read_text()
        self.assertIn("binding['_registered']=h.registered_revisions(registry,binding)", script)
        self.assertIn("binding=h.GitRepository(binding).register(old)", script)
        self.assertNotIn('remote_head()', script); self.assertNotIn('check_push_access', script)
        old = dict(self.root(), anchor=self.raw('rev-parse', 'HEAD'))
        _, waiting = self.publish()
        again = self.setup_child({'repositories': [old]}, old)
        self.assertEqual(again['revision'], old['revision'], 'the waiting save keeps its registration')
        self.assertEqual(again['anchor'], old['anchor']); self.assertFalse([k for k in again if k.startswith('_')])
        with self.assertRaisesRegex(ValueError, host_git.NOT_SYNCHRONIZED): self.setup_child({'repositories': []}, dict(old, id=uuid.uuid4().hex, prefix='bgp', revision='other'))
        (self.repo / 'notes.txt').write_text('hand\n'); self.raw('add', 'notes.txt'); self.raw('commit', '-m', 'by hand')
        with self.assertRaisesRegex(ValueError, 'not made by manager saves'): self.setup_child({'repositories': [old]}, old)

    def test_h2_setup_git_with_other_settings_never_strands_a_waiting_save(self):
        # Review must-fix: setup-git.sh without --label gives the folder another label, so registration(old) yields a new
        # revision that would replace the old one in git.json and leave its waiting save unpushable.
        old = dict(self.root(), anchor=self.raw('rev-parse', 'HEAD'))
        _, waiting = self.publish()
        with self.assertRaisesRegex(ValueError, '^A save made in that folder still waits for upload\\.$'):
            self.setup_child({'repositories': [old]}, old, label='repo')
        self.raw('push', '-q', 'origin', 'main')
        renamed = self.setup_child({'repositories': [old]}, old, label='repo')
        self.assertNotEqual(renamed['revision'], old['revision']); self.assertEqual(renamed['label'], 'repo')
        self.assertEqual(renamed['anchor'], waiting['commit'])
        # Unchanged settings keep the revision and need no remote answer about waiting saves.
        self.publish(self.capture('second\n'))
        same = self.setup_child({'repositories': [old]}, old)
        self.assertEqual(same['revision'], old['revision'])

    # ---- H3 --------------------------------------------------------------------------------------------------------
    def commit_folders(self, folders, message='states'):
        for folder, raw in folders.items():
            target = self.repo / folder; target.mkdir(parents=True, exist_ok=True); (target / 'manifest.json').write_bytes(raw)
        self.raw('add', '-A'); self.raw('commit', '-q', '-m', message)
        return self.raw('rev-parse', 'HEAD')

    def manifest(self, **fields):
        value = self.capture()['manifest']; value.update(fields)
        return json.dumps({k: v for k, v in value.items() if v is not Ellipsis}).encode()

    def history(self, worker=None):
        return (worker or self.worker).dispatch(self.request('history'))

    def test_h3_summaries_type_checked_and_bounded(self):
        self.publish(self.capture_schema2())
        capture = self.capture(); topology = b'name: BGP\n'
        capture['manifest']['files'].append(dict(path='BGP.clab.yml', size=len(topology), sha256=hashlib.sha256(topology).hexdigest(), kind='topology'))
        capture['files']['BGP.clab.yml'] = base64.b64encode(topology).decode(); capture['manifest']['files'][0]['short_name'] = 'pe1'
        self.publish(capture, target='baseline')
        bad_entry = json.loads(self.manifest()); bad_entry['files'][0]['restore_artifact'] = 7
        head = self.commit_folders({
            'x/not-json': b'{not json', 'x/big': self.manifest(pad='p' * (300 * 1024)), 'x/name-number': self.manifest(lab_name=5),
            'x/many': json.dumps({'files': [{}] * 10000}).encode(), 'x/bell': self.manifest(lab_name='a\x07b'), 'x/c1': self.manifest(lab_name='a\x85b'),
            'x/copied': self.manifest(lab_name='Someone else'), 'x/long': self.manifest(lab_name='n' * 300), 'x/artifact': json.dumps(bad_entry).encode(),
            'x/list': b'[1, 2]', 'x/deep': b'[' * 100000, 'x/no-files': self.manifest(files=Ellipsis)})
        calls = []
        def spy(*args, **kwargs):
            calls.append(args); return GitRepository.run(self.worker, *args, **kwargs)
        with patch.object(self.worker, 'run', side_effect=spy): result = self.history()
        self.assertEqual(result['head'], head)
        rows = {v['path']: v['summary'] for v in result['versions']}
        self.assertEqual(rows['latest'], {'lab_id': 'bgp', 'lab_name': 'BGP', 'kind': None, 'state': '', 'captured_at': '2026-09-16T00:00:00Z',
                                          'topology_digest': 'a' * 64, 'devices': [{'node': 'PE1', 'short_name': None, 'platform': 'juniper_cjunosevolved', 'restore': True}]})
        self.assertEqual(rows['baseline']['devices'], [{'node': 'PE1', 'short_name': 'pe1', 'platform': 'eos', 'restore': False}], 'an entry of a kind is no device')
        for path in ('x/not-json', 'x/big', 'x/name-number', 'x/many', 'x/bell', 'x/c1', 'x/artifact', 'x/list', 'x/deep', 'x/no-files'):
            self.assertIsNone(rows[path], path)
        self.assertEqual(rows['x/copied']['lab_id'], 'bgp', 'a copied lab id is returned as it is'); self.assertEqual(rows['x/copied']['lab_name'], 'Someone else')
        self.assertEqual(rows['x/long']['lab_name'], 'n' * 200)
        shows = [c for c in calls if c[:1] == ('show',)]
        self.assertEqual(len(shows), 1, 'one git show for every manifest read')
        big = self.raw('rev-parse', head + ':x/big/manifest.json')
        self.assertNotIn(big, shows[0], 'a manifest over 256 KiB is never read')
        self.assertTrue(all(host_git.HEX.fullmatch(a) for a in shows[0][1:]))
        self.assertEqual([c for c in calls if c[:1] == ('ls-tree',)], [('ls-tree', '-r', '-l', '-z', head)])
        text = json.dumps(result)
        self.assertNotIn('router bgp', text); self.assertNotIn('host-name', text); self.assertNotIn('PE1.cfg', text)

    def test_h3_a_lab_state_carries_its_name_through_publish_read_and_summary(self):
        capture = self.capture(); capture['manifest']['state'] = 'start'
        req, result = self.publish(capture, target='checkpoint', checkpoint='start')   # a checkpoint also writes latest
        self.assertEqual(result['status'], 'committed', result)
        read = self.worker.dispatch(self.request('read-version', commit=result['commit'], path='checkpoints/start'))
        self.assertEqual(read['snapshot']['manifest']['state'], 'start')
        self.assertEqual({v['path']: v['summary']['state'] for v in self.history()['versions']}, {'checkpoints/start': 'start', 'latest': 'start'})
        self.assertTrue(snapshot(read['snapshot'])); self.assertEqual(self.worker.read_manifest('checkpoints/start')['state'], 'start')
        self.commit_folders({'s/empty': self.manifest(state=''), 's/number': self.manifest(state=5), 's/null': self.manifest(state=None),
                             's/bell': self.manifest(state='a\x1bb'), 's/long': self.manifest(state='s' * 300)})
        rows = {v['path']: v['summary'] for v in self.history()['versions']}
        for path in ('s/empty', 's/number', 's/null', 's/bell'): self.assertIsNone(rows[path], path)
        self.assertEqual(rows['s/long']['state'], 's' * 200)

    def test_h3_600_states_are_read_in_one_call_and_a_long_list_in_more(self):
        self.publish()
        self.commit_folders({f'course/s{i:03d}': self.manifest(lab_name=f'Lab {i}') for i in range(600)})
        calls = []
        def spy(*args, **kwargs):
            calls.append(args[0]); return GitRepository.run(self.worker, *args, **kwargs)
        with patch.object(self.worker, 'run', side_effect=spy): result = self.history()
        self.assertEqual(len(result['versions']), 501); self.assertEqual(result['versions'][0]['path'], 'latest')
        self.assertTrue(all(v['summary'] for v in result['versions'])); self.assertEqual(calls.count('show'), 1)
        self.assertEqual(result['versions'][1]['summary']['lab_name'], 'Lab 0')
        calls.clear()
        with patch.object(self.worker, 'run', side_effect=spy), patch.object(host_git, 'SHOW_BATCH', 100): result = self.history()
        self.assertEqual(calls.count('show'), 6); self.assertTrue(all(v['summary'] for v in result['versions']))

    def test_h3_the_lab_s_own_states_keep_their_summary_when_the_budget_runs_out(self):
        self.publish(); self.publish(target='baseline'); self.publish(target='checkpoint', checkpoint='one')
        own = sum(int(self.raw('cat-file', '-s', 'HEAD:' + p + '/manifest.json')) for p in ('latest', 'baseline', 'checkpoints/one'))
        self.commit_folders({f'aaa/{i}': self.manifest() for i in range(20)})
        with patch.object(host_git, 'SUMMARY_TOTAL', own + 10): rows = self.history()['versions']
        self.assertEqual([v['path'] for v in rows[:3]], ['baseline', 'checkpoints/one', 'latest'])
        self.assertTrue(all(v['summary'] for v in rows[:3])); self.assertTrue(all(v['summary'] is None for v in rows[3:]))

    def test_h3_output_that_does_not_match_the_sizes_yields_no_summary(self):
        self.publish()
        original = GitRepository.run
        def shifted(*args, **kwargs):
            code, raw = original(self.worker, *args, **kwargs)
            return code, raw + b' '
        with patch.object(self.worker, 'run', side_effect=lambda *a, **k: shifted(*a, **k) if a[:1] == ('show',) else original(self.worker, *a, **k)):
            self.assertIsNone(self.history()['versions'][0]['summary'])

    # ---- H4 --------------------------------------------------------------------------------------------------------
    def empty_remote(self, branch='main'):
        remote = self.base / ('empty-' + uuid.uuid4().hex[:6] + '.git')
        subprocess.check_call([self.git, 'init', '-q', '--bare', '-b', branch, str(remote)], env=self.env)
        return remote

    def pending(self, name='fresh'):
        return {'id': uuid.uuid4().hex, 'label': name, 'owner': 'ben', 'path': str(self.home / 'labs' / name), 'home': str(self.home), 'remote': 'origin',
                'branch': '', 'push_url': '', 'prefix': '', 'revision': '', '_pending': True}

    def identity_env(self):
        return dict(self.env, GIT_AUTHOR_NAME='Ben', GIT_AUTHOR_EMAIL='ben@example.invalid', GIT_COMMITTER_NAME='Ben', GIT_COMMITTER_EMAIL='ben@example.invalid')

    def git_in(self, path, *args):
        return subprocess.run([self.git, *args], cwd=path, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

    def clone_state(self, path):
        """Everything a failed start must leave as it was: HEAD, refs, index and working files."""
        return (self.git_in(path, 'symbolic-ref', 'HEAD').stdout, self.git_in(path, 'for-each-ref').stdout, (path / '.git' / 'index').exists(),
                sorted(p.name for p in path.iterdir()))

    def test_h4_an_empty_repository_is_refused_without_initialize_and_started_with_it(self):
        remote = self.empty_remote(); binding = self.pending(); path = Path(binding['path'])
        with self.assertRaisesRegex(ValueError, '^This repository has no commits yet'):
            GitRepository(binding, git=self.git, allow_local=True, env=self.identity_env()).connect(str(remote))
        self.assertEqual(self.git_in(remote, 'for-each-ref').stdout, b'', 'nothing was pushed')
        self.assertTrue((path / '.git').is_dir())
        result = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env()).connect(str(remote), True)
        head = self.git_in(path, 'rev-parse', 'HEAD').stdout.decode().strip()
        self.assertEqual((result['branch'], result['anchor']), ('main', head))
        self.assertEqual(self.git_in(remote, 'rev-parse', 'refs/heads/main').stdout.decode().strip(), head)
        self.assertEqual(self.git_in(path, 'ls-tree', '-r', '--name-only', head).stdout, b'README.md\n', 'no path but README.md')
        self.assertEqual(self.git_in(path, 'show', head + ':README.md').stdout, host_git.START_README)
        self.assertEqual(self.git_in(path, 'rev-list', '--parents', '-n', '1', head).stdout.decode().split(), [head])
        self.assertEqual((path / 'README.md').read_bytes(), host_git.START_README, 'the working tree is populated')
        self.assertEqual(self.git_in(path, 'status', '--porcelain').stdout, b'')
        self.assertEqual(sorted(p.name for p in (path / '.git' / 'clab-manager').iterdir() if p.name.startswith('start-')), [], 'no temporary file is left')
        self.assertNotIn(b'Ben', host_git.START_README); self.assertNotIn(b'20', host_git.START_README)

    def test_h4_the_branch_the_clone_s_head_names_is_used(self):
        remote = self.empty_remote('trunk'); binding = self.pending('trunk-lab')
        result = GitRepository(binding, git=self.git, allow_local=True, env=self.identity_env()).connect(str(remote), True)
        self.assertEqual(result['branch'], 'trunk'); self.assertEqual(self.git_in(remote, 'for-each-ref', '--format=%(refname)').stdout, b'refs/heads/trunk\n')

    def test_h4_a_failed_push_leaves_the_clone_as_it_was_and_the_retry_succeeds(self):
        remote = self.empty_remote(); binding = self.pending(); path = Path(binding['path'])
        with self.assertRaisesRegex(ValueError, 'no commits yet'): GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env()).connect(str(remote))
        before = self.clone_state(path)
        worker = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env())
        original = worker.run
        with patch.object(worker, 'run', side_effect=lambda *a, **k: (1, b'') if a[:1] == ('push',) else original(*a, **k)):
            with self.assertRaisesRegex(ValueError, '^' + host_git.START_FAILED + '$'): worker.connect(str(remote), True)
        self.assertEqual(self.clone_state(path), before); self.assertEqual(self.git_in(remote, 'for-each-ref').stdout, b'')
        result = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env()).connect(str(remote), True)
        self.assertEqual(result['branch'], 'main')

    def test_h4_a_failure_after_the_push_is_resumed_by_the_retry(self):
        remote = self.empty_remote(); binding = self.pending(); path = Path(binding['path'])
        worker = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env())
        original = worker.run
        with patch.object(worker, 'run', side_effect=lambda *a, **k: (1, b'') if a[:1] == ('merge',) else original(*a, **k)):
            with self.assertRaisesRegex(ValueError, host_git.START_FAILED): worker.connect(str(remote), True)
        pushed = self.git_in(remote, 'rev-parse', 'refs/heads/main').stdout.decode().strip()
        self.assertEqual(self.git_in(path, 'rev-parse', '--verify', '-q', 'HEAD').returncode, 1, 'the local branch is still unborn')
        result = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env()).connect(str(remote), True)
        self.assertEqual(result['anchor'], pushed, 'the retry finishes the clone with the start commit already pushed')
        self.assertEqual(self.git_in(remote, 'rev-list', '--count', 'main').stdout.strip(), b'1')

    def seed(self, remote, branch='main', message='someone else', readme=None, tag=None):
        """Another clone pushes to `remote`: one commit on `branch` (README.md as given), or only a tag."""
        seed = self.base / ('seed-' + uuid.uuid4().hex[:6]); subprocess.check_call([self.git, 'init', '-q', '-b', branch, str(seed)], env=self.env)
        if readme is not None: (seed / 'README.md').write_bytes(readme); self.git_in(seed, 'add', 'README.md')
        self.git_in(seed, '-c', 'user.name=S', '-c', 'user.email=s@x', 'commit', '-q', '--allow-empty', '-m', message)
        self.assertEqual(self.git_in(seed, 'push', '-q', str(remote), ('refs/heads/' + branch + ':refs/tags/' + tag) if tag else branch).returncode, 0)
        return self.git_in(seed, 'rev-parse', 'HEAD').stdout.decode().strip()

    def connect_pending(self, binding, remote, initialize=False):
        return GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env()).connect(str(remote), initialize)

    def test_h4_a_branch_appearing_before_the_push_is_refused_and_the_clone_untouched(self):
        remote = self.empty_remote(); binding = self.pending(); path = Path(binding['path'])
        worker = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env())
        original = worker.run
        def race(*args, **kwargs):
            if args[:1] == ('push',): self.seed(remote)
            return original(*args, **kwargs)
        self.git_in(self.base, 'clone', '-q', str(remote), str(path)); before = self.clone_state(path)
        with patch.object(worker, 'run', side_effect=race):
            with self.assertRaisesRegex(ValueError, '^' + host_git.START_FAILED + '$'): worker.connect(str(remote), True)
        self.assertEqual(self.clone_state(path), before)
        self.assertEqual(self.git_in(remote, 'log', '-1', '--format=%s', 'main').stdout.strip(), b'someone else')
        # The repository is no longer empty: connecting again finishes the clone with its branch; nothing is pushed.
        result = self.connect_pending(binding, remote)
        self.assertEqual(result['anchor'], self.git_in(remote, 'rev-parse', 'main').stdout.decode().strip())
        self.assertEqual(self.git_in(remote, 'rev-list', '--count', 'main').stdout.strip(), b'1')

    def test_h4_another_ref_appearing_after_the_push_is_said_and_the_retry_finishes(self):
        remote = self.empty_remote(); binding = self.pending(); path = Path(binding['path'])
        worker = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env())
        original = worker.run
        def race(*args, **kwargs):
            result = original(*args, **kwargs)
            if args[:1] == ('push',): self.seed(remote, branch='dev', message='other branch')
            return result
        with patch.object(worker, 'run', side_effect=race):
            with self.assertRaisesRegex(ValueError, '^README.md was pushed to start the repository, but other branches or tags appeared'): worker.connect(str(remote), True)
        self.assertEqual(self.git_in(path, 'rev-parse', '--verify', '-q', 'HEAD').returncode, 1, 'the clone is still unborn')
        pushed = self.git_in(remote, 'rev-parse', 'main').stdout.decode().strip()
        self.assertEqual(self.connect_pending(binding, remote)['anchor'], pushed)
        self.assertEqual((path / 'README.md').read_bytes(), host_git.START_README)

    def test_h4_a_repository_with_only_a_dev_branch_or_only_a_tag_is_not_empty(self):
        for label, kwargs in (('dev', {'branch': 'dev'}), ('tag', {'tag': 'v1'})):
            remote = self.empty_remote(); self.seed(remote, **kwargs)
            binding = self.pending('lab-' + label); path = Path(binding['path'])
            sentence = '^The repository has branches or tags but no branch main, which the VM folder ' + str(path) + ' was cloned for; nothing was changed\\.$'
            with self.assertRaisesRegex(ValueError, sentence, msg=label): self.connect_pending(binding, remote)
            before = self.clone_state(path)
            with self.assertRaisesRegex(ValueError, sentence, msg=label): self.connect_pending(binding, remote, True)
            self.assertEqual(self.clone_state(path), before)
            self.assertEqual(self.git_in(remote, 'for-each-ref', '--format=%(refname)').stdout, b'refs/heads/dev\n' if label == 'dev' else b'refs/tags/v1\n')

    def test_h4_a_readme_added_online_after_a_refused_connect_finishes_the_clone(self):
        remote = self.empty_remote(); binding = self.pending(); path = Path(binding['path'])
        with self.assertRaisesRegex(ValueError, '^' + host_git.EMPTY_REPOSITORY + '$'): self.connect_pending(binding, remote)
        added = self.seed(remote, readme=b'# Course\n', message='Initial commit')
        self.assertNotEqual(self.git_in(path, 'cat-file', '-e', added).returncode, 0, 'that commit is not in this clone yet')
        result = self.connect_pending(binding, remote)
        self.assertEqual(result['anchor'], added); self.assertEqual((path / 'README.md').read_text(), '# Course\n')
        self.assertEqual(self.git_in(remote, 'rev-list', '--count', 'main').stdout.strip(), b'1', 'nothing was pushed')

    def test_h4_a_repository_another_vm_started_is_finished_here(self):
        remote = self.empty_remote(); first = self.pending('first'); second = self.pending('second')
        with self.assertRaisesRegex(ValueError, 'no commits yet'): self.connect_pending(second, remote)
        started = self.connect_pending(first, remote, True)['anchor']
        self.assertNotEqual(self.git_in(Path(second['path']), 'cat-file', '-e', started).returncode, 0, 'a README root commit not made by this clone')
        self.assertEqual(self.connect_pending(second, remote, True)['anchor'], started)
        self.assertEqual(self.git_in(remote, 'rev-list', '--count', 'main').stdout.strip(), b'1')

    def test_h4_root_wiring_reaches_the_owner_s_connect_for_real(self):
        self.registry(self.root()); remote = self.empty_remote()
        patches = (patch.object(host_git, 'GitRepository', lambda binding: GitRepository(binding, git=self.git, allow_local=True, env=self.identity_env())),
                   patch.object(host_git, 'clone_url', lambda value: value), patch.object(host_git, 'ENGINEER', self.base / 'none.json'))
        with patches[0], patches[1], patches[2]:
            with self.assertRaisesRegex(ValueError, '^' + host_git.EMPTY_REPOSITORY + '$'):
                host_git.connect(host_git.load_registry(), {'url': str(remote), 'prefix': ''}, self.owner, lookup=self.account)
            with self.assertRaisesRegex(ValueError, '^Invalid connect option\\.$'):
                host_git.connect(host_git.load_registry(), {'url': str(remote), 'prefix': '', 'initialize': 'true'}, self.owner, lookup=self.account)
            self.assertEqual(self.git_in(remote, 'for-each-ref').stdout, b'')
            result = host_git.connect(host_git.load_registry(), {'url': str(remote), 'prefix': '', 'initialize': True}, self.owner, lookup=self.account)
        self.assertEqual(result['branch'], 'main'); self.assertEqual(result['path'], str(self.home / 'labs' / remote.name.removesuffix('.git')))
        self.assertIn(result['id'], [b['id'] for b in self.saved().values()])
        self.assertEqual(self.git_in(remote, 'ls-tree', '-r', '--name-only', 'main').stdout, b'README.md\n')

    def test_h4_initialize_must_be_a_boolean(self):
        self.registry(self.root())
        for value in ('yes', 1, None, [], {}):
            with self.assertRaisesRegex(ValueError, '^Invalid connect option\\.$'):
                host_git.connect(host_git.load_registry(), {'url': 'https://github.com/Owner/Empty', 'prefix': '', 'initialize': value},
                                 lambda *a: self.fail('nothing runs as the owner'), lookup=self.account)

    def test_h4_files_in_the_clone_folder_or_a_foreign_owner_refuse_before_anything_is_written(self):
        remote = self.empty_remote(); binding = self.pending(); path = Path(binding['path'])
        self.git_in(self.base, 'clone', '-q', str(remote), str(path)); (path / 'README.md').write_text('mine\n')
        with self.assertRaisesRegex(ValueError, '^The VM folder ' + str(path) + ' holds files that are not in the repository; nothing was changed\\.$'):
            self.connect_pending(binding, remote, True)
        self.assertEqual((path / 'README.md').read_text(), 'mine\n'); self.assertEqual(self.git_in(remote, 'for-each-ref').stdout, b'')
        (path / 'README.md').unlink()
        def foreign(worker): raise ValueError('The checkout and .git must be owned by the registered account.')
        objects = sorted(str(p) for p in (path / '.git' / 'objects').rglob('*'))
        with patch.object(GitRepository, 'check_owner', foreign):
            with self.assertRaisesRegex(ValueError, 'must be owned'): self.connect_pending(binding, remote, True)
        self.assertEqual(sorted(str(p) for p in (path / '.git' / 'objects').rglob('*')), objects, 'no object was written')
        self.assertEqual(self.git_in(remote, 'for-each-ref').stdout, b'')

    # ---- H5 --------------------------------------------------------------------------------------------------------
    def test_h5_browse_lists_every_directory_of_a_large_tree(self):
        expected = set()
        for i in range(300):
            folder = self.repo / f'course/week{i // 30:02d}/lab{i:03d}'; folder.mkdir(parents=True)
            expected.update({f'course', f'course/week{i // 30:02d}', f'course/week{i // 30:02d}/lab{i:03d}'})
            for j in range(17): (folder / f'f{j}.txt').write_text('x')
        self.raw('add', '-A'); self.raw('commit', '-q', '-m', 'big')
        result = self.worker.dispatch(self.request('browse'))
        self.assertTrue(result['truncated']); self.assertEqual(len(result['files']), 4000, 'the file list keeps its cap')
        self.assertEqual(set(result['dirs']), expected); self.assertEqual(len(result['dirs']), len(expected)); self.assertFalse(result['dirs_truncated'])
        with patch.object(host_git, 'MAX_DIRS', 10): capped = self.worker.dispatch(self.request('browse'))
        self.assertEqual(len(capped['dirs']), 10); self.assertTrue(capped['dirs_truncated'])

    # ---- H6 --------------------------------------------------------------------------------------------------------
    def test_h6_compare_names_every_outgoing_commit(self):
        first, saved = self.publish()
        eth_binding, eth = self.sibling('eth')
        eth_req = {'mode': 'publish', 'binding_id': eth_binding['id'], 'revision': eth_binding['revision'], 'operation_id': uuid.uuid4().hex,
                   'expected_head': self.raw('rev-parse', 'HEAD'), 'target': 'latest', 'push': False, 'snapshot': self.capture('eth\n')}
        eth_save = eth.dispatch(eth_req)
        (self.repo / 'notes.txt').write_text('hand\n'); self.raw('add', 'notes.txt'); self.raw('commit', '-m', 'Notes by hand ' + 'x' * 300)
        hand = self.raw('rev-parse', 'HEAD')
        result = self.worker.dispatch(self.request('compare', operation_id=first['operation_id']))
        self.assertEqual(result['files'][0]['status'], 'added')
        self.assertEqual([(c['commit'], c['operation_id']) for c in result['outgoing']],
                         [(saved['commit'], first['operation_id']), (eth_save['commit'], eth_req['operation_id']), (hand, None)])
        self.assertEqual(result['outgoing'][0]['files'], ['latest/PE1.cfg', 'latest/manifest.json'])
        self.assertEqual(result['outgoing'][1]['files'], ['eth/latest/PE1.cfg', 'eth/latest/manifest.json'])
        self.assertEqual(result['outgoing'][2]['files'], ['notes.txt'])
        self.assertTrue(result['outgoing'][0]['subject'].startswith('Save BGP progress'))
        self.assertEqual(len(result['outgoing'][2]['subject']), 200); self.assertFalse(result['outgoing_truncated'])
        with patch.object(host_git, 'MAX_OUTGOING', 2): capped = self.worker.dispatch(self.request('compare', operation_id=first['operation_id']))
        self.assertEqual([c['commit'] for c in capped['outgoing']], [eth_save['commit'], hand]); self.assertTrue(capped['outgoing_truncated'])
        self.raw('push', '-q', 'origin', 'main')
        self.assertEqual(self.worker.dispatch(self.request('compare', operation_id=first['operation_id']))['outgoing'], [])

    def test_h6_an_unreachable_remote_answers_null_and_the_comparison_still_works(self):
        first, _ = self.publish()
        away = self.remote.with_name('away.git'); os.rename(self.remote, away)
        try: result = self.worker.dispatch(self.request('compare', operation_id=first['operation_id']))
        finally: os.rename(away, self.remote)
        self.assertIsNone(result['outgoing']); self.assertEqual(result['files'][0]['after'], 'router bgp 65001\n')

    # ---- H7 --------------------------------------------------------------------------------------------------------
    def test_h7_a_waiting_save_blocks_the_retire_in_both_shapes_and_an_uploaded_one_does_not(self):
        eth = dict(self.root(), id=uuid.uuid4().hex, prefix='eth', revision='r-eth')
        self.registry(self.root(), eth); before = (self.base / 'git.json').read_text()
        self.publish()
        for prefix in ('bgp', 'eth'):   # a new folder replacing the source, and add=False next to an existing one
            with self.assertRaisesRegex(ValueError, '^A save made in that folder still waits for upload\\.$'): self.register(prefix, retire=True)
            self.assertEqual((self.base / 'git.json').read_text(), before, 'nothing is written')
        for word in ('registration', 'prefix', 'overlap'): self.assertNotIn(word, host_git.SAVE_WAITS + host_git.SAVE_UNKNOWN)
        self.raw('push', '-q', 'origin', 'main')
        self.assertEqual(self.register('eth', retire=True)['id'], eth['id'])
        self.assertEqual(sorted(self.saved()), ['eth'])

    def test_h7_an_unreachable_remote_blocks_the_retire_only_when_a_save_could_wait(self):
        self.registry(self.root()); before = (self.base / 'git.json').read_text()
        self.publish(push=False)   # S1c: a save marked pushed no longer asks the remote, so the waiting one is unpushed
        away = self.remote.with_name('away.git'); os.rename(self.remote, away)
        try:
            with self.assertRaisesRegex(ValueError, '^The online copy could not be asked whether a save made in that folder still waits for upload\\.$'):
                self.register('bgp', retire=True)
        finally: os.rename(away, self.remote)
        self.assertEqual((self.base / 'git.json').read_text(), before)
        # A registration without any save of its own asks nobody.
        fresh = dict(self.root(), id=uuid.uuid4().hex, prefix='fresh', revision='r-fresh')
        worker = self.factory(dict(fresh, push_url=str(away)))
        self.assertIsNone(worker.check_retire())

    def test_h7_the_check_holds_the_checkout_lock(self):
        self.publish()
        with self.worker.lock():
            with self.assertRaisesRegex(ValueError, 'Another Git operation'): self.factory(dict(self.binding)).check_retire()


class RegistrySizeTests(unittest.TestCase):
    """Review F13: a registry of 4000 registrations still loads; one over 2 MiB is refused as before."""
    def test_4000_registrations_load_and_2_mib_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'git.json'
            rows = [{'id': uuid.uuid4().hex, 'label': f'Course / lab{i:04d}', 'owner': 'ben', 'uid': 1000, 'gid': 1000, 'home': '/home/ben',
                     'path': '/home/ben/labs/Course', 'remote': 'origin', 'prefix': f'week{i // 100:02d}/lab{i:04d}', 'branch': 'main',
                     'push_url': 'https://github.com/Owner/Course.git', 'revision': hashlib.sha256(str(i).encode()).hexdigest(), 'anchor': 'a' * 40} for i in range(4000)]
            path.write_text(json.dumps({'repositories': rows}, sort_keys=True, ensure_ascii=False))
            self.assertLess(path.stat().st_size, host_git.MAX_FILE)
            with patch.object(host_git, 'REGISTRY', path), patch.object(host_git, 'root_file'):
                self.assertEqual(len(host_git.load_registry()['repositories']), 4000)
                path.write_text(json.dumps({'repositories': rows, 'pad': 'x' * host_git.MAX_FILE}))
                with self.assertRaisesRegex(ValueError, 'too large'): host_git.load_registry()


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class HelperReviewFollowUpTests(unittest.TestCase):
    """The risk review of S1 (items 3 to 7 and 10): who waits for a retire, `approved`, display texts, response budgets,
    and the remote calls of `outgoing`."""
    setUp = HostGitTests.setUp
    raw = HostGitTests.raw; request = HostGitTests.request; publish = HostGitTests.publish; capture = HostGitTests.capture
    account = HostGitPlacesTests.account; sibling = HostGitPlacesTests.sibling
    factory = HelperRedesignTests.factory; other = HelperRedesignTests.other; commit_folders = HelperRedesignTests.commit_folders
    manifest = HelperRedesignTests.manifest

    def sibling_save(self, prefix='eth', text='eth\n'):
        binding, worker = self.sibling(prefix)
        req = {'mode': 'publish', 'binding_id': binding['id'], 'revision': binding['revision'], 'operation_id': uuid.uuid4().hex,
               'expected_head': self.raw('rev-parse', 'HEAD'), 'target': 'latest', 'push': False, 'snapshot': self.capture(text)}
        return binding, req, worker.dispatch(req)

    # ---- item 3: H7 decides "waits" by reachability, verified or not --------------------------------------------------
    def test_an_unverified_journal_with_a_commit_blocks_the_retire(self):
        req, saved = self.publish()
        journal = self.worker.load_journal(req['operation_id']); journal.update(verified=False, status='needs_attention'); self.worker.save_journal(journal)
        with self.assertRaisesRegex(ValueError, '^' + host_git.SAVE_WAITS + '$'): self.factory(dict(self.binding)).check_retire()

    def test_a_commit_head_no_longer_reaches_does_not_wait_and_asks_nobody(self):
        req, saved = self.publish()
        self.raw('reset', '-q', '--hard', 'origin/main')   # the owner dropped the save by hand
        worker = self.factory(dict(self.binding))
        with patch.object(worker, 'remote_head', side_effect=AssertionError('no remote question for nothing waiting')):
            self.assertIsNone(worker.check_retire())
        journal = self.worker.load_journal(req['operation_id']); journal['commit'] = 'f' * 40; self.worker.save_journal(journal)
        self.assertIsNone(self.factory(dict(self.binding)).check_retire(), 'a commit missing from the checkout cannot wait')

    def test_a_sibling_registration_s_waiting_save_does_not_block(self):
        self.publish(push=True)
        eth_binding, _, result = self.sibling_save()
        self.assertEqual(result['status'], 'committed')
        self.assertIsNone(self.factory(dict(self.binding)).check_retire())
        with self.assertRaisesRegex(ValueError, host_git.SAVE_WAITS): self.factory(dict(eth_binding)).check_retire()

    # ---- item 4: approved -----------------------------------------------------------------------------------------
    def test_outgoing_rows_say_whether_a_push_would_accept_them(self):
        own, saved = self.publish()
        _, eth_req, eth_save = self.sibling_save()
        (self.repo / 'notes.txt').write_text('hand\n'); self.raw('add', 'notes.txt'); self.raw('commit', '-q', '-m', 'by hand')
        rows = self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))['outgoing']
        self.assertEqual([(r['operation_id'], r['approved']) for r in rows],
                         [(own['operation_id'], True), (eth_req['operation_id'], False), (None, False)],
                         'a save under a registration main() does not approve has its operation and approved false')
        self.binding['_approved_revisions'] = [self.binding['revision'], hashlib.sha256(b'eth').hexdigest()]
        rows = self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))['outgoing']
        self.assertEqual([r['approved'] for r in rows], [True, True, False])
        journal = self.worker.load_journal(own['operation_id']); journal['verified'] = False; self.worker.save_journal(journal)
        self.assertFalse(self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))['outgoing'][0]['approved'])

    # ---- item 5: display texts --------------------------------------------------------------------------------------
    def test_subjects_and_summary_strings_drop_control_and_bidi_characters(self):
        own, _ = self.publish()
        (self.repo / 'notes.txt').write_text('x\n'); self.raw('add', 'notes.txt')
        self.raw('commit', '-q', '-m', 'evil‮⁦gnp.exe\x1b[31m ' + 'y' * 300)
        subject = self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))['outgoing'][-1]['subject']
        self.assertTrue(subject.startswith('evilgnp.exe[31m y')); self.assertEqual(len(subject), 200)
        self.assertFalse(any(unicodedata.category(c) in ('Cc', 'Cf', 'Zl', 'Zp') for c in subject))
        self.commit_folders({'s/bidi': self.manifest(lab_name='Lab‮A‏', state='st⁧art')})
        summary = {v['path']: v['summary'] for v in self.worker.dispatch(self.request('history'))['versions']}['s/bidi']
        self.assertEqual((summary['lab_name'], summary['state']), ('LabA', 'start'))
        self.commit_folders({'s/only-bidi': self.manifest(state='‮')})
        self.assertIsNone({v['path']: v['summary'] for v in self.worker.dispatch(self.request('history'))['versions']}['s/only-bidi'])

    # ---- item 6 and 10: the remote calls of outgoing ------------------------------------------------------------------
    def test_outgoing_asks_for_15_seconds_and_fetches_for_20_only_when_the_remote_commit_is_missing(self):
        own, saved = self.publish()
        calls = []
        real_head, real_fetch = GitRepository.remote_head, GitRepository.fetch_remote
        def head(worker, timeout=45): calls.append(('ls-remote', timeout)); return real_head(worker, timeout=timeout)
        def fetch(worker, check=True, timeout=60): calls.append(('fetch', timeout)); return real_fetch(worker, check=check, timeout=timeout)
        with patch.object(GitRepository, 'remote_head', head), patch.object(GitRepository, 'fetch_remote', fetch):
            rows = self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))['outgoing']
            self.assertEqual(calls, [('ls-remote', 15)], 'the VM is ahead: the remote commit is here, no fetch')
            self.assertEqual([r['commit'] for r in rows], [saved['commit']])
            other = self.other(); other('commit', '-q', '--allow-empty', '-m', 'remote only'); other('push', '-q')
            remote = other('rev-parse', 'HEAD'); self.assertNotEqual(subprocess.run([self.git, 'cat-file', '-e', remote], cwd=self.repo, env=self.env).returncode, 0)
            calls.clear(); rows = self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))['outgoing']
            self.assertEqual(calls, [('ls-remote', 15), ('fetch', 20)])
            self.assertEqual([r['commit'] for r in rows], [saved['commit']], 'after the fetch the diverged save is still listed')
        with patch.object(GitRepository, 'fetch_remote', lambda worker, check=True, timeout=60: (_ for _ in ()).throw(ValueError('down'))):
            other('commit', '-q', '--allow-empty', '-m', 'again'); other('push', '-q')
            self.assertIsNone(self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))['outgoing'])

    # ---- item 7: response budgets ---------------------------------------------------------------------------------------
    def test_summaries_dirs_and_outgoing_degrade_by_bytes_with_their_flags(self):
        own, _ = self.publish(); self.publish(target='baseline')
        self.commit_folders({f'aaa/{i:02d}': self.manifest(lab_name='n' * 150) for i in range(10)})
        full = self.worker.dispatch(self.request('history'))
        self.assertFalse(full['summaries_truncated']); self.assertTrue(all(v['summary'] for v in full['versions']))
        own_size = sum(len(json.dumps(v['summary'], ensure_ascii=False).encode()) for v in full['versions'][:2])
        with patch.object(host_git, 'SUMMARY_BYTES', own_size + 10): capped = self.worker.dispatch(self.request('history'))
        self.assertTrue(capped['summaries_truncated'])
        self.assertTrue(all(v['summary'] for v in capped['versions'][:2]), "the lab's own states keep theirs")
        self.assertTrue(all(v['summary'] is None for v in capped['versions'][2:]))
        with patch.object(host_git, 'DIRS_BYTES', 20): browsed = self.worker.dispatch(self.request('browse'))
        self.assertTrue(browsed['dirs_truncated']); self.assertLess(sum(len(d) + 3 for d in browsed['dirs']), 21)
        for i in range(3):
            (self.repo / f'n{i}.txt').write_text('x\n'); self.raw('add', f'n{i}.txt'); self.raw('commit', '-q', '-m', f'note {i}')
        with patch.object(host_git, 'OUTGOING_BYTES', 700): result = self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))
        self.assertTrue(result['outgoing_truncated']); self.assertGreaterEqual(len(result['outgoing']), 1)
        self.assertEqual(result['outgoing'][-1]['subject'], 'note 2', 'the budget keeps the newest commits, oldest first')


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class HelperSecondReviewTests(unittest.TestCase):
    """The second risk review of the helper (S1c): the waiting-save check follows the registration's own branch, runs
    last in register() with the lock held to its return, ignores uploaded saves; latest keeps its summary; texts."""
    setUp = HostGitTests.setUp
    raw = HostGitTests.raw; request = HostGitTests.request; publish = HostGitTests.publish; capture = HostGitTests.capture
    account = HostGitPlacesTests.account
    factory = HelperRedesignTests.factory; root = HelperRedesignTests.root; setup_child = HelperRedesignTests.setup_child
    commit_folders = HelperRedesignTests.commit_folders; manifest = HelperRedesignTests.manifest
    empty_remote = HelperRedesignTests.empty_remote; pending = HelperRedesignTests.pending; identity_env = HelperRedesignTests.identity_env
    git_in = HelperRedesignTests.git_in; connect_pending = HelperRedesignTests.connect_pending

    def test_a_branch_switch_does_not_hide_a_waiting_save(self):
        old = dict(self.root(), anchor=self.raw('rev-parse', 'HEAD'))
        _, waiting = self.publish()
        self.raw('switch', '-q', '-c', 'other', 'origin/main')
        self.raw('push', '-q', 'origin', 'other')
        with self.assertRaisesRegex(ValueError, '^' + host_git.SAVE_WAITS + '$'):
            self.setup_child({'repositories': [old]}, old, label='moved')
        with self.assertRaisesRegex(ValueError, host_git.SAVE_WAITS): self.factory(dict(old)).check_retire()
        self.raw('push', '-q', 'origin', 'main')   # uploaded from the registered branch: nothing waits any more
        self.assertIsNone(self.factory(dict(old)).check_retire())

    def test_the_waiting_check_runs_last_with_the_lock_held_to_the_return(self):
        old = dict(self.root(), anchor=self.raw('rev-parse', 'HEAD'))
        self.publish(push=True)
        order = []; real_push, real_waiting = GitRepository.check_push_access, GitRepository.check_waiting
        def push(worker): order.append('push check'); return real_push(worker)
        def waiting(worker, uploaded=None):
            real_waiting(worker, uploaded=uploaded); order.append('waiting check')
            with self.assertRaisesRegex(ValueError, 'Another Git operation'):
                with self.factory(dict(self.binding)).lock(): pass
        with patch.object(GitRepository, 'check_push_access', push), patch.object(GitRepository, 'check_waiting', waiting):
            renamed = self.setup_child({'repositories': [old]}, old, label='renamed')
        self.assertEqual(order, ['push check', 'waiting check']); self.assertNotEqual(renamed['revision'], old['revision'])
        with self.factory(dict(self.binding)).lock(): pass   # released once register() returned

    def test_an_uploaded_save_never_asks_the_remote_so_a_gone_remote_can_be_repaired(self):
        old = dict(self.root(), anchor=self.raw('rev-parse', 'HEAD'))
        self.publish(push=True)
        worker = self.factory(dict(old))
        with patch.object(worker, 'remote_head', side_effect=AssertionError('nothing waits: the remote is not asked')):
            self.assertIsNone(worker.check_retire())

    def test_latest_keeps_its_summary_when_own_checkpoints_exhaust_the_budget(self):
        self.publish()
        for i in range(6): self.publish(target='checkpoint', checkpoint=f'c{i}')
        latest = int(self.raw('cat-file', '-s', 'HEAD:latest/manifest.json'))
        for name, value in (('SUMMARY_TOTAL', latest + 10), ('SUMMARY_BYTES', 400)):
            with patch.object(host_git, name, value): result = self.worker.dispatch(self.request('history'))
            rows = {v['path']: v['summary'] for v in result['versions']}
            self.assertIsNotNone(rows['latest'], name); self.assertTrue(result['summaries_truncated'], name)
            self.assertIsNone(rows['checkpoints/c5'], name)
            self.assertEqual([v['path'] for v in result['versions']][:2], ['checkpoints/c0', 'checkpoints/c1'], 'the list order stays')

    def test_history_messages_go_through_the_display_filter(self):
        (self.repo / 'latest').mkdir(); (self.repo / 'latest' / 'notes.txt').write_text('x\n'); self.raw('add', 'latest')
        self.raw('commit', '-q', '-m', 'Save\u202e\u200b\u2028 BGP\x07 ' + 'm' * 600)
        message = self.worker.dispatch(self.request('history'))['commits'][0]['message']
        # S1d: Git cuts the subject to 500 columns (ending in '..'), the filter then drops the invisible characters.
        self.assertLessEqual(len(message), 500); self.assertGreater(len(message), 480); self.assertTrue(message.startswith('Save BGP m'))

    def test_a_failed_listing_after_the_start_push_is_finished_by_the_retry(self):
        remote = self.empty_remote(); binding = self.pending(); path = Path(binding['path'])
        worker = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env())
        original = worker.run; pushed = []
        def listing_fails(*args, **kwargs):
            if args[:1] == ('push',): pushed.append(True)
            if args[:1] == ('ls-remote',) and pushed: return 128, b''
            return original(*args, **kwargs)
        with patch.object(worker, 'run', side_effect=listing_fails):
            with self.assertRaisesRegex(ValueError, '^' + host_git.START_FAILED + '$'): worker.connect(str(remote), True)
        self.assertEqual(self.git_in(path, 'rev-parse', '--verify', '-q', 'HEAD').returncode, 1)
        started = self.git_in(remote, 'rev-parse', 'main').stdout.decode().strip()
        self.assertEqual(self.connect_pending(binding, remote)['anchor'], started)
        self.assertEqual(self.git_in(remote, 'rev-list', '--count', 'main').stdout.strip(), b'1')

    def test_a_missing_finishing_commit_leaves_head_as_it_was(self):
        remote = self.empty_remote(); binding = self.pending('trunkless'); path = Path(binding['path'])
        with self.assertRaisesRegex(ValueError, 'no commits yet'): self.connect_pending(binding, remote)
        HelperRedesignTests.seed(self, remote)
        head = self.git_in(path, 'symbolic-ref', 'HEAD').stdout
        worker = GitRepository(dict(binding), git=self.git, allow_local=True, env=self.identity_env()); original = worker.run
        with patch.object(worker, 'run', side_effect=lambda *a, **k: (1, b'') if a[:1] == ('fetch',) else original(*a, **k)):
            with self.assertRaisesRegex(ValueError, 'could not take the repository'): worker.connect(str(remote))
        self.assertEqual(self.git_in(path, 'symbolic-ref', 'HEAD').stdout, head)

    def test_outgoing_always_names_the_newest_commit(self):
        own, _ = self.publish()
        for i in range(40): (self.repo / f'f{i:02d}.txt').write_text('x\n')
        self.raw('add', '-A'); self.raw('commit', '-q', '-m', 'many files')
        with patch.object(host_git, 'OUTGOING_BYTES', 300): result = self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))
        self.assertEqual([r['subject'] for r in result['outgoing']], ['many files']); self.assertTrue(result['outgoing_truncated'])
        self.assertLess(len(result['outgoing'][0]['files']), 40)
        (self.worker.state / 'journals' / ('f' * 32 + '.json')).write_text('{corrupt')
        result = self.worker.dispatch(self.request('compare', operation_id=own['operation_id']))
        self.assertIsNotNone(result['outgoing'], 'a corrupt journal is not "the remote cannot be asked"')

    def test_setup_git_keeps_the_folder_s_label_when_none_is_given(self):
        # S1d: by behaviour, through the function the script's child calls, and the revision it then keeps.
        script = (Path(__file__).resolve().parents[2] / 'deploy' / 'setup-git.sh').read_text()
        self.assertIn("label=h.default_label(label,old,path)", script)
        self.assertLess(script.index("old=next("), script.index("label=h.default_label"))
        old = dict(self.root(), label='Course BGP', anchor=self.raw('rev-parse', 'HEAD'))
        self.assertEqual(host_git.default_label('', old, Path(self.repo)), 'Course BGP')
        self.assertEqual(host_git.default_label('', None, Path(self.repo)), 'repo')
        self.assertEqual(host_git.default_label('Given', old, Path(self.repo)), 'Given')
        self.publish()   # a waiting save: a changed revision would be refused
        again = self.setup_child({'repositories': [old]}, old, label=host_git.default_label('', old, Path(self.repo)))
        self.assertEqual(again['revision'], old['revision'])

    def test_the_owner_is_checked_before_the_checkout_gets_its_manager_folder(self):
        state = self.repo / '.git' / 'clab-manager'; shutil.rmtree(state)
        with patch.object(GitRepository, 'check_owner', lambda worker: (_ for _ in ()).throw(ValueError('must be owned'))):
            with self.assertRaisesRegex(ValueError, 'must be owned'): self.factory(dict(self.binding))
        self.assertFalse(state.exists())


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class HelperThirdReviewTests(unittest.TestCase):
    """The third risk review of the helper (S1d): lone surrogates, lenient history, mark_synced over journals(), a save
    the new remote already holds, and the remaining waiting-save cases."""
    setUp = HostGitTests.setUp
    raw = HostGitTests.raw; request = HostGitTests.request; publish = HostGitTests.publish; capture = HostGitTests.capture
    account = HostGitPlacesTests.account
    factory = HelperRedesignTests.factory; root = HelperRedesignTests.root; setup_child = HelperRedesignTests.setup_child
    other = HelperRedesignTests.other

    def test_a_lone_surrogate_in_a_manifest_is_filtered_and_history_answers(self):
        self.publish()
        (self.repo / 'x').mkdir(); (self.repo / 'x' / 'manifest.json').write_text('{"lab_name": "a\\ud800b", "files": []}')
        self.raw('add', 'x'); self.raw('commit', '-q', '-m', 'surrogate')
        result = self.worker.dispatch(self.request('history'))
        self.assertEqual({v['path']: v['summary'] for v in result['versions']}['x']['lab_name'], 'ab')
        json.dumps(result, ensure_ascii=False).encode()
        self.assertEqual(host_git.display_text('\ud800'), '')

    def test_a_subject_that_is_not_utf8_does_not_fail_history(self):
        self.publish()
        (self.repo / 'latest' / 'notes.txt').write_text('x\n'); self.raw('add', 'latest/notes.txt')
        tree = self.raw('write-tree'); parent = self.raw('rev-parse', 'HEAD')
        commit = subprocess.run([self.git.encode(), b'commit-tree', tree.encode(), b'-p', parent.encode(), b'-m', b'Caf\xe9 \xff save'],
                                cwd=self.repo, env=self.env, stdout=subprocess.PIPE, check=True).stdout.decode().strip()
        self.raw('update-ref', 'HEAD', commit)
        result = self.worker.dispatch(self.request('history'))
        self.assertEqual(result['commits'][0]['commit'], commit)
        self.assertTrue(result['commits'][0]['message'].startswith('Caf')); self.assertIn('save', result['commits'][0]['message'])

    def test_corrupt_and_non_object_journals_do_not_spoil_a_successful_push(self):
        req, saved = self.publish()
        journals = self.worker.state / 'journals'
        (journals / ('c' * 32 + '.json')).write_text('{corrupt'); (journals / ('d' * 32 + '.json')).write_text('[1, 2]')
        (journals / ('e' * 32 + '.json')).write_text(json.dumps({'operation_id': '../x', 'commit': saved['commit'], 'verified': True,
                                                                  'binding_revision': self.binding['revision']}))
        result = self.worker.dispatch(self.request('push', operation_id=req['operation_id']))
        self.assertEqual(result['status'], 'synced', result); self.assertTrue(result['pushed'])
        self.assertEqual(self.raw('ls-remote', 'origin', 'refs/heads/main').split()[0], saved['commit'])

    def second_remote(self):
        second = self.base / 'second.git'; subprocess.check_call([self.git, 'init', '-q', '--bare', str(second)], env=self.env)
        return second

    def test_a_save_the_new_remote_already_holds_needs_no_answer_from_the_gone_old_one(self):
        old = dict(self.root(), anchor=self.raw('rev-parse', 'HEAD'))
        _, waiting = self.publish()   # its upload failed: the old remote is gone
        second = self.second_remote(); os.rename(self.remote, self.base / 'gone.git')
        self.raw('remote', 'set-url', 'origin', str(second)); self.raw('push', '-q', 'origin', 'main')
        moved = self.setup_child({'repositories': [old]}, old)
        self.assertNotEqual(moved['revision'], old['revision']); self.assertEqual(moved['push_url'], str(second))

    def test_a_save_the_new_remote_lacks_still_refuses_while_the_old_remote_is_gone(self):
        old = dict(self.root(), anchor=self.raw('rev-parse', 'HEAD'))
        _, waiting = self.publish()
        second = self.second_remote(); os.rename(self.remote, self.base / 'gone.git')
        self.raw('switch', '-q', '-c', 'other', 'origin/main')   # the new registration's branch lacks the save
        self.raw('remote', 'set-url', 'origin', str(second)); self.raw('push', '-q', 'origin', 'other')
        with self.assertRaisesRegex(ValueError, '^' + host_git.SAVE_UNKNOWN + '$'): self.setup_child({'repositories': [old]}, old)

    def test_nothing_waits_on_a_registered_branch_that_is_gone_or_was_never_committed(self):
        self.publish()
        self.raw('switch', '-q', '-c', 'other', 'origin/main'); self.raw('branch', '-q', '-D', 'main')
        worker = self.factory(dict(self.binding))
        with patch.object(worker, 'remote_head', side_effect=AssertionError('nothing waits: the remote is not asked')):
            self.assertIsNone(worker.check_retire())
            worker.binding['branch'] = 'never-committed'; self.assertIsNone(worker.check_retire())

    def test_a_failed_fetch_answers_that_the_remote_could_not_be_asked(self):
        _, waiting = self.publish()
        other = self.other(); other('commit', '-q', '--allow-empty', '-m', 'remote only'); other('push', '-q')
        worker = self.factory(dict(self.binding))
        with patch.object(worker, 'fetch_remote', side_effect=ValueError('fetch failed')):
            with self.assertRaisesRegex(ValueError, '^' + host_git.SAVE_UNKNOWN + '$'): worker.check_retire()
        with patch.object(worker, 'fetch_remote', return_value=''):   # the fetch "worked" but the remote commit is still missing
            with self.assertRaisesRegex(ValueError, '^' + host_git.SAVE_UNKNOWN + '$'): worker.check_retire()

    def test_an_uploaded_save_lost_to_a_force_push_is_skipped_and_the_next_push_refuses(self):
        req, saved = self.publish(push=True)
        other = self.other(); other('reset', '-q', '--hard', 'HEAD~1'); other('commit', '-q', '--allow-empty', '-m', 'rewritten')
        other('push', '-q', '--force', 'origin', 'HEAD:main')
        self.assertIsNone(self.factory(dict(self.binding)).check_retire(), 'a journal marked pushed is not asked about')
        req2, second = self.publish(self.capture('next\n'), push=True)
        self.assertEqual(second['status'], 'needs_attention'); self.assertIn('advanced or diverged', second['message'])

    def test_an_unchanged_save_on_the_owner_s_own_commit_does_not_wait(self):
        self.publish(push=True)
        (self.repo / 'notes.txt').write_text('mine\n'); self.raw('add', 'notes.txt'); self.raw('commit', '-q', '-m', 'owner work')
        req, same = self.publish()
        self.assertEqual(same['status'], 'unchanged'); self.assertFalse(self.worker.load_journal(req['operation_id'])['verified'])
        worker = self.factory(dict(self.binding))
        with patch.object(worker, 'remote_head', side_effect=AssertionError('the owner\'s own commit is no manager save')):
            self.assertIsNone(worker.check_retire())

    def test_the_old_registration_s_lock_is_waited_for(self):
        old = dict(self.root(), anchor=self.raw('rev-parse', 'HEAD')); self.publish(push=True)
        import threading
        held = self.factory(dict(self.binding)).lock(); held.__enter__()
        import time
        threading.Timer(2.0, lambda: held.__exit__(None, None, None)).start(); started = time.monotonic()
        renamed = self.setup_child({'repositories': [old]}, old, label='renamed')
        self.assertEqual(renamed['label'], 'renamed'); self.assertGreater(time.monotonic() - started, 1.5, 'it waited for the lock')

    def test_setup_git_gives_the_login_hint_only_for_identity_or_login_refusals(self):
        for message in ('Git commit identity is missing or invalid.',
                        "The remote branch is unavailable. Check connectivity and the owner's noninteractive HTTPS Git login.",
                        'Git push preflight failed. Authenticate as the registered Linux owner and check remote write access.'):
            self.assertTrue(host_git.owner_login_problem(message), message)
        for message in (host_git.SAVE_WAITS, host_git.SAVE_UNKNOWN, 'Another Git operation is already running for this repository.',
                        host_git.NOT_MANAGER_SAVES, host_git.REMOTE_AHEAD):
            self.assertFalse(host_git.owner_login_problem(message), message)
        script = (Path(__file__).resolve().parents[2] / 'deploy' / 'setup-git.sh').read_text()
        self.assertIn('sys.exit(3 if h.owner_login_problem(str(error)) else 1)', script)
        self.assertIn('if [[ $status -ne 3 ]]; then', script); self.assertIn("<<'PY' || status=$?", script)


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class CheckpointOnlyTests(unittest.TestCase):
    """H8 (live pass, LIVE-ENV 9.3 item 5): an existing, older save kept as a checkpoint (`checkpoint_only: true`)
    writes only `checkpoints/<name>`; `latest` keeps the lab's newest save. Without the option nothing changes."""
    setUp = HostGitTests.setUp
    raw = HostGitTests.raw; capture = HostGitTests.capture
    sibling = HostGitPlacesTests.sibling
    design = HostGitDesignExportTests.design

    def lab(self):
        self.lab_binding, self.lab_worker = self.sibling('git-redesign')

    def save(self, snapshot, operation=None, **options):
        req = {'mode': 'publish', 'binding_id': self.lab_binding['id'], 'revision': self.lab_binding['revision'],
               'operation_id': operation or uuid.uuid4().hex, 'expected_head': self.raw('rev-parse', 'HEAD'),
               'target': 'latest', 'push': False, 'snapshot': snapshot}
        req.update(options)
        return req, self.lab_worker.dispatch(req)

    def with_topology(self, text):
        capture = self.capture(text); topology = b'name: BGP\ntopology:\n  nodes: {}\n'; layout = b'{"nodeAnnotations": []}'
        for name, raw, kind in (('BGP.clab.yml', topology, 'topology'), ('BGP.clab.yml.annotations.json', layout, 'annotations')):
            capture['files'][name] = base64.b64encode(raw).decode()
            capture['manifest']['files'].append(dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest(), kind=kind))
        capture['manifest']['schema'] = 2
        return capture

    def blobs(self, folder): return self.raw('ls-tree', '-r', 'HEAD', '--', folder)

    def test_an_older_save_kept_as_a_checkpoint_leaves_latest_alone(self):
        self.lab(); older = self.with_topology('router bgp 65001\n')
        self.assertEqual(self.save(older)[1]['status'], 'committed')
        self.assertEqual(self.save(self.with_topology('router bgp 65002\n'))[1]['status'], 'committed')
        latest = self.blobs('git-redesign/latest'); head = self.raw('rev-parse', 'HEAD')
        req, kept = self.save(older, target='checkpoint', checkpoint='kept', checkpoint_only=True)
        self.assertEqual(kept['status'], 'committed', kept); self.assertEqual(kept['snapshot_path'], 'git-redesign/checkpoints/kept')
        self.assertEqual(self.blobs('git-redesign/latest'), latest, 'every blob of latest is unchanged')
        touched = self.raw('diff-tree', '--no-commit-id', '--name-only', '-r', head, kept['commit']).splitlines()
        self.assertEqual(sorted(touched), ['git-redesign/checkpoints/kept/BGP.clab.yml', 'git-redesign/checkpoints/kept/BGP.clab.yml.annotations.json',
                                           'git-redesign/checkpoints/kept/PE1.cfg', 'git-redesign/checkpoints/kept/manifest.json'])
        self.assertEqual(json.loads(self.raw('show', kept['commit'] + ':git-redesign/checkpoints/kept/manifest.json')), older['manifest'])
        self.assertEqual(self.raw('show', 'HEAD:git-redesign/latest/PE1.cfg'), 'router bgp 65002')
        self.assertIn('Manager-Operation: ' + req['operation_id'], self.raw('log', '-1', '--format=%B'))
        compared = self.lab_worker.dispatch({'mode': 'compare', 'binding_id': self.lab_binding['id'], 'revision': self.lab_binding['revision'],
                                             'operation_id': req['operation_id']})
        self.assertEqual(sorted((f['name'], f['status']) for f in compared['files']),
                         [('BGP.clab.yml', 'added'), ('BGP.clab.yml.annotations.json', 'added'), ('PE1.cfg', 'added')],
                         'compare reads the journal\'s folder: the checkpoint, new in that commit')
        # Idempotent retry; the same operation with the option flipped is another request.
        self.assertEqual(self.lab_worker.dispatch(req)['commit'], kept['commit'])
        with self.assertRaisesRegex(ValueError, 'already belongs to a different snapshot'): self.lab_worker.dispatch(dict(req, checkpoint_only=False))
        pushed = self.lab_worker.dispatch({'mode': 'push', 'binding_id': self.lab_binding['id'], 'revision': self.lab_binding['revision'],
                                           'operation_id': req['operation_id']})
        self.assertEqual(pushed['status'], 'synced', pushed)

    def test_without_the_option_a_checkpoint_still_also_writes_latest(self):
        self.lab(); older = self.with_topology('router bgp 65001\n')
        self.save(older); self.save(self.with_topology('router bgp 65002\n'))
        _, kept = self.save(older, target='checkpoint', checkpoint='kept')
        self.assertEqual(kept['status'], 'committed', kept)
        self.assertEqual(self.raw('show', 'HEAD:git-redesign/latest/PE1.cfg'), 'router bgp 65001', 'today\'s behaviour: latest turns back')
        self.assertIn('git-redesign/latest/PE1.cfg', kept['changed_files'])

    def test_the_option_is_refused_outside_a_capture_checkpoint_and_writes_nothing(self):
        self.lab(); self.save(self.capture('router bgp 65001\n'))
        head = self.raw('rev-parse', 'HEAD')
        for options in ({'target': 'latest', 'checkpoint_only': True}, {'target': 'baseline', 'checkpoint_only': True},
                        {'target': 'checkpoint', 'checkpoint': 'k', 'checkpoint_only': 'true'},
                        {'target': 'checkpoint', 'checkpoint': 'k', 'checkpoint_only': 1}):
            _, result = self.save(self.capture('router bgp 65009\n'), **options)
            self.assertEqual((result['status'], result['message'], result['commit']), ('needs_attention', 'Invalid save option.', None), options)
        _, result = self.save(self.design(), target='checkpoint', checkpoint='plan', checkpoint_only=True)
        self.assertEqual((result['status'], result['message']), ('needs_attention', 'Invalid save option.'), 'a design export needs no flag')
        self.assertEqual(self.raw('rev-parse', 'HEAD'), head); self.assertEqual(self.raw('status', '--porcelain'), '')
        self.assertFalse((self.repo / 'git-redesign' / 'checkpoints').exists())

    def test_an_empty_lab_folder_gets_only_the_checkpoint(self):
        self.lab()
        _, kept = self.save(self.with_topology('router bgp 65001\n'), target='checkpoint', checkpoint='first', checkpoint_only=True)
        self.assertEqual(kept['status'], 'committed', kept)
        self.assertTrue(all(p.startswith('git-redesign/checkpoints/first/') for p in kept['changed_files']), kept['changed_files'])
        self.assertFalse((self.repo / 'git-redesign' / 'latest').exists()); self.assertEqual(self.blobs('git-redesign/latest'), '')


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class GeneratedLabelTests(unittest.TestCase):
    """Refusal audit (G2): a deep folder is never refused for its label. The label the helper generates is cut to the
    limit (the folder's end kept); a label a person gives keeps its check."""
    setUp = HostGitTests.setUp
    raw = HostGitTests.raw; account = HostGitPlacesTests.account
    factory = HelperRedesignTests.factory; owner = HelperRedesignTests.owner; registry = HelperRedesignTests.registry
    saved = HelperRedesignTests.saved; root = HelperRedesignTests.root; register = HelperRedesignTests.register

    def test_a_deep_folder_registers_with_a_cut_label_that_keeps_its_end(self):
        self.registry(self.root(label='clab-manager-scratch-checkout'))
        rest = 'b' * 60 + '/week-07/bgp-route-reflector-lab'
        first, second = 'a' + 'c' * 39 + '/' + rest, 'z' + 'c' * 39 + '/' + rest
        self.assertGreater(len('repo / ' + first), host_git.MAX_LABEL)
        one = self.register(first); two = self.register(second)
        for result, prefix in ((one, first), (two, second)):
            self.assertEqual(result['prefix'], prefix)
            stored = next(b for b in self.saved().values() if b['prefix'] == prefix)['label']
            self.assertLessEqual(len(stored), host_git.MAX_LABEL); self.assertTrue(stored.endswith('/week-07/bgp-route-reflector-lab'), stored)
            self.assertTrue(stored.startswith('repo / …')); self.assertFalse(any(ord(c) < 32 for c in stored))
        self.assertNotEqual(one['id'], two['id']); self.assertNotEqual(one['prefix'], two['prefix'])
        self.assertEqual(one['label'], two['label'], 'the labels may be equal: registrations are told apart by id, path and prefix')
        self.assertEqual(host_git.folder_label('repo', first), host_git.folder_label('repo', first), 'deterministic')
        self.assertEqual(host_git.folder_label('repo', 'bgp'), 'repo / bgp', 'a short label is unchanged')
        self.assertEqual(len(host_git.folder_label('r' * 150, '')), host_git.MAX_LABEL)

    def test_a_label_a_person_gives_keeps_its_check(self):
        self.registry(self.root())
        with self.assertRaisesRegex(ValueError, '^Use a short repository label\\.$'): self.register('bgp', label='L' * 101)
        self.assertEqual(sorted(self.saved()), [''])
        script = (Path(__file__).resolve().parents[2] / 'deploy' / 'setup-git.sh').read_text()
        self.assertIn("if len(label)>100 or any(ord(c)<32 for c in label): raise ValueError('Use a short repository label.')", script)
