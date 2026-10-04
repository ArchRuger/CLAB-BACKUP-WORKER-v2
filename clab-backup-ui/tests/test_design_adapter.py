"""Tests for app/design_adapter.py: reading the containerlab topology, mapping endpoints to NOS
interface names, building the netlab topology from a lab and its design intent, the allocation
collision helpers, and the read-only plan summary.

A capability lookup (`design_capabilities.profile_for`) is being written by another worker; these
tests use the stub PROFILES table the task specifies -- the adapter only needs 'netlab_device',
'mgmt_if' and an optional 'role' from it. The one real-engine test is skipped when `netlab` is not
on PATH.
"""
import copy
import ipaddress
import os
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

from app import design_adapter as da
from app import design_intent as di
from app.discovery import parse_definition

HAS_NETLAB = shutil.which('netlab') is not None
SKIP_REASON = 'netlab is not on PATH for this test run'

# The four-node fixture from docs/multi-platform-restore (restore-square), copied here as a text
# constant per the task: it is not read from /srv at test time.
FIXTURE_YAML = """\
name: restore-square
mgmt:
  network: clab
  ipv4-subnet: 172.20.20.0/24
topology:
  defaults:
    env:
      TZ: UTC
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
"""

# The stub capability lookup the task specifies (the real one is being written elsewhere).
PROFILES = {'arista_ceos': {'netlab_device': 'eos', 'mgmt_if': 'Management0'},
            'juniper_vjunosswitch': {'netlab_device': 'vjunos-switch', 'mgmt_if': 'fxp0'},
            'juniper_cjunosevolved': {'netlab_device': 'vptx', 'mgmt_if': 're0:mgmt-0'},
            'cisco_xrv9k': {'netlab_device': 'iosxr', 'mgmt_if': 'MgmtEth0/RP0/CPU0/0'},
            'linux': {'netlab_device': 'linux', 'mgmt_if': 'eth0', 'role': 'host'}}


def profile_for(kind):
    return PROFILES.get(kind)


def lab_nodes():
    return parse_definition(FIXTURE_YAML.encode())['nodes']


def base_intent():
    intent = di.empty_intent()
    intent['modules'] = ['ospf', 'bgp']
    intent['ospf'] = {'area': '0.0.0.0'}
    intent['bgp'] = {'as': 65000}
    return intent


# Six link keys of the fixture, in the ascending order build() now emits (sorted by key).
FIXTURE_LINK_KEYS = [
    'ceos:eth1--cjunosevolved:et-0/0/0',
    'ceos:eth2--xrv9k:Gi0/0/0/1',
    'ceos:eth3--host1:eth2',
    'cjunosevolved:et-0/0/1--vjunos-switch:ge-0/0/0',
    'host1:eth1--vjunos-switch:ge-0/0/2',
    'vjunos-switch:ge-0/0/1--xrv9k:Gi0/0/0/0',
]

# Routers sorted by name, then the one host, sorted by name (build()'s emission order).
FIXTURE_NODE_ORDER = ['ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k', 'host1']


class DesignAdapterTestCase(unittest.TestCase):
    pass


# --- parse_links -------------------------------------------------------------------------------------------

class ParseLinksTests(DesignAdapterTestCase):
    def _links(self, topology_body):
        text = yaml.safe_dump({'name': 'x', 'topology': {'nodes': {'a': {}, 'b': {}}, **topology_body}})
        return da.parse_links(text)

    def test_string_endpoints(self):
        rows = self._links({'links': [{'endpoints': ['a:eth1', 'b:eth1']}]})
        self.assertEqual(rows[0]['endpoints'], [('a', 'eth1'), ('b', 'eth1')])
        self.assertEqual(rows[0]['problem'], '')
        self.assertEqual(rows[0]['key'], di.link_key([('a', 'eth1'), ('b', 'eth1')]))

    def test_mapping_endpoints_node_interface_form(self):
        rows = self._links({'links': [{'endpoints': [{'node': 'a', 'interface': 'eth1'},
                                                       {'node': 'b', 'interface': 'eth2'}]}]})
        self.assertEqual(rows[0]['endpoints'], [('a', 'eth1'), ('b', 'eth2')])

    def test_mapping_endpoints_exporter_short_name_form(self):
        rows = self._links({'links': [{'endpoints': [{'node-short-name': 'a', 'interface-name': 'eth1'},
                                                       {'node-short-name': 'b', 'interface-name': 'eth2'}]}]})
        self.assertEqual(rows[0]['endpoints'], [('a', 'eth1'), ('b', 'eth2')])

    def test_a_z_endpoints_mapping(self):
        rows = self._links({'links': [{'endpoints': {'a': 'a:eth1', 'z': 'b:eth1'}}]})
        self.assertEqual(rows[0]['endpoints'], [('a', 'eth1'), ('b', 'eth1')])

    def test_non_veth_type_is_flagged_with_a_reason(self):
        rows = self._links({'links': [{'type': 'mgmt-net', 'endpoints': ['a:eth1', 'b:eth1']}]})
        self.assertNotEqual(rows[0]['problem'], '')
        self.assertIn('mgmt-net', rows[0]['problem'])

    def test_host_type_is_flagged(self):
        rows = self._links({'links': [{'type': 'host', 'endpoints': ['a:eth1']}]})
        self.assertIn('host', rows[0]['problem'])

    def test_macvlan_type_is_flagged(self):
        rows = self._links({'links': [{'type': 'macvlan', 'endpoints': ['a:eth1', 'b:eth1']}]})
        self.assertIn('macvlan', rows[0]['problem'])

    def test_vxlan_type_is_flagged(self):
        rows = self._links({'links': [{'type': 'vxlan', 'endpoints': ['a:eth1', 'b:eth1']}]})
        self.assertIn('vxlan', rows[0]['problem'])

    def test_link_with_one_endpoint_is_flagged(self):
        rows = self._links({'links': [{'endpoints': ['a:eth1']}]})
        self.assertNotEqual(rows[0]['problem'], '')
        self.assertEqual(rows[0]['endpoints'], [])

    def test_link_that_is_not_a_mapping_is_flagged(self):
        rows = self._links({'links': ['not-a-mapping']})
        self.assertEqual(rows[0]['problem'], 'not a mapping')


# --- management_networks -----------------------------------------------------------------------------------

class ManagementNetworksTests(DesignAdapterTestCase):
    def test_mgmt_subnet_and_per_node_slash32(self):
        nodes = [{'short_name': 'a', 'address': '172.20.20.101'}, {'short_name': 'b', 'address': '172.20.20.102'}]
        networks = da.management_networks(FIXTURE_YAML, nodes)
        labels_and_nets = {label: net for label, net in networks}
        self.assertIn(ipaddress.ip_network('172.20.20.0/24'), labels_and_nets.values())
        self.assertIn(ipaddress.ip_network('172.20.20.101/32'), labels_and_nets.values())
        self.assertIn(ipaddress.ip_network('172.20.20.102/32'), labels_and_nets.values())

    def test_hostname_address_is_skipped(self):
        nodes = [{'short_name': 'a', 'address': 'not-an-ip-hostname'}]
        networks = da.management_networks(FIXTURE_YAML, nodes)
        self.assertFalse(any('a' in label for label, _ in networks if label.startswith('device')))


# --- nos_interface / map_endpoint --------------------------------------------------------------------------

class NosInterfaceTests(DesignAdapterTestCase):
    def test_ceos_eth1_maps_to_ethernet1(self):
        self.assertEqual(da.nos_interface('arista_ceos', 'eth1'), 'Ethernet1')

    def test_ceos_ethernet2_passes_through(self):
        self.assertEqual(da.nos_interface('arista_ceos', 'Ethernet2'), 'Ethernet2')

    def test_vjunos_switch_ge_form_passes_through(self):
        self.assertEqual(da.nos_interface('juniper_vjunosswitch', 'ge-0/0/0'), 'ge-0/0/0')

    def test_vjunos_switch_eth1_maps_to_ge_0_0_0(self):
        self.assertEqual(da.nos_interface('juniper_vjunosswitch', 'eth1'), 'ge-0/0/0')

    def test_cjunosevolved_et_form_passes_through(self):
        self.assertEqual(da.nos_interface('juniper_cjunosevolved', 'et-0/0/0'), 'et-0/0/0')

    def test_cjunosevolved_eth4_maps_to_et_0_0_0(self):
        self.assertEqual(da.nos_interface('juniper_cjunosevolved', 'eth4'), 'et-0/0/0')

    def test_cjunosevolved_eth1_is_unresolved_image_reserved(self):
        self.assertEqual(da.nos_interface('juniper_cjunosevolved', 'eth1'), '')

    def test_xrv9k_short_gi_form_maps_to_long_name(self):
        self.assertEqual(da.nos_interface('cisco_xrv9k', 'Gi0/0/0/0'), 'GigabitEthernet0/0/0/0')

    def test_xrv9k_long_form_passes_through(self):
        self.assertEqual(da.nos_interface('cisco_xrv9k', 'GigabitEthernet0/0/0/1'), 'GigabitEthernet0/0/0/1')

    def test_xrv9k_eth1_maps_to_gi0_0_0_0(self):
        self.assertEqual(da.nos_interface('cisco_xrv9k', 'eth1'), 'GigabitEthernet0/0/0/0')

    def test_linux_eth1_passes_through(self):
        self.assertEqual(da.nos_interface('linux', 'eth1'), 'eth1')

    def test_linux_ens3_is_unresolved(self):
        self.assertEqual(da.nos_interface('linux', 'ens3'), '')

    def test_unknown_kind_is_unresolved(self):
        self.assertEqual(da.nos_interface('nokia_srlinux_typo', 'eth1'), '')

    def test_sub_interface_is_unresolved(self):
        self.assertEqual(da.nos_interface('juniper_cjunosevolved', 'et-0/0/0.100'), '')

    def test_breakout_child_is_unresolved(self):
        self.assertEqual(da.nos_interface('juniper_vjunosswitch', 'ge-0/0/1:0'), '')


class MapEndpointTests(DesignAdapterTestCase):
    def test_rule_source_when_no_override(self):
        entry = da.map_endpoint('arista_ceos', 'eth1')
        self.assertEqual(entry['nos'], 'Ethernet1')
        self.assertEqual(entry['source'], 'rule')
        self.assertNotIn('reason', entry)

    def test_manual_source_for_a_correctly_spelled_override(self):
        entry = da.map_endpoint('arista_ceos', 'eth1', override='Ethernet7')
        self.assertEqual(entry['nos'], 'Ethernet7')
        self.assertEqual(entry['source'], 'manual')

    def test_wrongly_spelled_override_gives_no_nos_and_a_reason(self):
        entry = da.map_endpoint('arista_ceos', 'eth1', override='eth7')
        self.assertEqual(entry['nos'], '')
        self.assertEqual(entry['source'], '')
        self.assertIn('reason', entry)

    def test_unresolved_endpoint_carries_a_reason(self):
        entry = da.map_endpoint('juniper_cjunosevolved', 'eth1')
        self.assertEqual(entry['nos'], '')
        self.assertIn('reason', entry)
        self.assertIn('eth1', entry['reason'])

    def test_unknown_kind_carries_a_reason(self):
        entry = da.map_endpoint('', 'eth1')
        self.assertEqual(entry['nos'], '')
        self.assertIn('unknown', entry['reason'])


# --- build() -----------------------------------------------------------------------------------------------

class BuildBasicsTests(DesignAdapterTestCase):
    def setUp(self):
        self.nodes = lab_nodes()

    def test_every_node_included_with_expected_profile_and_mgmt(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        top_nodes = result['topology']['nodes']
        self.assertEqual(top_nodes['ceos']['device'], 'eos')
        self.assertEqual(top_nodes['ceos']['mgmt'], {'ifname': 'Management0', 'ipv4': '172.20.20.101'})
        self.assertEqual(top_nodes['cjunosevolved']['device'], 'vptx')
        self.assertEqual(top_nodes['cjunosevolved']['mgmt'], {'ifname': 're0:mgmt-0', 'ipv4': '172.20.20.102'})
        self.assertEqual(top_nodes['vjunos-switch']['device'], 'vjunos-switch')
        self.assertEqual(top_nodes['vjunos-switch']['mgmt'], {'ifname': 'fxp0', 'ipv4': '172.20.20.103'})
        self.assertEqual(top_nodes['xrv9k']['device'], 'iosxr')
        self.assertEqual(top_nodes['xrv9k']['mgmt'], {'ifname': 'MgmtEth0/RP0/CPU0/0', 'ipv4': '172.20.20.104'})
        self.assertEqual(top_nodes['host1']['device'], 'linux')
        self.assertEqual(top_nodes['host1']['mgmt'], {'ifname': 'eth0', 'ipv4': '172.20.20.105'})

    def test_host_gets_host_role_and_empty_module_list(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        host = result['topology']['nodes']['host1']
        self.assertEqual(host['role'], 'host')
        self.assertEqual(host['module'], [])

    def test_nodes_are_emitted_routers_first_then_hosts_each_sorted_by_name(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        self.assertEqual(list(result['topology']['nodes'].keys()), FIXTURE_NODE_ORDER)

    def test_six_links_in_ascending_key_order_with_expected_ifnames(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        self.assertEqual(result['link_keys'], FIXTURE_LINK_KEYS)
        expected = [
            {'ceos': 'Ethernet1', 'cjunosevolved': 'et-0/0/0'},
            {'ceos': 'Ethernet2', 'xrv9k': 'GigabitEthernet0/0/0/1'},
            {'ceos': 'Ethernet3', 'host1': 'eth2'},
            {'cjunosevolved': 'et-0/0/1', 'vjunos-switch': 'ge-0/0/0'},
            {'host1': 'eth1', 'vjunos-switch': 'ge-0/0/2'},
            {'vjunos-switch': 'ge-0/0/1', 'xrv9k': 'GigabitEthernet0/0/0/0'},
        ]
        actual = [{node: entry['ifname'] for node, entry in link.items()} for link in result['topology']['links']]
        self.assertEqual(actual, expected)

    def test_link_keys_match_emission_order_of_topology_links(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        self.assertEqual(len(result['link_keys']), len(result['topology']['links']))

    def test_mapping_populated_with_source_rule_no_notes_no_blocked(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        self.assertEqual(set(result['mapping']), set(FIXTURE_LINK_KEYS))
        for ends in result['mapping'].values():
            for entry in ends.values():
                self.assertEqual(entry['source'], 'rule')
        self.assertEqual(result['notes'], [])
        self.assertEqual(result['blocked'], {})

    def test_no_defaults_plugin_config_tools_validate_key_anywhere(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        found = []

        def walk(obj, path=''):
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if key in ('defaults', 'plugin', 'config', 'tools', 'validate'):
                        found.append(path + '.' + str(key))
                    walk(value, path + '.' + str(key))
            elif isinstance(obj, list):
                for index, value in enumerate(obj):
                    walk(value, path + '[%d]' % index)

        walk(result['topology'])
        self.assertEqual(found, [])

    def test_provider_is_external_and_name_is_the_constant(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        self.assertEqual(result['topology']['provider'], 'external')
        self.assertEqual(result['topology']['name'], da.TOPOLOGY_NAME)


class BuildFamiliesTests(DesignAdapterTestCase):
    def setUp(self):
        self.nodes = lab_nodes()

    def test_ipv4_only_strips_ipv6_from_pools(self):
        intent = base_intent(); intent['families'] = {'ipv4': True, 'ipv6': False}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        for pool in result['topology']['addressing'].values():
            self.assertNotIn('ipv6', pool)

    def test_ipv6_only_adds_router_id_pool(self):
        intent = base_intent(); intent['families'] = {'ipv4': False, 'ipv6': True}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        addressing = result['topology']['addressing']
        for name, pool in addressing.items():
            if name != 'router_id':
                self.assertNotIn('ipv4', pool)
        self.assertIn('router_id', addressing)
        self.assertEqual(addressing['router_id']['ipv4'], '10.0.0.0/24')


class BuildLagTests(DesignAdapterTestCase):
    TWO = """name: two
topology:
  nodes:
    r1: {kind: arista_ceos, image: x}
    r2: {kind: juniper_vjunosswitch, image: y}
  links:
    - endpoints: ["r1:eth1", "r2:ge-0/0/0"]
    - endpoints: ["r1:eth2", "r2:ge-0/0/1"]
    - endpoints: ["r1:eth3", "r2:ge-0/0/2"]
"""

    def test_a_bundle_carries_its_member_ports_and_the_members_are_not_separate_links(self):
        nodes = parse_definition(self.TWO.encode())['nodes']
        K1, K2, K3 = 'r1:eth1--r2:ge-0/0/0', 'r1:eth2--r2:ge-0/0/1', 'r1:eth3--r2:ge-0/0/2'
        intent = dict(di.empty_intent(), modules=['lag'], links={K1: {'lag': {'members': [K2]}}})
        built = da.build(self.TWO, nodes, intent, profile_for)
        topo_links = built['topology']['links']
        self.assertEqual(len(topo_links), 2, 'the bundle and the third plain link; the member is inside the bundle')
        bundle = next(l for l in topo_links if 'lag' in l)
        self.assertEqual(bundle['r1'], {}); self.assertEqual(bundle['r2'], {})   # the bundle's own interface is the engine's
        # netlab keeps only `ifindex` on member ports and names them from the device template (an `ifname` here leaks onto the bundle: verified with the engine).
        self.assertEqual(bundle['lag']['members'], [{'r1': {'ifindex': 1}, 'r2': {'ifindex': 0}}, {'r1': {'ifindex': 2}, 'r2': {'ifindex': 1}}])
        plain = next(l for l in topo_links if 'lag' not in l)
        self.assertEqual(plain['r1'], {'ifname': 'Ethernet3'})
        rows = {r['key']: r for r in built['links']}
        self.assertTrue(rows[K2]['included']); self.assertIn('Member of the link aggregation carried by ' + K1, rows[K2]['reason'])
        self.assertEqual(built['link_keys'], [K3, K1], 'bundles are emitted after the plain links, in key order')
        self.assertIn(K2, built['mapping'])

    def test_a_member_that_is_a_bundle_or_is_claimed_twice_is_refused_never_dropped(self):
        # Audit 2026-10-03 L-17: validation refuses these; a design stored before that check never plans with the links silently missing.
        nodes = parse_definition(self.TWO.encode())['nodes']
        K1, K2, K3 = 'r1:eth1--r2:ge-0/0/0', 'r1:eth2--r2:ge-0/0/1', 'r1:eth3--r2:ge-0/0/2'
        for links, fragment in (({K1: {'lag': {'members': [K2]}}, K2: {'lag': {'members': [K1]}}}, 'carries an aggregation of its own'),
                                ({K1: {'lag': {'members': [K2]}}, K2: {'lag': {'members': [K3]}}}, 'carries an aggregation of its own'),
                                ({K1: {'lag': {'members': [K3]}}, K2: {'lag': {'members': [K3]}}}, 'member of two aggregations')):
            intent = dict(di.empty_intent(), modules=['lag'], links=links)
            with self.assertRaises(da.AdapterError) as caught:
                da.build(self.TWO, nodes, intent, profile_for)
            self.assertIn(fragment, str(caught.exception))


class BuildLedgerAndOverridesTests(DesignAdapterTestCase):
    def setUp(self):
        self.nodes = lab_nodes()

    def test_ledger_pins_id_loopback_and_link_prefix(self):
        key = 'ceos:eth1--cjunosevolved:et-0/0/0'
        intent = base_intent()
        intent['allocations'] = {'node_ids': {'ceos': 7}, 'loopbacks': {'ceos': {'ipv4': '10.255.0.9'}},
                                  'links': {key: {'ipv4': '10.1.0.100/31'}}}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        ceos = result['topology']['nodes']['ceos']
        self.assertEqual(ceos['id'], 7)
        self.assertEqual(ceos['loopback'], {'ipv4': '10.255.0.9'})
        idx = result['link_keys'].index(key)
        self.assertEqual(result['topology']['links'][idx]['prefix'], {'ipv4': '10.1.0.100/31'})

    def test_explicit_node_loopback_wins_over_the_ledger(self):
        intent = base_intent()
        intent['allocations'] = {'loopbacks': {'ceos': {'ipv4': '10.255.0.9'}}}
        intent['nodes'] = {'ceos': {'loopback': {'ipv4': '10.255.0.42'}}}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        self.assertEqual(result['topology']['nodes']['ceos']['loopback'], {'ipv4': '10.255.0.42'})

    def test_role_exclude_leaves_node_and_its_links_out_with_notes(self):
        intent = base_intent(); intent['nodes'] = {'xrv9k': {'role': 'exclude'}}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        self.assertNotIn('xrv9k', result['topology']['nodes'])
        self.assertTrue(any('xrv9k' in n and 'Excluded' in n for n in result['notes']))
        dropped = [n for n in result['notes'] if n.startswith('Link') and 'xrv9k' in n]
        self.assertEqual(len(dropped), 2)  # xrv9k has two links in the fixture

    def test_linux_node_keeps_its_links(self):
        result = da.build(FIXTURE_YAML, self.nodes, base_intent(), profile_for)
        host_links = [k for k in result['link_keys'] if 'host1' in k]
        self.assertEqual(len(host_links), 2)

    def test_unknown_kind_is_left_out_with_reason(self):
        text = re.sub(r'kind: cisco_xrv9k', 'kind: nokia_srlinux', FIXTURE_YAML)
        nodes = parse_definition(text.encode())['nodes']
        result = da.build(text, nodes, base_intent(), profile_for)
        self.assertNotIn('xrv9k', result['topology']['nodes'])
        self.assertIn('No design profile', result['nodes']['xrv9k']['reason'])
        self.assertTrue(any('xrv9k' in n and 'No design profile' in n for n in result['notes']))

    def test_all_nodes_unknown_kind_raises_adaptererror(self):
        with self.assertRaises(da.AdapterError):
            da.build(FIXTURE_YAML, self.nodes, base_intent(), lambda kind: None)

    def test_unmappable_endpoint_blocks_the_link_and_both_devices(self):
        text = FIXTURE_YAML.rstrip() + '\n    - endpoints: ["cjunosevolved:eth1", "xrv9k:Gi0/0/0/2"]\n'
        nodes = parse_definition(text.encode())['nodes']
        result = da.build(text, nodes, base_intent(), profile_for)
        key = 'cjunosevolved:eth1--xrv9k:Gi0/0/0/2'
        row = next(r for r in result['links'] if r['key'] == key)
        self.assertFalse(row['included'])
        self.assertIn('cjunosevolved', row['reason'])
        self.assertIn('cjunosevolved', result['blocked'])
        self.assertIn(key, result['blocked']['cjunosevolved'])
        self.assertIn('xrv9k', result['blocked'])
        # the unmapped link is excluded from the generated topology; only the six good links remain
        self.assertEqual(len(result['topology']['links']), 6)

    def test_interface_override_resolves_the_blocked_link(self):
        text = FIXTURE_YAML.rstrip() + '\n    - endpoints: ["cjunosevolved:eth1", "xrv9k:Gi0/0/0/2"]\n'
        nodes = parse_definition(text.encode())['nodes']
        key = 'cjunosevolved:eth1--xrv9k:Gi0/0/0/2'
        intent = base_intent(); intent['interfaces'] = {key: {'cjunosevolved': 'et-0/0/2'}}
        result = da.build(text, nodes, intent, profile_for)
        row = next(r for r in result['links'] if r['key'] == key)
        self.assertTrue(row['included'])
        self.assertEqual(row['endpoints']['cjunosevolved']['source'], 'manual')
        self.assertEqual(result['blocked'], {})

    def test_reserved_device_name_is_refused(self):
        text = re.sub(r'\bceos\b', 'prefix', FIXTURE_YAML)
        nodes = parse_definition(text.encode())['nodes']
        result = da.build(text, nodes, base_intent(), profile_for)
        self.assertNotIn('prefix', result['topology']['nodes'])
        self.assertIn('reserved', result['nodes']['prefix']['reason'])


class BuildSettingsPlacementTests(DesignAdapterTestCase):
    def setUp(self):
        self.nodes = lab_nodes()

    def test_node_module_settings_land_on_the_node_and_its_modules_list_replaces_the_designs(self):
        intent = base_intent()
        intent['nodes'] = {'ceos': {'modules': ['bgp', 'vlan'], 'bgp': {'as': 65001}}}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        ceos = result['topology']['nodes']['ceos']
        self.assertEqual(ceos['bgp'], {'as': 65001})
        self.assertEqual(ceos['module'], ['bgp', 'vlan'], "netlab's rule: a device's list is its whole list (here: no OSPF on ceos)")

    def test_top_level_vlans_and_vrfs_land_on_the_topology(self):
        intent = base_intent()
        intent['modules'] = ['ospf', 'bgp', 'vlan', 'vrf']
        intent['vlans'] = {'v10': {'id': 10}}
        intent['vrfs'] = {'vrfA': {'id': 100}}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        self.assertEqual(result['topology']['vlans'], {'v10': {'id': 10}})
        self.assertEqual(result['topology']['vrfs'], {'vrfA': {'id': 100}})

    def test_node_level_vlans_land_on_the_node(self):
        intent = base_intent()
        intent['modules'] = ['ospf', 'bgp', 'vlan']
        intent['nodes'] = {'ceos': {'vlans': {'v10': {'id': 10}}}}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        self.assertEqual(result['topology']['nodes']['ceos']['vlans'], {'v10': {'id': 10}})

    def test_link_settings_land_at_the_right_place(self):
        key = 'ceos:eth1--cjunosevolved:et-0/0/0'
        intent = base_intent()
        intent['links'] = {key: {'prefix': {'ipv4': '10.9.9.0/31'}, 'pool': 'p2p', 'role': 'core',
                                  'type': 'p2p', 'mtu': 1500,
                                  'endpoints': {'ceos': {'ipv4': '10.9.9.0/31', 'ospf': {'cost': 5}}}}}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for)
        idx = result['link_keys'].index(key)
        link = result['topology']['links'][idx]
        self.assertEqual(link['prefix'], {'ipv4': '10.9.9.0/31'})
        self.assertEqual(link['pool'], 'p2p')
        self.assertEqual(link['role'], 'core')
        self.assertEqual(link['type'], 'p2p')
        self.assertEqual(link['mtu'], 1500)
        self.assertEqual(link['ceos']['ipv4'], '10.9.9.0/31')
        self.assertEqual(link['ceos']['ospf'], {'cost': 5})


class BuildPinsTests(DesignAdapterTestCase):
    def setUp(self):
        self.nodes = lab_nodes()

    def test_pins_are_merged_over_intents_own_allocations(self):
        key = 'ceos:eth1--cjunosevolved:et-0/0/0'
        intent = base_intent()
        intent['allocations'] = {'node_ids': {'ceos': 7}}
        pins = {'links': {key: {'ipv4': '10.1.0.100/31'}}}
        result = da.build(FIXTURE_YAML, self.nodes, intent, profile_for, pins=pins)
        self.assertEqual(result['topology']['nodes']['ceos']['id'], 7)
        idx = result['link_keys'].index(key)
        self.assertEqual(result['topology']['links'][idx]['prefix'], {'ipv4': '10.1.0.100/31'})

    def test_pins_do_not_mutate_the_original_intent(self):
        key = 'ceos:eth1--cjunosevolved:et-0/0/0'
        intent = base_intent()
        intent['allocations'] = {}
        original = copy.deepcopy(intent)
        pins = {'links': {key: {'ipv4': '10.1.0.100/31'}}}
        da.build(FIXTURE_YAML, self.nodes, intent, profile_for, pins=pins)
        self.assertEqual(intent, original)


# --- collisions / fix_collisions / overlaps -----------------------------------------------------------------

class CollisionTests(DesignAdapterTestCase):
    LINK_KEYS = ['k1', 'k2', 'k3']
    TRANSFORMED = {'links': [{'prefix': {'ipv4': '10.1.0.0/31'}},
                              {'prefix': {'ipv4': '10.1.0.0/31'}},   # collides with k1
                              {'prefix': {'ipv4': '10.1.0.4/31'}}]}

    def test_unpinned_overlap_is_reported(self):
        found = da.collisions(self.TRANSFORMED, self.LINK_KEYS, {})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]['key'], 'k2')
        self.assertEqual(found[0]['with'], 'k1')
        self.assertEqual(found[0]['family'], 'ipv4')

    def test_pinned_link_itself_is_never_reported(self):
        ledger = {'links': {'k1': {'ipv4': '10.1.0.0/31'}}}
        found = da.collisions(self.TRANSFORMED, self.LINK_KEYS, ledger)
        self.assertEqual([f['key'] for f in found], ['k2'])

    def test_no_collisions_when_nothing_overlaps(self):
        clean = {'links': [{'prefix': {'ipv4': '10.1.0.0/31'}}, {'prefix': {'ipv4': '10.1.0.2/31'}}]}
        self.assertEqual(da.collisions(clean, ['k1', 'k2'], {}), [])

    def test_fix_collisions_proposes_a_free_prefix_of_the_same_size(self):
        pools = {'p2p': {'ipv4': '10.1.0.0/16', 'prefix': 31}, 'loopback': {'ipv4': '10.255.0.0/24'}}
        fixed = da.fix_collisions(self.TRANSFORMED, self.LINK_KEYS, {}, pools)
        self.assertIn('k2', fixed)
        proposed = ipaddress.ip_network(fixed['k2']['ipv4'])
        self.assertEqual(proposed.prefixlen, 31)
        used = [ipaddress.ip_network('10.1.0.0/31'), ipaddress.ip_network('10.1.0.4/31')]
        self.assertFalse(any(proposed.overlaps(u) for u in used))

    def test_fix_collisions_skips_the_avoid_networks(self):
        pools = {'p2p': {'ipv4': '10.1.0.0/16', 'prefix': 31}}
        avoid = (ipaddress.ip_network('10.1.0.6/31'),)
        fixed = da.fix_collisions(self.TRANSFORMED, self.LINK_KEYS, {}, pools, avoid=avoid)
        proposed = ipaddress.ip_network(fixed['k2']['ipv4'])
        self.assertNotEqual(proposed, ipaddress.ip_network('10.1.0.6/31'))


class OverlapsTests(DesignAdapterTestCase):
    def test_overlapping_link_prefixes_and_loopbacks_are_reported(self):
        transformed = {'links': [{'prefix': {'ipv4': '10.1.0.0/31'}}, {'prefix': {'ipv4': '10.1.0.0/31'}}],
                       'nodes': {'a': {'loopback': {'ipv4': '10.255.0.1/32'}},
                                 'b': {'loopback': {'ipv4': '10.255.0.1/32'}}}}
        found = da.overlaps(transformed)
        self.assertEqual(len(found), 2)
        families = {f['family'] for f in found}
        self.assertEqual(families, {'ipv4'})

    def test_clean_plan_reports_nothing(self):
        transformed = {'links': [{'prefix': {'ipv4': '10.1.0.0/31'}}, {'prefix': {'ipv4': '10.1.0.2/31'}}],
                       'nodes': {'a': {'loopback': {'ipv4': '10.255.0.1/32'}},
                                 'b': {'loopback': {'ipv4': '10.255.0.2/32'}}}}
        self.assertEqual(da.overlaps(transformed), [])


# --- plan_summary --------------------------------------------------------------------------------------------

class VlanSegmentOverlapTests(DesignAdapterTestCase):
    def test_access_ports_of_one_vlan_share_its_subnet_without_an_overlap(self):
        # netlab gives every access link of a VLAN the VLAN's prefix (verified with the engine): one segment, one subnet.
        red = {'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'red'}}
        same = {'links': [dict(red, linkindex=1), dict(red, linkindex=2)], 'nodes': {}}
        self.assertEqual(da.overlaps(same), [])
        other = {'links': [dict(red, linkindex=1), {'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'blue'}, 'linkindex': 2}], 'nodes': {}}
        self.assertEqual(da.overlaps(other), [{'family': 'ipv4', 'a': 'link 1', 'b': 'link 2'}], 'two VLANs on one subnet still overlap')
        plain = {'links': [dict(red, linkindex=1), {'prefix': {'ipv4': '172.16.0.0/24'}, 'linkindex': 2}], 'nodes': {}}
        self.assertEqual(len(da.overlaps(plain)), 1, 'a plain link on the VLAN subnet overlaps it')

    def test_a_trunk_whose_native_vlan_is_red_is_part_of_the_red_segment(self):
        # The pinned engine copies the VLAN prefix onto access and native links alike (netsim vlan.py set_link_vlan_prefix).
        transformed = {'links': [{'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'red'}, 'linkindex': 1},
                                 {'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'native': 'red', 'trunk': {'red': {}, 'blue': {}}}, 'linkindex': 2}], 'nodes': {}}
        self.assertEqual(da.overlaps(transformed), [])

    def test_one_vlan_name_on_two_different_subnets_still_overlaps(self):
        transformed = {'links': [{'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'red'}, 'linkindex': 1},
                                 {'prefix': {'ipv4': '172.16.0.0/25'}, 'vlan': {'access': 'red'}, 'linkindex': 2}], 'nodes': {}}
        self.assertEqual(da.overlaps(transformed), [{'family': 'ipv4', 'a': 'link 1', 'b': 'link 2'}])


class VlanSegmentCollisionTests(DesignAdapterTestCase):
    """Audit 2026-10-03 M-7: the engine gives every access (and native) link of a VLAN the VLAN's subnet and
    overwrites any prefix pinned on such a link, so two hosts on one VLAN are one segment, not a collision, and a
    VLAN link's prefix can never be moved by a pin."""
    RED = {'ipv4': '172.16.0.0/24', 'ipv6': '2001:db8:2::/64'}
    POOLS = {'lan': {'ipv4': '172.16.0.0/16', 'prefix': 24}, 'p2p': {'ipv4': '10.1.0.0/16', 'prefix': 31}, 'loopback': {'ipv4': '10.0.0.0/24'}}

    def test_two_access_links_of_one_vlan_are_not_a_collision(self):
        transformed = {'links': [{'prefix': dict(self.RED), 'vlan': {'access': 'red'}}, {'prefix': dict(self.RED), 'vlan': {'access': 'red'}},
                                 {'prefix': {'ipv4': '10.1.0.0/31'}}]}
        keys = ['h1:eth1--sw:eth1', 'h2:eth1--sw:eth2', 'r2:ge-0/0/0--sw:eth3']
        self.assertEqual(da.collisions(transformed, keys, {}), [])
        self.assertEqual(da.fix_collisions(transformed, keys, {}, self.POOLS), {})

    def test_an_access_port_and_a_trunk_with_that_native_vlan_are_not_a_collision(self):
        transformed = {'links': [{'prefix': dict(self.RED), 'vlan': {'access': 'red'}},
                                 {'prefix': dict(self.RED), 'vlan': {'native': 'red', 'trunk': {'red': {}, 'blue': {}}}}]}
        self.assertEqual(da.collisions(transformed, ['k1', 'k2'], {}), [])

    def test_a_vlan_given_only_on_one_link_end_is_still_its_segment(self):
        transformed = {'links': [{'prefix': dict(self.RED), 'interfaces': [{'node': 'h1'}, {'node': 'sw', 'vlan': {'access': 'red'}}]},
                                 {'prefix': dict(self.RED), 'interfaces': [{'node': 'h2'}, {'node': 'sw', 'vlan': {'access': 'red'}}]}]}
        self.assertEqual(da.collisions(transformed, ['k1', 'k2'], {}), [])
        self.assertEqual(da.overlaps(transformed), [])

    def test_two_vlans_on_one_subnet_still_collide(self):
        transformed = {'links': [{'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'red'}}, {'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'blue'}}]}
        found = da.collisions(transformed, ['k1', 'k2'], {})
        self.assertEqual(found, [{'key': 'k2', 'family': 'ipv4', 'prefix': '172.16.0.0/24', 'with': 'k1', 'vlan': 'blue'}])
        self.assertEqual(da.fix_collisions(transformed, ['k1', 'k2'], {}, self.POOLS), {}, 'the engine owns a VLAN link prefix: no pin can move it')

    def test_a_plain_link_on_a_vlan_subnet_is_the_one_that_moves(self):
        # k1 sorts first, so before the fix the VLAN link k2 was reported and given a pin the engine then overwrote.
        transformed = {'links': [{'prefix': {'ipv4': '172.16.0.0/30'}}, {'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'red'}}]}
        found = da.collisions(transformed, ['k1', 'k2'], {})
        self.assertEqual(found, [{'key': 'k1', 'family': 'ipv4', 'prefix': '172.16.0.0/30', 'with': 'k2'}])
        fixed = da.fix_collisions(transformed, ['k1', 'k2'], {}, {'lan': {'ipv4': '172.16.0.0/16'}})
        self.assertEqual(list(fixed), ['k1'])
        self.assertFalse(ipaddress.ip_network(fixed['k1']['ipv4']).overlaps(ipaddress.ip_network('172.16.0.0/24')))

    def test_a_vlan_subnet_over_a_pinned_prefix_is_reported_on_every_vlan_link_and_never_fixed(self):
        transformed = {'links': [{'prefix': {'ipv4': '172.16.0.0/30'}}, {'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'red'}},
                                 {'prefix': {'ipv4': '172.16.0.0/24'}, 'vlan': {'access': 'red'}}]}
        pinned = {'links': {'k1': {'ipv4': '172.16.0.0/30'}}}
        found = da.collisions(transformed, ['k1', 'k2', 'k3'], pinned)
        self.assertEqual([(f['key'], f['with'], f.get('vlan')) for f in found], [('k2', 'k1', 'red'), ('k3', 'k1', 'red')])
        self.assertEqual(da.fix_collisions(transformed, ['k1', 'k2', 'k3'], pinned, self.POOLS), {})


class PlanSummaryTests(DesignAdapterTestCase):
    def test_device_rows_neighbours_bgp_ospf_and_link_rows(self):
        transformed = {
            '_netlab_version': '26.9',
            'module': ['ospf', 'bgp'],
            'addressing': {'mgmt': {'ipv4': '172.20.20.0/24'}, 'loopback': {'ipv4': '10.255.0.0/24'}},
            'nodes': {
                'ceos': {'device': 'eos', 'id': 1, 'role': 'router', 'module': ['ospf', 'bgp'],
                         'loopback': {'ipv4': '10.255.0.1/32'},
                         'bgp': {'as': 65000, 'router_id': '10.255.0.1',
                                 'neighbors': [{'name': 'cjunosevolved', 'as': 65000, 'ipv4': '10.1.0.1'}]},
                         'ospf': {'area': '0.0.0.0', 'router_id': '10.255.0.1'},
                         'interfaces': [{'ifname': 'Ethernet1', 'ipv4': '10.1.0.0/31',
                                         'neighbors': [{'node': 'cjunosevolved', 'ifname': 'et-0/0/0.0'}],
                                         'ospf': {'cost': 10}}]},
                'cjunosevolved': {'device': 'vptx', 'id': 2, 'role': 'router', 'module': ['ospf', 'bgp'],
                                   'loopback': {'ipv4': '10.255.0.2/32'},
                                   'interfaces': [{'ifname': 'et-0/0/0.0', 'ipv4': '10.1.0.1/31',
                                                   'neighbors': [{'node': 'ceos', 'ifname': 'Ethernet1'}]}]},
            },
            'links': [{'linkindex': 1, 'prefix': {'ipv4': '10.1.0.0/31'},
                       'interfaces': [{'node': 'ceos', 'ifname': 'Ethernet1', 'ipv4': '10.1.0.0/31'},
                                      {'node': 'cjunosevolved', 'ifname': 'et-0/0/0.0', 'ipv4': '10.1.0.1/31'}]}],
        }
        mapping = {'ceos:eth1--cjunosevolved:et-0/0/0': {
            'ceos': {'clab': 'eth1', 'nos': 'Ethernet1'},
            'cjunosevolved': {'clab': 'et-0/0/0', 'nos': 'et-0/0/0'}}}
        summary = da.plan_summary(transformed, mapping)

        self.assertEqual(summary['engine_version'], '26.9')
        self.assertNotIn('mgmt', summary['addressing'])
        self.assertIn('loopback', summary['addressing'])

        by_name = {d['name']: d for d in summary['devices']}
        self.assertEqual(by_name['ceos']['interfaces'][0]['clab'], 'eth1')
        self.assertEqual(by_name['ceos']['interfaces'][0]['neighbors'],
                          [{'node': 'cjunosevolved', 'ifname': 'et-0/0/0.0', 'ipv4': '', 'ipv6': ''}])
        self.assertEqual(by_name['ceos']['bgp']['as'], 65000)
        self.assertEqual(by_name['ceos']['bgp']['neighbors'][0]['name'], 'cjunosevolved')
        self.assertEqual(by_name['ceos']['ospf'], {'area': '0.0.0.0', 'router_id': '10.255.0.1'})
        self.assertEqual(by_name['ceos']['interfaces'][0]['ospf'], {'cost': 10})

        # The Junos ".0" unit form matches the mapping recorded for the bare interface name.
        self.assertEqual(by_name['cjunosevolved']['interfaces'][0]['ifname'], 'et-0/0/0.0')
        self.assertEqual(by_name['cjunosevolved']['interfaces'][0]['clab'], 'et-0/0/0')

        self.assertEqual(len(summary['links']), 1)
        self.assertEqual(summary['links'][0]['prefix'], {'ipv4': '10.1.0.0/31', 'ipv6': ''})


# --- one real-engine test -------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class RealEngineTests(unittest.TestCase):
    """Runs the pinned engine for real against the fixture's built topology; no mocks."""

    def setUp(self):
        self.work_root = tempfile.mkdtemp(prefix='design-adapter-test-')
        self.addCleanup(shutil.rmtree, self.work_root, ignore_errors=True)

    def _run_netlab(self, topology, subdir='run'):
        workdir = os.path.join(self.work_root, subdir)
        home = os.path.join(workdir, 'home')
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(workdir, 'topology.yml'), 'w', encoding='utf-8') as handle:
            yaml.safe_dump(topology, handle, sort_keys=False)
        env = {'PATH': os.environ.get('PATH', ''), 'HOME': home, 'LANG': os.environ.get('LANG', 'C.UTF-8')}
        proc = subprocess.run(['netlab', 'create', '-p', 'external', '-o', 'config',
                                '-o', 'yaml=transformed.yaml', 'topology.yml'],
                               cwd=workdir, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(workdir, 'transformed.yaml'), encoding='utf-8') as handle:
            return yaml.safe_load(handle)

    def test_fresh_design_has_no_collisions_then_a_forced_pin_produces_one(self):
        nodes = lab_nodes()
        intent = base_intent()
        built = da.build(FIXTURE_YAML, nodes, intent, profile_for)
        self.assertEqual(built['link_keys'], FIXTURE_LINK_KEYS)

        transformed = self._run_netlab(built['topology'], subdir='fresh')
        ledger = di.ledger_from_plan(transformed, built['link_keys'])

        # Node ids 1..5 in definition (== emission) order; the four routers get loopbacks.
        self.assertEqual(ledger['node_ids'],
                          {'ceos': 1, 'cjunosevolved': 2, 'vjunos-switch': 3, 'xrv9k': 4, 'host1': 5})
        for router in ('ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k'):
            self.assertIn('ipv4', ledger['loopbacks'][router])
        self.assertNotIn('host1', ledger['loopbacks'])

        # Six link prefixes, keyed by the manager's own link keys.
        self.assertEqual(set(ledger['links']), set(FIXTURE_LINK_KEYS))

        self.assertEqual(da.collisions(transformed, built['link_keys'], {}), [])
        self.assertEqual(da.overlaps(transformed), [])

        summary = da.plan_summary(transformed, built['mapping'])
        by_name = {d['name']: d for d in summary['devices']}
        xrv9k_ifaces = {i['ifname']: i['clab'] for i in by_name['xrv9k']['interfaces']}
        self.assertEqual(xrv9k_ifaces['GigabitEthernet0/0/0/0'], 'Gi0/0/0/0')
        cjunos_ifaces = {i['ifname']: i['clab'] for i in by_name['cjunosevolved']['interfaces']}
        self.assertEqual(cjunos_ifaces['et-0/0/0.0'], 'et-0/0/0')

        # Pin the first link (sorted key order) to the prefix the engine gave the second link; on a
        # second run the engine's own sequential p2p allocator hands that same prefix to a different,
        # still-unpinned link, so collisions() must name it and fix_collisions() must clear it.
        first_key, second_key = built['link_keys'][0], built['link_keys'][1]
        forced_prefix = ledger['links'][second_key]['ipv4']
        pins = {'links': {first_key: {'ipv4': forced_prefix}}}
        pinned_built = da.build(FIXTURE_YAML, nodes, intent, profile_for, pins=pins)
        pinned_transformed = self._run_netlab(pinned_built['topology'], subdir='pinned')

        pin_ledger = {'links': {first_key: {'ipv4': forced_prefix}}}
        found = da.collisions(pinned_transformed, pinned_built['link_keys'], pin_ledger)
        self.assertTrue(found, 'expected a collision after pinning the first link over the second\'s prefix')
        self.assertEqual(found[0]['with'], first_key)
        colliding_key = found[0]['key']
        self.assertNotEqual(colliding_key, first_key)

        pools = pinned_built['topology']['addressing']
        fixed = da.fix_collisions(pinned_transformed, pinned_built['link_keys'], pin_ledger, pools)
        self.assertIn(colliding_key, fixed)
        proposed = ipaddress.ip_network(fixed[colliding_key]['ipv4'])
        current_prefixes = []
        for link in pinned_transformed.get('links') or []:
            prefix = link.get('prefix') if isinstance(link, dict) else None
            if isinstance(prefix, dict) and 'ipv4' in prefix:
                current_prefixes.append(ipaddress.ip_network(prefix['ipv4']))
        self.assertFalse(any(proposed.overlaps(p) for p in current_prefixes))



# --- regressions from the risk review of 1.30.43 --------------------------------------------------------------

class ReviewRegressionTests(unittest.TestCase):

    def test_overlaps_reports_a_plan_prefix_inside_a_guarded_network_but_never_guarded_against_guarded(self):
        import ipaddress
        transformed = {'links': [{'linkindex': 1, 'prefix': {'ipv4': '172.20.20.10/31'}}, {'linkindex': 2, 'prefix': {'ipv4': '10.1.0.0/31'}}],
                       'nodes': {'r1': {'loopback': {'ipv4': '10.255.0.1/32'}}}}
        avoid = [('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24')), ('device r1', ipaddress.ip_network('172.20.20.101/32'))]
        found = da.overlaps(transformed, avoid=avoid)
        self.assertEqual([(f['a'], f['b']) for f in found], [('link 1', 'management mgmt ipv4-subnet')])
        self.assertEqual(da.overlaps({'links': [], 'nodes': {}}, avoid=avoid), [], 'guarded networks are not compared with each other')

    def test_link_prefixes_returns_strings_keyed_by_link(self):
        transformed = {'links': [{'prefix': {'ipv4': '10.1.0.0/31', 'ipv6': '2001:db8:1::/64'}}, {'prefix': {'ipv4': '10.1.0.2/31'}}]}
        self.assertEqual(da.link_prefixes(transformed, ['a', 'b', 'c']), {'a': {'ipv4': '10.1.0.0/31', 'ipv6': '2001:db8:1::/64'}, 'b': {'ipv4': '10.1.0.2/31'}})




class SecondPassRegressionTests(unittest.TestCase):

    def test_overlaps_checks_every_interface_address_against_the_guarded_networks_only(self):
        import ipaddress
        transformed = {'links': [{'linkindex': 1, 'prefix': {'ipv4': '10.1.0.0/31'}}],
                       'nodes': {'r1': {'loopback': {'ipv4': '10.255.0.1/32'},
                                        'interfaces': [{'ifname': 'Ethernet1', 'ipv4': '10.1.0.0/31'}, {'ifname': 'Loopback1', 'ipv4': '172.20.20.101/32', 'vrf': 'red'}]}}}
        avoid = [('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))]
        found = da.overlaps(transformed, avoid=avoid)
        self.assertEqual([(f['a'], f['b']) for f in found], [('Loopback1 of r1', 'management mgmt ipv4-subnet')],
                         'an interface address inside a link prefix is not an overlap; a VRF loopback in the management network is')


class ThirdPassRegressionTests(unittest.TestCase):

    def test_management_networks_fall_back_to_containerlabs_defaults(self):
        import ipaddress
        text = 'name: x\ntopology:\n  nodes:\n    r1: {kind: arista_ceos, mgmt-ipv4: 172.20.20.11}\n'
        found = dict((label, net) for label, net in da.management_networks(text, [{'address': '172.20.20.11', 'short_name': 'r1'}]))
        self.assertEqual(found['containerlab default management ipv4-subnet'], ipaddress.ip_network('172.20.20.0/24'))
        self.assertEqual(found['containerlab default management ipv6-subnet'], ipaddress.ip_network('3fff:172:20:20::/64'))
        self.assertEqual(found['device r1'], ipaddress.ip_network('172.20.20.11/32'))
        auto = 'name: x\nmgmt:\n  ipv4-subnet: auto\ntopology:\n  nodes:\n    r1: {kind: arista_ceos}\n'
        found = dict((label, net) for label, net in da.management_networks(auto, [{'address': '10.44.5.9', 'short_name': 'r1'}]))
        self.assertEqual(found['management network of r1'], ipaddress.ip_network('10.44.5.0/24'))
        self.assertNotIn('containerlab default management ipv4-subnet', found)

    def test_overlaps_checks_the_whole_interface_subnet(self):
        import ipaddress
        transformed = {'links': [], 'nodes': {'r1': {'interfaces': [{'ifname': 'Ethernet1', 'ipv4': '172.20.0.1/16'}]}}}
        found = da.overlaps(transformed, avoid=[('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))])
        self.assertEqual([(f['a'], f['b']) for f in found], [('network of Ethernet1 of r1', 'management mgmt ipv4-subnet')])

if __name__ == '__main__':
    unittest.main()
