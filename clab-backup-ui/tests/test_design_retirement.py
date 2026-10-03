"""Tests for the retirement of EIGRP, RIP and VXLAN and the gating of EVPN in *Network design* (D10.1-D10.3 in
docs/netlab-integration/DECISIONS.md; the API in docs/uiux-email-2026-10-03/DESIGN-CONTRACT.md).

The policy under test: the modules stay readable everywhere (a stored design parses, validates, renders, exports),
Save and Import refuse only a retired use that is new compared with the stored design, Generate refuses a design
that uses one (409, nothing queued), and Apply (review and submit) refuses a plan that carries one, including plans
generated before the retirement. The capability matrix words them `retired` instead of "not supported".

Scratch state only (create_app(<tempdir>)); no engine run, no device, no VM.
"""
import copy
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app import design_capabilities as dc
from app import design_intent as di
from app.main import create_app
from test_design_apply import FRAGMENT, DesignApplyTestCase, add_generation, node_map
from test_network_design import TOPOLOGY, add_lab, plant_design, valid_intent

LINK = 'ceos:eth3--host1:eth2'


def vxlan_intent():
    """A design as it could be saved before the retirement: VLANs carried over VXLAN with EVPN."""
    intent = di.empty_intent()
    intent['modules'] = ['vlan', 'vxlan', 'bgp', 'evpn']
    intent['nodes'] = {'xrv9k': {'role': 'exclude'}}
    intent['bgp'] = {'as': 65000}
    intent['vlans'] = {'red': {'id': 100}}
    intent['links'] = {LINK: {'vlan': {'access': 'red'}}}
    return intent


class RetiredPolicyTests(unittest.TestCase):
    def test_retired_modules_stay_in_the_schema_but_not_in_authoring(self):
        for module in ('eigrp', 'ripv2', 'vxlan', 'evpn'):
            self.assertIn(module, di.MODULES)
            self.assertIn(module, di.RETIRED)
            self.assertNotIn(module, di.AUTHORING_MODULES)
            self.assertIn(module, di.TOP_KEYS)   # stored documents keep parsing
        self.assertEqual(set(di.MODULES) - set(di.AUTHORING_MODULES), set(di.RETIRED))
        self.assertEqual(di.RETIRED_STATUS['evpn'], 'under_review')
        self.assertEqual({di.RETIRED_STATUS[m] for m in ('eigrp', 'ripv2', 'vxlan')}, {'retired'})
        self.assertEqual(di.RETIRED_LABELS['ripv2'], 'RIP')
        self.assertEqual(di.RETIRED_FEATURES['ripng'], 'ripv2')

    def test_the_evpn_reason_is_product_specific(self):
        reason = di.RETIRED['evpn']
        for words in ('VXLAN', 'MPLS', 'Junos', 'not available'):
            self.assertIn(words, reason)

    def test_retired_in_walks_every_level(self):
        intent = {'modules': ['ospf', 'eigrp', 'vxlan'], 'eigrp': {'as': 1},
                  'nodes': {'r1': {'modules': ['ripv2'], 'ripv2': {}, 'vrfs': {'blue': {'evpn': {}}}}, 'r2': 'junk'},
                  'links': {'a:e1--b:e1': {'vxlan': {}, 'endpoints': {'a': {'evpn': {}}, 'b': None}}, 'bad': 3},
                  'vlans': {'red': {'evpn': {}}}, 'vrfs': {'blue': {'evpn': {}}}}
        found = {(e['path'], e['module']) for e in di.retired_in(intent)}
        self.assertEqual(found, {('modules', 'eigrp'), ('modules', 'vxlan'), ('eigrp', 'eigrp'),
                                 ('nodes.r1.modules', 'ripv2'), ('nodes.r1.ripv2', 'ripv2'), ('nodes.r1.vrfs.blue.evpn', 'evpn'),
                                 ('links.a:e1--b:e1.vxlan', 'vxlan'), ('links.a:e1--b:e1.endpoints.a.evpn', 'evpn'),
                                 ('vlans.red.evpn', 'evpn'), ('vrfs.blue.evpn', 'evpn')})
        self.assertTrue(all(e['message'] == di.RETIRED[e['module']] for e in di.retired_in(intent)))
        self.assertEqual(di.retired_in(valid_intent()), [])
        self.assertEqual(di.retired_in(None), [])
        self.assertEqual(di.retired_in({'modules': 'eigrp', 'nodes': [], 'links': 'x'}), [])

    def test_retired_added_compares_with_the_stored_design(self):
        stored = vxlan_intent()
        self.assertEqual(di.retired_added(copy.deepcopy(stored), stored), [])          # keeping is allowed
        removed = copy.deepcopy(stored); removed['modules'] = ['vlan', 'bgp']
        self.assertEqual(di.retired_added(removed, stored), [])                         # removing is allowed
        grown = copy.deepcopy(stored); grown['nodes']['ceos'] = {'vxlan': {}}
        self.assertEqual([(e['path'], e['module']) for e in di.retired_added(grown, stored)], [('nodes.ceos.vxlan', 'vxlan')])
        fresh = valid_intent(); fresh['modules'].append('ripv2')
        self.assertEqual([e['module'] for e in di.retired_added(fresh, None)], ['ripv2'])

    def test_validate_itself_still_accepts_an_old_design(self):
        """validate() is unchanged, so the view of an old design shows no invented problems."""
        self.assertEqual(di.validate(vxlan_intent(), schema=dc.engine_data()), [])

    def test_retired_in_generation_reads_modules_and_per_device_features(self):
        self.assertEqual(di.retired_in_generation({'modules': ['ospf', 'vxlan']}), ['vxlan'])
        self.assertEqual(di.retired_in_generation({'modules': ['ospf'], 'compatibility': {'ceos': [{'feature': 'ripng'}], 'x': [{'feature': 'evpn'}]}}),
                         ['ripv2', 'evpn'])
        self.assertEqual(di.retired_in_generation({'modules': ['ospf'], 'compatibility': {'ceos': [{'feature': 'ospfv2'}]}}), [])

    def test_wording_agrees_with_status_and_number(self):
        self.assertEqual(di.retired_sentence(['eigrp', 'ripv2', 'vxlan']), 'EIGRP, RIP and VXLAN')
        self.assertEqual(di.retired_phrase(['eigrp']), 'is no longer offered')
        self.assertEqual(di.retired_phrase(['evpn']), 'is not available')
        self.assertEqual(di.retired_phrase(['vxlan', 'evpn']), 'are no longer offered or not available')


class CapabilityWordingTests(unittest.TestCase):
    def test_the_public_matrix_words_retired_capabilities_as_retired(self):
        rows = {(r['kind'], r['feature']): r for r in dc.public_matrix(['arista_ceos', 'cisco_xrv9k'])}
        eigrp = rows[('arista_ceos', 'eigrp')]
        self.assertEqual(eigrp['level'], 'retired')
        self.assertEqual(eigrp['engine_level'], 'unsupported')
        self.assertEqual(eigrp['reason'], di.RETIRED['eigrp'])
        vxlan = rows[('arista_ceos', 'vxlan')]
        self.assertEqual((vxlan['level'], vxlan['engine_level'], vxlan['policy']), ('retired', 'generated_not_live_tested', 'retired'))
        self.assertEqual(rows[('arista_ceos', 'ripng')]['reason'], di.RETIRED['ripv2'])
        self.assertEqual(rows[('cisco_xrv9k', 'evpn')]['policy'], 'under_review')
        self.assertEqual(rows[('arista_ceos', 'ospfv2')]['level'], 'generated_not_live_tested')
        self.assertNotIn('policy', rows[('arista_ceos', 'ospfv2')])

    def test_resolve_stays_the_engine_truth(self):
        self.assertEqual(dc.resolve('eigrp', 'arista_ceos')['level'], 'unsupported')
        self.assertEqual(dc.resolve('vxlan', 'arista_ceos')['level'], 'generated_not_live_tested')

    def test_the_catalogue_carries_the_retirement(self):
        catalogue = {e['id']: e for e in dc.public_catalogue()}
        self.assertEqual(catalogue['evpn']['retired'], di.RETIRED['evpn'])
        self.assertEqual(catalogue['evpn']['policy'], 'under_review')
        self.assertEqual(catalogue['ospfv2']['retired'], '')


class AuthoringRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.addCleanup(self.app.state.network_design.close)
        self.lab_id = add_lab(self.app)

    def url(self, tail=''):
        return f'/api/labs/{self.lab_id}/design' + tail

    def test_context_offers_only_authoring_modules_and_explains_the_retired_ones(self):
        view = self.client.get(self.url()).json()
        self.assertEqual(view['modules'], list(di.AUTHORING_MODULES))
        self.assertEqual(view['retired'], di.RETIRED)
        self.assertEqual(view['retired_status']['evpn'], 'under_review')
        self.assertEqual(view['retired_labels']['ripv2'], 'RIP')
        self.assertEqual(view['retired_in_design'], [])
        levels = {(r['kind'], r['feature']): r['level'] for r in view['capabilities']}
        self.assertEqual(levels[('arista_ceos', 'eigrp')], 'retired')

    def test_save_refuses_a_newly_added_retired_module_with_structured_detail(self):
        intent = valid_intent(); intent['modules'].append('ripv2')
        response = self.client.put(self.url(), json={'intent': intent, 'revision': ''})
        self.assertEqual(response.status_code, 400, response.text)
        detail = response.json()['detail']
        self.assertIn('RIP', detail['message'])
        self.assertIn('no longer offered', detail['message'])
        self.assertEqual(detail['problems'], [{'path': 'modules', 'message': di.RETIRED['ripv2']}])
        self.assertEqual(detail['retired'], ['ripv2'])
        self.assertIsNone(self.client.get(self.url()).json()['intent'])

    def test_an_old_design_keeps_working_edits_keep_or_remove_but_never_add(self):
        revision = plant_design(self.app, self.lab_id, vxlan_intent())
        view = self.client.get(self.url()).json()
        self.assertEqual(view['problems'], [])
        self.assertEqual({e['module'] for e in view['retired_in_design']}, {'vxlan', 'evpn'})
        self.assertIn('vxlan', self.client.get(self.url('/export')).text)

        kept = view['intent']; kept['label'] = 'renamed'
        saved = self.client.put(self.url(), json={'intent': kept, 'revision': revision})
        self.assertEqual(saved.status_code, 200, saved.text)
        revision = saved.json()['intent']['revision']

        grown = copy.deepcopy(saved.json()['intent']); grown['nodes']['ceos'] = {'modules': ['bgp', 'vxlan']}
        refused = self.client.put(self.url(), json={'intent': grown, 'revision': revision})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual([p['path'] for p in refused.json()['detail']['problems']], ['nodes.ceos.modules'])

        trimmed = copy.deepcopy(saved.json()['intent']); trimmed['modules'] = ['vlan', 'bgp']
        removed = self.client.put(self.url(), json={'intent': trimmed, 'revision': revision})
        self.assertEqual(removed.status_code, 200, removed.text)
        self.assertEqual(removed.json()['retired_in_design'], [])

    def test_validate_reports_retired_uses_apart_from_problems(self):
        plant_design(self.app, self.lab_id, vxlan_intent())
        candidate = vxlan_intent(); candidate['modules'].append('eigrp')
        body = self.client.post(self.url('/validate'), json={'intent': candidate}).json()
        self.assertTrue(body['valid'])
        self.assertEqual(body['problems'], [])
        flags = {(e['path'], e['module']): e['new'] for e in body['retired']}
        self.assertEqual(flags[('modules', 'eigrp')], True)
        self.assertEqual(flags[('modules', 'vxlan')], False)

    def test_import_refuses_a_new_retired_module_and_accepts_an_old_design_kept(self):
        import yaml
        upload = yaml.safe_dump(vxlan_intent())
        response = self.client.post(self.url('/import'), files={'intent': ('d.yml', upload, 'application/yaml')}, data={'revision': ''})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(set(response.json()['detail']['retired']), {'vxlan', 'evpn'})
        self.assertIsNone(self.client.get(self.url()).json()['intent'])

        revision = plant_design(self.app, self.lab_id, vxlan_intent())
        again = self.client.post(self.url('/import'), files={'intent': ('d.yml', upload, 'application/yaml')}, data={'revision': revision})
        self.assertEqual(again.status_code, 200, again.text)
        self.assertTrue(again.json()['imported'])

    def test_generate_refuses_a_design_with_a_retired_module_and_queues_nothing(self):
        revision = plant_design(self.app, self.lab_id, vxlan_intent())
        response = self.client.post(self.url('/generate'), json={'revision': revision})
        self.assertEqual(response.status_code, 409, response.text)
        detail = response.json()['detail']
        for words in ('VXLAN', 'EVPN', 'Earlier plans', 'export'):
            self.assertIn(words, detail['message'])
        self.assertEqual(detail['retired'], ['vxlan', 'evpn'])
        self.assertIn('modules', [p['path'] for p in detail['problems']])
        self.assertEqual(self.client.get(self.url()).json()['generations'], [])

    def test_generate_reports_validation_problems_as_structured_detail(self):
        broken = valid_intent(); broken['links'] = {'no-such:eth1--link:eth2': {}}
        revision = plant_design(self.app, self.lab_id, broken)
        response = self.client.post(self.url('/generate'), json={'revision': revision})
        self.assertEqual(response.status_code, 400, response.text)
        detail = response.json()['detail']
        self.assertTrue(detail['message'].startswith('Fix the design first: '))
        self.assertIn('links.no-such:eth1--link:eth2', [p['path'] for p in detail['problems']])


class ApplyRefusesRetiredPlansTests(DesignApplyTestCase):
    def test_review_refuses_an_old_plan_with_vxlan(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]}, extra={'modules': ['vlan', 'vxlan']})
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn('VXLAN', response.json()['detail'])
        self.assertIn('cannot be applied', response.json()['detail'])
        self.assertEqual(self.client.get(f'/api/labs/{self.lab_id}/design/review-jobs').json(), [])

    def test_review_refuses_a_plan_whose_device_compatibility_carries_evpn(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]},
                                extra={'modules': ['bgp'], 'compatibility': {'ceos': [{'feature': 'evpn', 'level': 'generated_not_live_tested'}]}})
        response = self.review(gen_id)
        self.assertEqual(response.status_code, 409)
        self.assertIn('EVPN', response.json()['detail'])
        self.assertIn('not available', response.json()['detail'])

    def test_submit_refuses_a_plan_that_carries_a_retired_module(self):
        gen_id = self.default_generation()
        token = self.review(gen_id).json()['token']
        with self.app.state.store.lock:
            generation = next(g for g in self.app.state.store.lab(self.lab_id)['network_generations'] if g['id'] == gen_id)
            generation['modules'] = ['ospf', 'eigrp']
            self.app.state.store.save()
        response = self.submit_http(token)
        self.assertEqual(response.status_code, 409)
        self.assertIn('EIGRP', response.json()['detail'])
        self.assertEqual(self.client.get(f'/api/labs/{self.lab_id}/design/apply/jobs').json(), [])

    def test_a_plan_without_retired_modules_still_reviews(self):
        gen_id = add_generation(self.app, self.lab_id, node_map('ceos'), {'ceos': [('initial', FRAGMENT)]}, extra={'modules': ['ospf']})
        self.assertEqual(self.review(gen_id).status_code, 200)


if __name__ == '__main__':
    unittest.main()
