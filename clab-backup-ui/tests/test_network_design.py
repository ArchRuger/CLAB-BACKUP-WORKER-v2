"""Tests for app/network_design.py: the network design intent's HTTP surface (view, save, clear,
renumber), generation jobs run through the pinned `netlab` engine, their immutable artifacts, the
download bundle, export/import and the pure serialisers (public_design, public_generation,
requested_features).

Everything here drives the real app through TestClient against scratch state (create_app(<tempdir>)
or Store(<tempdir>) directly, never live data). Generation is a real child process (design_engine
runs the pinned `netlab` CLI), so every test that submits a generation and polls it to completion
uses `with TestClient(app) as client:` so the ASGI portal (and its event loop) is created once up
front, before any test that also needs to patch socket.socket around the request/poll loop (patching
socket.socket while TestClient still has to open a *new* portal per call breaks the client itself,
since starlette's default portal is created lazily per request outside a `with` block).

Generation tests need the pinned `netlab` engine on PATH (CLAUDE.md's PATH="$PWD/.venv/bin:$PATH"
prefix provides it) and are skipped, with a message, when it is absent.
"""
import copy
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
import zipfile
from io import BytesIO
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import create_app
from app.store import Store
from app.discovery import parse_definition
from app import design_intent as intent_schema
from app import network_design as nd
from app.network_design import NetworkDesign, public_design, public_generation, requested_features

HAS_NETLAB = shutil.which('netlab') is not None
SKIP_REASON = 'netlab is not on PATH for this test run'

TOPOLOGY = '''name: restore-square
mgmt:
  network: clab
  ipv4-subnet: 172.20.20.0/24
topology:
  nodes:
    ceos:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.101
    cjunosevolved:
      kind: juniper_cjunosevolved
      image: n24l/cjunosevolved:26.2R1.7-EVO
      mgmt-ipv4: 172.20.20.102
    vjunos-switch:
      kind: juniper_vjunosswitch
      image: n24l/vjunos-switch:23.2R1.14
      mgmt-ipv4: 172.20.20.103
    xrv9k:
      kind: cisco_xrv9k
      image: n24l/cisco_xrv9k:24.3.1
      mgmt-ipv4: 172.20.20.104
    host1:
      kind: linux
      image: ghcr.io/srl-labs/network-multitool:latest
      mgmt-ipv4: 172.20.20.105
  links:
    - endpoints: ["ceos:eth1", "cjunosevolved:et-0/0/0"]
    - endpoints: ["cjunosevolved:et-0/0/1", "vjunos-switch:ge-0/0/0"]
    - endpoints: ["vjunos-switch:ge-0/0/1", "xrv9k:Gi0/0/0/0"]
    - endpoints: ["xrv9k:Gi0/0/0/1", "ceos:eth2"]
    - endpoints: ["host1:eth1", "vjunos-switch:ge-0/0/2"]
    - endpoints: ["host1:eth2", "ceos:eth3"]
'''


def valid_intent():
    """A design intent that validates without the engine schema: dual stack, OSPF and BGP enabled."""
    intent = intent_schema.empty_intent()
    intent['modules'] = ['ospf', 'bgp']
    intent['ospf'] = {'area': '0.0.0.0'}
    intent['bgp'] = {'as': 65000}
    return intent


def add_lab(app, name='restore-square', definition_yaml=TOPOLOGY):
    """Appends a lab record straight into the store (never through a helper or the VM), as
    test_restore.py does; returns the new lab's id."""
    lab_id = uuid.uuid4().hex
    with app.state.store.lock:
        nodes = parse_definition(definition_yaml.encode())['nodes'] if definition_yaml else []
        lab = dict(id=lab_id, name=name, nodes=nodes, profiles=[], defaults={}, interval=0,
                   next_run=None, created='2026-09-26T00:00:00+00:00', updated='2026-09-26T00:00:00+00:00',
                   definition_yaml=definition_yaml)
        app.state.store.state['labs'].append(lab)
        app.state.store.save()
    return lab_id


def plant_design(app, lab_id, intent):
    """Stores `intent` on the lab as if it had been saved before a module it uses was retired (Save refuses to add a
    retired module now); returns its revision."""
    stored = intent_schema.normalize(intent)
    with app.state.store.lock:
        app.state.store.lab(lab_id)['network_design'] = stored
        app.state.store.save()
    return stored['revision']


def poll_generation(client, lab_id, generation_id, timeout=90):
    """Polls GET .../design until `generation_id` leaves queued/running; returns its public record."""
    deadline = time.monotonic() + timeout
    newest = None
    while time.monotonic() < deadline:
        response = client.get(f'/api/labs/{lab_id}/design')
        generations = response.json()['generations']
        matches = [g for g in generations if g['id'] == generation_id]
        if matches:
            newest = matches[0]
            if newest['status'] not in nd.DESIGN_BUSY:
                return newest
        time.sleep(0.2)
    raise AssertionError('Generation did not finish in time: ' + str(newest))


class DesignViewTests(unittest.TestCase):
    """Behaviour 1: the read-only design view of a lab, with and without a topology file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.network_design.close)

    def test_view_of_a_lab_without_a_design(self):
        lab_id = add_lab(self.app)
        response = self.client.get(f'/api/labs/{lab_id}/design')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data['intent'])
        self.assertIsNone(data['summary'])
        self.assertTrue(data['has_topology'])
        self.assertEqual(data['problems'], [])

        nodes = data['nodes']
        expected_profiles = {'ceos': 'eos', 'cjunosevolved': 'vptx', 'vjunos-switch': 'vjunos-switch',
                              'xrv9k': 'iosxr', 'host1': 'linux'}
        self.assertEqual(set(nodes), set(expected_profiles))
        for name, profile in expected_profiles.items():
            self.assertEqual(nodes[name]['profile'], profile, name)
            self.assertTrue(nodes[name]['included'], name)

        links = data['links']
        self.assertEqual(len(links), 6)
        for link in links:
            self.assertTrue(link['included'], link)
            for endpoint in link['endpoints'].values():
                self.assertTrue(endpoint['nos'])
                self.assertEqual(endpoint['source'], 'rule')

        self.assertTrue(data['capabilities'])
        kinds_in_matrix = {row['kind'] for row in data['capabilities']}
        for kind in ('arista_ceos', 'juniper_cjunosevolved', 'juniper_vjunosswitch', 'cisco_xrv9k'):
            self.assertIn(kind, kinds_in_matrix)

        self.assertTrue(data['catalogue'])
        self.assertIn('label', data['catalogue'][0])

        self.assertIn('available', data['engine'])
        self.assertIsInstance(data['modules'], list)
        self.assertIsInstance(data['pools'], list)
        self.assertIn('ospf', data['modules'])
        self.assertIn('loopback', data['pools'])

    def test_view_of_a_lab_without_a_topology_file(self):
        lab_id = add_lab(self.app, name='no-topology', definition_yaml='')
        response = self.client.get(f'/api/labs/{lab_id}/design')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['has_topology'])
        self.assertEqual(data['nodes'], {})

    def test_unknown_lab_is_404(self):
        response = self.client.get('/api/labs/' + uuid.uuid4().hex + '/design')
        self.assertEqual(response.status_code, 404)


class SaveDesignTests(unittest.TestCase):
    """Behaviours 2, 3 and 4: PUT /design, its validation, revision guard and the server-owned ledger."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.network_design.close)
        self.lab_id = add_lab(self.app)

    def test_invalid_intent_with_unknown_top_level_key_is_refused(self):
        intent = valid_intent()
        intent['bogus'] = 1
        response = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': intent, 'revision': ''})
        self.assertEqual(response.status_code, 400)
        self.assertIn('Fix the design first', response.json()['detail'])
        self.assertIn('bogus', response.json()['detail'])

        view = self.client.get(f'/api/labs/{self.lab_id}/design').json()
        self.assertIsNone(view['intent'])

        validate = self.client.post(f'/api/labs/{self.lab_id}/design/validate', json={'intent': intent})
        self.assertEqual(validate.status_code, 200)
        body = validate.json()
        self.assertFalse(body['valid'])
        self.assertTrue(body['problems'])
        self.assertIsNone(self.client.get(f'/api/labs/{self.lab_id}/design').json()['intent'])

    def test_invalid_intent_with_a_pool_overlapping_management_is_refused(self):
        intent = intent_schema.empty_intent()
        intent['addressing']['lan']['ipv4'] = '172.20.20.0/24'  # exactly the lab's mgmt ipv4-subnet
        response = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': intent, 'revision': ''})
        self.assertEqual(response.status_code, 400)
        detail = response.json()['detail']
        self.assertIn('Fix the design first', detail)
        self.assertIn('addressing.lan.ipv4', detail)
        self.assertIsNone(self.client.get(f'/api/labs/{self.lab_id}/design').json()['intent'])

        validate = self.client.post(f'/api/labs/{self.lab_id}/design/validate', json={'intent': intent})
        self.assertEqual(validate.status_code, 200)
        self.assertEqual(validate.json()['valid'], False)
        self.assertTrue(validate.json()['problems'])

    def test_malformed_families_or_device_modules_are_a_readable_400_never_a_500(self):
        import yaml
        for field, intent in (('families', dict(valid_intent(), families='x')), ('families', dict(valid_intent(), families=None)),
                              ('nodes.ceos.modules', dict(valid_intent(), nodes={'ceos': {'modules': [['ospf']]}})),
                              ('nodes.ceos.modules', dict(valid_intent(), nodes={'ceos': {'modules': [{}]}}))):
            with self.subTest(field=field, value=intent['families'] if field == 'families' else intent['nodes']):
                saved = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': intent, 'revision': ''})
                self.assertEqual(saved.status_code, 400, saved.text)
                self.assertIn('Fix the design first', saved.json()['detail'])
                self.assertIn(field, saved.json()['detail'])
                checked = self.client.post(f'/api/labs/{self.lab_id}/design/validate', json={'intent': intent})
                self.assertEqual(checked.status_code, 200, checked.text)
                self.assertFalse(checked.json()['valid'])
                self.assertIn(field, [p['path'] for p in checked.json()['problems']])
                imported = self.client.post(f'/api/labs/{self.lab_id}/design/import', files={'intent': ('x.yml', yaml.safe_dump(intent).encode(), 'application/yaml')})
                self.assertEqual(imported.status_code, 200, imported.text)
                self.assertFalse(imported.json()['imported'])
                self.assertIn(field, [p['path'] for p in imported.json()['problems']])
        self.assertIsNone(self.client.get(f'/api/labs/{self.lab_id}/design').json()['intent'])

    def test_saving_a_valid_intent_succeeds_and_is_stripped_from_public_state(self):
        response = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertRegex(body['intent']['revision'], r'^[0-9a-f]{24}$')
        self.assertTrue(body['summary']['present'])
        self.assertEqual(body['problems'], [])

        state = self.client.get('/api/state').json()
        lab_state = next(l for l in state['labs'] if l['id'] == self.lab_id)
        self.assertIn('design', lab_state)
        self.assertTrue(lab_state['design']['present'])
        self.assertEqual(lab_state['design']['revision'], body['intent']['revision'])
        self.assertEqual(lab_state['design']['modules'], ['ospf', 'bgp'])
        self.assertFalse(lab_state['design']['generating'])
        self.assertNotIn('network_design', lab_state)
        self.assertNotIn('network_generations', lab_state)

        with self.app.state.store.lock:
            stored_lab = self.app.state.store.lab(self.lab_id)
        self.assertIn('network_design', stored_lab)
        self.assertEqual(stored_lab['network_design']['schema'], 1)

    def test_stale_revision_is_refused_then_a_changed_label_gets_a_new_revision_and_a_no_op_keeps_it(self):
        first = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
        revision = first.json()['intent']['revision']

        stale = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': valid_intent(), 'revision': 'deadbeef'})
        self.assertEqual(stale.status_code, 409)
        self.assertIn('changed since this page loaded', stale.json()['detail'])

        changed = valid_intent()
        changed['label'] = 'changed'
        second = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': changed, 'revision': revision})
        self.assertEqual(second.status_code, 200)
        new_revision = second.json()['intent']['revision']
        self.assertNotEqual(new_revision, revision)

        no_op = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': changed, 'revision': new_revision})
        self.assertEqual(no_op.status_code, 200)
        self.assertEqual(no_op.json()['intent']['revision'], new_revision)

    def test_client_supplied_allocations_never_overwrite_the_server_ledger(self):
        first = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
        revision = first.json()['intent']['revision']
        self.assertEqual(first.json()['intent']['allocations'], {})

        with self.app.state.store.lock:
            lab = self.app.state.store.lab(self.lab_id)
            lab['network_design']['allocations'] = {'node_ids': {'ceos': 7}}
            self.app.state.store.save()

        tampered = valid_intent()
        tampered['label'] = 'still changed'
        tampered['allocations'] = {'node_ids': {'ceos': 99, 'xrv9k': 1}}
        response = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': tampered, 'revision': revision})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['intent']['allocations'], {'node_ids': {'ceos': 7}})


class ClearAndRenumberTests(unittest.TestCase):
    """Behaviours 5 and 6: clearing the design and forgetting the allocation ledger."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.network_design.close)
        self.lab_id = add_lab(self.app)
        saved = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
        self.revision = saved.json()['intent']['revision']

    def test_clear_with_wrong_revision_then_the_right_one_then_again_on_an_empty_design(self):
        wrong = self.client.post(f'/api/labs/{self.lab_id}/design/clear', json={'revision': 'not-it'})
        self.assertEqual(wrong.status_code, 409)
        self.assertIn('changed since this page loaded', wrong.json()['detail'])

        cleared = self.client.post(f'/api/labs/{self.lab_id}/design/clear', json={'revision': self.revision})
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()['intent'])

        again = self.client.post(f'/api/labs/{self.lab_id}/design/clear', json={'revision': ''})
        self.assertEqual(again.status_code, 200)
        self.assertIsNone(again.json()['intent'])

    def test_renumber_empties_the_allocation_ledger(self):
        with self.app.state.store.lock:
            lab = self.app.state.store.lab(self.lab_id)
            lab['network_design']['allocations'] = {'node_ids': {'ceos': 1, 'xrv9k': 4}}
            self.app.state.store.save()

        wrong = self.client.post(f'/api/labs/{self.lab_id}/design/renumber', json={'revision': 'not-it'})
        self.assertEqual(wrong.status_code, 409)

        response = self.client.post(f'/api/labs/{self.lab_id}/design/renumber', json={'revision': self.revision})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['intent']['allocations'], {})

    def test_renumber_without_a_design_is_404(self):
        lab_id = add_lab(self.app, name='no-design')
        response = self.client.post(f'/api/labs/{lab_id}/design/renumber', json={'revision': ''})
        self.assertEqual(response.status_code, 404)
        self.assertIn('no design', response.json()['detail'])


class GenerateGuardTests(unittest.TestCase):
    """Behaviour 7: the guards submit() checks before ever touching the engine."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.network_design.close)

    def test_generate_without_a_design_is_409(self):
        lab_id = add_lab(self.app)
        response = self.client.post(f'/api/labs/{lab_id}/design/generate', json={'revision': ''})
        self.assertEqual(response.status_code, 409)
        self.assertIn('Save a design first', response.json()['detail'])

    def test_generate_without_a_topology_file_is_409(self):
        lab_id = add_lab(self.app, name='no-topology', definition_yaml='')
        with self.app.state.store.lock:
            lab = self.app.state.store.lab(lab_id)
            stored = intent_schema.normalize(valid_intent())
            stored['updated'] = '2026-09-26T00:00:00+00:00'
            lab['network_design'] = stored
            self.app.state.store.save()
        response = self.client.post(f'/api/labs/{lab_id}/design/generate', json={'revision': stored['revision']})
        self.assertEqual(response.status_code, 409)
        self.assertIn('topology', response.json()['detail'])

    def test_generate_with_a_stale_revision_is_409(self):
        lab_id = add_lab(self.app)
        self.client.put(f'/api/labs/{lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
        response = self.client.post(f'/api/labs/{lab_id}/design/generate', json={'revision': 'deadbeef'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('changed since this page loaded', response.json()['detail'])


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class RealEngineGenerationTests(unittest.TestCase):
    """Behaviours 8, 9, 10, 12 and 13: a real generation run through the pinned netlab engine."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.app.state.network_design.close)
        self.lab_id = add_lab(self.app)
        saved = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
        self.revision = saved.json()['intent']['revision']

    def generate(self):
        response = self.client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': self.revision})
        self.assertEqual(response.status_code, 200, response.text)
        generation_id = response.json()['id']
        self.assertIn(response.json()['status'], ('queued', 'running'))
        return poll_generation(self.client, self.lab_id, generation_id, timeout=90)

    def test_successful_generation_artifacts_ledger_and_compatibility(self):
        record = self.generate()
        self.assertEqual(record['status'], 'succeeded')

        artifacts = record['artifacts']
        self.assertEqual([m for m, _ in [(a['module'], a) for a in artifacts['ceos']]],
                          ['normalize', 'initial', 'ospf', 'bgp'])
        self.assertEqual([a['module'] for a in artifacts['xrv9k']], ['initial', 'ospf', 'bgp'])
        for name in ('ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k', 'host1'):
            self.assertIn(name, artifacts)
            for entry in artifacts[name]:
                self.assertIn('module', entry)
                self.assertIn('size', entry)
                self.assertIn('sha256', entry)

        ledger = record['ledger']
        self.assertEqual(set(ledger), {'node_ids', 'loopbacks', 'links', 'router_ids'})
        self.assertEqual(len(ledger['links']), 6)
        self.assertEqual(record['passes'], 1)
        self.assertEqual(record['engine_version'], '26.09')
        self.assertTrue(record['plan_digest'])
        self.assertNotIn('folder', record)
        self.assertNotIn('stderr_tail', record)

        ceos_rows = {row['feature']: row for row in record['compatibility']['ceos']}
        self.assertEqual(ceos_rows['ospfv2']['level'], 'generated_not_live_tested')

        view = self.client.get(f'/api/labs/{self.lab_id}/design').json()
        self.assertEqual(view['intent']['revision'], self.revision)  # the ledger never bumps the revision
        self.assertEqual(view['intent']['allocations'], ledger)
        self.assertEqual(view['summary']['generation']['status'], 'succeeded')

        state = self.client.get('/api/state').json()
        lab_state = next(l for l in state['labs'] if l['id'] == self.lab_id)
        self.assertEqual(lab_state['design']['generation']['status'], 'succeeded')

    def test_generation_detail_artifacts_and_download(self):
        record = self.generate()
        generation_id = record['id']

        detail = self.client.get(f'/api/labs/{self.lab_id}/design/generations/{generation_id}')
        self.assertEqual(detail.status_code, 200)
        plan = detail.json()['plan']
        xrv9k = next(d for d in plan['devices'] if d['name'] == 'xrv9k')
        clab_names = {i['ifname']: i['clab'] for i in xrv9k['interfaces']}
        self.assertEqual(clab_names.get('GigabitEthernet0/0/0/0'), 'Gi0/0/0/0')
        self.assertTrue(plan['links'])

        ceos_initial = self.client.get(f'/api/labs/{self.lab_id}/design/generations/{generation_id}/artifacts/ceos/1')
        self.assertEqual(ceos_initial.status_code, 200)
        self.assertEqual(ceos_initial.headers['content-type'], 'text/plain; charset=utf-8')
        self.assertIn('interface Management0', ceos_initial.text)
        self.assertIn('ip routing', ceos_initial.text)

        out_of_range = self.client.get(f'/api/labs/{self.lab_id}/design/generations/{generation_id}/artifacts/ceos/99')
        self.assertEqual(out_of_range.status_code, 404)

        unknown_node = self.client.get(f'/api/labs/{self.lab_id}/design/generations/{generation_id}/artifacts/nosuchnode/0')
        self.assertEqual(unknown_node.status_code, 404)

        # Tamper with the stored artifact under the manager's own data directory.
        folder = self.app.state.network_design.root / self.lab_id / generation_id / 'nodes' / 'ceos' / '01-initial'
        self.assertTrue(folder.is_file())
        folder.write_text(folder.read_text() + 'TAMPERED\n')
        tampered = self.client.get(f'/api/labs/{self.lab_id}/design/generations/{generation_id}/artifacts/ceos/1')
        self.assertEqual(tampered.status_code, 409)
        self.assertIn('no longer matches', tampered.json()['detail'])

        download = self.client.get(f'/api/labs/{self.lab_id}/design/generations/{generation_id}/download')
        self.assertEqual(download.status_code, 200)
        archive = zipfile.ZipFile(BytesIO(download.content))
        names = set(archive.namelist())
        manifest = __import__('json').loads(archive.read('manifest.json'))
        self.assertEqual(manifest['type'], 'network-design-generation')
        for expected in ('intent.json', 'plan.json', 'topology.yml', 'mapping.json', 'nodes/xrv9k/01-ospf.cfg'):
            self.assertIn(expected, names, names)

        unknown_generation = self.client.get(f'/api/labs/{self.lab_id}/design/generations/unknown')
        self.assertEqual(unknown_generation.status_code, 404)

    def test_a_second_generation_of_the_same_design_keeps_the_pinned_allocations(self):
        first = self.generate()
        second_response = self.client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': self.revision})
        self.assertEqual(second_response.status_code, 200)
        second = poll_generation(self.client, self.lab_id, second_response.json()['id'])
        self.assertEqual(second['status'], 'succeeded')
        self.assertEqual(second['renumbering'], [])
        self.assertEqual(second['ledger'], first['ledger'])

        view = self.client.get(f'/api/labs/{self.lab_id}/design').json()
        self.assertEqual(len(view['generations']), 2)
        self.assertEqual({g['id'] for g in view['generations']}, {first['id'], second['id']})

    def test_two_generations_at_once_are_refused(self):
        first_response = self.client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': self.revision})
        self.assertEqual(first_response.status_code, 200)
        second_response = self.client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': self.revision})
        self.assertEqual(second_response.status_code, 409)
        self.assertIn('already being generated', second_response.json()['detail'])
        poll_generation(self.client, self.lab_id, first_response.json()['id'])

    def test_generation_never_touches_a_device_the_vm_or_docker(self):
        """The engine is a child process; the manager itself opens no socket and calls no VM helper
        while a plan is generated. Patches socket.socket and app.lab_operations.remote to prove it,
        and records every subprocess.Popen argv to prove only `netlab create` is ever spawned."""
        real_popen = subprocess.Popen
        captured = []

        class RecordingPopen(real_popen):
            def __init__(self, argv, *args, **kwargs):
                captured.append(list(argv))
                super().__init__(argv, *args, **kwargs)

        def refuse_socket(*args, **kwargs):
            raise AssertionError('network_design generation must never open a socket')

        def refuse_remote(*args, **kwargs):
            raise AssertionError('network_design generation must never call the VM gateway')

        with patch('socket.socket', side_effect=refuse_socket), \
             patch('app.lab_operations.remote', side_effect=refuse_remote), \
             patch('subprocess.Popen', RecordingPopen):
            record = self.generate()

        self.assertEqual(record['status'], 'succeeded')
        create_calls = [argv for argv in captured if 'create' in argv]
        self.assertEqual(len(create_calls), record['passes'])
        for argv in captured:
            joined = ' '.join(argv)
            self.assertNotIn('docker', joined)
            self.assertNotIn('containerlab', joined)
            self.assertNotIn('ansible-playbook', joined)
            self.assertNotIn('ssh', joined)
            self.assertNotIn('netlab up', joined)


VLAN_TOPOLOGY = '''name: vlan-pair
topology:
  nodes:
    sw: {kind: arista_ceos, image: n24l/ceos:4.35.0F, mgmt-ipv4: 172.20.20.101}
    r2: {kind: arista_ceos, image: n24l/ceos:4.35.0F, mgmt-ipv4: 172.20.20.102}
    h1: {kind: linux, image: ghcr.io/srl-labs/network-multitool:latest, mgmt-ipv4: 172.20.20.105}
    h2: {kind: linux, image: ghcr.io/srl-labs/network-multitool:latest, mgmt-ipv4: 172.20.20.106}
  links:
    - endpoints: ["h1:eth1", "sw:eth1"]
    - endpoints: ["h2:eth1", "sw:eth2"]
    - endpoints: ["sw:eth3", "r2:eth1"]
'''


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class VlanSegmentGenerationTests(unittest.TestCase):
    """Audit 2026-10-03 M-7, against the pinned engine: two hosts on one routed VLAN share its subnet (netlab copies
    the VLAN prefix onto every access link), which is one segment and not a collision; a link prefix that really
    lands on the VLAN subnet is still refused."""
    H1, H2, CORE = 'h1:eth1--sw:eth1', 'h2:eth1--sw:eth2', 'r2:eth1--sw:eth3'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.app.state.network_design.close)
        self.lab_id = add_lab(self.app, name='vlan-pair', definition_yaml=VLAN_TOPOLOGY)

    def intent(self, core=None):
        intent = intent_schema.empty_intent()
        intent['modules'] = ['vlan', 'ospf']
        intent['vlans'] = {'red': {'id': 100, 'mode': 'irb'}}
        intent['links'] = {self.H1: {'vlan': {'access': 'red'}}, self.H2: {'vlan': {'access': 'red'}}}
        if core: intent['links'][self.CORE] = core
        return intent

    def generate(self, intent=None):
        """Saves `intent` and generates it; without one, generates the saved design again."""
        if intent is not None:
            saved = self.client.put(f'/api/labs/{self.lab_id}/design', json={'intent': intent, 'revision': ''})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.revision = saved.json()['intent']['revision']
        response = self.client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': self.revision})
        self.assertEqual(response.status_code, 200, response.text)
        return poll_generation(self.client, self.lab_id, response.json()['id'])

    def test_two_access_links_of_one_routed_vlan_generate_and_regenerate(self):
        first = self.generate(self.intent())
        self.assertEqual(first['status'], 'succeeded', (first.get('message'), first.get('errors')))
        self.assertEqual(first['passes'], 1, 'nothing to fix: the shared VLAN subnet is not a collision')
        self.assertEqual(first['collision_fixes'], {})
        links = first['ledger']['links']
        self.assertEqual(links[self.H1], links[self.H2], 'both hosts are on the VLAN subnet')
        self.assertEqual(links[self.H1]['ipv4'], '172.16.0.0/24')
        self.assertNotEqual(links[self.CORE], links[self.H1])
        second = self.generate()   # now with both VLAN links pinned in the ledger
        self.assertEqual(second['status'], 'succeeded', (second.get('message'), second.get('errors')))
        self.assertEqual(second['ledger'], first['ledger'])
        self.assertEqual(second['renumbering'], [])

    def test_a_link_prefix_on_the_vlan_subnet_is_still_reported(self):
        # The engine gives VLAN red the first /24 of the default lan pool (the test above records it in the ledger).
        record = self.generate(self.intent(core={'prefix': {'ipv4': '172.16.0.0/30'}}))
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['passes'], 1, 'a pin cannot move a VLAN link prefix, so no second pass is tried')
        self.assertIn('VLAN', record['message'])
        joined = ' | '.join(record['errors'])
        self.assertIn(self.CORE, joined)
        self.assertIn('red', joined)


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class GenerationFailureTests(unittest.TestCase):
    """Behaviour 11: an unsupported module blocks every device before the engine runs, and excluding
    every router leaves the adapter with only the host."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.app.state.network_design.close)

    def test_an_unsupported_module_fails_the_generation_before_the_engine_runs(self):
        """EIGRP never generates. Since its retirement (D10.1) a design cannot gain it, so the design is planted as one
        saved before the retirement; Generate refuses it with 409 and queues nothing, and the capability check that
        used to fail the generation still blocks every one of the four kinds before any engine run."""
        lab_id = add_lab(self.app)
        intent = intent_schema.empty_intent()
        intent['modules'] = ['eigrp']
        intent['eigrp'] = {'as': 1}
        revision = plant_design(self.app, lab_id, intent)

        with patch('subprocess.Popen', side_effect=AssertionError('the engine must not run')):
            response = self.client.post(f'/api/labs/{lab_id}/design/generate', json={'revision': revision})
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()['detail']
        self.assertIn('EIGRP', detail['message'])
        self.assertEqual(detail['retired'], ['eigrp'])
        self.assertEqual(self.client.get(f'/api/labs/{lab_id}/design').json()['generations'], [])

        service = self.app.state.network_design
        with self.app.state.store.lock: lab = copy.deepcopy(self.app.state.store.lab(lab_id))
        built = nd.adapter.build(lab['definition_yaml'], lab['nodes'], intent, nd.capabilities.profile_for)
        _, blocking = service.compatibility(intent, built['nodes'])
        for kind in ('arista_ceos', 'juniper_cjunosevolved', 'juniper_vjunosswitch', 'cisco_xrv9k'):
            self.assertTrue(any('eigrp' in e and kind in e for e in blocking), blocking)

    def test_excluding_every_router_leaves_only_the_host_device(self):
        """Observed behaviour: excluding every router node does not raise in the adapter (the lone
        host device keeps the design non-empty); the generation succeeds with only host1 designed
        and every link left out with a note naming the excluded devices."""
        lab_id = add_lab(self.app, name='routers-excluded')
        intent = intent_schema.empty_intent()
        intent['modules'] = ['ospf']
        intent['ospf'] = {'area': '0.0.0.0'}
        intent['nodes'] = {name: {'role': 'exclude'} for name in
                           ('ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k')}
        saved = self.client.put(f'/api/labs/{lab_id}/design', json={'intent': intent, 'revision': ''})
        self.assertEqual(saved.status_code, 200, saved.text)
        revision = saved.json()['intent']['revision']

        response = self.client.post(f'/api/labs/{lab_id}/design/generate', json={'revision': revision})
        self.assertEqual(response.status_code, 200)
        record = poll_generation(self.client, lab_id, response.json()['id'])

        self.assertEqual(record['status'], 'succeeded')
        self.assertEqual(set(record.get('artifacts') or {}), {'host1'})
        for excluded in ('ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k'):
            self.assertFalse(record['nodes'][excluded]['included'])
            self.assertTrue(any(excluded in note for note in record['notes']), record['notes'])


class ReconciliationTests(unittest.TestCase):
    """Behaviour 14: NetworkDesign.__init__ marks a generation still 'running' at startup interrupted,
    exactly like the runner and the restore service do for their own jobs."""

    def test_a_running_generation_is_marked_interrupted_on_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.state['labs'] = [{'id': 'lab1', 'name': 'x',
                                    'network_generations': [{'id': 'g1', 'status': 'running'}]}]
            store.save()
            service = NetworkDesign(store)
            try:
                lab = store.lab('lab1')
                generation = lab['network_generations'][0]
                self.assertEqual(generation['status'], 'interrupted')
                self.assertTrue(generation.get('message'))
            finally:
                service.close()

    def test_a_queued_generation_is_also_marked_interrupted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.state['labs'] = [{'id': 'lab1', 'name': 'x',
                                    'network_generations': [{'id': 'g1', 'status': 'queued'}]}]
            store.save()
            service = NetworkDesign(store)
            try:
                generation = store.lab('lab1')['network_generations'][0]
                self.assertEqual(generation['status'], 'interrupted')
            finally:
                service.close()

    def test_a_finished_generation_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.state['labs'] = [{'id': 'lab1', 'name': 'x',
                                    'network_generations': [{'id': 'g1', 'status': 'succeeded', 'message': 'Plan generated'}]}]
            store.save()
            service = NetworkDesign(store)
            try:
                generation = store.lab('lab1')['network_generations'][0]
                self.assertEqual(generation['status'], 'succeeded')
                self.assertEqual(generation['message'], 'Plan generated')
            finally:
                service.close()


class UnsavedPlanTests(unittest.TestCase):
    """A plan whose finished record cannot be saved is not reported generated: the in-memory record would say
    `succeeded` and move the ledger while the saved one still says `running` (interrupted at the next start)."""

    def test_a_plan_whose_record_cannot_be_saved_fails_and_keeps_the_ledger(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            intent = intent_schema.normalize(valid_intent()); intent['allocations'] = {'node_ids': {'ceos': 7}}
            store.state['labs'] = [{'id': 'a' * 32, 'name': 'x', 'network_design': intent,
                                    'network_generations': [{'id': 'b' * 32, 'lab_id': 'a' * 32, 'status': 'queued', 'intent_revision': intent['revision']}]}]
            store.save()
            service = NetworkDesign(store)
            self.addCleanup(service.close)
            folder = service.root / ('a' * 32) / ('b' * 32); folder.mkdir(parents=True); (folder / 'plan.json').write_text('{}')
            store.lab('a' * 32)['network_generations'][0]['status'] = 'queued'   # the constructor marked it interrupted
            result = dict(status='succeeded', finished='2026-10-03T00:00:00+00:00', message='Plan generated', ledger={'node_ids': {'ceos': 1}},
                          artifacts={'ceos': [{'module': 'ospf', 'size': 1, 'sha256': '0' * 64}]}, errors=[], duration=1.0)
            real_save = store.save

            def full_disk():   # every save that would persist a generated plan fails, like a full disk would
                if any(g.get('status') == 'succeeded' for lab in store.state['labs'] for g in lab.get('network_generations') or []):
                    raise OSError(28, 'No space left on device')
                real_save()
            with patch.object(store, 'save', side_effect=full_disk), patch.object(service, '_generate', return_value=result):
                service.execute('a' * 32, 'b' * 32, {'intent': intent})
            generation = store.lab('a' * 32)['network_generations'][0]
            self.assertEqual(generation['status'], 'failed', generation)
            self.assertIn('could not be saved', generation['message'])
            self.assertNotIn('artifacts', generation)
            self.assertNotIn('ledger', generation)
            self.assertEqual(store.lab('a' * 32)['network_design']['allocations'], {'node_ids': {'ceos': 7}}, 'the ledger is not moved by an unsaved plan')
            self.assertFalse(folder.exists(), 'the files of an unsaved plan are removed')
            self.assertTrue(any(e['action'] == 'design.generated' and e['level'] == 'error' for e in store.events(job_id='b' * 32)))
            self.assertFalse(any('succeeded' in e['message'] for e in store.events(job_id='b' * 32)))
            persisted = json.loads(store.cipher.decrypt(store.path.read_bytes()))
            self.assertEqual(persisted['labs'][0]['network_generations'][0]['status'], 'failed', 'the outcome is saved once the disk takes it')

    def test_a_saved_plan_is_reported_generated(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            intent = intent_schema.normalize(valid_intent())
            store.state['labs'] = [{'id': 'a' * 32, 'name': 'x', 'network_design': intent,
                                    'network_generations': [{'id': 'b' * 32, 'lab_id': 'a' * 32, 'status': 'succeeded'}]}]
            service = NetworkDesign(store)
            self.addCleanup(service.close)
            store.lab('a' * 32)['network_generations'][0]['status'] = 'running'
            result = dict(status='succeeded', finished='2026-10-03T00:00:00+00:00', message='Plan generated', ledger={'node_ids': {'ceos': 1}}, errors=[])
            self.assertEqual(service._finish('a' * 32, 'b' * 32, intent['revision'], result), 'succeeded')
            self.assertEqual(store.lab('a' * 32)['network_design']['allocations'], {'node_ids': {'ceos': 1}})
            persisted = json.loads(store.cipher.decrypt(store.path.read_bytes()))['labs'][0]   # what a restart would read back
            self.assertEqual(persisted['network_generations'][0]['status'], 'succeeded')
            self.assertEqual(persisted['network_design']['allocations'], {'node_ids': {'ceos': 1}}, 'the ledger is saved with the plan')


class GenerationCapUnitTests(unittest.TestCase):
    """Behaviour 15 (unit half): _append_generation never drops a still-running record, even when it
    is the oldest one over the cap."""

    def test_a_running_record_is_never_dropped_even_when_oldest(self):
        with patch.object(nd, 'GENERATION_CAP', 3):
            lab = {'network_generations': [{'id': str(i), 'status': 'succeeded'} for i in range(3)]}
            lab['network_generations'][0]['status'] = 'running'
            dropped = nd._append_generation(lab, {'id': 'new', 'status': 'succeeded'})
        self.assertEqual(dropped, ['1'])
        self.assertEqual([g['id'] for g in lab['network_generations']], ['0', '2', 'new'])

    def test_under_the_cap_nothing_is_dropped(self):
        with patch.object(nd, 'GENERATION_CAP', 5):
            lab = {'network_generations': [{'id': str(i), 'status': 'succeeded'} for i in range(2)]}
            dropped = nd._append_generation(lab, {'id': 'new', 'status': 'succeeded'})
        self.assertEqual(dropped, [])
        self.assertEqual(len(lab['network_generations']), 3)


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class GenerationCapIntegrationTests(unittest.TestCase):
    """Behaviour 15 (integration half): a dropped generation's folder is removed from disk."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.app.state.network_design.close)

    def test_bounded_history_keeps_the_newest_and_removes_the_dropped_folder(self):
        lab_id = add_lab(self.app)
        saved = self.client.put(f'/api/labs/{lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
        revision = saved.json()['intent']['revision']

        with patch.object(nd, 'GENERATION_CAP', 3):
            generation_ids = []
            for _ in range(4):
                response = self.client.post(f'/api/labs/{lab_id}/design/generate', json={'revision': revision})
                self.assertEqual(response.status_code, 200, response.text)
                generation_id = response.json()['id']
                generation_ids.append(generation_id)
                record = poll_generation(self.client, lab_id, generation_id)
                self.assertEqual(record['status'], 'succeeded')

        view = self.client.get(f'/api/labs/{lab_id}/design').json()
        self.assertEqual(len(view['generations']), 3)
        kept_ids = {g['id'] for g in view['generations']}
        self.assertEqual(kept_ids, set(generation_ids[1:]))

        dropped_folder = self.app.state.network_design.root / lab_id / generation_ids[0]
        self.assertFalse(dropped_folder.exists())
        kept_folder = self.app.state.network_design.root / lab_id / generation_ids[-1]
        self.assertTrue(kept_folder.exists())


class ExportImportTests(unittest.TestCase):
    """Behaviour 16: exporting a design as YAML and importing it back, including refusals."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.network_design.close)

    def test_export_then_import_round_trips_the_design(self):
        lab_id = add_lab(self.app)
        self.client.put(f'/api/labs/{lab_id}/design', json={'intent': valid_intent(), 'revision': ''})

        export = self.client.get(f'/api/labs/{lab_id}/design/export')
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export.headers['content-type'], 'application/yaml')
        self.assertIn("filename*=UTF-8''restore-square.network-intent.yml", export.headers['content-disposition'])
        self.assertIn(b'containerlab_node_manager', export.content)
        self.assertIn(b'modules', export.content)

        other_lab = add_lab(self.app, name='second-lab')
        imported = self.client.post(f'/api/labs/{other_lab}/design/import',
                                     files={'intent': ('x.yml', export.content, 'application/yaml')})
        self.assertEqual(imported.status_code, 200)
        body = imported.json()
        self.assertTrue(body['imported'])
        self.assertEqual(body['problems'], [])
        self.assertEqual(body['intent']['modules'], ['ospf', 'bgp'])

    def test_export_without_a_design_is_404(self):
        lab_id = add_lab(self.app)
        response = self.client.get(f'/api/labs/{lab_id}/design/export')
        self.assertEqual(response.status_code, 404)

    def test_import_of_an_invalid_document_reports_problems_without_saving(self):
        lab_id = add_lab(self.app)
        bad = b"schema: 1\nmodules: ['not-a-real-module']\n"
        response = self.client.post(f'/api/labs/{lab_id}/design/import',
                                     files={'intent': ('bad.yml', bad, 'application/yaml')})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertFalse(body['imported'])
        self.assertTrue(body['problems'])
        self.assertIsNone(self.client.get(f'/api/labs/{lab_id}/design').json()['intent'])

    def test_import_over_the_size_limit_is_refused(self):
        lab_id = add_lab(self.app)
        oversized = b"schema: 1\nlabel: '" + b'x' * (600 * 1024) + b"'\n"
        response = self.client.post(f'/api/labs/{lab_id}/design/import',
                                     files={'intent': ('big.yml', oversized, 'application/yaml')})
        self.assertEqual(response.status_code, 400)
        self.assertIn('512 KiB', response.json()['detail'])

    def test_import_with_yaml_anchors_is_refused(self):
        lab_id = add_lab(self.app)
        anchored = b"defaults: &d\n  x: 1\nschema: 1\nlabel: *d\n"
        response = self.client.post(f'/api/labs/{lab_id}/design/import',
                                     files={'intent': ('anchor.yml', anchored, 'application/yaml')})
        self.assertEqual(response.status_code, 400)


class PublicSerializerTests(unittest.TestCase):
    """Behaviour 17: public_design() and public_generation(), pure functions over a lab record."""

    def test_public_design_is_none_without_intent_or_generations(self):
        self.assertIsNone(public_design({}))
        self.assertIsNone(public_design({'network_design': None, 'network_generations': []}))

    def test_public_design_with_a_generation_but_no_intent(self):
        lab = {'network_generations': [{'id': 'g1', 'status': 'succeeded', 'intent_revision': 'r1',
                                        'created': 'c', 'finished': 'f', 'message': 'm'}]}
        summary = public_design(lab)
        self.assertIsNotNone(summary)
        self.assertFalse(summary['present'])
        self.assertEqual(summary['generation']['id'], 'g1')
        self.assertNotIn('stale', summary)  # only computed when both an intent and a newest generation exist

    def test_public_design_marks_stale_when_the_newest_generation_used_an_older_revision(self):
        lab = {'network_design': {'revision': 'r2', 'modules': []},
               'network_generations': [{'id': 'g1', 'status': 'succeeded', 'intent_revision': 'r1',
                                        'created': 'c', 'finished': 'f', 'message': 'm'}]}
        summary = public_design(lab)
        self.assertTrue(summary['present'])
        self.assertTrue(summary['stale'])

    def test_public_design_is_not_stale_when_revisions_match(self):
        lab = {'network_design': {'revision': 'r1', 'modules': []},
               'network_generations': [{'id': 'g1', 'status': 'succeeded', 'intent_revision': 'r1',
                                        'created': 'c', 'finished': 'f', 'message': 'm'}]}
        self.assertFalse(public_design(lab)['stale'])

    def test_public_design_generating_is_true_while_a_generation_is_busy(self):
        lab = {'network_design': {'revision': 'r1', 'modules': []},
               'network_generations': [{'id': 'g1', 'status': 'running', 'intent_revision': 'r1',
                                        'created': 'c', 'finished': '', 'message': 'm'}]}
        self.assertTrue(public_design(lab)['generating'])

    def test_public_generation_strips_internal_fields(self):
        generation = {'id': 'g1', 'lab_id': 'lab1', 'status': 'succeeded', 'folder': '/data/secret',
                      'stderr_tail': 'raw engine output', 'workdir': '/tmp/x'}
        public = public_generation(generation)
        self.assertEqual(public['id'], 'g1')
        self.assertNotIn('folder', public)
        self.assertNotIn('stderr_tail', public)
        self.assertNotIn('workdir', public)


class RequestedFeaturesTests(unittest.TestCase):
    """Behaviour 18: requested_features() derives the capability ids a design asks for."""

    def test_dual_stack_ospf_and_bgp(self):
        intent = {'modules': ['ospf', 'bgp'], 'families': {'ipv4': True, 'ipv6': True}}
        self.assertEqual(requested_features(intent), {'ipv4', 'ipv6', 'ospfv2', 'ospfv3', 'bgp'})

    def test_ipv4_only_has_no_ospfv3(self):
        intent = {'modules': ['ospf'], 'families': {'ipv4': True, 'ipv6': False}}
        self.assertEqual(requested_features(intent), {'ipv4', 'ospfv2'})

    def test_gateway_vrrp_requests_vrrp_not_anycast(self):
        intent = {'modules': ['gateway'], 'gateway': {'protocol': 'vrrp'}, 'families': {'ipv4': True, 'ipv6': True}}
        features = requested_features(intent)
        self.assertIn('vrrp', features)
        self.assertNotIn('anycast_gateway', features)

    def test_gateway_default_is_anycast(self):
        intent = {'modules': ['gateway'], 'families': {'ipv4': True, 'ipv6': True}}
        features = requested_features(intent)
        self.assertIn('anycast_gateway', features)
        self.assertNotIn('vrrp', features)

    def test_mpls_vpn_requests_l3vpn_and_mpls_ldp(self):
        intent = {'modules': ['mpls'], 'mpls': {'vpn': True}, 'families': {'ipv4': True, 'ipv6': True}}
        features = requested_features(intent)
        self.assertIn('l3vpn', features)
        self.assertIn('mpls_ldp', features)

    def test_routing_prefix_requests_prefix_list(self):
        intent = {'modules': ['routing'], 'routing': {'prefix': {'p1': {}}}, 'families': {'ipv4': True, 'ipv6': True}}
        self.assertIn('prefix_list', requested_features(intent))

    def test_module_import_requests_redistribution(self):
        intent = {'modules': ['ospf'], 'ospf': {'import': ['bgp']}, 'families': {'ipv4': True, 'ipv6': True}}
        self.assertIn('redistribution', requested_features(intent))

    def test_lag_lacp_requests_lacp(self):
        intent = {'modules': ['lag'], 'lag': {'lacp': 'fast'}, 'families': {'ipv4': True, 'ipv6': True}}
        features = requested_features(intent)
        self.assertIn('lacp', features)
        self.assertIn('lag', features)

    def test_lag_off_does_not_request_lacp(self):
        intent = {'modules': ['lag'], 'lag': {'lacp': 'off'}, 'families': {'ipv4': True, 'ipv6': True}}
        self.assertNotIn('lacp', requested_features(intent))



# --- regressions from the risk review of 1.30.43 --------------------------------------------------------------

GROWN_TOPOLOGY = TOPOLOGY.replace('  links:\n', '  links:\n    - endpoints: ["ceos:eth4", "xrv9k:Gi0/0/0/2"]\n    - endpoints: ["ceos:eth5", "xrv9k:Gi0/0/0/3"]\n')


def save_and_generate(client, lab_id, intent, revision=''):
    saved = client.put(f'/api/labs/{lab_id}/design', json={'intent': intent, 'revision': revision})
    assert saved.status_code == 200, saved.text
    revision = saved.json()['intent']['revision']
    queued = client.post(f'/api/labs/{lab_id}/design/generate', json={'revision': revision})
    assert queued.status_code == 200, queued.text
    return revision, poll_generation(client, lab_id, queued.json()['id'])


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class ReviewRegressionGenerationTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='design-review-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = create_app(self.tmp)
        self.lab_id = add_lab(self.app)

    def test_two_links_added_to_a_pinned_design_keep_every_pin_and_get_free_prefixes(self):
        with TestClient(self.app) as client:
            revision, first = save_and_generate(client, self.lab_id, valid_intent())
            self.assertEqual(first['status'], 'succeeded', first)
            with self.app.state.store.lock:
                lab = self.app.state.store.lab(self.lab_id)
                lab['definition_yaml'] = GROWN_TOPOLOGY
                lab['nodes'] = parse_definition(GROWN_TOPOLOGY.encode())['nodes']
                self.app.state.store.save()
            queued = client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': revision})
            second = poll_generation(client, self.lab_id, queued.json()['id'])
            self.assertEqual(second['status'], 'succeeded', second)
            self.assertEqual(second['renumbering'], [])
            self.assertEqual(second['passes'], 2)
            for key, prefix in first['ledger']['links'].items():
                self.assertEqual(second['ledger']['links'][key], prefix, key)
            new_keys = set(second['ledger']['links']) - set(first['ledger']['links'])
            self.assertEqual(len(new_keys), 2)
            used = [p['ipv4'] for p in second['ledger']['links'].values()]
            self.assertEqual(len(used), len(set(used)), 'no two links share an IPv4 prefix')

    def test_an_explicit_link_prefix_counts_as_pinned_for_the_collision_check(self):
        with TestClient(self.app) as client:
            first_key = sorted(intent_schema.link_key(pair) for pair in (
                [('ceos', 'eth1'), ('cjunosevolved', 'et-0/0/0')], [('cjunosevolved', 'et-0/0/1'), ('vjunos-switch', 'ge-0/0/0')]))[0]
            intent = valid_intent()
            # The second link would naturally receive 10.1.0.2/31; give it to the first link explicitly.
            intent['links'] = {first_key: {'prefix': {'ipv4': '10.1.0.2/31', 'ipv6': '2001:db8:1:1::/64'}}}
            revision, record = save_and_generate(client, self.lab_id, intent)
            self.assertEqual(record['status'], 'succeeded', record)
            self.assertEqual(record['ledger']['links'][first_key]['ipv4'], '10.1.0.2/31')
            used = [p['ipv4'] for p in record['ledger']['links'].values()]
            self.assertEqual(len(used), len(set(used)))

    def test_a_device_level_module_the_kind_cannot_do_blocks_before_the_engine_runs(self):
        """A device's own module list is checked too: EIGRP on one device of an old design (planted, since a design
        cannot gain EIGRP any more) is refused at Generate, by path, before the engine; and the capability check
        still names that device."""
        with TestClient(self.app) as client:
            intent = valid_intent()
            intent['nodes'] = {'ceos': {'modules': ['eigrp'], 'eigrp': {'as': 1}}}
            revision = plant_design(self.app, self.lab_id, intent)
            with patch('subprocess.Popen', side_effect=AssertionError('the engine must not run')):
                response = client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': revision})
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn('nodes.ceos.modules', [p['path'] for p in response.json()['detail']['problems']])
            self.assertEqual(client.get(f'/api/labs/{self.lab_id}/design').json()['generations'], [])
            with self.app.state.store.lock: lab = copy.deepcopy(self.app.state.store.lab(self.lab_id))
            built = nd.adapter.build(lab['definition_yaml'], lab['nodes'], intent, nd.capabilities.profile_for)
            _, blocking = self.app.state.network_design.compatibility(intent, built['nodes'])
            self.assertTrue(any('ceos: eigrp' in e for e in blocking), blocking)

    def test_a_missing_prerequisite_blocks_before_the_engine_runs(self):
        """Segment routing without an IGP (sr_mpls needs IS-IS or OSPF). This used EVPN without BGP before EVPN was
        made unavailable (D10.3); the claim, a missing prerequisite fails the plan before the engine runs, is the same."""
        with TestClient(self.app) as client:
            intent = valid_intent()
            intent['modules'] = ['sr']
            intent.pop('ospf'); intent.pop('bgp')
            with patch('subprocess.Popen', side_effect=AssertionError('the engine must not run')):
                revision, record = save_and_generate(client, self.lab_id, intent)
            self.assertEqual(record['status'], 'failed')
            self.assertTrue(any('prerequisite' in e for e in record['errors']), record['errors'])

    def test_renumbering_is_reported_against_the_previous_plan_not_the_cleared_ledger(self):
        with TestClient(self.app) as client:
            revision, first = save_and_generate(client, self.lab_id, valid_intent())
            self.assertEqual(first['status'], 'succeeded')
            intent = client.get(f'/api/labs/{self.lab_id}/design').json()['intent']
            intent['addressing']['loopback'] = {'ipv4': '10.254.0.0/24', 'ipv6': '2001:db8:fe::/48'}
            saved = client.put(f'/api/labs/{self.lab_id}/design', json={'intent': intent, 'revision': revision})
            revision = saved.json()['intent']['revision']
            self.assertEqual(client.post(f'/api/labs/{self.lab_id}/design/renumber', json={'revision': revision}).status_code, 200)
            queued = client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': revision})
            second = poll_generation(client, self.lab_id, queued.json()['id'])
            self.assertEqual(second['status'], 'succeeded', second)
            changed = {(c['kind'], c['name']) for c in second['renumbering']}
            self.assertIn(('loopbacks', 'ceos'), changed)
            self.assertTrue(client.get(f'/api/labs/{self.lab_id}/design').json()['summary']['stale'] is False)

    def test_generated_files_are_private_to_the_manager_user(self):
        import os, stat
        with TestClient(self.app) as client:
            revision, record = save_and_generate(client, self.lab_id, valid_intent())
            self.assertEqual(record['status'], 'succeeded')
            root = os.path.join(self.tmp, 'network-design')
            for dirpath, dirnames, filenames in os.walk(root):
                self.assertEqual(stat.S_IMODE(os.stat(dirpath).st_mode), 0o700, dirpath)
                for name in filenames:
                    self.assertEqual(stat.S_IMODE(os.stat(os.path.join(dirpath, name)).st_mode), 0o600, name)

    def test_remove_lab_and_start_fresh_take_the_generated_plans_along(self):
        import os
        with TestClient(self.app) as client:
            revision, record = save_and_generate(client, self.lab_id, valid_intent())
            folder = os.path.join(self.tmp, 'network-design', self.lab_id)
            self.assertTrue(os.path.isdir(folder))
            removed = client.request('DELETE', f'/api/labs/{self.lab_id}', json={'name': 'restore-square'})
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertFalse(os.path.exists(folder))
            other = add_lab(self.app, name='other')
            revision, record = save_and_generate(client, other, valid_intent())
            self.assertTrue(os.path.isdir(os.path.join(self.tmp, 'network-design', other)))
            reset = client.post('/api/manager/reset', json={'confirmation': 'RESET'})
            self.assertEqual(reset.status_code, 200, reset.text)
            self.assertFalse(os.path.exists(os.path.join(self.tmp, 'network-design', other)))


class ReviewRegressionUnitTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='design-review-unit-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = create_app(self.tmp)
        self.lab_id = add_lab(self.app)

    def test_import_requires_the_current_revision_and_keeps_the_server_ledger(self):
        with TestClient(self.app) as client:
            saved = client.put(f'/api/labs/{self.lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
            revision = saved.json()['intent']['revision']
            with self.app.state.store.lock:
                self.app.state.store.lab(self.lab_id)['network_design']['allocations'] = {'node_ids': {'ceos': 7}}
                self.app.state.store.save()
            document = dict(valid_intent(), allocations={'node_ids': {'ceos': 1}})
            body = ('---\n' + __import__('yaml').safe_dump(document)).encode()
            stale = client.post(f'/api/labs/{self.lab_id}/design/import', files={'intent': ('x.yml', body, 'application/yaml')})
            self.assertEqual(stale.status_code, 409, stale.text)
            ok = client.post(f'/api/labs/{self.lab_id}/design/import', files={'intent': ('x.yml', body, 'application/yaml')}, data={'revision': revision})
            self.assertEqual(ok.status_code, 200, ok.text)
            self.assertTrue(ok.json()['imported'])
            self.assertEqual(ok.json()['intent']['allocations'], {'node_ids': {'ceos': 7}}, 'the uploaded ledger is ignored')

    def test_scrub_removes_the_data_and_work_paths_from_engine_lines(self):
        service = self.app.state.network_design
        lines = service._scrub(['Cannot read YAML from ' + str(service.work) + '/abc/../../x.yml', 'plain ' + str(service.store.root)])
        self.assertEqual(lines, ['Cannot read YAML from <work>/abc/../../x.yml', 'plain <data>'])

    def test_effective_modules_and_requested_features_follow_device_lists_and_link_settings(self):
        intent = dict(valid_intent(), nodes={'ceos': {'modules': ['isis']}, 'host1': {}}, links={'k': {'endpoints': {'ceos': {'ospf': {'passive': True}}}}, 'routing': {}})
        self.assertEqual(nd.effective_modules(intent, 'ceos', {'role': 'router'}), {'isis'}, "a device's own list replaces the design's")
        self.assertEqual(nd.effective_modules(intent, 'host1', {'role': 'host'}), set())
        self.assertEqual(nd.effective_modules(intent, 'xrv9k', {'role': 'router'}), {'ospf', 'bgp'})
        intent2 = dict(valid_intent(), modules=['ospf', 'bgp', 'routing'], links={'k': {'routing': {'static': [{'ipv4': '0.0.0.0/0'}]}}})
        self.assertIn('static_routes', requested_features(intent2))
        self.assertNotIn('static_routes', requested_features(intent2, modules={'ospf'}))




@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class SecondPassRegressionGenerationTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='design-review2-')
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.app = create_app(self.tmp)
        self.lab_id = add_lab(self.app)

    def _held_generation(self, client):
        """Start a generation and hold the engine call open until the returned event is set."""
        import threading
        hold = threading.Event(); started = threading.Event()
        original = self.app.state.network_design._run_engine
        def slow(topology, stop):
            started.set(); hold.wait(30)
            return original(topology, stop)
        patcher = patch.object(self.app.state.network_design, '_run_engine', slow); patcher.start(); self.addCleanup(patcher.stop)
        saved = client.put(f'/api/labs/{self.lab_id}/design', json={'intent': valid_intent(), 'revision': ''})
        revision = saved.json()['intent']['revision']
        queued = client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': revision})
        self.assertEqual(queued.status_code, 200, queued.text)
        self.assertTrue(started.wait(20), 'the generation did not start')
        return hold, queued.json()['id']

    def test_remove_lab_and_start_fresh_wait_for_a_running_generation(self):
        import os
        with TestClient(self.app) as client:
            hold, generation_id = self._held_generation(client)
            removed = client.request('DELETE', f'/api/labs/{self.lab_id}', json={'name': 'restore-square'})
            self.assertEqual(removed.status_code, 409, removed.text)
            self.assertIn('plan being generated', removed.json()['detail'])
            reset = client.post('/api/manager/reset', json={'confirmation': 'RESET'})
            self.assertEqual(reset.status_code, 409, reset.text)
            hold.set()
            record = poll_generation(client, self.lab_id, generation_id)
            self.assertEqual(record['status'], 'succeeded', record)
            removed = client.request('DELETE', f'/api/labs/{self.lab_id}', json={'name': 'restore-square'})
            self.assertEqual(removed.status_code, 200, removed.text)
            self.assertFalse(os.path.exists(os.path.join(self.tmp, 'network-design', self.lab_id)))

    def test_a_lab_removed_from_the_store_while_its_plan_runs_leaves_no_files(self):
        import os
        with TestClient(self.app) as client:
            hold, generation_id = self._held_generation(client)
            with self.app.state.store.lock:   # the store-level removal the route refuses: the record must still clean up
                self.app.state.store.state['labs'] = [l for l in self.app.state.store.state['labs'] if l['id'] != self.lab_id]
                self.app.state.store.save()
            hold.set()
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline and self.app.state.network_design.active: time.sleep(0.2)
            self.assertFalse(self.app.state.network_design.active)
            self.assertFalse(os.path.exists(os.path.join(self.tmp, 'network-design', self.lab_id)))

    def test_stale_is_reported_after_a_renumber_until_the_next_plan(self):
        with TestClient(self.app) as client:
            revision, first = save_and_generate(client, self.lab_id, valid_intent())
            self.assertEqual(first['status'], 'succeeded')
            self.assertFalse(client.get(f'/api/labs/{self.lab_id}/design').json()['summary']['stale'])
            self.assertEqual(client.post(f'/api/labs/{self.lab_id}/design/renumber', json={'revision': revision}).status_code, 200)
            self.assertTrue(client.get(f'/api/labs/{self.lab_id}/design').json()['summary']['stale'])
            queued = client.post(f'/api/labs/{self.lab_id}/design/generate', json={'revision': revision})
            second = poll_generation(client, self.lab_id, queued.json()['id'])
            self.assertEqual(second['status'], 'succeeded')
            self.assertFalse(client.get(f'/api/labs/{self.lab_id}/design').json()['summary']['stale'])


class SecondPassRegressionUnitTests(unittest.TestCase):

    def test_every_value_of_a_setting_counts_and_features_are_scoped_to_the_device(self):
        intent = dict(valid_intent(), modules=['ospf', 'bgp', 'gateway', 'lag', 'routing'],
                      links={'ceos:eth1--cjunosevolved:et-0/0/0': {'gateway': {'protocol': 'vrrp'}, 'lag': {'lacp': 'fast'}},
                             'vjunos-switch:ge-0/0/1--xrv9k:Gi0/0/0/0': {'gateway': {'protocol': 'anycast'}, 'lag': {'lacp': 'off'}}},
                      nodes={'ceos': {'routing': {'static': [{'ipv4': '10.9.0.0/24', 'nexthop': {'discard': True}}]}}})
        everywhere = requested_features(intent)
        self.assertTrue({'vrrp', 'anycast_gateway', 'lacp', 'static_routes'} <= everywhere, everywhere)
        ceos = requested_features(intent, node='ceos')
        self.assertTrue({'vrrp', 'lacp', 'static_routes'} <= ceos, ceos)
        self.assertNotIn('anycast_gateway', ceos)
        xrv9k = requested_features(intent, node='xrv9k')
        self.assertIn('anycast_gateway', xrv9k)
        self.assertNotIn('static_routes', xrv9k)
        self.assertNotIn('vrrp', xrv9k)

if __name__ == '__main__':
    unittest.main()
