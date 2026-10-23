"""Manager side of C05: link impairments and the pending-changes plan (app/impairments.py, docs/parity-campaign/C05-DESIGN.md 3.3, 3.4).

The helper is patched at `app.lab_operations.remote`; a temporary Store is used, never live data.
"""
import json
from pathlib import Path
import re
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.host_operations as host_operations
import app.impairments as imp
import app.lab_operations as lab_operations
from app.impairments import duration_text, public_impairment, public_plan, public_rows
import test_discovery as discovery_tests

ID = 'a' * 64
OTHER = 'b' * 64
TABLE = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'impairment_values.json').read_text())
ROW = {'interface': 'eth1', 'delay': '20ms', 'jitter': '5ms', 'loss': 1.5, 'rate': 1000, 'corruption': 0.5}
BUSY_SENTENCE = 'Wait for the current lab operation to finish.'


class PureTests(unittest.TestCase):
    def test_go_durations_become_whole_milliseconds(self):
        for raw, shown in (('20ms', '20ms'), ('60s', '60000ms'), ('1.5s', '1500ms'), ('1m0s', '60000ms'), ('0s', '0ms'), ('1h2m3.5s', '3723500ms'),
                           ('500µs', '1ms'), ('', ''), (None, ''), ('soon', ''), ('5', ''), ('5ms6', ''), (7, '')):
            self.assertEqual(duration_text(raw), shown, raw)

    def test_a_public_row_is_normalised_and_carries_the_port_name(self):
        row = public_impairment({'interface': 'eth3', 'delay': '1m0s', 'jitter': '1.5s', 'loss': 33.333, 'rate': 1000.0, 'corruption': -0.0}, 'arista_ceos')
        self.assertEqual(row, {'interface': 'eth3', 'port': 'Ethernet3', 'delay': '60000ms', 'jitter': '1500ms', 'loss': 33.33, 'rate': 1000, 'corruption': 0})
        self.assertIs(type(row['rate']), int)
        bare = public_impairment({'interface': 'eth1'}, 'linux')
        self.assertEqual(bare, {'interface': 'eth1', 'port': 'eth1', 'delay': '', 'jitter': '', 'loss': 0, 'rate': 0, 'corruption': 0})
        self.assertEqual(public_impairment({'interface': 'eth1', 'loss': True, 'rate': 'x'}, 'linux')['loss'], 0)

    def test_a_helper_alias_names_the_port_so_a_vjunos_row_reads_back(self):
        rows = public_rows([{'interface': 'eth1', 'alias': 'ge-0/0/0', 'delay': '20ms'}, {'interface': 'eth2', 'delay': '1ms'}], 'juniper_vjunosswitch')
        self.assertEqual([(r['interface'], r['port']) for r in rows], [('eth1', 'ge-0/0/0'), ('eth2', 'ge-0/0/1')])

    def test_rows_on_management_and_internal_interfaces_are_dropped(self):
        rows = [{'interface': n, 'delay': '1ms'} for n in ('eth0', 'cpu', 'fabric', 'eth1', 'eth2')]
        self.assertEqual([r['interface'] for r in public_rows(rows, 'arista_ceos')], ['eth1', 'eth2'])
        self.assertEqual([r['interface'] for r in public_rows(rows + [7, {'interface': ''}, {}], 'juniper_cjunosevolved')], [])
        self.assertEqual(public_rows('x', 'linux'), [])

    def test_the_public_plan_is_field_by_field_and_sorted(self):
        plan = public_plan({'deploys_lab': False, 'added': ['r3', 'r1', 3], 'removed': None, 'recreated': ['r2'], 'started': [], 'restarted': ['x'] * 3,
                            'links_added': ['a -- b'], 'endpoints_removed': [], 'reasons': {'r2': 'config drift: Env', 'r1': 'added link', 'r9': 5}, 'secret': 'x'})
        self.assertEqual(set(plan), {'deploys_lab', 'added', 'removed', 'recreated', 'started', 'restarted', 'links_added', 'endpoints_removed', 'reasons'})
        self.assertEqual((plan['added'], plan['removed'], list(plan['reasons'])), (['r1', 'r3'], [], ['r1', 'r2']))
        self.assertEqual(public_plan(None)['added'], [])


class ImpairmentBase(unittest.TestCase):
    setUp = discovery_tests.DiscoveryTests.setUp
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host

    def tearDown(self):
        self.app.state.operations.close(); discovery_tests.DiscoveryTests.tearDown(self)

    def start(self):
        """A linked lab 'training' (r1 xrv9k, r2 cjunosevolved), both running, and a patched helper that records its requests."""
        self.host(); lab = self.register(); self.lab_id = lab['id']
        self.store.state['host']['fingerprint'] = 'SHA256:fixture'
        with self.store.lock:
            stored = self.store.lab(self.lab_id)
            stored['vm_project_path'] = '/etc/containerlab/training/training.clab.yaml'
            for node in stored['nodes']: node.update(discovered=True, runtime_state='running')
            self.node, self.node2 = stored['nodes'][0]['name'], stored['nodes'][1]['name']
        self.requests = []; self.answers = {}; self.hold = None

        def remote(host, req, output=None, stopping=None, timeout=None):
            self.requests.append((req, timeout))
            if self.hold: self.hold(req)
            answer = self.answers.get(req['mode'])
            if isinstance(answer, Exception): raise answer
            return answer(req) if callable(answer) else answer
        patcher = patch('app.lab_operations.remote', side_effect=remote); patcher.start(); self.addCleanup(patcher.stop)

    def modes(self): return [r['mode'] for r, _ in self.requests]

    def get(self, path, **params): return self.client.get('/api/operations/' + path, headers=self.auth, params=params)

    def post(self, path, body, **kwargs): return self.client.post('/api/operations/impairments/' + path, headers=self.auth, json=body, **kwargs)

    def events(self):
        path = Path(self.tmp.name) / 'events.jsonl'
        return path.read_bytes() if path.exists() else b''

    def set_body(self, **changes):
        body = {'lab_id': self.lab_id, 'node': self.node, 'interface': 'eth1', 'expected_id': ID, **{k: v for k, v in ROW.items() if k != 'interface'}}
        body.update(changes); return body

    def reset_body(self, **changes):
        body = {'lab_id': self.lab_id, 'node': self.node, 'interface': 'eth1', 'expected_id': ID}
        body.update(changes); return body


class ReadTests(ImpairmentBase):
    def test_the_read_asks_one_call_for_every_device_and_answers_normalised_data_rows_only(self):
        self.start()
        self.answers['netem-show-all'] = {'complete': True, 'devices': [
            {'node': 'r1', 'container': 'clab-training-r1', 'present': True, 'id': ID, 'impairments': [ROW, {'interface': 'eth0', 'delay': '9ms'}, {'interface': 'eth2', 'delay': '1m0s'}]},
            {'node': 'r2', 'container': 'clab-training-r2', 'present': True, 'impairments': [{'interface': 'eth2', 'delay': '1ms'}, {'interface': 'eth4', 'loss': 10}]}]}
        before = self.events()
        response = self.get('impairments', lab_id=self.lab_id)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.requests, [({'mode': 'netem-show-all', 'name': 'training', 'options': {'nodes': [
            {'node': 'r1', 'container': 'clab-training-r1'}, {'node': 'r2', 'container': 'clab-training-r2'}]}}, imp.READ_TIMEOUT)])
        body = response.json()
        self.assertEqual(set(body), {'devices', 'interfaces', 'complete', 'fetched_at'}); self.assertTrue(body['complete']); self.assertEqual(body['interfaces'], 3)
        first = body['devices'][self.node]
        self.assertEqual((first['present'], first['id']), (True, ID)); self.assertEqual([r['interface'] for r in first['impairments']], ['eth1', 'eth2'])
        self.assertEqual(first['impairments'][1]['delay'], '60000ms')
        self.assertEqual(set(first['impairments'][0]), {'interface', 'port', 'delay', 'jitter', 'loss', 'rate', 'corruption'})
        second = body['devices'][self.node2]
        self.assertEqual(second['id'], '', 'no 64-hex id known: the discovery id is the 12-character one or none'); self.assertEqual([r['interface'] for r in second['impairments']], ['eth4'])
        self.assertEqual(self.events(), before, 'a GET writes no event and the events hold no interface list')
        self.assertEqual(self.get('impairments', lab_id=self.lab_id, node=self.node).status_code, 200)
        self.assertEqual(self.requests[-1][0]['options']['nodes'], [{'node': 'r1', 'container': 'clab-training-r1'}])

    def test_a_full_discovery_id_is_the_fallback_expected_id(self):
        self.start()
        with self.store.lock: self.store.lab(self.lab_id)['nodes'][0]['discovered_id'] = OTHER
        self.answers['netem-show-all'] = {'complete': True, 'devices': [{'node': 'r1', 'container': 'clab-training-r1', 'present': True, 'impairments': []},
                                                                       {'node': 'r2', 'container': 'clab-training-r2', 'present': True, 'id': 'xyz', 'impairments': []}]}
        devices = self.get('impairments', lab_id=self.lab_id).json()['devices']
        self.assertEqual((devices[self.node]['id'], devices[self.node2]['id']), (OTHER, ''))

    def test_no_call_without_a_device_with_a_container_and_unknown_names_are_404(self):
        self.start()
        with self.store.lock:
            for node in self.store.lab(self.lab_id)['nodes']: node.update(definition_node='', short_name='')
        body = self.get('impairments', lab_id=self.lab_id).json()
        self.assertEqual((self.requests, body['devices'], body['interfaces'], body['complete']), ([], {}, 0, True))
        self.assertEqual(self.get('impairments', lab_id='nope').status_code, 404)
        self.assertEqual(self.get('impairments', lab_id=self.lab_id, node='nope').status_code, 404)

    def test_above_64_devices_the_read_is_split_and_an_unread_pair_marks_it_incomplete(self):
        self.start()
        with self.store.lock:
            nodes = self.store.lab(self.lab_id)['nodes']
            for i in range(70): nodes.append({'name': 'clab-training-n%d' % i, 'short_name': 'n%d' % i, 'definition_node': 'n%d' % i, 'kind': 'arista_ceos'})
        def answer(req):
            devices = [{'node': p['node'], 'container': p['container'], 'present': True, 'impairments': [dict(ROW)]} for p in req['options']['nodes']]
            if len(self.requests) == 2: devices[0] = {'node': devices[0]['node'], 'container': devices[0]['container'], 'unread': True}
            return {'devices': devices, 'complete': len(self.requests) == 1}
        self.answers['netem-show-all'] = answer
        body = self.get('impairments', lab_id=self.lab_id).json()
        self.assertEqual([len(r['options']['nodes']) for r, _ in self.requests], [64, 8]); self.assertFalse(body['complete'])
        self.assertEqual((len(body['devices']), body['interfaces']), (71, 70), 'r2 eth1 is an internal interface of the cJunosEvolved: its row is dropped')

    def test_the_read_is_unguarded_and_answered_while_a_job_holds_the_lab_but_a_fourth_call_is_503(self):
        self.start()
        self.answers['netem-show-all'] = {'complete': True, 'devices': []}
        self.app.state.operations.active.add('job')
        self.store.state['operations'].append({'id': 'j', 'lab_id': self.lab_id, 'status': 'running', 'action': 'deploy'})
        self.assertEqual(self.get('impairments', lab_id=self.lab_id).status_code, 200)
        slots = self.app.state.device_diagnostics.slots
        for _ in range(3): self.assertTrue(slots.acquire(blocking=False))
        try: self.assertEqual(self.get('impairments', lab_id=self.lab_id).status_code, 503)
        finally:
            for _ in range(3): slots.release()

    def test_helper_errors_reach_the_page_as_their_sentence(self):
        self.start(); self.answers['netem-show-all'] = ValueError('Unknown request mode.')
        response = self.get('impairments', lab_id=self.lab_id)
        self.assertEqual((response.status_code, response.json()['detail']), (409, imp.__dict__.get('OLD', "This VM's manager tools need an update; ask your instructor or administrator.")))


class SetTests(ImpairmentBase):
    def ok_answer(self, rows=None):
        self.answers['netem-set'] = {'facts': {'present': True, 'id': ID}, 'impairments': rows if rows is not None else [{**ROW, 'delay': '20ms'}]}

    def test_set_sends_the_exact_request_with_a_digest_the_helper_reproduces_and_answers_public_rows(self):
        self.start(); self.ok_answer([{**ROW, 'delay': '1m0s', 'jitter': '1.5s'}, {'interface': 'eth0', 'delay': '3ms'}])
        before = self.events()
        response = self.post('set', self.set_body(delay='60s', jitter='1500ms'))
        self.assertEqual(response.status_code, 200, response.text)
        request, timeout = self.requests[0]
        self.assertEqual(set(request), {'mode', 'name', 'options', 'expected_id', 'digest'})
        self.assertEqual((request['mode'], request['name'], request['expected_id']), ('netem-set', 'training', ID))
        self.assertEqual(request['options'], {'node': 'r1', 'container': 'clab-training-r1', 'interface': 'eth1', 'delay': '60s', 'jitter': '1500ms', 'loss': 1.5, 'rate': 1000, 'corruption': 0.5})
        self.assertEqual(request['digest'], host_operations.digest({k: request[k] for k in ('mode', 'name', 'options', 'expected_id')}))
        self.assertEqual(timeout, imp.MUTATING_TIMEOUT)
        body = response.json(); self.assertEqual(set(body), {'container', 'impairments'}); self.assertEqual(body['container'], 'clab-training-r1')
        self.assertEqual([(r['interface'], r['delay'], r['jitter']) for r in body['impairments']], [('eth1', '60000ms', '1500ms')])
        added = self.events()[len(before):].decode()
        self.assertIn('Impairment set on r1 eth1: delay 60000ms, jitter 1500ms, loss 1.5%, rate 1000 kbit, corruption 0.5%', added)
        self.assertNotIn(ID, added); self.assertNotIn('clab-training-r1', added.replace('"node":"r1"', ''))
        self.assertEqual(self.app.state.operations.in_flight_impairments, set())

    def test_a_negative_zero_travels_as_zero(self):
        self.start(); self.ok_answer()
        self.assertEqual(self.post('set', self.set_body(loss=-0.0)).status_code, 200)
        sent = self.requests[0][0]['options']['loss']
        self.assertEqual(json.dumps(sent), '0')

    def test_every_case_of_the_shared_value_table_is_a_400_with_the_helpers_sentence_and_asks_nothing(self):
        self.start(); self.ok_answer()
        for case in TABLE['refused']:
            values = {**TABLE['base'], **case['values']}
            response = self.post('set', self.set_body(**values))
            self.assertEqual(response.status_code, 400, (case['name'], response.text))
            self.assertEqual(response.json()['detail'], TABLE['sentences'][case['problem']], case['name'])
        self.assertEqual(self.requests, [])
        for case in TABLE['accepted']:
            self.assertEqual(self.post('set', self.set_body(**case['values'])).status_code, 200, case['name'])

    def test_expected_id_is_required_and_64_hex(self):
        self.start(); self.ok_answer()
        for bad in (None, '', 'a' * 63, 'A' * 64, 'g' * 64, 7, 'a' * 65):
            body = self.set_body(); body['expected_id'] = bad
            response = self.post('set', body); self.assertEqual((response.status_code, response.json()['detail']), (400, imp.REOPEN_SENTENCE), repr(bad))
            body = self.reset_body(); body['expected_id'] = bad
            self.assertEqual(self.post('reset', body).status_code, 400)
        body = self.set_body(); del body['expected_id']; self.assertEqual(self.post('set', body).status_code, 400)
        self.assertEqual(self.requests, [])

    def test_unknown_stopped_management_internal_and_unknown_fields_are_refused_before_the_helper(self):
        self.start(); self.ok_answer()
        self.assertEqual(self.post('set', self.set_body(node='nope')).status_code, 404)
        self.assertEqual(self.post('set', self.set_body(lab_id='nope')).status_code, 404)
        for interface, text in (('eth0', 'eth0 is the management interface; the manager reaches the device through it and never impairs it.'),
                                ('cpu', 'cpu is an internal interface of this device, not a lab link.'), ('lo', 'lo is an internal interface of this device, not a lab link.')):
            response = self.post('set', self.set_body(interface=interface)); self.assertEqual((response.status_code, response.json()['detail']), (409, text), interface)
        response = self.post('set', self.set_body(node=self.node2, interface='eth2'))
        self.assertEqual((response.status_code, response.json()['detail']), (409, 'eth2 is an internal interface of this device, not a lab link.'))
        with self.store.lock: self.store.lab(self.lab_id)['nodes'][0]['runtime_state'] = 'exited'
        for path, body in (('set', self.set_body()), ('reset', self.reset_body())):
            response = self.post(path, body); self.assertEqual((response.status_code, response.json()['detail']), (409, 'r1 is not running. Impairments can be set only on a running device.'))
        self.assertEqual(self.post('set', {**self.set_body(), 'container': 'x'}).status_code, 422)
        self.assertEqual(self.requests, [])
        with self.store.lock: self.store.lab(self.lab_id)['nodes'][0]['runtime_state'] = 'running'; self.store.lab(self.lab_id)['nodes'][1]['runtime_state'] = 'running'
        self.assertEqual(self.post('set', self.set_body(node=self.node2, interface='eth4')).status_code, 200)

    def test_a_cross_origin_post_is_403_and_nothing_reaches_the_helper(self):
        self.start(); self.ok_answer()
        for path, body in (('set', self.set_body()), ('reset', self.reset_body()), ('clear', {'lab_id': self.lab_id})):
            response = self.client.post('/api/operations/impairments/' + path, headers={**self.auth, 'Origin': 'https://other.example'}, json=body)
            self.assertEqual(response.status_code, 403, path)
        self.assertEqual(self.requests, [])

    def test_the_helpers_lock_sentence_and_other_errors_map_to_their_wording(self):
        self.start()
        self.answers['netem-set'] = ValueError(host_operations.LOCK_SENTENCE)
        response = self.post('set', self.set_body())
        self.assertEqual((response.status_code, response.json()['detail']), (409, 'Another lab operation is running on the VM (it may belong to another lab); try again when it has finished.'))
        self.answers['netem-set'] = ValueError("The device's container changed since you opened this section; reopen it and apply again.")
        response = self.post('set', self.set_body()); self.assertEqual((response.status_code, response.json()['detail']), (409, "The device's container changed since you opened this section; reopen it and apply again."))
        self.assertEqual(self.app.state.operations.in_flight_impairments, set()); self.assertFalse(self.app.state.impairments.lab_lock(self.lab_id).locked())

    def test_reset_sends_three_options_reports_changed_and_logs_only_a_change(self):
        self.start()
        self.answers['netem-reset'] = {'facts': {}, 'changed': True, 'impairments': [{**ROW, 'interface': 'eth2'}]}
        before = self.events()
        response = self.post('reset', self.reset_body()); self.assertEqual(response.status_code, 200, response.text)
        request = self.requests[0][0]
        self.assertEqual((request['mode'], request['options'], request['expected_id']), ('netem-reset', {'node': 'r1', 'container': 'clab-training-r1', 'interface': 'eth1'}, ID))
        self.assertEqual(request['digest'], host_operations.digest({k: request[k] for k in ('mode', 'name', 'options', 'expected_id')}))
        body = response.json(); self.assertEqual((set(body), body['changed']), ({'container', 'changed', 'impairments'}, True)); self.assertEqual(body['impairments'][0]['interface'], 'eth2')
        self.assertIn('Impairment reset on r1 eth1', self.events()[len(before):].decode())
        before = self.events(); self.answers['netem-reset'] = {'facts': {}, 'changed': False, 'impairments': []}
        self.assertFalse(self.post('reset', self.reset_body()).json()['changed']); self.assertEqual(self.events()[len(before):].count(b'lab.impairment'), 0)


class BusyTests(ImpairmentBase):
    def test_a_running_job_a_restore_and_a_git_save_refuse_a_change_with_the_guard_sentences(self):
        self.start(); self.answers['netem-set'] = {'impairments': []}
        self.store.state['operations'].append({'id': 'j', 'lab_id': self.lab_id, 'status': 'running', 'action': 'deploy'})
        for path, body in (('set', self.set_body()), ('reset', self.reset_body()), ('clear', {'lab_id': self.lab_id})):
            response = self.post(path, body); self.assertEqual((response.status_code, response.json()['detail']), (409, BUSY_SENTENCE), path)
        self.store.state['operations'].clear()
        self.store.state.setdefault('restore_jobs', []).append({'id': 'r', 'lab_id': self.lab_id, 'status': 'applying'})
        self.assertEqual(self.post('set', self.set_body()).json()['detail'], BUSY_SENTENCE)
        self.store.state['restore_jobs'].clear()
        self.store.state.setdefault('git_jobs', []).append({'id': 'g', 'lab_id': self.lab_id, 'status': 'pushing'})
        self.assertEqual(self.post('set', self.set_body()).json()['detail'], BUSY_SENTENCE)
        self.store.state['git_jobs'].clear()
        self.store.state['jobs'].append({'id': 'b', 'lab_id': self.lab_id, 'status': 'running'})
        self.assertEqual(self.post('set', self.set_body()).json()['detail'], 'Wait for the lab backup or login job to finish.')
        self.assertEqual(self.requests, [])

    def test_a_preview_and_a_confirm_during_a_slow_change_answer_409_and_never_reach_the_helper(self):
        self.start()
        entered = threading.Event(); release = threading.Event()
        self.answers['netem-set'] = {'facts': {}, 'impairments': [ROW]}
        def slow(req):
            if req['mode'] == 'netem-set': entered.set(); self.assertTrue(release.wait(10))
        self.hold = slow
        worker = threading.Thread(target=lambda: self.results.append(self.post('set', self.set_body())), daemon=True); self.results = []
        worker.start(); self.assertTrue(entered.wait(5))
        try:
            calls = len(self.requests)
            preview = self.client.post('/api/operations/preview', headers=self.auth, json={'action': 'inspect-all'})
            self.assertEqual((preview.status_code, preview.json()['detail']), (409, BUSY_SENTENCE))
            token = 'a' * 32
            self.app.state.operations.previews[token] = {'request': {}, 'digest': 'x', 'revision': self.store.state.get('host', {}).get('revision'), 'lab_id': '', 'expires': time.monotonic() + 60}
            confirm = self.client.post('/api/operations/confirm', headers=self.auth, json={'token': token})
            self.assertEqual((confirm.status_code, confirm.json()['detail']), (409, BUSY_SENTENCE)); self.assertEqual(len(self.requests), calls, 'the helper was not asked')
            self.assertEqual(self.post('set', self.set_body()).json()['detail'], imp.CHANGE_IN_PROGRESS, 'a second change on the lab hears the lab sentence')
            other = self.client.post('/api/operations/impairments/set', headers=self.auth, json=self.set_body(lab_id='other'))
            self.assertEqual(other.status_code, 409)
        finally: release.set(); worker.join(10)
        self.assertEqual(self.results[0].status_code, 200); self.assertEqual(self.store.state['operations'], [])
        self.assertEqual(self.post('set', self.set_body()).status_code, 200, 'the lab is free again')


class ClearTests(ImpairmentBase):
    def many(self, count=70):
        with self.store.lock:
            nodes = self.store.lab(self.lab_id)['nodes']
            for i in range(count): nodes.append({'name': 'clab-training-n%d' % i, 'short_name': 'n%d' % i, 'definition_node': 'n%d' % i, 'kind': 'arista_ceos', 'runtime_state': 'running'})

    def show_all(self, impaired, ids=True):
        def answer(req):
            return {'complete': True, 'devices': [{'node': p['node'], 'container': p['container'], 'present': True, **({'id': ID} if ids else {}),
                                                   'impairments': [{**ROW, 'interface': 'eth1'}, {**ROW, 'interface': 'eth2'}] if p['node'] in impaired else []} for p in req['options']['nodes']]}
        self.answers['netem-show-all'] = answer

    def test_clear_resets_every_impaired_data_interface_in_device_order_and_reports_the_counts(self):
        self.start(); self.show_all({'r1'})
        self.answers['netem-reset'] = lambda req: {'changed': True, 'impairments': [{**ROW, 'interface': 'eth2'}] if req['options']['interface'] == 'eth1' else []}
        before = self.events()
        response = self.post('clear', {'lab_id': self.lab_id}); self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body['cleared'], body['total'], body['failed'], body['remaining'], body['complete']), (2, 2, [], [], True))
        self.assertEqual(body['devices'], {self.node: {'impairments': []}})
        resets = [r for r, _ in self.requests if r['mode'] == 'netem-reset']
        self.assertEqual([(r['options']['interface'], r['expected_id']) for r in resets], [('eth1', ID), ('eth2', ID)])
        for r in resets: self.assertEqual(r['digest'], host_operations.digest({k: r[k] for k in ('mode', 'name', 'options', 'expected_id')}))
        self.assertIn('Impairments cleared on training: 2 of 2 interfaces', self.events()[len(before):].decode())
        response = self.post('clear', {'lab_id': self.lab_id, 'node': self.node}); self.assertEqual(response.status_code, 200)
        self.assertEqual(self.requests[-3][0]['options']['nodes'], [{'node': 'r1', 'container': 'clab-training-r1'}])
        self.assertEqual(self.post('clear', {'lab_id': self.lab_id, 'node': 'nope'}).status_code, 404)

    def test_clear_takes_the_container_id_from_a_single_read_when_the_lab_wide_read_has_none(self):
        self.start(); self.show_all({'r1'}, ids=False)
        self.answers['netem-show'] = {'facts': {'present': True, 'id': OTHER}, 'impairments': []}
        self.answers['netem-reset'] = {'changed': True, 'impairments': []}
        self.assertEqual(self.post('clear', {'lab_id': self.lab_id}).json()['cleared'], 2)
        self.assertEqual(self.modes().count('netem-show'), 1)
        self.assertEqual({r['expected_id'] for r, _ in self.requests if r['mode'] == 'netem-reset'}, {OTHER})
        self.answers['netem-show'] = {'facts': {'present': True}, 'impairments': []}
        body = self.post('clear', {'lab_id': self.lab_id}).json()
        self.assertEqual((body['cleared'], len(body['failed']), len(body['remaining'])), (0, 1, 1))

    def test_clear_splits_70_devices_into_two_reads_and_stops_at_the_first_failure(self):
        self.start(); self.many(); self.show_all({'r1', 'n3', 'n60'})
        calls = []
        def reset(req):
            calls.append((req['options']['node'], req['options']['interface']))
            if len(calls) == 3: raise ValueError('Containerlab on the VM could not reset the impairment on eth1.')
            return {'changed': True, 'impairments': []}
        self.answers['netem-reset'] = reset
        body = self.post('clear', {'lab_id': self.lab_id}).json()
        self.assertEqual([len(r['options']['nodes']) for r, _ in self.requests if r['mode'] == 'netem-show-all'], [64, 8])
        self.assertEqual((body['cleared'], body['total']), (2, 6)); self.assertEqual(len(calls), 3, 'it stopped at the first failure')
        self.assertEqual(body['failed'], [{'node': 'clab-training-n3', 'interface': 'eth1', 'reason': 'Containerlab on the VM could not reset the impairment on eth1.'}])
        self.assertEqual(len(body['remaining']), 3); self.assertNotIn({'node': 'clab-training-n3', 'interface': 'eth1'}, body['remaining'])
        self.assertEqual(self.app.state.operations.in_flight_impairments, set())

    def test_clear_stops_when_its_budget_is_spent_and_names_what_remains(self):
        self.start(); self.show_all({'r1'}); self.answers['netem-reset'] = {'changed': True, 'impairments': []}
        clock = iter([0, 0, 500, 500, 500, 500]); real = time.monotonic
        with patch.object(imp, 'time', SimpleNamespace(monotonic=lambda: next(clock), time=time.time)):
            body = self.post('clear', {'lab_id': self.lab_id}).json()
        self.assertEqual((body['cleared'], body['total'], body['failed']), (1, 2, [])); self.assertEqual(body['remaining'], [{'node': self.node, 'interface': 'eth2'}])

    def test_clear_with_nothing_impaired_or_no_devices_asks_nothing_further(self):
        self.start(); self.show_all(set())
        body = self.post('clear', {'lab_id': self.lab_id}).json()
        self.assertEqual((body['cleared'], body['total'], body['devices']), (0, 0, {})); self.assertNotIn('netem-reset', self.modes())

    def test_clear_holds_the_in_flight_token_for_one_helper_call_at_a_time_and_a_refusal_between_resets_is_a_partial_result(self):
        self.start(); self.many(5); self.show_all({'r1', 'n0'})
        operations = self.app.state.operations; held = []; resets = []
        self.answers['netem-reset'] = {'changed': True, 'impairments': []}
        def watch(req):
            held.append((req['mode'], len(operations.in_flight_impairments)))
            if req['mode'] == 'netem-reset':
                resets.append(req)
                if len(resets) == 1: self.store.state['jobs'].append({'id': 'b', 'lab_id': self.lab_id, 'status': 'running'})   # a backup starts between two resets
        self.hold = watch
        body = self.post('clear', {'lab_id': self.lab_id}).json()
        self.assertEqual({count for _, count in held}, {1}, 'a helper call runs under exactly one token: %r' % held)
        self.assertEqual(len(resets), 1, 'the second reset was refused by the guard and never reached the helper')
        self.assertEqual((body['cleared'], body['total']), (1, 4))
        self.assertEqual(body['failed'], [{'node': self.node, 'interface': 'eth2', 'reason': 'Wait for the lab backup or login job to finish.'}])
        self.assertEqual(body['remaining'], [{'node': 'clab-training-n0', 'interface': 'eth1'}, {'node': 'clab-training-n0', 'interface': 'eth2'}])
        self.assertEqual(operations.in_flight_impairments, set())
        # Between two helper calls another lab's work is not shut out: a guard call made then is answered.
        self.store.state['jobs'].clear(); self.hold = None
        with self.store.lock: operations.guard('other')

    def test_clear_reads_with_the_long_timeout_and_resets_with_the_mutating_one(self):
        self.start(); self.show_all({'r1'}); self.answers['netem-reset'] = {'changed': True, 'impairments': []}
        self.answers['netem-show'] = {'facts': {'present': True, 'id': OTHER}, 'impairments': []}
        self.assertEqual(self.post('clear', {'lab_id': self.lab_id}).status_code, 200)
        timeouts = {mode: {t for r, t in self.requests if r['mode'] == mode} for mode in ('netem-show-all', 'netem-reset')}
        self.assertEqual(timeouts, {'netem-show-all': {imp.READ_TIMEOUT}, 'netem-reset': {imp.MUTATING_TIMEOUT}})
        # The order that makes it work: the helper's lab-wide read may take its whole deadline, and a set or reset is shorter.
        self.assertLess(imp.MUTATING_TIMEOUT, host_operations.SHOW_ALL_DEADLINE); self.assertGreater(imp.READ_TIMEOUT, host_operations.SHOW_ALL_DEADLINE)
        self.assertEqual(self.post('clear', {'lab_id': self.lab_id}).status_code, 200)
        lock = lab_operations.LOCK_SENTENCE; self.answers['netem-show-all'] = ValueError(lock)
        self.assertEqual(self.post('clear', {'lab_id': self.lab_id}).json()['detail'], imp.BUSY_ELSEWHERE, 'the lock sentence mapping is kept on the read')

    def test_a_posted_lab_id_the_manager_does_not_know_never_grows_the_lock_table(self):
        self.start(); table = self.app.state.impairments.locks
        before = len(table)
        for i in range(20):
            lab_id = 'random-%d' % i
            self.assertEqual(self.post('clear', {'lab_id': lab_id}).status_code, 404)
            self.assertIn(self.post('set', self.set_body(lab_id=lab_id)).status_code, (404, 409))
            self.assertIn(self.post('reset', self.reset_body(lab_id=lab_id)).status_code, (404, 409))
        self.assertEqual(len(table), before)
        self.show_all(set()); self.assertEqual(self.post('clear', {'lab_id': self.lab_id}).status_code, 200)
        self.assertIn(self.lab_id, table, 'a known lab keeps its lock')


class BusySentenceMirrorTests(ImpairmentBase):
    def test_the_drawers_busy_sentences_are_the_ones_the_manager_says(self):
        source = (Path(__file__).resolve().parents[1] / 'app' / 'static' / 'device-impairments.js').read_text()
        match = re.search(r"const IMP_BUSY\s*=\s*\[([^\]]*)\]", source)
        self.assertIsNotNone(match, 'device-impairments.js carries IMP_BUSY')
        shown = re.findall(r"'([^']*)'", match.group(1))
        self.start(); operations = self.app.state.operations
        said = []
        for setup, teardown in ((lambda: operations.in_flight_impairments.add('t'), lambda: operations.in_flight_impairments.discard('t')),
                                (lambda: self.store.state['jobs'].append({'id': 'b', 'lab_id': self.lab_id, 'status': 'running'}), lambda: self.store.state['jobs'].clear())):
            setup()
            try:
                with self.store.lock:
                    try: operations.guard(self.lab_id)
                    except imp.HTTPException as exc: said.append(exc.detail)
            finally: teardown()
        said.append(imp.BUSY_ELSEWHERE)
        self.assertEqual(len(said), 3); self.assertEqual(shown, said, 'IMP_BUSY mirrors guard()\'s two sentences and BUSY_ELSEWHERE, in that order')


class PlanTests(ImpairmentBase):
    PLAN = {'deploys_lab': False, 'added': ['r3'], 'removed': [], 'recreated': ['r2'], 'started': [], 'restarted': [], 'links_added': ['r1:eth1 -- r3:eth1'], 'endpoints_removed': [], 'reasons': {'r2': 'config drift: Env'}}

    def plan_answer(self, plan=None, failed='', error=''): self.answers['apply-plan'] = {'plan': plan, 'failed': failed, 'error': error}

    def test_the_plan_route_is_answered_here_never_by_the_job_route(self):
        self.start(); self.plan_answer(self.PLAN)
        response = self.get('apply-plan', lab_id=self.lab_id); self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(set(body), {'changed', 'plan', 'failed', 'error', 'checked_at'}); self.assertTrue(body['changed']); self.assertEqual(body['plan']['added'], ['r3'])
        self.assertEqual(self.requests, [({'mode': 'apply-plan', 'name': 'training', 'path': '/etc/containerlab/training/training.clab.yaml'}, imp.READ_TIMEOUT)])
        self.assertEqual(self.get('apply-plan', lab_id='nope').json()['detail'], 'Lab not found')
        self.assertEqual(self.get('apply-plan').status_code, 422)
        self.assertEqual(self.get('impairments', lab_id='nope').json()['detail'], 'Lab not found')
        self.assertEqual(self.get('nosuchjob').json()['detail'], 'Operation not found.', 'the job route still answers its own ids')

    def test_an_empty_plan_is_not_a_change_and_failures_carry_a_clean_sentence(self):
        self.start(); self.plan_answer({'deploys_lab': False, 'added': [], 'removed': [], 'recreated': [], 'started': [], 'restarted': [], 'links_added': [], 'endpoints_removed': [], 'reasons': {}})
        self.assertFalse(self.get('apply-plan', lab_id=self.lab_id, refresh='1').json()['changed'])
        self.plan_answer({'deploys_lab': True, 'added': [], 'removed': [], 'recreated': [], 'started': [], 'restarted': [], 'links_added': [], 'endpoints_removed': [], 'reasons': {}})
        self.assertTrue(self.get('apply-plan', lab_id=self.lab_id, refresh='1').json()['changed'])
        self.plan_answer(None, 'error', '\x1b[31mFailed to read topology file: yaml: line 3\x1b[0m' + 'x' * 600)
        body = self.get('apply-plan', lab_id=self.lab_id, refresh='1').json()
        self.assertEqual((body['plan'], body['failed'], body['changed']), (None, 'error', False)); self.assertTrue(body['error'].startswith('Failed to read topology file')); self.assertEqual(len(body['error']), 300)
        self.assertNotIn('\x1b', body['error'])
        self.plan_answer(None, 'unsupported', '')
        body = self.get('apply-plan', lab_id=self.lab_id, refresh='1').json(); self.assertEqual((body['failed'], body['error'], body['plan']), ('unsupported', '', None))

    def test_the_answer_is_cached_for_sixty_seconds_and_refresh_bypasses_it(self):
        self.start(); self.plan_answer(self.PLAN)
        first = self.get('apply-plan', lab_id=self.lab_id).json(); second = self.get('apply-plan', lab_id=self.lab_id).json()
        self.assertEqual((len(self.requests), second['checked_at']), (1, first['checked_at']))
        self.get('apply-plan', lab_id=self.lab_id, refresh='1'); self.assertEqual(len(self.requests), 2)
        clock = time.monotonic() + 61
        with patch.object(imp, 'time', SimpleNamespace(monotonic=lambda: clock, time=time.time)): self.get('apply-plan', lab_id=self.lab_id)
        self.assertEqual(len(self.requests), 3, 'an entry older than the TTL is asked again')

    def test_the_unlinked_lab_and_the_lab_without_a_folder_get_their_sentences(self):
        self.start(); self.plan_answer(self.PLAN)
        with self.store.lock: self.store.lab(self.lab_id)['vm_project_path'] = ''; self.store.lab(self.lab_id)['vm_source'] = {}
        self.assertEqual(self.get('apply-plan', lab_id=self.lab_id).json()['detail'], imp.NO_FOLDER_SENTENCE)
        with self.store.lock: self.store.lab(self.lab_id)['deployment_name'] = ''
        self.assertEqual(self.get('apply-plan', lab_id=self.lab_id).json()['detail'], imp.UNLINKED_SENTENCE)
        self.assertEqual(self.requests, [])

    def test_the_fourth_concurrent_call_is_503(self):
        self.start(); self.plan_answer(self.PLAN)
        slots = self.app.state.device_diagnostics.slots
        for _ in range(3): self.assertTrue(slots.acquire(blocking=False))
        try: self.assertEqual(self.get('apply-plan', lab_id=self.lab_id, refresh='1').status_code, 503)
        finally:
            for _ in range(3): slots.release()

    def test_a_plan_still_being_computed_when_the_lab_changes_is_not_stored(self):
        self.start(); operations = self.app.state.operations
        def during(req): operations.forget_plan(self.lab_id)
        self.plan_answer(self.PLAN); self.hold = during
        self.assertEqual(self.get('apply-plan', lab_id=self.lab_id).status_code, 200)
        self.assertNotIn(self.lab_id, operations.plan_cache, 'the stale answer was not kept'); self.hold = None
        self.get('apply-plan', lab_id=self.lab_id); self.assertIn(self.lab_id, operations.plan_cache)

    def test_a_successful_sync_drops_the_cached_plan(self):
        self.start(); self.plan_answer(self.PLAN); self.get('apply-plan', lab_id=self.lab_id)
        operations = self.app.state.operations; self.assertIn(self.lab_id, operations.plan_cache)
        with patch.object(self.app.state.discovery, 'refresh'), patch('app.discovery.discovery_fresh', return_value=True), \
             patch('app.vm_files.prepare_lab', side_effect=lambda bundle, name, lab: dict(lab)):
            self.app.state.discovery.sources['training'] = {'files': {}}
            response = self.client.post('/api/labs/' + self.lab_id + '/sync', headers=self.auth, json={})
        self.assertEqual(response.status_code, 200, response.text); self.assertNotIn(self.lab_id, operations.plan_cache)


if __name__ == '__main__': unittest.main()
