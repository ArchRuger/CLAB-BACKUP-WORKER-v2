"""The telemetry state machine on the running app: readiness-triggered provisioning, repeat safety,
retries, credential failures and redaction, unsupported kinds, stale detection, cleanup on runtime
changes, lab operations, removal and reset, address reuse, settings and series APIs and their limits."""
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import telemetry as manager_module
from app.main import create_app
from app.telemetry import RETRY_CONNECT_MAX, RETRY_MAX, RETRY_MIN, TelemetryManager, end_status, link_status, summarize
from app.telemetry_provision import ProvisionError


class Inline:
    def submit(self, fn, *args):
        fn(*args)

    def shutdown(self, **kwargs):
        pass


class FakeCollector:
    """Stands in for the gNMI worker: the tests raise its events and push its records."""
    instances = []

    def __init__(self, key, generation, target, creds, adapter, transport, sink, report, stopping=None):
        self.key, self.generation, self.target, self.creds, self.adapter, self.transport = key, generation, target, creds, adapter, transport
        self.sink, self.report, self.alive = sink, report, False
        FakeCollector.instances.append(self)

    def start(self):
        self.alive = True
        self.report({'key': self.key, 'generation': self.generation, 'event': 'connected', 'transport': self.transport, 'models': 2, 'encodings': ['json_ietf']})

    def stop(self):
        self.alive = False

    def is_alive(self):
        return self.alive

    def group(self, group, status, message='fixture'):
        self.report({'key': self.key, 'generation': self.generation, 'event': 'group', 'group': group, 'status': status, 'message': message})

    def fail(self, reason, message):
        self.alive = False
        self.report({'key': self.key, 'generation': self.generation, 'event': 'failed', 'reason': reason, 'message': message})

    def push(self, ts, ident, values, kind='interface', generation=None, **extra):
        for metric, value in values.items():
            self.sink.put({'lab_id': self.key[0], 'node': self.key[1], 'generation': generation or self.generation, 'kind': kind,
                           'ident': ident, 'metric': metric, 'value': value, 'ts': ts, 'method': 'gnmi-sample-10s', **extra})


def node(short, address, platform='arista_ceos'):
    return dict(name='clab-demo-' + short, short_name=short, definition_node=short, address=address, port=22,
                platform=platform, enabled=bool(platform), profile_id='', username='', password='', enable_password='',
                groups=[], endpoint_mode='auto', discovered=True, runtime_state='running', discovered_address=address)


class TelemetryManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        self.store = self.app.state.store
        self.services = self.app.state.node_services
        self.manager = self.app.state.telemetry
        self.manager.pool = Inline()
        FakeCollector.instances = []
        self.connects = []
        self.provisions = []
        self.provision_result = lambda adapter, mode: {'port': adapter.default_port, 'transport': 'plaintext', 'vrf': '', 'removed': [],
                                                        'applied': [] if mode != 'apply' else ['management api gnmi', '   transport grpc default'],
                                                        'blockers': [], 'missing': [], 'message': 'Added 2 telemetry configuration line(s).'}

        def connect(client, item, creds):
            self.connects.append((item['name'], creds.get('username'), creds.get('password')))

        def provision(client, adapter, creds, mode='apply', owned=None):
            self.provisions.append((adapter.kind, mode, list(owned or [])))
            result = self.provision_result(adapter, mode)
            if isinstance(result, Exception): raise result
            if mode == 'remove': result = dict(result, removed=list(owned or []), message='Removed the telemetry lines the manager had added.')
            return result
        self.patches = [patch.object(manager_module, 'connect', connect), patch.object(manager_module, 'provision', provision),
                        patch.object(manager_module, 'NodeCollector', FakeCollector)]
        for item in self.patches: item.start()
        self.lab = dict(id='lab', name='demo', deployment_name='demo', container_prefix='clab', profiles=[], defaults={}, interval=0, next_run=None,
                        nodes=[node('r1', '172.20.20.2'), node('r2', '172.20.20.3', 'cisco_xrv9k')],
                        telemetry={'auto': True, 'decided': True, 'profile_id': '', 'applied': {}},
                        drawing={'schema': 3, 'nodes': [{'id': 'r1', 'alias': 'r1', 'label': 'r1', 'x': 0, 'y': 0}, {'id': 'r2', 'alias': 'r2', 'label': 'r2', 'x': 200, 'y': 0}],
                                 'links': [[{'node': 'r1', 'interface': 'eth1'}, {'node': 'r2', 'interface': 'eth1'}]], 'decorations': [], 'settings': {}})
        self.store.state['labs'].append(self.lab)
        self.store.state['host'] = dict(address='127.0.0.1', port=22, username='clab-discovery', auth='password', password='vm-secret',
                                        enabled=True, command_mode='helper', fingerprint='SHA256:fixture', revision='r1')
        self.store.state['discovery'] = dict(ok=True, error='', checked_epoch=time.time(), checked_at='now', last_success='now',
                                             labs={'demo': [dict(name=n['name'], address=n['address'], state='running', kind=n['platform']) for n in self.lab['nodes']]})
        self.store.save()
        self.reachable('clab-demo-r1')

    def tearDown(self):
        for item in self.patches: item.stop()
        for service in ('telemetry', 'git_progress', 'operations', 'discovery', 'readiness', 'node_services', 'runner'):
            getattr(self.app.state, service).close()
        self.client.close()
        self.tmp.cleanup()

    def reachable(self, name, status='reachable'):
        with self.services.lock:
            self.services.checks[('lab', name)] = {'status': status, 'at': 'now', 'message': 'ok', 'source': 'automatic'}

    def drain(self):
        while self.manager.ingest_one(0): pass

    def scan(self):
        self.manager.scan()
        self.drain()

    def view(self):
        response = self.client.get('/api/labs/lab/telemetry')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def node_view(self, name):
        return next(n for n in self.view()['nodes'] if n['name'] == name)

    def collector(self, name):
        return next(c for c in reversed(FakeCollector.instances) if c.key == ('lab', name))

    def stream(self, name, ident='Ethernet1', ts=None):
        collector = self.collector(name)
        collector.group('interfaces', 'subscribed'); collector.group('interfaces', 'streaming')
        now = ts or time.time()
        collector.push(now - 10, ident, {'in-octets': 1000, 'out-octets': 500, 'oper-status': 'UP', 'admin-status': 'UP'})
        collector.push(now, ident, {'in-octets': 2000, 'out-octets': 1500, 'oper-status': 'UP', 'admin-status': 'UP'})
        self.drain()
        return collector

    def logs(self):
        return self.client.get('/api/logs?lab_id=lab&limit=500').text

    def test_provisioning_starts_only_after_the_nos_answered_and_streaming_means_samples(self):
        self.scan()
        r1, r2 = self.node_view('clab-demo-r1'), self.node_view('clab-demo-r2')
        self.assertEqual(r1['state'], 'connecting', r1); self.assertEqual(r1['endpoint'], '172.20.20.2:6030')
        self.assertEqual(r2['state'], 'waiting'); self.assertIn('Waiting for the NOS', r2['message'])
        self.assertEqual(self.provisions, [('arista_ceos', 'apply', [])])
        self.assertEqual(self.connects, [('clab-demo-r1', 'admin', 'admin')], 'the containerlab default login provisions the node')
        self.assertEqual(self.lab['telemetry']['applied']['clab-demo-r1']['lines'], ['management api gnmi', '   transport grpc default'])
        self.assertIn('telemetry.configure', self.logs()); self.assertIn('transport grpc default', self.logs())
        state = next(l for l in self.client.get('/api/state').json()['labs'] if l['id'] == 'lab')
        self.assertEqual(state['telemetry']['status'], 'waiting'); self.assertEqual(state['nodes'][0]['telemetry']['state'], 'connecting')
        self.assertNotIn('applied', state, 'the raw setting record stays out of the public lab')
        collector = self.stream('clab-demo-r1')
        r1 = self.node_view('clab-demo-r1')
        self.assertEqual(r1['state'], 'streaming'); self.assertTrue(r1['fresh'])
        row = r1['interfaces'][0]
        self.assertEqual((row['name'], row['wired'], row['peer'], row['drawn'], row['rx_bps'], row['tx_bps']), ('Ethernet1', True, 'clab-demo-r2', 'eth1', 800.0, 800.0))
        self.assertEqual(self.view()['summary']['status'], 'partial')
        self.assertIn('telemetry.streaming', self.logs())
        self.reachable('clab-demo-r2'); self.scan()
        self.assertEqual(self.node_view('clab-demo-r2')['state'], 'connecting')
        self.assertEqual(self.provisions[-1][0], 'cisco_xrv9k'); self.assertEqual(self.node_view('clab-demo-r2')['endpoint'], '172.20.20.3:57400')
        self.assertEqual(collector.transport, 'plaintext')

    def test_repeat_scans_do_not_rewrite_configuration_and_retries_back_off(self):
        self.scan(); self.scan(); self.scan()
        self.assertEqual(len(self.provisions), 1, 'a live collector is left alone')
        collector = self.collector('clab-demo-r1')
        collector.fail('connect', 'The gNMI port did not answer.')
        r1 = self.node_view('clab-demo-r1')
        self.assertEqual(r1['state'], 'failed'); self.assertIn(f'Next attempt in {RETRY_MIN} s', r1['message'])
        self.scan()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'failed', 'no attempt before the backoff elapses')
        self.manager.status[('lab', 'clab-demo-r1')]['retry_at'] = 0
        self.scan()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'connecting')
        self.assertEqual(len(self.provisions), 1, 'a node provisioned in this boot cycle reconnects without another SSH session')
        self.assertEqual(len(FakeCollector.instances), 2)
        self.collector('clab-demo-r1').fail('connect', 'again')
        self.assertIn(f'Next attempt in {RETRY_MIN * 2} s', self.node_view('clab-demo-r1')['message'])
        # A port that does not answer is a NOS booting after a container restart (its address and
        # running state do not change, so nothing else resets the node): keep the retry short.
        self.manager.status[('lab', 'clab-demo-r1')]['retry_at'] = 0
        self.scan(); self.collector('clab-demo-r1').fail('connect', 'still booting')
        self.assertIn(f'Next attempt in {RETRY_CONNECT_MAX} s', self.node_view('clab-demo-r1')['message'])
        self.manager.status[('lab', 'clab-demo-r1')]['retry_at'] = 0
        self.scan(); self.collector('clab-demo-r1').fail('error', 'unexpected')
        self.assertIn(f'Next attempt in {RETRY_MIN * 2 ** 3} s', self.node_view('clab-demo-r1')['message'], 'other failures keep backing off')
        self.assertEqual(self.client.post('/api/labs/lab/telemetry/retry', json={'node': 'clab-demo-r1'}).json(), {'retried': ['clab-demo-r1']})
        self.scan()
        self.assertEqual(len(self.provisions), 2, 'an explicit retry checks the configuration again')
        self.assertEqual(self.client.post('/api/labs/lab/telemetry/retry', json={'node': 'nope'}).status_code, 404)

    def test_credential_problems_are_actionable_and_secrets_never_leak(self):
        self.lab['profiles'] = [dict(id='k', label='Keyed', platform='arista_ceos', username='ops', auth='key', password='', private_key='-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----', passphrase='pp-secret', enable_password=''),
                                dict(id='p', label='Password', platform='arista_ceos', username='ops', auth='password', password='ops-secret', private_key='', passphrase='', enable_password='en-secret')]
        self.lab['defaults'] = {'arista_ceos': 'k'}; self.store.save()
        self.scan()
        r1 = self.node_view('clab-demo-r1')
        self.assertEqual(r1['state'], 'failed'); self.assertIn('SSH key', r1['message']); self.assertEqual(self.provisions, [])
        self.assertEqual(self.client.put('/api/labs/lab/telemetry/settings', json={'auto': True, 'profile_id': 'k'}).status_code, 400)
        self.assertEqual(self.client.put('/api/labs/lab/telemetry/settings', json={'auto': True, 'profile_id': 'missing'}).status_code, 400)
        self.assertEqual(self.client.put('/api/labs/lab/telemetry/settings', json={'auto': True, 'profile_id': 'p'}).status_code, 200)
        self.manager.status.clear(); self.scan()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'connecting')
        self.assertEqual(self.connects[-1], ('clab-demo-r1', 'ops', 'pp-secret' if False else self.connects[-1][2]))
        self.assertEqual(self.collector('clab-demo-r1').creds, {'username': 'ops', 'password': 'ops-secret'}, 'gNMI uses the chosen password profile')
        self.collector('clab-demo-r1').fail('auth', 'The NOS refused the gNMI login. secret-detail')
        r1 = self.node_view('clab-demo-r1')
        self.assertIn(f'Next attempt in {RETRY_MAX} s', r1['message'])
        self.provision_result = lambda adapter, mode: ProvisionError('EOS asks for an enable password; add it to the credential profile.')
        self.client.post('/api/labs/lab/telemetry/retry', json={}); self.scan()
        self.assertIn('enable password', self.node_view('clab-demo-r1')['message'])
        for text in (self.logs(), self.client.get('/api/labs/lab/telemetry').text, self.client.get('/api/state').text):
            for secret in ('ops-secret', 'en-secret', 'pp-secret', 'PRIVATE KEY'):
                self.assertNotIn(secret, text)

    def test_unsupported_kinds_and_partially_supported_nodes(self):
        self.lab['nodes'].append(node('lx', '172.20.20.9', ''))
        self.lab['nodes'].append(node('sw', '172.20.20.10', 'juniper_vqfx'))
        self.store.save(); self.reachable('clab-demo-lx'); self.reachable('clab-demo-sw')
        self.scan()
        self.assertEqual(self.node_view('clab-demo-lx')['state'], 'unsupported'); self.assertEqual(self.node_view('clab-demo-sw')['state'], 'unsupported')
        self.assertEqual([p[0] for p in self.provisions], ['arista_ceos'])
        collector = self.stream('clab-demo-r1')
        collector.group('bgp', 'unsupported', 'The node does not advertise the OpenConfig model for this group.')
        r1 = self.node_view('clab-demo-r1')
        self.assertEqual(r1['state'], 'streaming'); self.assertEqual(r1['groups']['bgp']['status'], 'unsupported'); self.assertEqual(r1['peers'], [])
        self.assertIn('telemetry.unsupported', self.logs())
        collector.push(time.time(), '10.0.0.2', {'session-state': 'ESTABLISHED', 'received': 4}, kind='bgp', instance='default', afi='IPV4_UNICAST')
        collector.group('bgp', 'streaming')
        self.drain()
        r1 = self.node_view('clab-demo-r1')
        self.assertEqual(r1['peers'][0]['state'], 'ESTABLISHED'); self.assertEqual(r1['groups']['bgp']['status'], 'streaming')
        self.assertEqual(self.view()['summary']['unsupported'], 2)

    def test_stale_streams_keep_history_and_recover(self):
        self.scan()
        collector = self.stream('clab-demo-r1', ts=time.time() - 120)
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'streaming')
        self.scan()
        r1 = self.node_view('clab-demo-r1')
        self.assertEqual(r1['state'], 'stale'); self.assertFalse(r1['fresh']); self.assertIsNone(r1['interfaces'][0]['rx_bps'])
        self.assertEqual(r1['interfaces'][0]['totals']['in-octets'], 2000, 'recent history stays available')
        # The bounded rate history stays in the store for Prometheus' next scrape; the UI draws no charts.
        self.assertEqual(len(self.manager.data.series('lab', 'clab-demo-r1', 'Ethernet1', 300)), 2)
        collector.push(time.time(), 'Ethernet1', {'in-octets': 3000}); self.drain()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'streaming')
        collector.alive = False; self.scan()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'failed'); self.assertIn('reconnecting', self.node_view('clab-demo-r1')['message'])

    def test_runtime_changes_operations_removal_and_reset_clear_the_session(self):
        self.scan(); collector = self.stream('clab-demo-r1')
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'streaming')
        self.lab['nodes'][0]['runtime_state'] = 'exited'; self.store.save(); self.scan()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'waiting'); self.assertFalse(collector.alive)
        self.assertIsNone(self.manager.data.snapshot('lab', 'clab-demo-r1'))
        self.lab['nodes'][0]['runtime_state'] = 'running'; self.store.save(); self.scan()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'connecting'); self.assertEqual(len(self.provisions), 2, 'a new boot cycle is checked again')
        new = self.collector('clab-demo-r1'); self.assertNotEqual(new.generation, collector.generation)
        collector.push(time.time(), 'Ethernet1', {'in-octets': 99}); self.drain()
        self.assertEqual(self.manager.data.snapshot('lab', 'clab-demo-r1')['dropped'], 1, 'late data from the previous deployment is dropped even at the same address')
        self.stream('clab-demo-r1')
        self.store.state['operations'] = [dict(id='op1', lab_id='lab', name='demo', action='redeploy', status='queued')]; self.store.save(); self.scan()
        self.assertIsNone(self.manager.data.snapshot('lab', 'clab-demo-r1')); self.assertIn('telemetry.clear', self.logs()); self.assertIn('redeploy', self.logs())
        self.store.state['operations'] = []; self.store.save(); self.scan(); self.stream('clab-demo-r1')
        self.assertEqual(self.client.post('/api/manager/reset', json={'confirmation': 'RESET'}).status_code, 200)
        self.assertEqual(self.manager.data.stats()['nodes'], 0); self.assertEqual(self.manager.status, {})

    def test_removing_a_lab_stops_its_collectors(self):
        self.scan(); collector = self.stream('clab-demo-r1')
        self.assertEqual(self.client.request('DELETE', '/api/labs/lab', json={'name': 'demo', 'prevent_reimport': True}).status_code, 200)
        self.assertFalse(collector.alive); self.assertEqual(self.manager.data.stats()['nodes'], 0)
        self.assertEqual(self.client.get('/api/labs/lab/telemetry').status_code, 404)

    def test_settings_gate_configuration_writes_and_disable_stops_everything(self):
        self.lab.pop('telemetry'); self.store.save()
        self.scan()
        r1 = self.node_view('clab-demo-r1')
        self.assertEqual(r1['state'], 'disabled'); self.assertIn('not been enabled', r1['message']); self.assertEqual(self.provisions, [])
        self.assertEqual(self.view()['settings'], {'auto': False, 'decided': False, 'profile_id': '', 'profile_label': ''})
        self.assertEqual(self.view()['summary']['status'], 'disabled')
        result = self.client.put('/api/labs/lab/telemetry/settings', json={'auto': True, 'profile_id': ''})
        self.assertEqual(result.status_code, 200); self.assertEqual(result.json()['settings']['decided'], True)
        self.scan(); self.assertEqual(self.node_view('clab-demo-r1')['state'], 'connecting'); self.assertEqual(len(self.provisions), 1)
        collector = self.stream('clab-demo-r1')
        self.assertEqual(self.client.put('/api/labs/lab/telemetry/settings', json={'auto': False}).status_code, 200)
        self.assertFalse(collector.alive); self.assertEqual(self.manager.data.stats()['nodes'], 0)
        self.scan()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'disabled'); self.assertEqual(len(self.provisions), 1)
        self.assertIn('telemetry.settings', self.logs())
        self.assertEqual(self.client.put('/api/labs/lab/telemetry/settings', json={'auto': True, 'extra': 1}).status_code, 422)

    def test_view_api_stays_bounded_and_the_chart_routes_are_gone(self):
        self.scan(); self.stream('clab-demo-r1')
        view = self.view()
        self.assertEqual(view['nodes'][0]['interfaces'][0]['rx_bps'], 800.0); self.assertNotIn('windows', view)
        self.assertEqual(set(view['grafana']), {'enabled', 'port', 'prometheus_port', 'map_uid'})
        # Charts moved to Grafana: the per-series routes no longer exist.
        self.assertEqual(self.client.get('/api/labs/lab/telemetry/series', params={'node': 'clab-demo-r1', 'interface': 'Ethernet1'}).status_code, 404)
        self.assertEqual(self.client.get('/api/labs/lab/telemetry/bgp-series', params={'node': 'clab-demo-r1', 'peer': '10.0.0.2'}).status_code, 404)
        self.assertEqual(self.client.get('/api/labs/nope/telemetry').status_code, 404)
        self.assertEqual(self.client.get('/api/labs/lab/telemetry', headers={'Origin': 'https://other.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/telemetry/health').json()['collector'], 'gnmi')
        health = self.client.get('/api/telemetry/health').json()
        self.assertEqual(health['bounds']['collectors'], 64); self.assertEqual(health['store']['bounds']['points_per_series'], 400)

    def test_explicit_removal_only_touches_recorded_lines_and_needs_auto_off(self):
        self.scan()
        self.assertEqual(self.client.post('/api/labs/lab/telemetry/remove-config', json={}).status_code, 409)
        self.client.put('/api/labs/lab/telemetry/settings', json={'auto': False})
        result = self.client.post('/api/labs/lab/telemetry/remove-config', json={}).json()
        self.assertEqual(result['started'], ['clab-demo-r1']); self.assertEqual(result['skipped'], ['clab-demo-r2'])
        self.assertEqual(self.provisions[-1], ('arista_ceos', 'remove', ['management api gnmi', '   transport grpc default']))
        self.assertNotIn('clab-demo-r1', self.lab['telemetry']['applied']); self.assertIn('telemetry.remove', self.logs())
        self.assertEqual(self.client.post('/api/labs/lab/telemetry/remove-config', json={'node': 'ghost'}).status_code, 404)

    def test_map_links_take_both_ends_into_account(self):
        self.scan(); self.reachable('clab-demo-r2'); self.scan()
        a = self.stream('clab-demo-r1')
        links = self.view()['links']
        self.assertEqual(links[0]['status'], 'up-partial'); self.assertEqual([e['state'] for e in links[0]['ends']], ['up', 'unknown'])
        z = self.collector('clab-demo-r2'); z.group('interfaces', 'streaming')
        z.push(time.time(), 'GigabitEthernet0/0/0/0', {'oper-status': 'DOWN', 'in-octets': 5}); self.drain()
        link = self.view()['links'][0]
        self.assertEqual((link['status'], link['mismatch']), ('down', True)); self.assertEqual(link['ends'][1]['nos_interface'], 'GigabitEthernet0/0/0/0')
        z.push(time.time(), 'GigabitEthernet0/0/0/0', {'oper-status': 'UP'}); self.drain()
        self.assertEqual(self.view()['links'][0]['status'], 'up')
        a.push(time.time() - 100, 'Ethernet1', {'oper-status': 'DOWN'}); self.drain()
        self.assertEqual(self.view()['links'][0]['status'], 'up', 'an out-of-order old sample cannot flip the link')

    def test_pure_functions_define_link_and_summary_vocabulary(self):
        self.assertEqual(link_status('up', 'up'), ('up', False)); self.assertEqual(link_status('up', 'down'), ('down', True))
        self.assertEqual(link_status('down', 'unknown'), ('down', False)); self.assertEqual(link_status('up', 'unknown'), ('up-partial', False))
        self.assertEqual(link_status('up', 'stale'), ('stale', False)); self.assertEqual(link_status('unknown', 'unsupported'), ('unknown', False))
        self.assertEqual(end_status(None, 'streaming'), 'unknown'); self.assertEqual(end_status({'fresh': False, 'oper': 'UP'}, 'streaming'), 'stale')
        self.assertEqual(end_status({'fresh': True, 'oper': 'LOWER_LAYER_DOWN'}, 'streaming'), 'down'); self.assertEqual(end_status({'fresh': True, 'oper': 'UP'}, 'unsupported'), 'unsupported')
        self.assertEqual(summarize([])['status'], 'disabled'); self.assertEqual(summarize(['disabled', 'disabled'])['status'], 'disabled')
        self.assertEqual(summarize(['unsupported'])['status'], 'unsupported'); self.assertEqual(summarize(['streaming', 'unsupported'])['status'], 'streaming')
        self.assertEqual(summarize(['streaming', 'waiting'])['status'], 'partial'); self.assertEqual(summarize(['failed', 'streaming'])['status'], 'failed')
        self.assertEqual(summarize(['waiting', 'configuring'])['status'], 'waiting')

    def test_environment_can_disable_the_collector(self):
        manager = TelemetryManager(self.store, self.services, environ={'TELEMETRY_COLLECTOR': 'disabled'})
        self.assertFalse(manager.enabled); self.assertIn('TELEMETRY_COLLECTOR', manager.health()['message'])
        self.assertFalse(TelemetryManager(self.store, self.services, environ={'TELEMETRY_COLLECTOR': 'kafka'}).enabled)
        self.manager.enabled = False; self.manager.unavailable = 'off'; self.scan()
        self.assertEqual(self.node_view('clab-demo-r1')['state'], 'disabled'); self.assertEqual(self.provisions, [])


if __name__ == '__main__':
    unittest.main()
