"""Optional packet capture control plane. Packet bytes never traverse the manager.

Providers return normalized targets and construct launch URLs. The only registered
provider is Edgeshark; no dynamic imports, shell commands or client-supplied URLs.
"""
import hashlib
import hmac
from http.client import HTTPException as HTTPProtocolError
import json
import os
import secrets
import threading
import time
from typing import Protocol
from urllib.error import URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

MAX_RESPONSE = 4 * 1024 * 1024
MAX_TARGETS = 10000


class CaptureError(ValueError):
    """Safe, user-facing provider error (never raw upstream output)."""


class Provider(Protocol):
    def discover(self) -> list[dict]: ...
    def launch(self, target: dict, interfaces: list[str]) -> str: ...


def service_url(value):
    try:
        u = urlsplit(value)
        if (u.scheme not in ('http', 'https') or not u.hostname or u.username is not None
                or u.password is not None or u.query or u.fragment or not u.port and u.netloc.endswith(':')
                or any(c.isspace() or ord(c) < 32 for c in value) or '\\' in value
                or len(value) > 2048):
            raise ValueError()
        if u.port is not None and not 1 <= u.port <= 65535:
            raise ValueError()
        return urlunsplit((u.scheme, u.netloc, u.path.rstrip('/') + '/', '', ''))
    except ValueError:
        raise CaptureError('Capture URLs must be HTTP(S) service addresses without credentials, query strings or fragments.') from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise CaptureError('Edgeshark redirected discovery. Configure its final service URL.')


def read_discovery(url):
    # Explicit operator configuration is the only source of a server address.
    # Ignore ambient proxies; do not forward manager/VM credentials or redirects.
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        started = time.monotonic()
        with opener.open(Request(url, headers={'Accept': 'application/json'}), timeout=8) as response:
            content = bytearray()
            while len(content) <= MAX_RESPONSE:
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if time.monotonic() - started > 12:
                    raise CaptureError('Edgeshark discovery timed out. Check the service and retry.')
            if len(content) > MAX_RESPONSE:
                raise CaptureError('Edgeshark discovery exceeds the 4 MiB limit.')
        return json.loads(content)
    except CaptureError:
        raise
    except (URLError, OSError, HTTPProtocolError, ValueError, RecursionError):
        raise CaptureError('Cannot read Edgeshark discovery. Check the configured URL, TLS certificate, service and network access.') from None


def normalize_targets(payload):
    """Ghostwire /mobyshark v1 contract; unknown additional fields are harmless."""
    rows = payload.get('containers') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_TARGETS:
        raise CaptureError('Unsupported Edgeshark discovery response: expected a bounded containers list.')
    result = []
    for row in rows:
        if not isinstance(row, dict):
            raise CaptureError('Unsupported Edgeshark capture target.')
        target = {}
        for key in ('name', 'type', 'prefix'):
            value = row.get(key, '')
            if not isinstance(value, str) or len(value) > 1024 or any(ord(c) < 32 for c in value):
                raise CaptureError('Unsupported Edgeshark target identity.')
            target[key] = value
        for key in ('netns', 'pid', 'starttime'):
            value = row.get(key, 0)
            if type(value) is not int or not 0 <= value < 2**64:
                raise CaptureError('Unsupported Edgeshark namespace identity.')
            target[key] = value
        if not target['netns'] or not target['name']:
            raise CaptureError('Edgeshark returned an incomplete namespace identity.')
        nifs = row.get('network-interfaces')
        if not isinstance(nifs, list) or len(nifs) > 4096:
            raise CaptureError('Unsupported Edgeshark interface list.')
        if any(not isinstance(n, str) or not n or any(0xD800 <= ord(c) <= 0xDFFF for c in n)
               or len(n.encode('utf-8')) > 15
               or '/' in n or any(c.isspace() or ord(c) < 32 for c in n) for n in nifs):
            raise CaptureError('Edgeshark returned an invalid Linux interface name.')
        target['network-interfaces'] = sorted(set(nifs))
        result.append(target)
    return result


class EdgesharkProvider:
    def __init__(self, internal_url, public_url):
        self.internal_url = service_url(internal_url)
        self.public_url = service_url(public_url)

    def discover(self):
        return normalize_targets(read_discovery(self.internal_url + 'discover/mobyshark'))

    def launch(self, target, interfaces):
        u = urlsplit(self.public_url)
        detail = {**target, 'network-interfaces': interfaces}
        query = urlencode({'container': json.dumps(detail, separators=(',', ':')), 'nif': '/'.join(interfaces)})
        return 'packetflix:' + urlunsplit(('wss' if u.scheme == 'https' else 'ws', u.netloc,
                                           u.path + 'capture', query, ''))


def configured_provider(environ) -> Provider | None:
    name = environ.get('CAPTURE_PROVIDER', 'disabled').strip().lower()
    if name in ('', 'disabled'):
        return None
    if name != 'edgeshark':
        raise CaptureError('Unknown capture provider. Supported values: disabled, edgeshark.')
    internal = environ.get('CAPTURE_EDGESHARK_URL', '')
    public = environ.get('CAPTURE_EDGESHARK_PUBLIC_URL', '')
    if not internal or not public:
        raise CaptureError('Set CAPTURE_EDGESHARK_URL and CAPTURE_EDGESHARK_PUBLIC_URL, then recreate the manager.')
    return EdgesharkProvider(internal, public)


class LaunchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_id: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    interfaces: list[str] = Field(min_length=1, max_length=128)


def expected_container(lab, node):
    short = node.get('definition_node') or node.get('short_name')
    if lab.get('deployment_name') and short:
        prefix = lab.get('container_prefix', 'clab')
        return f'{prefix}-{lab["deployment_name"]}-{short}' if prefix else short
    return node.get('container_name') or node['name']


class Captures:
    def __init__(self, store, environ=None):
        self.store = store
        self.secret = secrets.token_bytes(32)
        self.slots = threading.BoundedSemaphore(4)
        self.error = ''
        try:
            self.provider = configured_provider(os.environ if environ is None else environ)
        except CaptureError as error:
            self.provider = None
            self.error = str(error)

    def identity(self, target):
        # A namespace restart, process restart, engine prefix or interface change
        # invalidates a previously displayed selection. No PID is trusted alone.
        raw = json.dumps(target, sort_keys=True, separators=(',', ':')).encode()
        return hmac.new(self.secret, raw, hashlib.sha256).hexdigest()

    def discover(self):
        if not self.provider:
            raise HTTPException(503, self.error or 'Packet capture is disabled. Follow Capture setup to enable Edgeshark.')
        if not self.slots.acquire(blocking=False):
            raise HTTPException(429, 'Capture discovery is busy. Retry shortly.')
        try:
            return self.provider.discover()
        except CaptureError as error:
            raise HTTPException(502, str(error)) from None
        finally:
            self.slots.release()

    def install(self, app):
        @app.get('/api/capture/status')
        def status():
            return {'enabled': bool(self.provider), 'provider': 'edgeshark' if self.provider else 'disabled',
                    'message': self.error or ('Ready to discover live interfaces.' if self.provider else
                                             'Packet capture is optional. Follow Capture setup to enable it.'),
                    'setup_url': '/static/capture-setup.html'}

        @app.get('/api/capture/targets')
        def targets(lab_id: str = Query('', max_length=100), node: str = Query('', max_length=200)):
            names = None
            with self.store.lock:
                if lab_id:
                    lab = self.store.lab(lab_id)
                    if not lab:
                        raise HTTPException(404, 'Lab not found')
                    nodes = [n for n in lab['nodes'] if not node or n['name'] == node]
                    if node and not nodes:
                        raise HTTPException(404, 'Node not found')
                    names = {expected_container(lab, n) for n in nodes}
                elif node:
                    raise HTTPException(400, 'A node filter requires a lab.')
            rows = self.discover()
            # Never infer membership using a substring or an IP address.
            selected = [t for t in rows if names is None or t['name'] in names]
            unique = {self.identity(t): t for t in selected}
            return {'targets': [{'id': key, 'name': t['name'], 'kind': t['type'],
                                 'prefix': t['prefix'], 'interfaces': t['network-interfaces']}
                                for key, t in sorted(unique.items(), key=lambda item: (item[1]['name'], item[1]['prefix'], item[0]))],
                    'message': 'Live Linux interfaces. Edgeshark omits DOWN interfaces. Use All host targets for bridges, host NICs and other namespaces.'}

        @app.post('/api/capture/launch')
        def launch(data: LaunchRequest):
            rows = self.discover()  # Always revalidate; never launch from a cached PID.
            target = next((t for t in rows if hmac.compare_digest(self.identity(t), data.target_id)), None)
            if target is None:
                raise HTTPException(409, 'Capture target changed or disappeared. Refresh interfaces and select it again.')
            if len(set(data.interfaces)) != len(data.interfaces) or any(n not in target['network-interfaces'] for n in data.interfaces):
                raise HTTPException(409, 'Select interfaces from the refreshed live list.')
            uri = self.provider.launch(target, data.interfaces)
            self.store.event('capture.launch', 'Prepared Wireshark handoff for ' + target['name'] +
                             ' (' + ', '.join(data.interfaces) + '). Capture starts only in the workstation plugin.')
            return {'uri': uri, 'message': 'Open Wireshark to start. Stop and save the capture in Wireshark.'}
