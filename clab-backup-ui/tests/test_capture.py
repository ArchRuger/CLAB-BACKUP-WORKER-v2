"""Capture contract, trust boundary and stale-selection regression tests."""
import copy
import io
import json
from http.client import BadStatusLine
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from app.main import create_app
from app.capture import (CaptureError, EdgesharkProvider, MAX_RESPONSE, NoRedirect,
                         configured_provider, normalize_targets, read_discovery, service_url)


def fixture():
    # Synthetic payload following Siemens Ghostwire api/v1/targets.go, not user data.
    return {'metadata': {'creator-id': 'fixture'}, 'containers': [
        {'name': 'clab-demo-r1', 'type': 'docker', 'prefix': '', 'netns': 4026532100,
         'pid': 42, 'starttime': 12345, 'network-interfaces': ['lo', 'eth0', 'eth2']},
        {'name': 'init', 'type': 'proc', 'prefix': '', 'netns': 4026531992,
         'pid': 1, 'starttime': 1, 'network-interfaces': ['lo', 'ens18', 'br-test', 'vxlan10']},
        {'name': '/run/netns/test', 'type': 'bindmount', 'prefix': '', 'netns': 4026532300,
         'pid': 0, 'starttime': 0, 'network-interfaces': ['veth1']},
    ]}


class CaptureContractTests(unittest.TestCase):
    def test_optional_configuration_and_url_validation(self):
        self.assertIsNone(configured_provider({}))
        for config in [{'CAPTURE_PROVIDER': 'bogus'}, {'CAPTURE_PROVIDER': 'edgeshark'}]:
            with self.assertRaises(CaptureError): configured_provider(config)
        for url in ['file:///etc/passwd', '//host', 'http://user:secret@host', 'http://host?x=1',
                    'http://host/#x', 'http://host:0', 'http://host:65536', 'http://host:',
                    'http://host\\evil', 'http://host/\nfoo']:
            with self.subTest(url=url), self.assertRaises(CaptureError): service_url(url)
        self.assertEqual(service_url('https://[2001:db8::1]:8443/edgeshark'), 'https://[2001:db8::1]:8443/edgeshark/')

    def test_normalized_contract_preserves_every_namespace_type_and_interface(self):
        value=fixture();value['containers'][0]['future-extension']={'ignored': True}
        rows=normalize_targets(value)
        self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['network-interfaces'],['eth0','eth2','lo'])
        self.assertNotIn('future-extension',rows[0])
        self.assertEqual(rows[2]['pid'],0)

    def test_malformed_payload_fails_closed(self):
        for value in [[], {}, {'containers': {}}, {'containers': [None]}]:
            with self.assertRaises(CaptureError): normalize_targets(value)
        for key,value in [('netns',0),('pid',True),('starttime',-1),('name',''),
                          ('network-interfaces',['Gi0/0/0/1']),('network-interfaces',['a\nb']),
                          ('network-interfaces',['x'*16]),('network-interfaces',['\ud800']),('network-interfaces',None)]:
            data=fixture();data['containers'][0][key]=value
            with self.subTest(key=key,value=value), self.assertRaises(CaptureError): normalize_targets(data)

    def test_url_matches_upstream_packetflix_contract_and_encodes_special_characters(self):
        target=normalize_targets(fixture())[0];target['name']='name&"<>=?';target['prefix']='engine/x'
        provider=EdgesharkProvider('http://internal:5001','https://[2001:db8::1]:8443/edge/')
        uri=provider.launch(target,['eth0','eth2'])
        self.assertTrue(uri.startswith('packetflix:wss://[2001:db8::1]:8443/edge/capture?'))
        query=parse_qs(urlsplit(uri[len('packetflix:'):]).query)
        detail=json.loads(query['container'][0])
        self.assertEqual(detail,{**target,'network-interfaces':['eth0','eth2']})
        self.assertEqual(query['nif'],['eth0/eth2'])
        self.assertNotIn('internal',uri)

    def test_no_redirects(self):
        with self.assertRaises(CaptureError): NoRedirect().redirect_request(None,None,302,'',{},'http://other/')

    def test_http_errors_do_not_expose_upstream_text(self):
        for failure in [URLError('secret upstream output'), BadStatusLine('secret malformed HTTP')]:
            with patch('app.capture.build_opener') as opener:
                opener.return_value.open.side_effect=failure
                with self.assertRaisesRegex(CaptureError,'Cannot read Edgeshark') as error:
                    read_discovery('http://example/discover/mobyshark')
                self.assertNotIn('secret',str(error.exception))

    def test_response_bytes_and_time_are_bounded(self):
        for content,clock in [(b' '*(MAX_RESPONSE+1),0),(b'{}',13)]:
            stream=io.BufferedReader(io.BytesIO(content))
            with patch('app.capture.build_opener') as opener, patch('app.capture.time.monotonic',side_effect=[0]+[clock]*100):
                opener.return_value.open.return_value=stream
                with self.assertRaises(CaptureError): read_discovery('http://example/')

    def test_actual_http_transport_uses_discovery_path_and_rejects_redirects(self):
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                requests.append((self.path, dict(self.headers)))
                if self.path == '/redirect/':
                    self.send_response(302);self.send_header('Location','/secret');self.end_headers();return
                body=json.dumps(fixture()).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            provider=EdgesharkProvider(base+'/edge','http://workstation:5001')
            self.assertEqual(len(provider.discover()),3)
            self.assertEqual(requests[0][0],'/edge/discover/mobyshark')
            self.assertNotIn('Authorization',requests[0][1]);self.assertNotIn('Cookie',requests[0][1])
            with self.assertRaisesRegex(CaptureError,'redirected'): read_discovery(base+'/redirect/')
            self.assertEqual(len(requests),2)
        finally: server.shutdown();server.server_close();thread.join(timeout=2)


class CaptureAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        with patch.dict('os.environ',{'CAPTURE_PROVIDER':'disabled'}): self.app=create_app(self.tmp.name)
        self.client=TestClient(self.app)
        self.captures=self.app.state.captures
        self.lab={'id':'lab','name':'demo','deployment_name':'demo','container_prefix':'clab',
                  'nodes':[{'name':'r1','definition_node':'r1'}]}
        self.app.state.store.state['labs'].append(self.lab)
        self.captures.provider=EdgesharkProvider('http://internal:5001','http://localhost:5001')
        self.payload=fixture()
        self.reader=patch('app.capture.read_discovery',side_effect=lambda url: copy.deepcopy(self.payload))
        self.reader.start()

    def tearDown(self):
        self.reader.stop();self.client.close();self.app.state.runner.close()
        self.app.state.node_services.close();self.app.state.git_progress.close()
        self.app.state.operations.close();self.app.state.discovery.close();self.tmp.cleanup()

    def selection(self):
        r=self.client.get('/api/capture/targets?lab_id=lab&node=r1')
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(r.json()['targets']),1)
        return {'target_id':r.json()['targets'][0]['id'],'interfaces':['eth2']}

    def test_live_discovery_and_launch_keep_backup_state_unchanged(self):
        before=copy.deepcopy(self.app.state.store.state)
        data=self.selection();r=self.client.post('/api/capture/launch',json=data)
        self.assertEqual(r.status_code,200,r.text)
        detail=json.loads(parse_qs(urlsplit(r.json()['uri'][len('packetflix:'):]).query)['container'][0])
        self.assertEqual(detail['network-interfaces'],['eth2'])
        self.assertEqual(detail['pid'],42);self.assertEqual(detail['starttime'],12345)
        self.assertEqual(self.app.state.store.state,before)

    def test_all_host_targets_include_host_and_processless_namespaces(self):
        r=self.client.get('/api/capture/targets')
        self.assertEqual({t['kind'] for t in r.json()['targets']},{'docker','proc','bindmount'})

    def test_filters_validate_lab_and_node_and_do_not_use_substrings(self):
        self.payload['containers'][0]['name']='clab-demo-r10'
        self.assertEqual(self.client.get('/api/capture/targets?lab_id=lab&node=r1').json()['targets'],[])
        self.assertEqual(self.client.get('/api/capture/targets?lab_id=missing').status_code,404)
        self.assertEqual(self.client.get('/api/capture/targets?lab_id=lab&node=missing').status_code,404)
        self.assertEqual(self.client.get('/api/capture/targets?node=r1').status_code,400)

    def test_custom_and_empty_container_prefix(self):
        for prefix,expected in [('custom','custom-demo-r1'),('','r1')]:
            self.lab['container_prefix']=prefix;self.payload['containers'][0]['name']=expected
            self.selection()

    def test_restart_disappearance_interface_change_and_forgery_rejected(self):
        for field,value in [('netns',99),('pid',99),('starttime',999),('prefix','other'),('network-interfaces',['lo'])]:
            self.payload=fixture();data=self.selection();self.payload['containers'][0][field]=value
            self.assertEqual(self.client.post('/api/capture/launch',json=data).status_code,409)
        self.payload=fixture();data=self.selection();self.payload['containers']=[]
        self.assertEqual(self.client.post('/api/capture/launch',json=data).status_code,409)
        data['target_id']='f'*64
        self.assertEqual(self.client.post('/api/capture/launch',json=data).status_code,409)

    def test_interface_selection_and_arbitrary_payloads_rejected(self):
        data=self.selection()
        for interfaces in [['eth2','eth2'],['eth99'],['eth2;sh']]:
            self.assertEqual(self.client.post('/api/capture/launch',json={**data,'interfaces':interfaces}).status_code,409)
        for fields in [{'interfaces':[]},{'url':'http://evil'},{'netns':1},{'command':'sh'},{'target_id':'é'*64}]:
            self.assertEqual(self.client.post('/api/capture/launch',json={**data,**fields}).status_code,422)

    def test_cross_origin_launch_is_blocked(self):
        data=self.selection()
        self.assertEqual(self.client.post('/api/capture/launch',json=data,headers={'Origin':'https://evil.example'}).status_code,403)

    def test_provider_failure_is_isolated_and_disabled_does_no_network_io(self):
        self.captures.provider=None
        self.assertFalse(self.client.get('/api/capture/status').json()['enabled'])
        self.assertEqual(self.client.get('/api/capture/targets').status_code,503)
        self.captures.provider=EdgesharkProvider('http://host','http://host')
        self.payload={}
        self.assertEqual(self.client.get('/api/capture/targets').status_code,502)
        self.assertEqual(self.client.get('/').status_code,200)

    def test_concurrent_discovery_is_bounded(self):
        for _ in range(4): self.captures.slots.acquire()
        try:self.assertEqual(self.client.get('/api/capture/targets').status_code,429)
        finally:
            for _ in range(4): self.captures.slots.release()

    def test_same_container_name_in_multiple_engines_requires_explicit_choice(self):
        other=copy.deepcopy(self.payload['containers'][0]);other.update(prefix='nested',netns=1234)
        self.payload['containers'].append(other)
        rows=self.client.get('/api/capture/targets?lab_id=lab').json()['targets']
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id'])
