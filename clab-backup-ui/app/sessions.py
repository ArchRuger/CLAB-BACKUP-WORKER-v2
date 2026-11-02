"""Sessions, the gate and the sign-on routes (sign-on DESIGN.md 5, 6, 7.3, 8, 9.3; BUILD.md S1b).

- `Sessions` (`app.state.sessions`) keeps every live session, the user index the gate reads instead of the
  state, the three throttle levels and the open failure buckets, all in memory under one `threading.Lock`
  that is acquired after `store.lock` when both are needed and never held across I/O: every method collects
  under the lock what must be written and writes after releasing it (REVIEW R4). Expiry is decided on a
  monotonic clock (`self.clock`, replaceable by a test) and never extended by a `GET /api/...` request.
- `SessionGate` is a pure ASGI layer, shaped like `allowed_hosts.HostCheck`, added in `create_app` on the
  line before it: it resolves the `clab_session` cookie for HTTP and WebSocket scopes, sets
  `scope['state']['user']`, decides setup mode, the exemptions, the restricted session and the renewal, and
  answers every refusal itself with the fixed security headers. It takes no store lock, does no I/O and logs
  a refusal nowhere (REVIEW R8).
- `require_admin` is the one dependency admin-only routes declare; `EXEMPT` and `RESTRICTED` are the only
  places that name a path a session may skip, matched against the exact `scope['path']` string.
- `install(app, sessions, accounts)` adds the exempt routes (`/api/session`, `/api/session/password`,
  `/api/setup`, `/api/health`, `/login`, `/setup`). The three routes that verify or hash a password are
  `async` and run scrypt on `accounts.SCRYPT_EXECUTOR` behind its bound; every store read and write on them
  runs off the event loop through `run_in_threadpool`.

Nothing here logs, raises or returns a password, a setup code, a session id or a hash string; the audit log
names a session by its user and source, never by id.
"""
import asyncio
import ipaddress
import math
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from . import accounts
from .accounts import AccountError, Busy, FailureBuckets, detail, write_failure_entries
from .headers import encoded, security_headers
from .origin import scheme
from .store import Store

COOKIE = 'clab_session'
CAPTURE_COOKIE = 'clab_capture_owner'   # cleared by sign-out with Path=/api/capture (DESIGN 11.2, REVIEW R10)
IDLE = 43200          # 12 h without an act of the person
ABSOLUTE = 604800     # 7 days from sign-in, whatever happens
PER_USER = 32
PER_PROCESS = 512
SWEEP_INTERVAL = 60
STATIC = Path(__file__).parent/'static'

# DESIGN 6.3: exact (method, path) pairs; a HEAD request matches a GET row. Everything else needs a session.
EXEMPT = frozenset({
    ('GET', '/login'), ('GET', '/setup'),
    ('GET', '/static/login.css'), ('GET', '/static/login.js'), ('GET', '/static/setup.js'), ('GET', '/static/fabric-mark.svg'),
    ('POST', '/api/session'), ('GET', '/api/session'), ('DELETE', '/api/session'),
    ('POST', '/api/setup'), ('GET', '/api/health'),
})
RESTRICTED = EXEMPT | {('POST', '/api/session/password')}
# DESIGN 9.3: what answers while the user index is empty. Setup mode has no asset list of its own.
SETUP_ROWS = EXEMPT - {('GET', '/login'), ('POST', '/api/session'), ('GET', '/api/session'), ('DELETE', '/api/session')}

# DESIGN 8.2: the three levels.
L1_FREE = 5           # the 5th consecutive failure of a (source, name) pair starts a 30 s delay, doubling after
L2_THRESHOLD = 100    # failures of one source inside the window before the source is delayed
L2_WINDOW = 900       # the sliding window, seconds
L2_RECORDS = 200      # a source's window holds at most this many records
L3_TOKENS = 10        # tokens per name, spent by failures from unfamiliar sources only
L3_REFILL = 30        # seconds per token
FIRST_DELAY = 30
DELAY_CAP = 900
LEVEL_LIMIT = 10000   # entries per level; above it the entry with the oldest activity goes
PAIR_IDLE = 3600      # a pair idle this long is pruned


class UserFacts(NamedTuple):
    role: str
    disabled: bool
    password_changed: str
    must_change_password: bool


def source_key(address):
    """DESIGN 8.1: the IPv4 address itself, or the IPv6 /64 of the address; an IPv4-mapped IPv6 address is
    unmapped first. A value that is not an address (the TestClient's `testclient`) is its own key; '' is '-'."""
    if not address: return '-'
    if '/' in str(address): return str(address)
    try: ip = ipaddress.ip_address(address)
    except ValueError: return str(address)
    if ip.version == 6 and ip.ipv4_mapped: ip = ip.ipv4_mapped
    if ip.version == 4: return str(ip)
    return str(ipaddress.ip_network((ip, 64), strict=False))


def source_prefix(address):
    """The familiar-source prefix: the IPv4 /24 or the IPv6 /64, written `203.0.113.0/24`; '' for a non-address."""
    if not address: return ''
    try: ip = ipaddress.ip_address(address)
    except ValueError: return ''
    if ip.version == 6 and ip.ipv4_mapped: ip = ip.ipv4_mapped
    return str(ipaddress.ip_network((ip, 24 if ip.version == 4 else 64), strict=False))


def client_address(request):
    client = request.scope.get('client') if hasattr(request, 'scope') else None
    return client[0] if client else ''


def cookie_value(scope, name=COOKIE):
    """The first value of `name` in the request's Cookie header(s); None when absent or malformed."""
    for key, value in scope.get('headers', ()):
        if key != b'cookie': continue
        try: text = value.decode('latin-1')
        except UnicodeDecodeError: continue
        for part in text.split(';'):
            item, separator, found = part.strip().partition('=')
            if separator and item.strip() == name:
                found = found.strip()
                return found[1:-1] if len(found) > 1 and found[0] == found[-1] == '"' else found
    return None


class Sessions:
    """The in-memory session table, the user index, the throttle and the open failure buckets (DESIGN 16.1)."""
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.clock = time.monotonic           # replaced by a test; never `time.monotonic` itself
        self.sessions = {}                    # id → the record of DESIGN 5.2
        self.users = {}                       # name → UserFacts (5.5)
        self.on_end = []                      # callables(session_id), run after a session ends
        self.queue = []                       # audit entries collected under the lock, written by sweep
        self.buckets = FailureBuckets()
        self.pairs = {}                       # L1: (source key, name) → {'failures', 'last', 'inflight', 'unfamiliar'}
        self.sources = {}                     # L2: source key → {'window': deque[(time, name)], 'delay', 'last', 'inflight'}
        self.names = {}                       # L3: name → {'tokens', 'updated', 'inflight'}
        self.rotated = {}                     # old id → its successor after an own change, for open sockets only (11.3)
        self.last_sweep = None

    # ---- the user index (5.5) ----
    @staticmethod
    def facts(record):
        return UserFacts(record['role'], bool(record.get('disabled')), record.get('password_changed'), bool(record.get('must_change_password')))

    def load_users(self, users):
        with self.lock:
            self.users = {name: self.facts(record) for name, record in (users or {}).items()}

    def set_user(self, record):
        with self.lock: self.users[record['name']] = self.facts(record)

    def drop_user(self, name):
        with self.lock: self.users.pop(name, None)

    def user(self, name):
        with self.lock: return self.users.get(name)

    def setup_mode(self):
        with self.lock: return not self.users

    def actor(self, name):
        """The actor of a failed or throttled attempt: the submitted name only when it is a record's (REVIEW R2)."""
        with self.lock: return name if isinstance(name, str) and name in self.users else '-'

    # ---- sessions (5.2 to 5.5) ----
    @staticmethod
    def _entry(event, session, reason=''):
        return dict(event=event, actor=session['user'], source=session['source'], outcome='ok', detail=reason, time=Store.now())

    def _write(self, entries):
        for entry in entries:
            self.store.audit(entry['event'], actor=entry['actor'], source=entry['source'], outcome=entry['outcome'],
                             target=entry.get('target', ''), detail=entry.get('detail', ''), time=entry.get('time'))

    def _ended(self, ids):
        for sid in ids:
            for callback in list(self.on_end):
                try: callback(sid)
                except Exception: pass

    def create(self, record, source):
        """Mints a session for `record` from `source`; evicts the oldest `last_seen` session of the user above
        PER_USER, then of the process above PER_PROCESS, auditing each as `session.ended` `evicted`."""
        sid = secrets.token_urlsafe(32)
        now = self.clock()
        session = {'user': record['name'], 'role': record['role'], 'provider': 'local', 'created': now, 'created_at': Store.now(),
                   'last_seen': now, 'password_changed': record.get('password_changed'), 'source': source}
        with self.lock:
            evicted = []
            # Oldest `last_seen` first; on a tie the oldest sign-in (the dictionary keeps insertion order, the sort is stable).
            mine = sorted(((key, s) for key, s in self.sessions.items() if s['user'] == record['name']), key=lambda item: item[1]['last_seen'])
            while len(mine) >= PER_USER:
                key, _ = mine.pop(0); evicted.append((key, self.sessions.pop(key)))
            while len(self.sessions) >= PER_PROCESS:
                key = min(self.sessions, key=lambda k: self.sessions[k]['last_seen']); evicted.append((key, self.sessions.pop(key)))
            self.sessions[sid] = session
            entries = [self._entry('session.ended', s, 'evicted') for _, s in evicted]
        self._write(entries); self._ended([key for key, _ in evicted])
        return sid, dict(session)

    def get(self, session_id):
        with self.lock:
            session = self.sessions.get(session_id)
            return dict(session, id=session_id) if session else None

    def resolve(self, session_id):
        """The session with its `id`, role and `must_change_password` from the index, or None after deleting one
        that expired or whose user is gone, disabled or re-stamped. No I/O: the audit entry is queued for `sweep`."""
        if not session_id or not isinstance(session_id, str): return None
        ended = None
        with self.lock:
            session = self.sessions.get(session_id)
            if session is None: return None
            now = self.clock(); event = reason = None
            facts = self.users.get(session['user'])
            if now - session['last_seen'] > IDLE: event, reason = 'session.expired', 'idle'
            elif now - session['created'] > ABSOLUTE: event, reason = 'session.expired', 'absolute'
            elif facts is None: event, reason = 'session.ended', 'user_deleted'
            elif facts.disabled: event, reason = 'session.ended', 'user_disabled'
            elif facts.password_changed != session['password_changed']: event, reason = 'session.ended', 'password_reset'
            if reason:
                del self.sessions[session_id]
                self.queue.append(self._entry(event, session, reason)); ended = session_id
            else:
                result = dict(session, id=session_id, role=facts.role, must_change_password=facts.must_change_password)
        if ended: self._ended([ended]); return None
        return result

    def touch(self, session_id):
        with self.lock:
            session = self.sessions.get(session_id)
            if session: session['last_seen'] = self.clock()

    def rotate(self, session_id, password_changed):
        """The own change: a new id for the kept record, which takes the new stamp before the index does (5.5). The
        old id is remembered as rotated so that a socket opened under it follows (`follow`); a request does not."""
        new_id = secrets.token_urlsafe(32)
        with self.lock:
            session = self.sessions.pop(session_id, None)
            if session is None: return None
            session['password_changed'] = password_changed
            self.sessions[new_id] = session
            for old, successor in list(self.rotated.items()):
                if successor == session_id: self.rotated[old] = new_id      # a chain stays one step long
            self.rotated[session_id] = new_id
            while len(self.rotated) > PER_PROCESS * 4: self.rotated.pop(next(iter(self.rotated)))
        return new_id

    def follow(self, session_id):
        """For an open socket (node_services.SocketSession), never for a request: the id the session of `session_id`
        lives under now, the same id while it lives, its successor after an own change, None once it ended."""
        if not session_id or not isinstance(session_id, str): return None
        with self.lock:
            if session_id in self.sessions: return session_id
            successor = self.rotated.get(session_id)
            if successor is not None and successor not in self.sessions:
                del self.rotated[session_id]; successor = None
            return successor

    def end(self, session_id, reason):
        with self.lock:
            session = self.sessions.pop(session_id, None)
            if session is None: return None
            entry = self._entry('signout', session) if reason == 'signout' else self._entry('session.ended', session, reason)
        self._write([entry]); self._ended([session_id])
        return dict(session)

    def end_user(self, name, reason, keep=None):
        with self.lock:
            ended = [(key, self.sessions.pop(key)) for key in list(self.sessions) if self.sessions[key]['user'] == name and key != keep]
            entries = [self._entry('session.ended', s, reason) for _, s in ended]
        self._write(entries); self._ended([key for key, _ in ended])
        return len(ended)

    def count(self, name):
        with self.lock: return sum(1 for s in self.sessions.values() if s['user'] == name)

    def expires_at(self, session):
        now = self.clock()
        remaining = min(IDLE - (now - session['last_seen']), ABSOLUTE - (now - session['created']))
        return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, remaining))).isoformat(timespec='seconds')

    def sweep_due(self):
        with self.lock:
            now = self.clock()
            if self.last_sweep is not None and now - self.last_sweep < SWEEP_INTERVAL: return False
            self.last_sweep = now
            return True

    def sweep(self):
        """Deletes expired sessions, writes the queued audit entries, flushes the closed failure buckets and prunes
        the throttle tables. Run by every sign-in and, at most once a minute, from the gate in a worker thread."""
        now = self.clock()
        with self.lock:
            expired = []
            for key, session in list(self.sessions.items()):
                reason = 'idle' if now - session['last_seen'] > IDLE else 'absolute' if now - session['created'] > ABSOLUTE else None
                if reason:
                    del self.sessions[key]; self.queue.append(self._entry('session.expired', session, reason)); expired.append(key)
            entries, self.queue = self.queue, []
            flushed = self.buckets.flush()
            self._prune(now)
            for old in [old for old, successor in self.rotated.items() if successor not in self.sessions]: del self.rotated[old]
            self.last_sweep = now
        self._write(entries); write_failure_entries(self.store, flushed); self._ended(expired)

    # ---- the failure buckets (10.1) ----
    def record_failure(self, event, source_key, actor, reason, *, target='', retry_after=0):
        with self.lock:
            entries = self.buckets.add(event, source_key, actor, reason, target=target, retry_after=retry_after) + self.buckets.flush()
        write_failure_entries(self.store, entries)

    def flush_failures(self, force=False):
        with self.lock: entries = self.buckets.flush(force=force)
        write_failure_entries(self.store, entries)

    def open_failures(self):
        with self.lock: return self.buckets.open_entries()

    # ---- the throttle (8.2) ----
    @staticmethod
    def _trim(source, now):
        window = source['window']
        while window and now - window[0][0] > L2_WINDOW: window.popleft()

    @staticmethod
    def _refill(bucket, now):
        bucket['tokens'] = min(L3_TOKENS, bucket['tokens'] + (now - bucket['updated']) / L3_REFILL)
        bucket['updated'] = now

    def _bound(self):
        for table, field in ((self.pairs, 'last'), (self.sources, 'last'), (self.names, 'updated')):
            while len(table) > LEVEL_LIMIT:
                table.pop(min(table, key=lambda k: table[k][field]))

    def _prune(self, now):
        # A reservation does not pin an entry: a source with an empty window and a full name bucket go, so a
        # reservation a caller never settled heals at the next sweep; an attempt still in flight is then simply
        # not counted by that level until it settles, and `_settle` tolerates the missing entry.
        for key in [k for k, pair in self.pairs.items() if now - pair['last'] > PAIR_IDLE]: del self.pairs[key]
        for key, source in list(self.sources.items()):
            self._trim(source, now)
            if not source['window']: del self.sources[key]
        for key, bucket in list(self.names.items()):
            self._refill(bucket, now)
            if bucket['tokens'] >= L3_TOKENS: del self.names[key]

    # An attempt that passed `check` is *in flight* until `failure`, `success` or `release` settles it, and every
    # level counts it as the failure it may become: the verify is awaited for 50 to 110 ms, and attempts sent at once
    # would otherwise all pass the levels before the first one is counted (verification finding on 8.2). The
    # reservation lives on the pair (`inflight`, and `unfamiliar` for the L3 tokens it holds), on the source and on
    # the name, so that `success`, which does not know whether the source was familiar, can settle it from the pair.
    def _pair(self, key_source, name, now):
        return self.pairs.setdefault((key_source, name), {'failures': 0, 'last': now, 'inflight': 0, 'unfamiliar': 0})

    def _source(self, key_source, now):
        return self.sources.setdefault(key_source, {'window': deque(), 'delay': 0, 'last': now, 'inflight': 0})

    def _name(self, name, now):
        return self.names.setdefault(name, {'tokens': float(L3_TOKENS), 'updated': now, 'inflight': 0})

    @staticmethod
    def _settle(pair, source, bucket, held):
        """Drops one reservation of the pair (`held`: its L3 token too); tolerates a settle without a reservation."""
        if pair and pair['inflight'] > 0: pair['inflight'] -= 1
        if source and source['inflight'] > 0: source['inflight'] -= 1
        if held and pair and pair['unfamiliar'] > 0:
            pair['unfamiliar'] -= 1
            if bucket and bucket['inflight'] > 0: bucket['inflight'] -= 1

    def check(self, source, name, familiar):
        """0 when an attempt may proceed, which reserves it as in flight on every level until it is settled, else
        `retry_after` in seconds (the largest of the refusing levels); a refused attempt is recorded as
        `signin.throttled` with the level's reason and changes no counter."""
        key_source = source_key(source); now = self.clock(); delays = {}
        with self.lock:
            pair = self.pairs.get((key_source, name))
            if pair and pair['failures'] + pair['inflight'] >= L1_FREE:
                remaining = min(DELAY_CAP, FIRST_DELAY * 2 ** (pair['failures'] + pair['inflight'] - L1_FREE)) - (now - pair['last'])
                if remaining > 0: delays['pair'] = remaining
            entry = self.sources.get(key_source)
            if entry:
                self._trim(entry, now)
                if len(entry['window']) + entry['inflight'] < L2_THRESHOLD: entry['delay'] = 0
                else:
                    remaining = (entry['delay'] or FIRST_DELAY) - (now - entry['last'])
                    if remaining > 0: delays['source'] = remaining
            if not familiar:
                bucket = self.names.get(name)
                if bucket:
                    self._refill(bucket, now)
                    free = bucket['tokens'] - bucket['inflight']
                    if free < 1: delays['name'] = min(L3_REFILL, (1 - free) * L3_REFILL)
            if not delays:
                # The reservation moves no `last`: a delay counts from the last failure, and a reservation that is
                # released (busy) must not restart one.
                pair = self._pair(key_source, name, now); pair['inflight'] += 1
                entry = self._source(key_source, now); entry['inflight'] += 1
                if not familiar:
                    pair['unfamiliar'] += 1; self._name(name, now)['inflight'] += 1
                self._bound()
                return 0
            reason = max(delays, key=delays.get); retry = max(1, math.ceil(max(delays.values())))
            actor = name if name in self.users else '-'
            entries = self.buckets.add('signin.throttled', key_source, actor, reason, retry_after=retry) + self.buckets.flush()
        write_failure_entries(self.store, entries)
        return retry

    def release(self, source, name, familiar):
        """Settles a reservation of `check` for an attempt that ran no verify after all (the executor's `busy`
        refusal, a refused name or password on the setup route): every counter is as if `check` had not been called."""
        key_source = source_key(source)
        with self.lock:
            self._settle(self.pairs.get((key_source, name)), self.sources.get(key_source), self.names.get(name), not familiar)

    def failure(self, source, name, familiar, reason, event='signin.failed'):
        """An attempt that ran the verify and did not succeed: settles its reservation and counts the L1 pair, the L2
        window and, from an unfamiliar source, an L3 token; recorded as `event` (None: counters only, the caller
        audits). The effective count of every level is the same before and after: the attempt was already counted."""
        key_source = source_key(source); now = self.clock()
        with self.lock:
            pair = self._pair(key_source, name, now); entry = self._source(key_source, now)
            bucket = self._name(name, now) if not familiar else self.names.get(name)
            self._settle(pair, entry, bucket, not familiar)
            pair['failures'] += 1; pair['last'] = now
            self._trim(entry, now)
            entry['window'].append((now, name)); entry['last'] = now
            while len(entry['window']) > L2_RECORDS: entry['window'].popleft()
            if len(entry['window']) >= L2_THRESHOLD:
                entry['delay'] = FIRST_DELAY if not entry['delay'] else min(DELAY_CAP, entry['delay'] * 2)
            if not familiar:
                self._refill(bucket, now); bucket['tokens'] = max(0.0, bucket['tokens'] - 1)
            self._bound()
            entries = []
            if event:
                actor = name if name in self.users else '-'
                entries = self.buckets.add(event, key_source, actor, reason) + self.buckets.flush()
        write_failure_entries(self.store, entries)

    def success(self, source, name):
        """Settles every reservation of the pair, clears it and removes only this pair's records from the source's
        window; L3 is left alone (the tokens the pair held in flight are given back, none is refilled)."""
        key_source = source_key(source)
        with self.lock:
            pair = self.pairs.pop((key_source, name), None)
            entry = self.sources.get(key_source)
            if pair:
                if entry: entry['inflight'] = max(0, entry['inflight'] - pair['inflight'])
                bucket = self.names.get(name)
                if bucket: bucket['inflight'] = max(0, bucket['inflight'] - pair['unfamiliar'])
            if entry:
                entry['window'] = deque(record for record in entry['window'] if record[1] != name)
                if len(entry['window']) + entry['inflight'] < L2_THRESHOLD: entry['delay'] = 0
                if not entry['window'] and not entry['inflight']: del self.sources[key_source]


# ---- the gate (6) ----
def _next(scope):
    query = scope.get('query_string', b'')
    target = scope.get('path', '/') + ('?' + query.decode('latin-1') if query else '')
    return quote(target, safe='')


class SessionGate:
    """Pure ASGI layer directly inside HostCheck: resolves the cookie, sets scope['state']['user'], refuses by
    DESIGN 6.4 and 9.3, renews on acts of the person (5.4). Never raises; a malformed cookie is no session."""
    def __init__(self, app, sessions):
        self.app = app
        self.sessions = sessions

    def decide(self, scope):
        """None to pass the request on, else ('redirect', location) | ('json', status, code) | ('close', reason).
        Synchronous and pure: the sessions lock only, no store lock, no I/O."""
        state = scope.get('state')
        if state is None: state = scope['state'] = {}
        session = self.sessions.resolve(cookie_value(scope))
        user = {'name': session['user'], 'role': session['role'], 'session_id': session['id'],
                'must_change_password': session['must_change_password']} if session else None
        state['user'] = user
        socket = scope['type'] == 'websocket'
        method = 'GET' if socket else scope.get('method', 'GET')
        key = ('GET' if method == 'HEAD' else method, scope.get('path', ''))
        accept = next((v for k, v in scope.get('headers', ()) if k == b'accept'), b'')
        page = not socket and method in ('GET', 'HEAD') and b'text/html' in accept
        if self.sessions.setup_mode():
            if key in SETUP_ROWS: return None
            if socket: return ('close', 'setup_required')
            if page: return ('redirect', '/setup')
            return ('json', 503, 'setup_required')
        if key in EXEMPT: return None
        if user is None:
            if socket: return ('close', 'signed_out')
            if page: return ('redirect', '/login?next=' + _next(scope))
            return ('json', 401, 'signed_out')
        if user['must_change_password'] and key not in RESTRICTED:
            if socket: return ('close', 'password_change_required')
            if page: return ('redirect', '/login?change=1&next=' + _next(scope))
            return ('json', 403, 'password_change_required')
        if not socket and (method not in ('GET', 'HEAD') or page): self.sessions.touch(user['session_id'])
        return None

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            await self.app(scope, receive, send); return
        outcome = self.decide(scope)
        if self.sessions.sweep_due():
            try: asyncio.get_running_loop().run_in_executor(None, self.sessions.sweep)
            except RuntimeError: pass
        if outcome is None:
            await self.app(scope, receive, send); return
        if outcome[0] == 'close':
            await send({'type': 'websocket.close', 'code': 1008, 'reason': outcome[1]}); return
        if outcome[0] == 'redirect':
            headers = security_headers(scope, status=302, refusal=True)
            headers.update({'Location': outcome[1], 'Content-Length': '0'})
            await send({'type': 'http.response.start', 'status': 302, 'headers': encoded(headers)})
            await send({'type': 'http.response.body', 'body': b''}); return
        _, status, code = outcome
        body = JSONResponse({'detail': detail(status, code)}).body
        headers = security_headers(scope, status=status, refusal=True)
        headers.update({'Content-Type': 'application/json', 'Content-Length': str(len(body))})
        await send({'type': 'http.response.start', 'status': status, 'headers': encoded(headers)})
        await send({'type': 'http.response.body', 'body': body})


def require_admin(request: Request):
    """`Depends(require_admin)`: the request's user when it is an admin; otherwise records `forbidden` (summed per
    actor, route template and minute, 10.1) and raises 403 admin_required (7.1)."""
    user = getattr(request.state, 'user', None)
    if user and user.get('role') == 'admin': return user
    sessions = request.app.state.sessions
    route = getattr(request.scope.get('route'), 'path', request.url.path)
    sessions.record_failure('forbidden', source_key(client_address(request)), user['name'] if user else '-', 'admin_required', target=route)
    raise HTTPException(403, detail(403, 'admin_required'))


# ---- the routes (7.3) ----
class SignIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(max_length=256)
    password: str = Field(max_length=1024)


class OwnChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current: str = Field(max_length=1024)
    password: str = Field(max_length=1024)


class Setup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(max_length=256)
    username: str = Field(max_length=256)
    password: str = Field(max_length=1024)


class Empty(BaseModel):
    model_config = ConfigDict(extra='forbid')


def throttled(retry_after):
    return HTTPException(429, detail(429, 'throttled', retry_after=int(retry_after)), headers={'Retry-After': str(int(retry_after))})


def set_session_cookie(response, scope, session_id):
    response.set_cookie(COOKIE, session_id, max_age=ABSOLUTE, path='/', httponly=True, samesite='Strict', secure=scheme(scope) == 'https')


def clear_session_cookie(response, scope):
    response.delete_cookie(COOKIE, path='/', httponly=True, samesite='Strict', secure=scheme(scope) == 'https')


def clear_capture_cookie(response, scope):
    response.delete_cookie(CAPTURE_COOKIE, path='/api/capture', httponly=True, samesite='Strict', secure=scheme(scope) == 'https')


def page(name):
    path = STATIC/name
    if not path.is_file(): raise HTTPException(404, 'This page is not installed on this manager.')
    return FileResponse(path)


def install(app, sessions, accounts_):
    store = accounts_.store

    def session_body(name, session):
        facts = sessions.user(name)
        role = facts.role if facts else session['role']
        restricted = facts.must_change_password if facts else False
        return {'user': {'name': name, 'role': role, 'must_change_password': restricted}, 'expires': sessions.expires_at(session)}

    def signed_in(request, record, address):
        sid, session = sessions.create(record, address)
        sessions.sweep()
        response = JSONResponse(session_body(record['name'], session))
        set_session_cookie(response, request.scope, sid)
        return response

    def read_record(name):
        with store.lock:
            record = accounts_.record(name)
            return dict(record, known_sources=list(record.get('known_sources', []))) if record else None

    @app.post('/api/session')
    async def sign_in(data: SignIn, request: Request):
        if sessions.setup_mode(): raise HTTPException(503, detail(503, 'setup_required'))
        name = data.username.strip().lower(); address = client_address(request); prefix = source_prefix(address)
        record = await run_in_threadpool(read_record, name)
        familiar = bool(prefix) and prefix in (record or {}).get('known_sources', [])
        retry = await run_in_threadpool(sessions.check, address, name, familiar)
        if retry: raise throttled(retry)
        # One scrypt whatever the name (8.5): the user's hash only when the user exists and is enabled, else the dummy
        # (verify_password runs the dummy for None and for a string that does not parse).
        if record is None: hash_string, reason = None, 'invalid_name' if not accounts.check_name(name) else 'invalid_credentials'
        elif record.get('disabled'): hash_string, reason = None, 'disabled'
        elif accounts.parse_hash(record.get('password')) is None: hash_string, reason = record.get('password'), 'bad_record'
        else: hash_string, reason = record['password'], 'invalid_credentials'
        # From here the attempt is in flight on every level (8.2) until failure, success or release settles it.
        try: ok = await accounts_.averify(hash_string, data.password)
        except Busy:
            await run_in_threadpool(sessions.release, address, name, familiar)
            await run_in_threadpool(sessions.record_failure, 'signin.throttled', source_key(address), sessions.actor(name), 'busy', retry_after=2)
            raise throttled(2)
        except BaseException:
            await run_in_threadpool(sessions.release, address, name, familiar); raise
        if not ok or hash_string is None:
            await run_in_threadpool(sessions.failure, address, name, familiar, reason)
            raise HTTPException(401, detail(401, 'invalid_credentials', 'POST /api/session'))
        await run_in_threadpool(sessions.success, address, name)
        if accounts.needs_rehash(record['password']):
            try: fresh = await accounts_.ahash(data.password)
            except Busy: fresh = None
            if fresh: await run_in_threadpool(accounts_.replace_hash, name, fresh)
        record = await run_in_threadpool(accounts_.record_signin, name, prefix, address)
        previous = getattr(request.state, 'user', None)
        if previous: await run_in_threadpool(sessions.end, previous['session_id'], 'signout')
        return await run_in_threadpool(signed_in, request, record, address)

    @app.get('/api/session')
    def session_view(request: Request):
        user = getattr(request.state, 'user', None)
        session = sessions.get(user['session_id']) if user else None
        if session is None:
            response = JSONResponse({'detail': detail(401, 'signed_out')}, status_code=401)
            clear_session_cookie(response, request.scope)
            return response
        return session_body(user['name'], session)

    @app.delete('/api/session')
    def sign_out(data: Empty, request: Request):
        user = getattr(request.state, 'user', None)
        if user: sessions.end(user['session_id'], 'signout')
        response = JSONResponse({'signed_out': True})
        clear_session_cookie(response, request.scope); clear_capture_cookie(response, request.scope)
        return response

    @app.post('/api/session/password')
    async def change_password(data: OwnChange, request: Request):
        user = request.state.user
        name = user['name']; address = client_address(request); prefix = source_prefix(address)
        reasons = accounts.check_password(name, data.password)
        if reasons: raise HTTPException(422, detail(422, 'weak_password', reasons=reasons))
        record = await run_in_threadpool(read_record, name)
        if record is None: raise HTTPException(404, detail(404, 'user_not_found'))
        familiar = bool(prefix) and prefix in record.get('known_sources', [])
        retry = await run_in_threadpool(sessions.check, address, name, familiar)
        if retry: raise throttled(retry)
        try: ok = await accounts_.averify(record.get('password'), data.current)
        except Busy:
            await run_in_threadpool(sessions.release, address, name, familiar)
            await run_in_threadpool(sessions.record_failure, 'signin.throttled', source_key(address), name, 'busy', retry_after=2)
            raise throttled(2)
        except BaseException:
            await run_in_threadpool(sessions.release, address, name, familiar); raise
        if not ok:
            def wrong():
                sessions.failure(address, name, familiar, 'invalid_credentials', event=None)
                store.audit('password.changed', actor=name, source=address, outcome='failed', detail='invalid_credentials')
            await run_in_threadpool(wrong)
            raise HTTPException(401, detail(401, 'invalid_credentials', 'POST /api/session/password'))
        await run_in_threadpool(sessions.success, address, name)
        try: fresh = await accounts_.ahash(data.password)
        except Busy: raise throttled(2)
        try: new_id = await run_in_threadpool(accounts_.change_password, name, fresh, session_id=user['session_id'], source=address)
        except AccountError as exc: raise HTTPException(exc.status, exc.detail)
        except OSError: raise HTTPException(500, 'Could not save the new password; nothing was changed. Check manager storage and retry.')
        response = JSONResponse({'changed': True})
        if new_id: set_session_cookie(response, request.scope, new_id)
        return response

    @app.post('/api/setup')
    async def setup(data: Setup, request: Request):
        found = await run_in_threadpool(accounts_.read_setup_code)
        if found is None: raise HTTPException(404, detail(404, 'setup_closed', 'POST /api/setup'))
        mode, code = found
        name = data.username.strip().lower(); address = client_address(request); key_source = source_key(address)
        retry = await run_in_threadpool(sessions.check, address, name, False)
        if retry: raise throttled(retry)
        if not accounts.code_matches(code, data.code):
            await run_in_threadpool(sessions.failure, address, name, False, 'invalid_code', event='setup.failed')
            raise HTTPException(401, detail(401, 'invalid_code', 'POST /api/setup'))
        # The code was right: whatever refuses from here ran no verify and releases the reservation of `check`.
        async def refused(reason, retry_after=0):
            await run_in_threadpool(sessions.release, address, name, False)
            event = 'signin.throttled' if reason == 'busy' else 'setup.failed'
            await run_in_threadpool(sessions.record_failure, event, key_source, sessions.actor(name), reason, retry_after=retry_after)
        if not accounts.check_name(name):
            await refused('invalid_name')
            raise HTTPException(422, detail(422, 'invalid_name'))
        reasons = accounts.check_password(name, data.password)
        if reasons:
            await refused('weak_password')
            raise HTTPException(422, detail(422, 'weak_password', reasons=reasons))
        try: hash_string = await accounts_.ahash(data.password)
        except Busy:
            await refused('busy', retry_after=2)
            raise throttled(2)
        except BaseException:
            await run_in_threadpool(sessions.release, address, name, False); raise
        # complete_setup reads the file again under store.lock: a second submit of a used code, a replaced file or a
        # setup file beside existing users is refused setup_closed there, so one code creates one administrator (9.2, 9.5).
        try: record = await run_in_threadpool(accounts_.complete_setup, name, hash_string, code=data.code, mode=mode, source=address, prefix=source_prefix(address))
        except AccountError as exc:
            await refused(exc.code)
            raise HTTPException(exc.status, exc.detail)
        except OSError:
            await run_in_threadpool(sessions.release, address, name, False)
            raise HTTPException(500, 'Could not save the administrator; nothing was changed. Check manager storage and retry.')
        await run_in_threadpool(sessions.success, address, name)
        return await run_in_threadpool(signed_in, request, record, address)

    @app.get('/api/health')
    def health():
        return {'ready': True}

    @app.get('/login')
    def login_page(request: Request):
        user = getattr(request.state, 'user', None)
        if user and not user['must_change_password']: return RedirectResponse('/', status_code=302)
        return page('login.html')

    @app.get('/setup')
    def setup_page(request: Request):
        if getattr(request.state, 'user', None): return RedirectResponse('/', status_code=302)
        if accounts_.read_setup_code() is None: raise HTTPException(404, 'Not found')
        return page('setup.html')
