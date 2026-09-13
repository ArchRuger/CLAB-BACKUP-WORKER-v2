"""Optional VM-side Wireshark session service, run separately from the manager.

Docker operations are fixed and apply only to this service's labelled containers.
No browser/client can supply an image, command, mount, port, network or URL.
"""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import hmac
import ipaddress
import json
import os
import re
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from .capture import CaptureError, EdgesharkProvider, IDENTITY_FIELDS, normalize_target
from .capture_sessions import ASSET, TOKEN, relay

IMAGE = 'ghcr.io/srl-labs/wireshark-vnc-docker@sha256:682c8bd42282c44f991e0d6015ce3303e5a3aa08a1e2c2b6937fd554ddb31186'
LABEL = 'org.clab-manager.capture-owner'
IDLE_SECONDS = 15 * 60
LIFETIME_SECONDS = 2 * 60 * 60
MAX_SESSIONS = 4
# Saved captures live on a tmpfs-backed anonymous volume, not a container tmpfs: the
# Docker archive API behind the download reads the container filesystem through the
# daemon, which sees volumes but never a tmpfs mounted inside the container.
PCAPS_VOLUME_OPTIONS = 'size=256m,uid=1000,gid=1000,mode=0700,nosuid,nodev,noexec'
# The pinned image's websockify only completes the handshake for this subprotocol.
VNC_SUBPROTOCOL = 'binary'
VOLUME_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$')


def _chain(first, rest):
    yield first
    yield from rest


def tar_has_regular_file(buffer):
    """True when a tar stream prefix holds at least one regular file entry."""
    offset = 0
    while offset + 512 <= len(buffer):
        header = buffer[offset:offset + 512]
        if header == b'\0' * 512:
            return False
        try:
            size = int(header[124:136].split(b'\0', 1)[0].strip() or b'0', 8)
        except ValueError:
            return False
        if header[156:157] in (b'0', b'\0', b'7'):
            return True
        offset += 512 + ((size + 511) // 512) * 512
    return False


class StartRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target: dict
    interfaces: list[str] = Field(min_length=1, max_length=128)
    request_id: str = Field(pattern=r'^[0-9a-f]{64}$')


class Sessions:
    def __init__(self, token, network='clab-manager-capture', docker=None, provider=None):
        if not TOKEN.fullmatch(token):
            raise ValueError('CAPTURE_SESSION_TOKEN must be 64 hexadecimal characters; run setup-capture.sh.')
        self.token = token
        # Stable deployment ownership survives token rotation and source upgrades.
        # This stack has one fixed Docker network and one localhost service port.
        self.label = 'clab-manager-capture-v1'
        self.network = network
        self.docker = docker or httpx.Client(transport=httpx.HTTPTransport(uds='/var/run/docker.sock'),
                                            base_url='http://docker', timeout=30, trust_env=False)
        self.provider = provider or EdgesharkProvider('http://packetflix:5001')
        self.rows = {}
        self.pending = set()
        self.lock = asyncio.Lock()

    def auth(self, request):
        if not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + self.token):
            raise HTTPException(403, 'Capture service authentication required.')

    def owner(self, request):
        self.auth(request)
        who = request.headers.get('x-capture-owner', '')
        if not TOKEN.fullmatch(who):
            raise HTTPException(403, 'Browser ownership required.')
        return who

    def docker_request(self, method, path, **kwargs):
        try:
            response = self.docker.request(method, path, **kwargs)
            if response.status_code >= 400:
                raise HTTPException(503, 'Docker operation failed. Check capture service configuration.')
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, 'Docker unavailable.') from None

    def remove(self, name):
        # Only deterministic names generated here, never caller-supplied container IDs.
        try:
            response = self.docker.delete('/containers/' + name, params={'force': 'true', 'v': 'true'})
        except httpx.HTTPError:
            raise HTTPException(503, 'Could not reach Docker for session cleanup; retry shortly.') from None
        if response.status_code not in (204, 404):
            raise HTTPException(503, 'Could not remove the capture container; retry End session.')

    def cleanup_orphans(self):
        rows = self.docker_request('GET', '/containers/json', params={
            'all': 'true', 'filters': json.dumps({'label': [LABEL + '=' + self.label]})})
        for row in rows:
            # Recheck the label even if a daemon ignores filters.
            if row.get('Labels', {}).get(LABEL) == self.label:
                self.remove(row['Id'])
        # A container removal always carries v=true; still sweep capture volumes left
        # behind by a forced removal without it, so saved captures never outlive a session.
        volumes = self.docker_request('GET', '/volumes', params={
            'filters': json.dumps({'label': [LABEL + '=' + self.label], 'dangling': ['true']})})
        for volume in volumes.get('Volumes') or []:
            name = volume.get('Name', '')
            if volume.get('Labels', {}).get(LABEL) == self.label and VOLUME_NAME.fullmatch(name):
                try:
                    self.docker.delete('/volumes/' + name)
                except httpx.HTTPError:
                    print('Capture volume cleanup failed; automatic cleanup will retry.', flush=True)

    def reap(self):
        for name in list(self.pending):
            self.remove(name)
            self.pending.discard(name)
        now = time.monotonic()
        for sid, row in list(self.rows.items()):
            if now - row['seen'] >= IDLE_SECONDS or now - row['created'] >= LIFETIME_SECONDS:
                self.remove(row['container'])
                del self.rows[sid]

    def get(self, sid, who, touch=True):
        row = self.rows.get(sid)
        if not row or not hmac.compare_digest(row['owner'], who):
            raise HTTPException(404, 'Session not found.')
        now = time.monotonic()
        if now - row['seen'] >= IDLE_SECONDS or now - row['created'] >= LIFETIME_SECONDS:
            raise HTTPException(404, 'Session expired.')
        if touch:
            row['seen'] = now
        return row

    def public(self, sid, row):
        remaining = max(0, int(LIFETIME_SECONDS - (time.monotonic() - row['created'])))
        return {'id': sid, 'name': row['name'], 'interfaces': row['interfaces'],
                'remaining_seconds': remaining, 'idle_seconds': IDLE_SECONDS}

    def start(self, data, who):
        self.reap()
        sid = hmac.new(self.token.encode(), (who + data.request_id).encode(), hashlib.sha256).hexdigest()
        if sid in self.rows:
            return self.public(sid, self.get(sid, who))
        if len(self.rows) >= MAX_SESSIONS:
            raise HTTPException(429, 'Session capacity reached.')
        try:
            requested = normalize_target(data.target)
            current = next((t for t in self.provider.discover()
                            if all(t[k] == requested[k] for k in IDENTITY_FIELDS)), None)
        except CaptureError:
            raise HTTPException(503, 'Capture discovery unavailable.') from None
        if (current is None or len(set(data.interfaces)) != len(data.interfaces)
                or any(n not in current['network-interfaces'] for n in data.interfaces)):
            raise HTTPException(409, 'Capture target changed.')
        name = 'clab-capture-' + self.label + '-' + sid
        spec = {
            'Image': IMAGE,
            'Labels': {LABEL: self.label},
            'Env': ['PACKETFLIX_LINK=' + self.provider.stream_uri(current, data.interfaces),
                    'WEB_TERMINAL=0', 'WEB_FILE_MANAGER=0', 'WEB_AUDIO=0', 'WEB_NOTIFICATION=0',
                    'KEEP_APP_RUNNING=0', 'USER_ID=1000', 'GROUP_ID=1000'],
            'HostConfig': {'NetworkMode': self.network, 'Memory': 1024 * 1024 * 1024,
                           'NanoCpus': 1500000000, 'PidsLimit': 256, 'ShmSize': 64 * 1024 * 1024,
                           'CapDrop': ['NET_RAW'], 'SecurityOpt': ['no-new-privileges:true'],
                           'Mounts': [{'Type': 'volume', 'Target': '/pcaps', 'VolumeOptions': {
                               'Labels': {LABEL: self.label},
                               'DriverConfig': {'Name': 'local', 'Options': {
                                   'type': 'tmpfs', 'device': 'tmpfs', 'o': PCAPS_VOLUME_OPTIONS}}}}],
                           'Tmpfs': {'/config': 'rw,nosuid,nodev,size=64m', '/tmp': 'rw,nosuid,nodev,size=256m'},
                           'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '2m', 'max-file': '1'}}}}
        self.pending.add(name)
        try:
            self.docker_request('POST', '/containers/create', params={'name': name}, json=spec)
            self.docker_request('POST', '/containers/' + name + '/start')
            info = self.docker_request('GET', '/containers/' + name + '/json')
            address = str(ipaddress.IPv4Address(info['NetworkSettings']['Networks'][self.network]['IPAddress']))
            if not info['State']['Running']:
                raise ValueError('Container did not start')
        except Exception:
            # The fixed name also recovers a create whose HTTP reply was lost.
            try:
                self.remove(name)
                self.pending.discard(name)
            except Exception:
                # Sweep and startup reconciliation retry this labelled container.
                print('Capture creation cleanup failed; automatic cleanup will retry.', flush=True)
            raise HTTPException(503, 'Wireshark could not start. Pull the pinned image and check service logs.') from None
        now = time.monotonic()
        self.pending.discard(name)
        self.rows[sid] = {'owner': who, 'container': name, 'address': address, 'created': now,
                          'seen': now, 'name': current['name'], 'interfaces': data.interfaces}
        return self.public(sid, self.rows[sid])


def create_app(sessions=None):
    sessions = sessions or Sessions(os.environ.get('CAPTURE_SESSION_TOKEN', ''))

    async def sweep():
        while True:
            await asyncio.sleep(15)
            try:
                async with sessions.lock:
                    await asyncio.to_thread(sessions.reap)
            except Exception:
                print('Capture cleanup could not reach Docker; will retry.', flush=True)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(sessions.cleanup_orphans)
        task = asyncio.create_task(sweep())
        try:
            yield
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.to_thread(sessions.cleanup_orphans)
            sessions.docker.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get('/health')
    def health(request: Request):
        sessions.auth(request)
        sessions.docker_request('GET', '/images/' + IMAGE + '/json')
        return {'ready': True, 'max_sessions': MAX_SESSIONS}

    @app.post('/sessions')
    async def start(data: StartRequest, request: Request):
        who = sessions.owner(request)
        async with sessions.lock:
            return await asyncio.to_thread(sessions.start, data, who)

    @app.get('/sessions')
    async def listing(request: Request):
        who = sessions.owner(request)
        async with sessions.lock:
            await asyncio.to_thread(sessions.reap)
            return {'sessions': [sessions.public(sid, row) for sid, row in sessions.rows.items()
                                 if hmac.compare_digest(row['owner'], who)]}

    @app.get('/sessions/{sid}')
    def status(sid: str, request: Request):
        row = sessions.get(sid, sessions.owner(request))
        info = sessions.docker_request('GET', '/containers/' + row['container'] + '/json')
        return {**sessions.public(sid, row), 'running': bool(info['State']['Running'])}

    @app.post('/sessions/{sid}/end')
    async def end(sid: str, request: Request):
        who = sessions.owner(request)
        async with sessions.lock:
            row = sessions.get(sid, who)
            await asyncio.to_thread(sessions.remove, row['container'])
            del sessions.rows[sid]
            return {'ended': True}

    @app.get('/sessions/{sid}/assets/{path:path}')
    async def asset(sid: str, path: str, request: Request):
        row = sessions.get(sid, sessions.owner(request))
        if not ASSET.fullmatch(path) or '..' in path:
            raise HTTPException(404)
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
                async with client.stream('GET', 'http://' + row['address'] + ':5800/' + path) as upstream:
                    if upstream.status_code != 200:
                        raise HTTPException(503, 'Viewer starting; retry shortly.')
                    body = bytearray()
                    async for chunk in upstream.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise HTTPException(502)
            return Response(bytes(body), media_type='text/javascript')
        except httpx.HTTPError:
            raise HTTPException(503, 'Viewer starting; retry shortly.') from None

    @app.get('/sessions/{sid}/download')
    def download(sid: str, request: Request):
        row = sessions.get(sid, sessions.owner(request))
        upstream = sessions.docker.send(sessions.docker.build_request('GET',
            '/containers/' + row['container'] + '/archive', params={'path': '/pcaps'}), stream=True)
        if upstream.status_code != 200:
            upstream.close()
            raise HTTPException(409, 'Save captures in /pcaps first.')
        chunks = upstream.iter_bytes(65536)
        first = next(chunks, b'')
        # An archive of an empty folder is only the directory entry plus padding, so a
        # short first chunk without any file means nothing was saved yet.
        if len(first) < 65536 and not tar_has_regular_file(first):
            upstream.close()
            raise HTTPException(409, 'No saved captures yet. In Wireshark stop the capture, use File > Save As '
                                     'under /pcaps and type the full file name ending in .pcapng (Wireshark '
                                     'on the VM does not add the extension), then download again.')

        def content():
            total = 0
            try:
                for chunk in _chain(first, chunks):
                    total += len(chunk)
                    if total > 272 * 1024 * 1024:
                        raise RuntimeError('Capture archive exceeded limit')
                    yield chunk
            finally:
                upstream.close()
        return StreamingResponse(content(), media_type='application/x-tar')

    @app.websocket('/sessions/{sid}/websockify')
    async def desktop(ws: WebSocket, sid: str):
        try:
            row = sessions.get(sid, sessions.owner(ws))
            # websockify in the pinned image answers 400 to a handshake that does not
            # offer the binary subprotocol; the manager's relay offers it as well.
            async with connect('ws://' + row['address'] + ':5800/websockify', proxy=None,
                               subprotocols=[VNC_SUBPROTOCOL], max_size=4 * 1024 * 1024,
                               open_timeout=10) as upstream:
                await ws.accept(subprotocol=VNC_SUBPROTOCOL if VNC_SUBPROTOCOL in ws.scope.get('subprotocols', []) else None)
                await relay(ws, upstream)
        except (HTTPException, OSError, ValueError, WebSocketException, WebSocketDisconnect):
            pass
        finally:
            try:
                await ws.close(code=1000)
            except RuntimeError:
                pass
    return app
