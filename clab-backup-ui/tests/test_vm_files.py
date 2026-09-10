import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.discovery import parse_snapshot
from app.store import Store
from app.vm_files import PROTOCOL, decode_bundle
import test_discovery as discovery_tests
from test_discovery import YAML, response
import test_discovery_ssh as ssh_tests

INVENTORY = b'''all:
  vars:
    ansible_user: fixture-user
    ansible_password: fixture-device-secret
  hosts:
    clab-training-r1:
      ansible_host: 172.20.20.2
    clab-training-r2:
      ansible_host: 172.20.20.3
'''


def envelope(definition=YAML, annotations=None, inventory=INVENTORY, topology=None):
    files = {}
    for kind, raw in dict(definition=definition, annotations=annotations, inventory=inventory, topology=topology).items():
        if raw is not None:
            files[kind] = dict(path='/srv/labs/training/' + kind, sha256=hashlib.sha256(raw).hexdigest(),
                               content=base64.b64encode(raw).decode())
    return dict(protocol=PROTOCOL, inspect=json.loads(response()), sources={'training': {'files': files}})


class VMFilesTests(unittest.TestCase):
    setUp = discovery_tests.DiscoveryTests.setUp
    tearDown = discovery_tests.DiscoveryTests.tearDown
    host = discovery_tests.DiscoveryTests.host
    register = discovery_tests.DiscoveryTests.register

    def poll(self, value=None):
        value = envelope() if value is None else value
        with patch('app.discovery.inspect_host', return_value=(parse_snapshot(json.dumps(value).encode()), 'SHA256:fixture')):
            return self.service.refresh()

    def sync(self, lab, value):
        with patch('app.discovery.inspect_host', return_value=(parse_snapshot(json.dumps(value).encode()), 'SHA256:fixture')):
            return self.client.post('/api/labs/' + lab['id'] + '/sync', headers=self.auth, json={})

    def test_auto_import_and_no_secret_publication(self):
        self.host(); result = self.poll()
        self.assertTrue(result['file_import_supported'])
        lab = self.store.state['labs'][0]
        self.assertEqual(lab['name'], 'training')
        self.assertEqual(lab['nodes'][0]['username'], 'fixture-user')
        self.assertEqual(lab['nodes'][0]['password'], 'fixture-device-secret')
        self.assertEqual(lab['nodes'][0]['address'], '172.20.20.2')
        self.assertEqual(len(lab['drawing']['links']), 1)
        self.assertEqual(lab['vm_source']['status'], 'Up to date')
        public = self.client.get('/api/state', headers=self.auth).text
        for secret in ('fixture-device-secret', 'definition_yaml', 'content', 'host-secret'):
            self.assertNotIn(secret, public)
        disk = Store(self.tmp.name)
        self.assertEqual(disk.lab(lab['id'])['nodes'][0]['password'], 'fixture-device-secret')
        self.assertNotIn(b'fixture-device-secret', (Path(self.tmp.name) / 'state.enc').read_bytes())
        self.assertNotIn('fixture-device-secret', (Path(self.tmp.name) / 'events.jsonl').read_text())

    def test_change_is_pending_then_sync_retains_settings_history_and_identity(self):
        self.host(); self.poll(); lab = self.store.state['labs'][0]
        lab['profiles'] = [dict(id='p', label='saved', platform='cisco_xrv9k', username='custom', auth='password', password='saved-secret')]
        lab['nodes'][0].update(name='historical-r1', profile_id='p', endpoint_mode='manual', address='10.1.1.1', port=2022,
                               username='saved-user', password='saved-password', enabled=False)
        lab.update(interval=5, next_run=123)
        self.store.state['jobs'] = [dict(id='past', lab_id=lab['id'], nodes=[], status='succeeded')]
        value = envelope(YAML.replace(b'  links:', b'    r3:\n      kind: arista_ceos\n  links:'))
        self.poll(value)
        self.assertEqual(len(lab['nodes']), 2)
        self.assertEqual(lab['vm_source']['status'], 'Updates available')
        result = self.sync(lab, value)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(len(lab['nodes']), 3)
        node = lab['nodes'][0]
        self.assertEqual((node['name'], node['address'], node['port']), ('historical-r1', '10.1.1.1', 2022))
        self.assertEqual((node['profile_id'], node['password'], node['enabled']), ('p', 'saved-password', False))
        self.assertEqual(lab['profiles'][0]['password'], 'saved-secret')
        self.assertEqual(lab['next_run'], 123)
        self.assertEqual(self.store.state['jobs'][0]['id'], 'past')
        self.assertEqual(lab['vm_source']['status'], 'Up to date')

    def test_invalid_optional_file_blocks_atomic_sync(self):
        self.host(); self.poll(); lab = self.store.state['labs'][0]
        original = copy.deepcopy(lab)
        value = envelope(YAML.replace(b'r2:', b'r3:'), annotations=b'{bad json')
        result = self.sync(lab, value)
        self.assertEqual(result.status_code, 409)
        for key in ('nodes', 'drawing', 'definition_yaml', 'profiles'):
            self.assertEqual(lab[key], original[key])
        self.assertEqual(lab['vm_source']['status'], 'Files unavailable')

    def test_missing_files_and_removed_deployment_retain_saved_lab(self):
        self.host(); self.poll(); lab = self.store.state['labs'][0]
        self.poll(envelope(definition=None))
        self.assertEqual(len(lab['nodes']), 2)
        self.assertFalse(lab['vm_source']['can_sync'])
        self.poll(dict(protocol=PROTOCOL, inspect={}, sources={}))
        self.assertEqual(len(self.store.state['labs']), 1)
        self.assertEqual(lab['vm_source']['status'], 'Files unavailable')
        self.assertIn('fixture-device-secret', json.dumps(lab))

    def test_existing_workspace_requires_explicit_sync_and_keeps_map_when_annotations_missing(self):
        public = self.register(); lab = self.store.lab(public['id'])
        lab['drawing']['custom'] = 'retained'
        lab['nodes'][0]['username'] = 'manual'
        self.host(); self.poll()
        self.assertEqual(len(self.store.state['labs']), 1)
        self.assertEqual(lab['vm_source']['status'], 'Updates available')
        self.assertEqual(lab['nodes'][0]['username'], 'manual')
        self.assertEqual(self.sync(lab, envelope()).status_code, 200)
        self.assertEqual(lab['drawing']['custom'], 'retained')

    def test_annotation_changes_replace_map_only_after_sync(self):
        ann = json.dumps({'nodeAnnotations': [dict(id='r1', position={'x': 77, 'y': 88})]}).encode()
        self.host(); self.poll(envelope(annotations=ann)); lab = self.store.state['labs'][0]
        ann2 = ann.replace(b'77', b'99')
        self.poll(envelope(annotations=ann2))
        self.assertEqual(lab['drawing']['nodes'][0]['x'], 77)
        self.assertEqual(self.sync(lab, envelope(annotations=ann2)).status_code, 200)
        self.assertEqual(lab['drawing']['nodes'][0]['x'], 99)

    def test_mismatched_inventory_does_not_import_other_lab_credentials(self):
        self.host(); result = self.poll(envelope(inventory=INVENTORY.replace(b'clab-training-', b'clab-wrong-')))
        self.assertEqual(self.store.state['labs'], [])
        self.assertIn('training', result['file_errors'])
        self.assertNotIn('fixture-device-secret', json.dumps(result))

    def test_mismatched_export_and_bad_hash_rejected_per_lab(self):
        self.host()
        self.poll(envelope(topology=b'{"nodes":{"wrong":{"shortname":"wrong"}}}'))
        self.assertEqual(self.store.state['labs'], [])
        bad = envelope(); bad['sources']['training']['files']['definition']['sha256'] = '0' * 64
        self.poll(bad)
        self.assertEqual(self.store.state['labs'], [])
        self.assertTrue(self.service.public()['connected'])

    def test_legacy_helper_and_legacy_workspace_are_retained(self):
        self.host(); self.poll(json.loads(response()))
        self.assertFalse(self.service.public()['file_import_supported'])
        self.assertEqual(self.store.state['labs'], [])
        public = self.register(); lab = self.store.lab(public['id']); lab.pop('deployment_name')
        self.poll()
        self.assertEqual(len(self.store.state['labs']), 1)
        self.assertNotIn('deployment_name', lab)
        self.assertIn('Link deployment', self.service.public()['file_errors']['training'])

    def test_offline_sync_refused_and_unauthenticated_sync_refused(self):
        self.host(); self.poll(); lab = self.store.state['labs'][0]
        with patch('app.discovery.inspect_host', side_effect=OSError('secret')):
            result = self.client.post('/api/labs/' + lab['id'] + '/sync', headers=self.auth, json={})
        self.assertEqual(result.status_code, 409)
        self.assertNotIn('secret', result.text)
        self.assertEqual(self.client.post('/api/labs/' + lab['id'] + '/sync', json={}).status_code, 401)

    def test_saved_display_name_still_binds_map_by_definition_identity(self):
        self.host(); self.poll(); lab = self.store.state['labs'][0]
        lab['nodes'][0].update(name='historic-container-name', short_name='my-router')
        self.assertEqual(self.sync(lab, envelope()).status_code, 200)
        drawing = self.client.get('/api/labs/' + lab['id'] + '/topology', headers=self.auth).json()
        mapped = next(n for n in drawing['nodes'] if n['alias'] == 'r1')
        self.assertEqual(mapped['inventory_name'], 'historic-container-name')

    def test_custom_inventory_port_stays_manual(self):
        self.host(); self.poll(envelope(inventory=INVENTORY.replace(b'ansible_host: 172.20.20.2', b'ansible_host: 10.0.0.1\n      ansible_port: 2022')))
        node = self.store.state['labs'][0]['nodes'][0]
        self.assertEqual((node['address'], node['port'], node['endpoint_mode']), ('10.0.0.1', 2022, 'manual'))

    def test_real_ssh_transports_file_bundle(self):
        host, server, thread = ssh_tests.SSHDiscoveryTests().serve(data=json.dumps(envelope()).encode())
        try:
            from app.discovery import inspect_host
            labs, fingerprint = inspect_host(host)
            bundle = decode_bundle(labs.sources['training'])
            self.assertEqual(bundle['files']['definition'], YAML)
            self.assertEqual(labs['training'][0]['address'], '172.20.20.2')
        finally: thread.join(2)


spec = importlib.util.spec_from_file_location('file_helper', Path(__file__).resolve().parents[2] / 'deploy/clab_manager_files.py')
helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)


class HostHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.definition = self.root / 'training.clab.yaml'; self.definition.write_bytes(YAML)
        self.labdir = self.root / 'custom-generated'; self.labdir.mkdir()
        (self.labdir / 'ansible-inventory.yml').write_bytes(INVENTORY)
        Path(str(self.definition) + '.annotations.json').write_text('{"nodeAnnotations":[]}')
        self.inspection = json.loads(response())
        for row in self.inspection['training']:
            row.update(absLabPath=str(self.definition), container_id='ab' * 32)
        self.labels = {'containerlab': 'training', 'clab-topo-file': str(self.definition),
                       'clab-node-lab-dir': str(self.labdir / 'r1'), 'clab-node-name': 'r1'}

    def tearDown(self): self.tmp.cleanup()

    def collect(self, reader=helper.read_regular):
        return helper.collect(self.inspection, lambda ident: self.labels, reader=reader)['sources']['training']

    def test_reads_original_and_custom_generated_directory_only(self):
        source = self.collect()
        self.assertEqual(set(source['files']), {'definition', 'annotations', 'inventory'})
        self.assertEqual(base64.b64decode(source['files']['inventory']['content']), INVENTORY)
        self.assertTrue(source['warnings'][0].startswith('topology:'))
        self.assertNotIn('fixture-device-secret', json.dumps(source))

    def test_conflicting_path_metadata_and_non_yaml_refused(self):
        self.labels['clab-topo-file'] = '/etc/passwd'
        self.assertEqual(self.collect()['files'], {})
        self.inspection['training'][0]['absLabPath'] = '/etc/passwd'
        self.assertEqual(self.collect()['files'], {})

    def test_file_change_updates_digest_and_oversize_is_bounded(self):
        before = self.collect()['files']['definition']['sha256']
        self.definition.write_bytes(YAML + b'\n# updated')
        self.assertNotEqual(self.collect()['files']['definition']['sha256'], before)
        self.definition.write_bytes(b'x' * (helper.FILE_LIMIT + 1))
        self.assertNotIn('definition', self.collect()['files'])

    @unittest.skipIf(os.name == 'nt', 'Linux openat/O_NOFOLLOW requires Linux')
    def test_symlink_file_and_symlink_parent_refused(self):
        secret = self.root / 'secret'; secret.write_text('secret')
        self.definition.unlink(); self.definition.symlink_to(secret)
        self.assertNotIn('definition', self.collect()['files'])
        linked = self.root / 'linked'; linked.symlink_to(self.labdir, target_is_directory=True)
        with self.assertRaises(OSError): helper.read_regular(linked / 'ansible-inventory.yml')

    def test_total_budget_and_inspection_remain_separate(self):
        with patch.object(helper, 'TOTAL_LIMIT', 1):
            source = self.collect()
        self.assertEqual(source['files'], {})
        self.assertEqual(len(source['warnings']), 4)


if __name__ == '__main__': unittest.main()
