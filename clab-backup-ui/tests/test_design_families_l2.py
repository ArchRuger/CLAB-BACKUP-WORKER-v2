"""Generation tests for the *Network design* capability's layer-2, first-hop-gateway and overlay
families: VLANs, LAG/LACP, VRRP/anycast gateway, VXLAN+EVPN and STP, against the pinned real `netlab`
engine and the four-node restore-square fixture (docs/multi-platform-restore), copied here as a text
constant so nothing is read from /srv or a deployed manager's data. A sibling worker covers IS-IS,
static routes, VRFs, BGP policy and BFD in test_design_families_routing.py.

Every generation test drives app/design_adapter.py's `build()` and app/design_engine.py's
`run_generation()` directly (the same real child-process engine app/network_design.py uses, minus the
HTTP/job bookkeeping), against a fresh temporary work_root -- never `/srv` or a running manager's data
directory. `app.network_design.NetworkDesign.compatibility()` is a plain function of `(intent, nodes)`
with no state on `self`, so it is called unbound (`NetworkDesign.compatibility(None, ...)`) to exercise
the exact pre-engine blocking logic without needing a Store or an app.

Needs the pinned `netlab` engine on PATH (CLAUDE.md's PATH="$PWD/.venv/bin:$PATH" prefix provides it)
and is skipped, with a message, when it is absent.
"""
import shutil
import tempfile
import unittest

from app import design_adapter as da
from app import design_capabilities as dc
from app import design_engine as de
from app import design_intent as di
from app import network_design as nd
from app.discovery import parse_definition

HAS_NETLAB = shutil.which('netlab') is not None
SKIP_REASON = 'netlab is not on PATH for this test run'

# The four-node restore-square fixture (docs/multi-platform-restore), copied verbatim from
# tests/test_design_adapter.py's FIXTURE_YAML: nothing is read from /srv at test time.
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


def lab_nodes():
    return parse_definition(FIXTURE_YAML.encode())['nodes']


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class FamilyTestCase(unittest.TestCase):
    """Shared fixture and helpers: a fresh work_root per test, the lab-shaped arguments `design_intent
    .validate()` wants, and thin wrappers around build -> compatibility -> the real engine."""

    def setUp(self):
        self.work_root = tempfile.mkdtemp(prefix='design-families-l2-')
        self.addCleanup(shutil.rmtree, self.work_root, ignore_errors=True)
        self.nodes = lab_nodes()
        self.lab_nodes_map = {n['definition_node']: n.get('kind', '') for n in self.nodes}
        self.lab_links = [l['key'] for l in da.parse_links(FIXTURE_YAML) if not l['problem']]
        self.management = da.management_networks(FIXTURE_YAML, self.nodes)
        self.schema = dc.engine_data()

    def validate(self, intent):
        return di.validate(intent, lab_nodes=self.lab_nodes_map, lab_links=self.lab_links,
                            schema=self.schema, management=self.management)

    def assertValid(self, intent):
        problems = self.validate(intent)
        self.assertEqual(problems, [], problems)

    def assertRefused(self, intent, path, message_fragment):
        problems = self.validate(intent)
        matches = [p for p in problems if p['path'] == path and message_fragment in p['message']]
        self.assertTrue(matches, 'expected a problem at %r containing %r, got %r' % (path, message_fragment, problems))

    def build(self, intent, pins=None):
        return da.build(FIXTURE_YAML, self.nodes, intent, dc.profile_for, pins=pins)

    def compatibility(self, intent, built_nodes):
        # NetworkDesign.compatibility() reads no attribute of `self`; calling it unbound exercises the
        # manager's real pre-engine blocking logic without a Store or an app.
        return nd.NetworkDesign.compatibility(None, intent, built_nodes)

    def run_engine(self, topology):
        return de.run_generation(self.work_root, topology)

    def generate(self, intent):
        """Validates, builds, checks compatibility and runs the real engine once; asserts a clean
        design, no compatibility blocking and a successful run. Returns (built, result)."""
        self.assertValid(intent)
        built = self.build(intent)
        _, blocking = self.compatibility(intent, built['nodes'])
        self.assertEqual(blocking, [], blocking)
        result = self.run_engine(built['topology'])
        self.assertTrue(result['ok'], result.get('errors'))
        return built, result

    def assertByteIdenticalOnRerun(self, intent):
        """Generates `intent` twice (two independent engine child processes) and asserts every node's
        artifacts are byte-for-byte identical, per design_adapter.build()'s ordering guarantee. Returns
        the first (built, result) pair for content assertions."""
        first = self.generate(intent)
        second = self.generate(intent)
        self.assertEqual(set(first[1]['artifacts']), set(second[1]['artifacts']))
        for node, entries in first[1]['artifacts'].items():
            self.assertEqual(dict(entries), dict(second[1]['artifacts'].get(node, [])), node)
        return first


class VlanFamilyTests(FamilyTestCase):
    """VLANs (schema family `vlan`): access ports on host1's natural access links and a trunk between
    two routers, on cEOS and both Junos kinds. XRv9k has no `vlan` module upstream."""

    def intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['vlan']
        intent['vlans'] = {'red': {'id': 100}, 'blue': {'id': 200}}
        # vlan is unsupported on iosxr (see test_xrv9k_has_no_vlan_module_upstream); excluded here so
        # the other three kinds can be generated for real.
        intent['nodes'] = {'xrv9k': {'role': 'exclude'}}
        intent['links'] = {
            'host1:eth1--vjunos-switch:ge-0/0/2': {'vlan': {'access': 'red'}},
            'ceos:eth3--host1:eth2': {'vlan': {'access': 'blue'}},
            'ceos:eth1--cjunosevolved:et-0/0/0': {'vlan': {'trunk': ['red', 'blue']}},
            'cjunosevolved:et-0/0/1--vjunos-switch:ge-0/0/0': {'vlan': {'trunk': ['red', 'blue']}},
        }
        return intent

    def test_validates_clean(self):
        self.assertValid(self.intent())

    def test_refuses_undefined_vlan_reference(self):
        intent = self.intent()
        intent['links']['ceos:eth3--host1:eth2'] = {'vlan': {'access': 'green'}}
        self.assertRefused(intent, 'links.ceos:eth3--host1:eth2.vlan.access', 'No VLAN named green is defined')

    def test_refuses_vlan_id_out_of_range(self):
        intent = self.intent()
        intent['vlans']['red']['id'] = 9000
        self.assertRefused(intent, 'vlans.red.id', 'must be between 1 and 4094')

    def test_refuses_unknown_vlan_setting(self):
        intent = self.intent()
        intent['vlans']['red']['bogus'] = 'x'
        self.assertRefused(intent, 'vlans.red.bogus', 'Unknown setting')

    def test_ceos_and_junos_generate_vlan_configuration(self):
        built, result = self.assertByteIdenticalOnRerun(self.intent())
        self.assertNotIn('xrv9k', result['artifacts'])

        ceos = dict(result['artifacts']['ceos'])
        self.assertIn('vlan', ceos)
        self.assertIn('vlan 100', ceos['vlan'])
        self.assertIn('vlan 200', ceos['vlan'])
        self.assertIn('switchport mode trunk', ceos['vlan'])
        self.assertIn('switchport trunk allowed vlan 100,200', ceos['vlan'])
        self.assertIn('switchport access vlan 200', ceos['vlan'])

        cjunos = dict(result['artifacts']['cjunosevolved'])
        self.assertIn('vlan-id 100', cjunos['vlan'])
        self.assertIn('vlan-id 200', cjunos['vlan'])
        self.assertIn('family ethernet-switching', cjunos['vlan'])
        self.assertIn('interface-mode trunk;', cjunos['vlan'])

        vswitch = dict(result['artifacts']['vjunos-switch'])
        self.assertIn('vlan-id 100', vswitch['vlan'])
        self.assertIn('family ethernet-switching', vswitch['vlan'])
        self.assertIn('interface-mode trunk;', vswitch['vlan'])   # its et-0/0/0 side of the trunk link
        self.assertIn('members red', vswitch['vlan'])              # host1's access port

    def test_xrv9k_has_no_vlan_module_upstream(self):
        result = dc.resolve('vlan', 'cisco_xrv9k')
        self.assertFalse(result['engine'])
        self.assertEqual(result['level'], 'unsupported')
        self.assertIn('iosxr', result['reason'])

        # Included rather than excluded, NetworkDesign.compatibility() blocks the whole generation
        # before the engine ever runs: nothing is dropped or downgraded silently.
        intent = self.intent()
        intent['nodes'] = {}
        built = self.build(intent)
        _, blocking = self.compatibility(intent, built['nodes'])
        self.assertTrue(any('xrv9k' in b and 'vlan' in b and 'not supported' in b for b in blocking), blocking)


class LagFamilyTests(FamilyTestCase):
    """LAG/LACP (schema family `lag`). netlab's lag module (netsim/modules/lag.py,
    process_lag_link()/normalized_members()) requires the parent (bundle) link to carry an explicit
    `lag.members` list naming its physical member links, and errors "Link ... has 'lag' attribute but
    no 'lag.members'" when it is absent -- there is no other way to form a bundle. But
    design_intent.DENIED_KEYS refuses the key `members` at every level and depth, whatever the engine
    schema says (checked by scan()'s guard before anything else looks at the document). So a LAG/LACP
    bundle cannot be expressed through schema 1 today; the two capability-only checks below still hold
    without running the engine."""

    PARALLEL = """name: parallel
topology:
  nodes:
    ceos: {kind: arista_ceos, image: n24l/ceos:4.35.0F}
    vjunos-switch: {kind: juniper_vjunosswitch, image: n24l/vjunos-switch:23.2R1.14}
  links:
    - endpoints: ["ceos:eth1", "vjunos-switch:ge-0/0/0"]
    - endpoints: ["ceos:eth2", "vjunos-switch:ge-0/0/1"]
"""

    def test_a_bundle_of_two_parallel_links_generates_a_port_channel_and_an_ae_interface(self):
        # The acceptance lab has no parallel links: a two-router topology with two is used for the engine run.
        nodes = parse_definition(self.PARALLEL.encode())['nodes']
        K1, K2 = 'ceos:eth1--vjunos-switch:ge-0/0/0', 'ceos:eth2--vjunos-switch:ge-0/0/1'
        intent = dict(di.empty_intent(), modules=['lag', 'ospf'], links={K1: {'lag': {'members': [K2]}}})
        problems = di.validate(intent, lab_nodes={n['definition_node']: n['kind'] for n in nodes}, lab_links=[K1, K2], schema=self.schema, management=())
        self.assertEqual(problems, [])
        built = da.build(self.PARALLEL, nodes, intent, dc.profile_for)
        self.assertEqual(len(built['topology']['links']), 1)
        run = self.run_engine(built['topology'])
        self.assertTrue(run['ok'], run.get('errors'))
        eos = '\n'.join(text for module, text in run['artifacts']['ceos']); junos = '\n'.join(text for module, text in run['artifacts']['vjunos-switch'])
        self.assertIn('interface port-channel1', eos.lower()); self.assertEqual(eos.count('channel-group 1 mode active'), 2, 'both member ports join the bundle')
        self.assertIn('interface Ethernet2', eos)
        self.assertIn('ae1', junos, 'netlab numbers the bundle from lag.ifindex 1'); self.assertEqual(junos.count('802.3ad ae1'), 2)
        self.assertIn('ip address', eos, 'the bundle carries the link addressing')

    def test_lag_and_lacp_engine_support_on_ceos_and_junos(self):
        for kind in ('arista_ceos', 'juniper_vjunosswitch', 'juniper_cjunosevolved'):
            for feature in ('lag', 'lacp'):
                result = dc.resolve(feature, kind)
                self.assertTrue(result['engine'], (kind, feature, result))
                self.assertEqual(result['level'], 'generated_not_live_tested', (kind, feature, result))

    def test_lag_and_lacp_unsupported_on_xrv9k(self):
        for feature in ('lag', 'lacp'):
            result = dc.resolve(feature, 'cisco_xrv9k')
            self.assertFalse(result['engine'], result)
            self.assertEqual(result['level'], 'unsupported', result)
            self.assertIn('iosxr', result['reason'])


class GatewayFamilyTests(FamilyTestCase):
    """First-hop gateway (schema family `gateway`): VRRP on all four kinds; anycast only on cEOS and
    the two Junos kinds -- the XR profile's resolved gateway.protocol feature flag has no 'anycast'
    entry."""

    def vrrp_intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['gateway']
        intent['links'] = {
            'ceos:eth3--host1:eth2': {'gateway': {'protocol': 'vrrp'}},
            'host1:eth1--vjunos-switch:ge-0/0/2': {'gateway': {'protocol': 'vrrp'}},
            # A router-router link only has the default /31 (two usable addresses, no room for a third
            # virtual address); widen it so xrv9k's own vrrp fragment can be generated too. This is an
            # addressing-size fact, not a capability limit -- vrrp itself is listed as engine-supported
            # (generated_not_live_tested) on every one of the four kinds.
            'vjunos-switch:ge-0/0/1--xrv9k:Gi0/0/0/0': {
                'prefix': {'ipv4': '10.9.9.0/28', 'ipv6': '2001:db8:9::/60'},
                'gateway': {'protocol': 'vrrp'}},
        }
        return intent

    def test_vrrp_validates_clean(self):
        self.assertValid(self.vrrp_intent())

    def test_refuses_unknown_gateway_protocol(self):
        intent = self.vrrp_intent()
        intent['links']['ceos:eth3--host1:eth2'] = {'gateway': {'protocol': 'hsrp'}}
        self.assertRefused(intent, 'links.ceos:eth3--host1:eth2.gateway.protocol', 'Choose one of: anycast, vrrp')

    def test_refuses_unknown_gateway_setting(self):
        intent = self.vrrp_intent()
        intent['links']['ceos:eth3--host1:eth2']['gateway']['bogus'] = 1
        self.assertRefused(intent, 'links.ceos:eth3--host1:eth2.gateway.bogus', 'Unknown setting')

    def test_vrrp_on_all_four_kinds(self):
        built, result = self.assertByteIdenticalOnRerun(self.vrrp_intent())
        ceos = dict(result['artifacts']['ceos'])
        self.assertIn('vrrp 1 ipv4', ceos['gateway'])
        self.assertIn('vrrp 1 preempt', ceos['gateway'])

        vswitch = dict(result['artifacts']['vjunos-switch'])
        self.assertIn('vrrp {', vswitch['gateway'])
        self.assertIn('vrrp-group 1', vswitch['gateway'])

        xrv9k = dict(result['artifacts']['xrv9k'])
        self.assertIn('router vrrp', xrv9k['gateway'])
        self.assertIn('vrrp 1 version 3', xrv9k['gateway'])

    def anycast_intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['gateway']
        # anycast is unsupported on iosxr (see test_xrv9k_anycast_gateway_blocked); excluded here.
        intent['nodes'] = {'xrv9k': {'role': 'exclude'}}
        intent['links'] = {
            'ceos:eth3--host1:eth2': {'gateway': {'protocol': 'anycast'}},
            'host1:eth1--vjunos-switch:ge-0/0/2': {'gateway': {'protocol': 'anycast'}},
        }
        return intent

    def test_anycast_on_ceos_and_junos_only(self):
        built, result = self.assertByteIdenticalOnRerun(self.anycast_intent())
        self.assertNotIn('xrv9k', result['artifacts'])

        ceos = dict(result['artifacts']['ceos'])
        self.assertIn('ip virtual-router address', ceos['gateway'])
        self.assertIn('ip virtual-router mac-address', ceos['gateway'])

        vswitch = dict(result['artifacts']['vjunos-switch'])
        self.assertIn('virtual-gateway-address', vswitch['gateway'])
        self.assertIn('virtual-gateway-v4-mac', vswitch['gateway'])

    def test_xrv9k_anycast_gateway_blocked(self):
        result = dc.resolve('anycast_gateway', 'cisco_xrv9k', requested_modules={'gateway'})
        self.assertFalse(result['engine'])
        self.assertEqual(result['level'], 'unsupported')
        self.assertIn('anycast', result['reason'])

        intent = di.empty_intent()
        intent['modules'] = ['gateway']
        intent['links'] = {
            'ceos:eth3--host1:eth2': {'gateway': {'protocol': 'anycast'}},
            'vjunos-switch:ge-0/0/1--xrv9k:Gi0/0/0/0': {'gateway': {'protocol': 'anycast'}},
        }
        built = self.build(intent)
        _, blocking = self.compatibility(intent, built['nodes'])
        self.assertTrue(any('xrv9k' in b and 'anycast_gateway' in b for b in blocking), blocking)


class VxlanEvpnFamilyTests(FamilyTestCase):
    """VXLAN + EVPN (schema families `vlan`, `vxlan`, `bgp`, `evpn` together): EOS `interface vxlan 1`
    / `vxlan vlan ... vni`, Junos `vtep-source-interface` / `vni`, the `evpn` address family on BGP.
    XRv9k is blocked on `vlan` and `vxlan` (both unsupported on the iosxr profile) before `evpn` itself
    is ever reached."""

    def intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['vlan', 'vxlan', 'bgp', 'evpn']
        intent['nodes'] = {'xrv9k': {'role': 'exclude'}}
        intent['bgp'] = {'as': 65000}
        intent['vlans'] = {'red': {'id': 100}, 'blue': {'id': 200}}
        intent['links'] = {
            'host1:eth1--vjunos-switch:ge-0/0/2': {'vlan': {'access': 'red'}},
            'ceos:eth3--host1:eth2': {'vlan': {'access': 'blue'}},
        }
        return intent

    def test_validates_clean(self):
        self.assertValid(self.intent())

    def test_refuses_undefined_vlan_reference(self):
        intent = self.intent()
        intent['links']['ceos:eth3--host1:eth2'] = {'vlan': {'access': 'green'}}
        self.assertRefused(intent, 'links.ceos:eth3--host1:eth2.vlan.access', 'No VLAN named green is defined')

    def test_refuses_bad_evpn_transport(self):
        intent = self.intent()
        intent['evpn'] = {'transport': 'gre'}
        self.assertRefused(intent, 'evpn.transport', 'Choose one of: vxlan, mpls, sr')

    def test_eos_and_junos_generate_vxlan_evpn(self):
        built, result = self.assertByteIdenticalOnRerun(self.intent())
        self.assertNotIn('xrv9k', result['artifacts'])

        ceos = dict(result['artifacts']['ceos'])
        self.assertIn('interface vxlan 1', ceos['vxlan'])
        self.assertIn('vxlan source-interface Loopback0', ceos['vxlan'])
        self.assertIn('vxlan vlan 200 vni 100200', ceos['vxlan'])
        self.assertIn('address-family evpn', ceos['evpn'])

        vswitch = dict(result['artifacts']['vjunos-switch'])
        self.assertIn('vtep-source-interface', vswitch['vxlan'])
        self.assertIn('vni 100100', vswitch['vxlan'])
        self.assertIn('family evpn', vswitch['evpn'])
        self.assertIn('encapsulation vxlan', vswitch['evpn'])

    def test_xrv9k_blocked_on_vlan_and_vxlan(self):
        self.assertEqual(dc.resolve('vlan', 'cisco_xrv9k')['level'], 'unsupported')
        self.assertEqual(dc.resolve('vxlan', 'cisco_xrv9k')['level'], 'unsupported')

        intent = self.intent()
        intent['nodes'] = {}
        built = self.build(intent)
        _, blocking = self.compatibility(intent, built['nodes'])
        self.assertTrue(any('xrv9k' in b and 'vlan' in b and 'not supported' in b for b in blocking), blocking)
        self.assertTrue(any('xrv9k' in b and 'vxlan' in b and 'not supported' in b for b in blocking), blocking)


class StpFamilyTests(FamilyTestCase):
    """Spanning tree (schema family `stp`): cEOS only among the four kinds. netlab's stp module also
    requires the vlan module to be enabled alongside it ("Module stp requires module vlan"), so the
    fixture intent pairs them, matching how the feature would actually be offered."""

    def intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['stp', 'vlan']
        intent['vlans'] = {'red': {'id': 100}}
        intent['nodes'] = {'xrv9k': {'role': 'exclude'}, 'cjunosevolved': {'role': 'exclude'},
                           'vjunos-switch': {'role': 'exclude'}}
        intent['links'] = {'ceos:eth3--host1:eth2': {'vlan': {'access': 'red'}}}
        return intent

    def test_validates_clean(self):
        self.assertValid(self.intent())

    def test_refuses_bad_protocol(self):
        intent = self.intent()
        intent['stp'] = {'protocol': 'bogus'}
        self.assertRefused(intent, 'stp.protocol', 'Choose one of: stp, rstp, mstp, pvrst')

    def test_refuses_unknown_setting(self):
        intent = self.intent()
        intent['nodes']['ceos'] = {'stp': {'bogus': 1}}
        self.assertRefused(intent, 'nodes.ceos.stp.bogus', 'Unknown setting')

    def test_ceos_generates_stp_configuration(self):
        built, result = self.assertByteIdenticalOnRerun(self.intent())
        self.assertNotIn('cjunosevolved', result['artifacts'])
        self.assertNotIn('vjunos-switch', result['artifacts'])
        self.assertNotIn('xrv9k', result['artifacts'])

        ceos = dict(result['artifacts']['ceos'])
        self.assertIn('spanning-tree mode rstp', ceos['stp'])

    def test_stp_unsupported_on_junos_and_iosxr(self):
        for kind in ('juniper_vjunosswitch', 'juniper_cjunosevolved', 'cisco_xrv9k'):
            result = dc.resolve('stp', kind)
            self.assertFalse(result['engine'], (kind, result))
            self.assertEqual(result['level'], 'unsupported', (kind, result))

        intent = di.empty_intent()
        intent['modules'] = ['stp', 'vlan']
        intent['vlans'] = {'red': {'id': 100}}
        built = self.build(intent)
        _, blocking = self.compatibility(intent, built['nodes'])
        for kind_name in ('cjunosevolved', 'vjunos-switch', 'xrv9k'):
            self.assertTrue(any(b.startswith(kind_name + ': stp is not supported') for b in blocking), blocking)


if __name__ == '__main__':
    unittest.main()
