"""The real gNMI path: pygnmi against an in-process gRPC server that answers like each vendor.

This validates the client, encoding selection, path origins, subscription fallbacks and the
normalisation of typed and JSON values end to end. It is a fixture test, not a device test."""
from concurrent import futures
import json
import queue
import threading
import time
import unittest

import grpc
from pygnmi.spec.v080 import gnmi_pb2, gnmi_pb2_grpc

from app.telemetry_adapters import ADAPTERS
from app.telemetry_collector import NodeCollector

ENCODINGS = {'json': 0, 'bytes': 1, 'proto': 2, 'ascii': 3, 'json_ietf': 4}


def gnmi_path(text):
    path = gnmi_pb2.Path()
    elems, depth, current = [], 0, ''
    for char in text.strip('/'):
        if char == '/' and depth == 0:
            elems.append(current); current = ''
            continue
        depth += (char == '[') - (char == ']')
        current += char
    if current: elems.append(current)
    for elem in elems:
        name, _, rest = elem.partition('[')
        item = path.elem.add(name=name)
        for key in rest.rstrip(']').split(']['):
            if key:
                k, v = key.split('=', 1)
                item.key[k] = v
    return path


def quiet_thread_errors(args):
    # pygnmi's subscribe thread re-raises the RpcError of a cancelled stream; expected here.
    if not isinstance(args.exc_value, grpc.RpcError):
        threading.__excepthook__(args)


threading.excepthook = quiet_thread_errors


def typed(value, encoding):
    if encoding == 'json_ietf':
        return gnmi_pb2.TypedValue(json_ietf_val=json.dumps(value).encode())
    if isinstance(value, bool):
        return gnmi_pb2.TypedValue(bool_val=value)
    if isinstance(value, int):
        return gnmi_pb2.TypedValue(uint_val=value)
    return gnmi_pb2.TypedValue(string_val=str(value))


class Servicer(gnmi_pb2_grpc.gNMIServicer):
    def __init__(self, models, encodings, fixtures, login=('admin', 'admin'), reject=(), abort_after=None):
        self.models, self.encodings, self.fixtures, self.login, self.reject, self.abort_after = models, encodings, fixtures, login, reject, abort_after
        self.requests = []
        self.lock = threading.Lock()

    def authenticate(self, context):
        metadata = dict(context.invocation_metadata())
        if (metadata.get('username'), metadata.get('password')) != self.login:
            context.abort(grpc.StatusCode.UNAUTHENTICATED, 'authentication failed')

    def Capabilities(self, request, context):
        self.authenticate(context)
        return gnmi_pb2.CapabilityResponse(supported_models=[gnmi_pb2.ModelData(name=m, organization='OpenConfig working group', version='1.0') for m in self.models],
                                           supported_encodings=[ENCODINGS[e] for e in self.encodings], gNMI_version='0.8.0')

    def Subscribe(self, request_iterator, context):
        self.authenticate(context)
        first = next(request_iterator).subscribe
        encoding = next(k for k, v in ENCODINGS.items() if v == first.encoding)
        paths = [(s.path.origin, '/'.join(e.name + ''.join(f'[{k}={v}]' for k, v in e.key.items()) for e in s.path.elem), gnmi_pb2.SubscriptionMode.Name(s.mode), s.sample_interval) for s in first.subscription]
        with self.lock:
            self.requests.append({'encoding': encoding, 'paths': paths})
        if encoding not in self.encodings:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'unsupported encoding')
        for origin, path, mode, _ in paths:
            if any(path.startswith(r) for r in self.reject) or mode == 'ON_CHANGE' and 'no-on-change' in self.reject:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'path not supported')
        group = 'bgp' if any('network-instances' in p for _, p, _, _ in paths) else 'interfaces'
        sent = 0
        while context.is_active():
            for prefix, updates in self.fixtures.get(group, []):
                notification = gnmi_pb2.Notification(timestamp=int(time.time() * 1e9), prefix=gnmi_path(prefix) if prefix else None)
                for path, value in updates:
                    notification.update.add(path=gnmi_path(path), val=typed(value, encoding))
                yield gnmi_pb2.SubscribeResponse(update=notification)
            if not sent:
                yield gnmi_pb2.SubscribeResponse(sync_response=True)
            sent += 1
            if self.abort_after and sent >= self.abort_after:
                context.abort(grpc.StatusCode.UNAVAILABLE, 'stream ended')
            time.sleep(0.2)


EOS = {'interfaces': [('interfaces/interface[name=Ethernet1]/state/counters', [('in-octets', 100), ('out-octets', 50), ('in-pkts', 7), ('out-pkts', 3)]),
                      ('interfaces/interface[name=Ethernet1]/state', [('oper-status', 'UP'), ('admin-status', 'UP')])],
       'bgp': [('network-instances/network-instance[name=default]/protocols/protocol[identifier=BGP][name=BGP]/bgp/neighbors/neighbor[neighbor-address=10.0.0.2]',
                [('state/session-state', 'ESTABLISHED'), ('afi-safis/afi-safi[afi-safi-name=IPV4_UNICAST]/state/prefixes/received', 4)])]}
XR = {'interfaces': [('', [('openconfig-interfaces:interfaces/interface[name=GigabitEthernet0/0/0/0]/state/counters', {'in-octets': '1000', 'out-octets': '2000', 'in-pkts': '5', 'out-pkts': '6'}),
                          ('openconfig-interfaces:interfaces/interface[name=GigabitEthernet0/0/0/0]/state/oper-status', 'UP')])],
      'bgp': [('', [('openconfig-network-instance:network-instances/network-instance[name=default]/protocols/protocol[identifier=BGP][name=default]/bgp/neighbors/neighbor[neighbor-address=10.0.0.1]/state', {'session-state': 'ACTIVE'})])]}
JUNOS = {'interfaces': [('interfaces/interface[name=et-0/0/0]/state/counters', [('in-octets', 500), ('out-octets', 400), ('__timestamp__', 1757764800000)]),
                        ('interfaces/interface[name=et-0/0/0]/state', [('oper-status', 'UP')])]}


class Server:
    def __init__(self, servicer):
        self.servicer = servicer
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
        gnmi_pb2_grpc.add_gNMIServicer_to_server(servicer, self.server)
        self.port = self.server.add_insecure_port('127.0.0.1:0')
        self.server.start()

    def stop(self):
        self.server.stop(0)


class Run:
    def __init__(self, adapter, port, login=('admin', 'admin'), transport='plaintext'):
        self.sink = queue.Queue()
        self.events = []
        self.collector = NodeCollector(('lab', 'r1'), 'g1', ('127.0.0.1', port), {'username': login[0], 'password': login[1]}, adapter, transport, self.sink, self.events.append)
        self.collector.start()

    def wait(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate(): return True
            time.sleep(0.05)
        return False

    def group(self, name, status):
        return any(e['event'] == 'group' and e['group'] == name and e['status'] == status for e in self.events)

    def records(self):
        out = []
        while True:
            try: out.append(self.sink.get_nowait())
            except queue.Empty: return out

    def stop(self):
        self.collector.stop(); self.collector.join(timeout=5)


class GnmiPipelineTests(unittest.TestCase):
    def test_eos_json_ietf_streams_interfaces_and_bgp(self):
        servicer = Servicer(['openconfig-interfaces', 'openconfig-network-instance'], ['json', 'json_ietf', 'proto'], EOS)
        server = Server(servicer)
        try:
            run = Run(ADAPTERS['arista_ceos'], server.port)
            self.assertTrue(run.wait(lambda: run.group('interfaces', 'streaming') and run.group('bgp', 'streaming')), run.events)
            self.assertTrue(run.wait(lambda: run.sink.qsize() >= 8))
            records = run.records()
            self.assertEqual({r['ident'] for r in records if r['kind'] == 'interface'}, {'Ethernet1'})
            self.assertIn(('in-octets', 100), {(r['metric'], r['value']) for r in records}); self.assertIn(('session-state', 'ESTABLISHED'), {(r['metric'], r['value']) for r in records})
            self.assertEqual({r['generation'] for r in records}, {'g1'}); self.assertEqual({r['lab_id'] for r in records}, {'lab'})
            self.assertEqual(servicer.requests[0]['encoding'], 'json_ietf'); self.assertEqual(servicer.requests[0]['paths'][0][0], '', 'EOS paths carry no origin')
            self.assertEqual(servicer.requests[0]['paths'][1][2], 'ON_CHANGE'); self.assertEqual(servicer.requests[0]['paths'][0][3], 10_000_000_000)
            connected = next(e for e in run.events if e['event'] == 'connected'); self.assertEqual(connected['transport'], 'plaintext')
            self.assertEqual({r['method'] for r in records if r['metric'] == 'oper-status'}, {'gnmi-on-change'})
            run.stop()
            self.assertFalse(any(e['event'] == 'failed' for e in run.events), 'a deliberate stop is not a failure')
        finally:
            server.stop()

    def test_a_quiet_subscription_reports_idle_and_stays_open_until_data_arrives(self):
        # EOS sends nothing at all for a sampled BGP path without neighbours; 1.23.0 closed the
        # group as "failed" after two minutes and painted the BGP pill red on every lab without BGP.
        from unittest import mock
        from app import telemetry_collector
        fixtures = {'interfaces': EOS['interfaces'], 'bgp': []}
        servicer = Servicer(['openconfig-interfaces', 'openconfig-network-instance'], ['json_ietf'], fixtures)
        server = Server(servicer)
        try:
            with mock.patch.object(telemetry_collector, 'GROUP_IDLE', 1.0):
                run = Run(ADAPTERS['arista_ceos'], server.port)
                self.assertTrue(run.wait(lambda: run.group('interfaces', 'streaming') and run.group('bgp', 'subscribed')), run.events)
                self.assertTrue(run.wait(lambda: run.group('bgp', 'idle'), timeout=10), run.events)
                self.assertFalse(run.group('bgp', 'failed')); self.assertFalse(any(e['event'] == 'failed' for e in run.events))
                self.assertIn('bgp', run.collector.streams, 'the subscription stays open')
                self.assertFalse(run.group('interfaces', 'idle'), 'a streaming group is never idle')
                fixtures['bgp'] = EOS['bgp']     # a neighbour appears: the same subscription delivers it
                self.assertTrue(run.wait(lambda: run.group('bgp', 'streaming'), timeout=10), run.events)
                self.assertTrue(run.wait(lambda: any(r['metric'] == 'session-state' for r in run.records())))
                run.stop()
        finally:
            server.stop()

    def test_xr_origins_string_counters_and_on_change_fallback(self):
        servicer = Servicer(['openconfig-interfaces', 'openconfig-network-instance'], ['json_ietf', 'proto'], XR)
        server = Server(servicer)
        try:
            run = Run(ADAPTERS['cisco_xrv9k'], server.port)
            self.assertTrue(run.wait(lambda: run.group('interfaces', 'streaming') and run.group('bgp', 'streaming')), run.events)
            records = run.records()
            self.assertIn(('GigabitEthernet0/0/0/0', 'in-octets', '1000'), {(r['ident'], r['metric'], r['value']) for r in records})
            self.assertIn(('10.0.0.1', 'session-state', 'ACTIVE'), {(r['ident'], r['metric'], r['value']) for r in records})
            self.assertEqual(servicer.requests[0]['paths'][0][0], 'openconfig-interfaces'); self.assertTrue(all(p[2] == 'SAMPLE' for p in servicer.requests[0]['paths']))
            self.assertEqual(servicer.requests[1]['paths'][0][0], 'openconfig-network-instance')
            run.stop()
        finally:
            server.stop()
        servicer = Servicer(['openconfig-interfaces'], ['json_ietf'], EOS, reject=('no-on-change',))
        server = Server(servicer)
        try:
            run = Run(ADAPTERS['arista_ceos'], server.port)
            self.assertTrue(run.wait(lambda: run.group('interfaces', 'streaming')), run.events)
            self.assertEqual([p[2] for p in servicer.requests[0]['paths']], ['SAMPLE', 'ON_CHANGE', 'ON_CHANGE'])
            self.assertEqual([p[2] for p in servicer.requests[1]['paths']], ['SAMPLE', 'SAMPLE', 'SAMPLE'], 'the sampled variant is the fallback')
            self.assertTrue(run.group('bgp', 'unsupported'), 'the BGP model is not advertised')
            self.assertEqual({r['method'] for r in run.records()}, {'gnmi-sample-10s'})
            run.stop()
        finally:
            server.stop()

    def test_junos_proto_only_targets_and_typed_values(self):
        servicer = Servicer(['openconfig-interfaces'], ['proto'], JUNOS)
        server = Server(servicer)
        try:
            run = Run(ADAPTERS['juniper_cjunosevolved'], server.port)
            self.assertTrue(run.wait(lambda: run.group('interfaces', 'streaming')), run.events)
            self.assertEqual(servicer.requests[0]['encoding'], 'proto')
            records = run.records()
            self.assertIn(('et-0/0/0', 'in-octets', 500), {(r['ident'], r['metric'], r['value']) for r in records})
            self.assertNotIn('__timestamp__', {r['metric'] for r in records})
            run.stop()
        finally:
            server.stop()

    def test_login_refusal_and_stream_loss_are_reported(self):
        servicer = Servicer(['openconfig-interfaces'], ['json_ietf'], EOS)
        server = Server(servicer)
        try:
            run = Run(ADAPTERS['arista_ceos'], server.port, login=('admin', 'wrong'))
            self.assertTrue(run.wait(lambda: any(e['event'] == 'failed' for e in run.events)), run.events)
            failed = next(e for e in run.events if e['event'] == 'failed')
            self.assertEqual(failed['reason'], 'auth'); self.assertNotIn('wrong', failed['message']); self.assertNotIn('127.0.0.1', failed['message'])
            run.stop()
        finally:
            server.stop()
        servicer = Servicer(['openconfig-interfaces'], ['json_ietf'], EOS, abort_after=3)
        server = Server(servicer)
        try:
            run = Run(ADAPTERS['arista_ceos'], server.port)
            self.assertTrue(run.wait(lambda: run.group('interfaces', 'streaming')), run.events)
            self.assertTrue(run.wait(lambda: any(e['event'] == 'failed' for e in run.events)), run.events)
            self.assertFalse(run.collector.is_alive() and not run.wait(lambda: not run.collector.is_alive(), 5))
            run.stop()
        finally:
            server.stop()

    def test_tls_first_targets_fall_back_to_plain_text_only_after_a_transport_error(self):
        servicer = Servicer(['openconfig-interfaces'], ['json_ietf'], EOS)
        server = Server(servicer)
        try:
            run = Run(ADAPTERS['cisco_xrv9k'], server.port, transport='tls')
            self.assertTrue(run.wait(lambda: run.group('interfaces', 'streaming'), 30), run.events)
            connected = next(e for e in run.events if e['event'] == 'connected'); self.assertEqual(connected['transport'], 'plaintext')
            run.stop()
        finally:
            server.stop()


if __name__ == '__main__':
    unittest.main()
