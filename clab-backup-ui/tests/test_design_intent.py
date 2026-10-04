"""Tests for app/design_intent.py: the network design intent schema, its core validation, the
advanced (engine-schema-checked) fields, and the allocation ledger helpers.

Most behaviours are checked against the manager's own core rules and need no engine schema
(schema=None). The "advanced fields" tests (module settings, vlan/vrf bodies checked against the
engine's own attribute schema) run the pinned `netlab` CLI once, via engine_schema(), to build the
same shape of schema dict design_intent.SchemaChecker expects; they are skipped when `netlab` is not
on PATH (CLAUDE.md's PATH="$PWD/.venv/bin:$PATH" prefix puts it there).
"""
import functools
import ipaddress
import json
import shutil
import subprocess
import unittest

import yaml

from app import design_intent as di

HAS_NETLAB = shutil.which('netlab') is not None
SKIP_REASON = 'netlab is not on PATH for this test run'


def _attrs(module):
    out = subprocess.run(['netlab', 'show', 'attributes', '--system', '--format', 'yaml', '-m', module],
                          capture_output=True, text=True, timeout=30, check=True)
    return yaml.safe_load(out.stdout)


def _top_attrs():
    out = subprocess.run(['netlab', 'show', 'attributes', '--system', '--format', 'yaml'],
                          capture_output=True, text=True, timeout=30, check=True)
    return yaml.safe_load(out.stdout)


@functools.lru_cache(maxsize=1)
def engine_schema():
    """{'attributes': {module: <netlab's own attribute schema for it>}, 'types': <the top-level named
    types, minus the generic 'global'/'node'/'link'/'interface'/'loopback' sections>} -- exactly the
    shape design_intent.module_schema() and SchemaChecker expect. Built once per test run."""
    modules = ('ospf', 'bgp', 'isis', 'vlan', 'vrf', 'routing', 'gateway', 'lag')
    attributes = {module: _attrs(module) for module in modules}
    top = _top_attrs()
    types = {k: v for k, v in top.items() if k not in ('global', 'node', 'link', 'interface', 'loopback')}
    return {'attributes': attributes, 'types': types}


class DesignIntentTestCase(unittest.TestCase):
    def assertClean(self, errs):
        self.assertEqual(errs, [], 'expected no errors, got %r' % (errs,))

    def assertOnlyError(self, errs, path, word):
        """Exactly one error, at `path`, whose message contains `word` (case-insensitive)."""
        self.assertEqual(len(errs), 1, 'expected exactly one error, got %r' % (errs,))
        self.assertError(errs, path, word)

    def assertError(self, errs, path, word):
        matches = [e for e in errs if e['path'] == path]
        self.assertTrue(matches, '%s: no error at path %r among %r' % (self._testMethodName, path, errs))
        self.assertIn(word.lower(), matches[0]['message'].lower(),
                      '%s: %r does not contain %r' % (self._testMethodName, matches[0]['message'], word))

    def assertNoErrorAt(self, errs, path):
        self.assertFalse([e for e in errs if e['path'] == path], 'unexpected error at %r in %r' % (path, errs))


# --- envelope: empty_intent, normalize, revision, canonical -----------------------------------------------

class EnvelopeTests(DesignIntentTestCase):
    def test_empty_intent_validates_cleanly_without_schema(self):
        self.assertClean(di.validate(di.empty_intent()))

    def test_normalize_stamps_schema_and_24_hex_revision(self):
        normalized = di.normalize(di.empty_intent())
        self.assertEqual(normalized['schema'], di.SCHEMA)
        self.assertEqual(len(normalized['revision']), 24)
        int(normalized['revision'], 16)  # it is hex

    def test_revision_ignores_revision_and_updated_fields(self):
        base = di.normalize(di.empty_intent())
        again = di.normalize(dict(base, revision='not-the-real-one', updated='2020-01-01T00:00:00Z'))
        self.assertEqual(base['revision'], again['revision'])

    def test_revision_changes_when_content_changes(self):
        base = di.normalize(di.empty_intent())
        changed = di.normalize(dict(di.empty_intent(), label='changed'))
        self.assertNotEqual(base['revision'], changed['revision'])

    def test_canonical_drops_the_volatile_envelope(self):
        normalized = di.normalize(di.empty_intent())
        canonical = di.canonical(normalized)
        self.assertNotIn('revision', canonical)
        self.assertNotIn('updated', canonical)
        self.assertIn('schema', canonical)


# --- top-level shape --------------------------------------------------------------------------------------

class TopLevelShapeTests(DesignIntentTestCase):
    def test_unknown_top_level_key_is_refused(self):
        intent = dict(di.empty_intent(), bogus=1)
        self.assertError(di.validate(intent), 'bogus', 'unknown')

    def test_wrong_schema_number_is_refused(self):
        intent = dict(di.empty_intent(), schema=2)
        self.assertError(di.validate(intent), 'schema', 'schema')

    def test_label_too_long_is_refused(self):
        intent = dict(di.empty_intent(), label='x' * 200)
        self.assertError(di.validate(intent), 'label', 'short')

    def test_families_both_off_is_refused(self):
        intent = dict(di.empty_intent(), families={'ipv4': False, 'ipv6': False})
        self.assertError(di.validate(intent), 'families', 'enable')

    def test_families_non_boolean_value_is_refused(self):
        intent = dict(di.empty_intent(), families={'ipv4': 'yes'})
        self.assertError(di.validate(intent), 'families', 'enable')

    def test_families_unknown_key_is_refused(self):
        intent = dict(di.empty_intent(), families={'ipv4': True, 'ipv5': True})
        self.assertError(di.validate(intent), 'families', 'enable')

    def test_module_outside_supported_list_is_refused(self):
        intent = dict(di.empty_intent(), modules=['nonsense'])
        self.assertError(di.validate(intent), 'modules', 'protocol')

    def test_module_listed_twice_is_refused(self):
        intent = dict(di.empty_intent(), modules=['ospf', 'ospf'])
        self.assertError(di.validate(intent), 'modules', 'protocol')


# --- pools -------------------------------------------------------------------------------------------------

class PoolTests(DesignIntentTestCase):
    def test_mgmt_pool_name_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'mgmt': {'ipv4': '10.0.0.0/24'}})
        self.assertError(di.validate(intent), 'addressing.mgmt', 'mgmt')

    def test_unknown_pool_key_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'loopback': {'ipv4': '10.255.0.0/24', 'bogus': 1}})
        self.assertError(di.validate(intent), 'addressing.loopback', 'takes')

    def test_invalid_cidr_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'loopback': {'ipv4': 'not-a-cidr'}})
        self.assertError(di.validate(intent), 'addressing.loopback.ipv4', 'cidr')

    def test_ipv6_prefix_under_ipv4_key_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'loopback': {'ipv4': '2001:db8::/48'}})
        self.assertError(di.validate(intent), 'addressing.loopback.ipv4', 'ipv4')

    def test_prefix_size_below_pool_length_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'p2p': {'ipv4': '10.1.0.0/16', 'prefix': 8}})
        self.assertError(di.validate(intent), 'addressing.p2p.prefix', 'between')

    def test_prefix_size_above_32_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'p2p': {'ipv4': '10.1.0.0/16', 'prefix': 40}})
        self.assertError(di.validate(intent), 'addressing.p2p.prefix', 'between')

    def test_prefix6_beyond_128_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'loopback': {'ipv6': '2001:db8::/48', 'prefix6': 200}})
        self.assertError(di.validate(intent), 'addressing.loopback.prefix6', 'between')

    def test_family_switched_off_but_present_in_pool_is_refused(self):
        intent = dict(di.empty_intent(), families={'ipv4': True, 'ipv6': False},
                      addressing={'loopback': {'ipv6': '2001:db8::/48'}})
        self.assertError(di.validate(intent), 'addressing.loopback.ipv6', 'switched off')

    def test_two_pools_overlapping_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'p2p': {'ipv4': '10.1.0.0/16'},
                                                       'lan': {'ipv4': '10.1.5.0/24'}})
        self.assertError(di.validate(intent), 'addressing.lan.ipv4', 'overlap')

    def test_pool_overlapping_management_network_is_refused(self):
        management = [('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))]
        intent = dict(di.empty_intent(), addressing={'loopback': {'ipv4': '172.20.20.0/28'}})
        errs = di.validate(intent, management=management)
        self.assertError(errs, 'addressing.loopback.ipv4', 'management')

    def test_bad_start_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'p2p': {'ipv4': '10.1.0.0/16', 'start': 99999}})
        self.assertError(di.validate(intent), 'addressing.p2p.start', 'whole number')

    def test_bad_allocation_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'p2p': {'ipv4': '10.1.0.0/16', 'allocation': 'random'}})
        self.assertError(di.validate(intent), 'addressing.p2p.allocation', 'sequential')

    def test_bad_unnumbered_is_refused(self):
        intent = dict(di.empty_intent(), addressing={'p2p': {'ipv4': '10.1.0.0/16', 'unnumbered': 'yes'}})
        self.assertError(di.validate(intent), 'addressing.p2p.unnumbered', 'yes or no')

    def test_custom_pool_with_plain_identifier_is_accepted(self):
        intent = dict(di.empty_intent(), addressing={'custom1': {'ipv4': '192.168.0.0/24'}})
        self.assertClean(di.validate(intent))


# --- module settings (the advanced fields) ----------------------------------------------------------------

class ModuleSettingsCoreTests(DesignIntentTestCase):
    """Behaviours that do not need the engine schema."""

    def test_settings_for_a_module_not_enabled_are_refused(self):
        intent = dict(di.empty_intent(), ospf={'area': '0.0.0.0'})
        self.assertError(di.validate(intent), 'ospf', 'Enable')

    def test_without_schema_a_non_empty_module_mapping_is_refused(self):
        intent = dict(di.empty_intent(), modules=['ospf'], ospf={'area': '0.0.0.0'})
        self.assertError(di.validate(intent, schema=None), 'ospf', 'schema')

    def test_without_schema_an_empty_module_mapping_is_accepted(self):
        intent = dict(di.empty_intent(), modules=['ospf'], ospf={})
        self.assertClean(di.validate(intent, schema=None))

    def test_without_schema_module_true_is_accepted(self):
        intent = dict(di.empty_intent(), modules=['ospf'], ospf=True)
        self.assertClean(di.validate(intent, schema=None))

    def test_without_schema_any_non_empty_module_body_is_refused_at_the_module_path(self):
        # Without an engine schema, module_schema() returns None for every module, so a non-empty body is
        # refused with the generic "no settings at this level" message at the module's own path. (A denied
        # key such as 'config' never gets that far: the recursive guard refuses it by name first.)
        intent = dict(di.empty_intent(), modules=['ospf'], ospf={'area': 1})
        self.assertError(di.validate(intent, schema=None), 'ospf', 'schema')


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class ModuleSettingsAdvancedTests(DesignIntentTestCase):
    """Module settings checked against the real engine attribute schema."""

    def setUp(self):
        self.schema = engine_schema()

    def test_ospf_area_and_bgp_as_pass(self):
        intent = dict(di.empty_intent(), modules=['ospf', 'bgp'], ospf={'area': '0.0.0.0'}, bgp={'as': 65000})
        self.assertClean(di.validate(intent, schema=self.schema))

    def test_bgp_as_wrong_type_fails(self):
        intent = dict(di.empty_intent(), modules=['bgp'], bgp={'as': 'x'})
        self.assertOnlyError(di.validate(intent, schema=self.schema), 'bgp.as', 'type')

    def test_bgp_unknown_setting_fails(self):
        intent = dict(di.empty_intent(), modules=['bgp'], bgp={'as': 65000, 'bogus': 1})
        self.assertOnlyError(di.validate(intent, schema=self.schema), 'bgp.bogus', 'unknown')

    def test_bgp_as_must_be_present_and_in_range(self):
        # 0, a blank the form used to turn into 65000, a bool and an out-of-range value are refused with the field
        # named; the AS may live on the devices instead of globally (eBGP designs).
        for value in (0, 4294967296, -1):
            intent = dict(di.empty_intent(), modules=['bgp'], bgp={'as': value})
            errs = di.validate(intent, schema=self.schema)
            self.assertEqual([e['path'] for e in errs], ['bgp.as'], 'one problem, naming the field: %r' % (errs,))
        intent = dict(di.empty_intent(), modules=['bgp'], bgp={})
        self.assertOnlyError(di.validate(intent, schema=self.schema), 'bgp.as', 'globally or on each device')
        intent = dict(di.empty_intent(), modules=['bgp'], bgp={}, nodes={'r1': {'bgp': {'as': 65001}}})
        self.assertClean(di.validate(intent, schema=self.schema))
        intent = dict(di.empty_intent(), modules=['bgp'], bgp={'as': 65000}, nodes={'r1': {'bgp': {'as': 0}}})
        errs = di.validate(intent, schema=self.schema)
        self.assertEqual([e['path'] for e in errs], ['nodes.r1.bgp.as'], 'one problem naming the device field (the schema\'s own wording when it reports first): %r' % (errs,))

    def test_denied_key_config_under_a_module_is_refused_with_schema_too(self):
        intent = dict(di.empty_intent(), modules=['ospf'], ospf={'config': 1})
        self.assertOnlyError(di.validate(intent, schema=self.schema), 'ospf.config', 'not accepted')

    def test_denied_key_plugin_under_a_module_is_refused(self):
        intent = dict(di.empty_intent(), modules=['ospf'], ospf={'plugin': 'x'})
        self.assertOnlyError(di.validate(intent, schema=self.schema), 'ospf.plugin', 'not accepted')

    def test_denied_key_starting_with_underscore_under_a_module_is_refused(self):
        intent = dict(di.empty_intent(), modules=['ospf'], ospf={'_hidden': 1})
        self.assertOnlyError(di.validate(intent, schema=self.schema), 'ospf._hidden', 'not accepted')

    def test_ospf_timers_hello_below_minimum_fails(self):
        intent = dict(di.empty_intent(), modules=['ospf'], ospf={'timers': {'hello': 0}})
        self.assertOnlyError(di.validate(intent, schema=self.schema), 'ospf.timers.hello', 'type')

    def test_isis_type_invalid_value_fails(self):
        intent = dict(di.empty_intent(), modules=['isis'], isis={'type': 'level-9'})
        self.assertOnlyError(di.validate(intent, schema=self.schema), 'isis.type', 'choose')

    def test_bgp_community_list_passes(self):
        intent = dict(di.empty_intent(), modules=['bgp'], bgp={'as': 65000, 'community': {'ebgp': ['standard']}})
        self.assertClean(di.validate(intent, schema=self.schema))

    def test_routing_prefix_list_passes(self):
        # netlab's pfx_entry schema requires 'ipv4'/'ipv6' under a routing.prefix entry to be a LIST
        # of prefixes (`_subtype: {type: ipv4, use: prefix}` under a `type: list` node), not a bare
        # string; this is what the real engine accepts, confirmed by running the schema checker.
        intent = dict(di.empty_intent(), modules=['routing'],
                      routing={'prefix': {'p1': [{'action': 'permit', 'ipv4': ['10.0.0.0/8']}]}})
        self.assertClean(di.validate(intent, schema=self.schema))

    def test_node_level_bgp_rr_bool_passes(self):
        intent = dict(di.empty_intent(), modules=['bgp'], nodes={'r1': {'bgp': {'rr': True}}})
        self.assertClean(di.validate(intent, schema=self.schema, lab_nodes={'r1': 'x'}))

    def test_node_level_bgp_rr_wrong_type_fails(self):
        intent = dict(di.empty_intent(), modules=['bgp'], nodes={'r1': {'bgp': {'rr': 'yes'}}})
        errs = di.validate(intent, schema=self.schema, lab_nodes={'r1': 'x'})
        self.assertError(errs, 'nodes.r1.bgp.rr', 'type')

    def test_interface_level_ospf_priority_within_range_passes(self):
        # netlab's ospf module has 'priority' (0..255), not 'cost' (a link, not interface, attribute),
        # at the interface level; this is real engine behaviour, checked against the live schema.
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), modules=['ospf'],
                      links={key: {'endpoints': {'a': {'ospf': {'priority': 10}}}}})
        self.assertClean(di.validate(intent, schema=self.schema, lab_links=[key]))

    def test_interface_level_ospf_priority_out_of_range_fails(self):
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), modules=['ospf'],
                      links={key: {'endpoints': {'a': {'ospf': {'priority': 300}}}}})
        errs = di.validate(intent, schema=self.schema, lab_links=[key])
        self.assertError(errs, 'links.' + key + '.endpoints.a.ospf.priority', 'type')

    def test_ospf_cost_is_not_accepted_at_interface_level(self):
        # DEFECT-adjacent note, not a defect: the task's own example ("ospf: {cost: 10} passes at the
        # interface level") does not hold against the real engine schema -- 'cost' lives only at
        # ospf's 'link' level, never 'interface'. Recorded here so the discrepancy is not silently
        # lost; design_intent's behaviour (refusing it) is correct given the real schema.
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), modules=['ospf'],
                      links={key: {'endpoints': {'a': {'ospf': {'cost': 10}}}}})
        errs = di.validate(intent, schema=self.schema, lab_links=[key])
        self.assertError(errs, 'links.' + key + '.endpoints.a.ospf.cost', 'unknown')

    def test_ospf_cost_is_accepted_at_link_level(self):
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), modules=['ospf'], links={key: {'ospf': {'cost': 10}}})
        self.assertClean(di.validate(intent, schema=self.schema, lab_links=[key]))

    def test_ospf_cost_below_minimum_fails_at_link_level(self):
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), modules=['ospf'], links={key: {'ospf': {'cost': 0}}})
        errs = di.validate(intent, schema=self.schema, lab_links=[key])
        self.assertError(errs, 'links.' + key + '.ospf.cost', 'type')


# --- vlans / vrfs -------------------------------------------------------------------------------------------

class VlanVrfTests(DesignIntentTestCase):
    def test_vlans_need_the_vlan_module_enabled(self):
        intent = dict(di.empty_intent(), vlans={'v1': {'id': 10}})
        self.assertError(di.validate(intent), 'vlans', 'Enable')

    def test_vrfs_need_the_vrf_module_enabled(self):
        intent = dict(di.empty_intent(), vrfs={'v1': {'id': 10}})
        self.assertError(di.validate(intent), 'vrfs', 'Enable')

    def test_vlan_ids_are_bounded(self):
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 5000}})
        self.assertError(di.validate(intent), 'vlans.v1.id', 'between')

    def test_vlan_ids_are_unique(self):
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 10}, 'v2': {'id': 10}})
        self.assertError(di.validate(intent), 'vlans.v2.id', 'duplicate')

    def test_vlan_names_must_be_identifiers(self):
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'1bad': {'id': 10}})
        self.assertError(di.validate(intent), 'vlans.1bad', 'identifier')

    # QA-016 (stress finding B1): netlab types VRF, VLAN, pool, named-prefix and policy names as 16-character
    # identifiers (`must_be_id`, netsim/data/types.py); a longer name the manager accepted failed only at
    # generation with the engine's raw schema message. The manager now refuses it with its own words.
    def test_engine_identifiers_follow_netlabs_16_character_rule(self):
        sixteen, seventeen = 'a' * 16, 'a' * 17
        self.assertClean(di.validate(dict(di.empty_intent(), modules=['vlan'], vlans={sixteen: {'id': 10}})))
        self.assertClean(di.validate(dict(di.empty_intent(), modules=['vrf'], vrfs={sixteen: {'id': 10}})))
        self.assertError(di.validate(dict(di.empty_intent(), modules=['vlan'], vlans={seventeen: {'id': 10}})), 'vlans.' + seventeen, '16 characters')
        self.assertError(di.validate(dict(di.empty_intent(), modules=['vrf'], vrfs={seventeen: {'id': 10}})), 'vrfs.' + seventeen, '16 characters')
        self.assertClean(di.validate(dict(di.empty_intent(), addressing={sixteen: {'ipv4': '192.168.0.0/24'}})))
        self.assertError(di.validate(dict(di.empty_intent(), addressing={seventeen: {'ipv4': '192.168.0.0/24'}})), 'addressing.' + seventeen, '16 characters')
        nodes = {'r1': {'vrfs': {seventeen: {'id': 11}}}}
        self.assertError(di.validate(dict(di.empty_intent(), modules=['vrf'], nodes=nodes)), 'nodes.r1.vrfs', '16 characters')
        link = dict(di.empty_intent(), addressing={sixteen: {'ipv4': '192.168.0.0/24'}}, links={'r1:eth1--r2:eth1': {'pool': seventeen}})
        self.assertTrue(any(e['path'].endswith('.pool') for e in di.validate(link)), 'a link pool name over 16 characters is refused: %r' % di.validate(link))

    def test_vlan_body_must_be_a_mapping(self):
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': 'notadict'})
        self.assertError(di.validate(intent), 'vlans.v1', 'mapping')

    def test_vrf_ids_are_bounded(self):
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'v1': {'id': 70000}})
        self.assertError(di.validate(intent), 'vrfs.v1.id', 'between')

    def test_vrf_ids_are_unique(self):
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'v1': {'id': 5}, 'v2': {'id': 5}})
        self.assertError(di.validate(intent), 'vrfs.v2.id', 'duplicate')


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class VlanVrfAdvancedTests(DesignIntentTestCase):
    def setUp(self):
        self.schema = engine_schema()

    def test_node_level_vlans_ok(self):
        intent = dict(di.empty_intent(), modules=['vlan'], nodes={'a': {'vlans': {'v1': {'id': 10}}}})
        self.assertClean(di.validate(intent, schema=self.schema, lab_nodes={'a': 'x'}))

    def test_node_level_vlans_bad_key_fails(self):
        intent = dict(di.empty_intent(), modules=['vlan'], nodes={'a': {'vlans': {'v1': {'bogus': 1}}}})
        errs = di.validate(intent, schema=self.schema, lab_nodes={'a': 'x'})
        self.assertError(errs, 'nodes.a.vlans.v1.bogus', 'unknown')

    def test_node_level_vlans_without_schema_is_refused(self):
        intent = dict(di.empty_intent(), modules=['vlan'], nodes={'a': {'vlans': {'v1': {'id': 10, 'mode': 'irb'}}}})
        errs = di.validate(intent, schema=None, lab_nodes={'a': 'x'})
        self.assertError(errs, 'nodes.a.vlans.v1', 'schema')


# --- targets -----------------------------------------------------------------------------------------------

class TargetsTests(DesignIntentTestCase):
    def test_targets_must_be_a_list(self):
        intent = dict(di.empty_intent(), targets='notalist')
        self.assertError(di.validate(intent), 'targets', 'distinct')

    def test_targets_must_be_distinct(self):
        intent = dict(di.empty_intent(), targets=['a', 'a'])
        self.assertError(di.validate(intent), 'targets', 'distinct')

    def test_targets_reject_non_text_entries(self):
        intent = dict(di.empty_intent(), targets=[1, 2])
        self.assertError(di.validate(intent), 'targets', 'distinct')

    def test_unknown_target_device_is_refused_with_lab_nodes(self):
        intent = dict(di.empty_intent(), targets=['unknown1'])
        errs = di.validate(intent, lab_nodes={'a': 'arista_ceos'})
        self.assertError(errs, 'targets', 'unknown1')

    def test_known_target_device_is_accepted_with_lab_nodes(self):
        intent = dict(di.empty_intent(), targets=['a'])
        self.assertClean(di.validate(intent, lab_nodes={'a': 'arista_ceos'}))


# --- nodes -------------------------------------------------------------------------------------------------

class NodeTests(DesignIntentTestCase):
    def test_invalid_node_name_is_refused(self):
        intent = dict(di.empty_intent(), nodes={'1bad name!': {}})
        self.assertError(di.validate(intent), 'nodes.1bad name!', 'invalid')

    def test_nodes_must_be_a_mapping(self):
        intent = dict(di.empty_intent(), nodes=['a', 'b'])
        self.assertError(di.validate(intent), 'nodes', 'mapping')

    def test_unknown_device_with_lab_nodes_is_refused(self):
        intent = dict(di.empty_intent(), nodes={'nosuch': {}})
        errs = di.validate(intent, lab_nodes={'a': 'arista_ceos'})
        self.assertError(errs, 'nodes.nosuch', 'not in the lab')

    def test_unknown_node_setting_is_refused(self):
        intent = dict(di.empty_intent(), nodes={'a': {'bogus': 1}})
        errs = di.validate(intent, lab_nodes={'a': 'arista_ceos'})
        self.assertError(errs, 'nodes.a.bogus', 'unknown')

    def test_bad_role_is_refused(self):
        intent = dict(di.empty_intent(), nodes={'a': {'role': 'bogus'}})
        errs = di.validate(intent, lab_nodes={'a': 'arista_ceos'})
        self.assertError(errs, 'nodes.a.role', 'router')

    def test_node_modules_outside_the_list_is_refused(self):
        intent = dict(di.empty_intent(), nodes={'a': {'modules': ['bogus']}})
        errs = di.validate(intent, lab_nodes={'a': 'arista_ceos'})
        self.assertError(errs, 'nodes.a.modules', 'supported list')

    def test_loopback_false_is_accepted(self):
        intent = dict(di.empty_intent(), nodes={'a': {'loopback': False}})
        self.assertClean(di.validate(intent, lab_nodes={'a': 'arista_ceos'}))

    def test_loopback_dict_with_ipv4_and_ipv6_is_accepted(self):
        intent = dict(di.empty_intent(), nodes={'a': {'loopback': {'ipv4': '10.0.0.1', 'ipv6': '2001:db8::1'}}})
        self.assertClean(di.validate(intent, lab_nodes={'a': 'arista_ceos'}))

    def test_duplicate_loopback_across_two_nodes_is_refused(self):
        intent = dict(di.empty_intent(), nodes={'a': {'loopback': {'ipv4': '10.0.0.1'}},
                                                  'b': {'loopback': {'ipv4': '10.0.0.1'}}})
        errs = di.validate(intent, lab_nodes={'a': 'x', 'b': 'x'})
        self.assertError(errs, 'nodes.b.loopback.ipv4', 'duplicate')

    def test_loopback_address_of_the_wrong_family_is_refused(self):
        intent = dict(di.empty_intent(), nodes={'a': {'loopback': {'ipv4': '2001:db8::1'}}})
        errs = di.validate(intent, lab_nodes={'a': 'x'})
        self.assertError(errs, 'nodes.a.loopback.ipv4', 'ipv4')


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class NodeModuleSettingsAdvancedTests(DesignIntentTestCase):
    def setUp(self):
        self.schema = engine_schema()

    def test_node_module_setting_passes_at_node_level(self):
        intent = dict(di.empty_intent(), modules=['bgp'], nodes={'a': {'bgp': {'rr': True}}})
        self.assertClean(di.validate(intent, schema=self.schema, lab_nodes={'a': 'x'}))

    def test_node_module_setting_fails_at_node_level(self):
        intent = dict(di.empty_intent(), modules=['bgp'], nodes={'a': {'bgp': {'rr': 'yes'}}})
        errs = di.validate(intent, schema=self.schema, lab_nodes={'a': 'x'})
        self.assertError(errs, 'nodes.a.bgp.rr', 'type')


# --- links -------------------------------------------------------------------------------------------------

class LinkTests(DesignIntentTestCase):
    K = 'a:eth1--b:eth1'
    K2 = 'c:eth1--d:eth1'

    def test_invalid_link_key_without_double_dash_is_refused(self):
        intent = dict(di.empty_intent(), links={'nodashes': {}})
        self.assertError(di.validate(intent), 'links.nodashes', 'invalid')

    def test_unknown_link_with_lab_links_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {}})
        errs = di.validate(intent, lab_links=['other:eth1--x:eth1'])
        self.assertError(errs, 'links.' + self.K, 'not in the lab')

    def test_unknown_link_setting_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'bogus': 1}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.bogus', 'unknown')

    def test_link_prefix_false_is_accepted(self):
        intent = dict(di.empty_intent(), links={self.K: {'prefix': False}})
        self.assertClean(di.validate(intent, lab_links=[self.K]))

    def test_link_prefix_dict_with_ipv4_is_accepted(self):
        intent = dict(di.empty_intent(), links={self.K: {'prefix': {'ipv4': '10.1.1.0/31'}}})
        self.assertClean(di.validate(intent, lab_links=[self.K]))

    def test_two_links_with_overlapping_prefixes_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'prefix': {'ipv4': '10.1.1.0/24'}},
                                                  self.K2: {'prefix': {'ipv4': '10.1.1.128/25'}}})
        errs = di.validate(intent, lab_links=[self.K, self.K2])
        self.assertError(errs, 'links.' + self.K2 + '.prefix.ipv4', 'overlap')

    def test_link_prefix_bad_allocation_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'prefix': {'ipv4': '10.1.1.0/31', 'allocation': 'bogus'}}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.prefix.allocation', 'sequential')

    def test_link_pool_must_be_defined(self):
        intent = dict(di.empty_intent(), links={self.K: {'pool': 'nosuchpool'}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.pool', 'defined')

    def test_link_pool_builtin_name_is_accepted(self):
        intent = dict(di.empty_intent(), links={self.K: {'pool': 'p2p'}})
        self.assertClean(di.validate(intent, lab_links=[self.K]))

    def test_link_role_bad_value_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'role': 'bogus'}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.role', 'stub')

    def test_link_type_bad_value_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'type': 'bogus'}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.type', 'lan')

    def test_link_mtu_below_bound_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'mtu': 10}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.mtu', 'mtu')

    def test_link_bandwidth_below_bound_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'bandwidth': -1}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.bandwidth', 'bandwidth')

    def test_link_level_ipv4_must_be_boolean(self):
        intent = dict(di.empty_intent(), links={self.K: {'ipv4': 'yes'}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.ipv4', 'switches')

    def test_link_level_ipv6_must_be_boolean(self):
        intent = dict(di.empty_intent(), links={self.K: {'ipv6': 'yes'}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.ipv6', 'switches')

    def test_endpoint_device_not_on_link_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'endpoints': {'zzz': {}}}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.endpoints.zzz', 'not on this link')

    def test_endpoint_address_outside_link_prefix_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'prefix': {'ipv4': '10.1.1.0/31'},
                                                            'endpoints': {'a': {'ipv4': '10.1.2.5'}}}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.endpoints.a.ipv4', 'outside')

    def test_endpoint_address_equal_to_a_node_loopback_is_refused(self):
        intent = dict(di.empty_intent(), nodes={'a': {'loopback': {'ipv4': '10.1.1.0'}}},
                      links={self.K: {'endpoints': {'a': {'ipv4': '10.1.1.0'}}}})
        errs = di.validate(intent, lab_links=[self.K], lab_nodes={'a': 'x', 'b': 'x'})
        self.assertError(errs, 'links.' + self.K + '.endpoints.a.ipv4', 'duplicate')

    def test_endpoint_integer_ordinal_below_1_is_refused(self):
        intent = dict(di.empty_intent(), links={self.K: {'endpoints': {'a': {'ipv4': 0}}}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.endpoints.a.ipv4', 'counts from 1')

    def test_endpoint_integer_ordinal_of_1_or_more_is_accepted(self):
        intent = dict(di.empty_intent(), links={self.K: {'endpoints': {'a': {'ipv4': 3}}}})
        self.assertClean(di.validate(intent, lab_links=[self.K]))


@unittest.skipUnless(HAS_NETLAB, SKIP_REASON)
class LinkModuleSettingsAdvancedTests(DesignIntentTestCase):
    K = 'a:eth1--b:eth1'

    def setUp(self):
        self.schema = engine_schema()

    def test_interface_level_module_setting_passes(self):
        intent = dict(di.empty_intent(), modules=['ospf'],
                      links={self.K: {'endpoints': {'a': {'ospf': {'priority': 10}}}}})
        self.assertClean(di.validate(intent, schema=self.schema, lab_links=[self.K]))

    def test_interface_level_module_setting_fails(self):
        intent = dict(di.empty_intent(), modules=['ospf'],
                      links={self.K: {'endpoints': {'a': {'ospf': {'priority': 300}}}}})
        errs = di.validate(intent, schema=self.schema, lab_links=[self.K])
        self.assertError(errs, 'links.' + self.K + '.endpoints.a.ospf.priority', 'type')

    def test_lag_member_links_are_accepted_on_the_carrying_link_only(self):
        K2 = 'a:eth2--b:eth2'; K3 = 'a:eth3--c:eth1'
        good = dict(di.empty_intent(), modules=['lag'], links={self.K: {'lag': {'members': [K2]}}})
        self.assertClean(di.validate(good, schema=self.schema, lab_links=[self.K, K2, K3]))
        bad = dict(di.empty_intent(), modules=['lag'], links={self.K: {'lag': {'members': [self.K, K3, 'nope', K2, K2]}}})
        errs = di.validate(bad, schema=self.schema, lab_links=[self.K, K2, K3])
        messages = ' | '.join(e['message'] for e in errs if e['path'] == 'links.' + self.K + '.lag.members')
        for fragment in ('is a member by itself', 'same two devices', 'No link with this key', 'listed twice'):
            self.assertIn(fragment, messages)
        node_level = dict(di.empty_intent(), modules=['lag'], nodes={'a': {'lag': {'members': [K2]}}})
        self.assertError(di.validate(node_level, schema=self.schema, lab_nodes={'a': 'arista_ceos'}, lab_links=[self.K, K2]), 'nodes.a.lag.members', 'carries the aggregation')
        elsewhere = dict(di.empty_intent(), modules=['vlan'], vlans={'red': {'id': 100, 'members': ['x']}})
        self.assertError(di.validate(elsewhere, schema=self.schema), 'vlans.red.members', 'not accepted')

    def test_a_lag_member_that_carries_its_own_bundle_or_belongs_to_two_is_refused(self):
        # Audit 2026-10-03 L-17: such links used to pass and then vanish from the plan without a word.
        K2 = 'a:eth2--b:eth2'; K3 = 'a:eth3--b:eth3'; links = [self.K, K2, K3]
        cycle = dict(di.empty_intent(), modules=['lag'], links={self.K: {'lag': {'members': [K2]}}, K2: {'lag': {'members': [self.K]}}})
        errs = di.validate(cycle, schema=self.schema, lab_links=links)
        self.assertError(errs, 'links.' + self.K + '.lag.members', 'carries an aggregation of its own: ' + K2)
        self.assertError(errs, 'links.' + K2 + '.lag.members', 'carries an aggregation of its own: ' + self.K)
        chain = dict(di.empty_intent(), modules=['lag'], links={self.K: {'lag': {'members': [K2]}}, K2: {'lag': {'members': [K3]}}})
        errs = di.validate(chain, schema=self.schema, lab_links=links)
        self.assertError(errs, 'links.' + self.K + '.lag.members', 'carries an aggregation of its own: ' + K2)
        self.assertFalse([e for e in errs if e['path'] == 'links.' + K2 + '.lag.members'], errs)
        twice = dict(di.empty_intent(), modules=['lag'], links={self.K: {'lag': {'members': [K3]}}, K2: {'lag': {'members': [K3]}}})
        errs = di.validate(twice, schema=self.schema, lab_links=links)
        self.assertError(errs, 'links.' + K2 + '.lag.members', 'already a member of the aggregation carried by ' + self.K)
        self.assertFalse([e for e in errs if e['path'] == 'links.' + self.K + '.lag.members'], errs)

    def test_isis_area_default_origination_and_redistribution_forms(self):
        ok = dict(di.empty_intent(), modules=['isis', 'bgp', 'ospf'], isis={'area': '49.0001'}, bgp={'as': 65000},
                  nodes={'a': {'bgp': {'originate': ['0.0.0.0/0', '::/0'], 'import': {'ospf': True}}}})
        self.assertClean(di.validate(ok, schema=self.schema, lab_nodes={'a': 'arista_ceos'}, management=[('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))]))
        full = dict(di.empty_intent(), modules=['isis'], isis={'area': '49.0001.0000.0000.0001.00'})
        self.assertClean(di.validate(full, schema=self.schema))
        bad_area = dict(di.empty_intent(), modules=['isis'], isis={'area': 'zz.1'})
        self.assertError(di.validate(bad_area, schema=self.schema), 'isis.area', 'type')
        managed = dict(di.empty_intent(), modules=['bgp'], bgp={'as': 65000}, nodes={'a': {'bgp': {'originate': ['172.20.20.0/24']}}})
        self.assertError(di.validate(managed, schema=self.schema, lab_nodes={'a': 'arista_ceos'}, management=[('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))]), 'nodes.a.bgp.originate[0]', 'management')
        crashy = dict(di.empty_intent(), modules=['bgp', 'ospf'], bgp={'as': 65000}, nodes={'a': {'bgp': {'import': {'ospf': None}}}})
        self.assertError(di.validate(crashy, schema=self.schema, lab_nodes={'a': 'arista_ceos'}), 'nodes.a.bgp.import', 'true or to a mapping')


# --- interfaces overrides ------------------------------------------------------------------------------------

class InterfaceOverrideTests(DesignIntentTestCase):
    K = 'a:eth1--b:eth1'

    def test_unknown_link_with_lab_links_is_refused(self):
        intent = dict(di.empty_intent(), interfaces={'nosuch--x:eth1': {'a': 'Ethernet7'}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'interfaces.nosuch--x:eth1', 'not in the lab')

    def test_name_with_a_space_is_refused(self):
        intent = dict(di.empty_intent(), interfaces={self.K: {'a': 'Ethernet 7'}})
        errs = di.validate(intent, lab_links=[self.K])
        self.assertError(errs, 'interfaces.' + self.K + '.a', 'device itself shows')

    def test_ethernet7_is_accepted(self):
        intent = dict(di.empty_intent(), interfaces={self.K: {'a': 'Ethernet7'}})
        self.assertClean(di.validate(intent, lab_links=[self.K]))


# --- allocations ledger -----------------------------------------------------------------------------------

class LedgerValidationTests(DesignIntentTestCase):
    def test_accepted_shape_validates_cleanly(self):
        intent = dict(di.empty_intent(), allocations={
            'node_ids': {'a': 1, 'b': 2},
            'loopbacks': {'a': {'ipv4': '10.0.0.1'}},
            'links': {'a:eth1--b:eth1': {'ipv4': '10.1.1.0/31'}},
            'router_ids': {'a': '10.0.0.1'}})
        self.assertClean(di.validate(intent))

    def test_duplicate_node_ids_are_refused(self):
        intent = dict(di.empty_intent(), allocations={'node_ids': {'a': 1, 'b': 1}})
        self.assertError(di.validate(intent), 'allocations.node_ids', 'distinct')

    def test_node_id_above_the_maximum_is_refused(self):
        intent = dict(di.empty_intent(), allocations={'node_ids': {'a': di.MAX_NODE_ID + 50}})
        self.assertError(di.validate(intent), 'allocations.node_ids', str(di.MAX_NODE_ID))

    def test_invalid_loopback_is_refused(self):
        intent = dict(di.empty_intent(), allocations={'loopbacks': {'a': {'ipv4': 'garbage'}}})
        self.assertError(di.validate(intent), 'allocations.loopbacks.a.ipv4', 'valid')

    def test_invalid_link_prefix_is_refused(self):
        intent = dict(di.empty_intent(), allocations={'links': {'k1': {'ipv4': 'garbage'}}})
        self.assertError(di.validate(intent), 'allocations.links.k1.ipv4', 'valid')

    def test_router_ids_must_be_ipv4(self):
        intent = dict(di.empty_intent(), allocations={'router_ids': {'a': '2001:db8::1'}})
        self.assertError(di.validate(intent), 'allocations.router_ids', 'ipv4')

    def test_ledger_unexpected_shape_is_refused(self):
        intent = dict(di.empty_intent(), allocations={'bogus_section': {}})
        self.assertError(di.validate(intent), 'allocations', 'unexpected shape')


class LedgerHelperTests(DesignIntentTestCase):
    def test_link_key_is_order_independent(self):
        self.assertEqual(di.link_key([('a', 'eth1'), ('b', 'eth1')]),
                          di.link_key([('b', 'eth1'), ('a', 'eth1')]))

    def test_link_key_includes_both_interfaces(self):
        key = di.link_key([('a', 'eth1'), ('b', 'eth2')])
        self.assertIn('a:eth1', key)
        self.assertIn('b:eth2', key)

    def test_ledger_from_plan_maps_links_by_order_and_stops_at_shorter_list(self):
        transformed = {
            'nodes': {
                'a': {'id': 1, 'loopback': {'ipv4': '10.0.0.1'}, 'ospf': {'router_id': '10.0.0.1'}},
                'b': {'id': 2, 'loopback': {'ipv4': '10.0.0.2'}},
            },
            'links': [{'prefix': {'ipv4': '10.1.1.0/31'}}, {'prefix': {'ipv4': '10.1.1.2/31'}}],
        }
        ledger = di.ledger_from_plan(transformed, ['k1', 'k2', 'k3'])
        self.assertEqual(ledger['node_ids'], {'a': 1, 'b': 2})
        self.assertEqual(ledger['loopbacks'], {'a': {'ipv4': '10.0.0.1'}, 'b': {'ipv4': '10.0.0.2'}})
        self.assertEqual(ledger['links'], {'k1': {'ipv4': '10.1.1.0/31'}, 'k2': {'ipv4': '10.1.1.2/31'}})
        self.assertEqual(ledger['router_ids'], {'a': '10.0.0.1'})

        # fewer keys than links: stops at the shorter list, does not raise
        shorter = di.ledger_from_plan(transformed, ['k1'])
        self.assertEqual(shorter['links'], {'k1': {'ipv4': '10.1.1.0/31'}})

    def test_renumbering_reports_changed_loopback_and_link_prefix(self):
        previous = {'loopbacks': {'a': {'ipv4': '10.0.0.1'}},
                    'links': {'k1': {'ipv4': '10.1.1.0/31'}},
                    'node_ids': {'a': 1}, 'router_ids': {'a': '10.0.0.1'}}
        current = {'loopbacks': {'a': {'ipv4': '10.0.0.9'}},
                   'links': {'k1': {'ipv4': '10.1.1.4/31'}},
                   'node_ids': {'a': 1}, 'router_ids': {'a': '10.0.0.1'}}
        changes = di.renumbering(previous, current)
        kinds = {(c['kind'], c['name']) for c in changes}
        self.assertIn(('loopbacks', 'a'), kinds)
        self.assertIn(('links', 'k1'), kinds)
        self.assertEqual(len(changes), 2)

    def test_renumbering_ignores_new_names(self):
        previous = {'loopbacks': {'a': {'ipv4': '10.0.0.1'}}}
        current = {'loopbacks': {'a': {'ipv4': '10.0.0.1'}, 'b': {'ipv4': '10.0.0.2'}}}
        self.assertEqual(di.renumbering(previous, current), [])

    def test_renumbering_reports_nothing_for_identical_values(self):
        previous = {'node_ids': {'a': 1}, 'router_ids': {'a': '10.0.0.1'},
                    'loopbacks': {'a': {'ipv4': '10.0.0.1'}}, 'links': {}}
        current = {'node_ids': {'a': 1}, 'router_ids': {'a': '10.0.0.1'},
                   'loopbacks': {'a': {'ipv4': '10.0.0.1'}}, 'links': {}}
        self.assertEqual(di.renumbering(previous, current), [])


# --- document size limit ------------------------------------------------------------------------------------

class DocumentSizeTests(DesignIntentTestCase):
    def test_document_over_512_kib_is_refused_with_a_single_error(self):
        intent = dict(di.empty_intent(), nodes={('n%06d' % k): {} for k in range(50000)})
        self.assertGreater(len(json.dumps(intent)), di.MAX_DOCUMENT)
        errs = di.validate(intent)
        self.assertEqual(len(errs), 1)
        self.assertEqual(errs[0]['path'], '')
        self.assertIn('512', errs[0]['message'])



# --- regressions from the risk review of 1.30.43 --------------------------------------------------------------

class ReviewRegressionTests(DesignIntentTestCase):
    """The recursive guard and the VLAN/VRF schemas: what the first review proved was let through."""

    def test_an_include_key_is_refused_at_any_depth(self):
        intent = dict(di.empty_intent(), modules=['vrf', 'ospf'], vrfs={'red': {'ospf': {'_include': ['../../outside/leak.yml']}}})
        errs = di.validate(intent, schema=None)
        self.assertError(errs, 'vrfs.red.ospf._include', 'not accepted')
        self.assertEqual(len(errs), 1, 'the guard stops validation with the one problem')

    def test_a_password_under_a_vrf_is_refused_by_name(self):
        intent = dict(di.empty_intent(), modules=['vrf', 'ospf'], vrfs={'red': {'ospf': {'password': 'S3cretVRF'}}})
        self.assertError(di.validate(intent, schema=None), 'vrfs.red.ospf.password', 'not accepted')

    def test_a_denied_key_inside_a_typed_dict_is_refused(self):
        intent = dict(di.empty_intent(), modules=['routing'], routing={'prefix': {'config': [{'action': 'permit'}]}})
        self.assertError(di.validate(intent, schema=None), 'routing.prefix.config', 'not accepted')

    def test_text_with_a_newline_is_refused_wherever_it_is(self):
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100, 'mode': 'blue\nusername evil privilege 15 secret 0 pwned'}})
        self.assertError(di.validate(intent, schema=None), 'vlans.v1.mode', 'control characters')

    def test_quotes_braces_and_semicolons_are_refused_in_a_link_name(self):
        key = 'a:eth1--b:eth1'
        for bad in ('x"; system { }', "it's", 'a{b}', 'a;b', 'back\\slash', 'tick`'):
            intent = dict(di.empty_intent(), links={key: {'name': bad}})
            self.assertError(di.validate(intent, schema=None), 'links.' + key + '.name', 'quotes')

    def test_links_and_members_inside_a_vlan_or_vrf_are_refused(self):
        # A link body with a denied key inside is stopped by the guard first (the key is named)...
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'links': [{'r1': {'ifname': 'Ethernet7'}, 'r2': {}}, 'r1-r2']}})
        self.assertError(di.validate(intent, schema=None), 'vrfs.red.links[0].r1.ifname', 'not accepted')
        # ... and a plain link list, which the guard lets through, is refused by the object check.
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'links': ['r1-r2']}})
        self.assertError(di.validate(intent, schema=None), 'vrfs.red.links', 'topology')
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100, 'members': ['r1-r2']}})
        self.assertError(di.validate(intent, schema=None), 'vlans.v1.members', 'not accepted')

    def test_a_vlan_or_vrf_with_an_id_is_accepted(self):
        intent = dict(di.empty_intent(), modules=['vlan', 'vrf'], vlans={'v1': {'id': 100}}, vrfs={'red': {'id': 1}})
        self.assertClean(di.validate(intent, schema=None))

    def test_a_deeply_nested_document_is_refused(self):
        value = 1
        for _ in range(20): value = {'a': value}
        intent = dict(di.empty_intent(), modules=['ospf'], ospf=value)
        errs = di.validate(intent, schema=None)
        self.assertEqual(len(errs), 1)
        self.assertIn('nested', errs[0]['message'])
        self.assertTrue(errs[0]['path'].startswith('ospf.a.a'))

    def test_link_prefix_loopback_endpoint_and_ledger_inside_the_management_network_are_refused(self):
        import ipaddress
        mgmt = [('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))]
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), links={key: {'prefix': {'ipv4': '172.20.20.10/31'}}})
        self.assertError(di.validate(intent, management=mgmt), 'links.' + key + '.prefix.ipv4', 'management')
        intent = dict(di.empty_intent(), nodes={'a': {'loopback': {'ipv4': '172.20.20.12/32'}}})
        self.assertError(di.validate(intent, management=mgmt), 'nodes.a.loopback.ipv4', 'management')
        intent = dict(di.empty_intent(), links={key: {'endpoints': {'a': {'ipv4': '172.20.20.13'}}}})
        self.assertError(di.validate(intent, management=mgmt), 'links.' + key + '.endpoints.a.ipv4', 'management')
        intent = dict(di.empty_intent(), allocations={'links': {key: {'ipv4': '172.20.20.20/31'}}})
        self.assertError(di.validate(intent, management=mgmt), 'allocations.links.' + key + '.ipv4', 'management')
        intent = dict(di.empty_intent(), allocations={'loopbacks': {'a': {'ipv4': '172.20.20.99/32'}}})
        self.assertError(di.validate(intent, management=mgmt), 'allocations.loopbacks.a.ipv4', 'management')


@unittest.skipUnless(shutil.which('netlab'), 'netlab is not on PATH for this test run')
class ReviewRegressionSchemaTests(DesignIntentTestCase):
    """VLAN and VRF bodies are checked against the engine's own object schema."""

    @classmethod
    def setUpClass(cls):
        cls.schema = engine_schema()

    def test_vlan_body_is_checked_against_the_engine_schema(self):
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100, 'mode': 'irb', 'vni': 10100}})
        self.assertClean(di.validate(intent, schema=self.schema))
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100, 'mode': 'weird'}})
        self.assertError(di.validate(intent, schema=self.schema), 'vlans.v1.mode', 'choose')
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100, 'bogus': 1}})
        self.assertError(di.validate(intent, schema=self.schema), 'vlans.v1.bogus', 'unknown')

    def test_vlan_prefix_is_checked_as_a_prefix(self):
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100, 'prefix': {'ipv4': '10.7.0.0/24'}}})
        self.assertClean(di.validate(intent, schema=self.schema))
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100, 'prefix': {'ipv4': 'nonsense'}}})
        self.assertError(di.validate(intent, schema=self.schema), 'vlans.v1.prefix.ipv4', 'type')

    def test_vrf_body_is_checked_against_the_engine_schema(self):
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'id': 1, 'rd': '65000:1', 'import': ['65000:1'], 'export': ['65000:1']}})
        self.assertClean(di.validate(intent, schema=self.schema))
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'rd': 'not-an-rd'}})
        self.assertError(di.validate(intent, schema=self.schema), 'vrfs.red.rd', 'type')

    def test_named_types_come_from_the_top_level_schema_or_a_types_key(self):
        from_top = di.named_types({'attributes': {'top': {'global': {}, 'node': {}, 'pfx_entry': {'action': 'str'}}}})
        self.assertEqual(set(from_top), {'pfx_entry'})
        from_types = di.named_types({'attributes': {}, 'types': {'pfx_entry': {'action': 'str'}, 'link': {}}})
        self.assertEqual(set(from_types), {'pfx_entry'})




class SecondPassRegressionTests(DesignIntentTestCase):

    def test_unicode_line_separators_and_c1_controls_are_refused(self):
        key = 'a:eth1--b:eth1'
        for bad in ('core username x', 'a b', 'a\x85b', 'a\x9fb'):
            intent = dict(di.empty_intent(), links={key: {'name': bad}})
            self.assertError(di.validate(intent, schema=None), 'links.' + key + '.name', 'control')
        intent = dict(di.empty_intent(), links={key: {'name': 'Core link to Zürich, uplink #1 (10G)'}})
        self.assertClean(di.validate(intent, schema=None))

    def test_a_vrf_is_attached_by_name_and_a_module_can_be_switched_off(self):
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), modules=['vrf', 'ospf'], vrfs={'red': {'id': 1}}, links={key: {'vrf': 'red', 'ospf': False, 'endpoints': {'a': {'vrf': 'red', 'ospf': False}}}})
        self.assertClean(di.validate(intent, schema=None))
        # At the device or the global level those forms crash the engine (BoxTypeError/BoxValueError): refused here.
        intent = dict(di.empty_intent(), modules=['vrf', 'ospf'], vrfs={'red': {'id': 1}}, nodes={'a': {'vrf': 'red', 'ospf': False}})
        errs = di.validate(intent, schema=None)
        self.assertError(errs, 'nodes.a.vrf', 'link')
        self.assertError(errs, 'nodes.a.ospf', 'modules list')
        intent = dict(di.empty_intent(), modules=['ospf'], ospf=False)
        self.assertError(di.validate(intent, schema=None), 'ospf', 'modules list')
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'id': 1}}, links={key: {'vrf': 'blue'}})
        self.assertError(di.validate(intent, schema=None), 'links.' + key + '.vrf', 'no vrf')


@unittest.skipUnless(shutil.which('netlab'), 'netlab is not on PATH for this test run')
class SecondPassRegressionSchemaTests(DesignIntentTestCase):

    @classmethod
    def setUpClass(cls):
        cls.schema = engine_schema()
        import ipaddress
        cls.mgmt = [('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))]

    def test_a_prefix_inside_a_module_setting_may_not_touch_the_management_network(self):
        intent = dict(di.empty_intent(), modules=['routing'], nodes={'a': {'routing': {'static': [{'ipv4': '172.20.20.0/25', 'nexthop': {'discard': True}}]}}})
        self.assertError(di.validate(intent, schema=self.schema, management=self.mgmt), 'nodes.a.routing.static[0].ipv4', 'management')
        intent = dict(di.empty_intent(), modules=['routing'], nodes={'a': {'routing': {'static': [{'ipv4': '10.9.0.0/24', 'nexthop': {'discard': True}}]}}})
        self.assertClean(di.validate(intent, schema=self.schema, management=self.mgmt))

    def test_a_vrf_loopback_inside_the_management_network_is_refused(self):
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'loopback': '172.20.20.101/32'}})
        self.assertError(di.validate(intent, schema=self.schema, management=self.mgmt), 'vrfs.red.loopback', 'management')

    def test_the_management_pool_is_refused_wherever_a_pool_is_named(self):
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100, 'prefix': {'pool': 'mgmt'}}})
        self.assertError(di.validate(intent, schema=self.schema), 'vlans.v1.prefix.pool', 'management')

    def test_vlan_trunk_and_access_name_defined_vlans(self):
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100}, 'v2': {'id': 200}}, links={key: {'vlan': {'trunk': ['v1', 'v2']}}})
        self.assertClean(di.validate(intent, schema=self.schema))
        intent = dict(di.empty_intent(), modules=['vlan'], vlans={'v1': {'id': 100}}, links={key: {'vlan': {'trunk': ['v1', 'v9'], 'access': 'v8'}}})
        errs = di.validate(intent, schema=self.schema)
        self.assertError(errs, 'links.' + key + '.vlan.trunk', 'no vlan')
        self.assertError(errs, 'links.' + key + '.vlan.access', 'no vlan')


class ThirdPassRegressionTests(DesignIntentTestCase):

    def test_an_interface_address_is_guarded_by_its_whole_subnet(self):
        import ipaddress
        mgmt = [('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))]
        key = 'a:eth1--b:eth1'
        intent = dict(di.empty_intent(), links={key: {'endpoints': {'a': {'ipv4': '172.20.0.1/16'}}}})
        self.assertError(di.validate(intent, management=mgmt), 'links.' + key + '.endpoints.a.ipv4', 'management')
        intent = dict(di.empty_intent(), nodes={'a': {'loopback': {'ipv4': '172.20.0.1/16'}}})
        self.assertError(di.validate(intent, management=mgmt), 'nodes.a.loopback.ipv4', 'management')


class MalformedShapeTests(DesignIntentTestCase):
    """A malformed document is a problem list, never an exception (the routes would answer 500 without one)."""

    def test_families_that_are_not_a_mapping_are_one_problem_whatever_the_pools(self):
        for families in ('x', None, 1, True, [], ['ipv4']):
            with self.subTest(families=families):
                errs = di.validate(dict(di.empty_intent(), families=families))   # the default pools carry valid prefixes
                self.assertOnlyError(errs, 'families', 'Enable IPv4, IPv6 or both')

    def test_device_modules_with_unhashable_entries_are_one_problem(self):
        for modules in ([['ospf']], [{}], [[]], ['ospf', ['bgp']]):
            with self.subTest(modules=modules):
                errs = di.validate(dict(di.empty_intent(), modules=['ospf'], nodes={'r1': {'modules': modules}}))
                self.assertOnlyError(errs, 'nodes.r1.modules', 'supported list')


@unittest.skipUnless(shutil.which('netlab'), 'netlab is not on PATH for this test run')
class ThirdPassRegressionSchemaTests(DesignIntentTestCase):

    @classmethod
    def setUpClass(cls):
        cls.schema = engine_schema()
        import ipaddress
        cls.mgmt = [('mgmt ipv4-subnet', ipaddress.ip_network('172.20.20.0/24'))]

    def test_a_vrf_loopback_in_dict_form_is_checked_and_guarded(self):
        import ipaddress
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'loopback': {'ipv4': '172.20.20.101/32'}}})
        self.assertError(di.validate(intent, schema=self.schema, management=self.mgmt), 'vrfs.red.loopback.ipv4', 'management')
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'loopback': {'pool': 'mgmt'}}})
        self.assertError(di.validate(intent, schema=self.schema, management=self.mgmt), 'vrfs.red.loopback.pool', 'management')
        intent = dict(di.empty_intent(), modules=['vrf'], vrfs={'red': {'loopback': {'ipv4': '10.2.0.0/24'}}})
        self.assertClean(di.validate(intent, schema=self.schema, management=self.mgmt))
        intent = dict(di.empty_intent(), modules=['vrf'], nodes={'a': {'vrfs': {'red': {'loopback': {'ipv6': '3fff:172:20:20::5/128'}}}}})
        mgmt6 = [('mgmt ipv6-subnet', ipaddress.ip_network('3fff:172:20:20::/64'))]
        self.assertError(di.validate(intent, schema=self.schema, management=mgmt6), 'nodes.a.vrfs.red.loopback.ipv6', 'management')

    def test_a_setting_with_alternative_scalar_types_accepts_the_scalar_form(self):
        intent = dict(di.empty_intent(), modules=['bgp'], bgp={'as': 65000}, nodes={'a': {'bgp': {'originate': ['10.9.0.0/24']}}})
        self.assertClean(di.validate(intent, schema=self.schema))

if __name__ == '__main__':
    unittest.main()
