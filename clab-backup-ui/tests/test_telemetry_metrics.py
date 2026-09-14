"""Prometheus exposition of the session store: format, escaping, freshness, and the endpoint."""
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from app.main import create_app
from app.telemetry_metrics import escape, labels, render

NOW = 1_757_764_800.0


def view(**overrides):
    base = {'lab_id': 'lab', 'lab_name': 'demo', 'links': [], 'nodes': [{
        'name': 'clab-demo-r1', 'short_name': 'r1', 'platform': 'arista_ceos', 'state': 'streaming', 'last_sample': NOW - 3,
        'interfaces': [{'name': 'Ethernet1', 'oper': 'UP', 'admin': 'UP', 'at': NOW - 3, 'fresh': True, 'rx_bps': 800.0, 'tx_bps': None,
                        'rx_pps': 1, 'tx_pps': 2.5, 'totals': {'in-errors': 0, 'in-octets': 5}, 'peer': 'r2', 'peer_interface': 'eth1', 'role': 'physical'},
                       {'name': 'Management0', 'oper': 'DOWN', 'admin': 'UP', 'at': NOW - 70, 'fresh': False, 'rx_bps': 5.0, 'tx_bps': 5.0,
                        'rx_pps': None, 'tx_pps': None, 'totals': {'in-octets': 9}, 'peer': '', 'peer_interface': '', 'role': 'management'}],
        'peers': [{'peer': '10.0.0.2', 'instance': 'default', 'afi': 'IPV4_UNICAST', 'state': 'ESTABLISHED', 'received': 12, 'sent': None, 'fresh': True}]}]}
    base.update(overrides)
    return base


class RenderTests(unittest.TestCase):
    def test_families_are_typed_and_label_values_escaped(self):
        text = render([view(lab_name='de"mo\\\n')], NOW)
        self.assertIn('# TYPE clab_interface_receive_bits_per_second gauge', text)
        self.assertIn('# TYPE clab_interface_receive_errors_total counter', text)
        self.assertIn('lab="de\\"mo\\\\\\n"', text)
        self.assertEqual(escape('a"b\\c\nd'), 'a\\"b\\\\c\\nd')
        self.assertEqual(labels(a='x', b='', c=None), '{a="x"}')
        self.assertTrue(text.endswith('\n'))
        self.assertEqual(len([l for l in text.splitlines() if l.startswith('# HELP clab_interface_receive_bits_per_second')]), 1, 'one HELP line per family')

    def test_stale_interfaces_keep_state_but_drop_rates_and_counters(self):
        text = render([view()], NOW)
        self.assertIn('clab_interface_oper_up{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos",interface="Management0",role="management"} 0', text)
        self.assertNotIn('receive_bits_per_second{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos",interface="Management0"', text)
        self.assertNotIn('receive_bytes_total{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos",interface="Management0"', text)
        self.assertIn('interface="Ethernet1",peer="r2",peer_interface="eth1",role="physical"} 800.0', text)
        self.assertNotIn('transmit_bits_per_second{lab="demo",lab_id="lab",node="r1"', text, 'an unavailable rate is absent, never zero')
        self.assertIn('clab_interface_transmit_packets_per_second{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos",interface="Ethernet1",peer="r2",peer_interface="eth1",role="physical"} 2.5', text)
        self.assertIn('clab_interface_sample_age_seconds{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos",interface="Management0",role="management"} 70.0', text)

    def test_node_bgp_and_link_series(self):
        links = [{'status': 'up', 'ends': [{'label': 'r1', 'interface': 'eth1'}, {'label': 'r2', 'interface': 'eth1'}]},
                 {'status': 'unknown', 'ends': [{'label': 'r1', 'interface': 'eth2'}, {'label': 'r3', 'interface': 'eth5'}]}]
        text = render([view(links=links)], NOW)
        self.assertIn('clab_telemetry_node_state{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos",state="streaming"} 1', text)
        self.assertIn('clab_telemetry_node_sample_age_seconds{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos"} 3.0', text)
        self.assertIn('clab_telemetry_node_state_code{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos"} 3', text, 'streaming = 3 for the lab map')
        self.assertIn('clab_telemetry_node_state_code{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos"} -1',
                      render([view(nodes=[dict(view()['nodes'][0], state='failed')])], NOW))
        self.assertIn('clab_bgp_neighbor_established{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos",neighbor="10.0.0.2",instance="default",afi="IPV4_UNICAST"} 1', text)
        self.assertIn('clab_bgp_neighbor_prefixes_received{', text); self.assertNotIn('clab_bgp_neighbor_prefixes_sent{', text)
        self.assertIn('clab_link_status{lab="demo",lab_id="lab",a_node="r1",a_interface="eth1",z_node="r2",z_interface="eth1",status="up"} 1', text)
        self.assertIn('clab_link_up{lab="demo",lab_id="lab",a_node="r1",a_interface="eth1",z_node="r2",z_interface="eth1"} 1', text)
        self.assertNotIn('clab_link_up{lab="demo",lab_id="lab",a_node="r1",a_interface="eth2"', text, 'unknown links carry no up/down value')
        self.assertEqual(render([], NOW), '')


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.client = TestClient(self.app)
        store = self.app.state.store
        self.lab = dict(id='lab', name='demo', deployment_name='demo', container_prefix='clab', interval=0, next_run=None, defaults={'arista_ceos': 'p'},
                        profiles=[dict(id='p', label='Ops', platform='arista_ceos', username='ops', auth='password', password='ops-secret', private_key='', passphrase='', enable_password='')],
                        telemetry={'auto': True, 'decided': True, 'profile_id': '', 'applied': {'clab-demo-r1': {'lines': ['management api gnmi'], 'at': 'now', 'kind': 'arista_ceos'}}},
                        nodes=[dict(name='clab-demo-r1', short_name='r1', definition_node='r1', address='172.20.20.2', port=22, platform='arista_ceos', enabled=True, profile_id='',
                                    username='', password='', enable_password='', groups=[], endpoint_mode='auto', discovered=True, runtime_state='running', discovered_address='172.20.20.2')])
        store.state['labs'].append(self.lab); store.state['labs'].append(dict(self.lab, id='unlinked', name='inventory-only', deployment_name='', telemetry={}))
        store.save()
        manager = self.app.state.telemetry
        manager.data.begin('lab', 'clab-demo-r1', 'g1')
        now = time.time()
        for t, value in ((now - 10, 1000), (now, 2000)):
            manager.data.ingest(dict(lab_id='lab', node='clab-demo-r1', generation='g1', kind='interface', ident='Ethernet1', metric='in-octets', value=value, ts=t, method='gnmi-sample-10s'))
        manager.data.ingest(dict(lab_id='lab', node='clab-demo-r1', generation='g1', kind='interface', ident='Ethernet1', metric='oper-status', value='UP', ts=now, method='gnmi-sample-10s'))

    def tearDown(self):
        for service in ('telemetry', 'git_progress', 'operations', 'discovery', 'readiness', 'node_services', 'runner'):
            getattr(self.app.state, service).close()
        self.client.close(); self.tmp.cleanup()

    def test_endpoint_serves_prometheus_text_for_linked_labs_only_without_secrets(self):
        response = self.client.get('/api/telemetry/metrics')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['content-type'].startswith('text/plain; version=0.0.4'))
        self.assertIn('clab_interface_receive_bits_per_second{lab="demo",lab_id="lab",node="r1",container="clab-demo-r1",platform="arista_ceos",interface="Ethernet1",role="physical"} 800.0', response.text)
        self.assertNotIn('inventory-only', response.text); self.assertNotIn('172.20.20.2', response.text)
        for secret in ('ops-secret', 'management api gnmi', 'ops'):
            self.assertNotIn(secret + '"', response.text)
        self.assertEqual(self.client.get('/api/telemetry/metrics', headers={'Origin': 'https://other.example'}).status_code, 403)
        health = self.client.get('/api/telemetry/health').json()
        self.assertEqual(health['metrics_path'], '/api/telemetry/metrics'); self.assertEqual(health['grafana'], {'enabled': False, 'port': 3000, 'prometheus_port': 9090})
        # The lab header's Grafana link needs only these three values; no password, no Prometheus port.
        labs = {lab['id']: lab for lab in self.client.get('/api/state').json()['labs']}
        self.assertEqual(labs['lab']['telemetry']['grafana'], {'enabled': False, 'port': 3000, 'map_uid': ''})
        self.assertNotIn('grafana', str(labs['unlinked']['telemetry']))


if __name__ == '__main__':
    unittest.main()
