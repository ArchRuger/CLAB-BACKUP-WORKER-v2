"""Tests for the design export through the student's Git save (kind `design`):

- `app/network_design.py: NetworkDesign.design_snapshot(lab, generation)` -- the reviewed export set of
  one generated plan (the intent, plan, topology, mapping and every generated fragment), base64-encoded
  like a capture, with a manifest that names every row a generated artifact rather than a device backup.
- `app/git_progress.py`: `POST /api/labs/{lab_id}/design/generations/{generation_id}/git` (a design export
  is a Git job of kind `design`), `GitProgress.execute`'s design branch, and `public_job` exposing `kind`
  and `generation_id`.
- `app/restore.py`: a design export's manifest rows carry no `restore_artifact` and no `node`, so
  `RestoreService.resolve_source` never lists such a version as a restore candidate.

Everything here drives `create_app(tempfile.mkdtemp())` through `TestClient`; no Store ever points at
live data. The VM Git helper is replaced with a small fake (`app.git_progress.remote_git` patched), the
same pattern `tests/test_git_progress.py` uses. Generation folders and records are written by hand,
mirroring `tests/test_design_apply.py`'s `add_generation`, extended with the plan/topology/mapping files
`design_snapshot` itself reads from disk.
"""
import base64
import copy
import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
from unittest.mock import patch

import yaml
from fastapi.testclient import TestClient

from app.main import create_app
from app.git_progress import job_destination, host_identity, digest as gp_digest
from app.network_design import NetworkDesign, digest as nd_digest

INTENT = {'schema': 1, 'revision': 'rev1', 'modules': ['ospf', 'bgp'], 'nodes': {}}

DEFAULT_PLAN = b'{"plan": true, "links": []}'
DEFAULT_TOPOLOGY = b'name: design-export-test\n'
DEFAULT_MAPPING = b'{"mapping": {}, "link_keys": {}}'


# --- fixtures ------------------------------------------------------------------------------------------

def add_lab(app, name='design-export-lab'):
    lab_id = uuid.uuid4().hex
    store = app.state.store
    with store.lock:
        lab = dict(id=lab_id, name=name, nodes=[], profiles=[], defaults={}, interval=0, next_run=None,
                   created='2026-09-27T00:00:00+00:00', updated='2026-09-27T00:00:00+00:00', definition_yaml='')
        store.state['labs'].append(lab)
        store.save()
    return lab_id


def set_host(app, **fields):
    store = app.state.store
    payload = dict(address='127.0.0.1', port=22, username='fixture', fingerprint='SHA256:fixture')
    payload.update(fields)
    with store.lock:
        store.state['host'] = payload
        store.save()
    return payload


def bind_git(app, lab_id, node_names=(), path='/home/ben/labs/net-design', prefix=''):
    store = app.state.store
    with store.lock:
        host = store.state.get('host') or {}
        repo = dict(id='bens-lab', label='Bens lab', owner='ben', path=path, prefix=prefix, branch='main',
                    push_url='https://github.com/ben/net-design.git', revision='binding-1')
        binding = dict(binding_id=repo['id'], revision=repo['revision'], repository=repo,
                       host_identity=host_identity(host), node_names=list(node_names), review_before_push=True)
        lab = store.lab(lab_id)
        lab['git_binding'] = binding
        store.save()
    return binding


def write_generation(app, lab_id, fragments, status='succeeded', revision='rev1', intent=None, extra=None, omit=()):
    """`fragments`: {node: [(module, text)]}. Writes intent.json/plan.json/topology.yml/mapping.json
    (unless named in `omit`) and every fragment under the generation's folder, and appends a generation
    record whose `artifacts` entries' recorded size/sha256 match what was written -- exactly what
    `design_snapshot` checks (it reads the intent this plan was built from back from `intent.json` on
    disk, not the lab's current, possibly since-edited, design). Mirrors
    `tests/test_design_apply.py`'s `add_generation`, extended with the top-level files `design_snapshot`
    reads from disk (which that helper never needed to write)."""
    intent = INTENT if intent is None else intent
    store = app.state.store
    with store.lock:
        lab = store.lab(lab_id)
        gen_id = uuid.uuid4().hex
        folder = app.state.network_design.root / lab_id / gen_id
        folder.mkdir(parents=True, exist_ok=True)
        top_files = {'intent.json': json.dumps(intent, sort_keys=True).encode(), 'plan.json': DEFAULT_PLAN,
                    'topology.yml': DEFAULT_TOPOLOGY, 'mapping.json': DEFAULT_MAPPING}
        for name, raw in top_files.items():
            if name not in omit: (folder / name).write_bytes(raw)
        artifacts = {}
        for node, items in fragments.items():
            node_dir = folder / 'nodes' / node
            node_dir.mkdir(parents=True, exist_ok=True)
            entries = []
            for index, (module, text) in enumerate(items):
                raw = text.encode('utf-8')
                (node_dir / ('%02d-%s' % (index, module))).write_bytes(raw)
                entries.append({'module': module, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
            artifacts[node] = entries
        generation = {'id': gen_id, 'lab_id': lab_id, 'created': '2026-09-27T00:00:00+00:00', 'status': status,
                      'message': 'Plan generated', 'intent_revision': revision,
                      'topology_digest': hashlib.sha256((lab.get('definition_yaml') or '').encode()).hexdigest(),
                      'engine_version': 'netlab-26.09', 'modules': list((intent or {}).get('modules') or []),
                      'artifacts': artifacts}
        if extra: generation.update(extra)
        lab.setdefault('network_generations', []).append(generation)
        store.save()
    return gen_id


def rewrite_fragment(app, lab_id, generation_id, node, index, module, text):
    """Change a fragment's bytes on disk without updating the generation's recorded sha256 (a stale
    digest) -- used to prove `design_snapshot`'s own integrity check."""
    folder = app.state.network_design.root / lab_id / generation_id
    (folder / 'nodes' / node / ('%02d-%s' % (index, module))).write_text(text, encoding='utf-8')


class DesignExportGitTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = create_app(self.tmp)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.git_progress.close)
        self.addCleanup(self.app.state.restore.close)
        self.addCleanup(self.app.state.network_design.close)
        self.addCleanup(self.app.state.design_apply.close)
        self.store = self.app.state.store
        self.progress = self.app.state.git_progress
        self.progress.connection_wait = 0   # a busy connection answers at once in these tests
        self.designs = self.app.state.network_design
        set_host(self.app)
        self.lab_id = add_lab(self.app)
        self.binding = bind_git(self.app, self.lab_id)
        self.sent = []
        self.snapshots = {}
        self.helper = patch('app.git_progress.remote_git', side_effect=self.remote).start()
        self.addCleanup(patch.stopall)
        self.dispatch = patch.object(self.progress.pool, 'submit').start()

    def remote(self, host, request, stopping=None):
        self.sent.append(copy.deepcopy(request))
        mode = request['mode']
        if mode == 'status': return dict(ready=True, head=getattr(self, 'vm_head', 'a' * 40))   # the checkout's HEAD moves with a save
        if mode == 'publish':
            self.snapshots[request['operation_id']] = copy.deepcopy(request['snapshot']); self.vm_head = 'b' * 40
            return dict(status='synced' if request['push'] else 'committed', commit='b' * 40,
                       pushed=request['push'], changed_files=list(request['snapshot']['files']),
                       snapshot_path=request['target'])
        if mode == 'push':
            return dict(status='synced', commit='b' * 40, pushed=True, changed_files=[], snapshot_path='checkpoints/day-1')
        if mode == 'update': return dict(status='updated', head=request['expected_head'])   # nothing new online
        raise AssertionError(mode)

    def export_url(self, generation_id):
        return f'/api/labs/{self.lab_id}/design/generations/{generation_id}/git'

    def export(self, generation_id, **fields):
        data = dict(request_id=uuid.uuid4().hex, checkpoint='day-1', note='Checkpoint note', push=False)
        data.update(fields)
        return self.client.post(self.export_url(generation_id), json=data), data

    def generation(self, gen_id, lab_id=None):
        lab = self.store.lab(lab_id or self.lab_id)
        return next(g for g in lab['network_generations'] if g['id'] == gen_id)


# --- 1. design_snapshot ----------------------------------------------------------------------------

class DesignSnapshotTests(DesignExportGitTestCase):

    def test_an_empty_generated_file_is_left_out_of_the_export(self):
        # netlab writes an empty file for a module with nothing to say on a device (a `vlan` fragment on a router without
        # VLAN ports, seen live); the helper refuses empty files, so the export carries none and says nothing of it.
        gen_id = write_generation(self.app, self.lab_id,
                                  {'ceos': [('ospf', 'router ospf 1\n!\n'), ('vlan', '')], 'xrv9k': [('isis', 'router isis CORE\n!\n')]},
                                  intent=INTENT)
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        snapshot = self.designs.design_snapshot(lab, generation)
        self.assertNotIn('ceos--01-vlan.cfg', snapshot['files'])
        self.assertIn('ceos--00-ospf.cfg', snapshot['files'])
        self.assertEqual(sorted(r['device'] for r in snapshot['manifest']['files'] if r.get('device')), ['ceos', 'xrv9k'])
        self.assertEqual(snapshot['manifest']['devices'], ['ceos', 'xrv9k'])

    def test_snapshot_manifest_and_files(self):
        gen_id = write_generation(self.app, self.lab_id,
                                  {'ceos': [('ospf', 'router ospf 1\n!\n'), ('bgp', 'router bgp 65000\n!\n')],
                                   'xrv9k': [('isis', 'router isis CORE\n!\n')]},
                                  intent=INTENT, extra={'label': 'Day 1 plan'})
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        snapshot = self.designs.design_snapshot(lab, generation)
        manifest, files = snapshot['manifest'], snapshot['files']

        self.assertEqual(set(files), {'network-intent.yml', 'plan.json', 'topology.yml', 'mapping.json',
                                      'ceos--00-ospf.cfg', 'ceos--01-bgp.cfg', 'xrv9k--00-isis.cfg'})
        self.assertEqual(manifest['schema'], 2)
        self.assertEqual(manifest['kind'], 'network-design')
        self.assertEqual(manifest['lab_id'], self.lab_id)
        self.assertEqual(manifest['generation_id'], gen_id)
        self.assertEqual(manifest['intent_revision'], 'rev1')
        self.assertEqual(manifest['topology_digest'], generation['topology_digest'])
        self.assertEqual(manifest['engine_version'], 'netlab-26.09')
        self.assertEqual(manifest['devices'], ['ceos', 'xrv9k'])
        self.assertEqual(manifest['node_names'], [])
        self.assertEqual(manifest['restore_capable_nodes'], 0)

        rows = manifest['files']
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertEqual(row['artifact'], 'network-design')
            self.assertNotIn('node', row)
            self.assertNotIn('restore_artifact', row)
        fragments = [r for r in rows if r['kind'] == 'fragment']
        self.assertEqual(len(fragments), 3)
        for row in fragments:
            self.assertIn('device', row); self.assertIn('module', row)
        for row in rows:
            if row['kind'] != 'fragment':
                self.assertNotIn('device', row); self.assertNotIn('module', row)

        # base64 round trip: the plan file's decoded bytes match what was written, and the row's
        # size/sha256 describe exactly those bytes.
        raw_plan = base64.b64decode(files['plan.json'])
        self.assertEqual(raw_plan, DEFAULT_PLAN)
        plan_row = next(r for r in rows if r['path'] == 'plan.json')
        self.assertEqual(plan_row['size'], len(raw_plan))
        self.assertEqual(plan_row['sha256'], hashlib.sha256(raw_plan).hexdigest())

        # The intent file is the *frozen* intent this plan was generated from (read back from the
        # generation folder's own intent.json), wrapped with export provenance -- not the lab's
        # current design, which may have moved on since.
        document = yaml.safe_load(base64.b64decode(files['network-intent.yml']))
        self.assertEqual(document['containerlab_node_manager']['generation'], gen_id)
        self.assertEqual(document['containerlab_node_manager']['exported'], generation['created'])
        self.assertEqual(document['modules'], INTENT['modules'])

    def test_manifest_names_the_lab_or_the_jobs_frozen_name(self):
        # The manifest's lab_name labels the commit and names the version download; a loop over the plan's files once
        # overwrote it, so every export said 'mapping.json'.
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n!\n')]}, intent=INTENT)
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        self.assertEqual(self.designs.design_snapshot(lab, generation)['manifest']['lab_name'], 'design-export-lab')
        frozen = self.designs.design_snapshot(lab, generation, lab_name='renamed-since')
        self.assertEqual(frozen['manifest']['lab_name'], 'renamed-since')
        document = yaml.safe_load(base64.b64decode(frozen['files']['network-intent.yml']))
        self.assertEqual(document['containerlab_node_manager']['lab'], 'renamed-since')

    def test_a_save_bound_before_the_lab_name_fix_gets_its_bound_bytes_back(self):
        # A pending export whose digest was recorded by a manager before the fix (lab_name 'mapping.json') must publish
        # exactly what it was bound to, not fail as "changed": `bound` selects that form only when it is the bound one.
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n!\n')]}, intent=INTENT)
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        current = self.designs.design_snapshot(lab, generation, lab_name=lab['name'])
        before_fix = copy.deepcopy(current); before_fix['manifest']['lab_name'] = 'mapping.json'
        old_digest = nd_digest(before_fix)
        legacy = self.designs.design_snapshot(lab, generation, lab_name=lab['name'], bound=old_digest)
        self.assertEqual(legacy, before_fix)
        self.assertEqual(self.designs.design_snapshot(lab, generation, lab_name=lab['name'], bound=nd_digest(current)), current)
        self.assertEqual(self.designs.design_snapshot(lab, generation, lab_name=lab['name'], bound='0' * 64), current,
                         'any other digest gets the current form, so the changed-plan guard still refuses it')

    def test_execute_publishes_the_lab_name_in_the_manifest(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='day-1', push=False)
        job_id = response.json()['id']
        self.progress.execute(job_id)
        self.assertEqual(self.snapshots[job_id]['manifest']['lab_name'], 'design-export-lab')
        self.assertEqual(self.client.get('/api/git/jobs/' + job_id).json()['status'], 'committed')

    def test_snapshot_refuses_non_succeeded(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]},
                                  status='running', intent=INTENT)
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        with self.assertRaises(ValueError) as ctx:
            self.designs.design_snapshot(lab, generation)
        self.assertIn('Only a generated plan can be exported.', str(ctx.exception))

    def test_snapshot_refuses_missing_fragment(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        folder = self.designs.root / self.lab_id / gen_id
        (folder / 'nodes' / 'ceos' / '00-ospf').unlink()
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        with self.assertRaises(ValueError) as ctx:
            self.designs.design_snapshot(lab, generation)
        self.assertIn('A generated file of this plan is missing', str(ctx.exception))

    def test_snapshot_refuses_changed_fragment_digest(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        rewrite_fragment(self.app, self.lab_id, gen_id, 'ceos', 0, 'ospf', 'router ospf 2\n')
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        with self.assertRaises(ValueError) as ctx:
            self.designs.design_snapshot(lab, generation)
        self.assertIn('A generated file of this plan changed on disk', str(ctx.exception))

    def test_snapshot_refuses_missing_plan_file(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]},
                                  intent=INTENT, omit=('plan.json',))
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        with self.assertRaises(ValueError) as ctx:
            self.designs.design_snapshot(lab, generation)
        self.assertIn('A file of this plan is missing', str(ctx.exception))

    def test_snapshot_refuses_unusable_name(self):
        # A node name that passes the node-name filter (<=200 chars) but whose composed fragment
        # filename ('<node>--<nn>-<module>.cfg') exceeds the 181-character file-name limit.
        long_node = 'n' * 190
        gen_id = write_generation(self.app, self.lab_id, {long_node: [('x', 'conf\n')]}, intent=INTENT)
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        with self.assertRaises(ValueError) as ctx:
            self.designs.design_snapshot(lab, generation)
        self.assertIn('unusable file name', str(ctx.exception))

    def test_snapshot_refuses_invalid_device_name(self):
        gen_id = write_generation(self.app, self.lab_id, {'bad node': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        with self.assertRaises(ValueError) as ctx:
            self.designs.design_snapshot(lab, generation)
        self.assertIn('device name of this plan cannot be exported', str(ctx.exception))

    def test_snapshot_refuses_missing_intent(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]},
                                  intent=INTENT, omit=('intent.json',))
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        with self.assertRaises(ValueError) as ctx:
            self.designs.design_snapshot(lab, generation)
        self.assertIn('The intent of this plan is missing', str(ctx.exception))


# --- 2. the route ------------------------------------------------------------------------------------

class ExportRouteTests(DesignExportGitTestCase):

    def test_route_creates_job_with_expected_fields(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='day-1', note='Day 1', push=True)
        self.assertEqual(response.status_code, 200, response.text)
        job = self.store.state['git_jobs'][-1]
        self.assertEqual(job['kind'], 'design')
        self.assertEqual(job['generation_id'], gen_id)
        self.assertEqual(job['target'], 'checkpoint')
        self.assertEqual(job['checkpoint'], 'day-1')
        self.assertEqual(job['destination'], job_destination(self.binding, 'checkpoint', 'day-1'))
        self.assertTrue(job['review_before_push'])
        self.assertTrue(job.get('snapshot_digest'))
        self.assertEqual(job['request']['push'], False)
        self.assertEqual(job['request']['target'], 'checkpoint')
        self.assertEqual(job['request']['checkpoint'], 'day-1')
        self.assertEqual(job['node_names'], [])

    def test_route_idempotent_and_conflicting_request_id(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        body = dict(request_id=uuid.uuid4().hex, checkpoint='day-1', note='Day 1', push=False)
        first = self.client.post(self.export_url(gen_id), json=body)
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(self.export_url(gen_id), json=body)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()['id'], first.json()['id'])
        self.assertEqual(len([j for j in self.store.state['git_jobs'] if j['id'] == body['request_id']]), 1)
        different = dict(body, note='A different note')
        conflict = self.client.post(self.export_url(gen_id), json=different)
        self.assertEqual(conflict.status_code, 409, conflict.text)

    def test_route_404_unknown_generation(self):
        response, _ = self.export('0' * 32)
        self.assertEqual(response.status_code, 404, response.text)

    def test_route_409_generation_not_succeeded(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]},
                                  status='failed', intent=INTENT)
        response, _ = self.export(gen_id)
        self.assertEqual(response.status_code, 409, response.text)

    def test_route_400_bad_checkpoint_name(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='bad name')
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn('checkpoint name', response.json()['detail'])

    def test_route_400_multiline_note(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, note='line one\nline two')
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn('single-line note', response.json()['detail'])

    def test_route_409_busy(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        with self.store.lock:
            self.store.state['git_jobs'].append({'id': 'b' * 32, 'lab_id': self.lab_id, 'status': 'queued'})
            self.store.save()
        response, _ = self.export(gen_id)
        self.assertEqual(response.status_code, 409, response.text)

    def test_route_409_while_a_repository_connection_is_being_changed(self):
        # Review follow-up G4 (audit M-3): an export made while a folder change rewrites the binding could never be retried.
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        with self.progress.changing(self.lab_id):
            response, _ = self.export(gen_id)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('Try again in a moment', response.json()['detail'])
        self.assertEqual(self.store.state['git_jobs'], [])
        # Only a change of this lab's connection holds its exports (review issue G4-a).
        with self.progress.changing('another-lab'):
            self.assertEqual(self.export(gen_id)[0].status_code, 200)

    def test_route_409_while_a_design_apply_of_this_lab_is_read_back_after_a_restart(self):
        # Review follow-up J4 (audit L-15): the read-back holds its own lab only; the export says why and waits for it.
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        with self.store.lock:
            self.store.state.setdefault('design_jobs', []).append(dict(id='d' * 32, lab_id='another-lab', status='interrupted', rechecking=['r1']))
            self.store.save()
        self.assertEqual(self.export(gen_id)[0].status_code, 200, 'another lab being read back holds nothing here')
        self.store.state['git_jobs'][-1]['status'] = 'dismissed'
        with self.store.lock:
            self.store.state['design_jobs'][-1]['lab_id'] = self.lab_id; self.store.save()
        response, _ = self.export(gen_id)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("still reading this lab's devices back after a restart", response.json()['detail'])
        self.assertEqual(len(self.store.state['git_jobs']), 1, 'nothing was queued')

    def test_route_409_no_binding(self):
        other = add_lab(self.app, name='unbound-lab')
        gen_id = write_generation(self.app, other, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response = self.client.post(f'/api/labs/{other}/design/generations/{gen_id}/git',
                                    json=dict(request_id=uuid.uuid4().hex, checkpoint='day-1'))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('Connect this lab to a Git repository', response.json()['detail'])

    def test_route_409_changed_vm_identity(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        set_host(self.app, fingerprint='SHA256:different')
        response, _ = self.export(gen_id)
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn('Reconnect the original VM', response.json()['detail'])


# --- 3. execute --------------------------------------------------------------------------------------

class ExecuteTests(DesignExportGitTestCase):

    def test_execute_publishes_checkpoint_target_with_matching_snapshot_and_head(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='day-1', push=False)
        job_id = response.json()['id']
        self.progress.execute(job_id)

        publishes = [r for r in self.sent if r['mode'] == 'publish']
        self.assertEqual(len(publishes), 1, self.sent)
        request = publishes[0]
        self.assertEqual(request['target'], 'checkpoint')
        self.assertEqual(request['checkpoint'], 'day-1')
        self.assertEqual(request['expected_head'], 'a' * 40)
        self.assertNotIn('checkpoint_only', request, 'a design export is no checkpoint from a save')
        # Before its first publication the export asks for the VM copy to be brought up to date, like a save.
        self.assertEqual([r['mode'] for r in self.sent], ['status', 'update', 'publish'])

        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        expected = self.designs.design_snapshot(lab, generation)
        self.assertEqual(request['snapshot']['files'], expected['files'])

        job = self.client.get('/api/git/jobs/' + job_id).json()
        self.assertEqual(job['status'], 'committed')
        self.assertFalse(job['pushed'])

    def test_execute_review_pending_when_push_requested_committed_otherwise(self):
        for push, expected_status in ((False, 'committed'), (True, 'review_pending')):
            with self.subTest(push=push):
                gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
                response, _ = self.export(gen_id, checkpoint='cp-' + gen_id[:8], push=push)
                self.assertEqual(response.status_code, 200, response.text)
                job_id = response.json()['id']
                self.progress.execute(job_id)
                job = self.client.get('/api/git/jobs/' + job_id).json()
                self.assertEqual(job['status'], expected_status, job)
                self.assertFalse(job['pushed'])
                self.assertTrue(job['commit'])
                self.assertFalse(any(r['mode'] == 'push' for r in self.sent))

    def test_retry_with_reviewed_pushes(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='day-1', push=True)
        job_id = response.json()['id']
        self.progress.execute(job_id)
        pending = self.client.get('/api/git/jobs/' + job_id).json()
        self.assertEqual(pending['status'], 'review_pending')

        retry = self.client.post('/api/git/jobs/' + job_id + '/retry', json={'push': True, 'reviewed': True, 'head': self.vm_head})   # the HEAD the review showed
        self.assertEqual(retry.status_code, 200, retry.text)
        self.progress.execute(job_id)

        job = self.client.get('/api/git/jobs/' + job_id).json()
        self.assertEqual(job['status'], 'synced')
        self.assertTrue(job['pushed'])
        pushes = [r for r in self.sent if r['mode'] == 'push']
        self.assertEqual(len(pushes), 1, self.sent)

    def test_digest_mismatch_fails_job_without_publish(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='day-1', push=False)
        job_id = response.json()['id']

        def tampered(lab, generation, **kw):
            result = copy.deepcopy(NetworkDesign.design_snapshot(self.designs, lab, generation))
            result['manifest']['engine_version'] = 'tampered-' + result['manifest']['engine_version']
            return result

        with patch.object(self.designs, 'design_snapshot', side_effect=tampered):
            self.progress.execute(job_id)

        job = self.client.get('/api/git/jobs/' + job_id).json()
        self.assertEqual(job['status'], 'failed', job)
        self.assertIn('changed since this export was started', job['message'])
        self.assertFalse(any(r['mode'] == 'publish' for r in self.sent), self.sent)
        self.assertFalse(any(r['mode'] == 'status' for r in self.sent), self.sent)

    def test_a_save_queued_before_the_lab_name_fix_publishes_what_it_was_bound_to(self):
        # A design export queued (or left unpublished) by a manager whose manifest named every lab 'mapping.json' has its
        # digest over that form. After the upgrade it must publish exactly those bytes, not fail as "changed".
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='day-1', push=False)
        job_id = response.json()['id']
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        before_fix = self.designs.design_snapshot(lab, generation, lab_name=lab['name'])
        before_fix['manifest']['lab_name'] = 'mapping.json'
        with self.store.lock:
            job = next(j for j in self.store.state['git_jobs'] if j['id'] == job_id)
            job['snapshot_digest'] = gp_digest(before_fix)   # what the pre-fix manager recorded at creation
            self.store.save()
        self.progress.execute(job_id)

        job = self.client.get('/api/git/jobs/' + job_id).json()
        self.assertEqual(job['status'], 'committed', job)
        self.assertEqual(self.snapshots[job_id], before_fix, 'the published set is the bound one, byte for byte')
        self.assertEqual(self.snapshots[job_id]['manifest']['lab_name'], 'mapping.json', 'frozen metadata is never relabelled')

    def test_a_save_being_written_before_the_lab_name_fix_reconciles_with_what_it_was_bound_to(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='day-1', push=False)
        job_id = response.json()['id']
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        before_fix = self.designs.design_snapshot(lab, generation, lab_name=lab['name'])
        before_fix['manifest']['lab_name'] = 'mapping.json'
        with self.store.lock:
            job = next(j for j in self.store.state['git_jobs'] if j['id'] == job_id)
            # What the pre-fix manager left when its publish answer was lost: the bound digest, the head and the attempt.
            job.update(snapshot_digest=gp_digest(before_fix), expected_head='a' * 40, published_attempt=True,
                       status='export_pending', retry=True)
            self.store.save()
        self.progress.execute(job_id)

        job = self.client.get('/api/git/jobs/' + job_id).json()
        self.assertEqual(job['status'], 'committed', job)
        self.assertEqual(self.snapshots[job_id], before_fix, 'the replayed publication is the bound one, byte for byte')
        self.assertFalse(any(r['mode'] == 'status' for r in self.sent), 'the recorded head is reused, not re-read')


# --- 4. public_job -----------------------------------------------------------------------------------

class PublicJobTests(DesignExportGitTestCase):

    def test_public_job_exposes_kind_and_generation_id_not_internal_fields(self):
        gen_id = write_generation(self.app, self.lab_id, {'ceos': [('ospf', 'router ospf 1\n')]}, intent=INTENT)
        response, _ = self.export(gen_id, checkpoint='day-1', push=False)
        self.assertEqual(response.status_code, 200, response.text)
        public = response.json()
        self.assertEqual(public['kind'], 'design')
        self.assertEqual(public['generation_id'], gen_id)
        self.assertNotIn('snapshot_digest', public)
        self.assertNotIn('request', public)
        self.assertNotIn('binding_digest', public)

        again = self.client.get('/api/git/jobs/' + response.json()['id']).json()
        self.assertEqual(again['kind'], 'design')
        self.assertEqual(again['generation_id'], gen_id)
        self.assertNotIn('snapshot_digest', again)


# --- 5. restore never treats a design export as a candidate -----------------------------------------

class RestoreCandidateTests(DesignExportGitTestCase):

    def test_restore_never_lists_a_design_version_as_a_candidate(self):
        gen_id = write_generation(self.app, self.lab_id,
                                  {'ceos': [('ospf', 'router ospf 1\n')], 'xrv9k': [('isis', 'router isis CORE\n')]},
                                  intent=INTENT)
        lab = self.store.lab(self.lab_id); generation = self.generation(gen_id)
        snapshot = self.designs.design_snapshot(lab, generation)

        def read_version(host, request, stopping=None):
            if request['mode'] == 'read-version': return {'snapshot': snapshot}
            raise AssertionError(request['mode'])

        with patch('app.git_progress.remote_git', side_effect=read_version):
            desc, candidates = self.app.state.restore.resolve_source(
                self.lab_id, {'type': 'git', 'commit': 'a' * 40, 'path': 'latest'})

        self.assertEqual(candidates, {})
        self.assertEqual(desc['restore_capable_nodes'], 0)
        self.assertEqual(desc['type'], 'git')


if __name__ == '__main__':
    unittest.main()
