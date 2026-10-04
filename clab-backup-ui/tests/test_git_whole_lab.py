"""A Git save is the whole lab (owner goal G1): the topology file and the map travel with every save.

Each test states one claim. The VM side is the real `host_git.GitRepository` on a throw-away checkout (the same
helper a VM runs, local remote allowed), so "unchanged", the compare and the saved-version views are the helper's
own answers, not a script. The manager side is the real app (`create_app(<temp dir>)`); only the transport
(`remote_git`) and the background pool are replaced, and the capture is the real `Runner.embed_topology` over a
fixture backup record. Nothing here touches live data.

The `test_gap_*` tests document today's behaviour where a save reaches the repository without the topology or the
map (or with a different one) although the lab has them. They assert what happens today and carry a one-line
comment saying what G1 would require instead; none is an expected failure.
"""
import base64
import copy
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
import zipfile

from app import __version__
from app.downloads import topology_names
from app.git_progress import PROTOCOL, annotated_compare, captured_snapshot, decoded_snapshot, snapshot_diff
from app.host_git import GitRepository, content_digest
from app.layout import map_document
from app.vm_files import decode_bundle
import test_discovery as discovery_tests
import test_git_progress as progress_tests

LAB_YAML = discovery_tests.YAML.decode()
TOPOLOGY_FILE = 'training.clab.yml'
MAP_FILE = 'training.clab.yml.annotations.json'
VM_YAML = LAB_YAML.replace('r1: {}', 'r1:\n      mgmt-ipv4: 172.20.20.77')   # the deployed file differs from the manager's copy
VM_MAP = json.dumps({'nodeAnnotations': [{'id': 'r1', 'label': 'r1', 'position': {'x': 500, 'y': 600}, 'yamlNodeId': 'r1'}]}, indent=2)
INVENTORY = b'''all:
  children:
    cisco_xrv9k:
      vars: {ansible_user: clab, ansible_password: test-secret}
      hosts:
        clab-example-PE1: {ansible_host: 172.20.20.5}
    juniper_cjunosevolved:
      hosts:
        clab-example-PE2: {ansible_host: 172.20.20.3}
'''


def sha(text):
    return hashlib.sha256(text if isinstance(text, bytes) else text.encode()).hexdigest()


def vm_bundle(definition, annotations=None, path='/srv/labs/training/training.clab.yml'):
    """What discovery keeps of the files beside the deployed topology on the VM (`vm_files.decode_bundle`)."""
    def item(raw, where):
        raw = raw.encode() if isinstance(raw, str) else raw
        return dict(content=base64.b64encode(raw).decode(), sha256=sha(raw), path=where)
    files = {'definition': item(definition, path)}
    if annotations is not None: files['annotations'] = item(annotations, path + '.annotations.json')
    return decode_bundle(dict(files=files))


@unittest.skipUnless(shutil.which('git'), 'Git executable required')
class WholeLabCase(unittest.TestCase):
    setUp_base = discovery_tests.DiscoveryTests.setUp
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host
    poll = discovery_tests.DiscoveryTests.poll
    capture = progress_tests.GitProgressTests.capture      # a backup record with its device files, topology only when asked
    save = progress_tests.GitProgressTests.save
    run_save = progress_tests.GitProgressTests.run_save

    def setUp(self):
        self.setUp_base()
        self.progress = self.app.state.git_progress
        self.host(); self.store.state['host']['fingerprint'] = 'SHA256:fixture'
        self.lab = self.register(); self.url = '/api/labs/' + self.lab['id'] + '/git'
        # The VM: the real helper on a scratch checkout with a bare remote.
        self.vm = tempfile.TemporaryDirectory(); self.addCleanup(self.vm.cleanup)
        base = Path(self.vm.name); repo = base / 'repo'; repo.mkdir(); home = base / 'home'; home.mkdir()
        self.env = {**os.environ, 'HOME': str(home), 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                    'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '0'}
        for key in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'): self.env.pop(key, None)
        self.git = shutil.which('git'); self.checkout = repo
        self.raw('init', '--bare', str(base / 'remote.git'), cwd=base)
        self.raw('init', '-b', 'main'); self.raw('config', 'user.name', 'Fixture Ben'); self.raw('config', 'user.email', 'ben@example.invalid')
        self.raw('config', 'core.autocrlf', 'false')
        (repo / 'README.md').write_text('Existing lab\n'); self.raw('add', 'README.md'); self.raw('commit', '-m', 'Initial lab')
        self.raw('remote', 'add', 'origin', str(base / 'remote.git')); self.raw('push', '-u', 'origin', 'main')
        binding = dict(id='bens-lab', label='Bens lab', owner='ben', path=str(repo), home=str(home), remote='origin', branch='main',
                       prefix='', push_url=str(base / 'remote.git'), revision='a' * 64)
        self.worker = GitRepository(binding, git=self.git, allow_local=True, env=self.env)
        self.sent = []
        patch('app.git_progress.remote_git', side_effect=self.remote).start()
        self.addCleanup(patch.stopall)
        self.dispatch = patch.object(self.progress.pool, 'submit').start()
        self.names = [n['name'] for n in self.store.lab(self.lab['id'])['nodes']]
        response = self.client.put(self.url, json=dict(binding_id='bens-lab', node_names=self.names))
        self.assertEqual(response.status_code, 200, response.text)

    def tearDown(self):
        self.app.state.operations.close()
        discovery_tests.DiscoveryTests.tearDown(self)

    def raw(self, *args, cwd=None):
        result = subprocess.run([self.git, *args], cwd=cwd or self.checkout, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        return result.stdout.decode().strip()

    def remote(self, host, request, stopping=None):
        self.sent.append(copy.deepcopy(request))
        if request['mode'] == 'list':
            return dict(protocol=PROTOCOL, version=__version__, repositories=[self.worker.descriptor()])
        return self.worker.dispatch(request)

    # ---- captures -------------------------------------------------------------------------------------------

    def fresh_capture(self, lab_id=None, **kwargs):
        """A backup record as the runner leaves it: the device files, then the real `Runner.embed_topology` over
        the lab as the manager holds it now (VM files from the last discovery pass when it has them)."""
        job = self.capture(lab_id, **kwargs)
        lab = copy.deepcopy(self.store.lab(job['lab_id']))
        log = lambda action, message, level='info', node='': self.store.event(action, message, level=level, lab_id=lab['id'], job_id=job['id'], node=node)
        record = self.app.state.runner.embed_topology(lab, self.store.root / 'backups' / lab['id'], job['id'], log)
        stored = next(j for j in self.store.state['jobs'] if j['id'] == job['id'])
        if record: stored['topology'] = record
        self.store.save()
        return copy.deepcopy(stored)

    def old_capture(self, **kwargs):
        """A capture that carries no embedded topology record: taken before embedding existed."""
        job = self.capture(**kwargs)
        self.assertNotIn('topology', job)
        return job

    def saved(self, capture=None, **fields):
        """Save and run the whole job against the real helper; the save never uploads (push is a later, reviewed step)."""
        fields.setdefault('push', False)
        if capture is not None: fields['backup_job_id'] = capture['id']
        job, _ = self.save(**fields)
        outcome, submit = self.run_save(job)
        return outcome, submit

    def fresh_save(self, **fields):
        """A save that makes its own capture, which is the real embedding over a fixture backup."""
        job, _ = self.save(**{'push': False, **fields})
        with patch.object(self.app.state.runner, 'submit', side_effect=self.fresh_capture) as submit:
            self.progress.execute(job['id'])
        return self.client.get('/api/git/jobs/' + job['id']).json(), submit

    def published(self):
        return [r for r in self.sent if r['mode'] == 'publish'][-1]['snapshot']

    def by_kind(self, manifest):
        found = {}
        for entry in manifest['files']:
            if entry.get('kind'): found.setdefault(entry['kind'], []).append(entry)
        return found

    def version(self, commit, path='latest'):
        response = self.client.post(self.url + '/version', json=dict(commit=commit, path=path))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def names_in(self, commit, path='latest'):
        return sorted(f['name'] for f in self.version(commit, path)['files'])

    def lab_state(self):
        return self.store.lab(self.lab['id'])

    def move_node(self, x):
        """The student moves a node in Edit map and saves it (the manager-only map write)."""
        document = self.client.get('/api/labs/' + self.lab['id'] + '/map-document').json()
        data = json.loads(document['annotations']); data['nodeAnnotations'][0]['position'] = {'x': x, 'y': 40}
        response = self.client.put('/api/labs/' + self.lab['id'] + '/map-document',
                                   json=dict(annotations=json.dumps(data, indent=2), revision=document['revision']))
        self.assertEqual(response.status_code, 200, response.text)

    def change_topology(self, text):
        """Update topology file…: the same lab, new text, the map document untouched."""
        before = map_document(self.lab_state())
        self.register(raw=text.encode(), lab_id=self.lab['id'])
        self.assertEqual(self.lab_state()['definition_yaml'], text)
        self.assertEqual(map_document(self.lab_state()), before, 'the fixture changes the topology file only')


class EveryWholeSaveCarriesTheLabTests(WholeLabCase):
    """Claims 1 and 2: the topology file and the map are in every save target made from a capture."""

    def assert_whole(self, snapshot, topology_text, map_text, source='manager'):
        manifest = snapshot['manifest']; kinds = self.by_kind(manifest)
        self.assertEqual({k: len(v) for k, v in kinds.items()}, {'topology': 1, 'annotations': 1}, 'one entry of each kind')
        topology, annotations = kinds['topology'][0], kinds['annotations'][0]
        self.assertEqual((topology['path'], annotations['path']), (TOPOLOGY_FILE, MAP_FILE))
        self.assertEqual((topology['size'], topology['sha256']), (len(topology_text.encode()), sha(topology_text)))
        self.assertEqual((annotations['size'], annotations['sha256']), (len(map_text.encode()), sha(map_text)))
        self.assertEqual(base64.b64decode(snapshot['files'][TOPOLOGY_FILE]).decode(), topology_text)
        self.assertEqual(base64.b64decode(snapshot['files'][MAP_FILE]).decode(), map_text)
        self.assertEqual(manifest['topology_provenance'], 'embedded')
        self.assertEqual(manifest['topology_digest'], sha(topology_text), 'the topology file\'s own digest')
        self.assertEqual((topology['source'], annotations['source']), (source, source))
        self.assertTrue(all('node' not in e for e in kinds['topology'] + kinds['annotations']), 'files of a kind, never devices')
        self.assertEqual(manifest['node_names'], sorted(self.names), 'the device scope is unchanged')
        self.assertEqual(len(snapshot['files']), len(self.names) + 2)

    def assert_in_repository(self, folder, topology_text, map_text):
        self.assertEqual(self.raw('show', f'HEAD:{folder}/{TOPOLOGY_FILE}'), topology_text.strip())
        self.assertEqual(self.raw('show', f'HEAD:{folder}/{MAP_FILE}'), map_text.strip())

    def test_a_save_to_latest_from_a_fresh_capture_carries_the_topology_and_the_map(self):
        lab = self.lab_state(); map_text = map_document(lab)
        self.assertTrue(map_text and lab['definition_yaml'], 'the fixture lab has both')
        outcome, submit = self.fresh_save(target='latest')
        submit.assert_called_once()   # a real capture was made
        self.assertEqual(outcome['status'], 'committed', outcome)
        self.assert_whole(self.published(), lab['definition_yaml'], map_text)
        self.assert_in_repository('latest', lab['definition_yaml'], map_text)

    def test_a_checkpoint_from_a_fresh_capture_carries_the_topology_and_the_map(self):
        lab = self.lab_state(); map_text = map_document(lab)
        outcome, _ = self.fresh_save(target='checkpoint', checkpoint='day-1')
        self.assertEqual(outcome['status'], 'committed', outcome)
        self.assertEqual(outcome['snapshot_path'], 'checkpoints/day-1')
        self.assert_whole(self.published(), lab['definition_yaml'], map_text)
        self.assert_in_repository('checkpoints/day-1', lab['definition_yaml'], map_text)

    def test_a_checkpoint_from_an_existing_capture_carries_them_without_reading_a_device(self):
        lab = self.lab_state(); map_text = map_document(lab)
        capture = self.fresh_capture()
        outcome, submit = self.saved(capture, target='checkpoint', checkpoint='from-capture')
        submit.assert_not_called()   # no device was read
        self.assertEqual(outcome['status'], 'committed', outcome)
        self.assert_whole(self.published(), lab['definition_yaml'], map_text)
        self.assert_in_repository('checkpoints/from-capture', lab['definition_yaml'], map_text)

    def test_a_baseline_from_an_existing_capture_carries_the_topology_and_the_map(self):
        lab = self.lab_state(); map_text = map_document(lab)
        capture = self.fresh_capture()
        outcome, submit = self.saved(capture, target='baseline')
        submit.assert_not_called()
        self.assertEqual(outcome['status'], 'committed', outcome)
        self.assertEqual(outcome['snapshot_path'], 'baseline')
        self.assert_whole(self.published(), lab['definition_yaml'], map_text)
        self.assert_in_repository('baseline', lab['definition_yaml'], map_text)

    def test_a_lab_without_a_map_saves_without_one_and_without_a_complaint(self):
        # Claim 3: no drawing, so no map document; the topology still travels and nothing is called a problem.
        lab = self.lab_state(); lab.pop('drawing'); self.store.save()
        self.assertEqual(map_document(lab), '')
        for fields in (dict(target='latest'), dict(target='checkpoint', checkpoint='no-map')):
            outcome, _ = self.fresh_save(**fields)
            self.assertEqual(outcome['status'], 'committed', outcome)
            snapshot = self.published(); kinds = self.by_kind(snapshot['manifest'])
            self.assertEqual(sorted(kinds), ['topology'], 'no annotations entry')
            self.assertNotIn(MAP_FILE, snapshot['files'])
            self.assertEqual(kinds['topology'][0]['sha256'], sha(lab['definition_yaml']))
            self.assertEqual((snapshot['manifest']['topology_provenance'], snapshot['manifest']['topology_digest']), ('embedded', sha(lab['definition_yaml'])))
            for word in ('map', 'annotation', 'missing', 'warning', 'problem', 'error'):
                self.assertNotIn(word, outcome['message'].lower())
        logged = self.client.get('/api/logs', headers=self.auth).json()['events']
        self.assertEqual([e for e in logged if e['action'] == 'topology.skip' or e['level'] in ('warning', 'error')], [])
        self.assertNotIn(MAP_FILE, self.names_in(outcome['commit'], 'checkpoints/no-map'))

    def test_an_existing_capture_keeps_the_map_it_was_taken_with(self):
        # A checkpoint made later from an old capture is the lab as it was at capture time, configurations and map alike.
        capture = self.fresh_capture(); taken = map_document(self.lab_state())
        self.move_node(777)
        self.assertNotEqual(map_document(self.lab_state()), taken)
        self.saved(capture, target='checkpoint', checkpoint='as-captured')
        self.assert_whole(self.published(), self.lab_state()['definition_yaml'], taken)


class ChangesAreRealChangesTests(WholeLabCase):
    """Claim 4: a change of only the map, or only the topology file, is a real change with its own review entry."""

    def two_saves(self, change):
        first, _ = self.fresh_save(target='latest'); self.assertEqual(first['status'], 'committed', first)
        change()
        second, _ = self.fresh_save(target='latest')
        return first, second

    def review_entries(self, job):
        response = self.client.post(self.url + '/compare', json={'job_id': job['id']})
        self.assertEqual(response.status_code, 200, response.text)
        return {f['name']: f for f in response.json()['files']}

    def compare_with_latest(self, commit):
        response = self.client.post(self.url + '/compare', json=dict(commit=commit, path='latest'))
        self.assertEqual(response.status_code, 200, response.text)
        return {f['name']: f for f in response.json()['files']}

    def test_an_unchanged_lab_saves_as_unchanged(self):
        # The control for the two tests below: the same files are the helper's `unchanged`.
        first, again = self.two_saves(lambda: None)
        self.assertEqual(again['message'], 'No configuration changes.')   # push is off, so the job reads `committed`, with nothing new in it
        self.assertEqual((again['commit'], again['changed_files']), (first['commit'], []))
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD'), '2', 'the README commit and the first save only')

    def test_a_change_of_only_the_map_is_a_real_change_and_the_review_lists_the_map(self):
        first, second = self.two_saves(lambda: self.move_node(321))
        self.assertEqual(second['status'], 'committed', second)
        self.assertNotEqual(second['commit'], first['commit'])
        self.assertEqual(second['changed_files'], [f'latest/{MAP_FILE}', 'latest/manifest.json'], 'the map and the manifest that lists it')
        entries = self.review_entries(second)
        self.assertEqual(set(entries), {MAP_FILE})
        self.assertEqual(entries[MAP_FILE]['status'], 'changed')
        self.assertIn('"x": 321', entries[MAP_FILE]['after']); self.assertNotIn('"x": 321', entries[MAP_FILE]['before'])
        self.assertFalse(entries[MAP_FILE]['diff']['identical'])
        # The same change seen from the saved version against the newest save (snapshot_diff).
        self.assertEqual(set(self.compare_with_latest(first['commit'])), {MAP_FILE})

    def test_a_change_of_only_the_topology_file_is_a_real_change_and_the_review_lists_it(self):
        edited = LAB_YAML + '# one more comment\n'
        first, second = self.two_saves(lambda: self.change_topology(edited))
        self.assertEqual(second['status'], 'committed', second)
        self.assertNotEqual(second['commit'], first['commit'])
        self.assertIn(f'latest/{TOPOLOGY_FILE}', second['changed_files']); self.assertNotIn(f'latest/{MAP_FILE}', second['changed_files'])
        entries = self.review_entries(second)
        self.assertEqual(set(entries), {TOPOLOGY_FILE})
        self.assertEqual((entries[TOPOLOGY_FILE]['status'], entries[TOPOLOGY_FILE]['after']), ('changed', edited))
        self.assertEqual(set(self.compare_with_latest(first['commit'])), {TOPOLOGY_FILE})

    def test_snapshot_diff_pairs_the_topology_and_the_map_by_kind_not_by_name(self):
        before = captured_snapshot(self.store, self.fresh_capture())
        self.move_node(55)
        after = captured_snapshot(self.store, self.fresh_capture())
        decode = lambda snap: {k: base64.b64decode(v) for k, v in snap['files'].items()}
        changes = snapshot_diff(before['manifest'], decode(before), after['manifest'], decode(after))
        self.assertEqual([(c['name'], c['status']) for c in changes], [(MAP_FILE, 'changed')])
        shown = annotated_compare(changes)
        self.assertFalse(shown[0]['diff']['identical'])


class TheSavedVersionShowsAndDownloadsBothTests(WholeLabCase):
    """Claim 5: the saved-version view and the ZIP of a saved state include both files."""

    def test_the_version_view_and_the_zip_include_the_topology_and_the_map(self):
        lab = self.lab_state(); map_text = map_document(lab)
        outcome, _ = self.fresh_save(target='latest'); commit = outcome['commit']
        version = self.version(commit)
        shown = {f['name']: f['text'] for f in version['files']}
        self.assertEqual(shown[TOPOLOGY_FILE], lab['definition_yaml']); self.assertEqual(shown[MAP_FILE], map_text)
        self.assertEqual(sorted(self.by_kind(version['manifest'])), ['annotations', 'topology'])
        self.assertEqual(version['manifest']['topology_provenance'], 'embedded')
        self.assertEqual(version['restore_nodes'], [], 'neither file is offered for a restore')
        response = self.client.post(self.url + '/version/download', json=dict(commit=commit, path='latest'))
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['content-type'], 'application/zip')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = set(archive.namelist())
            self.assertTrue({TOPOLOGY_FILE, MAP_FILE, 'manifest.json'} <= names, names)
            self.assertEqual(archive.read(TOPOLOGY_FILE).decode(), lab['definition_yaml'])
            self.assertEqual(archive.read(MAP_FILE).decode(), map_text)
            self.assertEqual(len(names), len(self.names) + 3)
            manifest = json.loads(archive.read('manifest.json'))
        self.assertEqual(sorted(e['path'] for e in manifest['files'] if e.get('kind')), [TOPOLOGY_FILE, MAP_FILE])

    def test_the_checkpoint_and_the_baseline_are_viewable_with_both_files_too(self):
        capture = self.fresh_capture()
        checkpoint, _ = self.saved(capture, target='checkpoint', checkpoint='c1')
        baseline, _ = self.saved(capture, target='baseline')
        for outcome, path in ((checkpoint, 'checkpoints/c1'), (baseline, 'baseline')):
            names = self.names_in(outcome['commit'], path)
            self.assertTrue({TOPOLOGY_FILE, MAP_FILE} <= set(names), (path, names))


class WhichCopyIsCapturedTests(WholeLabCase):
    """Claim 6: where the decision is made, `Runner.topology_capture`, and what a save then carries.

    The VM's files beside the deployed topology win whenever discovery holds them (they are the lab as deployed,
    read within the discovery interval, never compared by age against the manager's copy); the manager's own copy
    is used when discovery holds none, because the poll failed or the host changed (`Discovery.sources` is emptied
    by every pass and refilled only by a successful one)."""

    def hold_vm_files(self, definition=VM_YAML, annotations=VM_MAP):
        self.service.sources[self.lab_state()['deployment_name']] = vm_bundle(definition, annotations)
        self.store.state['discovery']['last_success'] = '2026-10-04T10:00:00+00:00'

    def capture_decision(self):
        return self.app.state.runner.topology_capture(copy.deepcopy(self.lab_state()))

    def test_the_vm_files_are_used_when_discovery_holds_them(self):
        self.hold_vm_files()
        chosen = self.capture_decision()
        self.assertEqual(chosen['source'], 'vm')
        self.assertEqual((chosen['definition'], chosen['annotations'], chosen['annotations_source']), (VM_YAML.encode(), VM_MAP.encode(), 'vm'))
        self.assertEqual((chosen['path'], chosen['read_at']), ('/srv/labs/training/training.clab.yml', '2026-10-04T10:00:00+00:00'))
        self.assertNotEqual(chosen['definition'].decode(), self.lab_state()['definition_yaml'])
        # ... and that is what the save carries and the repository holds.
        outcome, _ = self.fresh_save(target='latest')
        self.assertEqual(outcome['status'], 'committed', outcome)
        snapshot = self.published(); kinds = self.by_kind(snapshot['manifest'])
        self.assertEqual(base64.b64decode(snapshot['files'][TOPOLOGY_FILE]).decode(), VM_YAML)
        self.assertEqual(base64.b64decode(snapshot['files'][MAP_FILE]).decode(), VM_MAP)
        self.assertEqual((kinds['topology'][0]['source'], kinds['topology'][0]['vm_path']), ('vm', '/srv/labs/training/training.clab.yml'))
        self.assertEqual(snapshot['manifest']['topology_digest'], sha(VM_YAML))
        self.assertEqual(self.raw('show', f'HEAD:latest/{TOPOLOGY_FILE}'), VM_YAML.strip())

    def test_a_vm_topology_without_a_map_file_travels_with_the_managers_map(self):
        self.hold_vm_files(annotations=None)
        chosen = self.capture_decision()
        self.assertEqual((chosen['source'], chosen['annotations_source']), ('vm', 'manager'))
        self.assertEqual(chosen['annotations'].decode(), map_document(self.lab_state()))
        self.fresh_save(target='latest')
        kinds = self.by_kind(self.published()['manifest'])
        self.assertEqual((kinds['topology'][0]['source'], kinds['annotations'][0]['source']), ('vm', 'manager'))

    def test_without_the_vm_files_the_managers_copy_is_used(self):
        chosen = self.capture_decision()
        self.assertEqual((chosen['source'], chosen['annotations_source']), ('manager', 'manager'))
        self.assertEqual((chosen['definition'].decode(), chosen['annotations'].decode()),
                         (self.lab_state()['definition_yaml'], map_document(self.lab_state())))

    def test_a_failed_poll_drops_the_vm_files_and_the_managers_copy_is_used_again(self):
        self.hold_vm_files(); self.assertEqual(self.capture_decision()['source'], 'vm')
        self.poll(error=OSError('the VM did not answer'))
        self.assertEqual(self.service.sources, {})
        self.assertEqual(self.capture_decision()['source'], 'manager')

    def test_a_vm_bundle_without_a_topology_file_is_not_used(self):
        self.service.sources[self.lab_state()['deployment_name']] = decode_bundle(dict(files={}))
        self.assertEqual(self.capture_decision()['source'], 'manager')


class GapTests(WholeLabCase):
    """Claim 7: every way found by which a save reaches the repository without the lab's topology or map, or with
    a different one. Today's behaviour is asserted; the comment on each says what G1 would require instead."""

    def assert_carries_neither(self, snapshot):
        self.assertEqual(self.by_kind(snapshot['manifest']), {})
        self.assertFalse({TOPOLOGY_FILE, MAP_FILE} & set(snapshot['files']))

    def test_gap_a_backup_without_an_embedded_record_saves_without_the_topology_to_latest(self):
        # G1 would require: refuse the save, or take the lab's current files, when the lab has a topology the capture lacks.
        # Reached by: Save progress -> POST /api/labs/{id}/git/save with a backup_job_id, or a manual / scheduled /
        # restore-pre backup taken before embedding existed.
        self.assertTrue(self.lab_state()['definition_yaml'])
        outcome, _ = self.saved(self.old_capture(), target='latest')
        self.assertEqual(outcome['status'], 'committed', outcome)
        self.assert_carries_neither(self.published())
        self.assertEqual((self.published()['manifest']['topology_provenance'], self.published()['manifest']['topology_digest']), ('unknown', None),
                         'a save from an existing capture even loses the manager copy\'s digest: only a fresh capture has the save context')
        self.assertNotIn('topology', outcome['message'].lower())

    def test_gap_a_checkpoint_and_a_baseline_from_an_older_capture_carry_no_topology(self):
        # G1 would require: the same refusal or fallback for checkpoint and baseline (the route builds the snapshot from the capture only).
        capture = self.old_capture()
        for fields in (dict(target='checkpoint', checkpoint='old-1'), dict(target='baseline')):
            outcome, submit = self.saved(capture, **fields)
            submit.assert_not_called()
            self.assertEqual(outcome['status'], 'committed', outcome)
            self.assert_carries_neither(self.published())
            self.assertEqual(sorted(self.names_in(outcome['commit'], outcome['snapshot_path'])), sorted(self.published()['files']))
            self.assertNotIn(TOPOLOGY_FILE, self.names_in(outcome['commit'], outcome['snapshot_path']))

    def test_gap_a_later_save_without_the_topology_removes_the_one_the_repository_held(self):
        # G1 would require: a save without the lab's files never deletes the ones latest/ already holds.
        first, _ = self.fresh_save(target='latest')
        self.assertTrue({TOPOLOGY_FILE, MAP_FILE} <= set(self.names_in(first['commit'])))
        second, _ = self.saved(self.old_capture(), target='latest')
        self.assertEqual(second['status'], 'committed', second)
        self.assertNotIn(TOPOLOGY_FILE, self.names_in(second['commit'])); self.assertNotIn(MAP_FILE, self.names_in(second['commit']))
        self.assertIn(f'latest/{TOPOLOGY_FILE}', second['changed_files'], 'the helper deletes the files the new manifest no longer owns')
        self.assertEqual(self.raw('rev-list', '--count', 'HEAD'), '3')
        removed = self.client.post(self.url + '/compare', json={'job_id': second['id']}).json()['files']
        self.assertEqual({f['name']: f['status'] for f in removed if f['name'] in (TOPOLOGY_FILE, MAP_FILE)},
                         {TOPOLOGY_FILE: 'removed', MAP_FILE: 'removed'}, 'visible in the review, but a plain removed file, not a warning')

    def test_gap_a_capture_whose_embedding_failed_is_saved_without_a_word_to_the_student(self):
        # G1 would require: the save says the capture carries no topology (or retries the embedding) instead of committing silently.
        # Reached by: any backup where Runner.embed_topology swallowed an error (runner.py: log 'topology.skip', returns None).
        with patch.object(self.app.state.runner, 'topology_capture', side_effect=OSError('disk')):
            capture = self.fresh_capture()
        self.assertNotIn('topology', capture)
        outcome, _ = self.saved(capture, target='latest')
        self.assertEqual(outcome['status'], 'committed', outcome)
        self.assert_carries_neither(self.published())
        self.assertNotIn('topology', outcome['message'].lower()); self.assertNotIn('map', outcome['message'].lower())
        events = self.client.get('/api/logs?job_id=' + capture['id'], headers=self.auth).json()['events']
        self.assertEqual([e['level'] for e in events if e['action'] == 'topology.skip'], ['warning'], 'only the event log of the backup knows')

    def test_gap_an_unwritable_drawing_saves_the_topology_without_the_map(self):
        # G1 would require: fail or warn when the lab has a map the capture could not write, rather than saving the topology alone.
        self.lab_state()['drawing'] = {'broken': True}; self.store.save()
        capture = self.fresh_capture()
        self.assertEqual(capture['topology']['file'], 'topology.clab.yml'); self.assertNotIn('annotations_file', capture['topology'])
        outcome, _ = self.saved(capture, target='latest')
        self.assertEqual(outcome['status'], 'committed', outcome)
        kinds = self.by_kind(self.published()['manifest'])
        self.assertEqual(sorted(kinds), ['topology']); self.assertNotIn(MAP_FILE, self.published()['files'])
        self.assertNotIn('map', outcome['message'].lower())

    def test_gap_a_lab_known_only_from_an_inventory_has_no_topology_to_save(self):
        # G1 would require: say so when a save cannot carry the lab's topology (an inventory import has none; it
        # arrives only through Update topology file… or a VM import).
        created = self.client.post('/api/inventory', headers=self.auth, data={'name': 'Example lab'},
                                   files={'inventory': ('ansible-inventory.yml', INVENTORY)})
        self.assertEqual(created.status_code, 200, created.text)
        lab = created.json(); url = '/api/labs/' + lab['id'] + '/git'
        self.assertEqual(self.client.post(self.url + '/unlink', json={}).status_code, 200)   # one registration per lab
        self.assertFalse(self.store.lab(lab['id']).get('definition_yaml'))
        names = [n['name'] for n in self.store.lab(lab['id'])['nodes'] if n.get('platform') in ('cisco_xrv9k', 'juniper_cjunosevolved')]
        self.assertEqual(self.client.put(url, json=dict(binding_id='bens-lab', node_names=names)).status_code, 200)
        capture = self.fresh_capture(lab['id'], node_names=names)
        self.assertNotIn('topology', capture)
        sent = self.client.post(url + '/save', json=dict(request_id=uuid.uuid4().hex, target='latest', push=False,
                                                       note='Inventory lab', backup_job_id=capture['id']))
        self.assertEqual(sent.status_code, 200, sent.text)
        self.run_save(sent.json())
        snapshot = self.published()
        self.assertEqual(snapshot['manifest']['lab_id'], lab['id'])
        self.assert_carries_neither(snapshot)
        self.assertEqual((snapshot['manifest']['topology_provenance'], snapshot['manifest']['topology_digest']), ('unknown', None))

    def sync_from_vm(self, annotations):
        """What POST /api/labs/{id}/sync applies (vm_files.prepare_lab, then replace the lab), from a held VM bundle."""
        from app.vm_files import prepare_lab
        bundle = vm_bundle(LAB_YAML, annotations); self.service.sources[self.lab_state()['deployment_name']] = bundle
        lab = self.lab_state(); candidate = prepare_lab(bundle, lab['deployment_name'], lab)
        lab.clear(); lab.update(candidate); self.store.save()

    def saved_map(self):
        outcome, _ = self.fresh_save(target='latest')
        self.assertEqual(outcome['status'], 'committed', outcome)
        return (base64.b64decode(self.published()['files'][MAP_FILE]).decode(),
                self.by_kind(self.published()['manifest'])['annotations'][0]['source'])

    def test_a_map_edited_in_the_manager_after_a_sync_is_the_saved_map(self):
        self.sync_from_vm(VM_MAP)
        self.assertEqual(self.saved_map(), (VM_MAP, 'vm'), 'nothing was edited: the VM file, as before')
        self.move_node(999)
        students_map = map_document(self.lab_state())
        self.assertIn('"x": 999', students_map); self.assertNotEqual(students_map, VM_MAP)
        saved, source = self.saved_map()
        self.assertEqual((saved, source), (students_map, 'manager'))

    def test_a_vm_map_changed_since_the_last_sync_is_the_saved_map_when_nobody_edited_here(self):
        self.sync_from_vm(VM_MAP)
        newer = VM_MAP.replace('"x": 500', '"x": 777')
        self.service.sources[self.lab_state()['deployment_name']] = vm_bundle(LAB_YAML, newer)
        self.assertEqual(self.saved_map(), (newer, 'vm'))

    def test_when_both_the_vm_map_and_the_managers_map_changed_the_managers_wins(self):
        self.sync_from_vm(VM_MAP); self.move_node(999)
        newer = VM_MAP.replace('"x": 500', '"x": 777')
        self.service.sources[self.lab_state()['deployment_name']] = vm_bundle(LAB_YAML, newer)
        saved, source = self.saved_map()
        self.assertEqual((saved, source), (map_document(self.lab_state()), 'manager')); self.assertIn('"x": 999', saved)

    def test_two_syncs_within_one_clock_tick_are_still_syncs(self):
        # The mark a sync leaves must not depend on the clock: with the same stamp twice, the VM's map stays the saved one.
        with patch('app.discovery.stamp', return_value='2026-10-04T12:00:00+00:00'):   # vm_files imports it at call time
            self.sync_from_vm(VM_MAP); self.sync_from_vm(VM_MAP)
        self.assertNotIn('map_written_at', self.lab_state())
        self.assertEqual(self.saved_map(), (VM_MAP, 'vm'))

    def test_a_map_that_discovery_placed_from_the_vm_is_not_taken_for_an_edit(self):
        from app.layout import keep_document
        from app.runner import Runner
        from app.topology import unplaced
        lab = self.lab_state(); name = lab['deployment_name']
        lab['drawing']['placed'] = False; keep_document(lab, b''); self.store.save()   # as if known from the topology alone: nobody placed a node
        self.assertIn('map_written_at', self.lab_state())
        self.assertTrue(unplaced(self.lab_state()['drawing']))
        def raw(text, where): return dict(content=base64.b64encode(text.encode()).decode(), sha256=sha(text.encode()), path=where)
        where = '/srv/labs/training/training.clab.yml'
        with self.store.lock:
            self.service.update_sources({name: dict(files={'definition': raw(LAB_YAML, where), 'annotations': raw(VM_MAP, where + '.annotations.json')})})
        self.assertFalse(unplaced(self.lab_state()['drawing']), 'discovery placed the nodes from the VM file')
        self.assertFalse(Runner.map_changed_in_manager(self.lab_state()))

    def test_a_drag_in_the_topology_tab_after_a_sync_is_the_saved_map_too(self):
        self.sync_from_vm(VM_MAP)
        alias = self.lab_state()['drawing']['nodes'][0]['id']
        sent = self.client.put('/api/labs/' + self.lab['id'] + '/layout', json=dict(positions={alias: [321, 123]}))
        self.assertEqual(sent.status_code, 200, sent.text)
        saved, source = self.saved_map()
        self.assertEqual((saved, source), (map_document(self.lab_state()), 'manager')); self.assertNotEqual(saved, VM_MAP)

    def test_without_a_map_file_on_the_vm_the_managers_map_is_saved(self):
        self.sync_from_vm(None); self.move_node(999)
        self.service.sources[self.lab_state()['deployment_name']] = vm_bundle(LAB_YAML)
        saved, source = self.saved_map()
        self.assertEqual((saved, source), (map_document(self.lab_state()), 'manager'))

    def test_gap_a_topology_updated_in_the_manager_after_deployment_loses_to_the_deployed_file(self):
        # G1 would require: a decision between the deployed file and the manager's newer copy that the student can see
        # (today the manager's text is saved only while discovery holds no VM file).
        self.service.sources[self.lab_state()['deployment_name']] = vm_bundle(LAB_YAML, VM_MAP)
        edited = LAB_YAML + '# edited in the manager after deployment\n'
        self.change_topology(edited)
        outcome, _ = self.fresh_save(target='latest')
        self.assertEqual(outcome['status'], 'committed', outcome)
        saved = base64.b64decode(self.published()['files'][TOPOLOGY_FILE]).decode()
        self.assertEqual(saved, LAB_YAML); self.assertNotEqual(saved, self.lab_state()['definition_yaml'])

    def test_gap_a_design_export_carries_the_plans_netlab_topology_and_not_the_labs_files(self):
        # G1 would require: decide whether a design export is a save of the lab; if so it needs the lab's topology and
        # map. Note the clash: its manifest entry `kind: topology` is the generated netlab file (topology.yml).
        generation_id = uuid.uuid4().hex
        folder = self.app.state.network_design.folder(self.lab['id'], generation_id); (folder / 'nodes').mkdir(parents=True)
        (folder / 'intent.json').write_text(json.dumps({'revision': 'r1', 'roles': {}}))
        for name, text in (('plan.json', '{"plan": true}'), ('topology.yml', 'name: generated\n'), ('mapping.json', '{}')):
            (folder / name).write_text(text)
        self.lab_state().setdefault('network_generations', []).append(
            dict(id=generation_id, lab_id=self.lab['id'], status='succeeded', created='2026-10-04T10:00:00+00:00', finished='2026-10-04T10:00:05+00:00', artifacts={}))
        self.store.save()
        response = self.client.post(f'/api/labs/{self.lab["id"]}/design/generations/{generation_id}/git',
                                    json=dict(request_id=uuid.uuid4().hex, checkpoint='plan-1', note='Plan one'))
        self.assertEqual(response.status_code, 200, response.text)
        job = response.json()
        self.progress.execute(job['id'])
        outcome = self.client.get('/api/git/jobs/' + job['id']).json()
        self.assertEqual(outcome['status'], 'committed', outcome)
        snapshot = self.published()
        self.assertEqual(snapshot['manifest'].get('kind'), 'network-design')
        self.assertFalse({TOPOLOGY_FILE, MAP_FILE} & set(snapshot['files']))
        topology = [e for e in snapshot['manifest']['files'] if e.get('kind') == 'topology']
        self.assertEqual([(e['path'], e['artifact']) for e in topology], [('topology.yml', 'network-design')])
        self.assertEqual(sorted(self.by_kind(snapshot['manifest'])), ['intent', 'mapping', 'plan', 'topology'])


class TopologyNamesAndDigestsTests(WholeLabCase):
    """The names a save uses come from `topology_names` and the lab's name, and the same capture is always the same snapshot."""

    def test_the_saved_names_are_the_labs_own_download_names(self):
        capture = self.fresh_capture()
        self.assertEqual(topology_names(capture), {'topology': TOPOLOGY_FILE, 'annotations': MAP_FILE})
        snapshot = captured_snapshot(self.store, capture)
        _, files = decoded_snapshot({'snapshot': snapshot})
        self.assertTrue({TOPOLOGY_FILE, MAP_FILE} <= set(files))
        self.assertEqual(content_digest(snapshot['manifest']), content_digest(captured_snapshot(self.store, capture)['manifest']))


if __name__ == '__main__':
    unittest.main()
