"""Manager side of C03: read-only device diagnostics over the operations helper (app/device_diagnostics.py).

The helper is patched at `app.lab_operations.remote`; a temporary Store is used, never live data.
"""
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import app.device_diagnostics as dd
from app.device_diagnostics import (cut_last, image_key, interface_role, public_facts, redact_lines, redact_text, strip_escapes)
from app.lab_operations import scrub
import test_discovery as discovery_tests

ID = 'a' * 64
STAMP = '2026-10-23T03:04:05.123456789Z'
FACTS = {'present': True, 'id': ID, 'pid': 4242, 'status': 'running', 'health': 'healthy', 'started': '2026-10-23T03:00:00Z',
         'kind': 'cisco_xrv9k', 'ports': [{'container': '22/tcp', 'host': '2201'}], 'labels': {'leak': 'x'}}
IFACES = [{'name': n, 'alias': '', 'state': 'up', 'mac': '02:00:00:00:00:0' + str(i), 'type': 'veth', 'mtu': 1500, 'ifindex': 10 + i}
          for i, n in enumerate(('eth0', 'eth1', 'eth2', 'lo'))]
COUNTERS = {k: 1 for k in dd.COUNTER_KEYS}


class PureTests(unittest.TestCase):
    def test_strip_escapes_removes_sequences_returns_and_controls_but_keeps_newline_and_tab(self):
        raw = '\x1b[31mred\x1b[0m\x1b]0;title\x07 ok\x1b]8;;http://x\x1b\\ a\tb\r\nnext\x00\x07\x1bMend\x7f'
        self.assertEqual(strip_escapes(raw), 'red ok a\tb\nnextend')

    def test_stamp_survives_redaction_and_only_the_body_is_judged(self):
        lines = [STAMP + ' PASSWORD: hunter2', STAMP + ' fine', 'no stamp password=abc', STAMP]
        got = redact_lines(lines, [], stamped=True)
        self.assertEqual(got, [(STAMP, dd.LINE_MASK), (STAMP, 'fine'), ('', dd.LINE_MASK), (STAMP, '')])

    def test_stored_secrets_are_replaced_longest_first_in_bodies_only(self):
        got = redact_lines([STAMP + ' login with s3cret-long and s3cret'], ['s3cret-long', 's3cret'], stamped=True)
        self.assertEqual(got, [(STAMP, 'login with [redacted] and [redacted]')])

    def test_a_private_key_block_is_omitted_from_begin_through_end_and_the_state_does_not_leak(self):
        lines = [STAMP + ' before', STAMP + ' -----BEGIN OPENSSH PRIVATE KEY-----', STAMP + ' b3BlbnNzaC1rZXk=', STAMP + ' AAAA',
                 STAMP + ' -----END OPENSSH PRIVATE KEY-----', STAMP + ' after']
        got = redact_lines(lines, [], stamped=True)
        self.assertEqual([b for _, b in got], ['before'] + [dd.KEY_BLOCK_MASK] * 4 + ['after'])
        self.assertTrue(all(s == STAMP for s, _ in got))
        one = redact_lines(['-----BEGIN RSA PRIVATE KEY----- x -----END RSA PRIVATE KEY-----', 'next'], [])
        self.assertEqual([b for _, b in one], [dd.KEY_BLOCK_MASK, 'next'])
        unfinished = redact_lines(['-----BEGIN PRIVATE KEY-----', 'abc', 'def'], [])
        self.assertEqual({b for _, b in unfinished}, {dd.KEY_BLOCK_MASK})

    def test_the_shared_rules_give_the_answers_scrub_gives_for_lines_and_secrets(self):
        state = {'host': {'password': 'pw-secret'}, 'labs': []}
        text = 'ok\nPASSWORD: abc\nuse pw-secret now\nsnmp community public\nplain\n'
        self.assertEqual(redact_text(text, ['pw-secret']), scrub(text, state))

    def test_cut_last_keeps_the_end_at_a_line(self):
        text = ''.join('line %05d\n' % i for i in range(100))
        cut, truncated = cut_last(text, 100)
        self.assertTrue(truncated); self.assertTrue(cut.startswith('line ')); self.assertTrue(cut.endswith('line 00099\n'))
        self.assertLessEqual(len(cut.encode()), 100)
        self.assertEqual(cut_last('short\n', 100), ('short\n', False))

    def test_image_key_is_a_normal_form_never_a_string_compare(self):
        same = {image_key(r) for r in ('alpine', 'alpine:latest', 'docker.io/library/alpine:latest', 'index.docker.io/library/alpine')}
        self.assertEqual(same, {'docker.io/library/alpine:latest'})
        self.assertEqual(image_key('ghcr.io/nokia/srlinux'), 'ghcr.io/nokia/srlinux:latest')
        self.assertEqual(image_key('ceos:4.35.0F'), 'docker.io/library/ceos:4.35.0F')
        self.assertEqual(image_key('localhost:5000/x'), 'localhost:5000/x:latest')
        self.assertEqual(image_key('n24l/cisco_xrv9k:24.3.1'), 'docker.io/n24l/cisco_xrv9k:24.3.1')
        digest = 'ghcr.io/a/b@sha256:' + 'c' * 64
        self.assertEqual(image_key(digest), 'ghcr.io/a/b@sha256:' + 'c' * 64)
        self.assertNotEqual(image_key('alpine'), image_key('alpine:3'))
        self.assertEqual((image_key(''), image_key(None), image_key(3)), ('', '', ''))

    def test_role_and_port_rules(self):
        self.assertEqual(interface_role('arista_ceos', 'eth0'), 'management')
        for name in ('cpu', 'fabric', 'lo'): self.assertEqual(interface_role('arista_ceos', name), 'internal')
        self.assertEqual(interface_role('arista_ceos', 'eth1'), 'data')
        self.assertEqual([interface_role('juniper_cjunosevolved', 'eth%d' % i) for i in (1, 2, 3, 4)], ['internal'] * 3 + ['data'])
        self.assertEqual(interface_role('nokia_srlinux', 'e1-1'), 'data')
        self.assertEqual(interface_role('linux', 'eth1'), 'data')

    def test_public_facts_copies_fields_and_drops_the_rest(self):
        got = public_facts(FACTS)
        self.assertEqual(set(got), {'present', 'id', 'pid', 'status', 'health', 'started', 'ports'})
        self.assertEqual(public_facts({'present': False}), {'present': False})
        self.assertEqual(public_facts('x'), {'present': False})
        self.assertEqual(public_facts({'present': True, 'pid': True})['pid'], 0)


class DiagnosticsAPITests(unittest.TestCase):
    setUp = discovery_tests.DiscoveryTests.setUp
    register = discovery_tests.DiscoveryTests.register
    host = discovery_tests.DiscoveryTests.host

    def tearDown(self):
        self.app.state.operations.close(); discovery_tests.DiscoveryTests.tearDown(self)

    def start(self, handler=None):
        """A linked lab 'training' (r1 xrv9k, r2 cjunosevolved) and a patched helper that records its requests."""
        self.host(); lab = self.register(); self.lab_id = lab['id']
        self.store.state['host']['fingerprint'] = 'SHA256:fixture'
        with self.store.lock:
            stored = self.store.lab(self.lab_id)
            stored['vm_project_path'] = '/etc/containerlab/training/training.clab.yaml'
            self.node = stored['nodes'][0]['name']
        self.requests = []
        self.answers = {}

        def remote(host, req, output=None, stopping=None, timeout=None):
            self.requests.append((req, timeout))
            answer = self.answers.get(req['mode'])
            if isinstance(answer, Exception): raise answer
            return answer(req) if callable(answer) else answer
        patcher = patch('app.lab_operations.remote', side_effect=remote); patcher.start(); self.addCleanup(patcher.stop)

    def get(self, path, **params):
        return self.client.get('/api/operations/' + path, headers=self.auth, params=params)

    def logs(self, **extra):
        return self.get('logs', lab_id=self.lab_id, node=self.node, **extra)

    def events(self):
        path = Path(self.tmp.name) / 'events.jsonl'
        return path.read_bytes() if path.exists() else b''

    def test_logs_request_shape_redaction_and_public_answer(self):
        self.start()
        key = ['-----BEGIN OPENSSH PRIVATE KEY-----', 'b3BlbnNzaC1rZXktdjE=', 'QUFBQUI=', '-----END OPENSSH PRIVATE KEY-----']
        text = '\n'.join([STAMP + ' \x1b[31mPASSWORD: hunter2\x1b[0m', STAMP + ' booting\r', 'stampless line', STAMP + ' host-secret leaked',
                          *[STAMP + ' ' + k for k in key], STAMP + ' \x1b]0;t\x07done']) + '\n'
        self.answers['logs'] = {'facts': FACTS, 'text': text, 'truncated': True, 'extra': 'no'}
        response = self.logs(tail='500', since='2026-10-23T03:00:00Z')
        self.assertEqual(response.status_code, 200, response.text)
        request, timeout = self.requests[0]
        self.assertEqual(request, {'mode': 'logs', 'name': 'training', 'options': {'node': 'r1', 'container': 'clab-training-r1',
                                                                                    'tail': 500, 'since': '2026-10-23T03:00:00Z'}})
        self.assertIs(type(request['options']['tail']), int); self.assertEqual(timeout, 30)
        body = response.json()
        self.assertEqual(set(body), {'container', 'present', 'facts', 'lines', 'truncated', 'fetched_at'})
        self.assertEqual(body['container'], 'clab-training-r1'); self.assertTrue(body['truncated']); self.assertTrue(body['present'])
        self.assertNotIn('labels', body['facts']); self.assertNotIn('kind', body['facts'])
        self.assertEqual(body['lines'], [
            {'at': STAMP, 'text': dd.LINE_MASK}, {'at': STAMP, 'text': 'booting'}, {'at': '', 'text': 'stampless line'},
            {'at': STAMP, 'text': dd.SECRET_MASK + ' leaked'}] + [{'at': STAMP, 'text': dd.KEY_BLOCK_MASK}] * 4 + [{'at': STAMP, 'text': 'done'}])
        self.assertNotIn('b3Blbn', response.text); self.assertNotIn('hunter2', response.text); self.assertNotIn('\\u001b', response.text)

    def test_since_is_left_out_when_not_asked_and_the_default_tail_is_200(self):
        self.start(); self.answers['logs'] = {'facts': FACTS, 'text': '', 'truncated': False}
        self.assertEqual(self.logs().status_code, 200)
        self.assertEqual(self.requests[0][0]['options'], {'node': 'r1', 'container': 'clab-training-r1', 'tail': 200})
        self.assertEqual(self.logs(since='').status_code, 200)
        self.assertNotIn('since', self.requests[1][0]['options'])
        self.assertEqual(self.logs().json()['lines'], [])

    def test_bad_tail_and_since_are_refused_before_the_helper_is_asked(self):
        self.start(); self.answers['logs'] = {'facts': FACTS, 'text': '', 'truncated': False}
        for tail in ('0', '2001', '10x', '１０', ' 10', '-1', '1.5', 'true', '', '00001e', '99999'):
            response = self.logs(tail=tail)
            self.assertEqual(response.status_code, 400, tail); self.assertEqual(response.json()['detail'], dd.TAIL_SENTENCE)
        for since in ('2026-10-23', '2026-10-23T03:00:00', '2026-10-23T03:00:00+00:00', '２０２６-10-23T03:00:00Z', '2026-10-23T03:00:00Z\n',
                      '2026-10-23T03:00:00.1234567890Z', 'yesterday'):
            response = self.logs(since=since)
            self.assertEqual(response.status_code, 400, since); self.assertEqual(response.json()['detail'], dd.SINCE_SENTENCE)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.logs(tail='2000', since='2026-10-23T03:00:00.5Z').status_code, 200)

    def test_twenty_polls_leave_events_and_the_store_free_of_log_text(self):
        self.start(); self.answers['logs'] = {'facts': FACTS, 'text': STAMP + ' marker-line-xyz\n', 'truncated': False}
        before = self.events(); state_before = json.dumps(self.store.state, sort_keys=True, default=str)
        for _ in range(20): self.assertEqual(self.logs().status_code, 200)
        self.assertEqual(self.events(), before)
        self.assertEqual(json.dumps(self.store.state, sort_keys=True, default=str), state_before)
        self.assertNotIn('marker-line-xyz', json.dumps(self.store.state, default=str))
        self.assertNotIn(b'marker-line-xyz', self.events())

    def test_polled_reads_write_no_event_but_a_view_post_is_the_one_audited_record(self):
        self.start()
        self.answers['interfaces'] = {'facts': FACTS, 'interfaces': IFACES, 'counters': {'eth1': COUNTERS}, 'sampled_at': 1.5}
        self.answers['netem-show'] = {'facts': FACTS, 'impairments': []}
        before = self.events()
        for path in ('interfaces', 'netem'): self.assertEqual(self.get(path, lab_id=self.lab_id, node=self.node).status_code, 200)
        self.assertEqual(self.events(), before)

    def test_absent_container_is_not_an_error(self):
        self.start()
        self.answers.update({'logs': {'facts': {'present': False}, 'text': '', 'truncated': False},
                             'interfaces': {'facts': {'present': False}, 'interfaces': []},
                             'netem-show': {'facts': {'present': False}, 'impairments': []}})
        logs = self.logs().json()
        self.assertEqual((logs['present'], logs['lines'], logs['facts'], logs['container']), (False, [], {'present': False}, 'clab-training-r1'))
        interfaces = self.get('interfaces', lab_id=self.lab_id, node=self.node).json()
        self.assertEqual((interfaces['present'], interfaces['interfaces'], interfaces['counters'], interfaces['sampled_at']), (False, [], {}, None))
        self.assertEqual(self.get('netem', lab_id=self.lab_id, node=self.node).json(), {'container': 'clab-training-r1', 'present': False, 'impairments': []})

    def test_unlinked_lab_unknown_node_and_unknown_device_have_their_sentences(self):
        self.start(); self.answers['logs'] = {'facts': FACTS, 'text': '', 'truncated': False}
        with self.store.lock:
            lab = self.store.lab(self.lab_id); node = lab['nodes'][1]
            node['definition_node'] = ''; node['short_name'] = ''
        response = self.get('logs', lab_id=self.lab_id, node=node['name'])
        self.assertEqual((response.status_code, response.json()['detail']), (409, dd.NO_NODE_SENTENCE))
        with self.store.lock: self.store.lab(self.lab_id)['deployment_name'] = ''
        response = self.logs()
        self.assertEqual((response.status_code, response.json()['detail']), (409, dd.UNLINKED_SENTENCE))
        self.assertEqual(self.get('logs', lab_id='nope', node=self.node).status_code, 404)
        self.assertEqual(self.get('logs', lab_id=self.lab_id, node='ghost').status_code, 404)
        self.assertEqual(self.requests, [])

    def test_the_browser_cannot_name_a_container_or_lab(self):
        self.start(); self.answers['logs'] = {'facts': FACTS, 'text': '', 'truncated': False}
        response = self.get('logs', lab_id=self.lab_id, node=self.node, container='clab-other-r9', name='other')
        self.assertEqual(response.status_code, 200)
        request = self.requests[0][0]
        self.assertEqual((request['name'], request['options']['container']), ('training', 'clab-training-r1'))
        self.assertEqual(self.get('logs', lab_id=self.lab_id, node='clab-other-r9').status_code, 404)

    def test_interfaces_public_shape_port_role_and_counters(self):
        self.start()
        names = ('eth0', 'eth1', 'eth2', 'eth3', 'eth4', 'cpu', 'fabric1', 'e1-1', 'lo')
        rows = [dict(IFACES[0], name=n) for n in names]
        counters = {n: COUNTERS for n in names[:3]}; counters['stranger'] = COUNTERS
        expect = {
            'cisco_xrv9k': {'eth0': ('', 'management'), 'eth1': ('Gi0/0/0/0', 'data'), 'eth4': ('Gi0/0/0/3', 'data'), 'cpu': ('', 'internal')},
            'juniper_vjunosswitch': {'eth1': ('ge-0/0/0', 'data'), 'eth0': ('', 'management')},
            'juniper_cjunosevolved': {'eth1': ('', 'internal'), 'eth2': ('', 'internal'), 'eth3': ('', 'internal'), 'eth4': ('et-0/0/0', 'data')},
            'arista_ceos': {'eth0': ('', 'management'), 'eth1': ('Ethernet1', 'data'), 'cpu': ('', 'internal'), 'fabric1': ('', 'internal')},
            'nokia_srlinux': {'e1-1': ('', 'data'), 'eth0': ('', 'management')},
            'linux': {'eth1': ('', 'data')},
        }
        for kind, wanted in expect.items():
            self.answers['interfaces'] = {'facts': dict(FACTS, kind=kind), 'interfaces': rows, 'counters': counters, 'sampled_at': 12.5, 'output': 'raw'}
            response = self.get('interfaces', lab_id=self.lab_id, node=self.node)
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(set(body), {'container', 'present', 'facts', 'interfaces', 'counters', 'sampled_at', 'counters_reason'})
            got = {i['name']: (i['port'], i['role']) for i in body['interfaces']}
            for name, pair in wanted.items(): self.assertEqual(got[name], pair, (kind, name))
            self.assertEqual(set(body['interfaces'][0]), {'name', 'alias', 'state', 'mac', 'type', 'mtu', 'ifindex', 'port', 'role'})
            self.assertEqual(set(body['counters']), {'eth0', 'eth1', 'eth2'}, 'counters of an interface not in the list are dropped')
            self.assertEqual((body['sampled_at'], body['counters_reason']), (12.5, ''))
            self.assertNotIn('raw', response.text)
        self.assertEqual(self.requests[0][0], {'mode': 'interfaces', 'name': 'training', 'options': {'node': 'r1', 'container': 'clab-training-r1'}})
        self.assertEqual(self.requests[0][1], 45)

    def test_counters_reason_and_the_node_kind_fallback(self):
        self.start()
        for reason in ('pid', 'host'):
            self.answers['interfaces'] = {'facts': {k: v for k, v in FACTS.items() if k != 'kind'}, 'interfaces': IFACES, 'counters_reason': reason}
            body = self.get('interfaces', lab_id=self.lab_id, node=self.node).json()
            self.assertEqual((body['counters'], body['sampled_at'], body['counters_reason']), ({}, None, reason))
        self.assertEqual({i['name']: i['port'] for i in body['interfaces']}['eth1'], 'Gi0/0/0/0', "the manager's own node kind is the fallback")

    def test_netem_is_an_allowlisted_copy(self):
        self.start()
        self.answers['netem-show'] = {'facts': FACTS, 'impairments': [{'interface': 'eth1', 'delay': '15ms', 'loss': 5, 'rate': 1.5, 'secret': 'x'},
                                                                      {'interface': ''}, 'junk']}
        response = self.get('netem', lab_id=self.lab_id, node=self.node)
        self.assertEqual(response.json(), {'container': 'clab-training-r1', 'present': True,
                                           'impairments': [{'interface': 'eth1', 'delay': '15ms', 'loss': 5, 'rate': 1.5}]})
        self.assertEqual(self.requests[0], ({'mode': 'netem-show', 'name': 'training', 'options': {'node': 'r1', 'container': 'clab-training-r1'}}, 30))

    def test_the_fourth_concurrent_call_is_a_503_and_a_slot_frees_after_every_outcome(self):
        self.start(); self.answers['logs'] = {'facts': FACTS, 'text': '', 'truncated': False}
        slots = self.app.state.device_diagnostics.slots
        for _ in range(3): self.assertTrue(slots.acquire(blocking=False))
        for path in ('logs', 'interfaces', 'netem'):
            response = self.get(path, lab_id=self.lab_id, node=self.node)
            self.assertEqual((response.status_code, response.json()['detail']), (503, dd.BUSY_SENTENCE), path)
        self.assertEqual(self.requests, [])
        slots.release()
        self.assertEqual(self.logs().status_code, 200)
        for _ in range(2): slots.release()
        self.answers['logs'] = ValueError('Docker on the VM did not answer about this container.')
        for _ in range(5): self.assertEqual(self.logs().status_code, 409)
        self.answers['logs'] = RuntimeError('boom')
        for _ in range(5): self.assertEqual(self.logs().status_code, 409)
        self.answers['logs'] = {'facts': FACTS, 'text': '', 'truncated': False}
        for _ in range(3): self.assertTrue(slots.acquire(blocking=False))   # all three are free again
        for _ in range(3): slots.release()

    def test_helper_sentences_map_and_the_old_helper_gets_the_student_sentence(self):
        self.start()
        for sentence in ('This container does not belong to lab training.', "Docker on the VM did not return this container's log.",
                         'Ask for 1 to 2000 log lines.', 'This lab was deployed from outside the trusted lab roots. Add its project root during operations setup.'):
            self.answers['logs'] = ValueError(sentence)
            response = self.logs()
            self.assertEqual((response.status_code, response.json()['detail']), (409, sentence))
        self.answers['logs'] = ValueError('Unknown request mode.')
        self.assertEqual(self.logs().json()['detail'], dd.OLD_HELPER_SENTENCE)
        self.answers['logs'] = RuntimeError('socket detail 10.0.0.1')
        detail = self.logs().json()['detail']
        self.assertEqual(detail, dd.UNREACHABLE_SENTENCE); self.assertNotIn('10.0.0.1', detail)
        self.answers['logs'] = ['not', 'a', 'dict']
        self.assertEqual(self.logs().json()['detail'], dd.UNUSABLE_SENTENCE)

    def test_view_redacts_cuts_at_a_line_and_read_stays_exact(self):
        self.start()
        folder = '/etc/containerlab/training/'
        raw = '\x1b[1mhostname r1\x1b[0m\r\nusername admin password 0 s3cret\nsnmp-server community public ro\n'
        self.answers['read'] = lambda req: {'path': req['path'], 'text': raw, 'sha256': 'x'}
        view = lambda path, lab=None: self.client.post('/api/operations/view', headers=self.auth, json={'lab_id': lab or self.lab_id, 'path': path})
        response = view('clab-training/r1/startup-config')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.requests[-1][0], {'mode': 'read', 'path': folder + 'clab-training/r1/startup-config'})
        self.assertEqual(response.json(), {'name': 'startup-config', 'text': 'hostname r1\n' + dd.LINE_MASK + '\n' + dd.LINE_MASK + '\n', 'truncated': False})
        self.assertEqual(view(folder + 'training.clab.yaml').status_code, 200, 'an absolute path inside the lab folder is accepted')
        before = len(self.requests)
        for bad in ('/etc/passwd', '../other/x.yaml', 'a/../../x', '', '/etc/containerlab/training', '/etc/containerlab/training-evil/x', 'a\x00b'):
            self.assertEqual(view(bad).status_code, 400, bad)
        self.assertEqual(len(self.requests), before)
        self.assertEqual(view('x', lab='nope').status_code, 404)
        self.assertEqual(self.client.post('/api/operations/read', headers=self.auth, json={'path': folder + 'training.clab.yaml'}).json()['text'], raw,
                         '/read is untouched and byte-exact')
        big = ''.join('line %06d filler filler filler filler\n' % i for i in range(16000))   # about 600 KiB
        self.assertGreater(len(big.encode()), 600 * 1024 - 1)
        self.answers['read'] = lambda req: {'path': req['path'], 'text': big, 'sha256': 'x'}
        cut = view('big.txt').json()
        self.assertTrue(cut['truncated']); self.assertLessEqual(len(cut['text'].encode()), dd.VIEW_LIMIT)
        self.assertTrue(cut['text'].startswith('line ')); self.assertTrue(cut['text'].endswith('line 015999 filler filler filler filler\n'))
        with self.store.lock: self.store.lab(self.lab_id)['vm_project_path'] = ''
        self.assertEqual(view('x').status_code, 409)

    def test_view_replaces_stored_secrets(self):
        self.start()
        self.answers['read'] = {'path': 'p', 'text': 'login host-secret ok\n', 'sha256': 'x'}
        response = self.client.post('/api/operations/view', headers=self.auth, json={'lab_id': self.lab_id, 'path': 'a.txt'})
        self.assertEqual(response.json()['text'], 'login [redacted] ok\n')

    def test_browse_without_files_is_the_old_request_and_with_files_copies_entries(self):
        self.start()
        self.answers['browse'] = {'path': '/etc/containerlab', 'parent': '', 'entries': [{'name': 'a', 'path': '/etc/containerlab/a', 'directory': True}], 'x': 1}
        post = lambda **body: self.client.post('/api/operations/browse', headers=self.auth, json=body)
        response = post(path='/etc/containerlab')
        self.assertEqual(self.requests[-1][0], {'mode': 'browse', 'path': '/etc/containerlab'})
        self.assertEqual(response.json(), self.answers['browse'])
        self.answers['browse'] = {'path': '/e/t', 'parent': '/e', 'entries': [
            {'name': 'clab-t', 'path': '/e/t/clab-t', 'directory': True, 'kind': 'directory'},
            {'name': 't.clab.yaml', 'path': '/e/t/t.clab.yaml', 'directory': False, 'kind': 'topology', 'size': 120},
            {'name': 'startup-config', 'path': '/e/t/startup-config', 'directory': False, 'kind': 'file', 'size': 2100, 'owner': 'root'}, 'junk', {'name': 5}]}
        response = post(path='/e/t', files=True, lab_id=self.lab_id)
        self.assertEqual(self.requests[-1][0], {'mode': 'browse', 'path': '/e/t', 'options': {'files': True}})
        self.assertEqual(response.json()['entries'], [
            {'name': 'clab-t', 'path': '/e/t/clab-t', 'directory': True, 'kind': 'directory'},
            {'name': 't.clab.yaml', 'path': '/e/t/t.clab.yaml', 'directory': False, 'kind': 'topology', 'size': 120},
            {'name': 'startup-config', 'path': '/e/t/startup-config', 'directory': False, 'kind': 'file', 'size': 2100}])
        self.assertEqual(post(path='/e', files='yes please').status_code, 422)
        self.assertEqual(post(path='/e', options={}).status_code, 422)

    def test_images_tolerate_an_old_helper_and_build_used_by_and_missing_through_image_key(self):
        self.start()
        topology = 'name: x\ntopology:\n  nodes:\n    a:\n      kind: linux\n      image: alpine\n    b:\n      kind: linux\n      image: ghcr.io/x/y:1\n' \
                   '    c:\n      kind: linux\n      image: ghcr.io/x/pinned@sha256:' + 'd' * 64 + '\n'
        with self.store.lock: self.store.lab(self.lab_id)['definition_yaml'] = topology
        self.answers['images'] = {'available': True, 'images': ['alpine:latest', 'other:1']}
        body = self.get('images').json()
        self.assertEqual(body['details'], [])
        self.assertEqual(body['images'], ['alpine:latest', 'other:1'])
        self.assertEqual(body['used_by'], {'alpine:latest': ['training'], 'ghcr.io/x/y:1': ['training'], 'ghcr.io/x/pinned@sha256:' + 'd' * 64: ['training']})
        self.assertEqual(body['missing'], ['ghcr.io/x/y:1'], 'alpine matches alpine:latest by key; a digest is never missing')
        self.assertEqual(len([r for r, _ in self.requests if r['mode'] == 'images']), 1)
        self.get('images'); self.assertEqual(len(self.requests), 1, 'the helper answer is cached for a minute')
        self.app.state.device_diagnostics.images_cache = None
        self.answers['images'] = {'available': True, 'images': ['alpine:latest'], 'details': [
            {'reference': 'alpine:latest', 'id': 'abc', 'size': '7.8MB', 'created': '2026-01-01', 'extra': 'x'}, 'junk']}
        body = self.get('images').json()
        self.assertEqual(body['details'], [{'reference': 'alpine:latest', 'id': 'abc', 'size': '7.8MB', 'created': '2026-01-01'}])

    def test_images_error_maps_like_the_other_routes(self):
        self.start(); self.answers['images'] = ValueError('Unknown request mode.')
        response = self.get('images')
        self.assertEqual((response.status_code, response.json()['detail']), (409, dd.OLD_HELPER_SENTENCE))

    def test_capabilities_pass_diagnostics_and_the_containerlab_version_through(self):
        self.start(); self.answers['capabilities'] = {'protocol': 'p', 'version': '1', 'actions': {}, 'roots': [], 'network': False,
                                                      'diagnostics': True, 'containerlab': '0.79.0'}
        body = self.get('capabilities').json()
        self.assertEqual((body['diagnostics'], body['containerlab']), (True, '0.79.0'))

    def test_the_routes_sit_before_the_job_route_and_guard_the_origin(self):
        self.start(); self.answers['logs'] = {'facts': FACTS, 'text': '', 'truncated': False}
        response = self.client.get('/api/operations/logs', headers={**self.auth, 'Origin': 'https://other.example'}, params={'lab_id': self.lab_id, 'node': self.node})
        self.assertEqual(response.status_code, 403)
        self.assertIn('lines', self.logs().json(), '/logs is not taken by GET /api/operations/{job_id}')
        self.assertEqual(self.get('logs').status_code, 422)


if __name__ == '__main__':
    unittest.main()
