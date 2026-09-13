"""Per-NOS adapters: what is read, the smallest lines added, scoped commits and subscriptions."""
import unittest

from app.telemetry_adapters import ADAPTERS, SAMPLE_NS, adapter_for


def outputs(adapter, *texts):
    return dict(zip(adapter.show_commands(), texts))


class EosAdapterTests(unittest.TestCase):
    adapter = ADAPTERS['arista_ceos']

    def test_containerlab_default_config_needs_no_change(self):
        plan = self.adapter.plan(outputs(self.adapter, 'management api gnmi\n   transport grpc default\n', 'interface Management0\n   ip address 172.20.20.2/24\n'))
        self.assertTrue(plan.ready); self.assertEqual((plan.port, plan.transport), (6030, 'plaintext'))

    def test_missing_service_is_added_in_the_management_vrf_without_saving(self):
        plan = self.adapter.plan(outputs(self.adapter, '', 'interface Management0\n   vrf MGMT\n   ip address 172.20.20.2/24\n'))
        self.assertEqual(plan.add, ['management api gnmi', '   transport grpc default', '      vrf MGMT'])
        commands = self.adapter.apply(plan)
        self.assertEqual(commands, ['configure terminal', 'management api gnmi', 'transport grpc default', 'vrf MGMT', 'end'])
        self.assertNotIn('write', ' '.join(commands)); self.assertNotIn('copy running-config', ' '.join(commands))

    def test_existing_transport_settings_are_respected(self):
        plan = self.adapter.plan(outputs(self.adapter, 'management api gnmi\n   transport grpc mine\n      port 5900\n      ssl profile LAB\n', ''))
        self.assertTrue(plan.ready); self.assertEqual((plan.port, plan.transport), (5900, 'tls'))
        shut = self.adapter.plan(outputs(self.adapter, 'management api gnmi\n   transport grpc default\n      shutdown\n', ''))
        self.assertFalse(shut.ready); self.assertIn('shut down', shut.blockers[0])
        wrong_vrf = self.adapter.plan(outputs(self.adapter, 'management api gnmi\n   transport grpc default\n', 'interface Management0\n   vrf MGMT\n'))
        self.assertIn('management VRF MGMT', wrong_vrf.blockers[0])

    def test_removal_only_covers_the_transport_the_manager_added(self):
        self.assertEqual(self.adapter.remove(['management api gnmi', '   transport grpc default']),
                         ['configure terminal', 'management api gnmi', 'no transport grpc default', 'exit', 'end'])
        self.assertEqual(self.adapter.remove(['      vrf MGMT']), [], 'a partial record removes nothing')

    def test_subscriptions_prefer_on_change_state_with_sampled_fallbacks(self):
        variants = self.adapter.subscriptions('interfaces')
        self.assertEqual(variants[0][0], {'path': '/interfaces/interface/state/counters', 'mode': 'sample', 'sample_interval': SAMPLE_NS})
        self.assertEqual(variants[0][1]['mode'], 'on_change')
        self.assertTrue(all(v['mode'] == 'sample' for v in variants[1]))
        self.assertEqual(variants[-1], [{'path': '/interfaces/interface/state', 'mode': 'sample', 'sample_interval': SAMPLE_NS}])
        self.assertEqual(self.adapter.encodings[0], 'json_ietf')
        self.assertTrue(self.adapter.models_present('bgp', [{'name': 'openconfig-network-instance'}]))
        self.assertFalse(self.adapter.models_present('bgp', [{'name': 'openconfig-interfaces'}]))


class IosxrAdapterTests(unittest.TestCase):
    adapter = ADAPTERS['cisco_xrv9k']

    def test_absent_grpc_is_added_and_committed(self):
        plan = self.adapter.plan(outputs(self.adapter, '% No such configuration item(s)\n', 'interface MgmtEth0/RP0/CPU0/0\n ipv4 address dhcp\n!\n'))
        self.assertEqual(plan.add, ['grpc', ' port 57400']); self.assertEqual(plan.transport, 'tls')
        self.assertEqual(self.adapter.apply(plan), ['configure terminal', 'grpc', 'port 57400', 'commit', 'end'])
        self.assertEqual(self.adapter.abort(), ['abort'])

    def test_existing_grpc_settings_decide_port_and_transport(self):
        plan = self.adapter.plan(outputs(self.adapter, 'grpc\n port 57400\n no-tls\n!\n', ''))
        self.assertTrue(plan.ready); self.assertEqual((plan.port, plan.transport), (57400, 'plaintext'))
        tls = self.adapter.plan(outputs(self.adapter, 'grpc\n port 57777\n!\n', ''))
        self.assertEqual((tls.port, tls.transport), (57777, 'tls'))
        vrf = self.adapter.plan(outputs(self.adapter, 'grpc\n!\n', 'interface MgmtEth0/RP0/CPU0/0\n vrf MGMT\n!\n'))
        self.assertIn('vrf MGMT', vrf.blockers[0])
        added = self.adapter.plan(outputs(self.adapter, '', 'interface MgmtEth0/RP0/CPU0/0\n vrf MGMT\n!\n'))
        self.assertEqual(added.add, ['grpc', ' port 57400', ' vrf MGMT'])

    def test_paths_carry_the_module_origin_xr_requires(self):
        first = self.adapter.subscriptions('interfaces')[0]
        self.assertEqual(first[0]['path'], 'openconfig-interfaces:interfaces/interface/state/counters')
        self.assertTrue(all(v['mode'] == 'sample' for v in first))
        bgp = self.adapter.subscriptions('bgp')[0]
        self.assertTrue(bgp[0]['path'].startswith('openconfig-network-instance:network-instances/'))
        self.assertEqual(self.adapter.remove(['grpc', ' port 57400']), ['configure terminal', 'no grpc', 'commit', 'end'])
        self.assertTrue(self.adapter.failed('% Failed to commit one or more configuration items'))
        self.assertEqual(self.adapter.failed('RP/0/RP0/CPU0:ios(config)#'), '')


class JunosEvoAdapterTests(unittest.TestCase):
    adapter = ADAPTERS['juniper_cjunosevolved']

    def test_clear_text_grpc_is_added_with_a_private_commit(self):
        plan = self.adapter.plan(outputs(self.adapter, '', ''))
        self.assertEqual(plan.add, ['set system services extension-service request-response grpc clear-text port 32767'])
        self.assertEqual(self.adapter.apply(plan), ['configure private', plan.add[0], 'commit and-quit'])
        self.assertEqual(self.adapter.abort(), ['rollback 0', 'exit configuration-mode'])

    def test_management_instance_binds_the_service_to_mgmt_junos(self):
        plan = self.adapter.plan(outputs(self.adapter, '', 'set system management-instance\n'))
        self.assertEqual(plan.add[1], 'set system services extension-service request-response grpc routing-instance mgmt_junos')
        blocked = self.adapter.plan(outputs(self.adapter, 'set system services extension-service request-response grpc clear-text port 32767\n', 'set system management-instance\n'))
        self.assertIn('mgmt_junos', blocked.blockers[0])

    def test_existing_services_are_reused(self):
        plan = self.adapter.plan(outputs(self.adapter, 'set system services extension-service request-response grpc clear-text port 50051\n', ''))
        self.assertTrue(plan.ready); self.assertEqual((plan.port, plan.transport), (50051, 'plaintext'))
        ssl = self.adapter.plan(outputs(self.adapter, 'set system services extension-service request-response grpc ssl port 32767\nset system services extension-service request-response grpc ssl local-certificate lab\n', ''))
        self.assertEqual((ssl.port, ssl.transport), (32767, 'tls'))
        self.assertEqual(self.adapter.remove(['set system services extension-service request-response grpc clear-text port 32767']),
                         ['configure private', 'delete system services extension-service request-response grpc clear-text', 'commit and-quit'])
        self.assertTrue(self.adapter.failed('error: configuration check-out failed'))
        self.assertEqual(self.adapter.subscriptions('interfaces')[0][0]['path'], '/interfaces/interface/state/counters')


class RegistryTests(unittest.TestCase):
    def test_only_the_three_lab_platforms_have_adapters(self):
        self.assertEqual(sorted(ADAPTERS), ['arista_ceos', 'cisco_xrv9k', 'juniper_cjunosevolved'])
        self.assertIsNone(adapter_for('juniper_vqfx')); self.assertIsNone(adapter_for('')); self.assertIsNone(adapter_for(None))


if __name__ == '__main__':
    unittest.main()
