"""Real loopback HTTP/WebSocket transport through the manager (synthetic VM service)."""
import hashlib
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import Response
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import uvicorn

from app.main import create_app
from app import capture_sessions
from app.capture import EdgesharkProvider
from app.capture_sessions import BrowserSessions
from test_capture import fixture


class CaptureProxyTests(unittest.TestCase):
    def setUp(self):
        broker=FastAPI();self.who='';self.seen=[];self.offered=[];self.empty=False;self.refusal=None
        def auth(request):
            self.seen.append(dict(request.headers))
            if request.headers.get('authorization')!='Bearer '+'a'*64:
                raise HTTPException(403)
            if self.who and request.headers.get('x-capture-owner')!=self.who:
                raise HTTPException(404)
        @broker.post('/sessions')
        async def start(request:Request):
            auth(request);self.who=request.headers['x-capture-owner']
            return {'id':'c'*64}
        @broker.get('/sessions/{sid}/assets/{path:path}')
        async def asset(sid:str,path:str,request:Request):
            auth(request)
            # Stand-in for capture_service.py's own answers: the (status, detail) it raises instead of serving.
            if self.refusal:raise HTTPException(*self.refusal)
            return Response('export default class RFB {}',media_type='text/javascript')
        @broker.get('/sessions/{sid}/download')
        async def download(sid:str,request:Request):
            auth(request)
            if self.empty:raise HTTPException(409,'No saved captures yet. Use File > Save As under /pcaps.')
            return Response(b'synthetic-tar',media_type='application/x-tar')
        @broker.websocket('/sessions/{sid}/websockify')
        async def desktop(ws:WebSocket,sid:str):
            auth(ws);self.offered.append(list(ws.scope.get('subprotocols',[])))
            await ws.accept(subprotocol='binary' if 'binary' in ws.scope.get('subprotocols',[]) else None)
            await ws.send_bytes(b'RFB 003.008\n')
            await ws.send_bytes(await ws.receive_bytes());await ws.close()
        sock=socket.socket();sock.bind(('127.0.0.1',0))
        self.port=sock.getsockname()[1]
        self.server=uvicorn.Server(uvicorn.Config(broker,log_level='error',access_log=False))
        self.thread=threading.Thread(target=self.server.run,kwargs={'sockets':[sock]},daemon=True);self.thread.start()
        for _ in range(200):
            if self.server.started:break
            time.sleep(.01)
        self.assertTrue(self.server.started)
        self.tmp=tempfile.TemporaryDirectory()
        with patch.dict('os.environ',{'CAPTURE_PROVIDER':'disabled'}):self.app=create_app(self.tmp.name)
        self.client=TestClient(self.app)
        self.app.state.captures.provider=EdgesharkProvider('http://fixture')
        self.app.state.captures.sessions=BrowserSessions(f'http://127.0.0.1:{self.port}','a'*64)
        self.read=patch('app.capture.read_discovery',return_value=fixture());self.read.start()

    def tearDown(self):
        self.read.stop();self.client.close()
        for service in ('runner','node_services','git_progress','operations','discovery'):
            getattr(self.app.state,service).close()
        self.tmp.cleanup();self.server.should_exit=True;self.thread.join(5)

    def launch(self):
        target=self.client.get('/api/capture/targets').json()['targets'][0]
        result=self.client.post('/api/capture/launch',json={'target_id':target['id'],'interfaces':[target['interfaces'][0]]})
        self.assertEqual(result.status_code,200,result.text)
        self.assertNotIn('packetflix:',result.text);self.assertNotIn('a'*64,result.text)
        self.assertIn('HttpOnly',result.headers['set-cookie'])
        self.assertIn('SameSite=strict',result.headers['set-cookie'])
        return '/api/capture/sessions/'+result.json()['id']

    def test_viewer_modules_that_differ_from_the_pinned_image_never_run_as_manager_javascript(self):
        # A compromised desktop could serve any rfb.js; the manager origin must not execute it.
        base=self.launch()
        response=self.client.get(base+'/assets/core/rfb.js')
        self.assertEqual(response.status_code,502);self.assertNotIn('javascript',response.headers['content-type'])
        self.assertNotIn('class RFB',response.text)
        # A module the pinned client does not have is refused before the service is asked.
        before=len(self.seen)
        self.assertEqual(self.client.get(base+'/assets/core/evil.js').status_code,404);self.assertEqual(len(self.seen),before)

    def test_the_services_refusal_reaches_the_browser_as_final_and_starting_stays_retryable(self):
        # AUDIT-2026-10-03 L-28 review: the service refuses an unpinned or oversized viewer module itself
        # with 502; the viewer must not read that as "still starting" and poll for half a minute.
        base=self.launch()
        for refusal in ((502,'Viewer asset is not the pinned one.'),(502,)):
            self.refusal=refusal;response=self.client.get(base+'/assets/core/rfb.js')
            self.assertEqual(response.status_code,502,refusal)
            self.assertNotIn('javascript',response.headers['content-type'])
            detail=response.json()['detail']
            self.assertIn('not the pinned one',detail);self.assertIn('start a new capture',detail)
        # A desktop that is still starting (the service's 503) or a session the service no longer
        # knows (404) stays the retryable 404 the viewer waits on.
        for refusal in ((503,'Viewer starting; retry shortly.'),(404,)):
            self.refusal=refusal;response=self.client.get(base+'/assets/core/rfb.js')
            self.assertEqual(response.status_code,404,refusal)
            self.assertEqual(response.json()['detail'],'Viewer asset unavailable. Reopen the capture session.')

    def test_an_unreachable_capture_service_is_retryable_and_names_the_next_step(self):
        # AUDIT-2026-10-03 L-28 review: a transport failure may clear by itself, so it is not the refusal's
        # final 502; its own text still tells the student what to do if it persists.
        base=self.launch()
        dead=socket.socket();dead.bind(('127.0.0.1',0));port=dead.getsockname()[1];dead.close()
        self.app.state.captures.sessions=BrowserSessions(f'http://127.0.0.1:{port}','a'*64)
        response=self.client.get(base+'/assets/core/rfb.js')
        self.assertEqual(response.status_code,503)
        self.assertIn('Reconnect viewer',response.json()['detail'])

    def test_http_assets_download_cookie_isolation_and_no_credential_forwarding(self):
        base=self.launch()
        # The synthetic service serves a stand-in module; list its bytes as the pinned image's own.
        with patch.dict(capture_sessions.VIEWER_ASSETS,{'core/rfb.js':hashlib.sha256(b'export default class RFB {}').hexdigest()}):
            response=self.client.get(base+'/assets/core/rfb.js',headers={'Authorization':'unrelated browser credential'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['content-type'],'text/javascript; charset=utf-8')
        self.assertEqual(self.seen[-1]['authorization'],'Bearer '+'a'*64)
        self.assertNotIn('cookie',self.seen[-1])
        response=self.client.get(base+'/download')
        self.assertEqual(response.content,b'synthetic-tar')
        self.assertIn('wireshark-captures.tar',response.headers['content-disposition'])
        self.empty=True;response=self.client.get(base+'/download')
        self.assertEqual(response.status_code,409);self.assertIn('Save As',response.json()['detail']);self.empty=False
        with TestClient(self.app) as other:
            self.assertEqual(other.get(base+'/download').status_code,404)
        for path in ('index.html','core/test.html','app/ui.js'):
            self.assertEqual(self.client.get(base+'/assets/'+path).status_code,404)
        self.assertEqual(self.client.get(base+'/download',headers={'Origin':'https://evil'}).status_code,403)

    def test_binary_websocket_roundtrip_and_cross_origin_rejection(self):
        base=self.launch()
        with self.client.websocket_connect(base+'/websockify',headers={'Origin':'http://testserver'}) as ws:
            self.assertEqual(ws.receive_bytes(),b'RFB 003.008\n')
            ws.send_bytes(b'\x00\x01\xff');self.assertEqual(ws.receive_bytes(),b'\x00\x01\xff')
            self.assertIsNone(ws.accepted_subprotocol)
        # The relay always offers websockify's subprotocol upstream and echoes it only to a browser that asked.
        self.assertEqual(self.offered[-1],['binary'])
        with self.client.websocket_connect(base+'/websockify',headers={'Origin':'http://testserver'},subprotocols=['binary']) as ws:
            self.assertEqual(ws.accepted_subprotocol,'binary');self.assertEqual(ws.receive_bytes(),b'RFB 003.008\n')
        for origin in ('https://evil',''):
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(base+'/websockify',headers={'Origin':origin}):pass

    def test_viewer_page_has_scoped_canvas_style_policy(self):
        page=self.client.get('/static/capture-session.html')
        self.assertEqual(page.status_code,200)
        self.assertIn("style-src 'self' 'unsafe-inline'",page.headers['content-security-policy'])
        self.assertNotIn("style-src 'self' 'unsafe-inline'",self.client.get('/').headers['content-security-policy'])
