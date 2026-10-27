"""Edit topology, the manager side (campaign 2, T04a; docs/parity-campaign/TOPOLOGY-EDIT-DESIGN.md sections 4, 12.2 and 12.5).

The preview's `deployed` option and `map_revision` field, the deployed-save sentences the manager builds from the helper's
`affected` containers and the two topology texts (A13), the per-device plan limits of an apply review (A10), `forget_plan`
after a save with `lab_id` (A12) and the re-registration of a lab after a successful apply, deploy or redeploy (A1). The VM
helper is faked: its answers follow the T03 contract (a flagged `revise` lists every container found by name or path)."""
import copy
import hashlib
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.lab_operations as lab_operations
from app.host_operations import digest
from app.lab_operations import (RECREATE_LIMIT, RESTART_KNOWN_LIMITS, RESTART_UNVERIFIED, MAP_CHANGED_SENTENCE,
                                annotate_plan, deployed_save_warnings, plan_limits)
from app.layout import revision
from app.main import create_app
from app.runner import Runner

PATH = '/etc/containerlab/training/training.clab.yml'
OLD = '''name: training
topology:
  nodes:
    r1: {kind: cisco_xrv9k, image: "xrv:1"}
    r2: {kind: arista_ceos, image: "ceos:1"}
    r3: {kind: linux, image: "mt:1"}
    sw1: {kind: juniper_vjunosswitch, image: "vjs:1"}
    gone: {kind: linux, image: "alpine:1"}
    old: {kind: linux, image: "mt:1", env: {ROLE: "edge"}}
  links:
    - endpoints: ["r1:Gi0/0/0/0", "r2:eth1"]
'''
# r1 and sw1 unchanged, r2 a new image, r3 a new kind, gone removed, old renamed to new (same definition).
NEW = '''name: training
topology:
  nodes:
    r1: {kind: cisco_xrv9k, image: "xrv:1"}
    r2: {kind: arista_ceos, image: "ceos:2"}
    r3: {kind: arista_ceos, image: "mt:1"}
    sw1: {kind: juniper_vjunosswitch, image: "vjs:1"}
    new: {kind: linux, image: "mt:1", env: {ROLE: "edge"}}
  links:
    - endpoints: ["r1:Gi0/0/0/0", "r2:eth1"]
'''
HELPER_SENTENCE = ('This lab has 5 running and 1 stopped devices. Saving replaces the topology file and the map layout on the VM; '
                   'the devices are not changed. Applying the changes is a separate, reviewed step.')
REMOVED = ('Running devices the new file does not define: gone. They keep running until the changes are applied; '
           'applying removes them and their unsaved configuration.')
CHANGED = ('Devices whose definition changed: r2 (image), r3 (kind), old (renamed to new). Applying recreates them; '
           'configuration not saved is lost then. Use Save in the lab header first to keep it.')
NO_DRY_RUN = 'The installed containerlab cannot show what applying will change.'
TERMINAL = ('succeeded', 'failed', 'cancelled', 'interrupted')


def sha(text): return hashlib.sha256(text.encode()).hexdigest()


class TopologyEditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.auth = {'Authorization': 'Bearer ' + self.app.state.store.token}
        self.store = self.app.state.store; self.operations = self.app.state.operations; self.service = self.app.state.discovery
        response = self.client.put('/api/host', headers=self.auth, json=dict(address='127.0.0.1', port=22, username='fixture', auth='password', password='host-secret'))
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post('/api/lab-definitions', headers=self.auth, files={'definition': ('training.clab.yml', OLD.encode(), 'application/yaml')})
        self.assertEqual(response.status_code, 200, response.text)
        self.lab_id = response.json()['id']
        with self.store.lock:
            self.store.state['host']['fingerprint'] = 'SHA256:fixture'
            self.store.lab(self.lab_id)['vm_project_path'] = PATH; self.store.save()
        # The fake VM: its files, the containers the helper lists for this lab, whether deploy has --dry-run, the apply plan.
        self.files = {PATH: OLD}
        self.containers = []
        self.dry_run = True
        self.plan = None
        self.read_errors = {}
        self.calls = []
        self.remote = patch('app.lab_operations.remote', side_effect=self.fake_remote); self.remote.start()

    def tearDown(self):
        self.remote.stop(); self.operations.close()
        self.app.state.git_progress.close(); self.service.close(); self.app.state.runner.close(); self.app.state.node_services.close()
        self.client.close(); self.tmp.cleanup()

    def fake_remote(self, host, req, *args, **kwargs):
        self.calls.append(copy.deepcopy(req))
        mode = req['mode']
        if mode == 'read':
            if req['path'] in self.read_errors: raise self.read_errors[req['path']]
            if req['path'] not in self.files: raise ValueError('The selected VM path no longer exists.')
            return {'path': req['path'], 'text': self.files[req['path']], 'sha256': sha(self.files[req['path']])}
        if mode == 'capabilities':
            return {'actions': {'deploy': {'available': True, 'dry_run': self.dry_run}, 'revise': {'available': True, 'deployed': True}}}
        if mode in ('preview', 'run'):
            options = req.get('options') or {}
            affected = []
            warnings = []
            extra = {}
            if req['action'] == 'revise' and self.containers:
                if options.get('deployed') is not True: raise ValueError('This lab has running devices. Reopen the lab in the manager and save again.')
                affected = sorted(self.containers, key=lambda a: a['name']); warnings.append(HELPER_SENTENCE)
            if req['action'] == 'apply' and self.plan is not None: extra = {'plan': copy.deepcopy(self.plan), 'plan_failed': ''}
            base = {k: req.get(k) for k in ('action', 'name', 'path', 'options')}
            if mode == 'run':
                if req['action'] == 'revise': self.files[req['path']] = options['text']
                return {'exit_code': 0}
            return {**base, 'source_hash': sha(self.files.get(req['path'], '')), 'digest': digest(base), 'affected': affected,
                    'argv': [], 'steps': [], 'warnings': warnings, **extra}
        return {}

    def post(self, **body): return self.client.post('/api/operations/preview', headers=self.auth, json=body)

    def revise(self, text=NEW, **extra):
        options = {'text': text, 'base': {'yaml': sha(self.files[PATH]), 'annotations': ''}, **extra.pop('options', {})}
        return self.post(action='revise', path=PATH, options=options, **extra)

    def execute(self, token):
        """Confirm a review and run its job on this thread; returns the stored job."""
        with patch.object(self.operations.pool, 'submit') as submit, patch.object(self.service, 'refresh'):
            job = self.client.post('/api/operations/confirm', headers=self.auth, json={'token': token})
            self.assertEqual(job.status_code, 200, job.text)
            args = submit.call_args.args; args[0](*args[1:])
        found = next(j for j in self.store.state['operations'] if j['id'] == job.json()['id'])
        self.assertIn(found['status'], TERMINAL); return found

    def deployed(self, stopped=('gone',)):
        names = ('r1', 'r2', 'r3', 'sw1', 'gone', 'old')
        self.containers = [{'name': 'clab-training-' + n, 'id': 'c-' + n, 'state': 'exited' if n in stopped else 'running'} for n in names]

    def events(self, action): return [e for e in self.store.events(lab_id=self.lab_id) if e['action'] == action]

    # 1. The option and the request fields.
    def test_deployed_is_a_revise_option_and_every_wrong_use_is_a_400_never_a_500(self):
        for body, sentence in (
                (dict(action='revise', path=PATH, options={'text': NEW, 'deployed': 'yes'}), 'Invalid boolean option.'),
                (dict(action='revise', path=PATH, options={'text': NEW, 'deployed': 1}), 'Invalid boolean option.'),
                (dict(action='deploy', lab_id=self.lab_id, options={'deployed': True}), 'This action does not take: Save while deployed.'),
                (dict(action='publish', options={'root': '/etc/containerlab', 'text': NEW, 'deployed': True}), 'This action does not take: Save while deployed.'),
                (dict(action='create', path='/etc/containerlab/x.clab.yml', options={'text': NEW, 'deployed': True}), 'This action does not take: Save while deployed.'),
                (dict(action='inspect', lab_id=self.lab_id, options={'deployed': False}), 'This action does not take: Save while deployed.'),
                (dict(action='deploy', lab_id=self.lab_id, map_revision='x'), 'Only Save changes to the VM names a map revision.')):
            response = self.post(**body)
            self.assertEqual((response.status_code, response.json()['detail']), (400, sentence), body)
        self.assertFalse([c for c in self.calls if c['mode'] == 'preview'], 'no refused review reached the helper')
        accepted = self.revise(options={'deployed': True})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertIs(next(c for c in self.calls if c['mode'] == 'preview')['options']['deployed'], True, 'the flag reaches the helper')

    def test_without_the_flag_the_helper_judges_and_its_refusal_is_the_answer(self):
        self.deployed()
        refused = self.revise()
        self.assertEqual((refused.status_code, refused.json()['detail']), (409, 'This lab has running devices. Reopen the lab in the manager and save again.'))
        self.assertTrue([c for c in self.calls if c['mode'] == 'preview'], 'the manager has no refusal of its own for a running lab (R6)')

    def test_a_lab_id_that_no_longer_exists_is_404_and_a_path_only_save_still_works(self):
        missing = self.revise(lab_id='0' * 32, options={'deployed': True})
        self.assertEqual((missing.status_code, missing.json()['detail']), (404, 'Lab not found.'))
        self.assertEqual(self.revise(options={'deployed': True}).status_code, 200)

    # 2. The map revision.
    def test_a_map_changed_in_the_manager_since_edit_topology_opened_refuses_before_the_helper(self):
        current = self.client.get('/api/labs/' + self.lab_id + '/map-document', headers=self.auth).json()['revision']
        self.assertEqual(current, revision(self.store.lab(self.lab_id)['drawing']))
        before = len(self.calls)
        stale = self.revise(lab_id=self.lab_id, map_revision='0' * 64, options={'deployed': True})
        self.assertEqual((stale.status_code, stale.json()['detail']), (409, MAP_CHANGED_SENTENCE))
        self.assertEqual(self.calls[before:], [], 'neither the file nor the helper was asked')
        fresh = self.revise(lab_id=self.lab_id, map_revision=current, options={'deployed': True})
        self.assertEqual(fresh.status_code, 200, fresh.text)
        self.assertEqual(self.revise(map_revision='0' * 64, options={'deployed': True}).status_code, 200, 'without lab_id there is no map to compare')

    # 3. The deployed-save sentences.
    def test_the_deployed_save_names_removed_renamed_and_changed_devices_by_their_device_names(self):
        self.deployed()
        result = self.revise(lab_id=self.lab_id, options={'deployed': True}).json()
        self.assertIs(result['deployed'], True)
        self.assertEqual(result['warnings'], [HELPER_SENTENCE, REMOVED, CHANGED], 'r1 and sw1 are unchanged and named nowhere')
        self.dry_run = False; self.operations.cap_cache = None
        self.assertEqual(self.revise(lab_id=self.lab_id, options={'deployed': True}).json()['warnings'], [HELPER_SENTENCE, REMOVED, CHANGED, NO_DRY_RUN])

    def test_the_job_of_a_deployed_save_carries_the_flag_and_an_undeployed_one_does_not(self):
        # A16: the page's output dialog reads job.deployed, so it never offers a deploy of a lab that runs.
        self.deployed()
        token = self.revise(lab_id=self.lab_id, options={'deployed': True}).json()['token']
        self.assertIs(self.execute(token).get('deployed'), True)
        self.setUp()
        token = self.revise(options={'deployed': True}).json()['token']
        self.assertNotIn('deployed', self.execute(token))

    def test_an_undeployed_save_is_marked_so_and_carries_no_deployed_sentence(self):
        result = self.revise(options={'deployed': True}).json()
        self.assertIs(result['deployed'], False); self.assertEqual(result.get('warnings', []), [])
        self.assertFalse([c for c in self.calls if c['mode'] == 'capabilities'], 'the dry-run question is asked only for a deployed save')

    def test_the_sentences_follow_containers_of_a_lab_deployed_under_another_name(self):
        warnings = deployed_save_warnings(OLD, NEW, [{'name': 'clab-other-gone', 'id': 'x'}, {'name': 'clab-other-r2', 'id': 'y'}], ['other', 'training'], True)
        self.assertEqual(warnings[0], REMOVED)
        self.assertTrue(warnings[1].startswith('Devices whose definition changed: r2 (image). '), warnings)
        self.assertEqual(deployed_save_warnings(OLD, NEW, [{'name': 'clab-training-r1', 'id': 'x'}], ['training'], True), [], 'an unchanged device alone')
        self.assertEqual(deployed_save_warnings('not: a topology', NEW, [{'name': 'clab-training-r1'}], ['training'], False), [NO_DRY_RUN])

    # 4. The plan limits.
    def test_the_apply_review_names_the_devices_to_back_up_first(self):
        self.files[PATH] = NEW
        self.plan = {'deploys_lab': False, 'added': [], 'removed': [], 'recreated': ['sw1', 'r2'], 'started': [], 'restarted': ['r1', 'r3'],
                     'links_added': ['r1:Gi0/0/0/1 -- r3:eth1'], 'endpoints_removed': [], 'reasons': {'sw1': 'config drift: Image'}}
        result = self.post(action='apply', lab_id=self.lab_id).json()
        self.assertEqual(result['plan']['limits'], {'r1': RESTART_KNOWN_LIMITS['cisco_xrv9k'], 'sw1': RECREATE_LIMIT}, 'cEOS r2 and r3 have none')
        self.assertEqual(result['backup_first'], ['r1', 'sw1'])
        self.assertEqual(result['plan']['reasons'], self.plan['reasons'], 'the helper plan is otherwise unchanged')
        self.plan = {**self.plan, 'recreated': ['r2'], 'restarted': ['r3']}
        ceos = self.post(action='apply', lab_id=self.lab_id).json()
        self.assertEqual(ceos['plan']['limits'], {}); self.assertNotIn('backup_first', ceos)

    def test_plan_limits_by_kind_including_the_unverified_vrnetlab_restart(self):
        text = 'name: t\ntopology:\n  nodes:\n    vr: {kind: vr-vjunosrouter}\n    sw: {kind: juniper_vjunosswitch}\n    pe: {kind: juniper_cjunosevolved}\n    c: {kind: ceos}\n'
        limits = plan_limits(text, {'restarted': ['vr', 'sw', 'pe', 'c'], 'recreated': []})
        self.assertEqual(limits, {'sw': RESTART_KNOWN_LIMITS['juniper_vjunosswitch'], 'vr': RESTART_UNVERIFIED})
        self.assertEqual(plan_limits(text, {'restarted': [], 'recreated': ['vr', 'pe', 'c']}), {'pe': RECREATE_LIMIT, 'vr': RECREATE_LIMIT})
        self.assertEqual(annotate_plan('not yaml: [', {'restarted': ['vr']}), ({'restarted': ['vr'], 'limits': {}}, []))

    # 5. lab_id on a save.
    def test_a_succeeded_save_with_lab_id_forgets_the_plan_and_does_not_register_the_lab_again(self):
        self.deployed()
        review = self.revise(lab_id=self.lab_id, options={'deployed': True}).json()
        self.operations.plan_cache[self.lab_id] = (time.monotonic() + 60, {'changed': False}); generation = self.operations.plan_gen.get(self.lab_id, 0)
        before = copy.deepcopy(self.store.lab(self.lab_id))
        job = self.execute(review['token'])
        self.assertEqual(job['status'], 'succeeded', job); self.assertEqual(self.files[PATH], NEW)
        self.assertNotIn(self.lab_id, self.operations.plan_cache); self.assertGreater(self.operations.plan_gen[self.lab_id], generation)
        lab = self.store.lab(self.lab_id)
        self.assertEqual((lab['definition_yaml'], lab['nodes'], lab['drawing']), (before['definition_yaml'], before['nodes'], before['drawing']),
                         'between a deployed save and Apply the lab keeps its running devices (A1)')
        self.assertEqual(self.events('topology.registered'), []); self.assertNotIn('note', job)

    # 6. The re-registration after Apply.
    def test_a_succeeded_apply_registers_the_lab_from_the_vm_file_keeping_its_deployment_hide_and_settings(self):
        with self.store.lock:
            lab = self.store.lab(self.lab_id)
            lab['deployment_name'] = 'training-live'; lab['hidden'] = True; lab['favorite'] = True
            next(n for n in lab['nodes'] if n['definition_node'] == 'r1')['username'] = 'student'
            self.store.save()
        self.files[PATH] = NEW
        self.files[PATH + '.annotations.json'] = json.dumps({'nodeAnnotations': [{'id': 'r1', 'position': {'x': 40, 'y': 50}}, {'id': 'new', 'position': {'x': 300, 'y': 70}}]})
        self.plan = {'deploys_lab': False, 'added': ['new'], 'removed': ['gone', 'old'], 'recreated': [], 'started': [], 'restarted': [], 'links_added': [], 'endpoints_removed': [], 'reasons': {}}
        job = self.execute(self.post(action='apply', lab_id=self.lab_id).json()['token'])
        self.assertEqual(job['status'], 'succeeded', job); self.assertNotIn('note', job)
        lab = self.store.lab(self.lab_id)
        self.assertEqual([n['definition_node'] for n in lab['nodes']], ['r1', 'r2', 'r3', 'sw1', 'new'], 'the devices follow the file')
        self.assertEqual(lab['definition_yaml'], NEW)
        drawn = {n['id']: (n['x'], n['y']) for n in lab['drawing']['nodes']}
        self.assertEqual((drawn['r1'], drawn['new']), ((40, 50), (300, 70)), 'the map follows the VM map file'); self.assertNotIn('gone', drawn)
        self.assertEqual(lab['annotations'], self.files[PATH + '.annotations.json'], 'kept through keep_document')
        self.assertEqual(lab['annotations_for'], revision(lab['drawing']))
        self.assertEqual((lab['deployment_name'], lab.get('hidden'), lab.get('favorite')), ('training-live', True, True))
        self.assertEqual(next(n for n in lab['nodes'] if n['definition_node'] == 'r1')['username'], 'student')
        self.assertEqual(next(n for n in lab['nodes'] if n['definition_node'] == 'new')['name'], 'clab-training-live-new')
        self.assertEqual([e['message'] for e in self.events('topology.registered')], ['Lab definition refreshed after apply'])

    def test_deploy_and_redeploy_register_too_and_a_map_placed_in_the_manager_keeps_its_positions(self):
        response = self.client.put('/api/labs/' + self.lab_id + '/layout', headers=self.auth, json={'positions': {'r1': [11, 22]}})
        self.assertEqual(response.status_code, 200, response.text)
        self.files[PATH] = NEW
        self.files[PATH + '.annotations.json'] = json.dumps({'nodeAnnotations': [{'id': 'r1', 'position': {'x': 999, 'y': 999}}]})
        job = self.execute(self.post(action='deploy', lab_id=self.lab_id).json()['token'])
        self.assertEqual(job['status'], 'succeeded', job)
        lab = self.store.lab(self.lab_id); drawn = {n['id']: (n['x'], n['y']) for n in lab['drawing']['nodes']}
        self.assertEqual(drawn['r1'], (11, 22), 'a person placed it here since the last sync: the old VM map file does not win')
        self.assertIn('new', drawn, "the file's new device is on the map"); self.assertNotIn('gone', [n['definition_node'] for n in lab['nodes']])
        self.files[PATH] = OLD
        job = self.execute(self.post(action='redeploy', lab_id=self.lab_id).json()['token'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertIn('gone', [n['definition_node'] for n in self.store.lab(self.lab_id)['nodes']])
        self.assertEqual(len(self.events('topology.registered')), 2)

    def test_a_read_failure_is_a_note_on_the_succeeded_job_and_the_lab_stays_as_it_was(self):
        before = copy.deepcopy(self.store.lab(self.lab_id))
        token = self.post(action='apply', lab_id=self.lab_id).json()['token']
        self.files[PATH] = NEW; self.read_errors[PATH] = ValueError('Operation connection interrupted. Inspect the lab before retrying.')
        job = self.execute(token)
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertTrue(job['note'].startswith('The lab ran, but the manager could not read its topology file on the VM afterwards'), job['note'])
        self.assertNotIn('interrupted', job['note'], 'a fixed sentence, never the transport error')
        lab = self.store.lab(self.lab_id)
        self.assertEqual((lab['definition_yaml'], lab['nodes']), (before['definition_yaml'], before['nodes']))
        self.assertEqual(self.events('topology.registered'), [])

    def test_an_unreadable_map_file_is_a_note_and_the_devices_still_follow_the_file(self):
        self.files[PATH] = NEW
        self.read_errors[PATH + '.annotations.json'] = ValueError('Select a regular file smaller than 1 MiB.')
        job = self.execute(self.post(action='apply', lab_id=self.lab_id).json()['token'])
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(job['note'], 'The manager could not read the map file beside the topology on the VM; the map in the manager was kept.')
        lab = self.store.lab(self.lab_id)
        self.assertIn('new', [n['definition_node'] for n in lab['nodes']]); self.assertIn('new', [n['id'] for n in lab['drawing']['nodes']])
        del self.read_errors[PATH + '.annotations.json']   # an absent map file is not a problem: no note
        self.files[PATH] = OLD
        self.assertNotIn('note', self.execute(self.post(action='apply', lab_id=self.lab_id).json()['token']))

    # 7. The map after Apply: the VM file's devices merged into a kept manager map (A18), the marker of a registration (A18).
    def placed(self, names=('r1', 'r2', 'r3', 'sw1', 'gone', 'old')):
        """Register the lab again from a file with a placed map, as the builder's undeployed save does."""
        ann = json.dumps({'nodeAnnotations': [{'id': n, 'position': {'x': 10 + i * 100, 'y': 10}} for i, n in enumerate(names)]})
        response = self.client.post('/api/lab-definitions', headers=self.auth, data={'lab_id': self.lab_id},
                                    files={'definition': ('training.clab.yml', OLD.encode(), 'application/yaml'),
                                           'annotations': ('training.clab.yml.annotations.json', ann.encode(), 'application/json')})
        self.assertEqual(response.status_code, 200, response.text)

    def apply_new(self, vm_map):
        self.files[PATH] = NEW; self.files[PATH + '.annotations.json'] = vm_map
        self.plan = {'deploys_lab': False, 'added': ['new'], 'removed': ['gone', 'old'], 'recreated': [], 'started': [], 'restarted': [], 'links_added': [], 'endpoints_removed': [], 'reasons': {}}
        job = self.execute(self.post(action='apply', lab_id=self.lab_id).json()['token'])
        self.assertEqual(job['status'], 'succeeded', job); self.assertNotIn('note', job)
        lab = self.store.lab(self.lab_id)
        return lab, {n['id']: (n['x'], n['y']) for n in lab['drawing']['nodes']}

    def test_a_map_registered_from_a_file_is_the_vm_map_so_the_vm_map_file_wins_after_apply(self):
        self.placed()
        lab = self.store.lab(self.lab_id)
        self.assertNotIn('synced_at', lab.get('vm_source') or {})
        self.assertNotIn('map_written_at', lab, 'placed from a file, not by a person')
        self.assertFalse(Runner.map_changed_in_manager(lab), "never changed by the accident of '' == ''")
        # The builder's deployed save wrote the manager's map plus the new device beside the new file.
        vm_map = json.dumps({'nodeAnnotations': [{'id': n, 'position': {'x': 10 + i * 100, 'y': 10}} for i, n in enumerate(('r1', 'r2', 'r3', 'sw1'))]
                            + [{'id': 'new', 'position': {'x': 777, 'y': 333}}]})
        lab, drawn = self.apply_new(vm_map)
        self.assertEqual((drawn['r1'], drawn['new']), ((10, 10), (777, 333)))
        self.assertEqual(lab['annotations'], vm_map)
        self.assertNotIn('map_written_at', lab, 'the map after Apply is the VM file again'); self.assertFalse(Runner.map_changed_in_manager(lab))

    def test_a_map_changed_in_the_manager_keeps_its_positions_and_takes_the_new_devices_from_the_vm_file(self):
        self.placed()
        response = self.client.put('/api/labs/' + self.lab_id + '/layout', headers=self.auth, json={'positions': {'r1': [11, 22]}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(Runner.map_changed_in_manager(self.store.lab(self.lab_id)))
        vm_map = json.dumps({'nodeAnnotations': [{'id': 'r1', 'position': {'x': 999, 'y': 999}}, {'id': 'r2', 'position': {'x': 998, 'y': 998}},
                                                 {'id': 'new', 'position': {'x': 300, 'y': 70}, 'icon': 'client', 'iconColor': '#123456'}]})
        lab, drawn = self.apply_new(vm_map)
        self.assertEqual((drawn['r1'], drawn['r2'], drawn['r3']), ((11, 22), (110, 10), (210, 10)), "the manager's entries win for its devices")
        self.assertEqual(drawn['new'], (300, 70), 'the device new in the file takes its VM position')
        new = next(n for n in lab['drawing']['nodes'] if n['id'] == 'new')
        self.assertEqual((new['icon'], new['iconColor']), ('client', '#123456'), 'and its look')
        document = json.loads(lab['annotations'])
        self.assertEqual([r['id'] for r in document['nodeAnnotations']].count('new'), 1)
        self.assertEqual(lab['annotations_for'], revision(lab['drawing']), 'kept through keep_document, the drawing read from it')
        self.assertTrue(Runner.map_changed_in_manager(lab), "still the person's map")

    def test_an_old_empty_marker_without_a_sync_still_keeps_the_manager_map_and_merges(self):
        # A lab stored before registration dropped the marker: ambiguous, so the person's map is kept (and merged).
        self.placed()
        with self.store.lock: self.store.lab(self.lab_id)['map_written_at'] = ''; self.store.save()
        self.assertTrue(Runner.map_changed_in_manager(self.store.lab(self.lab_id)))
        _, drawn = self.apply_new(json.dumps({'nodeAnnotations': [{'id': 'r1', 'position': {'x': 999, 'y': 999}}, {'id': 'new', 'position': {'x': 5, 'y': 6}}]}))
        self.assertEqual((drawn['r1'], drawn['new']), ((10, 10), (5, 6)))

    def test_a_device_the_vm_map_file_lacks_takes_nothing_extra(self):
        self.placed()
        self.client.put('/api/labs/' + self.lab_id + '/layout', headers=self.auth, json={'positions': {'r1': [11, 22]}})
        kept = self.client.get('/api/labs/' + self.lab_id + '/map-document', headers=self.auth).json()
        vm_map = json.dumps({'nodeAnnotations': [{'id': 'r1', 'position': {'x': 999, 'y': 999}}, {'id': 'ghost', 'position': {'x': 5, 'y': 5}}],
                             'freeTextAnnotations': [{'id': 't1', 'text': 'from the VM', 'position': {'x': 1, 'y': 1}}]})
        lab, drawn = self.apply_new(vm_map)
        self.assertEqual(drawn['r1'], (11, 22)); self.assertIn('new', drawn, 'the new device is on the map, at the default place')
        self.assertNotIn('ghost', drawn, 'a VM entry for a device the file does not define is not taken')
        self.assertEqual(lab['annotations'], kept['annotations'], "nothing to add: the manager's document text for text")
        document = json.loads(lab['annotations'])
        self.assertFalse({'new', 'ghost'} & {r['id'] for r in document['nodeAnnotations']}, 'no entry invented or taken')
        self.assertFalse(document.get('freeTextAnnotations'), "the VM file's texts are not taken")

    # 8. The map revision again at confirm (A19).
    def test_a_map_changed_between_review_and_confirm_refuses_the_confirm_and_creates_no_job(self):
        self.deployed()
        current = self.client.get('/api/labs/' + self.lab_id + '/map-document', headers=self.auth).json()['revision']
        token = self.revise(lab_id=self.lab_id, map_revision=current, options={'deployed': True}).json()['token']
        response = self.client.put('/api/labs/' + self.lab_id + '/layout', headers=self.auth, json={'positions': {'r1': [11, 22]}})
        self.assertEqual(response.status_code, 200, response.text)
        jobs = len(self.store.state['operations'])
        with patch.object(self.operations.pool, 'submit') as submit:
            refused = self.client.post('/api/operations/confirm', headers=self.auth, json={'token': token})
        self.assertEqual((refused.status_code, refused.json()['detail']), (409, MAP_CHANGED_SENTENCE))
        submit.assert_not_called(); self.assertEqual(len(self.store.state['operations']), jobs); self.assertEqual(self.files[PATH], OLD)
        current = self.client.get('/api/labs/' + self.lab_id + '/map-document', headers=self.auth).json()['revision']
        job = self.execute(self.revise(lab_id=self.lab_id, map_revision=current, options={'deployed': True}).json()['token'])
        self.assertEqual(job['status'], 'succeeded', job); self.assertEqual(self.files[PATH], NEW)
        path_only = self.revise(text=OLD, options={'deployed': True}).json()['token']
        self.client.put('/api/labs/' + self.lab_id + '/layout', headers=self.auth, json={'positions': {'r1': [33, 44]}})
        self.assertEqual(self.execute(path_only)['status'], 'succeeded', 'a save without lab_id names no map to compare')

    def test_a_failed_apply_registers_nothing(self):
        self.files[PATH] = NEW
        token = self.post(action='apply', lab_id=self.lab_id).json()['token']
        inner = self.fake_remote
        def failing(host, req, *args, **kwargs):
            if req['mode'] == 'run': return {'exit_code': 1}
            return inner(host, req, *args, **kwargs)
        self.remote.stop(); self.remote = patch('app.lab_operations.remote', side_effect=failing); self.remote.start()
        job = self.execute(token)
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(self.store.lab(self.lab_id)['definition_yaml'], OLD); self.assertEqual(self.events('topology.registered'), [])


if __name__ == '__main__':
    unittest.main()
