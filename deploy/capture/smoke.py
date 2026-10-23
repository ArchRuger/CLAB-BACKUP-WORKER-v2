"""Live acceptance on an otherwise empty Linux Docker host (CI).

Starts only this optional stack and a capture session, generates loopback UDP,
checks noVNC's RFB greeting, the per-session VNC password challenge, the pinned
viewer modules and real capture bytes, and removes its own resources.
Run with the application's Python dependencies installed. Never use a production
capture stack: the preflight refuses any existing clab-manager-capture project.

After the single-session checks it starts a second desktop on the same namespace under
another request id and checks what the manager's capture sets rely on (C07): the two
sessions are distinct (id, container, VNC password), each id is the service's
HMAC-SHA256(token, owner + request_id), posting the first request again meets the first
session (no third container), and ending both leaves no labelled container.
"""
import argparse
import asyncio
import hashlib
import hmac
import io
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import sys
import tarfile
import time

import httpx
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'clab-backup-ui'))
from app.capture_service import IMAGE, LABEL  # noqa: E402
from app.capture_sessions import VIEWER_ASSETS  # noqa: E402


def command(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def packets(data):
    if data[:4] in (b'\xd4\xc3\xb2\xa1', b'\xa1\xb2\xc3\xd4'):
        return len(data) > 40
    if data[:4] != b'\x0a\x0d\x0d\x0a' or len(data) < 28:
        return False
    endian = '<' if data[8:12] == b'\x4d\x3c\x2b\x1a' else '>'
    offset = 0
    while offset + 12 <= len(data):
        kind, size = struct.unpack_from(endian + 'II', data, offset)
        if size < 12 or offset + size > len(data):
            return False
        if kind in (2, 3, 6):
            return True
        offset += size
    return False


def session_id(token, owner, request_id):
    """The id the service gives an owner's request: the same derivation as capture_service.Sessions.start
    and BrowserSessions.session_id, repeated here so the real service pins it."""
    return hmac.new(token.encode(), (owner + request_id).encode(), hashlib.sha256).hexdigest()


def labelled(*flags):
    return command('docker', 'ps', *flags, '--filter', 'label=' + LABEL, capture_output=True, text=True).stdout.splitlines()


def two_desktops(client, token, target, first, sid):
    """A second desktop on the same namespace with its own request id, and the first one's request posted
    again. Returns the second session's id; the caller ends both."""
    owner = client.headers['X-Capture-Owner']
    assert sid == session_id(token, owner, first['request_id']), 'The first session id is not HMAC(token, owner + request_id)'
    password = client.get('/sessions/' + sid).raise_for_status().json()['viewer_password']
    second = {'target': target, 'interfaces': ['lo'], 'request_id': secrets.token_hex(32)}
    other = client.post('/sessions', json=second).raise_for_status().json()['id']
    assert other != sid, 'A new request id must start a new session'
    assert other == session_id(token, owner, second['request_id']), 'The second session id is not HMAC(token, owner + request_id)'
    assert {row['id'] for row in client.get('/sessions').raise_for_status().json()['sessions']} == {sid, other}
    status = client.get('/sessions/' + other).raise_for_status().json()
    assert len(status['viewer_password']) == 8 and status['viewer_password'] != password, 'Desktops must not share a VNC password'
    names = labelled('--format', '{{.Names}}')
    first_name, second_name = (next(n for n in names if n.endswith(i)) for i in (sid, other))
    assert first_name != second_name
    # The same body again (the manager's retry after a lost reply) meets the first session.
    again = client.post('/sessions', json=first).raise_for_status().json()
    assert again['id'] == sid, 'The same request id must answer the same session'
    assert {row['id'] for row in client.get('/sessions').raise_for_status().json()['sessions']} == {sid, other}
    assert sorted(labelled('--format', '{{.Names}}')) == sorted([first_name, second_name]), 'The repeated request created a container'
    return other


def eventually(callback, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = callback()
            if result:
                return result
        except (httpx.HTTPError, ValueError, KeyError, StopIteration):
            pass
        time.sleep(2)
    raise AssertionError('Capture smoke readiness timed out')


def main():
    argparse.ArgumentParser(description=__doc__.split('\n\n')[0]).parse_args()
    existing = command('docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=clab-manager-capture',
                       capture_output=True, text=True).stdout.strip()
    if existing:
        sys.exit('Refusing to touch an existing capture stack. Run on an isolated Docker host.')
    if command('docker', 'ps', '-aq', '--filter', 'label=' + LABEL,
               capture_output=True, text=True).stdout.strip():
        sys.exit('Refusing to touch existing capture session containers. Use an isolated Docker host.')
    env = {**os.environ, 'CAPTURE_SESSION_TOKEN': secrets.token_hex(32)}
    compose = ['docker', 'compose', '-f', str(ROOT / 'deploy/compose.capture.yml')]
    headers = {'Authorization': 'Bearer ' + env['CAPTURE_SESSION_TOKEN'], 'X-Capture-Owner': secrets.token_hex(32)}
    client = httpx.Client(base_url='http://127.0.0.1:5801', headers=headers, timeout=45, trust_env=False)
    try:
        command('docker', 'pull', IMAGE)
        command(*compose, 'up', '-d', '--build', env=env)
        eventually(lambda: client.get('/health').raise_for_status().json()['ready'])

        def discover():
            data = httpx.get('http://127.0.0.1:5001/discover/mobyshark', timeout=15, trust_env=False).raise_for_status().json()
            return next(t for t in data['containers'] if t.get('type') == 'proc' and t.get('pid') == 1 and 'lo' in t.get('network-interfaces', []))
        target = eventually(discover)
        first = {'target': target, 'interfaces': ['lo'], 'request_id': secrets.token_hex(32)}
        result = client.post('/sessions', json=first).raise_for_status().json()
        sid = result['id']
        eventually(lambda: client.get('/sessions/' + sid + '/assets/core/rfb.js').raise_for_status().content)
        # The service relays a module only when it is the pinned image's own bytes.
        for path in VIEWER_ASSETS:
            client.get('/sessions/' + sid + '/assets/' + path).raise_for_status()
        assert len(client.get('/sessions/' + sid).raise_for_status().json()['viewer_password']) == 8

        async def greeting():
            async with connect('ws://127.0.0.1:5801/sessions/' + sid + '/websockify',
                               additional_headers=headers, proxy=None) as ws:
                message = await asyncio.wait_for(ws.recv(), timeout=15)
                assert message.startswith(b'RFB 003.'), 'No real noVNC RFB greeting'
                # Desktops share one network: each demands its own session's VNC password.
                await ws.send(b'RFB 003.008\n')
                types = b''
                while not types or len(types) < 1 + types[0]:
                    types += await asyncio.wait_for(ws.recv(), timeout=15)
                assert list(types[1:1 + types[0]]) == [2], 'The desktop must offer only VNC password authentication'
        asyncio.run(greeting())
        names = command('docker', 'ps', '--format', '{{.Names}}', '--filter', 'label=' + LABEL,
                        capture_output=True, text=True).stdout.splitlines()
        name = next(n for n in names if n.endswith(sid))
        # The raw VNC port stays closed; the web port answering proves the probe itself works.
        probe = ['docker', 'exec', name, 'nc', '-w3', '-z', '127.0.0.1']
        assert subprocess.run(probe + ['5800'], capture_output=True).returncode == 0, 'Port probe unavailable'
        assert subprocess.run(probe + ['5900'], capture_output=True).returncode != 0, 'Raw VNC port 5900 is open'

        # Nothing saved yet: the download must say so instead of handing over an empty archive.
        assert client.get('/sessions/' + sid + '/download').status_code == 409, 'Empty /pcaps must not download'

        def captured():
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                for _ in range(20):
                    udp.sendto(b'clab-browser-capture-smoke', ('127.0.0.1', 59999))
            # Wireshark writes its live file to a tmpfs, which docker cp never sees; read
            # it from inside the container. tar may report the growing file as changed.
            content = subprocess.run(['docker', 'exec', name, 'tar', '-C', '/tmp', '-cf', '-', '.'],
                                     capture_output=True).stdout
            with tarfile.open(fileobj=io.BytesIO(content)) as archive:
                for entry in archive:
                    if entry.isfile() and 0 < entry.size < 16 * 1024 * 1024:
                        data = archive.extractfile(entry).read()
                        if packets(data):
                            return data
            return None
        data = eventually(captured)
        # Exercise download with actual captured bytes, without automating Qt menus.
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w') as archive:
            entry = tarfile.TarInfo('smoke.pcapng');entry.size = len(data);entry.mode = 0o600;entry.uid = 1000
            archive.addfile(entry, io.BytesIO(data))
        # Save the way Wireshark does: as the desktop user, inside the container's /pcaps.
        command('docker', 'exec', '-i', '-u', '1000:1000', name, 'tar', '-C', '/pcaps', '-xf', '-',
                input=stream.getvalue(), capture_output=True)
        download = client.get('/sessions/' + sid + '/download').raise_for_status()
        with tarfile.open(fileobj=io.BytesIO(download.content)) as archive:
            entry = next(e for e in archive if e.name.endswith('smoke.pcapng'))
            assert archive.extractfile(entry).read() == data
        other = two_desktops(client, env['CAPTURE_SESSION_TOKEN'], target, first, sid)
        for ended in (sid, other):
            client.post('/sessions/' + ended + '/end', json={}).raise_for_status()
        assert not client.get('/sessions').json()['sessions']
        assert not labelled('-a', '-q'), 'A capture container outlived its session'
        print('PASS: real Wireshark/extcap stream, noVNC RFB, saved capture download, two concurrent desktops with idempotent '
              'request ids, and cleanup.')
    finally:
        client.close()
        command(*compose, 'down', '--remove-orphans', env=env)


if __name__ == '__main__':
    main()
