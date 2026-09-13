"""Notification normalisation for the three vendor shapes and failure classification."""
import json
from pathlib import Path
import time
import unittest

from app.telemetry_collector import classify, failure_reason, flatten, normalize

FIXTURES = Path(__file__).parent / 'fixtures' / 'telemetry'


def load(name):
    return json.loads((FIXTURES / name).read_text())


def records(name, now=1_757_764_805.0):
    result = []
    for message in load(name):
        result.extend(normalize(message, now))
    return result


class NormalizeTests(unittest.TestCase):
    def test_eos_per_leaf_updates_with_prefix(self):
        rows = records('eos_interfaces_json_ietf.json')
        counters = {r['metric']: r['value'] for r in rows if r['ident'] == 'Ethernet1' and r['ts'] == 1757764800.0}
        self.assertEqual(counters['in-octets'], 123456); self.assertEqual(counters['oper-status'], 'UP')
        self.assertEqual({r['ident'] for r in rows}, {'Ethernet1', 'Management0'})
        self.assertEqual([r['value'] for r in rows if r['metric'] == 'in-octets'], [123456, 1123456])
        self.assertTrue(all(r['kind'] == 'interface' for r in rows))

    def test_xr_module_prefixed_json_subtrees_with_string_counters(self):
        rows = records('xr_interfaces_json_ietf.json')
        first = [r for r in rows if r['ident'] == 'GigabitEthernet0/0/0/0' and r['ts'] == 1757764800.0]
        self.assertEqual({r['metric'] for r in first}, {'in-octets', 'out-octets', 'in-pkts', 'out-pkts', 'in-errors', 'out-errors', 'in-discards', 'out-discards', 'oper-status', 'admin-status'})
        self.assertEqual(next(r['value'] for r in first if r['metric'] == 'in-octets'), '100000', 'RFC 7951 strings are passed to the store as-is')
        self.assertNotIn('last-clear', {r['metric'] for r in first})
        self.assertIn('MgmtEth0/RP0/CPU0/0', {r['ident'] for r in rows})

    def test_junos_proto_prefix_elements_and_extra_leaves(self):
        rows = records('junos_interfaces_proto.json')
        self.assertEqual({r['ident'] for r in rows}, {'et-0/0/0', 'et-0/0/0.0'})
        self.assertNotIn('__timestamp__', {r['metric'] for r in rows})
        self.assertEqual([r['value'] for r in rows if r['metric'] == 'out-octets'], [4000, 9000])

    def test_bgp_shapes_for_all_three_vendors(self):
        eos = records('eos_bgp_json_ietf.json')
        self.assertEqual([(r['ident'], r['metric'], r['value']) for r in eos], [('10.0.0.2', 'session-state', 'ESTABLISHED'), ('10.0.0.2', 'received', 12), ('10.0.0.2', 'sent', 7)])
        self.assertEqual(eos[1]['afi'], 'IPV4_UNICAST'); self.assertEqual(eos[0]['instance'], 'default')
        xr = records('xr_bgp_json_ietf.json')
        self.assertEqual({(r['metric'], r['value']) for r in xr}, {('session-state', 'ESTABLISHED'), ('received', '3'), ('sent', '5'), ('installed', '3')})
        self.assertEqual(xr[1]['afi'], 'IPV4_UNICAST', 'the identity module prefix is stripped from key values')
        junos = records('junos_bgp_proto.json')
        self.assertEqual((junos[0]['instance'], junos[0]['ident'], junos[0]['value']), ('master', '192.0.2.1', 'ACTIVE'))

    def test_timestamps_far_from_now_are_replaced_by_receive_time(self):
        now = time.time()
        message = {'update': {'timestamp': int((now - 3600) * 1e9), 'prefix': '/interfaces/interface[name=Ethernet1]/state', 'update': [{'path': 'oper-status', 'val': 'DOWN'}]}}
        self.assertEqual(normalize(message, now)[0]['ts'], now)
        message['update']['timestamp'] = int((now - 5) * 1e9)
        self.assertAlmostEqual(normalize(message, now)[0]['ts'], now - 5, places=3)
        self.assertEqual(normalize({'sync_response': True}, now), []); self.assertEqual(normalize(None, now), [])

    def test_flatten_handles_keyed_lists_and_ignores_unkeyed_ones(self):
        value = {'openconfig-network-instance:network-instance': [{'name': 'default', 'protocols': {'protocol': [{'identifier': 'BGP', 'name': 'BGP', 'bgp': {'neighbors': {'neighbor': [{'neighbor-address': '10.0.0.9', 'state': {'session-state': 'IDLE'}}]}}}]}}]}
        leaves = dict(flatten('', 'network-instances', value))
        self.assertEqual(leaves, {'network-instances/network-instance[name=default]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor[neighbor-address=10.0.0.9]/state/session-state': 'IDLE'})
        self.assertEqual(dict(flatten('', 'x', {'list': [1, 2, 3]})), {})
        self.assertIsNone(classify('interfaces/interface[name=Ethernet1]/state/mtu', 1500))
        self.assertIsNone(classify('components/component[name=cpu]/state/temperature', 40))


class FailureReasonTests(unittest.TestCase):
    def test_grpc_codes_and_texts_are_classified_without_echoing_details(self):
        class Err(Exception):
            def __init__(self, name): super().__init__('GRPC ERROR Host: 10.0.0.1:6030, Error: secret detail'); self.name = name
            def code(self): return self
        for name, expected in (('UNAUTHENTICATED', 'auth'), ('PERMISSION_DENIED', 'auth'), ('UNAVAILABLE', 'connect'), ('DEADLINE_EXCEEDED', 'connect'), ('INVALID_ARGUMENT', 'unsupported'), ('UNIMPLEMENTED', 'unsupported'), ('INTERNAL', 'error')):
            kind, message = failure_reason(Err(name))
            self.assertEqual(kind, expected, name); self.assertNotIn('secret detail', message); self.assertNotIn('10.0.0.1', message)
        self.assertEqual(failure_reason(Exception('The SSL certificate cannot be retrieved from x'))[0], 'connect')
        self.assertEqual(failure_reason(Exception("Requested encoding 'proto' not in supported encodings"))[0], 'unsupported')


if __name__ == '__main__':
    unittest.main()
