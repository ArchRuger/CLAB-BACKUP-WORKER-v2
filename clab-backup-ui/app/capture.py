"""Optional packet discovery and browser capture control plane.

Edgeshark streams to VM-hosted Wireshark. The manager relays the desktop and saved
downloads through a separate session service; it never receives Docker access.
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
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request as URLRequest, build_opener

from fastapi import HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_RESPONSE = 4 * 1024 * 1024
MAX_TARGETS = 10000
# What identifies a capture location: the namespace, its root process (PID plus start
# time), name and engine prefix. The interface list is deliberately not part of it;
# see Captures.identity.
IDENTITY_FIELDS = ('name', 'type', 'prefix', 'netns', 'pid', 'starttime')


class CaptureError(ValueError):
    """Safe, user-facing provider error (never raw upstream output)."""


class Provider(Protocol):
    def discover(self) -> list[dict]: ...
    def stream_uri(self, target: dict, interfaces: list[str]) -> str: ...


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
        with opener.open(URLRequest(url, headers={'Accept': 'application/json'}), timeout=8) as response:
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


def normalize_target(row):
    """One Ghostwire /mobyshark v1 row; unknown additional fields are harmless."""
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
    return target


def normalize_targets(payload, skipped=None):
    """Ghostwire /mobyshark v1 contract.

    A malformed row is skipped (and counted in `skipped` when a list is given) rather
    than hiding every other namespace behind one bad entry; a launch can never use a
    row that did not validate. The response shape itself, or a list with no usable
    row at all, still fails closed.
    """
    rows = payload.get('containers') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > MAX_TARGETS:
        raise CaptureError('Unsupported Edgeshark discovery response: expected a bounded containers list.')
    result = []
    for row in rows:
        try:
            result.append(normalize_target(row))
        except CaptureError as error:
            if skipped is not None:
                skipped.append(str(error))
    if rows and not result:
        raise CaptureError('Edgeshark returned no usable capture target. Check its version and service logs.')
    return result


def merge_shared_namespaces(rows):
    """One network namespace is one capture location.

    A host-networked container (the manager itself, for example) shares the host's
    namespace, and Ghostwire reports both. Keep one row per namespace, preferring the
    host's init process, then a container, and list the other names as aliases so
    the operator can still recognise them. Only used for the unfiltered host view;
    lab and node views keep every container row so exact name matching still works.
    """
    groups = {}
    for target in rows:
        groups.setdefault(target['netns'], []).append(target)
    merged = []
    for group in groups.values():
        group.sort(key=lambda t: (0 if t['type'] == 'proc' and t['pid'] == 1 else 1 if t['type'] != 'proc' else 2, t['name']))
        keep = dict(group[0])
        keep['aliases'] = [t['name'] for t in group[1:]]
        merged.append(keep)
    return merged


class EdgesharkProvider:
    def __init__(self, internal_url):
        self.internal_url = service_url(internal_url)
        self.skipped = 0

    def discover(self):
        skipped = []
        rows = normalize_targets(read_discovery(self.internal_url + 'discover/mobyshark'), skipped)
        self.skipped = len(skipped)
        return rows

    def stream_uri(self, target, interfaces):
        u = urlsplit(self.internal_url)
        # Only the identity fields travel; display-only keys such as aliases do not.
        detail = {**{k: target[k] for k in IDENTITY_FIELDS}, 'network-interfaces': interfaces}
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
    if not internal:
        raise CaptureError('Run deploy/setup-capture.sh to enable browser capture, then recreate the manager.')
    return EdgesharkProvider(internal)


class CaptureEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    target_id: str = Field(min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    interfaces: list[str] = Field(min_length=1, max_length=128)


class LaunchRequest(BaseModel):
    """Two body forms: today's single capture, byte for byte, or a set of 1 to 4 captures (one session each)."""
    model_config = ConfigDict(extra='forbid')
    target_id: str | None = Field(default=None, min_length=64, max_length=64, pattern=r'^[0-9a-f]{64}$')
    interfaces: list[str] | None = Field(default=None, min_length=1, max_length=128)
    captures: list[CaptureEntry] | None = Field(default=None, min_length=1, max_length=4)
    request_id: str = Field(default_factory=lambda: secrets.token_hex(32), pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def one_form(self):
        single = self.target_id is not None or self.interfaces is not None
        if single == (self.captures is not None) or (single and (self.target_id is None or self.interfaces is None)):
            raise ValueError('Send either target_id with interfaces, or captures.')
        return self

    def entries(self):
        return self.captures or [CaptureEntry(target_id=self.target_id, interfaces=self.interfaces)]


# The most records and request plans kept in memory (C07). Nothing about sessions is persisted.
KNOWN_LIMIT = 64
CAPACITY_SECONDS = 60
CHANGED = 'Capture target changed or disappeared. Refresh interfaces and select it again.'
NOT_LISTED = 'Select interfaces from the refreshed live list.'
LISTED_TWICE = 'The same interface is listed twice. Refresh interfaces and select again.'
PRUNE_GRACE_SECONDS = 10  # A listing and a launch are not atomic: a just-made record may be missing from a listing taken meanwhile.
NOT_ATTEMPTED = 'Not attempted: an earlier capture of this set failed.'
MAY_HAVE_STARTED = 'This capture may have started; see Your capture sessions. '
STARTED_ONE = 'Wireshark session started on the VM. Open the browser viewer to inspect packets.'
CAPTURE_SET_TOO_LARGE = ('{k} separate Wireshark sessions are more than the limit of {limit} at a time. '
                         'Untick interfaces, or open one Wireshark for all of them.')
CAPTURE_SLOTS_OWN_DEVICE = ('You already have {n} Wireshark {sessions} running from this browser; {k} more would pass '
                            'the limit of {limit} at a time. End a session under Your capture sessions, untick '
                            'interfaces, or open one Wireshark for all of them.')
CAPTURE_SLOTS_OWN_LINK = ('You already have {n} Wireshark {sessions} running from this browser; both ends would pass '
                          'the limit of {limit} at a time. End a session under Your capture sessions, or untick one end.')


def expected_container(lab, node):
    # Imported here, not at module level: the capture session image ships this module without
    # discovery.py or its dependencies, and only the manager's Captures calls this function.
    from .discovery import container_name
    short = node.get('definition_node') or node.get('short_name')
    if lab.get('deployment_name') and short:
        return container_name(lab.get('container_prefix', 'clab'), lab['deployment_name'], short)
    return node.get('container_name') or node['name']


class Captures:
    def __init__(self, store, environ=None):
        self.store = store
        self.secret = secrets.token_bytes(32)
        self.slots = threading.BoundedSemaphore(4)
        self.error = ''
        self.sessions = None
        # In memory only (C07), all under known_lock because the routes run on the threadpool:
        # known: session id -> the one record shape label() makes; known_owner: session id -> the
        # owner cookie that started it (so one browser's listing prunes only its own records);
        # requests: request id -> {derived request id: session id or None} of a set's last attempt.
        self.known_lock = threading.Lock()
        self.known = {}
        self.known_owner = {}
        self.requests = {}
        self.capacity_cache = None
        try:
            config = os.environ if environ is None else environ
            self.provider = configured_provider(config)
            if self.provider:
                from .capture_sessions import BrowserSessions
                self.sessions = BrowserSessions(config.get('CAPTURE_SESSION_URL', 'http://127.0.0.1:5801'),
                                                config.get('CAPTURE_SESSION_TOKEN', ''))
        except CaptureError as error:
            self.provider = None
            self.error = str(error)

    def identity(self, target):
        # A namespace restart, process restart or engine prefix change invalidates a
        # previously displayed selection. No PID is trusted alone. The interface list
        # is excluded on purpose: the selected interfaces are re-validated against
        # fresh discovery at launch anyway, and hashing unrelated interfaces made any
        # container start or stop on the host (a new veth) invalidate a selected
        # host-namespace target whose chosen interface had not changed.
        raw = json.dumps({k: target[k] for k in IDENTITY_FIELDS}, sort_keys=True, separators=(',', ':')).encode()
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

    def label(self, name, interfaces):
        """The one record shape of a session (C07 §2.2 step 3), at launch and as the listing's fallback.

        The lab and node come from container-name equality under the store lock (never the lab the
        page sent); a container no lab names keeps its own name and the veth names."""
        from .topology import displayed_interface
        interfaces = [i for i in interfaces if isinstance(i, str)] if isinstance(interfaces, list) else []
        lab_name = lab_id = ''
        device, ports = name, list(interfaces)
        def named(lab, node):
            try:
                return expected_container(lab, node) == name
            except (KeyError, TypeError, AttributeError):
                return False  # One odd stored node never blocks a launch or the listing.
        with self.store.lock:
            for lab in self.store.state.get('labs', []):
                node = next((n for n in lab.get('nodes', []) if named(lab, n)), None) if name else None
                if node is not None:
                    lab_name, lab_id = str(lab.get('name', '')), str(lab.get('id', ''))
                    device = str(node.get('short_name') or node['name'])
                    ports = [displayed_interface(node.get('kind', ''), i) for i in interfaces]
                    break
        return {'lab': lab_name, 'lab_id': lab_id, 'device': device, 'ports': ports,
                'label': (device + ' ' + ', '.join(ports)).strip(), 'started': 0.0}

    def remember(self, who, sid, record):
        with self.known_lock:
            self.known.pop(sid, None)
            self.known[sid] = record
            self.known_owner[sid] = who
            while len(self.known) > KNOWN_LIMIT:
                oldest = next(iter(self.known))
                del self.known[oldest]
                self.known_owner.pop(oldest, None)

    def plan(self, request_id, rids):
        """Record a set's derived request ids before its first service call; earlier answers are kept."""
        with self.known_lock:
            plan = self.requests.pop(request_id, {})
            for rid in rids:
                plan.setdefault(rid, None)
            self.requests[request_id] = plan
            while len(self.requests) > KNOWN_LIMIT:
                del self.requests[next(iter(self.requests))]

    def planned(self, request_id, rid, sid):
        with self.known_lock:
            if request_id in self.requests:
                self.requests[request_id][rid] = sid

    def own_ids(self, who, request_id, rids):
        """The service session ids these derived request ids have, or would have, for this browser."""
        with self.known_lock:
            plan = dict(self.requests.get(request_id, {}))
        ids = {plan[rid] for rid in rids if plan.get(rid)}
        derive = getattr(self.sessions, 'session_id', None)
        if derive:
            ids.update(derive(who, rid) for rid in rids)
        return ids

    def relisted(self, who, request_id, rid):
        """After a 502 mid-set: the session id of this entry when the owner's listing now shows it, else ''."""
        from .capture_sessions import TOKEN
        try:
            listed = self.sessions.request('GET', 'sessions', who).get('sessions')
        except HTTPException:
            return ''
        ids = self.own_ids(who, request_id, [rid])
        return next((r['id'] for r in listed if isinstance(r, dict) and isinstance(r.get('id'), str)
                     and TOKEN.fullmatch(r['id']) and r['id'] in ids), '') if isinstance(listed, list) else ''

    def record_for(self, row):
        with self.known_lock:
            record = self.known.get(row['id'])
        return record if record is not None else self.label(row.get('name') if isinstance(row.get('name'), str) else '',
                                                            row.get('interfaces'))

    def prune(self, who, listed):
        """Drop this browser's records the service no longer lists; other browsers' records stay."""
        now = time.time()
        with self.known_lock:
            # A record younger than the grace is kept: its launch may still be answering, and a retry must find it.
            for sid in [s for s, owner in self.known_owner.items() if owner == who and s not in listed
                        and not 0 <= now - self.known.get(s, {}).get('started', 0) < PRUNE_GRACE_SECONDS]:
                self.known.pop(sid, None)
                self.known_owner.pop(sid, None)

    def forget(self, sids):
        with self.known_lock:
            for sid in sids:
                self.known.pop(sid, None)
                self.known_owner.pop(sid, None)

    def capacity(self):
        """The service's published max_sessions, at most once a minute; 4 when it does not say."""
        now = time.monotonic()
        with self.known_lock:
            if self.capacity_cache and now - self.capacity_cache[0] < CAPACITY_SECONDS:
                return self.capacity_cache[1]
        try:
            value = self.sessions.request('GET', 'health').get('max_sessions')
        except HTTPException:
            value = None
        limit = value if type(value) is int and 1 <= value <= 64 else 4
        with self.known_lock:
            self.capacity_cache = (now, limit)
        return limit

    def install(self, app):
        from .capture_sessions import install, owner
        install(app, self)
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
            if names is None:
                selected = merge_shared_namespaces(selected)
            unique = {self.identity(t): t for t in selected}
            skipped = getattr(self.provider, 'skipped', 0)
            message = 'Live Linux interfaces. Edgeshark omits DOWN interfaces. Use All host targets for bridges, host NICs and other namespaces.'
            if skipped:
                message += f' {skipped} discovered namespace(s) were unreadable and are not listed.'
            return {'targets': [{'id': key, 'name': t['name'], 'kind': t['type'], 'prefix': t['prefix'],
                                 'interfaces': t['network-interfaces'], 'aliases': t.get('aliases', [])}
                                for key, t in sorted(unique.items(), key=lambda item: (item[1]['name'], item[1]['prefix'], item[0]))],
                    'message': message}

        @app.post('/api/capture/launch')
        def launch(data: LaunchRequest, request: Request, response: Response):
            if not self.sessions:
                raise HTTPException(503, self.error or 'Browser capture is disabled. Follow Capture setup.')
            from .capture_sessions import TOKEN
            rows = self.discover()  # Always revalidate, once per request; never launch from a cached PID.
            entries = data.entries()
            sets, many, total = data.captures is not None, len(entries) > 1, len(entries)

            def position(i):
                return f'Capture {i + 1} of {total}'
            # 1. Validate the whole set before any container exists.
            resolved, seen = [], set()
            for i, entry in enumerate(entries):
                prefix = position(i) + ': ' if many else ''
                target = next((t for t in rows if hmac.compare_digest(self.identity(t), entry.target_id)), None)
                if target is None:
                    raise HTTPException(409, prefix + CHANGED)
                if len(set(entry.interfaces)) != len(entry.interfaces) or any(n not in target['network-interfaces'] for n in entry.interfaces):
                    raise HTTPException(409, prefix + NOT_LISTED)
                # One namespace, one interface: two rows of a shared namespace are the same interface too.
                pairs = {(target['netns'], n) for n in entry.interfaces}
                if seen & pairs:
                    raise HTTPException(409, LISTED_TWICE)
                seen |= pairs
                resolved.append((entry, target, self.label(target['name'], entry.interfaces)))
            who = owner(request, response)
            # A set's sessions get request ids derived from the entry's content, never its position, so a
            # retried or narrowed set meets the same session at the service (which dedups on owner + id).
            rids = ([hashlib.sha256(f'{data.request_id}:{e.target_id}:{"/".join(e.interfaces)}'.encode()).hexdigest()
                     for e in entries] if sets else [data.request_id])
            # 2. A convenience for the common case, never a reservation: the service's 429 is the cap.
            if many:
                listed = self.sessions.request('GET', 'sessions', who).get('sessions')
                mine = self.own_ids(who, data.request_id, rids)
                own = len([r for r in listed if isinstance(r, dict) and r.get('id') not in mine]) if isinstance(listed, list) else 0
                limit = self.capacity()
                if total > limit:
                    raise HTTPException(409, CAPTURE_SET_TOO_LARGE.format(k=total, limit=limit))
                if own + total > limit:
                    template = CAPTURE_SLOTS_OWN_LINK if len({t['netns'] for _, t, _ in resolved}) > 1 else CAPTURE_SLOTS_OWN_DEVICE
                    raise HTTPException(409, template.format(n=own, sessions='session' if own == 1 else 'sessions', k=total, limit=limit))
            if sets:
                self.plan(data.request_id, rids)
            # 3. Start in order; any refusal stops the set.
            started, refused = [], []

            def begin(sid, rid, entry, target, record):
                with self.known_lock:
                    old = self.known.get(sid)
                if old is None:  # Only a session the service newly made; a re-answered one keeps its record and writes no event.
                    record = {**record, 'started': time.time()}
                    self.remember(who, sid, record)
                    self.store.event('capture.launch', 'Started browser Wireshark session for ' + target['name'] +
                                     ' (' + ', '.join(entry.interfaces) + ').')
                else:
                    record = old
                if sets:
                    self.planned(data.request_id, rid, sid)
                started.append({'id': sid, 'url': '/static/capture-session.html#' + sid, 'name': target['name'],
                                'interfaces': list(entry.interfaces), 'label': record['label']})

            for i, ((entry, target, record), rid) in enumerate(zip(resolved, rids)):
                try:
                    session = self.sessions.request('POST', 'sessions', who,
                                                    {'target': {k: target[k] for k in (*IDENTITY_FIELDS, 'network-interfaces')},
                                                     'interfaces': entry.interfaces, 'request_id': rid})
                    if not isinstance(session.get('id'), str) or not TOKEN.fullmatch(session['id']):
                        raise HTTPException(502, 'Browser capture service returned an invalid session.')
                except HTTPException as error:
                    if not sets:
                        raise  # The single form keeps today's path exactly.
                    head = str(error.detail)
                    if error.status_code == 502:
                        # The container may exist although its reply was lost: look once, by this entry's id only.
                        sid = self.relisted(who, data.request_id, rid)
                        if sid:
                            begin(sid, rid, entry, target, record)
                            continue  # Recovered: the set goes on with the entries not yet tried.
                        head = MAY_HAVE_STARTED + head
                    for j in range(i, total):
                        refused.append({'position': position(j), 'label': resolved[j][2]['label'],
                                        'interfaces': list(entries[j].interfaces), 'detail': head if j == i else NOT_ATTEMPTED})  # Untried entries were never sent: never entry i's reason.
                    if not started:
                        raise  # Nothing started: a plain error, as a single launch.
                    break
                begin(session['id'], rid, entry, target, record)
            result = {}
            if started:
                result.update(id=started[0]['id'], url=started[0]['url'])
            if refused:
                message = ('Wireshark started for ' + ', '.join(s['label'] for s in started) + '; not for ' +
                           ', '.join(r['label'] for r in refused) + ': ' + refused[0]['detail'])
            elif len(started) == 1:
                message = STARTED_ONE
            else:
                message = f'Wireshark started on the VM for {len(started)} captures. Open each viewer below.'
            result.update(message=message, sessions=started, refused=refused)
            return result
