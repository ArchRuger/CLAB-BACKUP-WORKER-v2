"""Session service policy, Docker contract, cleanup and browser ownership."""
import asyncio
import copy
import hashlib
import importlib.util
import re
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from starlette.websockets import WebSocketDisconnect

from app.capture_service import IMAGE, LABEL, IDLE_SECONDS, LIFETIME_SECONDS, Sessions, create_app, tar_has_regular_file
from app import capture_sessions
from app.capture_sessions import ASSET, BrowserSessions
from test_capture import fixture


class FakeDesktop:
    """Stands in for the container's websockify: one greeting, then the stream ends."""
    def __init__(self):
        self.greeted=False;self.sent=[]

    async def __aenter__(self):return self

    async def __aexit__(self,*exc):return False

    def __aiter__(self):return self

    async def __anext__(self):
        if self.greeted:raise StopAsyncIteration
        self.greeted=True;return b'RFB 003.008\n'

    async def send(self,message):self.sent.append(message)


def directory_only_archive():
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as archive:
        entry=tarfile.TarInfo('pcaps');entry.type=tarfile.DIRTYPE;archive.addfile(entry)
    return stream.getvalue()


class BrokenArchive(httpx.SyncByteStream):
    """An archive reply whose stream breaks after the status line, as when Docker restarts mid-download."""
    def __init__(self):
        self.closed=False

    def __iter__(self):
        raise httpx.ReadError('PRIVATE socket reset')
        yield b''

    def close(self):self.closed=True


class DockerFixture:
    def __init__(self):
        self.calls=[];self.containers={};self.volumes=[];self.fail='';self.archive=b''
        self.running=True;self.archive_error=None;self.archive_stream=None

    def handle(self, request):
        path=request.url.path;self.calls.append(request)
        if self.fail and self.fail in path:return httpx.Response(500,json={'message':'PRIVATE daemon output'})
        if path.startswith('/images/'):
            return httpx.Response(200,json={'Id':IMAGE})
        if path=='/volumes':
            return httpx.Response(200,json={'Volumes':self.volumes or None})
        if path.startswith('/volumes/') and request.method=='DELETE':
            self.volumes=[v for v in self.volumes if v['Name']!=path.split('/')[2]];return httpx.Response(204)
        if path=='/containers/json':
            return httpx.Response(200,json=[{'Id':k,'Labels':v['Labels']} for k,v in self.containers.items()])
        if path=='/containers/create':
            name=request.url.params['name'];self.containers[name]=json.loads(request.content)
            return httpx.Response(201,json={'Id':name})
        parts=path.split('/');name=parts[2]
        if request.method=='DELETE':
            self.containers.pop(name,None);return httpx.Response(204)
        if parts[-1]=='start':return httpx.Response(204)
        if name not in self.containers:return httpx.Response(404,json={'message':'PRIVATE no such container'})
        if parts[-1]=='json':return httpx.Response(200,json={'State':{'Running':self.running},'NetworkSettings':{'Networks':{'clab-manager-capture':{'IPAddress':'172.30.0.7'}}}})
        if parts[-1]=='archive':
            if self.archive_error:raise self.archive_error
            if self.archive_stream:return httpx.Response(200,stream=self.archive_stream)
            return httpx.Response(200,content=self.archive)
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
        # Saved captures sit on a labelled tmpfs-backed volume the archive API can read;
        # a container tmpfs is invisible to downloads. No host path is ever mounted.
        self.assertNotIn('/pcaps',config['Tmpfs']);self.assertIn('size=256m',config['Tmpfs']['/tmp'])
        mount,=config['Mounts']
        self.assertEqual((mount['Type'],mount['Target']),('volume','/pcaps'));self.assertNotIn('Source',mount)
        self.assertEqual(mount['VolumeOptions']['Labels'],{LABEL:self.sessions.label})
        driver=mount['VolumeOptions']['DriverConfig']
        self.assertEqual((driver['Name'],driver['Options']['type']),('local','tmpfs'))
        for option in ('size=256m','uid=1000','mode=0700','noexec'):self.assertIn(option,driver['Options']['o'])
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

    def test_orphan_capture_volumes_are_swept_and_unrelated_volumes_kept(self):
        self.docker.volumes=[{'Name':'f'*64,'Labels':{LABEL:self.sessions.label}},{'Name':'lab-data','Labels':{}}]
        self.sessions.cleanup_orphans()
        self.assertEqual([v['Name'] for v in self.docker.volumes],['lab-data'])
        deletes=[r.url.path for r in self.docker.calls if r.method=='DELETE']
        self.assertEqual(deletes,['/volumes/'+'f'*64])

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
        # An archive holding only the folder entry means nothing was saved: explain, do not hand over an empty tar.
        self.docker.archive=directory_only_archive()
        response=self.client.get('/sessions/'+sid+'/download',headers=self.headers)
        self.assertEqual(response.status_code,409);self.assertIn('Save As',response.json()['detail'])
        self.assertFalse(tar_has_regular_file(directory_only_archive()));self.assertTrue(tar_has_regular_file(stream.getvalue()))
        self.assertFalse(tar_has_regular_file(b''));self.assertFalse(tar_has_regular_file(b'x'*600))
        for path in ('index.html','app/ui.js','vendor/../config.js','core/evil.html'):
            self.assertEqual(self.client.get('/sessions/'+sid+'/assets/'+path,headers=self.headers).status_code,404)

    def test_desktop_stays_up_when_wireshark_exits_so_saved_files_survive(self):
        # The pinned image stops its container when the app exits unless KEEP_APP_RUNNING=1,
        # and moby's local volume driver unmounts a tmpfs-backed volume when its last container stops,
        # so a later archive read of /pcaps is expected to come back empty (not verified live here).
        self.start();env=next(iter(self.docker.containers.values()))['Env']
        self.assertIn('KEEP_APP_RUNNING=1',env);self.assertNotIn('KEEP_APP_RUNNING=0',env)

    def test_download_from_a_stopped_desktop_says_the_files_were_lost_not_never_saved(self):
        sid=self.start();self.docker.archive=directory_only_archive();self.docker.running=False
        response=self.client.get('/sessions/'+sid+'/download',headers=self.headers)
        self.assertEqual(response.status_code,409);detail=response.json()['detail']
        self.assertIn('lost',detail);self.assertNotIn('No saved captures yet',detail);self.assertNotIn('Save As',detail)

    def test_a_stopped_desktop_whose_files_survived_still_downloads_them(self):
        # AUDIT-2026-10-03 M-12 review: the loss is only reported when the archive really is empty, so a
        # Docker that keeps the volume's files hands them over instead of telling the student they are gone.
        stream=io.BytesIO()
        with tarfile.open(fileobj=stream,mode='w') as archive:
            data=b'\x0a\x0d\x0d\x0a'+b'fixture packet data'
            entry=tarfile.TarInfo('pcaps/kept.pcapng');entry.size=len(data);archive.addfile(entry,io.BytesIO(data))
        sid=self.start();self.docker.archive=stream.getvalue();self.docker.running=False
        response=self.client.get('/sessions/'+sid+'/download',headers=self.headers)
        self.assertEqual(response.status_code,200);self.assertEqual(response.content,stream.getvalue())

    def test_status_of_a_stopped_desktop_does_not_keep_its_slot_alive(self):
        sid=self.start();row=self.sessions.rows[sid];row['seen']-=60;before=row['seen']
        self.docker.running=False
        response=self.client.get('/sessions/'+sid,headers=self.headers)
        self.assertEqual(response.json()['running'],False);self.assertEqual(row['seen'],before)
        row['seen']-=IDLE_SECONDS;self.sessions.reap();self.assertNotIn(sid,self.sessions.rows)
        # A running desktop's status poll is still the viewer heartbeat.
        self.docker.running=True;sid=self.start();row=self.sessions.rows[sid];row['seen']-=60;before=row['seen']
        self.assertEqual(self.client.get('/sessions/'+sid,headers=self.headers).json()['running'],True)
        self.assertGreater(row['seen'],before)

    def test_one_stuck_removal_does_not_block_other_cleanup_starts_or_listing(self):
        expired=self.start();self.sessions.rows[expired]['created']-=LIFETIME_SECONDS+1
        stuck='clab-capture-'+self.sessions.label+'-'+'f'*64;self.sessions.pending.add(stuck);self.docker.fail=stuck
        self.sessions.reap()
        self.assertNotIn(expired,self.sessions.rows);self.assertFalse(self.docker.containers);self.assertEqual(self.sessions.pending,{stuck})
        self.assertEqual(self.client.get('/sessions',headers=self.headers).status_code,200)
        sid=self.start({**self.data,'request_id':'1'*64})
        # An expired session whose removal fails stays counted and is retried on the next sweep.
        self.sessions.rows[sid]['created']-=LIFETIME_SECONDS+1;self.docker.fail=self.sessions.rows[sid]['container']
        self.sessions.reap();self.assertIn(sid,self.sessions.rows)
        self.docker.fail='';self.sessions.reap()
        self.assertNotIn(sid,self.sessions.rows);self.assertFalse(self.sessions.pending);self.assertFalse(self.docker.containers)

    def test_download_maps_docker_transport_errors_and_a_removed_container(self):
        sid=self.start();self.docker.archive_error=httpx.ConnectError('PRIVATE socket gone')
        response=self.client.get('/sessions/'+sid+'/download',headers=self.headers)
        self.assertEqual(response.status_code,503);self.assertNotIn('PRIVATE',response.text)
        # The reply started, then the stream broke: the upstream response is closed, not leaked.
        self.docker.archive_error=None;self.docker.archive_stream=BrokenArchive()
        response=self.client.get('/sessions/'+sid+'/download',headers=self.headers)
        self.assertEqual(response.status_code,503);self.assertNotIn('PRIVATE',response.text);self.assertTrue(self.docker.archive_stream.closed)
        # A container removed outside the service is a gone session, not a hint to save in /pcaps.
        self.docker.archive_stream=None;self.docker.containers.clear()
        response=self.client.get('/sessions/'+sid+'/download',headers=self.headers)
        self.assertEqual(response.status_code,404);self.assertNotIn('/pcaps',response.json()['detail'])

    def test_desktop_relay_negotiates_the_binary_subprotocol_websockify_requires(self):
        sid=self.start();seen={}
        def connect(url,**kwargs):
            seen['url']=url;seen.update(kwargs);return FakeDesktop()
        with patch('app.capture_service.connect',connect):
            # Starlette's test client adds handshake headers to the dict it is given; pass copies.
            with self.client.websocket_connect('/sessions/'+sid+'/websockify',headers={**self.headers},subprotocols=['binary']) as ws:
                self.assertEqual(ws.accepted_subprotocol,'binary')
                self.assertEqual(ws.receive_bytes(),b'RFB 003.008\n')
                with self.assertRaises(WebSocketDisconnect):ws.receive_bytes()
        self.assertEqual(seen['url'],'ws://172.30.0.7:5800/websockify')
        self.assertEqual(seen['subprotocols'],['binary'])
        # A client that offers nothing (noVNC's default) is still served, without an invented reply protocol.
        with patch('app.capture_service.connect',connect):
            with self.client.websocket_connect('/sessions/'+sid+'/websockify',headers={**self.headers}) as ws:
                self.assertIsNone(ws.accepted_subprotocol);self.assertEqual(ws.receive_bytes(),b'RFB 003.008\n')
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/sessions/'+sid+'/websockify',headers={**self.headers,'X-Capture-Owner':'d'*64}):pass

    def test_each_desktop_demands_its_own_vnc_password_and_opens_no_raw_vnc_port(self):
        # Desktops share one Docker network: without a password a process in one desktop could
        # drive another's VNC server directly, bypassing the owner check entirely.
        first=self.start();second=self.start({**self.data,'request_id':'1'*64})
        envs={sid:self.docker.containers[self.sessions.rows[sid]['container']]['Env'] for sid in (first,second)}
        passwords={}
        for sid,env in envs.items():
            self.assertIn('VNC_LISTENING_PORT=-1',env)
            password,=[e.split('=',1)[1] for e in env if e.startswith('VNC_PASSWORD=')]
            self.assertRegex(password,r'^[A-Za-z0-9]{8}$');passwords[sid]=password
        self.assertNotEqual(passwords[first],passwords[second])
        # Only the owner's status answer carries it; listings and start replies never do.
        self.assertEqual(self.client.get('/sessions/'+first,headers=self.headers).json()['viewer_password'],passwords[first])
        self.assertEqual(self.client.get('/sessions/'+first,headers={**self.headers,'X-Capture-Owner':'d'*64}).status_code,404)
        for response in (self.client.get('/sessions',headers=self.headers),self.client.post('/sessions',headers=self.headers,json=self.data)):
            for password in passwords.values():self.assertNotIn(password,response.text)

    def test_viewer_modules_must_be_the_pinned_images_own_bytes(self):
        sid=self.start();served={'body':b'export default class RFB {}','paths':[]}
        def handler(request):
            served['paths'].append(request.url.path);return httpx.Response(200,content=served['body'])
        real=httpx.AsyncClient
        with patch('app.capture_service.httpx.AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw)):
            # A desktop serving anything but the pinned image's module is refused, never relayed as JavaScript.
            response=self.client.get('/sessions/'+sid+'/assets/core/rfb.js',headers=self.headers)
            self.assertEqual(response.status_code,502);self.assertNotIn('javascript',response.headers['content-type'])
            self.assertNotIn('class RFB',response.text)
            # A module name outside the pinned client is never even requested from the desktop.
            served['paths'].clear()
            self.assertEqual(self.client.get('/sessions/'+sid+'/assets/core/evil.js',headers=self.headers).status_code,404)
            self.assertEqual(served['paths'],[])
            with patch.dict(capture_sessions.VIEWER_ASSETS,{'core/rfb.js':hashlib.sha256(served['body']).hexdigest()}):
                response=self.client.get('/sessions/'+sid+'/assets/core/rfb.js',headers=self.headers)
            self.assertEqual(response.status_code,200);self.assertEqual(response.content,served['body'])
            self.assertIn('text/javascript',response.headers['content-type'])
        self.assertEqual(served['paths'],['/core/rfb.js'])

    def test_viewer_module_list_belongs_to_the_pinned_image(self):
        # A new pin must come with that image's module hashes (deploy/capture/viewer_assets.py).
        self.assertTrue(IMAGE.endswith('@'+capture_sessions.VIEWER_IMAGE))
        self.assertIn('core/rfb.js',capture_sessions.VIEWER_ASSETS)
        for path,digest in capture_sessions.VIEWER_ASSETS.items():
            self.assertTrue(ASSET.fullmatch(path),path);self.assertRegex(digest,r'^[0-9a-f]{64}$')

    def test_viewer_module_list_tool_follows_every_relative_import(self):
        path=Path(__file__).resolve().parents[2]/'deploy/capture/viewer_assets.py'
        spec=importlib.util.spec_from_file_location('viewer_assets',path)
        tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            files={'core/rfb.js':'import X from "./util/a.js";\nimport {\n b,\n c\n} from \'../vendor/z/b.js\';\n',
                   'core/util/a.js':"export * from './c.js';\n",'core/util/c.js':'export const c = 1;\n',
                   'vendor/z/b.js':'export const b = 2;\n','core/unused.js':'export {};\n'}
            for name,text in files.items():
                (root/name).parent.mkdir(parents=True,exist_ok=True);(root/name).write_text(text)
            found=tool.modules(root)
        self.assertEqual(set(found),{'core/rfb.js','core/util/a.js','core/util/c.js','vendor/z/b.js'})
        self.assertEqual(found['vendor/z/b.js'],hashlib.sha256(files['vendor/z/b.js'].encode()).hexdigest())

    def test_service_health_requires_credentials_and_image(self):
        self.assertEqual(self.client.get('/health').status_code,403)
        self.assertTrue(self.client.get('/health',headers=self.headers).json()['ready'])
        self.docker.fail='/images/'
        self.assertEqual(self.client.get('/health',headers=self.headers).status_code,503)


class CaptureSetupTests(unittest.TestCase):
    def test_session_service_image_imports_from_only_the_files_its_dockerfile_copies(self):
        # The service image holds the four modules on the Dockerfile's COPY line and the packages of its
        # pip line, not the manager's; a manager-only import kills browser Wireshark at the next setup.
        root=Path(__file__).resolve().parents[2];dockerfile=(root/'deploy/capture/Dockerfile').read_text()
        copied=next(line.split()[1:-1] for line in dockerfile.splitlines() if line.startswith('COPY '))
        self.assertIn('clab-backup-ui/app/capture_service.py',copied)
        allowed={line[1:] for line in (root/'deploy/capture/Dockerfile.dockerignore').read_text().splitlines() if line.startswith('!clab-backup-ui/app/')}
        self.assertEqual(set(copied)-allowed,set())
        blocked=['paramiko','yaml','cryptography','ansible','multipart','python_multipart','netlab']
        probe=('import importlib.abc,sys\n'
               'class Block(importlib.abc.MetaPathFinder):\n'
               ' def find_spec(self,name,path=None,target=None):\n'
               '  if name.split(".")[0] in %r:raise ModuleNotFoundError("not in the image: "+name)\n'
               'sys.meta_path.insert(0,Block())\n'
               'import app.capture_service\n'
               'print(sorted(m for m in sys.modules if m.startswith("app.")))\n') % (blocked,)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'app').mkdir()
            for name in copied:(Path(tmp)/'app'/Path(name).name).write_bytes((root/name).read_bytes())
            env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP')}
            result=subprocess.run([sys.executable,'-c',probe],cwd=tmp,env=env,capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr[-2000:])
        self.assertIn("'app.capture_service'",result.stdout)

    def test_setup_pulls_the_same_fixed_image_that_sessions_launch(self):
        text=(Path(__file__).resolve().parents[2]/'deploy/setup-capture.sh').read_text()
        self.assertIn("image='"+IMAGE+"'",text)
        # Upgrades rename the project network; only recreated containers can join it.
        self.assertIn('up -d --build --force-recreate',text)
        # Part of every installation: the script applies its settings to a running manager itself
        # unless the launcher, which creates the manager afterwards, asks it not to.
        self.assertIn('recreate-manager.sh',text);self.assertIn('--no-recreate',text);self.assertIn('--remove',text)

    def test_remove_keeps_the_token_and_urls_and_only_switches_the_provider_off(self):
        path=Path(__file__).resolve().parents[2]/'deploy/setup_capture.py'
        spec=importlib.util.spec_from_file_location('capture_setup',path)
        setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
        with tempfile.TemporaryDirectory() as folder:
            env=Path(folder)/'.env'
            env.write_text('UI_PORT=8088\n')
            setup.configure(env);before=env.read_text()
            token=re.search(r'CAPTURE_SESSION_TOKEN=([0-9a-f]{64})',before)[1]
            setup.disable(env);text=env.read_text()
            self.assertIn('CAPTURE_PROVIDER=disabled',text);self.assertNotIn('CAPTURE_PROVIDER=edgeshark',text)
            self.assertIn('CAPTURE_SESSION_TOKEN='+token,text);self.assertIn('UI_PORT=8088',text);self.assertIn('CAPTURE_SESSION_URL=',text)
            setup.configure(env);again=env.read_text()
            self.assertEqual(again.count('CAPTURE_PROVIDER='),1);self.assertIn('CAPTURE_PROVIDER=edgeshark',again);self.assertIn('CAPTURE_SESSION_TOKEN='+token,again)

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
