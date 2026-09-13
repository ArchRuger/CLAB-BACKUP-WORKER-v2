"""Browser session adapter. Only the separate VM service has Docker access.

The browser receives same-origin URLs, never service credentials or packet URLs.
Session ownership is browser-cookie isolation within the manager's trusted lab UI,
not a replacement for user authentication at a shared/public reverse proxy.
"""
import asyncio
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
        if not ASSET.fullmatch(path) or '..' in path:
            raise HTTPException(404)
        adapter = service()
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=15) as client:
                async with client.stream('GET', adapter.url + session_path(sid) + '/assets/' + path,
                                         headers=adapter.headers(owner(request))) as upstream:
                    if upstream.status_code != 200:
                        raise HTTPException(404, 'Viewer asset unavailable. Reopen the capture session.')
                    body = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise HTTPException(502, 'Viewer asset exceeds limit.')
            return Response(bytes(body), media_type='text/javascript')
        except httpx.HTTPError:
            raise HTTPException(502, 'Browser viewer unavailable.') from None

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
                raise HTTPException(409, 'Capture files unavailable. Check the session and save files in /pcaps first.')
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
                               proxy=None, max_size=4 * 1024 * 1024, open_timeout=15) as upstream:
                await ws.accept()
                await relay(ws, upstream)
        except (HTTPException, OSError, ValueError, WebSocketException, WebSocketDisconnect):
            pass
        finally:
            try:
                await ws.close(code=1000)
            except RuntimeError:
                pass
