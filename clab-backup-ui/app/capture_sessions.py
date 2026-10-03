"""Browser session adapter. Only the separate VM service has Docker access.

The browser receives same-origin URLs, never service credentials or packet URLs.
Session ownership is browser-cookie isolation within the manager's trusted lab UI,
not a replacement for user authentication at a shared/public reverse proxy.
"""
import asyncio
import hashlib
import json
import re
import secrets
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

TOKEN = re.compile(r'^[0-9a-f]{64}$')
ASSET = re.compile(r'^(?:core|vendor)/(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_.-]+\.js$')
COOKIE = 'clab_capture_owner'
# noVNC in the pinned image offers no subprotocol; websockify behind the service
# requires this one, so the relay offers it upstream and echoes it back only when
# a browser asked for it (a browser drops a connection whose reply ignores its offer).
VNC_SUBPROTOCOL = 'binary'
# The pinned desktop image's noVNC client: core/rfb.js and every module it imports,
# byte for byte. They run as the manager's own JavaScript, so whatever else a desktop
# serves (a compromised container, a changed image) is refused, never relayed. A new
# image pin needs its list from deploy/capture/viewer_assets.py.
VIEWER_IMAGE = 'sha256:682c8bd42282c44f991e0d6015ce3303e5a3aa08a1e2c2b6937fd554ddb31186'
VIEWER_ASSETS = {
    'core/base64.js': '76d6b7ec73aed8cbc72b49b8b865bcb334acc59a6b0e96b19bc39c9e8e053ae3',
    'core/crypto/aes.js': '00b9a69185f913b882270c4cc7a076b4dd3a083981edb91c1e55db22f8ffcef3',
    'core/crypto/bigint.js': 'e7880d27af8bf439579f6fc40d7b81fd379a9babb1d13c83999effd8c64823ab',
    'core/crypto/crypto.js': 'e6006697ce1d195c951ef1e986172d17174e533909df19e07be583ac75dd344b',
    'core/crypto/des.js': '91d8c8ed596d2beda7da9dd68c9ae1d325c673822e3ccfc8a4091e121c99a316',
    'core/crypto/dh.js': '9102454282ba646ee4a4ce34c5db5d2a9979179f9d4606737fc6bb7a669e5ebe',
    'core/crypto/md5.js': '364c0f0d44d3f8fd608c18a0e1253e5a77e9b8e4c48e3c6503a0f45c9bb2ff8d',
    'core/crypto/rsa.js': '83875db9e5d978ea0eb2a1e2af8afbb7dedfb0f18eca2bab75c2756285037476',
    'core/decoders/copyrect.js': 'da3b571e10984438ea49559738e11034b5d0c85154a68eac1a6bf9ef10e5aa02',
    'core/decoders/h264.js': '96d47901c5e26dc02256b152aa642490d936bbcc395f59ffd580356118edff84',
    'core/decoders/hextile.js': '63eb86247bea83119af75f3d145a4515a2411ff28a72492d2d7b925268d50163',
    'core/decoders/jpeg.js': '6747ac900d09a5899c3a6fff897e58e88607e69b39ff4a6bddddee2e9e6bc6b4',
    'core/decoders/raw.js': 'bc7d4517213dc1df8626e8198eadf32b2c1946f75228b31387d3916963af0727',
    'core/decoders/rre.js': 'b3380dbc75310769ef24e956e1fa1f13d8217f8b1d7d6f5c9d08db9a336a4c0d',
    'core/decoders/tight.js': 'a7f01df99922be812ea21c5e46597b76379a5d8267f99ec8bea9a202bec34130',
    'core/decoders/tightpng.js': '38bd2fd200f5c8e9b0905eca2389fb8e6ad2151de886e4fa9a9c59cc1c7696f0',
    'core/decoders/zlib.js': '1d1c05cdca4840ff46082103ab35aa7696b41504bec91ebd74fae9e0e5f61380',
    'core/decoders/zrle.js': '6853c115f97a1d4de39ca71ab8b519a05916bb8c173aa8112ce4881cbb612cbd',
    'core/deflator.js': 'ceb6763eb3fcc53f34d08534a8d1df9b63af3a95c58f8d96d238ef5ce639ad1f',
    'core/display.js': '10d298551124a172c97dcb54d8d30fca416e6038b064c93ba5f7cf079fa4bf1f',
    'core/encodings.js': '4975904fe1da6dc22b53ecb8462ec7c9a43e99db72dba4aab9f625c4177e355d',
    'core/inflator.js': 'b1955cbd1608619911b8dfd451fae07f38c5767098f6f47e4a2a1682c11feb65',
    'core/input/domkeytable.js': '5eb985e1a412d1be6b606ba0d7e912fc0842d873d252bd7ec8a363670dfc800c',
    'core/input/fixedkeys.js': '6bb21b0a2d5f5d7ad73e75b80ddc1d844ac770c4426b312d5740f2443455f0c0',
    'core/input/gesturehandler.js': 'c04b67fdae6ac061c7d51cb5ee8ca296ee9c7c80aa246cee5751e74eefe61758',
    'core/input/keyboard.js': '42c5ac0b0a40f327ec93633a0494a19c7980937c6e8f3061d1e136cffb37e077',
    'core/input/keysym.js': '4ddf0e21f07328358974d91aa2d7f839ba2116688b28e43d3f6f4e2eae8c45cf',
    'core/input/keysymdef.js': '76f338d45fb73b7decb7d8b4ef6e95edf7ce9583722c5220642a9be85fc2cc89',
    'core/input/util.js': '2e156ea656404afcb6cc54dd85cbe5dd2dd0ba209ae9a6fb1b78ec5db17d01ce',
    'core/input/vkeys.js': '9a1ce4393e1aa4ace5dcdcf7e032f4a1c03a9cb964b4e0e7b7fcffd3a982eb84',
    'core/input/xtscancodes.js': 'f0fc982627e1c02feaac1bd50d7fdd3bcbb05f0062b910d8002f47d1b08967a6',
    'core/ra2.js': '4aeffb60af9c163365170e2af392acb6f0a7c21a0cb6827f85dd776d33277bee',
    'core/rfb.js': '4beefd5022d8d828dee3331220b62f3870a1ab648aba84a50cf9469c97209b3f',
    'core/util/browser.js': '592f56dc2195331c3b8329f8e51fa3a444a89ac85d5fa29e2364508aa9303df7',
    'core/util/cursor.js': 'adabe605d73f38e5f29abd302489d4b9e98a9e495823a06a2edbe7f6744856fa',
    'core/util/element.js': '13845321fc5abccc1de25594082d8db15405af56c5f4fc32b3bdd0878bd891e3',
    'core/util/events.js': 'ec7f4da0407ea67f5d6f5ce53bd9b3342155feb9407707de3992c5261e460ead',
    'core/util/eventtarget.js': '9481965aa6cee36ae2decdccc6ca5203c9371a8afc33346ad4170e471766e0da',
    'core/util/int.js': 'b1c4b7dec2e7767322b3464f3c186b13138cdf341c621db44ddd06ce78180c01',
    'core/util/logging.js': 'c3a49715c9f908d5bb385de5787e99b824faf34d26036d993eea4740bac9d482',
    'core/util/strings.js': '77d0604c7bf9e95de780f8cb9764d918ae24c86811a0a1c5b08cd30e50ad2a3a',
    'core/websock.js': 'd1a96fc1316eaab9badcba9b0f1a7a55d748a4d4d26dc0263cc179dba2131cf4',
    'vendor/pako/lib/utils/common.js': '0749bc4661ed186714b90e7f2321c9625a8ce7c680563bfe3ac6df7aa332bf28',
    'vendor/pako/lib/zlib/adler32.js': '7412dd3ecc015888b99292f45e4d4ba69abc77f208508c9a1c93e8dfe54ba6cd',
    'vendor/pako/lib/zlib/crc32.js': '897fa9eabd2bb239ec632326dbff85bc72cc81d4da80265cde59520db339f405',
    'vendor/pako/lib/zlib/deflate.js': 'd2a498ad04bb5d1f67ba01696c31a2e88e8b88e4fc6c36c635294d1c445b22c1',
    'vendor/pako/lib/zlib/inffast.js': 'ec1e0f7abeec681a0d5e3da46d06f499969cbf265eaaa5e21a135d2a9b878c16',
    'vendor/pako/lib/zlib/inflate.js': '321582ddc4023e47aa981a71caed0e1dad8b58f0d9e93a0b0a34fe7e3c45e05f',
    'vendor/pako/lib/zlib/inftrees.js': '94780cbdef562bcd0434c7e6f4faca1ff6be6980bf7305a200809d98d419d9c7',
    'vendor/pako/lib/zlib/messages.js': '7860a8d3c873c28e4f5f92db9ca3e45006e21b084210d87b8b7775cddccf05ed',
    'vendor/pako/lib/zlib/trees.js': 'ad9cb5245b9e39edd164234d6ca19febb9dba683f1f99a67af48d62931d91426',
    'vendor/pako/lib/zlib/zstream.js': '240917347c379b1ad33b8bf07cc6981557173bc3408f35e9875866a14b9967b2',
}


def viewer_asset(path, body):
    """Whether body is the pinned image's own copy of this noVNC module."""
    return path in VIEWER_ASSETS and hashlib.sha256(body).hexdigest() == VIEWER_ASSETS[path]


def owner(request, response=None):
    value = request.cookies.get(COOKIE, '')
    if not TOKEN.fullmatch(value):
        if response is None:
            raise HTTPException(404, 'Capture session not found in this browser.')
        value = secrets.token_hex(32)
        response.set_cookie(COOKIE, value, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', path='/api/capture', max_age=86400)
    return value


async def relay(ws, upstream):
    """Bounded binary noVNC bridge; disconnect either end cancels the other."""
    async def incoming():
        while True:
            event = await ws.receive()
            if event['type'] == 'websocket.disconnect':
                raise WebSocketDisconnect(event.get('code', 1000))
            message = event.get('bytes')
            if not isinstance(message, bytes):
                raise ValueError('Expected binary VNC data')
            if len(message) > 4 * 1024 * 1024:
                raise ValueError('VNC frame too large')
            await upstream.send(message)

    async def outgoing():
        async for message in upstream:
            if not isinstance(message, bytes):
                raise ValueError('Expected binary VNC data')
            await ws.send_bytes(message)

    tasks = [asyncio.create_task(incoming()), asyncio.create_task(outgoing())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


class BrowserSessions:
    def __init__(self, url, token):
        from .capture import CaptureError, service_url
        self.url = service_url(url)
        if not TOKEN.fullmatch(token):
            raise CaptureError('Run deploy/setup-capture.sh to configure the browser capture service and its token.')
        self.token = token

    def headers(self, who=''):
        return {'Authorization': 'Bearer ' + self.token, 'X-Capture-Owner': who}

    def request(self, method, path, who='', data=None):
        try:
            with httpx.Client(trust_env=False, timeout=45) as client:
                result = client.request(method, self.url + path, headers=self.headers(who), json=data)
            if result.status_code >= 400:
                code = result.status_code if result.status_code in (404, 409, 429, 503) else 502
                messages = {404: 'Capture session ended or is not owned by this browser.',
                            409: 'Capture target changed. Refresh interfaces and retry.',
                            429: 'All browser capture slots are in use. End a session or wait for expiry.',
                            503: 'Browser capture service is not ready. Run Capture setup and check its logs.'}
                raise HTTPException(code, messages.get(code, 'Browser capture service failed. Check its logs.'))
            value = result.json()
            if not isinstance(value, dict):
                raise ValueError('Invalid capture service response')
            return value
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, 'Cannot reach the browser capture service. Check Capture setup and retry.') from None


def install(app, captures):
    def service():
        if not captures.sessions:
            raise HTTPException(503, captures.error or 'Browser capture is disabled. Follow Capture setup.')
        return captures.sessions

    def session_path(sid):
        if not TOKEN.fullmatch(sid):
            raise HTTPException(404, 'Capture session not found.')
        return 'sessions/' + sid

    @app.get('/api/capture/health')
    def health():
        return service().request('GET', 'health')

    @app.get('/api/capture/sessions')
    def sessions(request: Request, response: Response):
        return service().request('GET', 'sessions', owner(request, response))

    @app.get('/api/capture/sessions/{sid}')
    def session(sid: str, request: Request):
        return service().request('GET', session_path(sid), owner(request))

    @app.post('/api/capture/sessions/{sid}/end')
    def end(sid: str, request: Request):
        result = service().request('POST', session_path(sid) + '/end', owner(request), {})
        captures.store.event('capture.end', 'Ended browser Wireshark session and removed its temporary files.')
        return result

    @app.get('/api/capture/sessions/{sid}/assets/{path:path}')
    async def asset(sid: str, path: str, request: Request):
        if not ASSET.fullmatch(path) or '..' in path or path not in VIEWER_ASSETS:
            raise HTTPException(404)
        adapter = service()
        # 502 is final (waiting never changes a refused file); 404 and 503 are what the viewer waits on.
        refused = ('The Wireshark desktop served a viewer file that is not the pinned one, so it was not '
                   'opened. End this session and start a new capture.')
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
                async with client.stream('GET', adapter.url + session_path(sid) + '/assets/' + path,
                                         headers=adapter.headers(owner(request))) as upstream:
                    if upstream.status_code == 502:
                        # The service already refused the file (not pinned, or over its size limit).
                        raise HTTPException(502, refused)
                    if upstream.status_code != 200:
                        raise HTTPException(404, 'Viewer asset unavailable. Reopen the capture session.')
                    body = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise HTTPException(502, refused)
            if not viewer_asset(path, bytes(body)):
                raise HTTPException(502, refused)
            return Response(bytes(body), media_type='text/javascript')
        except httpx.HTTPError:
            # The service may be restarting or slow; this can clear by itself, so it is retryable.
            raise HTTPException(503, 'Browser viewer unavailable. Click Reconnect viewer to try again.') from None

    @app.get('/api/capture/sessions/{sid}/download')
    async def download(sid: str, request: Request):
        adapter = service()
        path = session_path(sid) + '/download'
        who = owner(request)
        client = httpx.AsyncClient(trust_env=False, timeout=60)
        try:
            upstream = await client.send(client.build_request('GET', adapter.url + path,
                                         headers=adapter.headers(who)), stream=True)
            if upstream.status_code != 200:
                # The service explains why (nothing saved yet, session gone); pass its
                # own wording through, never the transport or Docker output.
                detail = ''
                try:
                    detail = (json.loads(await upstream.aread()) or {}).get('detail', '')
                except ValueError:
                    pass
                await upstream.aclose()
                if upstream.status_code == 404:
                    raise HTTPException(404, 'Capture session ended or is not owned by this browser.')
                raise HTTPException(409, detail if isinstance(detail, str) and detail else
                                    'Capture files unavailable. Check the session and save files in /pcaps first.')
        except (httpx.HTTPError, HTTPException) as error:
            await client.aclose()
            if isinstance(error, HTTPException):
                raise
            raise HTTPException(502, 'Capture download unavailable.') from None

        async def close():
            await upstream.aclose()
            await client.aclose()

        async def content():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await close()
        return StreamingResponse(content(), media_type='application/x-tar',
                                 headers={'Content-Disposition': 'attachment; filename="wireshark-captures.tar"'},
                                 background=BackgroundTask(close))

    @app.websocket('/api/capture/sessions/{sid}/websockify')
    async def desktop(ws: WebSocket, sid: str):
        origin = urlsplit(ws.headers.get('origin', ''))
        scheme = 'https' if ws.url.scheme == 'wss' else 'http'
        if origin.scheme != scheme or origin.netloc != ws.url.netloc or not TOKEN.fullmatch(sid):
            await ws.close(code=1008)
            return
        try:
            adapter = service()
            headers = adapter.headers(owner(ws))
            url = adapter.url.replace('https:', 'wss:', 1).replace('http:', 'ws:', 1)
            async with connect(url + session_path(sid) + '/websockify', additional_headers=headers,
                               subprotocols=[VNC_SUBPROTOCOL], proxy=None, max_size=4 * 1024 * 1024,
                               open_timeout=15) as upstream:
                await ws.accept(subprotocol=VNC_SUBPROTOCOL if VNC_SUBPROTOCOL in ws.scope.get('subprotocols', []) else None)
                await relay(ws, upstream)
        except (HTTPException, OSError, ValueError, WebSocketException, WebSocketDisconnect):
            pass
        finally:
            try:
                await ws.close(code=1000)
            except RuntimeError:
                pass
