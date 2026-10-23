"""Capture contract, trust boundary and stale-selection regression tests."""
import copy
import hashlib
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

from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import create_app
from app.capture import (CaptureError, EdgesharkProvider, MAX_RESPONSE, NoRedirect,
                         configured_provider, normalize_targets, read_discovery, service_url)
from app.capture_sessions import BrowserSessions


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

    def test_malformed_shape_fails_closed_and_bad_rows_are_skipped_not_launchable(self):
        # A wrong response shape, or a list with no usable row, still fails closed.
        for value in [[], {}, {'containers': {}}, {'containers': [None]}, {'containers': [{'name': 'x'}]}]:
            with self.subTest(value=value), self.assertRaises(CaptureError): normalize_targets(value)
        # One malformed row must not hide every other namespace; it is dropped and counted.
        for key,value in [('netns',0),('pid',True),('starttime',-1),('name',''),
                          ('network-interfaces',['Gi0/0/0/1']),('network-interfaces',['a\nb']),
                          ('network-interfaces',['x'*16]),('network-interfaces',['\ud800']),('network-interfaces',None)]:
            data=fixture();data['containers'][0][key]=value;skipped=[]
            with self.subTest(key=key,value=value):
                rows=normalize_targets(data,skipped)
                self.assertEqual([r['name'] for r in rows],['init','/run/netns/test'])
                self.assertEqual(len(skipped),1)

    def test_shared_namespaces_merge_with_aliases_preferring_host_init(self):
        from app.capture import merge_shared_namespaces
        rows=normalize_targets(fixture())
        manager=dict(rows[0],name='containerlab-node-manager-backup-ui-1',netns=rows[1]['netns'],pid=4242,starttime=99)
        merged=merge_shared_namespaces(rows+[manager])
        host=next(t for t in merged if t['netns']==rows[1]['netns'])
        self.assertEqual((host['name'],host['type'],host['aliases']),('init','proc',['containerlab-node-manager-backup-ui-1']))
        self.assertEqual(len(merged),3)
        self.assertEqual([t['aliases'] for t in merged if t['netns']!=rows[1]['netns']],[[],[]])

    def test_url_matches_upstream_packetflix_contract_and_encodes_special_characters(self):
        target=normalize_targets(fixture())[0];target['name']='name&"<>=?';target['prefix']='engine/x'
        provider=EdgesharkProvider('https://[2001:db8::1]:8443/edge/')
        uri=provider.stream_uri(target,['eth0','eth2'])
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
            provider=EdgesharkProvider(base+'/edge')
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
        self.captures.provider=EdgesharkProvider('http://internal:5001')
        self.session_calls=[]
        class FakeSessions:
            def request(inner, method, path, who='', data=None):
                self.session_calls.append(data)
                return {'id':'a'*64}
        self.captures.sessions=FakeSessions()
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
        self.assertEqual(r.json()['url'],'/static/capture-session.html#'+'a'*64)
        self.assertNotIn('uri',r.json())
        detail=self.session_calls[-1]['target'];detail['network-interfaces']=self.session_calls[-1]['interfaces']
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
        for prefix,expected in [('custom','custom-demo-r1'),('','r1'),('__lab-name','demo-r1')]:
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
        self.captures.provider=EdgesharkProvider('http://host')
        self.payload={}
        self.assertEqual(self.client.get('/api/capture/targets').status_code,502)
        self.assertEqual(self.client.get('/').status_code,200)

    def test_concurrent_discovery_is_bounded(self):
        for _ in range(4): self.captures.slots.acquire()
        try:self.assertEqual(self.client.get('/api/capture/targets').status_code,429)
        finally:
            for _ in range(4): self.captures.slots.release()

    def test_unrelated_interface_changes_keep_a_selection_valid(self):
        # A new veth on the host (any container start) must not invalidate a selected
        # host-namespace target whose chosen interface is unchanged; only the selected
        # interfaces are checked against the fresh list.
        data=self.selection();self.payload['containers'][0]['network-interfaces'].append('eth9')
        self.assertEqual(self.client.post('/api/capture/launch',json=data).status_code,200)
        host=next(t for t in self.client.get('/api/capture/targets').json()['targets'] if t['name']=='init')
        self.payload['containers'][1]['network-interfaces'].append('veth9')
        self.assertEqual(self.client.post('/api/capture/launch',json={'target_id':host['id'],'interfaces':['ens18']}).status_code,200)
        self.payload['containers'][1]['network-interfaces'].remove('ens18')
        self.assertEqual(self.client.post('/api/capture/launch',json={'target_id':host['id'],'interfaces':['ens18']}).status_code,409)

    def test_host_view_lists_a_shared_namespace_once_and_launches_it(self):
        manager=copy.deepcopy(self.payload['containers'][0])
        manager.update(name='containerlab-node-manager-backup-ui-1',netns=self.payload['containers'][1]['netns'],pid=4242,starttime=99,
                       **{'network-interfaces':self.payload['containers'][1]['network-interfaces']})
        self.payload['containers'].append(manager)
        rows=self.client.get('/api/capture/targets').json()['targets']
        host=[t for t in rows if t['name'] in ('init','containerlab-node-manager-backup-ui-1')]
        self.assertEqual([(t['name'],t['aliases']) for t in host],[('init',['containerlab-node-manager-backup-ui-1'])])
        r=self.client.post('/api/capture/launch',json={'target_id':host[0]['id'],'interfaces':['ens18']})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['url'],'/static/capture-session.html#'+'a'*64)
        self.assertNotIn('uri',r.json())
        detail=self.session_calls[-1]['target'];detail['network-interfaces']=self.session_calls[-1]['interfaces']
        self.assertNotIn('aliases',detail);self.assertEqual(detail['name'],'init')
        # Lab and node views keep every container row so exact name matching still works.
        self.lab['nodes'].append({'name':'mgr','definition_node':'x'});self.lab['deployment_name']=''
        self.lab['nodes'][-1]['container_name']='containerlab-node-manager-backup-ui-1'
        names=[t['name'] for t in self.client.get('/api/capture/targets?lab_id=lab').json()['targets']]
        self.assertIn('containerlab-node-manager-backup-ui-1',names)

    def test_unreadable_rows_are_reported_in_the_message(self):
        self.payload['containers'][2]['name']=''
        data=self.client.get('/api/capture/targets').json()
        self.assertEqual(len(data['targets']),2)
        self.assertIn('1 discovered namespace(s) were unreadable',data['message'])

    def test_same_container_name_in_multiple_engines_requires_explicit_choice(self):
        other=copy.deepcopy(self.payload['containers'][0]);other.update(prefix='nested',netns=1234)
        self.payload['containers'].append(other)
        rows=self.client.get('/api/capture/targets?lab_id=lab').json()['targets']
        self.assertEqual(len(rows),2);self.assertNotEqual(rows[0]['id'],rows[1]['id'])


WHO='b'*64
OTHER='d'*64
SLOTS='All browser capture slots are in use. End a session or wait for expiry.'
LOST='Cannot reach the browser capture service. Check Capture setup and retry.'
STARTED='Wireshark session started on the VM. Open the browser viewer to inspect packets.'


class ScriptedService:
    """Stands in for capture_service.py at the adapter boundary (C07): owner-scoped rows, the global cap of
    four, idempotent ids derived as the service derives them, and scripted failures per POST /sessions."""
    def __init__(self):
        self.token='a'*64;self.rows={};self.calls=[];self.fail={};self.end_fail={};self.extra={};self.listing_extra=[]
        self.health={'ready':True,'max_sessions':4}

    def session_id(self,who,request_id):
        return BrowserSessions.session_id(self,who,request_id)

    def public(self,sid,row):
        return {'id':sid,'name':row['name'],'interfaces':list(row['interfaces']),'remaining_seconds':7000,'idle_seconds':900}

    def posts(self):
        return [c for c in self.calls if c[:2]==('POST','sessions')]

    def request(self,method,path,who='',data=None):
        self.calls.append((method,path,who,copy.deepcopy(data)))
        if path=='health':
            if isinstance(self.health,Exception):raise self.health
            return self.health
        if (method,path)==('GET','sessions'):
            return {'sessions':[{**self.public(s,r),**self.extra} for s,r in self.rows.items() if r['owner']==who]
                    +copy.deepcopy(self.listing_extra)}
        if (method,path)==('POST','sessions'):
            action=self.fail.get(len(self.posts()));sid=self.session_id(who,data['request_id'])
            if isinstance(action,Exception):raise action
            if action=='token':return {'id':'not-a-session'}
            if sid in self.rows:return self.public(sid,self.rows[sid])
            if len(self.rows)>=4:raise HTTPException(429,SLOTS)
            self.rows[sid]={'owner':who,'name':data['target']['name'],'interfaces':list(data['interfaces'])}
            if action=='lost':raise HTTPException(502,LOST)  # created, then the reply was lost
            return self.public(sid,self.rows[sid])
        if method=='POST' and path.endswith('/end'):
            sid=path.split('/')[1]
            if sid in self.end_fail:raise self.end_fail[sid]
            row=self.rows.get(sid)
            if not row or row['owner']!=who:raise HTTPException(404,'Capture session ended or is not owned by this browser.')
            del self.rows[sid];return {'ended':True}
        raise AssertionError((method,path))


class CaptureSetTests(unittest.TestCase):
    """C07: one request, several sessions; the manager's own session list; End all my sessions."""
    def setUp(self):
        CaptureAPITests.setUp(self)
        self.service=ScriptedService();self.captures.sessions=self.service
        self.client.cookies.set('clab_capture_owner',WHO)
        self.rid='e'*64
        self.r1=CaptureAPITests.selection(self)['target_id']
        self.host=next(t['id'] for t in self.client.get('/api/capture/targets').json()['targets'] if t['name']=='init')
        self.before=copy.deepcopy(self.app.state.store.state)

    def tearDown(self):
        CaptureAPITests.tearDown(self)

    def derived(self,target_id,interfaces,rid=None):
        return hashlib.sha256(f'{rid or self.rid}:{target_id}:{"/".join(interfaces)}'.encode()).hexdigest()

    def launch(self,*entries,rid=None):
        return self.client.post('/api/capture/launch',json={'captures':[{'target_id':t,'interfaces':i} for t,i in entries],
                                                            'request_id':rid or self.rid})

    def occupy(self,n,who=WHO):
        base=0 if who==WHO else 100
        for index in range(n):
            self.service.rows[f'{base+index:064x}']={'owner':who,'name':'clab-demo-r1','interfaces':['lo']}

    def limit(self,value):
        self.service.health={'ready':True,'max_sessions':value};self.captures.capacity_cache=None

    def events(self,action):
        return [e for e in self.app.state.store.events() if e['action']==action]

    def test_a_set_starts_one_session_per_entry_with_derived_request_ids_and_labels(self):
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual(r.status_code,200,r.text);body=r.json()
        rids=[c[3]['request_id'] for c in self.service.posts()]
        self.assertEqual(rids,[self.derived(self.r1,['eth2']),self.derived(self.host,['ens18'])])
        self.assertEqual([s['label'] for s in body['sessions']],['r1 eth2','init ens18'])
        self.assertEqual([s['name'] for s in body['sessions']],['clab-demo-r1','init'])
        self.assertEqual([s['interfaces'] for s in body['sessions']],[['eth2'],['ens18']])
        self.assertEqual([set(s) for s in body['sessions']],[{'id','url','name','interfaces','label'}]*2)
        first=body['sessions'][0]['id']
        self.assertEqual((body['id'],body['url']),(first,'/static/capture-session.html#'+first))
        self.assertEqual([s['url'] for s in body['sessions']],['/static/capture-session.html#'+s['id'] for s in body['sessions']])
        self.assertEqual(body['refused'],[])
        self.assertEqual(body['message'],'Wireshark started on the VM for 2 captures. Open each viewer below.')
        self.assertEqual([e['message'] for e in self.events('capture.launch')],
                         ['Started browser Wireshark session for init (ens18).','Started browser Wireshark session for clab-demo-r1 (eth2).'])
        self.assertEqual(list(self.captures.requests[self.rid]),rids)
        record=self.captures.known[first]
        self.assertEqual(set(record),{'lab','lab_id','device','ports','label','started'})
        self.assertEqual((record['lab'],record['lab_id'],record['device'],record['ports'],record['label']),('demo','lab','r1',['eth2'],'r1 eth2'))
        self.assertGreater(record['started'],0)
        self.assertEqual(self.app.state.store.state,self.before)

    def test_a_launched_session_is_listed_with_its_record(self):
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']));self.assertEqual(r.status_code,200,r.text)
        rows=self.client.get('/api/capture/sessions').json()['sessions']
        launched=next(s for s in rows if s['id']==r.json()['sessions'][0]['id'])
        self.assertEqual((launched['lab'],launched['device'],launched['ports'],launched['label']),('demo','r1',['eth2'],'r1 eth2'))
        fallback=self.captures.label('clab-demo-r1',['eth2']);known=self.captures.known[launched['id']]
        self.assertEqual(set(fallback),set(known))
        self.assertEqual({k:v for k,v in fallback.items() if k!='started'},{k:v for k,v in known.items() if k!='started'})
        # A manager restart forgets the records: the fallback answers the same keys and values.
        self.captures.known.clear()
        again=next(s for s in self.client.get('/api/capture/sessions').json()['sessions'] if s['id']==launched['id'])
        self.assertEqual(again,launched)

    def test_a_set_is_validated_whole_before_anything_starts(self):
        for entries,detail in [
                (((self.r1,['eth2']),(self.r1,['eth99'])),'Capture 2 of 2: Select interfaces from the refreshed live list.'),
                (((self.r1,['eth2']),(self.host,['ens18','ens18'])),'Capture 2 of 2: Select interfaces from the refreshed live list.'),
                (((self.r1,['eth2']),('f'*64,['eth2'])),'Capture 2 of 2: Capture target changed or disappeared. Refresh interfaces and select it again.'),
                (((self.r1,['eth2']),(self.r1,['eth2'])),'The same interface is listed twice. Refresh interfaces and select again.'),
                (((self.r1,['eth0','eth2']),(self.host,['ens18']),(self.r1,['eth2'])),'The same interface is listed twice. Refresh interfaces and select again.'),
                # A set of one keeps the single launch's wording (there is no position to name).
                (((self.r1,['eth99']),),'Select interfaces from the refreshed live list.')]:
            with self.subTest(entries=entries):
                r=self.launch(*entries)
                self.assertEqual((r.status_code,r.json()['detail']),(409,detail))
        self.assertEqual(self.service.calls,[]);self.assertEqual(self.captures.known,{})
        self.assertEqual(self.events('capture.launch'),[])

    def test_the_body_takes_exactly_one_form_and_at_most_four_entries(self):
        entry={'target_id':self.r1,'interfaces':['eth2']}
        for body in [{'captures':[entry]*5},{'captures':[]},{'captures':[entry],'target_id':self.r1,'interfaces':['eth2']},
                     {'captures':[entry],'interfaces':['eth2']},{'target_id':self.r1},{'interfaces':['eth2']},{},
                     {'captures':[{**entry,'url':'http://evil'}]},{'captures':[{**entry,'interfaces':[]}]},
                     {'captures':[{'target_id':'é'*64,'interfaces':['eth2']}]},{'captures':[entry],'request_id':'x'},
                     {'captures':[{'target_id':self.r1}]}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post('/api/capture/launch',json=body).status_code,422)
        self.assertEqual(self.service.calls,[])

    def test_the_own_slot_pre_check_refuses_before_starting_in_the_variant_of_the_set(self):
        self.occupy(3);self.occupy(1,who=OTHER)
        r=self.launch((self.r1,['eth0']),(self.r1,['eth2']))
        self.assertEqual((r.status_code,r.json()['detail']),(409,
            'You already have 3 Wireshark sessions running from this browser; 2 more would pass the limit of 4 at a time. '
            'End a session under Your capture sessions, untick interfaces, or open one Wireshark for all of them.'))
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual((r.status_code,r.json()['detail']),(409,
            'You already have 3 Wireshark sessions running from this browser; both ends would pass the limit of 4 at a time. '
            'End a session under Your capture sessions, or untick one end.'))
        self.service.rows.clear();self.occupy(1);self.limit(2)
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual((r.status_code,r.json()['detail']),(409,
            'You already have 1 Wireshark session running from this browser; both ends would pass the limit of 2 at a time. '
            'End a session under Your capture sessions, or untick one end.'))
        r=self.launch((self.r1,['eth0']),(self.r1,['eth2']),(self.r1,['lo']))
        self.assertEqual((r.status_code,r.json()['detail']),(409,
            '3 separate Wireshark sessions are more than the limit of 2 at a time. Untick interfaces, or open one Wireshark for all of them.'))
        self.assertEqual(self.service.posts(),[])
        # The pre-check counts this browser only and reserves nothing: the service's cap stays the authority.
        self.service.rows.clear();self.occupy(1);self.occupy(3,who=OTHER);self.limit(4)
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual((r.status_code,r.json()),(429,{'detail':SLOTS}))
        self.assertEqual(len(self.service.posts()),1)

    def test_a_larger_published_capacity_is_honoured(self):
        self.occupy(3);self.limit(6)
        r=self.launch((self.r1,['eth0']),(self.r1,['eth2']))
        # 3 + 2 <= 6 passes the pre-check; the service's own cap of four answers the second start.
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(len(r.json()['sessions']),1);self.assertEqual(r.json()['refused'][0]['detail'],SLOTS)

    def test_a_retry_of_a_started_set_is_never_refused_by_its_own_sessions(self):
        self.occupy(2)
        first=self.launch((self.r1,['eth0']),(self.r1,['eth2']))
        self.assertEqual(first.status_code,200,first.text);self.assertEqual(len(self.service.rows),4)
        again=self.launch((self.r1,['eth0']),(self.r1,['eth2']))
        self.assertEqual(again.status_code,200,again.text)
        self.assertEqual([s['id'] for s in again.json()['sessions']],[s['id'] for s in first.json()['sessions']])
        self.assertEqual(len(self.service.posts()),4);self.assertEqual(len(self.service.rows),4)
        # An entry of this request that never started still has every other session counted against it.
        r=self.launch((self.r1,['eth0']),(self.r1,['lo']))
        self.assertEqual(r.status_code,409);self.assertIn('You already have 3 Wireshark sessions',r.json()['detail'])
        self.assertEqual(len(self.service.posts()),4)

    def test_a_mid_set_refusal_reports_started_and_refused(self):
        self.service.fail={2:HTTPException(429,SLOTS)}
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual(r.status_code,200,r.text);body=r.json()
        self.assertEqual([s['label'] for s in body['sessions']],['r1 eth2'])
        self.assertEqual(body['refused'],[{'position':'Capture 2 of 2','label':'init ens18','interfaces':['ens18'],'detail':SLOTS}])
        self.assertEqual(body['message'],'Wireshark started for r1 eth2; not for init ens18: '+SLOTS)
        self.assertEqual(body['id'],body['sessions'][0]['id'])
        self.assertEqual(len(self.events('capture.launch')),1)
        # A service 409 (its own discovery disagrees) stops the set the same way, the remaining entries included.
        self.service.rows.clear();self.service.calls.clear()
        changed='Capture target changed. Refresh interfaces and retry.'
        self.service.fail={2:HTTPException(409,changed)}
        r=self.launch((self.r1,['eth0']),(self.r1,['eth2']),(self.r1,['lo']),rid='1'*64)
        self.assertEqual([s['label'] for s in r.json()['sessions']],['r1 eth0'])
        self.assertEqual([(x['position'],x['label'],x['interfaces'],x['detail']) for x in r.json()['refused']],
                         [('Capture 2 of 3','r1 eth2',['eth2'],changed),('Capture 3 of 3','r1 lo',['lo'],changed)])
        self.assertEqual(len(self.service.posts()),2)
        self.assertEqual(r.json()['message'],'Wireshark started for r1 eth0; not for r1 eth2, r1 lo: '+changed)

    def test_the_managers_own_session_check_stops_a_set(self):
        self.service.fail={2:'token'}
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual(r.status_code,200,r.text)
        refused,=r.json()['refused']
        self.assertEqual(refused['detail'],'This capture may have started; see Your capture sessions. '
                                           'Browser capture service returned an invalid session.')
        self.assertEqual(len(r.json()['sessions']),1)

    def test_a_failure_on_the_first_entry_is_a_plain_error(self):
        self.service.fail={1:HTTPException(429,SLOTS)}
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual((r.status_code,r.json()),(429,{'detail':SLOTS}))
        self.assertEqual(len(self.service.posts()),1);self.assertEqual(self.events('capture.launch'),[])

    def test_a_lost_reply_is_recovered_from_one_relisting(self):
        self.service.fail={2:'lost'}
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual(r.status_code,200,r.text);body=r.json()
        self.assertEqual([s['label'] for s in body['sessions']],['r1 eth2','init ens18']);self.assertEqual(body['refused'],[])
        self.assertEqual(body['sessions'][1]['id'],self.service.session_id(WHO,self.derived(self.host,['ens18'])))
        self.assertEqual(len(self.events('capture.launch')),2)
        self.assertEqual([c[:2] for c in self.service.calls].count(('GET','sessions')),2)  # the pre-check, then one re-list
        self.assertIn(body['sessions'][1]['id'],self.captures.known)
        # Lost on the first entry: recovered as well, and the set goes on with the untried entries.
        self.service.rows.clear();self.service.calls.clear();self.service.fail={1:'lost'}
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']),rid='1'*64)
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual([s['label'] for s in r.json()['sessions']],['r1 eth2','init ens18']);self.assertEqual(r.json()['refused'],[])
        self.assertEqual(len(self.service.posts()),2)

    def test_after_a_recovered_reply_one_more_service_failure_stops_the_set_as_not_attempted(self):
        self.service.fail={1:'lost',2:HTTPException(502,LOST)}
        r=self.launch((self.r1,['eth0']),(self.r1,['eth2']),(self.r1,['lo']))
        self.assertEqual(r.status_code,200,r.text);body=r.json()
        self.assertEqual([s['label'] for s in body['sessions']],['r1 eth0'])
        self.assertEqual([(x['label'],x['detail']) for x in body['refused']],
                         [('r1 eth2','This capture may have started; see Your capture sessions. '+LOST),
                          ('r1 lo','Not attempted: an earlier capture of this set failed.')])
        self.assertEqual(len(self.service.posts()),2)
        self.assertNotIn('Cannot reach',body['refused'][1]['detail'])

    def test_a_repeated_set_logs_no_second_launch_and_keeps_started(self):
        first=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual(first.status_code,200,first.text)
        ids=[s['id'] for s in first.json()['sessions']]
        started={i:self.captures.known[i]['started'] for i in ids}
        self.assertEqual(len(self.events('capture.launch')),2)
        again=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual(again.status_code,200,again.text)
        self.assertEqual([s['id'] for s in again.json()['sessions']],ids)
        self.assertEqual(len(self.events('capture.launch')),2)
        self.assertEqual({i:self.captures.known[i]['started'] for i in ids},started)
        # The single form repeated with its request id behaves the same.
        data=CaptureAPITests.selection(self);single={**data,'request_id':'2'*64}
        a=self.client.post('/api/capture/launch',json=single);sid=a.json()['id'];t=self.captures.known[sid]['started']
        n=len(self.events('capture.launch'))
        b=self.client.post('/api/capture/launch',json=single)
        self.assertEqual((b.status_code,b.json()['id']),(200,sid))
        self.assertEqual(len(self.events('capture.launch')),n);self.assertEqual(self.captures.known[sid]['started'],t)

    def test_a_502_without_a_listed_row_may_have_started_and_the_narrowed_retry_meets_it(self):
        self.service.fail={2:HTTPException(502,LOST)}
        r=self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.assertEqual(r.status_code,200,r.text)
        refused,=r.json()['refused']
        self.assertEqual(refused['detail'],'This capture may have started; see Your capture sessions. '+LOST)
        self.assertEqual(r.json()['message'],'Wireshark started for r1 eth2; not for init ens18: This capture may have started; '
                                             'see Your capture sessions. '+LOST)
        # The page narrows to the refused entry and keeps the request id: the same content-derived id goes out.
        self.service.fail={}
        again=self.launch((self.host,['ens18']))
        self.assertEqual(again.status_code,200,again.text)
        self.assertEqual(self.service.posts()[-1][3]['request_id'],self.derived(self.host,['ens18']))
        self.assertEqual(again.json()['sessions'][0]['id'],self.service.session_id(WHO,self.derived(self.host,['ens18'])))
        self.assertEqual(again.json()['message'],STARTED)
        # A set of one whose only entry fails with no listed row is the plain error.
        self.service.fail={len(self.service.posts())+1:HTTPException(502,LOST)}
        r=self.launch((self.r1,['eth0']))
        self.assertEqual((r.status_code,r.json()),(502,{'detail':LOST}))

    def test_single_launch_body_and_response_are_unchanged(self):
        data=CaptureAPITests.selection(self)
        r=self.client.post('/api/capture/launch',json={**data,'request_id':self.rid})
        self.assertEqual(r.status_code,200,r.text);body=r.json()
        self.assertEqual(self.service.posts()[0][3]['request_id'],self.rid)  # the single form sends its own id
        self.assertEqual(body['message'],STARTED)
        self.assertEqual([s['id'] for s in body['sessions']],[body['id']]);self.assertEqual(body['refused'],[])
        self.assertEqual(body['sessions'][0]['label'],'r1 eth2')
        self.assertEqual([c[:2] for c in self.service.calls],[('POST','sessions')])  # no listing, no health call
        self.service.fail={2:HTTPException(502,LOST)}
        r=self.client.post('/api/capture/launch',json=data)
        self.assertEqual((r.status_code,r.json()),(502,{'detail':LOST}))
        self.assertEqual([c[:2] for c in self.service.calls].count(('GET','sessions')),0)

    def test_sessions_listing_is_a_whitelist_with_labels(self):
        self.lab['nodes'].append({'name':'j1','definition_node':'j1','short_name':'j1','kind':'juniper_vjunosrouter'})
        self.app.state.store.state['labs'].insert(0,{'id':'odd','name':'odd','nodes':[{'kind':'linux'}]})  # one odd stored node
        launched=self.launch((self.r1,['eth2']),rid='1'*64).json()['sessions'][0]['id']
        self.service.rows[f'{7:064x}']={'owner':WHO,'name':'clab-demo-j1','interfaces':['eth1']}  # started before a manager restart
        self.service.extra={'password':'PRIVATE','address':'172.30.0.7','viewer_password':'PRIVATE'}
        self.service.listing_extra=[{'id':'../evil','name':'x','interfaces':[]},{'id':'A'*64,'name':'x','interfaces':[]},
                                    {'name':'x','interfaces':[]}]
        rows=self.client.get('/api/capture/sessions').json()['sessions']
        self.assertEqual(len(rows),2);self.assertNotIn('PRIVATE',json.dumps(rows))
        for row in rows:
            self.assertEqual(set(row),{'id','name','interfaces','remaining_seconds','idle_seconds','lab','device','ports','label'})
        mine=next(r for r in rows if r['id']==launched);other=next(r for r in rows if r['id']==f'{7:064x}')
        self.assertEqual((mine['lab'],mine['device'],mine['ports'],mine['label']),('demo','r1',['eth2'],'r1 eth2'))
        self.assertEqual((other['lab'],other['device'],other['ports'],other['label'],other['interfaces']),
                         ('demo','j1',['ge-0/0/0'],'j1 ge-0/0/0',['eth1']))
        # A container no lab names: no lab, the container name and the veth names.
        self.assertEqual(self.captures.label('clab-other-x',['eth1']),
                         {'lab':'','lab_id':'','device':'clab-other-x','ports':['eth1'],'label':'clab-other-x eth1','started':0.0})

    def test_known_is_pruned_per_browser_and_both_maps_are_capped(self):
        a=self.launch((self.r1,['eth2']),rid='1'*64).json()['sessions'][0]['id']
        self.client.cookies.set('clab_capture_owner',OTHER)
        b=self.launch((self.r1,['eth2']),rid='2'*64).json()['sessions'][0]['id']
        self.assertEqual(set(self.captures.known),{a,b})
        del self.service.rows[b]
        self.client.get('/api/capture/sessions')  # browser OTHER lists: only its own records are pruned
        self.assertEqual(set(self.captures.known),{a})
        self.client.cookies.set('clab_capture_owner',WHO);self.client.get('/api/capture/sessions')
        self.assertEqual(set(self.captures.known),{a})
        for n in range(80):
            self.captures.remember(WHO,f'{n+1000:064x}',self.captures.label('x',['eth1']))
            self.captures.plan(f'{n+1000:064x}',['f'*64])
        self.assertEqual(len(self.captures.known),64);self.assertEqual(len(self.captures.requests),64)
        self.assertEqual(set(self.captures.known),set(self.captures.known_owner))
        self.assertNotIn(a,self.captures.known);self.assertIn(f'{1079:064x}',self.captures.known)

    def test_end_all_ends_only_the_cookies_sessions_and_reports_failures(self):
        first=[s['id'] for s in self.launch((self.r1,['eth2']),(self.host,['ens18'])).json()['sessions']]
        self.occupy(1,who=OTHER)
        r=self.client.post('/api/capture/sessions/end-all',json={})
        self.assertEqual((r.status_code,r.json()),(200,{'ended':2,'failed':[]}))
        ends=[c[1] for c in self.service.calls if c[1].endswith('/end')]
        self.assertEqual(ends,['sessions/'+sid+'/end' for sid in first])
        self.assertEqual(len(self.service.rows),1)  # the other browser's session is untouched
        self.assertEqual([e['message'] for e in self.events('capture.end_all')],
                         ['Ended 2 browser Wireshark session(s) and removed their temporary files.'])
        self.assertFalse(set(first)&set(self.captures.known))
        # Nothing left: no event.
        self.assertEqual(self.client.post('/api/capture/sessions/end-all',json={}).json(),{'ended':0,'failed':[]})
        self.assertEqual(len(self.events('capture.end_all')),1)
        # A 404 (expired between list and end) counts as ended; a 503 gets the fixed sentence and the loop goes on.
        ids=[s['id'] for s in self.launch((self.r1,['eth2']),(self.r1,['eth0']),(self.host,['ens18']),rid='1'*64).json()['sessions']]
        self.service.end_fail={ids[0]:HTTPException(404,'gone'),
                               ids[1]:HTTPException(503,'Browser capture service is not ready. Run Capture setup and check its logs.')}
        r=self.client.post('/api/capture/sessions/end-all',json={})
        self.assertEqual(r.json(),{'ended':2,'failed':[{'id':ids[1],'label':'r1 eth0','detail':'Could not end r1 eth0; try End session on its row.'}]})
        self.assertNotIn('Capture setup',r.text)
        newest=self.events('capture.end_all')[0]
        self.assertEqual((newest['message'],newest['level']),
                         ('Ended 2 browser Wireshark session(s) and removed their temporary files; 1 could not be ended.','warning'))
        self.assertNotIn(ids[0],self.captures.known);self.assertIn(ids[1],self.captures.known)

    def test_end_all_needs_the_cookie_the_origin_and_a_body(self):
        self.launch((self.r1,['eth2']),(self.host,['ens18']))
        stranger=TestClient(self.app)
        try:
            r=stranger.post('/api/capture/sessions/end-all',json={})
            self.assertEqual((r.status_code,r.json()['detail']),(404,'Capture session not found in this browser.'))
            stranger.cookies.set('clab_capture_owner',OTHER)
            self.assertEqual(stranger.post('/api/capture/sessions/end-all',json={}).json(),{'ended':0,'failed':[]})
        finally:stranger.close()
        self.assertEqual(len(self.service.rows),2)
        self.assertEqual(self.client.post('/api/capture/sessions/end-all',json={},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/capture/sessions/end-all').status_code,413)
        self.assertEqual(len(self.service.rows),2);self.assertEqual([c for c in self.service.calls if c[1].endswith('/end')],[])

    def test_capacity_falls_back_to_four_and_is_cached(self):
        self.service.health=HTTPException(502,LOST)
        self.assertEqual(self.captures.capacity(),4)
        for value in (True,0,65,'6',None,6.0):
            with self.subTest(value=value):
                self.limit(value);self.assertEqual(self.captures.capacity(),4)
        self.limit(6)
        with patch('app.capture.time.monotonic',return_value=1000.0):self.assertEqual(self.captures.capacity(),6)
        self.service.health={'ready':True,'max_sessions':3}
        with patch('app.capture.time.monotonic',return_value=1059.0):self.assertEqual(self.captures.capacity(),6)
        with patch('app.capture.time.monotonic',return_value=1061.0):self.assertEqual(self.captures.capacity(),3)
        self.assertEqual([c[1] for c in self.service.calls].count('health'),9)

    def test_no_store_key_or_event_carries_a_password_a_packet_url_or_the_cookie(self):
        self.service.extra={'viewer_password':'PRIVATE'}
        self.launch((self.r1,['eth2']),(self.host,['ens18']))
        self.client.get('/api/capture/sessions');self.client.post('/api/capture/sessions/end-all',json={})
        text=json.dumps(self.app.state.store.events())
        for needle in ('PRIVATE','viewer_password','packetflix',WHO):self.assertNotIn(needle,text)
        self.assertEqual(self.app.state.store.state,self.before)
