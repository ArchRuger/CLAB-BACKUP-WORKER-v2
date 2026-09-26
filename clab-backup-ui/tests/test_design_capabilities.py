"""The netlab-integration capability model (D3.1/D3.2): engine support read from the committed JSON,
the kind -> netlab profile table, and resolve()'s three-axis combination. A contract test regenerates
the JSON with the build tool and pins it against the committed copy; it is skipped, not failed, when
`netlab` is not on PATH (see CLAUDE.md's PATH prefix for running these tests)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app import design_capabilities as dc

BUILD_TOOL = Path(__file__).resolve().parents[2] / 'docs' / 'netlab-integration' / 'tools' / 'build_capability_data.py'


class TestEngineDataContract(unittest.TestCase):
    def test_regeneration_matches_committed_json(self):
        if shutil.which('netlab') is None:
            self.skipTest('netlab is not on PATH (activate clab-backup-ui/.venv first)')
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'design_capability_data.json'
            result = subprocess.run(
                [sys.executable, str(BUILD_TOOL), str(out)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            fresh = json.loads(out.read_text())
        committed = dc.engine_data()
        self.assertEqual(fresh['engine_version'], committed['engine_version'])
        self.assertEqual(fresh, committed)

    def test_every_features_module_is_in_the_engine_module_list(self):
        modules = set(dc.engine_data()['modules'])
        for feature_id, feature in dc.FEATURES.items():
            if feature['module'] is not None:
                self.assertIn(
                    feature['module'], modules,
                    f"FEATURES['{feature_id}']['module'] = {feature['module']!r} is not in the JSON's module list",
                )


class TestProfiles(unittest.TestCase):
    def test_the_four_profiles_map_as_stated(self):
        self.assertEqual(dc.profile_for('arista_ceos')['profile'], 'eos')
        self.assertEqual(dc.profile_for('juniper_vjunosswitch')['profile'], 'vjunos-switch')
        self.assertEqual(dc.profile_for('juniper_cjunosevolved')['profile'], 'vptx')
        self.assertEqual(dc.profile_for('cisco_xrv9k')['profile'], 'iosxr')

    def test_unmapped_kind_is_none(self):
        self.assertIsNone(dc.profile_for('juniper_crpd'))
        self.assertIsNone(dc.profile_for('not_a_real_kind'))

    def test_profile_for_returns_a_copy(self):
        first = dc.profile_for('arista_ceos')
        first['profile'] = 'mutated'
        self.assertEqual(dc.profile_for('arista_ceos')['profile'], 'eos')


ALL_KINDS = ['arista_ceos', 'juniper_vjunosswitch', 'juniper_cjunosevolved', 'cisco_xrv9k']


class TestResolve(unittest.TestCase):
    def test_eigrp_unsupported_everywhere_with_engine_reason(self):
        for kind in ALL_KINDS:
            r = dc.resolve('eigrp', kind)
            self.assertEqual(r['level'], 'unsupported', kind)
            self.assertFalse(r['engine'], kind)
            self.assertTrue(r['engine_reason'], kind)

    def test_srv6_generated_not_live_tested_on_iosxr_only(self):
        self.assertEqual(dc.resolve('srv6', 'cisco_xrv9k')['level'], 'generated_not_live_tested')
        self.assertTrue(dc.resolve('srv6', 'cisco_xrv9k')['engine'])
        for kind in ('arista_ceos', 'juniper_vjunosswitch', 'juniper_cjunosevolved'):
            r = dc.resolve('srv6', kind)
            self.assertEqual(r['level'], 'unsupported', kind)
            self.assertFalse(r['engine'], kind)

    def test_anycast_unsupported_on_iosxr_feature_flag_supported_on_junos_and_eos(self):
        r = dc.resolve('anycast_gateway', 'cisco_xrv9k')
        self.assertEqual(r['level'], 'unsupported')
        self.assertFalse(r['engine'])
        self.assertIn('gateway.protocol', r['engine_reason'])
        for kind in ('arista_ceos', 'juniper_vjunosswitch', 'juniper_cjunosevolved'):
            r = dc.resolve('anycast_gateway', kind)
            self.assertTrue(r['engine'], kind)
            self.assertNotEqual(r['level'], 'unsupported', kind)

    def test_wireguard_unsupported_everywhere(self):
        for kind in ALL_KINDS:
            r = dc.resolve('wireguard', kind)
            self.assertEqual(r['level'], 'unsupported', kind)
            self.assertFalse(r['engine'], kind)

    def test_gre_follows_the_engines_tunnel_flag_eos_only(self):
        # The resolved device features carry tunnel.gre for eos only; the Junos profiles declare no tunnel
        # flag, so GRE stays unsupported there until the engine says otherwise (fail closed).
        r = dc.resolve('gre', 'arista_ceos')
        self.assertTrue(r['engine'])
        self.assertNotEqual(r['level'], 'unsupported')
        self.assertIn('gre', dc.engine_data()['device_features']['eos'].get('tunnel', {}))
        for kind in ('juniper_vjunosswitch', 'juniper_cjunosevolved', 'cisco_xrv9k'):
            r = dc.resolve('gre', kind)
            self.assertFalse(r['engine'], kind)
            self.assertEqual(r['level'], 'unsupported', kind)

    def test_unknown_kind_unsupported_with_mapping_reason(self):
        r = dc.resolve('bgp', 'not_a_real_kind')
        self.assertEqual(r['level'], 'unsupported')
        self.assertEqual(r['profile'], '')
        self.assertEqual(r['reason'], dc.UNMAPPED_KIND_REASON)
        self.assertEqual(r['engine_reason'], dc.UNMAPPED_KIND_REASON)

    def test_validation_entry_reports_its_level_and_evidence(self):
        key = ('arista_ceos', 'bgp')
        self.assertNotIn(key, dc.VALIDATION)
        dc.VALIDATION[key] = {
            'level': 'verified_on_image',
            'evidence': 'docs/netlab-integration/evidence/eos-bgp.md',
        }
        try:
            r = dc.resolve('bgp', 'arista_ceos')
            self.assertEqual(r['level'], 'verified_on_image')
            self.assertEqual(r['evidence'], 'docs/netlab-integration/evidence/eos-bgp.md')
        finally:
            del dc.VALIDATION[key]

    def test_evpn_blocked_missing_prerequisite_then_not(self):
        blocked = dc.resolve('evpn', 'arista_ceos', requested_modules={'evpn'})
        self.assertEqual(blocked['level'], 'blocked_missing_prerequisite')
        self.assertIn('bgp', blocked['reason'])
        clear = dc.resolve('evpn', 'arista_ceos', requested_modules={'evpn', 'bgp', 'vxlan'})
        self.assertNotEqual(clear['level'], 'blocked_missing_prerequisite')

    def test_resolve_without_requested_modules_never_blocks_on_prerequisite(self):
        r = dc.resolve('evpn', 'arista_ceos')
        self.assertNotEqual(r['level'], 'blocked_missing_prerequisite')

    def test_resolve_always_has_all_keys(self):
        expected = {'feature', 'kind', 'profile', 'engine', 'engine_reason', 'image_limit', 'level', 'evidence', 'reason'}
        for kind in ALL_KINDS + ['not_a_real_kind']:
            self.assertEqual(set(dc.resolve('bgp', kind).keys()), expected, kind)


class TestEngineSupports(unittest.TestCase):
    def test_module_absent_is_not_supported(self):
        ok, reason = dc.engine_supports('eigrp', 'eos')
        self.assertFalse(ok)
        self.assertIn('eigrp', reason)

    def test_always_feature_is_always_supported(self):
        ok, reason = dc.engine_supports('lldp', 'iosxr')
        self.assertTrue(ok)

    def test_plugin_feature_flag_value_lookup(self):
        ok, _ = dc.engine_supports('gre', 'eos')
        self.assertTrue(ok)
        ok, _ = dc.engine_supports('gre', 'iosxr')
        self.assertFalse(ok)


class TestMatrix(unittest.TestCase):
    def test_matrix_one_row_per_pair_all_keys(self):
        kinds = ALL_KINDS
        feature_ids = ['bgp', 'eigrp', 'srv6']
        rows = dc.matrix(kinds, feature_ids)
        self.assertEqual(len(rows), len(kinds) * len(feature_ids))
        expected_keys = {'feature', 'kind', 'profile', 'engine', 'engine_reason', 'image_limit', 'level', 'evidence', 'reason'}
        for row in rows:
            self.assertEqual(set(row.keys()), expected_keys)
        pairs = {(row['kind'], row['feature']) for row in rows}
        self.assertEqual(len(pairs), len(rows))

    def test_matrix_default_feature_ids_covers_all_features(self):
        rows = dc.matrix(['arista_ceos'])
        self.assertEqual(len(rows), len(dc.FEATURES))


class TestPublicCatalogue(unittest.TestCase):
    def test_lists_every_feature_with_a_label(self):
        catalogue = dc.public_catalogue()
        ids = {entry['id'] for entry in catalogue}
        self.assertEqual(ids, set(dc.FEATURES.keys()))
        for entry in catalogue:
            self.assertIn('label', entry)
            self.assertTrue(entry['label'])
            self.assertIn('family', entry)
            self.assertIn('module', entry)
            self.assertNotIn('attributes', entry)
            self.assertNotIn('feature_flag', entry)


if __name__ == '__main__':
    unittest.main()
