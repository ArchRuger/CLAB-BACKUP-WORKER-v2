"""Junos kind identity, onboarding and snapshot regression coverage (no live NOS)."""
import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

from fastapi.testclient import TestClient

from app.discovery import parse_definition
from app.git_progress import captured_snapshot, decoded_snapshot
from app.inventory import PLATFORMS, parse_inventory
from app.main import create_app
from app.runner import credential_source, effective_credentials, filename, make_inventory, readiness
from app.topology import session_xml
from app.vm_files import prepare_lab


KINDS = {
    'juniper_vqfx': ('juniper_vqfx', 'vr-vqfx', 'vqfx'),
    'juniper_vjunosswitch': ('juniper_vjunosswitch', 'vr-vjunosswitch', 'vjunosswitch'),
    'juniper_vjunosrouter': ('juniper_vjunosrouter', 'vr-vjunosrouter', 'vjunosrouter'),
    'juniper_vsrx': ('juniper_vsrx', 'vr-vsrx', 'vsrx'),
}
GENERIC_JUNOS = ('junos', 'junipernetworks.junos.junos')


def definition(kind, name='sw1'):
    return json.dumps({'name': 'junos-lab', 'topology': {'nodes': {name: {'kind': kind}}}}).encode()


def inventory(group='all', **values):
    return json.dumps({'all': {'children': {group: {'hosts': {'clab-junos-lab-sw1': {
        'ansible_host': '192.0.2.11', **values}}}}}}).encode()


def bundle(kind, inv=None):
    files = {'definition': definition(kind)}
    if inv is not None:
        files['inventory'] = inv
    manifest = {name: {'path': '/etc/containerlab/' + name,
                       'sha256': hashlib.sha256(raw).hexdigest()} for name, raw in files.items()}
    return {'files': files, 'manifest': manifest, 'digest': hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()).hexdigest()}


def node(platform, name='sw1'):
    return {'name': name, 'short_name': name, 'platform': platform,
            'address': '192.0.2.11', 'port': 22, 'enabled': True,
            'profile_id': '', 'username': 'fixture-admin', 'password': 'fixture-device-secret'}


class VJunosRouterKindTests(unittest.TestCase):
    def test_router_is_a_junos_platform_with_its_own_label_default_login_and_download_name(self):
        from app.downloads import FORMATS as DOWNLOADS
        from app.git_progress import FORMATS as SAVE_FORMATS
        from app.inventory import DEFAULT_CREDENTIALS, JUNOS_PLATFORMS, JUNOS_SWITCHES
        self.assertIn('juniper_vjunosrouter', JUNOS_PLATFORMS)
        self.assertNotIn('juniper_vjunosrouter', JUNOS_SWITCHES)
        self.assertEqual(PLATFORMS['juniper_vjunosrouter']['label'], 'Junos (vJunos-router)')
        self.assertEqual(PLATFORMS['juniper_vjunosrouter']['os'], PLATFORMS['juniper_vjunosswitch']['os'])
        self.assertEqual(PLATFORMS['juniper_vjunosrouter']['command'], PLATFORMS['juniper_vjunosswitch']['command'])
        self.assertEqual(DEFAULT_CREDENTIALS['juniper_vjunosrouter'], ('admin', 'admin@123'))
        self.assertEqual(DOWNLOADS['juniper_vjunosrouter'], ('vJunos-router', 'cfg'))
        self.assertEqual(SAVE_FORMATS['juniper_vjunosrouter'], 'junos-display-set')

    def test_router_has_no_restore_artifact_and_no_restore_driver_until_proven_live(self):
        from app import restore_drivers, restore_junos
        from app.restore import NO_DRIVER, saved_device_reason
        from app.runner import restore_filename
        self.assertFalse(any(k.startswith('restore') for k in PLATFORMS['juniper_vjunosrouter']))
        self.assertEqual(restore_filename({'name': 'r1', 'platform': 'juniper_vjunosrouter'}), '')
        self.assertIsNone(restore_drivers.for_platform('juniper_vjunosrouter'))
        self.assertFalse(restore_junos.supports_restore('juniper_vjunosrouter'))
        lab = {'nodes': [{'name': 'r1', 'platform': 'juniper_vjunosrouter'}]}
        self.assertEqual(saved_device_reason(lab, 'r1', 'juniper_vjunosrouter'), NO_DRIVER)

    def test_router_is_not_offered_to_network_design(self):
        from app import design_junos, design_ownership, design_provision
        from app import design_capabilities as dc
        self.assertNotIn('juniper_vjunosrouter', design_junos.SUPPORTED_KINDS)
        self.assertNotIn('juniper_vjunosrouter', design_ownership.SET_KINDS)
        self.assertNotIn('juniper_vjunosrouter', design_provision.PREPARERS)
        self.assertEqual(dc.resolve('bgp', 'juniper_vjunosrouter')['level'], 'unsupported')


class VSRXKindTests(unittest.TestCase):
    """vSRX (campaign 2, B02): the same contract as vJunos-router, its own identity, restore and design gated until proven live."""

    def test_vsrx_is_a_junos_platform_with_its_own_label_default_login_and_download_name(self):
        from app.downloads import FORMATS as DOWNLOADS
        from app.git_progress import FORMATS as SAVE_FORMATS
        from app.inventory import ALIASES, DEFAULT_CREDENTIALS, JUNOS_PLATFORMS, JUNOS_SWITCHES
        self.assertIn('juniper_vsrx', JUNOS_PLATFORMS)
        self.assertNotIn('juniper_vsrx', JUNOS_SWITCHES)
        self.assertEqual(PLATFORMS['juniper_vsrx']['label'], 'Junos (vSRX)')
        self.assertEqual(PLATFORMS['juniper_vsrx']['os'], PLATFORMS['juniper_vjunosrouter']['os'])
        self.assertEqual(PLATFORMS['juniper_vsrx']['command'], PLATFORMS['juniper_vjunosrouter']['command'])
        # The official default of https://containerlab.dev/manual/kinds/vr-vsrx/ (checked 2026-10-27).
        self.assertEqual(DEFAULT_CREDENTIALS['juniper_vsrx'], ('admin', 'admin@123'))
        self.assertEqual(DOWNLOADS['juniper_vsrx'], ('vSRX', 'cfg'))
        self.assertEqual(SAVE_FORMATS['juniper_vsrx'], 'junos-display-set')
        for alias in ('juniper_vsrx', 'vr-vsrx', 'vsrx'):
            self.assertEqual(ALIASES[alias], 'juniper_vsrx')
        # The concrete kinds never collapse into each other: vSRX is not cJunosEvolved, a switch or the router.
        self.assertEqual(len({ALIASES[k] for k in ('vsrx', 'cjunosevolved', 'vjunosswitch', 'vjunosrouter')}), 4)

    def test_vsrx_has_no_restore_artifact_no_restore_driver_and_no_console_until_proven_live(self):
        from app import restore_drivers, restore_junos
        from app.inventory import console_port
        from app.restore import NO_DRIVER, saved_device_reason
        from app.runner import restore_filename
        self.assertFalse(any(k.startswith('restore') for k in PLATFORMS['juniper_vsrx']))
        self.assertEqual(restore_filename({'name': 'fw1', 'platform': 'juniper_vsrx'}), '')
        self.assertIsNone(restore_drivers.for_platform('juniper_vsrx'))
        self.assertFalse(restore_junos.supports_restore('juniper_vsrx'))
        lab = {'nodes': [{'name': 'fw1', 'platform': 'juniper_vsrx'}]}
        self.assertEqual(saved_device_reason(lab, 'fw1', 'juniper_vsrx'), NO_DRIVER)
        self.assertIsNone(console_port('juniper_vsrx'))
        self.assertIsNone(console_port('vr-vsrx'))

    def test_vsrx_is_not_offered_to_network_design(self):
        from app import design_junos, design_ownership, design_provision
        from app import design_capabilities as dc
        self.assertNotIn('juniper_vsrx', design_junos.SUPPORTED_KINDS)
        self.assertNotIn('juniper_vsrx', design_ownership.SET_KINDS)
        self.assertNotIn('juniper_vsrx', design_provision.PREPARERS)
        self.assertEqual(dc.resolve('bgp', 'juniper_vsrx')['level'], 'unsupported')

    def test_vsrx_data_ports_map_like_the_router_and_accept_the_documented_spellings(self):
        from app.device_diagnostics import VM_KINDS
        from app.topology import container_interface
        # containerlab.dev: eth1 is ge-0/0/0 (ge, xe and et are accepted spellings of the same port).
        self.assertEqual(container_interface('juniper_vsrx', 'ge-0/0/0'), 'eth1')
        self.assertEqual(container_interface('juniper_vsrx', 'xe-0/0/2'), 'eth3')
        self.assertEqual(container_interface('juniper_vsrx', 'et-0/0/1'), 'eth2')
        self.assertEqual(container_interface('juniper_vsrx', 'fxp0'), '')
        self.assertIn('juniper_vsrx', VM_KINDS)


class JunosKindImportTests(unittest.TestCase):
    def test_definition_maps_canonical_and_legacy_names_without_losing_kind(self):
        for platform, aliases in KINDS.items():
            for kind in aliases:
                with self.subTest(platform=platform, kind=kind):
                    parsed = parse_definition(definition(kind))['nodes'][0]
                    self.assertEqual(parsed['kind'], kind)
                    self.assertEqual(parsed['platform'], platform)
                    self.assertTrue(parsed['enabled'])
                    self.assertEqual(parsed['definition_node'], 'sw1')
        for kind in ('juniper_cjunosevolved', 'cjunosevolved'):
            with self.subTest(existing_kind=kind):
                self.assertEqual(parse_definition(definition(kind))['nodes'][0]['platform'],
                                 'juniper_cjunosevolved')

    def test_kind_groups_override_generic_junos_in_static_and_script_inventories(self):
        for platform, aliases in KINDS.items():
            for kind in aliases:
                for generic in GENERIC_JUNOS:
                    with self.subTest(platform=platform, kind=kind, generic=generic):
                        raw = inventory(kind, ansible_network_os=generic)
                        self.assertEqual(parse_inventory(raw)[0]['platform'], platform)
                        script = {'_meta': {'hostvars': {'clab-junos-lab-sw1': {
                            'ansible_network_os': generic, 'ansible_host': '192.0.2.11'}}},
                            kind: {'hosts': ['clab-junos-lab-sw1']}}
                        self.assertEqual(parse_inventory(json.dumps(script))[0]['platform'], platform)

    def test_topology_hint_overrides_generic_junos_inventory(self):
        for platform, aliases in KINDS.items():
            for kind in aliases:
                for generic in GENERIC_JUNOS:
                    with self.subTest(kind=kind, generic=generic):
                        topo = json.dumps({'nodes': {'sw1': {'kind': kind,
                            'longname': 'clab-junos-lab-sw1', 'shortname': 'sw1'}}})
                        parsed = parse_inventory(inventory(ansible_network_os=generic), topo)[0]
                        self.assertEqual(parsed['platform'], platform)
                        self.assertEqual(parsed['short_name'], 'sw1')

    def test_explicit_clab_kind_wins_over_generic_os_group_and_topology(self):
        topo = json.dumps({'nodes': {'clab-junos-lab-sw1': {'kind': 'juniper_cjunosevolved'}}})
        for platform, aliases in KINDS.items():
            for kind in aliases:
                with self.subTest(kind=kind):
                    parsed = parse_inventory(inventory('arista_ceos', clab_kind=kind,
                        ansible_network_os='junos'), topo)[0]
                    self.assertEqual(parsed['platform'], platform)

    def test_generic_junos_without_specific_kind_keeps_existing_fallback(self):
        for generic in GENERIC_JUNOS:
            with self.subTest(generic=generic):
                self.assertEqual(parse_inventory(inventory(ansible_network_os=generic))[0]['platform'],
                                 'juniper_cjunosevolved')

    def test_conflicting_junos_groups_require_explicit_kind(self):
        for generic in GENERIC_JUNOS:
            with self.subTest(generic=generic):
                values = {'ansible_network_os': generic, 'ansible_host': '192.0.2.11'}
                data = {'_meta': {'hostvars': {'sw1': values}},
                        'juniper_vqfx': {'hosts': ['sw1']},
                        'juniper_vjunosswitch': {'hosts': ['sw1']}}
                with self.assertRaises(ValueError):
                    parse_inventory(json.dumps(data))
                values['clab_kind'] = 'vr-vqfx'
                self.assertEqual(parse_inventory(json.dumps(data))[0]['platform'], 'juniper_vqfx')

    def test_vm_import_keeps_definition_kind_with_generic_inventory_and_no_export_json(self):
        for platform, aliases in KINDS.items():
            for kind in aliases:
                for generic in GENERIC_JUNOS:
                    with self.subTest(kind=kind, generic=generic):
                        imported = prepare_lab(bundle(kind, inventory(ansible_network_os=generic,
                            ansible_user='fixture-user', ansible_password='import-secret')), 'junos-lab')
                        item = imported['nodes'][0]
                        self.assertEqual(item['platform'], platform)
                        self.assertEqual(item['kind'], kind)
                        self.assertEqual(item['address'], '192.0.2.11')
                        self.assertEqual(item['password'], 'import-secret')
                        self.assertTrue(item['enabled'])

    def test_sync_maps_previously_unknown_kind_but_preserves_saved_settings(self):
        for platform in KINDS:
            with self.subTest(platform=platform):
                current_bundle = bundle(platform, inventory(ansible_network_os='junos',
                    ansible_user='new-import-user', ansible_password='new-import-secret'))
                old = prepare_lab(current_bundle, 'junos-lab')
                old['nodes'][0].update(platform='', enabled=False, name='saved-display-name',
                    endpoint_mode='manual', address='198.51.100.90', port=2222,
                    profile_id='existing-profile', username='saved-user', password='',
                    enable_password='saved-enable-secret')
                old['profiles'] = [{'id': 'existing-profile', 'platform': 'ssh',
                                    'username': 'profile-user', 'password': 'profile-secret'}]
                old['defaults'] = {'ssh': 'existing-profile'}
                old['interval'] = 30
                before = copy.deepcopy(old)
                updated = prepare_lab(current_bundle, 'junos-lab', old)
                item = updated['nodes'][0]
                self.assertEqual(item['platform'], platform)
                for key in ('name', 'enabled', 'endpoint_mode', 'address', 'port',
                            'profile_id', 'username', 'password', 'enable_password'):
                    self.assertEqual(item[key], before['nodes'][0][key], key)
                for key in ('id', 'profiles', 'defaults', 'interval'):
                    self.assertEqual(updated[key], before[key], key)
                self.assertEqual(old, before, 'Preparing a sync must not mutate the saved workspace')

    def test_sync_preserves_user_selected_platform(self):
        for platform in KINDS:
            for saved_platform in ('juniper_cjunosevolved', 'arista_ceos'):
                with self.subTest(platform=platform, saved_platform=saved_platform):
                    current_bundle = bundle(platform)
                    old = prepare_lab(current_bundle, 'junos-lab')
                    old['nodes'][0].update(platform=saved_platform, enabled=True)
                    updated = prepare_lab(current_bundle, 'junos-lab', old)
                    self.assertEqual(updated['nodes'][0]['platform'], saved_platform)
                    self.assertEqual(updated['nodes'][0]['kind'], platform)

    def test_driver_test_command_and_internal_filename_use_junos_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for platform in KINDS:
                item = node(platform)
                lab = {'nodes': [item], 'profiles': [], 'defaults': {}}
                for operation, command in (('backup', 'show configuration | display set | no-more'),
                                           ('test', 'show version')):
                    with self.subTest(platform=platform, operation=operation):
                        variables = make_inventory(lab, [item], work, operation)['all']['children']['targets']['hosts']['node_0']
                        self.assertEqual(variables['ansible_network_os'], 'junipernetworks.junos.junos')
                        self.assertEqual(variables['backup_command'], command)
                        self.assertEqual(variables['ansible_user'], 'fixture-admin')
                        self.assertNotIn('ansible_become', variables)
                        self.assertTrue(filename(item).endswith('.set'))

    def test_superputty_defaults_to_admin_for_both_switch_types(self):
        items = [node(platform, 'sw' + str(index)) for index, platform in enumerate(KINDS)]
        for item in items:
            item.update(username='', password='')
        lab = {'name': 'Junos', 'nodes': items, 'profiles': [], 'defaults': {}}
        sessions = ET.fromstring(session_xml(lab)).findall('SessionData')
        self.assertEqual([item.attrib['Username'] for item in sessions], ['admin'] * len(KINDS))
        self.assertTrue(all(item.attrib['ExtraArgs'] == '' for item in sessions))


class JunosKindAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.lab = {'id': 'junos-lab', 'name': 'Junos lab', 'profiles': [], 'defaults': {},
                    'interval': 0, 'nodes': [node(platform, name) for platform, name in
                        (('juniper_vqfx', 'qfx1'), ('juniper_vjunosswitch', 'switch1'),
                         ('juniper_cjunosevolved', 'evo1'), ('juniper_vjunosrouter', 'router1'),
                         ('juniper_vsrx', 'fw1'))]}
        self.store.state['labs'].append(self.lab)
        self.store.save()

    def tearDown(self):
        self.app.state.git_progress.close()
        self.app.state.operations.close()
        self.app.state.node_services.close()
        self.app.state.runner.close()
        self.client.close()
        self.tmp.cleanup()

    def test_distinct_profiles_readiness_ui_state_and_git_device_scope(self):
        for item in self.lab['nodes']:
            item.update(username='', password='')
        for platform in KINDS:
            # Without a profile or inventory login, containerlab's documented default
            # (admin / admin@123 for these Junos kinds) makes the node usable at once.
            item = next(n for n in self.lab['nodes'] if n['platform'] == platform)
            self.assertEqual(readiness(self.lab, item), 'Ready')
            self.assertEqual(credential_source(self.lab, item), 'default')
            self.assertEqual((effective_credentials(self.lab, item)['username'], effective_credentials(self.lab, item)['password']), ('admin', 'admin@123'))
            response = self.client.post('/api/labs/junos-lab/profiles', data={
                'label': platform, 'platform': platform, 'username': 'admin-' + platform,
                'auth': 'password', 'password': 'private-' + platform})
            self.assertEqual(response.status_code, 200, response.text)
        public = self.client.get('/api/state')
        self.assertEqual(public.status_code, 200)
        state = public.json()
        for platform in KINDS:
            self.assertIn(platform, state['platforms'])
            item = next(n for n in self.lab['nodes'] if n['platform'] == platform)
            self.assertEqual(effective_credentials(self.lab, item)['username'], 'admin-' + platform)
            display = next(n for n in state['labs'][0]['nodes'] if n['platform'] == platform)
            self.assertEqual(display['readiness'], 'Ready')
            self.assertEqual(display['credential_source'], 'profile')
            self.assertTrue(display['ssh_ready'])
            self.assertNotIn('private-' + platform, public.text)
        # cJunosEvolved has no profile here: the documented default applies, never a
        # profile created for a different Junos kind.
        self.assertEqual(credential_source(self.lab, self.lab['nodes'][2]), 'default')
        self.assertEqual(effective_credentials(self.lab, self.lab['nodes'][2])['username'], 'admin')
        self.assertNotIn('admin@123', public.text)
        self.assertEqual(len(set(self.lab['defaults'].values())), len(KINDS))
        self.assertNotEqual(PLATFORMS['juniper_vqfx']['label'], PLATFORMS['juniper_vjunosswitch']['label'])
        with patch('app.git_progress.remote_git') as remote:
            response = self.client.get('/api/labs/junos-lab/git')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['unsupported_nodes'], [])
        self.assertEqual({n['platform'] for n in response.json()['supported_nodes']},
                         {'juniper_vqfx', 'juniper_vjunosswitch', 'juniper_cjunosevolved', 'juniper_vjunosrouter', 'juniper_vsrx'})
        remote.assert_not_called()

    def capture(self):
        items = self.lab['nodes'][:2]
        runner = self.app.state.runner
        with patch.object(runner.pool, 'submit'):
            job = runner.submit(self.lab['id'], node_names=[item['name'] for item in items])
        output = {item['name']: f"set system host-name {item['name']}\nset system services ssh\n" for item in items}

        def ansible(args, **kwargs):
            self.assertEqual(args[0], 'ansible-playbook')
            Path(kwargs['env']['BACKUP_EVENT_FILE']).write_text(''.join(json.dumps({
                'host': f'node_{index}', 'status': 'ok', 'task': 'Capture config',
                'stdout': output[item['name']], 'captured_at': '2026-09-11T12:34:00+00:00'}) + '\n'
                for index, item in enumerate(items)), encoding='utf-8')
            return SimpleNamespace(poll=lambda: 0, returncode=0)

        with patch('app.runner.subprocess.Popen', side_effect=ansible), \
             patch('app.runner.subprocess.run', return_value=SimpleNamespace(stdout='', returncode=0)):
            runner.execute(job['id'], copy.deepcopy(self.lab), copy.deepcopy(items), 'backup')
        saved = next(j for j in self.store.state['jobs'] if j['id'] == job['id'])
        self.assertEqual(saved['status'], 'succeeded', saved)
        return saved, output

    def test_capture_retains_kind_and_git_snapshot_preserves_display_set_bytes(self):
        job, output = self.capture()
        for item in job['nodes']:
            self.assertIn(item['platform'], KINDS)
            self.assertTrue(item['file'].endswith('.set'))
        with patch('app.git_progress.remote_git') as remote:
            snapshot = captured_snapshot(self.store, job)
            manifest, files = decoded_snapshot({'snapshot': snapshot})
        remote.assert_not_called()
        for row in manifest['files']:
            self.assertEqual(row['format'], 'junos-display-set')
            self.assertIn(row['platform'], KINDS)
            # The Git snapshot's human-facing file is `.cfg` (display-set text, matching EOS and
            # IOS XR there); the internal capture storage extension stays `.set` (asserted above).
            self.assertEqual(row['path'], row['short_name'] + '.cfg')
            self.assertEqual(files[row['path']], output[row['node']].encode())
            self.assertEqual(base64.b64decode(snapshot['files'][row['path']]), output[row['node']].encode())

    def test_individual_and_zip_downloads_use_distinct_names_without_relabeling_history(self):
        job, output = self.capture()
        # Current inventory edits must not change the immutable capture's identity.
        for item in self.lab['nodes'][:2]:
            item['platform'] = 'juniper_cjunosevolved'
        response = self.client.get(f"/api/jobs/{job['id']}/download")
        self.assertEqual(response.status_code, 200, response.text)
        expected = ['vQFX_qfx1_2026-09-11_12-34UTC.cfg',
                    'vJunos-switch_switch1_2026-09-11_12-34UTC.cfg']
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(set(archive.namelist()), {*expected, 'manifest.json'})
            for index, name in enumerate(expected):
                single = self.client.get(f"/api/jobs/{job['id']}/nodes/{index}/download")
                self.assertEqual(single.status_code, 200, single.text)
                self.assertIn(name, single.headers['content-disposition'])
                self.assertEqual(single.content, archive.read(name))
                self.assertEqual(single.content, output[job['nodes'][index]['name']].encode())


if __name__ == '__main__':
    unittest.main()
