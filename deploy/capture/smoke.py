"""Live acceptance on an otherwise empty Linux Docker host (CI).

Starts only this optional stack and a capture session, generates loopback UDP,
checks noVNC's RFB greeting and real capture bytes, and removes its own resources.
Run with the application's Python dependencies installed. Never use a production
capture stack: the preflight refuses any existing clab-manager-capture project.
"""
import asyncio
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
    existing = command('docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=clab-manager-capture',
                       capture_output=True, text=True).stdout.strip()
    if existing:
        sys.exit('Refusing to touch an existing capture stack. Run on an isolated Docker host.')
    if command('docker', 'ps', '-aq', '--filter', 'label=' + LABEL,
               capture_output=True, text=True).stdout.strip():
        sys.exit('Refusing to touch existing capture session containers. Use an isolated Docker host.')
    env = {**os.environ, 'CAPTURE_SESSION_TOKEN': secrets.token_hex(32), 'CAPTURE_BIND': '127.0.0.1', 'CAPTURE_PORT': '5001'}
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
        result = client.post('/sessions', json={'target': target, 'interfaces': ['lo'], 'request_id': secrets.token_hex(32)}).raise_for_status().json()
        sid = result['id']
        eventually(lambda: client.get('/sessions/' + sid + '/assets/core/rfb.js').raise_for_status().content)

        async def greeting():
            async with connect('ws://127.0.0.1:5801/sessions/' + sid + '/websockify',
                               additional_headers=headers, proxy=None) as ws:
                message = await asyncio.wait_for(ws.recv(), timeout=15)
                assert message.startswith(b'RFB 003.'), 'No real noVNC RFB greeting'
        asyncio.run(greeting())
        names = command('docker', 'ps', '--format', '{{.Names}}', '--filter', 'label=' + LABEL,
                        capture_output=True, text=True).stdout.splitlines()
        name = next(n for n in names if n.endswith(sid))

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
        client.post('/sessions/' + sid + '/end', json={}).raise_for_status()
        assert not client.get('/sessions').json()['sessions']
        print('PASS: real Wireshark/extcap stream, noVNC RFB, saved capture download and cleanup.')
    finally:
        client.close()
        command(*compose, 'down', '--remove-orphans', env=env)


if __name__ == '__main__':
    main()
