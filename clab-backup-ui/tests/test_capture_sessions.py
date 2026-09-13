"""Session service policy, Docker contract, cleanup and browser ownership."""
import asyncio
import copy
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.capture_service import IMAGE, LABEL, IDLE_SECONDS, LIFETIME_SECONDS, Sessions, create_app
from app.capture_sessions import BrowserSessions
from test_capture import fixture


class DockerFixture:
    def __init__(self):
        self.calls=[];self.containers={};self.fail='';self.archive=b''

    def handle(self, request):
        path=request.url.path;self.calls.append(request)
        if self.fail and self.fail in path:return httpx.Response(500,json={'message':'PRIVATE daemon output'})
        if path.startswith('/images/'):
            return httpx.Response(200,json={'Id':IMAGE})
        if path=='/containers/json':
            return httpx.Response(200,json=[{'Id':k,'Labels':v['Labels']} for k,v in self.containers.items()])
        if path=='/containers/create':
            name=request.url.params['name'];self.containers[name]=json.loads(request.content)
            return httpx.Response(201,json={'Id':name})
        parts=path.split('/');name=parts[2]
        if request.method=='DELETE':
            self.containers.pop(name,None);return httpx.Response(204)
        if parts[-1]=='start':return httpx.Response(204)
        if parts[-1]=='json':return httpx.Response(200,json={'State':{'Running':True},'NetworkSettings':{'Networks':{'clab-manager-capture':{'IPAddress':'172.30.0.7'}}}})
        if parts[-1]=='archive':return httpx.Response(200,content=self.archive)
        raise AssertionError((request.method,path))


class CaptureSessionTests(unittest.TestCase):
    def setUp(self):
        self.docker=DockerFixture()
        client=httpx.Client(transport=httpx.MockTransport(self.docker.handle),base_url='http://docker')
        self.provider=Mock();self.provider.discover.return_value=copy.deepcopy(fixture()['containers'])
        self.provider.stream_uri.return_value='packetflix:ws://packetflix:5001/capture?fixture'
        self.sessions=Sessions('a'*64,docker=client,provider=self.provider)
        self.client=TestClient(create_app(self.sessions))
        self.headers={'Authorization':'Bearer '+'a'*64,'X-Capture-Owner':'b'*64}
        self.data={'target':fixture()['containers'][0],'interfaces':['eth2'],'request_id':'c'*64}

    def tearDown(self):
        self.client.close();self.sessions.docker.close()

    def start(self,data=None):
        response=self.client.post('/sessions',headers=self.headers,json=data or self.data)
        self.assertEqual(response.status_code,200,response.text)
        return response.json()['id']

    def test_fixed_image_network_resource_limits_and_no_host_mounts_or_ports(self):
        sid=self.start();spec=next(iter(self.docker.containers.values()))
        self.assertEqual(spec['Image'],IMAGE)
        self.assertIn(LABEL,spec['Labels'])
        config=spec['HostConfig']
        self.assertEqual(config['NetworkMode'],'clab-manager-capture')
        for field in ('Binds','PortBindings','Privileged','PidMode'):
            self.assertNotIn(field,config)
        self.assertEqual(config['Memory'],1024**3)
        self.assertIn('size=256m',config['Tmpfs']['/pcaps'])
        self.assertEqual(self.client.get('/sessions/'+sid,headers=self.headers).json()['running'],True)

    def test_auth_ownership_and_unknown_fields_fail_closed(self):
        self.assertEqual(self.client.post('/sessions',json=self.data).status_code,403)
        sid=self.start();other={**self.headers,'X-Capture-Owner':'d'*64}
        self.assertEqual(self.client.get('/sessions',headers=other).json()['sessions'],[])
        for suffix in ('','/download','/assets/core/rfb.js'):
            self.assertEqual(self.client.get('/sessions/'+sid+suffix,headers=other).status_code,404)
        self.assertEqual(self.client.post('/sessions/'+sid+'/end',headers=other,json={}).status_code,404)
        for field in ('image','url','command','mount','network'):
            self.assertEqual(self.client.post('/sessions',headers=self.headers,json={**self.data,field:'evil'}).status_code,422)
        self.assertEqual(len(self.docker.containers),1)

    def test_fresh_validation_rejects_namespace_and_interface_changes(self):
        self.provider.discover.return_value[0]['pid']=99
        self.assertEqual(self.client.post('/sessions',headers=self.headers,json=self.data).status_code,409)
        self.provider.discover.return_value=fixture()['containers']
        for interfaces in (['evil'],['eth2','eth2']):
            self.assertEqual(self.client.post('/sessions',headers=self.headers,json={**self.data,'interfaces':interfaces}).status_code,409)
        self.assertFalse(self.docker.containers)

    def test_retry_is_idempotent_and_capacity_is_bounded(self):
        sid=self.start();self.assertEqual(self.start(),sid)
        self.assertEqual(len(self.docker.containers),1)
        for n in range(3):self.start({**self.data,'request_id':str(n)*64})
        self.assertEqual(self.client.post('/sessions',headers=self.headers,json={**self.data,'request_id':'9'*64}).status_code,429)

    def test_failed_start_removes_partial_container_and_hides_daemon_output(self):
        self.docker.fail='/start'
        response=self.client.post('/sessions',headers=self.headers,json=self.data)
        self.assertEqual(response.status_code,503)
        self.assertNotIn('PRIVATE',response.text)
        self.assertFalse(self.docker.containers);self.assertFalse(self.sessions.rows)

    def test_failed_creation_cleanup_is_retried_by_the_sweeper(self):
        self.docker.fail='/start'
        with patch.object(self.sessions,'remove',side_effect=HTTPException(503)):
            self.assertEqual(self.client.post('/sessions',headers=self.headers,json=self.data).status_code,503)
        self.assertEqual(len(self.sessions.pending),1)
        self.docker.fail='';self.sessions.reap()
        self.assertFalse(self.sessions.pending);self.assertFalse(self.docker.containers)

    def test_rotating_service_token_retains_orphan_ownership(self):
        self.start()
        restarted=Sessions('e'*64,docker=self.sessions.docker,provider=self.provider)
        restarted.cleanup_orphans()
        self.assertFalse(self.docker.containers)

    def test_end_idle_and_hard_expiry_remove_only_owned_containers(self):
        sid=self.start();self.docker.containers['unrelated-lab']={'Labels':{}}
        self.assertEqual(self.client.post('/sessions/'+sid+'/end',headers=self.headers,json={}).status_code,200)
        self.assertEqual(set(self.docker.containers),{'unrelated-lab'})
        sid=self.start();self.sessions.rows[sid]['seen']-=IDLE_SECONDS+1;self.sessions.reap()
        self.assertNotIn(sid,self.sessions.rows)
        sid=self.start();self.sessions.rows[sid]['created']-=LIFETIME_SECONDS+1;self.sessions.reap()
        self.assertNotIn(sid,self.sessions.rows)
        self.start();self.sessions.cleanup_orphans()
        self.assertEqual(set(self.docker.containers),{'unrelated-lab'})

    def test_failed_end_keeps_session_for_retry(self):
        sid=self.start();name=self.sessions.rows[sid]['container'];self.docker.fail=name
        self.assertEqual(self.client.post('/sessions/'+sid+'/end',headers=self.headers,json={}).status_code,503)
        self.assertIn(sid,self.sessions.rows)
        self.docker.fail=''
        self.assertEqual(self.client.post('/sessions/'+sid+'/end',headers=self.headers,json={}).status_code,200)

    def test_download_archive_preserves_saved_pcap_bytes_and_restricts_path(self):
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as archive:
            data=b'\x0a\x0d\x0d\x0a'+b'fixture packet data'
            entry=tarfile.TarInfo('pcaps/test.pcapng');entry.size=len(data)
            archive.addfile(entry,io.BytesIO(data))
        self.docker.archive=stream.getvalue();sid=self.start()
        response=self.client.get('/sessions/'+sid+'/download',headers=self.headers)
        self.assertEqual(response.content,stream.getvalue())
        self.assertEqual(self.docker.calls[-1].url.params['path'],'/pcaps')
        for path in ('index.html','app/ui.js','vendor/../config.js','core/evil.html'):
            self.assertEqual(self.client.get('/sessions/'+sid+'/assets/'+path,headers=self.headers).status_code,404)

    def test_service_health_requires_credentials_and_image(self):
        self.assertEqual(self.client.get('/health').status_code,403)
        self.assertTrue(self.client.get('/health',headers=self.headers).json()['ready'])
        self.docker.fail='/images/'
        self.assertEqual(self.client.get('/health',headers=self.headers).status_code,503)


class CaptureSetupTests(unittest.TestCase):
    def test_setup_pulls_the_same_fixed_image_that_sessions_launch(self):
        text=(Path(__file__).resolve().parents[2]/'deploy/setup-capture.sh').read_text()
        self.assertIn("image='"+IMAGE+"'",text)

    def test_migration_retains_other_settings_and_token_without_evaluating_shell(self):
        path=Path(__file__).resolve().parents[2]/'deploy/setup_capture.py'
        spec=importlib.util.spec_from_file_location('capture_setup',path)
        setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
        with tempfile.TemporaryDirectory() as folder:
            env=Path(folder)/'.env'
            env.write_text('UI_PORT=8088\nUNRELATED=$(do-not-run)\nCAPTURE_EDGESHARK_PUBLIC_URL=http://old\n')
            setup.configure(env);first=env.read_text();setup.configure(env)
            self.assertEqual(first,env.read_text())
            self.assertIn('UI_PORT=8088',first);self.assertIn('$(do-not-run)',first)
            self.assertNotIn('CAPTURE_EDGESHARK_PUBLIC_URL',first)
            env.write_text('CAPTURE_EDGESHARK_URL=http://custom:9999\n')
            with self.assertRaises(ValueError):setup.configure(env)
            self.assertEqual(env.read_text(),'CAPTURE_EDGESHARK_URL=http://custom:9999\n')
