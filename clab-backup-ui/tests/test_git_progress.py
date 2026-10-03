import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
import zipfile

from fastapi import HTTPException

from app import __version__
from app.git_progress import (GitProgress, base_folder, captured_snapshot, decoded_snapshot, pending_progress,
                              PROTOCOL, snapshot_conflict, snapshot_diff, version_label, resolve_version_path,
                              annotated_compare, file_label, job_destination, pair_renamed_files,
                              repository_display_name, strip_credentials, job_pending, GIT_JOB_CAP,
                              _append_git_job, kept_on_vm, digest as git_digest)
from app.store import Store
import test_discovery as discovery_tests


class VersionPathTests(unittest.TestCase):
    """Labelling and path resolution for saved versions across folders."""
    def test_version_label_names_the_folder_and_state(self):
        self.assertEqual(version_label('reference/broken-01/latest'), 'reference/broken-01 · latest')
        self.assertEqual(version_label('work/baseline'), 'work · baseline')
        self.assertEqual(version_label('work/checkpoints/attempt-1'), 'work · checkpoint · attempt-1')
        self.assertEqual(version_label('latest'), 'latest')
        self.assertEqual(version_label(''), 'repository root')

    def test_resolve_version_path_handles_exact_paths(self):
        # Rule 5 (revised): a leading slash is an exact repository-relative path ('/' is the
        # root); a bare 'latest', 'baseline' or 'checkpoints/<name>' keeps its pre-upgrade meaning
        # (the lab's own folder), compatibility for a page or tool built before this release; any
        # other bare path is exact, same as an explicit leading slash.
        binding = {'repository': {'prefix': 'labs/work'}}
        # (a) exact: leading slash strips to a repository-relative path.
        self.assertEqual(resolve_version_path(binding, '/'), '')
        self.assertEqual(resolve_version_path(binding, '/Final'), 'Final')
        self.assertEqual(resolve_version_path(binding, '/latest'), 'latest')  # root-level 'latest', not labs/work/latest
        self.assertEqual(resolve_version_path(binding, '/labs/work/latest'), 'labs/work/latest')
        # (b) bare reserved names: compatibility mapping onto the connected (lab) folder.
        self.assertEqual(resolve_version_path(binding, 'latest'), 'labs/work/latest')
        self.assertEqual(resolve_version_path(binding, 'baseline'), 'labs/work/baseline')
        self.assertEqual(resolve_version_path(binding, 'checkpoints/one'), 'labs/work/checkpoints/one')
        # (c) any other bare path: exact, unchanged.
        self.assertEqual(resolve_version_path(binding, 'Final'), 'Final')
        self.assertEqual(resolve_version_path(binding, 'course/lab/reference/solution'), 'course/lab/reference/solution')
        self.assertEqual(resolve_version_path(binding, 'Final/latest'), 'Final/latest')
        self.assertEqual(resolve_version_path(binding, 'working/checkpoints/one'), 'working/checkpoints/one')
        for bad in ('../etc/latest', 'reference/.git/latest', '/../etc/latest', ''):
            with self.assertRaises(HTTPException, msg=bad):
                resolve_version_path(binding, bad)

    def test_base_folder_refuses_reserved_lab_folder_shapes(self):
        # Rule 1: latest, baseline and checkpoints/<name> are reserved lab-folder shapes.
        for bad, parent in (('latest', ''), ('course/latest', 'course'), ('course/baseline', 'course'),
                            ('course/checkpoints', 'course'), ('working/checkpoints/one', 'working')):
            with self.assertRaises(ValueError, msg=bad) as refused:
                base_folder(bad)
            where = (parent + '/latest') if parent else "the repository root's latest"
            self.assertIn('its saves go to ' + where, str(refused.exception), bad)
        self.assertEqual(base_folder('course/latest/working'), 'course/latest/working')
        self.assertEqual(base_folder('Week-01/BGP/Final-State'), 'Week-01/BGP/Final-State')
        self.assertEqual(base_folder(''), '')

    def test_snapshot_conflict_names_the_folder_at_or_below(self):
        # Rule 2: a lab folder at, or below, an existing snapshot folder (manifest.json at HEAD).
        files = [dict(path='README.md'), dict(path='Final/manifest.json'), dict(path='Final/latest/manifest.json')]
        self.assertEqual(snapshot_conflict(files, 'Final'), 'Final')
        self.assertEqual(snapshot_conflict(files, 'Final/sub'), 'Final')
        self.assertEqual(snapshot_conflict(files, 'Final/latest'), 'Final/latest')
        self.assertEqual(snapshot_conflict(files, 'Elsewhere'), '')
        self.assertEqual(snapshot_conflict(files, ''), '')


class DestinationTests(unittest.TestCase):
    """E3: the destination a job freezes at save time, built from the binding, never re-derived."""

    def test_repository_display_name_prefers_the_remote_url_leaf(self):
        self.assertEqual(repository_display_name({'push_url': 'https://github.com/ben/BENS-BGP-LAB.git', 'path': '/x/checkout'}), 'BENS-BGP-LAB')
        self.assertEqual(repository_display_name({'push_url': '', 'path': '/home/ben/labs/bgp'}), 'bgp')
        self.assertEqual(repository_display_name({'push_url': '', 'path': '', 'label': 'Bens lab'}), 'Bens lab')
        self.assertEqual(repository_display_name({}), 'repository')

    def test_strip_credentials_removes_userinfo_only(self):
        self.assertEqual(strip_credentials('https://token@github.com/ben/lab.git'), 'https://github.com/ben/lab.git')
        self.assertEqual(strip_credentials('https://user:pass@github.com/ben/lab.git'), 'https://github.com/ben/lab.git')
        self.assertEqual(strip_credentials('https://github.com/ben/lab.git'), 'https://github.com/ben/lab.git')
        self.assertEqual(strip_credentials(''), '')

    def test_job_destination_freezes_repository_branch_path_and_checkout(self):
        binding = {'repository': {'path': '/home/ben/labs/bgp', 'prefix': 'Gtel-100G-G8032/Working',
                                  'branch': 'main', 'push_url': 'https://user:pass@github.com/ben/Course-Labs.git'}}
        latest = job_destination(binding, 'latest')
        self.assertEqual(latest, {'repository': 'Course-Labs', 'remote': 'https://github.com/ben/Course-Labs.git',
                                  'branch': 'main', 'path': 'Gtel-100G-G8032/Working/latest', 'checkout': '/home/ben/labs/bgp'})
        checkpoint = job_destination(binding, 'checkpoint', 'day-1')
        self.assertEqual(checkpoint['path'], 'Gtel-100G-G8032/Working/checkpoints/day-1')
        root = job_destination({'repository': {'path': '/x', 'prefix': '', 'branch': 'main', 'push_url': ''}}, 'baseline')
        self.assertEqual(root['path'], 'baseline')
        self.assertEqual(root['repository'], 'x')


class RenamedFileCompareTests(unittest.TestCase):
    """The VM helper's `compare` mode pairs files by name; a device whose human backup extension
    moved between saves (Junos `.set` to `.cfg`) must still read as one changed file."""

    def test_a_suffix_renamed_file_is_folded_into_one_changed_entry(self):
        files = [dict(name='r2.set', status='removed', before='OLD\n', after=''),
                 dict(name='r2.cfg', status='added', before='', after='NEW\n')]
        result = pair_renamed_files(files)
        self.assertEqual(len(result), 1, result)
        self.assertEqual(result[0]['status'], 'changed')
        self.assertEqual(result[0]['name'], 'r2.cfg')
        self.assertEqual(result[0]['renamed_from'], 'r2.set')
        self.assertEqual(result[0]['before'], 'OLD\n')
        self.assertEqual(result[0]['after'], 'NEW\n')

    def test_an_unrelated_removed_and_added_pair_is_left_alone(self):
        files = [dict(name='r2.set', status='removed', before='OLD\n', after=''),
                 dict(name='r3.cfg', status='added', before='', after='NEW\n')]
        result = pair_renamed_files(files)
        self.assertEqual({f['name'] for f in result}, {'r2.set', 'r3.cfg'})
        self.assertEqual({f['status'] for f in result}, {'removed', 'added'})

    def test_an_ambiguous_stem_match_is_never_guessed(self):
        files = [dict(name='r2.set', status='removed', before='OLD\n', after=''),
                 dict(name='r2.cfg', status='added', before='', after='A\n'),
                 dict(name='r2-abcdef123456.cfg', status='added', before='', after='B\n')]
        # Only one candidate matches the stem 'r2' exactly; the hashed-collision name is a
        # different stem and is left as its own added file, never guessed at.
        result = pair_renamed_files(files)
        self.assertEqual(len(result), 2, result)
        changed = next(f for f in result if f['status'] == 'changed')
        self.assertEqual(changed['name'], 'r2.cfg')
        self.assertEqual(changed['renamed_from'], 'r2.set')
        added = next(f for f in result if f['status'] == 'added')
        self.assertEqual(added['name'], 'r2-abcdef123456.cfg')

    def test_an_ordinary_changed_file_is_unaffected(self):
        files = [dict(name='r1.cfg', status='changed', before='a\n', after='b\n')]
        self.assertEqual(pair_renamed_files(files), files)

    def test_annotated_compare_adds_a_diff_and_a_label_after_folding_a_rename(self):
        files = [dict(name='r2.set', status='removed', before='set a\n', after=''),
                 dict(name='r2.cfg', status='added', before='', after='set b\n')]
        result = annotated_compare(files)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['label'], 'r2')
        self.assertFalse(result[0]['diff']['identical'])
        self.assertGreaterEqual(result[0]['diff']['added'], 1)

    def test_the_review_never_calls_a_file_identical_when_its_change_lies_past_the_line_cap(self):
        # Audit L-7: a saved configuration over 20 000 lines whose only change is after that point.
        before = ''.join(f'set line {n}\n' for n in range(20005))
        after = before.replace('set line 20003\n', 'set line 20003 changed\n')
        diff = annotated_compare([dict(name='r1.set', status='changed', before=before, after=after)])[0]['diff']
        self.assertFalse(diff['identical']); self.assertTrue(diff['truncated'])
        self.assertIn('first 20000 lines', diff['note'])


class FileLabelTests(unittest.TestCase):
    def test_file_label_strips_the_saved_extension(self):
        self.assertEqual(file_label('r2.cfg'), 'r2')
        self.assertEqual(file_label('r2.jcfg'), 'r2')
        self.assertEqual(file_label('manifest'), 'manifest')
        self.assertEqual(file_label(''), '')


class SnapshotDiffTests(unittest.TestCase):
    """`snapshot_diff` pairs two saved snapshots by manifest node, not by filename, so a device's
    human backup can change extension between saves (Junos `.set` to `.cfg`) without appearing as a
    removed file plus an added one."""

    @staticmethod
    def manifest_and_files(node, suffix, text, restore_text=None, restore_suffix='jcfg'):
        entry = {'path': f'{node}.{suffix}', 'node': node, 'platform': 'juniper_cjunosevolved',
                 'format': 'junos-display-set'}
        files = {entry['path']: text.encode('utf-8')}
        if restore_text is not None:
            entry.update(restore_artifact=f'{node}.{restore_suffix}', restore_format='junos-hierarchical',
                        restore_capable=True)
            files[entry['restore_artifact']] = restore_text.encode('utf-8')
        return {'files': [entry]}, files

    def test_renamed_and_changed_file_pairs_as_one_changed_entry(self):
        before_manifest, before_files = self.manifest_and_files('r2', 'set', 'set system host-name OLD\n')
        after_manifest, after_files = self.manifest_and_files('r2', 'cfg', 'set system host-name NEW\n')
        result = snapshot_diff(before_manifest, before_files, after_manifest, after_files)
        self.assertEqual(len(result), 1, result)
        self.assertEqual(result[0]['status'], 'changed')
        self.assertEqual(result[0]['name'], 'r2.cfg')  # shown under its current name
        self.assertIn('OLD', result[0]['before'])
        self.assertIn('NEW', result[0]['after'])
        self.assertFalse(any(f['status'] in ('added', 'removed') for f in result))

    def test_unchanged_restore_artifact_with_a_renamed_config_only_reports_the_config(self):
        before_manifest, before_files = self.manifest_and_files('r2', 'set', 'OLD\n', restore_text='hier\n')
        after_manifest, after_files = self.manifest_and_files('r2', 'cfg', 'NEW\n', restore_text='hier\n')
        result = snapshot_diff(before_manifest, before_files, after_manifest, after_files)
        self.assertEqual([f['name'] for f in result], ['r2.cfg'])

    def test_changed_restore_artifact_is_paired_by_node_too(self):
        before_manifest, before_files = self.manifest_and_files('r2', 'cfg', 'same\n', restore_text='OLD-HIER\n')
        after_manifest, after_files = self.manifest_and_files('r2', 'cfg', 'same\n', restore_text='NEW-HIER\n')
        result = snapshot_diff(before_manifest, before_files, after_manifest, after_files)
        self.assertEqual(len(result), 1, result)
        self.assertEqual(result[0]['name'], 'r2.jcfg')
        self.assertEqual(result[0]['status'], 'changed')

    def test_node_only_in_before_is_removed_not_paired(self):
        before_manifest, before_files = self.manifest_and_files('r2', 'set', 'OLD\n')
        after_manifest, after_files = {'files': []}, {}
        result = snapshot_diff(before_manifest, before_files, after_manifest, after_files)
        self.assertEqual(result, [{'name': 'r2.set', 'status': 'removed', 'before': 'OLD\n', 'after': ''}])

    def test_node_only_in_after_is_added_not_paired(self):
        before_manifest, before_files = {'files': []}, {}
        after_manifest, after_files = self.manifest_and_files('r3', 'cfg', 'NEW\n')
        result = snapshot_diff(before_manifest, before_files, after_manifest, after_files)
        self.assertEqual(result, [{'name': 'r3.cfg', 'status': 'added', 'before': '', 'after': 'NEW\n'}])

    def test_identical_snapshot_reports_no_files(self):
        manifest, files = self.manifest_and_files('r2', 'cfg', 'same\n', restore_text='same-hier\n')
        self.assertEqual(snapshot_diff(manifest, files, manifest, files), [])


class GitJobCapTests(unittest.TestCase):
    """B-001: 'git_jobs' is bounded like 'operations', never dropping a save still pending review,
    a retry, capture, export or push (job_pending; a pending save is compared by digest later)."""

    def test_job_pending_matches_the_terminal_status_vocabulary(self):
        self.assertTrue(job_pending(dict(status='queued')))
        self.assertTrue(job_pending(dict(status='review_pending')))
        self.assertTrue(job_pending(dict(status='push_pending')))
        self.assertTrue(job_pending(dict(status='export_pending')))
        self.assertTrue(job_pending(dict(status='interrupted')))
        self.assertTrue(job_pending(dict(status='unchanged', pushed=False)))
        self.assertFalse(job_pending(dict(status='synced')))
        self.assertFalse(job_pending(dict(status='dismissed')))
        self.assertFalse(job_pending(dict(status='capture_incomplete')))
        self.assertFalse(job_pending(dict(status='failed')))
        self.assertFalse(job_pending(dict(status='unchanged', pushed=True)))

    def test_append_caps_at_the_newest_but_keeps_a_pending_save_beyond_it(self):
        state = {'git_jobs': [dict(id=str(i), status='synced') for i in range(GIT_JOB_CAP)]}
        state['git_jobs'][0]['status'] = 'review_pending'  # oldest entry; first to fall out of the window
        _append_git_job(state, dict(id='new', status='queued'))
        self.assertEqual(len(state['git_jobs']), GIT_JOB_CAP + 1)  # the newest cap, plus the survivor
        ids = [j['id'] for j in state['git_jobs']]
        self.assertIn('0', ids)
        self.assertIn('new', ids)
        # Append order (oldest to newest) is preserved; the survivor still sits before the newest job.
        self.assertLess(ids.index('0'), ids.index('new'))

    def test_append_drops_only_terminal_jobs_once_over_cap(self):
        state = {'git_jobs': [dict(id=str(i), status='synced') for i in range(GIT_JOB_CAP)]}
        _append_git_job(state, dict(id='newest', status='synced'))
        self.assertEqual(len(state['git_jobs']), GIT_JOB_CAP)
        self.assertNotIn('0', [j['id'] for j in state['git_jobs']])  # the oldest terminal job was dropped
        self.assertIn('newest', [j['id'] for j in state['git_jobs']])

    # Risk review 2, item 3: finish()'s 'unchanged' detection compares a fresh commit against the
    # newest pushed=True entry of the same binding; that entry must survive the cap too, even
    # though its own status ('synced') is not job_pending.
    def test_append_keeps_the_newest_pushed_entry_per_binding_beyond_the_cap(self):
        state = {'git_jobs': [dict(id=str(i), status='synced', pushed=(i == 0), binding_digest='b1')
                              for i in range(GIT_JOB_CAP)]}
        _append_git_job(state, dict(id='new', status='synced', pushed=True, binding_digest='other-binding'))
        self.assertEqual(len(state['git_jobs']), GIT_JOB_CAP + 1)
        ids = [j['id'] for j in state['git_jobs']]
        self.assertIn('0', ids)     # the last uploaded save of binding 'b1' survives the cap
        self.assertIn('new', ids)  # and so does the newest save of the unrelated binding
        self.assertLess(ids.index('0'), ids.index('new'))

    def test_append_lets_an_older_pushed_entry_go_once_a_newer_one_of_the_same_binding_exists(self):
        state = {'git_jobs': [dict(id=str(i), status='synced', pushed=(i in (0, 1)), binding_digest='b1')
                              for i in range(GIT_JOB_CAP)]}
        # Only the *newest* pushed entry per binding is protected, not every one of them.
        _append_git_job(state, dict(id='new', status='synced', pushed=False, binding_digest='b1'))
        ids = [j['id'] for j in state['git_jobs']]
        self.assertNotIn('0', ids)   # superseded by '1' as the newest pushed save of binding 'b1'
        self.assertIn('1', ids)

    def test_append_keeps_a_kept_save_whose_commit_may_still_go_along_beyond_the_cap(self):
        # Review issue G1-a: the review counts saves kept with Keep snapshot only until an upload carried them; one
        # trimmed away could no longer be counted. One that was uploaded, or never reached the VM, may go.
        state = {'git_jobs': [dict(id=str(i), status='synced') for i in range(GIT_JOB_CAP)]}
        state['git_jobs'][0].update(status='dismissed', commit='d'*40, pushed=False)
        state['git_jobs'][1].update(status='dismissed', commit='', published_attempt=True)
        state['git_jobs'][2].update(status='dismissed', commit='e'*40, pushed=True, binding_digest='b1')
        state['git_jobs'][3].update(status='dismissed', commit='')
        for n in range(4): _append_git_job(state, dict(id='new' + str(n), status='synced', pushed=True, binding_digest='b1'))
        ids = [j['id'] for j in state['git_jobs']]
        self.assertEqual(ids[:2], ['0', '1']); self.assertNotIn('2', ids); self.assertNotIn('3', ids)
        self.assertTrue(kept_on_vm(state['git_jobs'][0])); self.assertFalse(kept_on_vm(dict(status='dismissed', target='update', commit='f'*40)))


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
        self.extra_files = []           # extra repository files a GitPlacesTests test can add to 'browse'
        self.nothing_new = False        # the helper's answer when a save finds no changed file: it reuses HEAD
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
            if self.nothing_new:
                return dict(status='unchanged', commit='b'*40, pushed=None, changed_files=[], message='No configuration changes.', snapshot_path=request['target'])
            return dict(status='synced' if request['push'] else 'committed', commit='b'*40,
                        pushed=request['push'], changed_files=list(request['snapshot']['files']), snapshot_path=request['target'])
        if mode == 'push':
            if self.push_error: raise ValueError(self.push_error)
            return dict(status='synced', commit='b'*40, pushed=True, changed_files=[], snapshot_path='latest')
        if mode == 'read-version': return {'snapshot': next(iter(self.snapshots.values()))}
        if mode == 'history':
            versions = getattr(self, 'history_versions', None) or [dict(name='latest', path='latest', commit='b'*40)]
            return dict(commits=[dict(commit='b'*40, message='Saved', time=1)], versions=versions)
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
        if kwargs.get('topology'):
            # A capture that embedded the topology and map (UI/UX changes 2, item 10), as runner.embed_topology writes them.
            definition = kwargs['topology'].encode(); annotations = kwargs.get('annotations', '{"nodeAnnotations": []}').encode()
            (folder/'topology.clab.yml').write_bytes(definition); (folder/'topology.clab.yml.annotations.json').write_bytes(annotations)
            job['topology'] = dict(file='topology.clab.yml', size=len(definition), sha256=hashlib.sha256(definition).hexdigest(), source='vm',
                                   path='/srv/labs/t.clab.yml', read_at='2026-09-11T10:00:30+00:00', annotations_file='topology.clab.yml.annotations.json',
                                   annotations_size=len(annotations), annotations_sha256=hashlib.sha256(annotations).hexdigest())
        if kwargs.get('progress_context'): job['progress_context'] = copy.deepcopy(kwargs['progress_context'])
        if kwargs.get('progress_id'): job['progress_id'] = kwargs['progress_id']
        self.store.state['jobs'].insert(0, job); self.store.save()
        return copy.deepcopy(job)

    def save(self, **fields):
        data = dict(request_id=uuid.uuid4().hex, target='latest', push=True, note='Fixture save')
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
        # The Junos human-facing Git snapshot file is `.cfg` (display-set text, matching EOS and
        # IOS XR there); the internal capture storage extension (`.set`, the fixture's own file
        # above) never leaks into the repository. The restore artifact keeps its own `.jcfg` name.
        self.assertTrue(entry['path'].endswith('.cfg'), entry['path'])
        self.assertTrue(entry['restore_artifact'].endswith('.jcfg'), entry['restore_artifact'])
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

    def test_a_save_without_a_short_label_is_refused(self):
        for note in ('', '   '):
            response = self.client.post(self.url+'/save', json=dict(request_id=uuid.uuid4().hex, target='latest', note=note))
            self.assertEqual(response.status_code, 400, note)
            self.assertIn('Give this save a short label.', response.json()['detail'])
        self.assertEqual(len(self.store.state['git_jobs']), 0)
        ok = self.client.post(self.url+'/save', json=dict(request_id=uuid.uuid4().hex, target='latest', note='OSPF adjacencies up'))
        self.assertEqual(ok.status_code, 200, ok.text)

    def test_a_save_freezes_its_destination_and_the_commit_message_is_the_label(self):
        job, _ = self.save(note='OSPF adjacencies up on every router')
        self.assertEqual(job['destination'], {'repository': 'bgp', 'remote': '', 'branch': 'main',
                                               'path': 'latest', 'checkout': '/home/ben/labs/bgp'})
        outcome, _ = self.run_save(job)
        publish = next(r for r in self.sent if r['mode'] == 'publish')
        self.assertEqual(publish['message'], 'OSPF adjacencies up on every router')
        # The binding moving to a different folder afterwards never rewrites a destination already
        # frozen on an earlier job: only a fresh save picks up the new binding.
        with self.store.lock:
            self.store.lab(self.lab['id'])['git_binding']['repository']['prefix'] = 'moved'; self.store.save()
        refreshed = self.client.get('/api/git/jobs/'+job['id']).json()
        self.assertEqual(refreshed['destination']['path'], 'latest')
        moved, _ = self.save(note='After the move')
        self.assertEqual(moved['destination']['path'], 'moved/latest')

    def test_retry_reuses_the_same_job_and_never_recaptures_or_rewrites_the_commit(self):
        job, _ = self.save(push=False); outcome, submit = self.run_save(job)
        self.assertEqual(outcome['status'], 'committed'); first_commit = outcome['commit']
        outcome, submit = self.review_and_upload(job)
        self.assertEqual(outcome['id'], job['id']); self.assertEqual(outcome['commit'], first_commit)
        self.assertEqual(outcome['status'], 'synced'); submit.assert_not_called()
        self.assertEqual(sum(r['mode'] == 'publish' for r in self.sent), 1, 'the capture and commit were never repeated')

    def test_compare_by_job_id_folds_a_renamed_file_and_annotates_every_file(self):
        original_remote = self.remote
        def remote(host, request, stopping=None):
            if request['mode'] == 'compare':
                return {'files': [dict(name='r1.set', status='removed', before='set old\n', after=''),
                                  dict(name='r1.cfg', status='added', before='', after='set new\n')]}
            return original_remote(host, request, stopping)
        self.helper.side_effect = remote
        job, _ = self.save(); self.run_save(job)
        diff = self.client.post(self.url+'/compare', json={'job_id': job['id']})
        self.assertEqual(diff.status_code, 200, diff.text)
        files = diff.json()['files']
        self.assertEqual(len(files), 1, files)
        self.assertEqual(files[0]['status'], 'changed')
        self.assertEqual(files[0]['renamed_from'], 'r1.set')
        self.assertEqual(files[0]['label'], 'r1')
        self.assertGreaterEqual(files[0]['diff']['added'], 1)

    def test_partial_capture_keeps_git_untouched(self):
        backup = self.capture(); self.store.state['jobs'][0]['status'] = 'partial'
        self.store.state['jobs'][0]['nodes'][0]['status'] = 'failed'
        job, _ = self.save()
        with patch.object(self.app.state.runner, 'submit', return_value=backup): self.progress.execute(job['id'])
        outcome = self.client.get('/api/git/jobs/'+job['id']).json()
        self.assertEqual(outcome['status'], 'capture_incomplete')
        self.assertFalse(any(r['mode'] == 'publish' for r in self.sent))

    def test_the_topology_and_map_embedded_with_a_capture_travel_with_the_save(self):
        text = 'name: training\ntopology:\n  nodes:\n    r1: {kind: cisco_xrv9k}\n'
        backup = self.capture(topology=text, annotations='{"nodeAnnotations": [{"id": "r1", "position": {"x": 1, "y": 2}}]}')
        result = captured_snapshot(self.store, backup)
        kinds = {f['path']: f for f in result['manifest']['files'] if f.get('kind')}
        self.assertEqual(sorted(kinds), ['training.clab.yml', 'training.clab.yml.annotations.json'], 'the lab\'s own names, beside the device files')
        self.assertEqual((kinds['training.clab.yml']['kind'], kinds['training.clab.yml']['source'], kinds['training.clab.yml']['vm_path']), ('topology', 'vm', '/srv/labs/t.clab.yml'))
        self.assertNotIn('read_at', kinds['training.clab.yml'], 'the read time stays on the backup record: it moves with every discovery pass and would make every save a new commit')
        # Two captures of the same files read at different times are one and the same snapshot to the helper.
        from app.host_git import content_digest
        later = self.capture(topology=text, annotations='{"nodeAnnotations": [{"id": "r1", "position": {"x": 1, "y": 2}}]}')
        self.store.state['jobs'][0]['topology']['read_at'] = '2026-09-11T10:30:00+00:00'; self.store.save()
        self.assertEqual(content_digest(captured_snapshot(self.store, later)['manifest']), content_digest(result['manifest']))
        # A restore reads a capture for its device files and is never stopped by the embedded topology.
        broken = self.capture(topology=text); (self.store.root/'backups'/broken['lab_id']/'history'/broken['id']/'topology.clab.yml').unlink()
        with self.assertRaisesRegex(ValueError, 'missing or unsafe'): captured_snapshot(self.store, broken)
        self.assertNotIn('training.clab.yml', captured_snapshot(self.store, broken, embedded_files=False)['files'])
        # A lab whose file-safe name begins with a dash still gets a name the helper takes.
        from app.downloads import topology_names
        self.assertEqual(topology_names({'lab_name': '-lab', 'topology': {'file': 'topology.clab.yml', 'annotations_file': 'x'}}), {'topology': '_-lab.clab.yml', 'annotations': '_-lab.clab.yml.annotations.json'})
        self.assertEqual(topology_names({'lab_name': 'Lab 1', 'topology': {'file': 'topology.clab.yml'}}), {'topology': 'Lab_1.clab.yml'})
        self.assertEqual(kinds['training.clab.yml.annotations.json']['kind'], 'annotations')
        self.assertTrue(all('node' not in f for f in kinds.values()), 'no device identity: restore and the device pairing leave them alone')
        self.assertEqual(base64.b64decode(result['files']['training.clab.yml']).decode(), text)
        self.assertEqual(result['manifest']['topology_provenance'], 'embedded')
        self.assertEqual(result['manifest']['topology_digest'], hashlib.sha256(text.encode()).hexdigest(), 'the digest is the embedded file\'s own')
        self.assertEqual(result['manifest']['node_names'], sorted(n['name'] for n in backup['nodes']), 'the device scope is unchanged')
        self.assertEqual(len(result['files']), len(backup['nodes']) + 2)
        # The helper's whole-snapshot rules still hold for the file map (every file listed, each once).
        from app.host_git import snapshot
        manifest, decoded = snapshot(result)
        self.assertEqual(set(decoded), set(result['files']))
        # A tampered embedded file is refused like a tampered configuration.
        (self.store.root/'backups'/backup['lab_id']/'history'/backup['id']/'topology.clab.yml').write_text('name: other\n')
        with self.assertRaisesRegex(ValueError, 'no longer matches'): captured_snapshot(self.store, backup)
        # Through the save route the embedded files reach the helper, the version view lists them without
        # offering them for a restore, and a compare pairs the topology of two saves by kind.
        backup = self.capture(topology=text)
        job, _ = self.save(backup_job_id=backup['id'])
        outcome, submit = self.run_save(job); submit.assert_not_called()
        self.review_and_upload(job)
        request = next(r for r in self.sent if r['mode'] == 'publish')
        self.assertIn('training.clab.yml', request['snapshot']['files'])
        self.assertEqual(request['snapshot']['manifest']['topology_provenance'], 'embedded')
        version = self.client.post(self.url + '/version', json={'commit': 'b'*40, 'path': 'latest'}).json()
        self.assertIn('training.clab.yml', [f['name'] for f in version['files']])
        self.assertNotIn('training.clab.yml', version['restore_nodes'])
        before = captured_snapshot(self.store, self.capture(topology='name: a\n'))
        after = captured_snapshot(self.store, self.capture(topology='name: b\n'))
        from app.git_progress import snapshot_diff
        decoded_before = {k: base64.b64decode(v) for k, v in before['files'].items()}; decoded_after = {k: base64.b64decode(v) for k, v in after['files'].items()}
        changes = [c for c in snapshot_diff(before['manifest'], decoded_before, after['manifest'], decoded_after) if c['name'] == 'training.clab.yml']
        self.assertEqual([(c['status'], c['before'], c['after']) for c in changes], [('changed', 'name: a\n', 'name: b\n')])

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

    def test_a_save_with_nothing_new_after_an_uploaded_save_is_unchanged_and_blocks_nothing(self):
        first, _ = self.save(); self.run_save(first)
        outcome, _ = self.review_and_upload(first); self.assertEqual(outcome['status'], 'synced')
        self.nothing_new = True; self.sent.clear()
        again, _ = self.save(); outcome, _ = self.run_save(again)
        self.assertEqual(outcome['status'], 'unchanged'); self.assertTrue(outcome['pushed'])
        self.assertEqual(outcome['changed_files'], []); self.assertIn('was uploaded', outcome['message'])
        self.assertFalse(any(r['mode'] == 'push' for r in self.sent), 'nothing was uploaded for it')
        with self.store.lock: self.assertFalse(pending_progress(self.store.state, self.lab['id']), 'it must not block a folder change')
        self.dispatch.reset_mock()
        same = self.client.post('/api/git/jobs/'+again['id']+'/retry', json={'push': True, 'reviewed': True})
        self.assertEqual(same.status_code, 200, same.text); self.assertEqual(same.json()['status'], 'unchanged')
        self.dispatch.assert_not_called()

    def test_a_save_with_nothing_new_keeps_waiting_for_the_review_while_its_commit_was_never_uploaded(self):
        first, _ = self.save(); outcome, _ = self.run_save(first)
        self.assertEqual(outcome['status'], 'review_pending')           # saved on the VM, review declined so far
        self.nothing_new = True
        again, _ = self.save(); outcome, _ = self.run_save(again)
        self.assertEqual(outcome['status'], 'review_pending'); self.assertFalse(outcome['pushed'])
        with self.store.lock: self.assertTrue(pending_progress(self.store.state, self.lab['id']))
        # the upload of that commit is still possible, and still needs the review
        self.assertEqual(self.client.post('/api/git/jobs/'+again['id']+'/retry', json={'push': True}).status_code, 409)

    def test_a_commit_uploaded_through_another_binding_does_not_make_a_save_unchanged(self):
        first, _ = self.save(); self.run_save(first); self.review_and_upload(first)
        with self.store.lock:
            next(j for j in self.store.state['git_jobs'] if j['id'] == first['id'])['binding_digest'] = 'another-binding'
            self.store.save()
        self.nothing_new = True
        again, _ = self.save(); outcome, _ = self.run_save(again)
        self.assertEqual(outcome['status'], 'review_pending'); self.assertFalse(outcome['pushed'])

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

    def later_jobs(self, count):
        """`count` later backup/test jobs through the real Runner.submit() (and its trim), each
        finished at once, as a scheduled backup or Test logins run would produce over time."""
        runner = self.app.state.runner
        with patch.object(runner.pool, 'submit'), patch('app.runner.node_available', return_value=True):
            for _ in range(count):
                job = runner.submit(self.lab['id'], 'test')
                with self.store.lock:
                    next(j for j in self.store.state['jobs'] if j['id'] == job['id'])['status'] = 'succeeded'

    def test_export_pending_saves_capture_survives_the_jobs_cap_and_its_retry_still_finds_it(self):
        # Risk review 2, item 1: a pending save's capture must not be evicted by unrelated later
        # backup/login jobs (a 1-minute schedule reaches JOB_CAP in a few hours).
        job, _ = self.save(push=False)
        self.publish_error = 'VM Git helper unreachable'
        outcome, _ = self.run_save(job)
        self.assertEqual(outcome['status'], 'export_pending')
        capture = outcome['backup_job_id']; self.assertTrue(capture)
        with patch('app.runner.JOB_CAP', 3):
            self.later_jobs(3)
        self.assertIn(capture, [j['id'] for j in self.store.state['jobs']],
                      "a pending save's capture must survive the jobs cap")
        self.publish_error = ''
        self.assertEqual(self.client.post('/api/git/jobs/' + job['id'] + '/retry', json={'push': False}).status_code, 200)
        outcome, _ = self.run_save(job)
        self.assertNotIn('original capture is unavailable', outcome['message'])
        self.assertNotEqual(outcome['status'], 'export_pending')

    def test_an_interrupted_restores_pre_and_post_backups_survive_the_jobs_cap(self):
        # Risk review 2, item 1: a restart-recheck reads a still-interrupted restore's own safety
        # backups back by id (pre_backup_job_id/post_backup_job_id); they must not be evicted by
        # unrelated later backup/login jobs. 'interrupted' (unlike RESTORE_BUSY) does not block new
        # backups on any lab, so this is exactly the state in which other jobs keep accumulating
        # around it while it waits to be reconciled.
        pre = self.capture(); post = self.capture()
        restore_job = dict(id=uuid.uuid4().hex, lab_id=self.lab['id'], lab_name=self.lab['name'],
                           created='2026-09-11T10:00:00+00:00', status='interrupted', confirm_minutes=5,
                           source={}, pre_backup_job_id=pre['id'], post_backup_job_id=post['id'],
                           targets=[], progress={'settled': 0, 'total': 0})
        with self.store.lock:
            self.store.state.setdefault('restore_jobs', []).append(restore_job); self.store.save()
        with patch('app.runner.JOB_CAP', 3):
            self.later_jobs(3)
        stored_ids = [j['id'] for j in self.store.state['jobs']]
        self.assertIn(pre['id'], stored_ids); self.assertIn(post['id'], stored_ids)

    def test_unchanged_detection_survives_the_git_jobs_cap(self):
        # Risk review 2, item 3: finish()'s 'unchanged' detection needs the last uploaded save of
        # this binding still in 'git_jobs' (same commit, same binding_digest, pushed=True); many
        # later saves of an unrelated lab must not evict it from the cap.
        job, _ = self.save(push=False); outcome, _ = self.run_save(job)
        outcome, _ = self.review_and_upload(job); self.assertEqual(outcome['status'], 'synced')
        with self.store.lock, patch('app.git_progress.GIT_JOB_CAP', 3):
            for _ in range(3):   # later terminal entries (another lab's saves, folder moves, 'update' markers)
                _append_git_job(self.store.state, dict(id=uuid.uuid4().hex, lab_id='other', status='dismissed'))
        self.assertIn(job['id'], [j['id'] for j in self.store.state['git_jobs']])
        self.nothing_new = True
        again, _ = self.save(push=False); outcome, _ = self.run_save(again)
        self.assertEqual(outcome['status'], 'unchanged')

    def test_state_no_longer_slices_away_a_protected_pending_save(self):
        # Risk review 2, item 2 (finding 7): /api/state used to slice git_jobs to its last 200,
        # which could cut off a pending save the write-time trim deliberately kept further back
        # (in front, since git_jobs is oldest-to-newest). Storage is now the only place this is
        # bounded, so the read must not slice at all.
        job, _ = self.save(push=False); self.publish_error = 'down'; self.run_save(job)
        with self.store.lock, patch('app.git_progress.GIT_JOB_CAP', 200):
            for _ in range(200):
                _append_git_job(self.store.state, dict(id=uuid.uuid4().hex, lab_id='other', status='dismissed'))
        self.assertIn(job['id'], [j['id'] for j in self.store.state['git_jobs']])
        shown = [j['id'] for j in self.client.get('/api/state').json()['git_jobs']]
        self.assertIn(job['id'], shown)

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

    def test_version_route_reads_an_exact_snapshot_path_and_names_the_download(self):
        # Rule 5: an exact path with no reserved-name shape (not latest/baseline/checkpoints/<name>)
        # is a valid snapshot path now; the old shape check is gone.
        job, _ = self.save(); self.run_save(job)
        data = dict(commit='b'*40, path='Final')
        response = self.client.post(self.url+'/version', json=data)
        self.assertEqual(response.status_code, 200, response.text)
        read = next(r for r in self.sent if r['mode'] == 'read-version')
        self.assertEqual(read['path'], 'Final')
        download = self.client.post(self.url+'/version/download', json=data)
        self.assertEqual(download.status_code, 200, download.text)
        self.assertIn('.zip', download.headers['content-disposition'])
        root = self.client.post(self.url+'/version', json={**data, 'path': '/'})
        self.assertEqual(root.status_code, 200, root.text)
        self.assertEqual([r for r in self.sent if r['mode'] == 'read-version'][-1]['path'], '')

    def test_history_route_labels_an_exact_folder_by_its_own_path(self):
        self.history_versions = [dict(name='Final', path='Final', commit='b'*40, connected=False)]
        response = self.client.get(self.url + '/history')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['versions'][0]['label'], 'Final')

    def test_history_lists_a_legacy_and_a_fresh_save_and_compare_pairs_them_per_node(self):
        """A repository saved before this change holds `r2.set` + `r2.jcfg`; a fresh save after it
        holds `r2.cfg` + `r2.jcfg` for the same node. History still lists both saved versions,
        comparing the older one against the fresh one pairs the human file as one changed entry
        (never removed+added) despite the extension change, and either manifest still names its
        `.jcfg` restore artifact."""
        old_raw, old_hier = b'set system host-name OLD\n', b'system { host-name OLD; }\n'
        new_raw, new_hier = b'set system host-name NEW\n', b'system { host-name NEW; }\n'

        def manifest_for(raw, hier, suffix):
            return {'schema': 2, 'lab_id': self.lab['id'], 'lab_name': self.lab['name'], 'node_names': ['r2'],
                    'files': [{'path': f'r2.{suffix}', 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
                               'node': 'r2', 'platform': 'juniper_cjunosevolved', 'format': 'junos-display-set',
                               'restore_artifact': 'r2.jcfg', 'restore_size': len(hier),
                               'restore_sha256': hashlib.sha256(hier).hexdigest(),
                               'restore_format': 'junos-hierarchical', 'restore_capable': True}]}
        old_snap = {'manifest': manifest_for(old_raw, old_hier, 'set'),
                   'files': {'r2.set': base64.b64encode(old_raw).decode(), 'r2.jcfg': base64.b64encode(old_hier).decode()}}
        new_snap = {'manifest': manifest_for(new_raw, new_hier, 'cfg'),
                   'files': {'r2.cfg': base64.b64encode(new_raw).decode(), 'r2.jcfg': base64.b64encode(new_hier).decode()}}
        old_commit, new_commit = 'a'*40, 'b'*40
        self.history_versions = [dict(name='latest', path='latest', commit=new_commit, connected=True)]
        reads = {(old_commit, 'latest'): old_snap, (new_commit, 'latest'): new_snap}

        def remote(host, request, stopping=None):
            self.sent.append(copy.deepcopy(request))
            mode = request['mode']
            if mode == 'list': return dict(protocol=PROTOCOL, version=__version__, repositories=[self.repo])
            if mode == 'status': return dict(repository=self.repo, ready=True, head=new_commit, baseline_revision='', latest_manifest=None)
            if mode == 'history': return dict(commits=[], versions=self.history_versions)
            if mode == 'read-version': return {'snapshot': reads[(request['commit'], request['path'])]}
            raise AssertionError(mode)
        self.helper.side_effect = remote

        # History lists the one saved version regardless of which naming its files use.
        history = self.client.get(self.url + '/history').json()
        self.assertEqual(history['versions'][0]['label'], 'latest')

        # Comparing the legacy commit against the fresh latest pairs the human file per node.
        diff = self.client.post(self.url+'/compare', json={'commit': old_commit, 'path': 'latest'})
        self.assertEqual(diff.status_code, 200, diff.text)
        files = diff.json()['files']
        # The renamed human file (`r2.set` -> `r2.cfg`) and the restore artifact (`r2.jcfg`,
        # unchanged name, changed content) each appear exactly once, paired by node.
        self.assertEqual([f['name'] for f in files], ['r2.cfg', 'r2.jcfg'])
        self.assertTrue(all(f['status'] == 'changed' for f in files), files)
        config = next(f for f in files if f['name'] == 'r2.cfg')
        self.assertIn('OLD', config['before']); self.assertIn('NEW', config['after'])
        self.assertFalse(any(f['status'] in ('added', 'removed') for f in files),
                         'a renamed human file must not appear as removed+added')

        # Both the legacy and the fresh manifest still name their restore artifact explicitly.
        _, old_files = decoded_snapshot({'snapshot': old_snap})
        _, new_files = decoded_snapshot({'snapshot': new_snap})
        self.assertIn('r2.jcfg', old_files); self.assertIn('r2.jcfg', new_files)
        self.assertEqual(old_snap['manifest']['files'][0]['restore_artifact'], 'r2.jcfg')
        self.assertEqual(new_snap['manifest']['files'][0]['restore_artifact'], 'r2.jcfg')

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
            response = self.client.post(self.url+'/save', json=dict(request_id=uuid.uuid4().hex, note='Fixture save'))
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
        if (getattr(self, 'faithful', False) and mode not in ('list', 'connect') and request.get('binding_id')
                and not any(r['id'] == request['binding_id'] for r in self.registry)):
            self.sent.append(copy.deepcopy(request))
            raise ValueError('Select a registered Git repository.')   # host_git.main() for a binding that is gone
        if mode == 'list':
            self.sent.append(copy.deepcopy(request))
            return dict(protocol=PROTOCOL, version=__version__, repositories=[dict(r) for r in self.registry])
        if mode == 'browse':
            self.sent.append(copy.deepcopy(request))
            repo = next(r for r in self.registry if r['id'] == request['binding_id'])
            return dict(repository=repo, head='a'*40, files=[dict(path='README.md', size=12), dict(path='bgp/latest/r1.cfg', size=30), dict(path='bgp/latest/manifest.json', size=200)] + self.extra_files,
                        truncated=False, saved={'latest': 1789128000, 'baseline': None, 'checkpoints': None},
                        folders=[dict(id=r['id'], label=r['label'], prefix=r['prefix']) for r in self.registry if r['path'] == repo['path']])
        if mode in ('register-prefix', 'connect'):
            self.sent.append(copy.deepcopy(request))
            if self.publish_error: raise ValueError(self.publish_error)
            prefix = request['prefix']
            existing = next((r for r in self.registry if r['prefix'] == prefix and (mode == 'register-prefix' or r.get('push_url') == request['url'])), None)
            if mode == 'register-prefix' and getattr(self, 'faithful', False):
                # What the real helper does (host_git.plan_prefix / register_prefix): lab folders of one
                # checkout cannot overlap unless the source is being retired, and retiring removes it.
                source = next(r for r in self.registry if r['id'] == request['binding_id'])
                if not existing:
                    for other in self.registry:
                        if other is source and request.get('retire'): continue
                        if not prefix or not other['prefix'] or prefix.startswith(other['prefix'] + '/') or other['prefix'].startswith(prefix + '/'):
                            raise ValueError('Lab folders in one repository cannot overlap: ' + (other['prefix'] or 'the repository root') + ' is already a lab folder. Choose a folder beside it.')
                if request.get('retire'): self.registry.remove(source)
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
            problem = getattr(self, 'not_ready', '')
            return dict(repository=repo, ready=not problem, problem=problem, head='a'*40, baseline_revision='', latest_manifest=None)
        return super().remote(host, request, stopping)

    def sibling_lab(self):
        """A second lab bound to its own folder of the same VM checkout ('One repository can hold several labs')."""
        if not hasattr(self, 'registry'): self.registry = [self.repo]
        self.registry.append(dict(self.repo, id='sibling', prefix='sibling', revision='rev-sibling', label='Bens lab / sibling'))
        other = self.register(discovery_tests.YAML.replace(b'name: training', b'name: other-lab'))
        names = [n['name'] for n in self.store.lab(other['id'])['nodes']]
        response = self.client.put('/api/labs/' + other['id'] + '/git', json=dict(binding_id='sibling', node_names=names))
        self.assertEqual(response.status_code, 200, response.text)
        return other

    def save_in(self, lab_id, expect=200, **fields):
        data = dict(request_id=uuid.uuid4().hex, target='latest', push=True, note='Fixture save'); data.update(fields)
        response = self.client.post('/api/labs/' + lab_id + '/git/save', json=data)
        self.assertEqual(response.status_code, expect, response.text)
        return response

    def stored_save(self, lab_id, commit, **fields):
        """A save as an older release could leave it: committed in the shared checkout, waiting for its review."""
        with self.store.lock:
            lab = self.store.lab(lab_id)
            job = dict(id=uuid.uuid4().hex, lab_id=lab_id, lab_name=lab['name'], created='2026-10-01T10:00:00+00:00', status='review_pending',
                       message='Saved on VM; not pushed.', backup_job_id='', target='latest', checkpoint='', note='Stored ' + lab['name'], pushed=False,
                       review_before_push=True, binding_digest=git_digest(lab['git_binding']), request=dict(target='latest', push=False, message='x'),
                       want_push=False, node_names=list(lab['git_binding']['node_names']), capture_context={}, commit=commit, changed_files=['latest/r1.cfg'])
            job.update(fields)
            self.store.state['git_jobs'].append(job); self.store.save()
        return job

    def test_a_save_or_move_waits_while_another_lab_of_the_checkout_has_an_unreviewed_save(self):
        other = self.sibling_lab()
        theirs = self.save_in(other['id'], note='OSPF done').json()
        outcome, _ = self.run_save(theirs); self.assertEqual(outcome['status'], 'review_pending')
        # Saving this lab now would commit on top of that save, and this lab's upload would then carry it unreviewed.
        refused = self.save_in(self.lab['id'], expect=409, note='Mine')
        self.assertIn('other-lab', refused.text); self.assertIn("'OSPF done'", refused.text)
        self.assertIn('review and upload that save', refused.text)
        self.assertIn('Keep snapshot only', refused.text); self.assertIn('goes along with the next upload from this repository', refused.text)
        self.assertEqual([j['lab_id'] for j in self.store.state['git_jobs']], [other['id']], 'nothing was queued')
        # The folder move's automatic upload is held at its source too: nothing changes on the VM.
        sent = len(self.sent)
        moved = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        self.assertEqual(moved.status_code, 409, moved.text); self.assertIn('other-lab', moved.text)
        self.assertFalse([r for r in self.sent[sent:] if r['mode'] == 'register-prefix'])
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['binding_id'], 'bens-lab')
        # A retry that would commit (a save whose export never finished) is held the same way.
        stalled = self.stored_save(self.lab['id'], '', status='export_pending')
        again = self.client.post('/api/git/jobs/' + stalled['id'] + '/retry', json={'push': True})
        self.assertEqual(again.status_code, 409, again.text); self.assertIn('other-lab', again.text)
        self.assertEqual(self.progress.get_job(stalled['id'])['status'], 'export_pending')
        self.progress.update(stalled['id'], status='dismissed')
        # Once the other lab's save is reviewed and uploaded, this lab saves again.
        outcome, _ = self.review_and_upload(theirs); self.assertEqual(outcome['status'], 'synced')
        self.save_in(self.lab['id'], note='Mine')

    def test_saves_stacked_by_an_older_release_upload_only_after_each_was_reviewed(self):
        other = self.sibling_lab()
        theirs = self.stored_save(other['id'], 'd'*40)
        mine = self.stored_save(self.lab['id'], 'c'*40)     # committed on top of theirs before the upgrade
        refused = self.client.post('/api/git/jobs/' + mine['id'] + '/retry', json={'push': True, 'reviewed': True})
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn('other-lab', refused.text); self.assertIn('Your review of this save is kept', refused.text)
        self.assertFalse([r for r in self.sent if r['mode'] == 'push'], 'nothing unreviewed was uploaded')
        kept = self.progress.get_job(mine['id'])
        self.assertTrue(kept['reviewed']); self.assertEqual(kept['status'], 'review_pending')
        diff = self.client.post(self.url + '/compare', json={'job_id': mine['id']})
        self.assertEqual(diff.status_code, 200, diff.text)
        self.assertEqual((diff.json()['also_sends'], diff.json()['also_sends_other_labs']), (1, 1), 'the dialog count includes the other lab')
        self.assertIn('other-lab', diff.json()['upload_blocked'])
        # The other lab's upload may now carry this lab's reviewed save, and the verified result settles both.
        original = self.remote

        def push_settles_both(host, request, stopping=None):
            result = original(host, request, stopping)
            if request['mode'] == 'push': result['synced_operations'] = [theirs['id'], mine['id']]
            return result

        self.helper.side_effect = push_settles_both
        outcome, _ = self.review_and_upload(theirs)
        self.assertEqual(outcome['status'], 'synced')
        self.assertEqual(self.progress.get_job(mine['id'])['status'], 'synced')
        self.assertFalse(pending_progress(self.store.state))

    def test_a_folder_move_that_meets_an_unreviewed_save_of_another_lab_is_kept_on_the_vm(self):
        other = self.sibling_lab()
        response = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()['job']
        self.stored_save(other['id'], 'd'*40)                # appeared while the move waited
        self.progress.execute(job['id'])
        outcome = self.client.get('/api/git/jobs/' + job['id']).json()
        self.assertEqual(outcome['status'], 'committed', outcome); self.assertIn('other-lab', outcome['message'])
        self.assertTrue([r for r in self.sent if r['mode'] == 'move'])
        self.assertFalse([r for r in self.sent if r['mode'] == 'push'], 'the move was not uploaded with the unreviewed save')
        refused = self.client.post('/api/git/jobs/' + job['id'] + '/retry', json={'push': True})
        self.assertEqual(refused.status_code, 409, refused.text); self.assertIn('other-lab', refused.text)

    def test_a_save_kept_with_keep_snapshot_only_is_counted_and_named_in_the_review_until_an_upload_carried_it(self):
        # Review follow-up G1 (audit M-2): a dismissed save is no longer pending, but its commit stays in the checkout
        # and the next upload from this repository sends it. The review says so instead of showing nothing.
        other = self.sibling_lab()
        theirs = self.stored_save(other['id'], 'd'*40, note='OSPF done')
        mine = self.stored_save(self.lab['id'], 'c'*40)
        refused = self.client.post('/api/git/jobs/' + mine['id'] + '/retry', json={'push': True, 'reviewed': True})
        self.assertEqual(refused.status_code, 409, refused.text)
        self.assertIn('goes along with the next upload from this repository', refused.text)
        kept = self.client.post('/api/git/jobs/' + theirs['id'] + '/dismiss', json={'acknowledge': True})
        self.assertEqual(kept.status_code, 200, kept.text)
        answer = self.client.post(self.url + '/compare', json={'job_id': mine['id']}).json()
        self.assertEqual((answer['also_sends'], answer['also_sends_other_labs']), (1, 1), 'the kept commit goes along: the count says so')
        self.assertEqual(answer['also_sends_kept'], [dict(lab='other-lab', note='OSPF done')])
        self.assertNotIn('upload_blocked', answer)
        # A kept save made under an earlier binding of the same checkout counts too (review issue G1-a): the binding
        # digest also changes with the device selection, while the helper still approves that registration's commits.
        # Counting it can over-report (its registration may be retired); leaving it out could under-report.
        older = self.stored_save(other['id'], 'e'*40, status='dismissed', binding_digest='older-binding', note='Before')
        answer = self.client.post(self.url + '/compare', json={'job_id': mine['id']}).json()
        self.assertEqual((answer['also_sends'], answer['also_sends_other_labs']), (2, 2))
        self.assertEqual(answer['also_sends_kept'], [dict(lab='other-lab', note='OSPF done'), dict(lab='other-lab', note='Before')])
        original = self.remote

        def push_carries_it(host, request, stopping=None):
            result = original(host, request, stopping)
            if request['mode'] == 'push': result['synced_operations'] = [theirs['id'], mine['id'], older['id']]
            return result

        self.helper.side_effect = push_carries_it
        outcome, _ = self.review_and_upload(mine); self.assertEqual(outcome['status'], 'synced')
        carried = self.progress.get_job(theirs['id'])
        self.assertEqual((carried['status'], carried['pushed']), ('dismissed', True), 'still dismissed, now known as uploaded')
        self.assertEqual((self.progress.get_job(older['id'])['status'], self.progress.get_job(older['id'])['pushed']), ('dismissed', True),
                         'a kept save of the checkout is matched by its checkout, not by the binding digest of the day')
        later = self.stored_save(self.lab['id'], 'f'*40)
        again = self.client.post(self.url + '/compare', json={'job_id': later['id']}).json()
        self.assertEqual((again['also_sends'], again['also_sends_kept']), (0, []))

    def kept(self, lab_id, commit, note='OSPF done', **fields):
        """A save of this release kept with Keep snapshot only: it froze its checkout and VM when it was made."""
        with self.store.lock: binding = copy.deepcopy(self.store.lab(lab_id)['git_binding'])
        job = self.stored_save(lab_id, commit, note=note, destination=job_destination(binding, 'latest'),
                               host_identity=binding['host_identity'], **fields)
        response = self.client.post('/api/git/jobs/' + job['id'] + '/dismiss', json={'acknowledge': True})
        self.assertEqual(response.status_code, 200, response.text)
        return job

    def review_of(self, lab_id, commit='c'*40):
        mine = self.stored_save(lab_id, commit)
        response = self.client.post('/api/labs/' + lab_id + '/git/compare', json={'job_id': mine['id']})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_a_kept_save_is_still_counted_after_its_lab_chose_other_devices(self):
        # Review issue G1-a (a): Save settings with another device selection changes the binding digest, not the VM
        # registration, so the helper still pushes the kept commit along with the next upload from this lab.
        name = self.store.lab(self.lab['id'])['name']
        self.kept(self.lab['id'], 'd'*40)
        self.stored_save(self.lab['id'], 'e'*40, status='dismissed', note='Older release')   # froze neither checkout nor VM
        response = self.client.put(self.url, json=dict(binding_id=self.repo['id'], node_names=self.names[:1]))
        self.assertEqual(response.status_code, 200, response.text)
        answer = self.review_of(self.lab['id'])
        self.assertEqual((answer['also_sends'], answer['also_sends_other_labs']), (2, 0))
        self.assertEqual(answer['also_sends_kept'], [dict(lab=name, note='OSPF done'), dict(lab=name, note='Older release')])

    def test_a_kept_save_of_a_lab_disconnected_since_is_still_counted(self):
        # Review issue G1-a (b): Disconnect is allowed once the save is dismissed, and the VM keeps its registration and
        # commit. The save froze its checkout and VM, so the review of every other lab of that checkout still counts it.
        other = self.sibling_lab()
        self.kept(other['id'], 'd'*40)
        self.assertEqual(self.client.post('/api/labs/' + other['id'] + '/git/unlink', json={}).status_code, 200)
        answer = self.review_of(self.lab['id'])
        self.assertEqual((answer['also_sends'], answer['also_sends_other_labs']), (1, 1))
        self.assertEqual(answer['also_sends_kept'], [dict(lab='other-lab', note='OSPF done')])

    def test_a_kept_save_whose_answer_was_lost_counts_like_its_pending_form(self):
        # Review issue G1-a (c): the VM may have committed a save whose publication answer was lost. While pending it
        # counts as possibly holding a commit; kept with Keep snapshot only it still may, so it still counts.
        other = self.sibling_lab()
        self.kept(other['id'], '', status='export_pending', published_attempt=True, note='Design lost')
        self.kept(other['id'], '', status='export_pending', expected_head='a'*40, note='Capture lost')
        self.kept(other['id'], '', status='export_pending', note='Never sent')    # stopped before its publication
        self.kept(other['id'], 'd'*40, status='review_pending', pushed=True, note='Uploaded')
        answer = self.review_of(self.lab['id'])
        self.assertEqual((answer['also_sends'], answer['also_sends_other_labs']), (2, 2))
        self.assertEqual([k['note'] for k in answer['also_sends_kept']], ['Design lost', 'Capture lost'])

    def refused_then_kept(self, head_after_push):
        """Review follow-up H1 (audit M-2): another lab's save whose publication the VM refused (no commit, an expected
        HEAD) is kept with Keep snapshot only, then this lab saves and uploads. `head_after_push` is the checkout's HEAD
        the status check reports after that upload (the VM's real answer, `host_git.status`), or an exception."""
        other = self.sibling_lab()
        theirs = self.save_in(other['id'], note='Refused').json()
        original = self.remote; vm = dict(head='a'*40, mine=None)

        def helper(host, request, stopping=None):
            if request['mode'] == 'publish' and request['operation_id'] == theirs['id']:
                self.sent.append(copy.deepcopy(request))   # host_git.publish: expected_head no longer HEAD, nothing written
                return dict(status='needs_attention', commit=None, changed_files=[], pushed=False, snapshot_path='latest', synced_operations=None,
                            message='The repository changed since it was selected. Refresh status and retry the preserved snapshot.')
            if request['mode'] == 'status' and vm['mine'] and any(r['mode'] == 'push' for r in self.sent):
                self.sent.append(copy.deepcopy(request))
                if isinstance(head_after_push, Exception): raise head_after_push
                return dict(repository=self.repo, ready=True, problem='', head=head_after_push, baseline_revision='', latest_manifest=None)
            result = original(host, request, stopping)
            if request['mode'] == 'push': result['synced_operations'] = [vm['mine']]   # the helper names only verified journals
            return result

        self.helper.side_effect = helper
        outcome, _ = self.run_save(theirs)
        self.assertEqual((outcome['status'], outcome['commit']), ('export_pending', None), outcome)
        self.assertTrue(kept_on_vm(dict(self.progress.get_job(theirs['id']), status='dismissed')), 'it sent a publication')
        self.assertEqual(self.client.post('/api/git/jobs/' + theirs['id'] + '/dismiss', json={'acknowledge': True}).status_code, 200)
        mine = self.save_in(self.lab['id'], note='Mine').json(); vm['mine'] = mine['id']
        outcome, _ = self.run_save(mine); self.assertEqual(outcome['status'], 'review_pending')
        answer = self.client.post(self.url + '/compare', json={'job_id': mine['id']}).json()
        self.assertEqual(answer['also_sends_kept'], [dict(lab='other-lab', note='Refused')], 'counted while the VM may hold a commit of it')
        outcome, _ = self.review_and_upload(mine); self.assertEqual(outcome['status'], 'synced', outcome)
        return theirs

    def test_a_kept_save_the_vm_refused_stops_counting_once_an_upload_of_the_checkouts_head_was_verified(self):
        # The helper names only saves it journaled with a verified commit, so this one was never named and was counted in
        # every later review forever, beyond the jobs cap too. An upload verified to have put the checkout's HEAD on the
        # remote proves nothing of it is left to go along: it ends there, privately, never as uploaded.
        theirs = self.refused_then_kept('b'*40)
        answer = self.review_of(self.lab['id'], 'f'*40)
        self.assertEqual((answer['also_sends'], answer['also_sends_kept']), (0, []))
        stored = self.progress.get_job(theirs['id'])
        self.assertEqual((stored['status'], stored['pushed']), ('dismissed', False), 'still kept, never claimed as uploaded')
        self.assertTrue(stored['head_uploaded']); self.assertFalse(kept_on_vm(stored))
        self.assertNotIn('head_uploaded', self.client.get('/api/git/jobs/' + theirs['id']).json())
        self.assertEqual([j for j in self.client.get('/api/state').json()['git_jobs'] if 'head_uploaded' in j], [])
        self.assertTrue(next(j for j in Store(self.tmp.name).state['git_jobs'] if j['id'] == theirs['id'])['head_uploaded'], 'stored')
        with self.store.lock:
            for n in range(GIT_JOB_CAP): _append_git_job(self.store.state, dict(id='later' + str(n), status='synced'))
            self.assertNotIn(theirs['id'], [j['id'] for j in self.store.state['git_jobs']], 'the cap lets it go')

    def still_counted(self, theirs):
        self.assertNotIn('head_uploaded', self.progress.get_job(theirs['id']))
        self.assertEqual(self.review_of(self.lab['id'], 'f'*40)['also_sends_kept'], [dict(lab='other-lab', note='Refused')])

    def test_a_kept_save_stays_counted_while_the_checkouts_head_is_past_the_uploaded_commit(self):
        # A HEAD that is not the uploaded commit (an older save uploaded while newer commits sit on top) may still hold a
        # commit of the kept save that a later upload carries: it stays counted.
        self.still_counted(self.refused_then_kept('c'*40))

    def test_a_kept_save_stays_counted_when_the_check_after_the_upload_fails(self):
        # A status check that fails proves nothing; the upload itself stays verified (synced, checked above).
        self.still_counted(self.refused_then_kept(ValueError('Git connection interrupted.')))

    def test_a_kept_save_of_another_branch_or_remote_of_the_checkout_is_not_settled_by_this_upload(self):
        # The helper approves a journal for a push only from the same checkout, push URL and branch: an upload on another
        # branch of the folder proves nothing about a save made on this one.
        theirs = self.refused_then_kept('b'*40)
        stored = self.progress.get_job(theirs['id'])
        self.assertTrue(stored['head_uploaded'])
        for change in (dict(branch='dev'), dict(remote='https://example.test/other.git')):
            self.progress.update(theirs['id'], head_uploaded=False, destination=dict(stored['destination'], **change))
            mine = self.stored_save(self.lab['id'], 'b'*40, reviewed='2026-10-03T10:00:00+00:00')
            self.assertEqual(self.client.post('/api/git/jobs/' + mine['id'] + '/retry', json={'push': True}).status_code, 200)
            self.progress.execute(mine['id'])
            self.assertFalse(self.progress.get_job(theirs['id'])['head_uploaded'], change)

    def test_a_save_has_its_vm_host_identity_frozen_privately_with_its_checkout(self):
        saved = self.save_in(self.lab['id']).json()
        stored = self.progress.get_job(saved['id'])
        self.assertEqual((stored['host_identity'], stored['destination']['checkout']),
                         (self.store.lab(self.lab['id'])['git_binding']['host_identity'], self.repo['path']))
        self.assertNotIn('host_identity', saved)
        self.assertNotIn('host_identity', self.client.get('/api/git/jobs/' + saved['id']).json())
        self.assertEqual([j for j in self.client.get('/api/state').json()['git_jobs'] if 'host_identity' in j], [])

    def test_a_kept_save_of_another_checkout_or_another_vm_is_not_counted(self):
        other = self.sibling_lab()
        elsewhere = self.kept(other['id'], 'd'*40, note='Elsewhere')
        self.progress.update(elsewhere['id'], destination=dict(elsewhere['destination'], checkout='/home/ben/labs/other'))
        far = self.kept(other['id'], 'e'*40, note='Other VM')
        self.progress.update(far['id'], host_identity='another-vm')
        answer = self.review_of(self.lab['id'])
        self.assertEqual((answer['also_sends'], answer['also_sends_kept']), (0, []))

    def test_two_labs_whose_saves_both_lack_a_commit_never_hold_each_others_retry_back(self):
        # Review follow-up G2 (audit M-2): an older release could leave one commit-less save per lab of a checkout.
        other = self.sibling_lab()
        theirs = self.stored_save(other['id'], '', status='export_pending', backup_job_id=self.capture(other['id'])['id'])
        mine = self.stored_save(self.lab['id'], '', status='interrupted', backup_job_id=self.capture()['id'])
        first = self.client.post('/api/git/jobs/' + mine['id'] + '/retry', json={'push': True})
        self.assertEqual(first.status_code, 200, first.text)
        self.assertFalse(self.progress.get_job(mine['id'])['retry_push'], 'a retry without a commit only saves on the VM')
        outcome, _ = self.run_save(mine); self.assertEqual(outcome['status'], 'review_pending')
        self.assertFalse([r for r in self.sent if r['mode'] == 'push'])
        # Now this lab holds a commit nobody reviewed: the other lab's retry waits for that review, and this lab's
        # upload for the other lab's save. The refused upload keeps its review, which lets the other retry go on.
        self.assertEqual(self.client.post('/api/git/jobs/' + theirs['id'] + '/retry', json={'push': True}).status_code, 409)
        held = self.client.post('/api/git/jobs/' + mine['id'] + '/retry', json={'push': True, 'reviewed': True})
        self.assertEqual(held.status_code, 409, held.text); self.assertIn('Your review of this save is kept', held.text)
        self.assertEqual(self.client.post('/api/git/jobs/' + theirs['id'] + '/retry', json={'push': True}).status_code, 200)
        outcome, _ = self.run_save(theirs); self.assertEqual(outcome['status'], 'review_pending')
        for job in (theirs, mine):
            outcome, _ = self.review_and_upload(job); self.assertEqual(outcome['status'], 'synced')
        self.assertFalse(pending_progress(self.store.state))

    def test_a_retry_without_a_commit_still_waits_for_another_labs_save_that_has_one(self):
        other = self.sibling_lab()
        self.stored_save(other['id'], 'd'*40)
        stalled = self.stored_save(self.lab['id'], '', status='export_pending')
        for push in (True, False):
            refused = self.client.post('/api/git/jobs/' + stalled['id'] + '/retry', json={'push': push})
            self.assertEqual(refused.status_code, 409, refused.text); self.assertIn('other-lab', refused.text)
        self.assertEqual(self.progress.get_job(stalled['id'])['status'], 'export_pending')

    def test_a_refused_folder_change_leaves_the_lab_on_its_existing_registration(self):
        self.faithful = True; self.registry = [dict(self.repo)]
        with self.store.lock:   # a discovery sync removed a device after the lab was connected
            self.store.lab(self.lab['id'])['git_binding']['node_names'].append('removed-router'); self.store.save()
        refused = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        self.assertIn(refused.status_code, (400, 409), refused.text); self.assertIn('Save settings', refused.text)
        self.assertEqual([r['id'] for r in self.registry], ['bens-lab'], 'the registration the lab uses still exists')
        self.assertFalse([r for r in self.sent if r['mode'] == 'register-prefix'])
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['binding_id'], 'bens-lab')
        self.assertEqual(self.client.get(self.url + '/history').status_code, 200)
        # One connection change at a time, so nothing can take the new folder between the checks and the retire.
        with self.store.lock: self.store.lab(self.lab['id'])['git_binding']['node_names'].remove('removed-router'); self.store.save()
        with self.progress.binding_lock:
            busy = self.client.post(self.url + '/destination', json=dict(prefix='bgp'))
            self.assertEqual(busy.status_code, 409, busy.text); self.assertIn('Try again in a moment', busy.text)
            self.assertEqual(self.client.put(self.url, json=dict(binding_id='bens-lab', node_names=self.names)).status_code, 409)
        self.assertFalse([r for r in self.sent if r['mode'] == 'register-prefix'])
        self.assertEqual(self.client.post(self.url + '/destination', json=dict(prefix='bgp')).status_code, 200)

    def test_a_folder_change_the_vm_already_made_is_kept_when_work_starts_or_the_answer_is_lost(self):
        self.faithful = True; self.registry = [dict(self.repo)]
        original = self.remote; lose = {'answer': False}
        backup = dict(id=uuid.uuid4().hex, lab_id=self.lab['id'], operation='backup', status='running', nodes=[], created='2026-10-01T10:00:00+00:00')

        def racing(host, request, stopping=None):
            result = original(host, request, stopping)
            if request['mode'] == 'register-prefix':
                with self.store.lock: self.store.state['jobs'].insert(0, backup)   # a backup started meanwhile
                if lose['answer']: raise ValueError('Git connection interrupted. Retry this saved operation to reconcile its result.')
            return result

        self.helper.side_effect = racing
        moved = self.client.post(self.url + '/destination', json=dict(prefix='bgp'))
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['binding_id'], 'register-prefix-bgp')
        self.assertEqual([r['id'] for r in self.registry], ['register-prefix-bgp'])
        self.store.state['jobs'].remove(backup)
        lose['answer'] = True
        again = self.client.post(self.url + '/destination', json=dict(prefix='ospf'))
        self.assertEqual(again.status_code, 200, again.text)
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['repository']['prefix'], 'ospf')
        self.assertEqual([r['prefix'] for r in self.registry], ['ospf'])
        self.store.state['jobs'].remove(backup)
        self.assertIn('ospf', self.store.state['git_folders'][self.repo['path']])

    def test_a_folder_change_whose_answer_and_check_were_both_lost_is_followed_by_the_next_change(self):
        # Review follow-up G3 (audit M-3): the VM made the change, its answer was lost and so was the list that would
        # have shown it. The lab's registration is gone; the next Change folder follows the VM instead of browsing with it.
        self.faithful = True; self.registry = [dict(self.repo)]
        original = self.remote; lost = {'answer': True, 'list': 0}

        def lossy(host, request, stopping=None):
            if request['mode'] == 'list' and lost['list']:
                lost['list'] -= 1; raise ValueError('Git connection interrupted. Retry this saved operation to reconcile its result.')
            result = original(host, request, stopping)
            if request['mode'] == 'register-prefix' and lost['answer']:
                lost.update(answer=False, list=1); raise ValueError('Git connection interrupted. Retry this saved operation to reconcile its result.')
            return result

        self.helper.side_effect = lossy
        first = self.client.post(self.url + '/destination', json=dict(prefix='bgp'))
        self.assertEqual(first.status_code, 409, first.text)
        self.assertEqual([r['id'] for r in self.registry], ['register-prefix-bgp'], 'the VM made the change')
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['binding_id'], 'bens-lab')
        self.assertEqual(self.client.get(self.url + '/history').status_code, 409)
        # Another folder cannot be reached from a registration that no longer exists; the answer says what to do.
        elsewhere = self.client.post(self.url + '/destination', json=dict(prefix='ospf'))
        self.assertEqual(elsewhere.status_code, 409, elsewhere.text); self.assertIn('choose that folder again', elsewhere.text)
        self.assertEqual([r['id'] for r in self.registry], ['register-prefix-bgp'])
        again = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        self.assertEqual(again.status_code, 200, again.text)
        binding = self.store.lab(self.lab['id'])['git_binding']
        self.assertEqual((binding['binding_id'], binding['repository']['prefix'], binding['node_names']), ('register-prefix-bgp', 'bgp', self.names))
        self.assertEqual(again.json()['job']['target'], 'move', 'the files still move from the folder the lab left')
        self.assertEqual(self.store.state['git_jobs'][-1]['request']['source_prefix'], '')
        self.assertEqual(len([r for r in self.sent if r['mode'] == 'register-prefix']), 1, 'nothing was registered twice')
        self.assertEqual(self.client.get(self.url + '/history').status_code, 200)

    def test_a_folder_change_is_never_adopted_from_a_vm_connection_switched_during_the_call(self):
        self.faithful = True; self.registry = [dict(self.repo)]
        original = self.remote

        def switched(host, request, stopping=None):
            result = original(host, request, stopping)
            if request['mode'] == 'register-prefix':
                with self.store.lock: self.store.state['host']['address'] = '192.0.2.99'   # another VM connected meanwhile
                raise ValueError('Git connection interrupted. Retry this saved operation to reconcile its result.')
            return result

        self.helper.side_effect = switched
        moved = self.client.post(self.url + '/destination', json=dict(prefix='bgp'))
        self.assertEqual(moved.status_code, 409, moved.text)
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['binding_id'], 'bens-lab', 'nothing adopted from another connection')

    def test_a_folder_change_is_never_adopted_from_a_vm_connection_switched_during_the_check_after_a_lost_answer(self):
        # Review issue G3-a: the connection can also be switched while retired_already() lists the catalog itself.
        self.faithful = True; self.registry = [dict(self.repo)]
        original = self.remote; lost = {'answer': False}

        def switched(host, request, stopping=None):
            result = original(host, request, stopping)
            if request['mode'] == 'register-prefix':
                lost['answer'] = True; raise ValueError('Git connection interrupted. Retry this saved operation to reconcile its result.')
            if request['mode'] == 'list' and lost['answer']:
                with self.store.lock: self.store.state['host']['address'] = '192.0.2.99'   # another VM connected meanwhile
            return result

        self.helper.side_effect = switched
        moved = self.client.post(self.url + '/destination', json=dict(prefix='bgp'))
        self.assertEqual(moved.status_code, 409, moved.text)
        self.assertEqual([r['id'] for r in self.registry], ['register-prefix-bgp'], 'the first VM made the change')
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['binding_id'], 'bens-lab', 'nothing adopted from another connection')

    def test_a_registration_that_vanishes_between_the_list_and_the_browse_is_followed_not_browsed(self):
        # Review issue G3-a: the catalog still showed the lab's registration, then an earlier change of this folder
        # landed on the VM and the browse answers "Select a registered Git repository.": the change is followed.
        self.faithful = True; self.registry = [dict(self.repo)]
        original = self.remote

        def vanishing(host, request, stopping=None):
            if request['mode'] == 'browse' and any(r['id'] == 'bens-lab' for r in self.registry):
                self.registry[:] = [dict(self.repo, id='register-prefix-bgp', prefix='bgp', revision='rev-bgp', label='Bens lab / bgp')]
            return original(host, request, stopping)

        self.helper.side_effect = vanishing
        moved = self.client.post(self.url + '/destination', json=dict(prefix='bgp'))
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['binding_id'], 'register-prefix-bgp')
        self.assertEqual([r['mode'] for r in self.sent if r['mode'] in ('browse', 'register-prefix')], ['browse'], 'nothing registered again')
        self.assertEqual(self.client.get(self.url + '/history').status_code, 200)

    def test_this_labs_saves_and_disconnect_wait_while_its_repository_connection_is_being_changed(self):
        # Review follow-up G4 (audit M-3): a folder change rewrites the lab's binding after the VM answered. A Disconnect
        # or a save from another tab in that window would be undone or left unretryable, so both wait. Another lab's
        # save does not (review issue G4-a): its binding is not being changed, and a URL clone can take minutes.
        other = self.sibling_lab(); seen = {}
        original = self.remote

        def meanwhile(host, request, stopping=None):
            if request['mode'] == 'register-prefix' and not seen:   # another tab, while the VM changes this lab's folder
                seen.update(save=self.save_in(self.lab['id'], expect=409).text, unlink=self.client.post(self.url + '/unlink', json={}),
                            other=self.save_in(other['id']).json())
            return original(host, request, stopping)

        self.helper.side_effect = meanwhile
        moved = self.client.post(self.url + '/destination', json=dict(prefix='bgp'))
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertIn('Try again in a moment', seen['save'])
        self.assertEqual(seen['unlink'].status_code, 409, seen['unlink'].text); self.assertIn('Try again in a moment', seen['unlink'].text)
        self.assertEqual([j['lab_id'] for j in self.store.state['git_jobs']], [other['id']])
        self.assertEqual(self.store.lab(self.lab['id'])['git_binding']['binding_id'], 'register-prefix-bgp', 'the Disconnect was not undone')
        # Any connection change still waits for another one (they check and retire registrations of one checkout),
        # while saves wait only for a change of their own lab.
        self.progress.update(seen['other']['id'], status='dismissed')
        with self.progress.changing(other['id']):
            unlink = self.client.post(self.url + '/unlink', json={})
            self.assertEqual(unlink.status_code, 409, unlink.text); self.assertIn('Try again in a moment', unlink.text)
            mine = self.save_in(self.lab['id']).json()
        self.progress.update(mine['id'], status='dismissed')
        self.assertEqual(self.client.post(self.url + '/unlink', json={}).status_code, 200)
        self.assertNotIn('git_binding', self.store.lab(self.lab['id']))

    def test_a_folder_move_that_stops_before_its_commit_or_loses_its_answer_stays_retryable(self):
        response = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        job = response.json()['job']
        self.not_ready = 'The repository already has staged changes.'
        self.progress.execute(job['id'])
        outcome = self.client.get('/api/git/jobs/' + job['id']).json()
        self.assertEqual(outcome['status'], 'export_pending', outcome); self.assertIn('staged changes', outcome['message'])
        self.not_ready = ''; self.publish_error = 'Git connection interrupted. Retry this saved operation to reconcile its result.'
        self.assertEqual(self.client.post('/api/git/jobs/' + job['id'] + '/retry', json={'push': True}).status_code, 200)
        self.progress.execute(job['id'])
        self.assertEqual(self.client.get('/api/git/jobs/' + job['id']).json()['status'], 'export_pending', 'a lost answer is never failed')
        self.publish_error = ''
        self.assertEqual(self.client.post('/api/git/jobs/' + job['id'] + '/retry', json={'push': True}).status_code, 200)
        self.progress.execute(job['id'])
        self.assertEqual(self.client.get('/api/git/jobs/' + job['id']).json()['status'], 'synced')
        moves = [r for r in self.sent if r['mode'] == 'move']
        self.assertEqual({r['operation_id'] for r in moves}, {job['id']}, 'every retry replays the same journaled move')

    def test_a_move_an_older_release_marked_failed_can_be_retried(self):
        response = self.client.post(self.url + '/destination', json=dict(prefix='bgp', move_files=True))
        job = response.json()['job']
        self.progress.update(job['id'], status='failed', message='Repository needs attention before moving folders.')
        self.assertEqual(self.client.post('/api/git/jobs/' + job['id'] + '/retry', json={'push': False}).status_code, 200)
        self.progress.execute(job['id'])
        outcome = self.client.get('/api/git/jobs/' + job['id']).json()
        self.assertEqual(outcome['status'], 'committed', outcome)
        self.assertFalse([r for r in self.sent if r['mode'] == 'push'], 'a retry on this VM only does not upload')

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

    def test_an_empty_folder_stays_in_the_tree_when_the_lab_moves_on_and_the_vm_retires_its_registration(self):
        # The reported case: the lab saves to JunOS-TEST-2, a folder "working" is created beneath it.
        self.faithful = True
        self.registry = [dict(self.repo, prefix='JunOS-TEST-2')]
        tree = lambda: self.client.get('/api/git/repositories/' + self.store.lab(self.lab['id'])['git_binding']['binding_id'] + '/tree').json()
        with self.store.lock:
            self.store.lab(self.lab['id'])['git_binding']['repository']['prefix'] = 'JunOS-TEST-2'; self.store.save()
        # Beside-the-lab registration is impossible inside the lab's own folder; a planned folder is not.
        refused = self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix='JunOS-TEST-2/working'))
        self.assertEqual(refused.status_code, 409); self.assertIn('cannot overlap', refused.text)
        self.assertEqual(tree()['planned'], [], 'a refused creation leaves no phantom folder')
        planned = self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix='JunOS-TEST-2/working', plan=True))
        self.assertEqual(planned.status_code, 200, planned.text); self.assertEqual(planned.json(), {'planned': 'JunOS-TEST-2/working'})
        self.assertFalse([r for r in self.sent if r['mode'] == 'register-prefix' and r['prefix'] == 'JunOS-TEST-2/working' and r.get('retire')], 'planning registers nothing on the VM')
        self.assertEqual(tree()['planned'], ['JunOS-TEST-2/working'])
        self.assertEqual([f['prefix'] for f in tree()['folders']], ['JunOS-TEST-2'], 'the save destination did not change')
        # Duplicates are refused accurately: planned, a lab folder, and a committed folder.
        for name in ('JunOS-TEST-2/working', 'JunOS-TEST-2', 'bgp'):
            again = self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix=name, plan=True))
            self.assertEqual(again.status_code, 409, name); self.assertIn('already exists', again.text)
        self.assertEqual(self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix='', plan=True)).status_code, 400)
        # The lab moves into it, then on to a second folder, then back: the VM keeps one registration only.
        for prefix in ('JunOS-TEST-2/working', 'JunOS-TEST-2/solution', 'JunOS-TEST-2'):
            moved = self.client.post(self.url + '/destination', json=dict(prefix=prefix))
            self.assertEqual(moved.status_code, 200, moved.text)
            self.assertEqual([r['prefix'] for r in self.registry], [prefix])
        now = tree()
        self.assertEqual([f['prefix'] for f in now['folders']], ['JunOS-TEST-2'])
        self.assertEqual(sorted(now['planned']), ['JunOS-TEST-2', 'JunOS-TEST-2/solution', 'JunOS-TEST-2/working'], 'the folders the lab left are still there')
        self.assertEqual(sorted(Store(self.tmp.name).state['git_folders'][self.repo['path']]), sorted(now['planned']), 'and they survive a restart')
        self.assertNotIn('git_folders', self.client.get('/api/state').json())
        # A planned folder that was never used can be forgotten; nothing on the VM is involved.
        sent = len(self.sent)
        gone = self.client.request('DELETE', '/api/git/repositories/' + self.registry[0]['id'] + '/folders', json=dict(prefix='JunOS-TEST-2/solution'))
        self.assertEqual(gone.status_code, 200, gone.text)
        self.assertEqual(len([r for r in self.sent[sent:] if r['mode'] not in ('list',)]), 0)
        self.assertNotIn('JunOS-TEST-2/solution', tree()['planned'])
        self.assertEqual(self.client.request('DELETE', '/api/git/repositories/' + self.registry[0]['id'] + '/folders', json=dict(prefix='never-made')).status_code, 404)

    def test_a_failed_store_write_creates_no_planned_folder(self):
        persist = self.store.save
        with patch.object(self.store, 'save', side_effect=OSError('disk')):
            response = self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix='notes', plan=True))
        self.assertEqual(response.status_code, 500); self.assertIn('Nothing was created', response.text)
        self.assertEqual(self.client.get('/api/git/repositories/bens-lab/tree').json()['planned'], [])
        self.assertTrue(callable(persist))

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
        # A move that stopped before its commit stays retryable (it was 'failed', which nothing could retry).
        self.assertEqual(outcome['status'], 'export_pending', outcome)
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

    def test_destination_refuses_reserved_names_and_snapshot_conflicts(self):
        # Rule 1: a reserved lab-folder shape is refused before the repository is even read.
        reserved = self.client.post(self.url + '/destination', json=dict(prefix='working/latest'))
        self.assertEqual(reserved.status_code, 400, reserved.text)
        self.assertIn('Choose the folder above them', reserved.text)
        self.assertFalse([r for r in self.sent if r['mode'] == 'browse'], 'no tree read for a name refused outright')
        # Rule 2: a prefix at, or below, an existing snapshot folder is refused (409); the manager
        # never registers or writes anything on the VM for it.
        self.extra_files = [dict(path='Final/manifest.json', size=50), dict(path='Final/latest/manifest.json', size=60)]
        at = self.client.post(self.url + '/destination', json=dict(prefix='Final'))
        self.assertEqual(at.status_code, 409, at.text); self.assertIn('Final is a saved configuration', at.text)
        self.assertIn('manifest.json', at.text)
        below = self.client.post(self.url + '/destination', json=dict(prefix='Final/sub'))
        self.assertEqual(below.status_code, 409, below.text); self.assertIn('Final is a saved configuration', below.text)
        self.assertFalse([r for r in self.sent if r['mode'] == 'register-prefix'], 'a refused destination registers nothing')
        # A folder beside the snapshot, not at or below it, is unaffected by rule 2.
        beside = self.client.post(self.url + '/destination', json=dict(prefix='Other'))
        self.assertEqual(beside.status_code, 200, beside.text)

    def test_folders_route_refuses_reserved_names_and_snapshot_conflicts(self):
        self.extra_files = [dict(path='Final/manifest.json', size=50), dict(path='Final/latest/manifest.json', size=60)]
        for form in (dict(prefix='Final'), dict(prefix='Final/sub'), dict(prefix='Final', plan=True), dict(prefix='Final/sub', plan=True)):
            response = self.client.post('/api/git/repositories/bens-lab/folders', json=form)
            self.assertEqual(response.status_code, 409, response.text); self.assertIn('is a saved configuration', response.text)
        self.assertFalse([r for r in self.sent if r['mode'] in ('register-prefix', 'connect')])
        reserved = self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix='working/latest'))
        self.assertEqual(reserved.status_code, 400, reserved.text)
        reserved_plan = self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix='working/checkpoints/one', plan=True))
        self.assertEqual(reserved_plan.status_code, 400, reserved_plan.text)
        # A folder beside the snapshot still registers normally.
        ok = self.client.post('/api/git/repositories/bens-lab/folders', json=dict(prefix='Other'))
        self.assertEqual(ok.status_code, 200, ok.text)


# The subclass only adds scenarios; the inherited scenarios already run once above.
for _name in [n for n in dir(GitProgressTests) if n.startswith('test_')]:
    setattr(GitPlacesTests, _name, None)
