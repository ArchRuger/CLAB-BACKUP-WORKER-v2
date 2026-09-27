"""Milestone E: generation tests for the *Network design* feature families beyond OSPF/BGP
(milestone D applied those live) -- IS-IS, static routes, VRFs, BGP policy/redistribution/default
origination, and BFD -- run with the real, pinned netlab engine on the four-node restore-square
fixture (docs/multi-platform-restore), copied here as a text constant exactly as
tests/test_network_design.py and tests/test_design_adapter.py do: never read from /srv or a
deployed manager.

Each family gets:
  * an intent :func:`design_intent.validate` accepts (checked with the lab's nodes, links, the
    real capability/engine schema and its management networks, as :meth:`NetworkDesign.validation`
    does);
  * a real generation -- for most families through :func:`design_adapter.build` plus
    :func:`design_engine.run_generation` directly (the fast path
    tests/test_design_adapter.py's ``RealEngineTests`` uses), for BFD also through the full
    ``create_app()``/``TestClient`` HTTP flow tests/test_network_design.py's
    ``RealEngineGenerationTests`` uses, because that family's point is the *whole-generation*
    refusal ``network_design.NetworkDesign.compatibility()`` makes;
  * assertions on the generated fragment text per platform (what the provisioning drivers meet
    live);
  * an obviously wrong variant :func:`design_intent.validate` refuses;
  * a determinism check: the same built topology run twice through the engine gives byte-identical
    artifacts.

Every engine run uses its own temporary work root (never /srv or the deployed manager's data
directory) and is cleaned up whether it succeeds or fails.
"""
import copy
import shutil
import tempfile
import time
import unittest
import uuid

from fastapi.testclient import TestClient

from app import design_adapter as da
from app import design_capabilities as caps
from app import design_engine as engine
from app import design_intent as di
from app import network_design as nd
from app.discovery import parse_definition
from app.main import create_app

HAS_NETLAB = shutil.which('netlab') is not None
SKIP_REASON = 'netlab is not on PATH for this test run'

# The four-node restore-square fixture (docs/multi-platform-restore), copied verbatim from
# tests/test_network_design.py's TOPOLOGY: never read from /srv or a deployed manager at test time.
FIXTURE_YAML = '''name: restore-square
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

ROUTERS = ('ceos', 'cjunosevolved', 'vjunos-switch', 'xrv9k')


def lab_nodes():
    return parse_definition(FIXTURE_YAML.encode())['nodes']


def lab_nodes_map():
    return {n['definition_node']: n.get('kind', '') for n in lab_nodes()}


def lab_link_keys():
    return [l['key'] for l in da.parse_links(FIXTURE_YAML) if not l['problem']]


def management():
    return da.management_networks(FIXTURE_YAML, lab_nodes())


def validate(intent):
    """design_intent.validate() with everything network_design.NetworkDesign.validation() gives
    it for this fixture: the lab's nodes and links, the real engine schema, the management
    networks no pool or address may overlap."""
    return di.validate(intent, lab_nodes=lab_nodes_map(), lab_links=lab_link_keys(),
                        schema=caps.engine_data(), management=management())


def add_lab(app):
    """Appends the fixture lab straight into the store, as test_network_design.py's add_lab does."""
    lab_id = uuid.uuid4().hex
    with app.state.store.lock:
        lab = dict(id=lab_id, name='restore-square', nodes=lab_nodes(), profiles=[], defaults={},
                   interval=0, next_run=None, created='2026-09-27T00:00:00+00:00',
                   updated='2026-09-27T00:00:00+00:00', definition_yaml=FIXTURE_YAML)
        app.state.store.state['labs'].append(lab)
        app.state.store.save()
    return lab_id


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


class RoutingFamilyTestCase(unittest.TestCase):
    """Base for the direct adapter+engine path: a fresh work_root per test, removed on cleanup."""

    def setUp(self):
        self.work_root = tempfile.mkdtemp(prefix='design-families-test-')
        self.addCleanup(shutil.rmtree, self.work_root, ignore_errors=True)

    def build_and_run(self, intent, expect_ok=True):
        """Builds the netlab topology from the fixture and this intent, then runs the real engine
        on it. Asserts the intent validates first (never generates something validate() refuses)."""
        problems = validate(intent)
        self.assertEqual(problems, [], problems)
        built = da.build(FIXTURE_YAML, lab_nodes(), intent, caps.profile_for)
        result = engine.run_generation(self.work_root, built['topology'])
        self.addCleanup(shutil.rmtree, result.get('workdir', ''), ignore_errors=True)
        if expect_ok:
            self.assertTrue(result['ok'], result.get('errors'))
        return built, result

    def artifact(self, result, node, module):
        entries = dict(result['artifacts'].get(node, []))
        self.assertIn(module, entries, (node, sorted(entries)))
        return entries[module]

    def assert_stable(self, topology):
        """The same built topology run twice through the real engine gives byte-identical
        artifacts (docs/NETWORK-DESIGN.md's own determinism claim under 'Identity and endpoint
        mapping': 'the same semantic input yields byte-identical generated files')."""
        first = engine.run_generation(self.work_root, topology)
        self.addCleanup(shutil.rmtree, first.get('workdir', ''), ignore_errors=True)
        second = engine.run_generation(self.work_root, topology)
        self.addCleanup(shutil.rmtree, second.get('workdir', ''), ignore_errors=True)
        self.assertTrue(first['ok'], first.get('errors'))
        self.assertTrue(second['ok'], second.get('errors'))
        self.assertEqual(first['artifacts'], second['artifacts'])


# --- 1. IS-IS ------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class IsisFamilyTests(RoutingFamilyTestCase):
    """dual-stack IS-IS, area and level at the global level, a per-node type override."""

    def _intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['isis']
        intent['isis'] = {'area': '49.0001.0000.0000.0001.00', 'type': 'level-2'}
        intent['nodes'] = {'xrv9k': {'isis': {'type': 'level-1'}}}
        return intent

    def test_shape_is_accepted_and_an_unknown_top_level_key_is_refused(self):
        intent = self._intent()
        self.assertEqual(validate(intent), [])
        bad = copy.deepcopy(intent)
        bad['bogus'] = 1
        self.assertEqual(validate(bad), [{'path': 'bogus', 'message': 'Unknown design field'}])

    def test_a_short_isis_area_is_accepted_like_the_engine_accepts_it(self):
        intent = di.empty_intent()
        intent['modules'] = ['isis']
        intent['isis'] = {'area': '49.0001', 'type': 'level-2'}
        self.assertEqual(validate(intent), [], 'the `net` type takes an IS-IS area as well as a full NET')
        intent['isis']['area'] = 'zz.1'
        problems = validate(intent)
        self.assertTrue(any(p['path'] == 'isis.area' for p in problems), problems)

    def test_every_router_gets_an_isis_fragment_with_the_area_and_the_per_node_override(self):
        intent = self._intent()
        built, result = self.build_and_run(intent)
        for router in ROUTERS:
            self.assertIn(router, result['artifacts'])
        self.assertNotIn('isis', dict(result['artifacts'].get('host1', [])))

        eos = self.artifact(result, 'ceos', 'isis')
        self.assertIn('router isis', eos)
        self.assertIn('net 49.0001.0000.0000.0001.00', eos)
        self.assertIn('is-type level-2', eos)

        cjunos = self.artifact(result, 'cjunosevolved', 'isis')
        self.assertIn('protocols {', cjunos)
        self.assertIn('isis {', cjunos)
        self.assertIn('family iso {', cjunos)
        self.assertIn('address 49.0001.0000.0000.0001.00.', cjunos)

        vjunos = self.artifact(result, 'vjunos-switch', 'isis')
        self.assertIn('family iso {', vjunos)
        self.assertIn('address 49.0001.0000.0000.0001.00.', vjunos)

        xr = self.artifact(result, 'xrv9k', 'isis')
        self.assertIn('router isis', xr)
        self.assertIn('net 49.0001.0000.0000.0001.00.', xr)
        self.assertIn('is-type level-1', xr)  # the per-node override reaches xrv9k

    def test_generation_is_byte_identical_when_run_twice(self):
        built = da.build(FIXTURE_YAML, lab_nodes(), self._intent(), caps.profile_for)
        self.assert_stable(built['topology'])


# --- 2. Static routes -----------------------------------------------------------------------------

@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class StaticRoutesFamilyTests(RoutingFamilyTestCase):
    """Node-level routing.static (a list of static_entry per design_intent/the engine schema),
    with an explicit discard next hop so no dependency on allocated addresses is needed."""

    def _intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['routing']
        entry = [{'ipv4': '192.0.2.0/24', 'nexthop': {'discard': True}}]
        intent['nodes'] = {n: {'routing': {'static': copy.deepcopy(entry)}} for n in ROUTERS}
        return intent

    def test_shape_is_accepted_and_a_nexthop_inside_management_is_refused(self):
        intent = self._intent()
        self.assertEqual(validate(intent), [])
        bad = copy.deepcopy(intent)
        bad['nodes']['ceos']['routing']['static'][0]['nexthop'] = {'ipv4': '172.20.20.50'}
        problems = validate(bad)
        self.assertEqual(problems, [{'path': 'nodes.ceos.routing.static[0].nexthop.ipv4',
                                     'message': 'Overlaps the lab management network mgmt ipv4-subnet'}])

    def test_static_route_fragments_carry_ip_route_route_and_router_static_per_platform(self):
        intent = self._intent()
        built, result = self.build_and_run(intent)

        eos = self.artifact(result, 'ceos', 'routing')
        self.assertIn('Static routes', eos)
        self.assertIn('ip route 192.0.2.0/24 Null0', eos)

        for junos_node in ('cjunosevolved', 'vjunos-switch'):
            junos = self.artifact(result, junos_node, 'routing')
            self.assertIn('routing-options {', junos)
            self.assertIn('static route 192.0.2.0/24 {', junos)
            self.assertIn('discard;', junos)

        xr = self.artifact(result, 'xrv9k', 'routing')
        self.assertIn('router static', xr)
        self.assertIn('address-family ipv4 unicast 192.0.2.0/24 Null0', xr)

    def test_generation_is_byte_identical_when_run_twice(self):
        built = da.build(FIXTURE_YAML, lab_nodes(), self._intent(), caps.profile_for)
        self.assert_stable(built['topology'])


# --- 3. VRFs ---------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class VrfFamilyTests(RoutingFamilyTestCase):
    """Two VRF objects, `vrf: red` attached at link level on two links (one touching ceos and
    cjunosevolved, one touching vjunos-switch and xrv9k, so all four routers get a VRF interface),
    a VRF loopback, and OSPF enabled globally so it becomes VRF-aware on the VRF's interfaces."""

    def _links(self):
        return lab_link_keys()

    def _intent(self):
        links = self._links()
        intent = di.empty_intent()
        intent['modules'] = ['vrf', 'ospf']
        intent['ospf'] = {'area': '0.0.0.0'}
        intent['vrfs'] = {'red': {'loopback': True}, 'blue': {}}
        intent['links'] = {links[0]: {'vrf': 'red'}, links[2]: {'vrf': 'red'}}
        return intent

    def test_shape_is_accepted_and_an_undefined_vrf_reference_is_refused(self):
        intent = self._intent()
        self.assertEqual(validate(intent), [])
        bad = copy.deepcopy(intent)
        bad['links'][self._links()[0]] = {'vrf': 'green'}
        problems = validate(bad)
        self.assertEqual(problems, [{'path': 'links.' + self._links()[0] + '.vrf',
                                     'message': 'No VRF named green is defined in this design'}])

    def test_ospf_or_bgp_settings_nested_inside_a_vrf_object_are_refused_by_the_schema(self):
        bad = copy.deepcopy(self._intent())
        bad['vrfs']['red']['ospf'] = {'area': '0.0.0.1'}
        problems = validate(bad)
        self.assertEqual(problems, [{'path': 'vrfs.red.ospf', 'message': 'Unknown setting for this module'}])
        # Documented limit, not a gap: netlab's own VRF object takes no module settings; VRF-scoped routing is expressed
        # by attaching links to the VRF while the module is enabled (proven by the generation above).

    def test_link_level_vrf_reaches_ospf_and_the_vrf_fragment_per_platform(self):
        intent = self._intent()
        built, result = self.build_and_run(intent)

        ceos_initial = self.artifact(result, 'ceos', 'initial')
        self.assertIn('vrf instance red', ceos_initial)
        self.assertIn('ip routing vrf red', ceos_initial)
        self.assertIn(' vrf red', ceos_initial)  # the VRF-attached interface and Loopback1
        self.assertIn('VRF Loopback red', ceos_initial)
        ceos_vrf = self.artifact(result, 'ceos', 'vrf')
        self.assertIn('router ospf 100 vrf red', ceos_vrf)

        cjunos_initial = self.artifact(result, 'cjunosevolved', 'initial')
        self.assertIn('routing-instances {', cjunos_initial)
        self.assertIn('instance-type vrf;', cjunos_initial)
        self.assertIn('route-distinguisher', cjunos_initial)
        cjunos_vrf = self.artifact(result, 'cjunosevolved', 'vrf')
        self.assertIn('routing-instances {', cjunos_vrf)
        self.assertIn('ospf {', cjunos_vrf)

        vjunos_vrf = self.artifact(result, 'vjunos-switch', 'vrf')
        self.assertIn('routing-instances {', vjunos_vrf)
        self.assertIn('ospf {', vjunos_vrf)

        xr_vrf = self.artifact(result, 'xrv9k', 'vrf')
        self.assertIn('vrf red', xr_vrf)
        self.assertIn('rd 65000:1', xr_vrf)  # netlab's default BGP AS (65000) used for the auto RD
        self.assertIn('router ospf 100 vrf red', xr_vrf)
        xr_initial = self.artifact(result, 'xrv9k', 'initial')
        self.assertIn('VRF Loopback red', xr_initial)

    def test_generation_is_byte_identical_when_run_twice(self):
        built = da.build(FIXTURE_YAML, lab_nodes(), self._intent(), caps.profile_for)
        self.assert_stable(built['topology'])


# --- 4. BGP policy, redistribution and default origination ----------------------------------------

@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class BgpPolicyFamilyTests(RoutingFamilyTestCase):
    """A prefix list and a route policy at the global `routing` module; per-node OSPF-to-connected
    and BGP-to-OSPF (filtered by the policy) redistribution; a per-node BGP default origination."""

    def _intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['ospf', 'bgp', 'routing']
        intent['ospf'] = {'area': '0.0.0.0'}
        intent['bgp'] = {'as': 65000}
        intent['routing'] = {
            'prefix': {'p1': [{'action': 'permit', 'ipv4': ['172.16.0.0/16']}]},
            'policy': {'from_ospf': [{'action': 'permit', 'match': {'prefix': 'p1'}}]},
        }
        per_node = {'ospf': {'import': {'connected': True}},
                    'bgp': {'import': {'ospf': {'policy': 'from_ospf'}}}}
        intent['nodes'] = {n: copy.deepcopy(per_node) for n in ROUTERS}
        # A summary route, not a literal default: see
        # test_a_literal_default_route_origination_is_always_refused_by_the_schema below for why
        # '0.0.0.0/0' itself cannot be used here.
        intent['nodes']['ceos']['bgp']['originate'] = ['203.0.113.0/24']
        return intent

    def test_shape_is_accepted_and_an_originated_prefix_inside_management_is_refused(self):
        intent = self._intent()
        self.assertEqual(validate(intent), [])
        bad = copy.deepcopy(intent)
        bad['nodes']['ceos']['bgp']['originate'] = ['172.20.20.0/24']
        problems = validate(bad)
        self.assertEqual(problems, [{'path': 'nodes.ceos.bgp.originate[0]',
                                     'message': 'Overlaps the lab management network mgmt ipv4-subnet'}])

    def test_a_literal_default_route_origination_is_accepted(self):
        intent = self._intent()
        intent['nodes']['ceos']['bgp']['originate'] = ['0.0.0.0/0']
        self.assertEqual(validate(intent), [], 'a default route is a prefix to originate, never an address inside the management network')
        intent['nodes']['ceos']['bgp']['originate'] = ['172.20.20.0/24']
        problems = validate(intent)
        self.assertTrue(any('management' in p['message'] for p in problems), problems)

    def test_route_maps_prefix_lists_redistribution_and_default_origination_per_platform(self):
        intent = self._intent()
        built, result = self.build_and_run(intent)

        eos_bgp = self.artifact(result, 'ceos', 'bgp')
        self.assertIn('redistribute ospf route-map from_ospf-ipv4', eos_bgp)
        self.assertIn('network 203.0.113.0/24', eos_bgp)  # the origination reaches only ceos
        eos_routing = self.artifact(result, 'ceos', 'routing')
        self.assertIn('route-map from_ospf-ipv4 permit 10', eos_routing)
        self.assertIn('ip prefix-list p1-ipv4', eos_routing)
        eos_ospf = self.artifact(result, 'ceos', 'ospf')
        self.assertIn('redistribute connected', eos_ospf)

        for junos_node in ('cjunosevolved', 'vjunos-switch'):
            junos_bgp = self.artifact(result, junos_node, 'bgp')
            self.assertIn('protocol ospf;', junos_bgp)
            self.assertIn('policy from_ospf;', junos_bgp)
            junos_routing = self.artifact(result, junos_node, 'routing')
            self.assertIn('policy-statement from_ospf {', junos_routing)
            self.assertIn('route-filter-list p1-ipv4 {', junos_routing)
            junos_ospf = self.artifact(result, junos_node, 'ospf')
            self.assertIn('export default-ospf-export;', junos_ospf)

        xr_bgp = self.artifact(result, 'xrv9k', 'bgp')
        self.assertIn('redistribute ospf 1 match internal external nssa-external route-policy from_ospf', xr_bgp)
        self.assertNotIn('203.0.113.0/24', xr_bgp)  # the origination reaches only ceos
        xr_routing = self.artifact(result, 'xrv9k', 'routing')
        self.assertIn('route-policy from_ospf', xr_routing)
        self.assertIn('prefix-set p1', xr_routing)
        xr_ospf = self.artifact(result, 'xrv9k', 'ospf')
        self.assertIn('redistribute connected', xr_ospf)

    def test_generation_is_byte_identical_when_run_twice(self):
        built = da.build(FIXTURE_YAML, lab_nodes(), self._intent(), caps.profile_for)
        self.assert_stable(built['topology'])


# --- 5. BFD ----------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class BfdFamilyTests(RoutingFamilyTestCase):
    """OSPF with BFD. XRv9k (profile iosxr) has no bfd module in the pinned engine's module
    support data, so the capability model must report it unsupported, and a generation that
    includes xrv9k as a router must refuse the whole plan (network_design._generate fails the
    entire generation when NetworkDesign.compatibility() reports anything blocking, never a
    partial per-device success) rather than silently excluding or downgrading it."""

    def _intent(self):
        intent = di.empty_intent()
        intent['modules'] = ['ospf', 'bfd']
        intent['ospf'] = {'area': '0.0.0.0', 'bfd': True}
        return intent

    def test_capability_model_reports_bfd_unsupported_on_cisco_xrv9k(self):
        xr = caps.resolve('bfd', 'cisco_xrv9k')
        self.assertEqual(xr['level'], 'unsupported')
        self.assertFalse(xr['engine'])
        self.assertIn("module 'bfd' does not support device profile 'iosxr'", xr['reason'])

        eos = caps.resolve('bfd', 'arista_ceos')
        self.assertTrue(eos['engine'])
        self.assertNotEqual(eos['level'], 'unsupported')

    def test_shape_is_accepted_and_an_unknown_bfd_setting_is_refused(self):
        intent = self._intent()
        self.assertEqual(validate(intent), [])
        bad = copy.deepcopy(intent)
        bad['bfd'] = {'bogus_attr': 1}
        problems = validate(bad)
        self.assertEqual(problems, [{'path': 'bfd.bogus_attr', 'message': 'Unknown setting for this module'}])

    def test_the_whole_generation_is_refused_when_xrv9k_is_included(self):
        """The full create_app()/TestClient HTTP flow (as tests/test_network_design.py's
        RealEngineGenerationTests uses), because the point here is
        network_design.NetworkDesign.compatibility()'s own behaviour, not a guess: reading
        NetworkDesign._generate(), `blocking` (any 'unsupported' or 'blocked_missing_prerequisite'
        feature on an included, non-host device) fails the ENTIRE generation with status
        'failed' before the engine even runs -- no artifacts for any device, not just xrv9k."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app = create_app(tmp.name)
        client = TestClient(app)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.addCleanup(app.state.network_design.close)

        lab_id = add_lab(app)
        intent = self._intent()
        saved = client.put(f'/api/labs/{lab_id}/design', json={'intent': intent, 'revision': ''})
        self.assertEqual(saved.status_code, 200, saved.text)
        revision = saved.json()['intent']['revision']

        response = client.post(f'/api/labs/{lab_id}/design/generate', json={'revision': revision})
        self.assertEqual(response.status_code, 200, response.text)
        record = poll_generation(client, lab_id, response.json()['id'])

        self.assertEqual(record['status'], 'failed')
        self.assertIn('cannot do', record['message'])
        self.assertTrue(any('xrv9k' in e and 'bfd' in e and 'cisco_xrv9k' in e for e in record['errors']), record['errors'])
        self.assertFalse(record.get('artifacts'))

    def test_bfd_reaches_ospf_interfaces_on_eos_and_junos_when_xrv9k_is_excluded(self):
        intent = self._intent()
        intent['nodes'] = {'xrv9k': {'role': 'exclude'}}
        built, result = self.build_and_run(intent)

        self.assertNotIn('xrv9k', result['artifacts'])
        eos = self.artifact(result, 'ceos', 'ospf')
        self.assertIn('ip ospf neighbor bfd', eos)
        self.assertIn('ipv6 ospf bfd', eos)
        for junos_node in ('cjunosevolved', 'vjunos-switch'):
            junos = self.artifact(result, junos_node, 'ospf')
            self.assertIn('bfd-liveness-detection {', junos)

    def test_generation_is_byte_identical_when_run_twice(self):
        intent = self._intent()
        intent['nodes'] = {'xrv9k': {'role': 'exclude'}}
        built = da.build(FIXTURE_YAML, lab_nodes(), intent, caps.profile_for)
        self.assert_stable(built['topology'])


if __name__ == '__main__':
    unittest.main()
