"""Accounts: the user record, scrypt hashing and the password policy, the setup code, and the audit vocabulary.

Sign-on DESIGN.md sections 3 (the record), 4 (hashing and policy), 9.2 and 9.5 (the setup code and recovery)
and 10 (the audit vocabulary and the per-minute failure buckets). This module holds no HTTP route: the
routes of `app.state.accounts` are installed by `install(app)` (BUILD.md S1b), which builds on the
`Accounts` object below. Every record change runs under `store.lock`, saves the state, then refreshes the
user index of `app.state.sessions` inside the same block and audits; a save that fails leaves the record
as it was in memory (the house pattern of main.py `save_lab`).

Nothing in this module logs, raises or returns a password, a setup code, a session id or a hash string.
"""
import asyncio
import base64
import hashlib
import hmac
import os
import re
import secrets
import stat
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .store import Store

# ---- scrypt (DESIGN 4.1, 4.2) ----
PARAMS = {'n': 2**15, 'r': 8, 'p': 1}   # the shipped parameters; a test process may lower them before create_app
DKLEN = 32
SALT_BYTES = 32
MAXMEM = 64*1024*1024   # hashlib.scrypt's default maxmem refuses n=2**15, r=8: every call passes this
N_RANGE = (2**14, 2**20); R_RANGE = (1, 32); P_RANGE = (1, 16); SALT_RANGE = (16, 64)
# Every scrypt call, verify and hash alike, runs here: four threads, never the shared Starlette pool (REVIEW R7).
SCRYPT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix='scrypt')
VERIFY_LIMIT = 20   # at most 4 verifies run and 16 wait; beyond that a sign-in is refused `busy` without hashing
pending = 0         # verifies queued or running through averify/ahash; read and written on the event loop only


class Busy(Exception):
    """The executor bound is reached: the route answers 429 throttled with retry_after 2 (DESIGN 4.1, 8.3)."""


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')


def _unb64(text):
    """URL-safe base64 without padding, canonical only; None for anything else."""
    if not text or not re.fullmatch(r'[A-Za-z0-9_-]+', text): return None
    try: raw = base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    except ValueError: return None
    return raw if _b64(raw) == text else None


def _encode(password):
    # NFKC before hashing (NIST SP 800-63B 5.1.1.2), the same normalisation the policy counts with, so a
    # password typed on another keyboard in a decomposed form still verifies. Whitespace is kept as typed.
    return unicodedata.normalize('NFKC', password).encode('utf8')


def parse_hash(text):
    """`scrypt$<n>$<r>$<p>$<salt>$<hash>` → {'n','r','p','salt','hash'}, or None for every malformed case of DESIGN 4.2."""
    if not isinstance(text, str): return None
    parts = text.split('$')
    if len(parts) != 6 or parts[0] != 'scrypt': return None
    if any(not re.fullmatch(r'[1-9][0-9]*', part) for part in parts[1:4]): return None
    n, r, p = (int(part) for part in parts[1:4])
    if not (N_RANGE[0] <= n <= N_RANGE[1]) or n & (n - 1): return None
    if not (R_RANGE[0] <= r <= R_RANGE[1]) or not (P_RANGE[0] <= p <= P_RANGE[1]): return None
    # scrypt needs 128*r*(n+p+2) bytes (OpenSSL's bound, which hashlib enforces as ValueError above maxmem), and OpenSSL
    # also refuses N >= 2**(16 r) (its scrypt.c; with r=1 that is every n from 2**16, all under MAXMEM): a string inside
    # the ranges that hashlib would refuse cannot be verified, so it is malformed here, a bad_record, never a 500.
    if 128 * r * (n + p + 2) > MAXMEM: return None
    if 16 * r <= 63 and n >= 1 << (16 * r): return None
    salt = _unb64(parts[4]); digest = _unb64(parts[5])
    if salt is None or digest is None: return None
    if not (SALT_RANGE[0] <= len(salt) <= SALT_RANGE[1]) or len(digest) != DKLEN: return None
    return {'n': n, 'r': r, 'p': p, 'salt': salt, 'hash': digest}


def _scrypt(password, salt, n, r, p):
    # The one call site of hashlib.scrypt (ruling 4): always maxmem, always dklen.
    return hashlib.scrypt(_encode(password), salt=salt, n=n, r=r, p=p, dklen=DKLEN, maxmem=MAXMEM)


def hash_password(password, params=None):
    """A new hash string with the shipped PARAMS (or `params`) and a fresh 32-byte salt. Synchronous: call it on
    SCRYPT_EXECUTOR (through ahash) from an async route."""
    params = dict(PARAMS if params is None else params)
    salt = secrets.token_bytes(SALT_BYTES)
    digest = _scrypt(password, salt, params['n'], params['r'], params['p'])
    return '$'.join(['scrypt', str(params['n']), str(params['r']), str(params['p']), _b64(salt), _b64(digest)])


def verify_password(hash_string, password):
    """True when `password` matches the string. A string that is None or does not parse is verified against
    DUMMY_HASH and answers False, so every attempt costs exactly one scrypt (DESIGN 4.2, 8.5)."""
    parsed = parse_hash(hash_string)
    known = parsed is not None
    if not known: parsed = parse_hash(DUMMY_HASH)
    try: digest = _scrypt(password, parsed['salt'], parsed['n'], parsed['r'], parsed['p'])
    except ValueError:
        # parse_hash mirrors OpenSSL's rules; should a build refuse more, the string is a bad record all the same:
        # the refused call did no work, the dummy is verified instead and the attempt still costs one scrypt.
        parsed = parse_hash(DUMMY_HASH); known = False
        digest = _scrypt(password, parsed['salt'], parsed['n'], parsed['r'], parsed['p'])
    return hmac.compare_digest(digest, parsed['hash']) and known


def needs_rehash(hash_string):
    """True when a string that parses carries other parameters than the shipped ones (rehash on sign-in, 4.2)."""
    parsed = parse_hash(hash_string)
    return parsed is not None and (parsed['n'], parsed['r'], parsed['p']) != (PARAMS['n'], PARAMS['r'], PARAMS['p'])


# A random password hashed once at import with the shipped parameters; verified for every name that cannot sign in.
DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


async def _run(function, *args):
    global pending
    if pending >= VERIFY_LIMIT: raise Busy()
    pending += 1
    try: return await asyncio.get_running_loop().run_in_executor(SCRYPT_EXECUTOR, function, *args)
    finally: pending -= 1


async def averify(hash_string, password):
    """verify_password on the scrypt executor, behind the `pending` bound; raises Busy."""
    return await _run(verify_password, hash_string, password)


async def ahash(password):
    """hash_password on the scrypt executor, behind the same bound; raises Busy."""
    return await _run(hash_password, password)


# ---- the policy (DESIGN 3.1, 4.3) ----
NAME = re.compile(r'^[a-z0-9][a-z0-9._-]{1,31}$')
ROLES = ('admin', 'operator')
MIN_LENGTH = 12
MAX_LENGTH = 128
# The deny-list: SecLists, Passwords/Common-Credentials/10-million-password-list-top-100.txt (Mark Burnett's
# ten-million-password corpus, 2015), copied from the SecLists release tag 2023.1 on 2026-11-01
# (sha256 780ebec6f93bd80aff2121c2644cf9e198ac1e361379ca73f28528fbcf044443; the file holds 101 lines, all kept).
# Compared casefolded after NFKC. A larger list is a file the image does not need (DESIGN 4.3).
COMMON_PASSWORDS = frozenset((
    '123456', 'password', '12345678', 'qwerty', '123456789', '12345', '1234', '111111', '1234567', 'dragon',
    '123123', 'baseball', 'abc123', 'football', 'monkey', 'letmein', '696969', 'shadow', 'master', '666666',
    'qwertyuiop', '123321', 'mustang', '1234567890', 'michael', '654321', 'pussy', 'superman', '1qaz2wsx', '7777777',
    'fuckyou', '121212', '000000', 'qazwsx', '123qwe', 'killer', 'trustno1', 'jordan', 'jennifer', 'zxcvbnm',
    'asdfgh', 'hunter', 'buster', 'soccer', 'harley', 'batman', 'andrew', 'tigger', 'sunshine', 'iloveyou',
    'fuckme', '2000', 'charlie', 'robert', 'thomas', 'hockey', 'ranger', 'daniel', 'starwars', 'klaster',
    '112233', 'george', 'asshole', 'computer', 'michelle', 'jessica', 'pepper', '1111', 'zxcvbn', '555555',
    '11111111', '131313', 'freedom', '777777', 'pass', 'fuck', 'maggie', '159753', 'aaaaaa', 'ginger',
    'princess', 'joshua', 'cheese', 'amanda', 'summer', 'love', 'ashley', '6969', 'nicole', 'chelsea',
    'biteme', 'matthew', 'access', 'yankees', '987654321', 'dallas', 'austin', 'thunder', 'taylor', 'matrix',
    'minecraft',
))
# Product names: a password that contains one is common (DESIGN 4.3); kept apart so COMMON_PASSWORDS stays the published list.
# Default account names and vendor defaults that the top-100 list does not hold; they take part in rules (i) and (ii) only.
BASE_WORDS = frozenset(('admin', 'root', 'clab', 'student', 'manager', 'secret', 'welcome', 'admin@123', 'clab@123', 'nokiasrl1!'))
PRODUCT_NAMES = ('containerlab', 'clab-manager', 'clabmanager', 'clab-backup', 'clabbackup', 'nodemanager', 'labmanager',
                 'administrator', 'changeme')
REASON_ORDER = ('too_short', 'too_long', 'equals_name', 'common')
REASON_SENTENCES = {
    'too_short': 'Use at least 12 characters.',
    'too_long': 'Use at most 128 characters.',
    'equals_name': 'Choose a password that is not your username.',
    'common': 'That password is too common. Choose another.',
}


def check_name(name):
    """The name rule of DESIGN 3.1: lowercase, 2 to 32 characters, letters, digits, dot, dash, underscore."""
    return isinstance(name, str) and NAME.fullmatch(name) is not None


def _is_common(lowered):
    """DESIGN 4.3, casefolded after NFKC: in the list (or a default account name); the same without trailing digits,
    punctuation and symbols; digits, punctuation and symbols only (no letter, not just whitespace); or containing a product name."""
    if lowered in COMMON_PASSWORDS or lowered in BASE_WORDS: return True
    stripped = lowered.rstrip(''.join(c for c in set(lowered) if c.isspace() or unicodedata.category(c)[0] in 'NPS'))
    if stripped and (stripped in COMMON_PASSWORDS or stripped in BASE_WORDS): return True
    if any(not c.isspace() for c in lowered) and all(c.isspace() or unicodedata.category(c)[0] in 'NPS' for c in lowered): return True
    return any(product in lowered for product in PRODUCT_NAMES)


def check_password(name, password):
    """The reason codes of DESIGN 4.3 in the order of 7.4; empty when the password is acceptable."""
    normal = unicodedata.normalize('NFKC', password)
    reasons = []
    if len(normal) < MIN_LENGTH: reasons.append('too_short')
    if len(normal) > MAX_LENGTH: reasons.append('too_long')
    lowered = normal.casefold(); lowered_name = (name or '').casefold()
    if lowered_name and (lowered == lowered_name or lowered_name in lowered): reasons.append('equals_name')
    if _is_common(lowered): reasons.append('common')
    return reasons


def message_for(reasons):
    """The 422 weak_password message: the sentences of the reasons, joined by one space, in the order of 7.4."""
    return ' '.join(REASON_SENTENCES[reason] for reason in REASON_ORDER if reason in reasons)


# ---- every error body (DESIGN 7.4), keyed by (status, code, route); '' is the sentence for every route ----
MESSAGES = {
    (401, 'signed_out', ''): 'Your session ended. Sign in again.',
    (401, 'invalid_credentials', 'POST /api/session'): 'Wrong username or password.',
    (401, 'invalid_credentials', 'POST /api/session/password'): 'The current password is not right.',
    (401, 'invalid_code', 'POST /api/setup'): 'That setup code is not right. On the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code',
    (403, 'admin_required', ''): 'Administrators only.',
    (403, 'password_change_required', ''): 'Choose your own password before you continue.',
    (404, 'setup_closed', 'POST /api/setup'): 'Setup is closed. Sign in, or ask the VM administrator to run the recovery command.',
    (404, 'user_not_found', ''): 'No account has that name.',
    (409, 'exists', 'POST /api/users'): 'That name already exists.',
    (409, 'exists', 'POST /api/setup'): 'That name already exists. Choose a new name for the recovery administrator.',
    (409, 'last_admin', ''): 'The last administrator stays.',
    (409, 'self_change', 'PATCH /api/users/{name} disabled'): 'You cannot deactivate your own account. Sign out instead.',
    (409, 'self_change', 'PATCH /api/users/{name} role'): 'You cannot change your own role. Ask another administrator.',
    (409, 'self_change', 'DELETE /api/users/{name}'): 'You cannot remove your own account. Ask another administrator.',
    (409, 'self_change', 'POST /api/users/{name}/password'): 'Use Manager ▾ › Change password… for your own account.',
    (422, 'invalid_name', ''): 'Use lowercase letters, digits, dot, dash or underscore, 2 to 32 characters.',
    (429, 'throttled', ''): 'Too many sign-in attempts. Try again in {n} s.',
    (503, 'setup_required', ''): 'This manager is not set up yet. Open /setup to create the first administrator.',
}


def message(status, code, route=''):
    """The sentence of a refusal: the route's own when 7.4 has one, else the one for every route. KeyError otherwise."""
    if (status, code, route) in MESSAGES: return MESSAGES[(status, code, route)]
    return MESSAGES[(status, code, '')]


def detail(status, code, route='', **extra):
    """The `detail` body of a refusal: {code, message, ...extra}. weak_password joins its reasons' sentences;
    throttled fills {n} from retry_after."""
    if code == 'weak_password': text = message_for(extra['reasons'])
    else:
        text = message(status, code, route)
        if code == 'throttled': text = text.format(n=extra['retry_after'])
    return {'code': code, **extra, 'message': text}


class AccountError(Exception):
    """A refusal of the account model; the route answers HTTPException(status, detail)."""
    def __init__(self, status, code, route='', **extra):
        super().__init__(code)
        self.status = status; self.code = code; self.detail = detail(status, code, route, **extra)


# ---- the audit vocabulary (DESIGN 10.2): the one table, as constants ----
AUDIT_EVENTS = ('setup', 'setup.failed', 'recover.requested', 'recover.expired', 'signin', 'signin.failed', 'signin.throttled',
                'signout', 'session.expired', 'session.ended', 'password.changed', 'user.created', 'user.deleted', 'user.disabled',
                'user.enabled', 'user.role', 'user.password_reset', 'forbidden', 'manager.reset')
AUDIT_OUTCOMES = ('ok', 'failed', 'throttled')
AUDIT_REASONS = ('setup', 'recover', 'invalid_code', 'weak_password', 'invalid_name', 'exists', 'invalid_credentials', 'disabled',
                 'bad_record', 'pair', 'source', 'name', 'busy', 'idle', 'absolute', 'user_disabled', 'user_deleted',
                 'password_reset', 'password_changed', 'evicted', 'admin_required')
FAILURE_EVENTS = ('signin.failed', 'signin.throttled', 'setup.failed')   # summed, written to audit-failures.jsonl


def failure_actor(users, name):
    """The actor of a failed or throttled attempt: the submitted name only when it is an existing record's,
    otherwise '-' (REVIEW R2: a password typed into the username field never reaches a file)."""
    return name if isinstance(name, str) and name in users else '-'


class FailureBuckets:
    """Per-minute summing of the failure events and `forbidden` (DESIGN 10.1): one open bucket per
    (event, source key, actor, target, reason) and UTC minute. Pure and unlocked: `Sessions` owns one and
    calls it under its lock; the caller writes what `flush` returns with `write_failure_entries` after
    releasing the lock. Bounded: above `limit` open buckets the one with the oldest first failure is
    flushed and returned by `add`."""
    def __init__(self, limit=10000):
        self.limit = limit
        self.buckets = {}

    def add(self, event, source_key, actor, reason, *, target='', retry_after=0, now=None):
        now = time.time() if now is None else now
        minute = int(now // 60)
        key = (event, source_key, actor, target, reason, minute)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = dict(time=now, event=event, source=source_key, actor=actor, target=target,
                                              reason=reason, count=0, retry_after=0, minute=minute)
        bucket['count'] += 1
        bucket['retry_after'] = max(bucket['retry_after'], int(retry_after or 0))
        overflow = []
        while len(self.buckets) > self.limit:
            oldest = min(self.buckets, key=lambda k: self.buckets[k]['time'])
            overflow.append(self.entry(self.buckets.pop(oldest)))
        return overflow

    def open_entries(self):
        """The open buckets as entries, for GET /api/audit (an attack in progress is visible at once)."""
        return [self.entry(bucket) for bucket in self.buckets.values()]

    def flush(self, now=None, force=False):
        """Removes and returns the buckets whose minute has passed (every bucket with `force`)."""
        now = time.time() if now is None else now
        current = int(now // 60)
        closed = [key for key, bucket in self.buckets.items() if force or bucket['minute'] < current]
        return [self.entry(self.buckets.pop(key)) for key in closed]

    @staticmethod
    def entry(bucket):
        detail_text = f"{bucket['reason']} count={bucket['count']}"
        if bucket['event'] == 'signin.throttled': detail_text += f" retry_after={bucket['retry_after']}"
        outcome = 'throttled' if bucket['event'] == 'signin.throttled' else 'failed'
        return Store.audit_entry(bucket['event'], actor=bucket['actor'], source=bucket['source'], outcome=outcome,
                                 target=bucket['target'], detail=detail_text,
                                 time=datetime.fromtimestamp(bucket['time'], timezone.utc).isoformat(timespec='microseconds'))


def write_failure_entries(store, entries):
    """Writes flushed buckets: the three failure events to audit-failures.jsonl, `forbidden` to the security record."""
    for entry in entries:
        if entry['event'] == 'forbidden':
            store.audit(entry['event'], actor=entry['actor'], source=entry['source'], outcome=entry['outcome'],
                        target=entry['target'], detail=entry['detail'], time=entry['time'])
        else:
            store.audit_failure(entry['event'], actor=entry['actor'], source=entry['source'], outcome=entry['outcome'],
                                detail=entry['detail'], time=entry['time'])


# ---- the setup code (DESIGN 9.2, 9.5) ----
SETUP_ALPHABET = 'abcdefghjkmnpqrstuvwxyz23456789'   # 31 symbols, no 0/o/1/l/i; 24 of them are about 119 bits
CODE_LENGTH = 24
CODE_GROUP = 6
SETUP_FILE = 'setup-code'
RECOVER_TTL = 15*60
SETUP_LOG = ('Setup required: open https://{address}:{port}/setup and enter the code from {file} '
             '(on the VM: sudo cat /srv/containerlab-node-manager/data/setup-code).')


def generate_code():
    return ''.join(secrets.choice(SETUP_ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code):
    return '-'.join(code[i:i+CODE_GROUP] for i in range(0, len(code), CODE_GROUP))


def normalize_code(text):
    """How both sides of the comparison read a code: strip, lowercase, dashes and spaces removed (REVIEW U13)."""
    return str(text or '').strip().lower().replace('-', '').replace(' ', '')


def code_matches(expected, submitted):
    return hmac.compare_digest(normalize_code(expected).encode('utf8'), normalize_code(submitted).encode('utf8'))


def write_setup_code(root, mode):
    """Writes <root>/setup-code (0600 through Store.atomic) with `mode=<mode>` and `code=<new code>`; returns the code."""
    code = format_code(generate_code())
    Store.atomic(Path(root)/SETUP_FILE, f'mode={mode}\ncode={code}\n'.encode('utf8'))
    return code


def delete_setup_code(root):
    (Path(root)/SETUP_FILE).unlink(missing_ok=True)


def drop_stale_setup_code(root):
    """Removes a `mode=setup` file that exists while users do (a restored /data, an unlink that failed after the
    save): setup is closed once the first administrator exists, and the file would otherwise serve the setup page
    and accept its code again. A `recover` file is left alone. True when a file was removed."""
    found = read_setup_code(root)
    if found is None or found[0] != 'setup': return False
    delete_setup_code(root)
    return True


def read_setup_code(root, on_expired=None):
    """(mode, code) from <root>/setup-code, read on every request (no code is kept in memory). None when the file is
    absent, a symlink, not a regular file, wider than 0600, malformed, or a `recover` file older than RECOVER_TTL,
    which is deleted and reported through `on_expired` (the caller audits recover.expired)."""
    path = Path(root)/SETUP_FILE
    try: fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    except OSError: return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077: return None
        data = os.read(fd, 4096)
    except OSError: return None
    finally: os.close(fd)
    try: text = data.decode('utf8')
    except UnicodeDecodeError: return None
    fields = {}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        if separator: fields[key] = value.strip()
    mode = fields.get('mode'); code = fields.get('code', '')
    bare = normalize_code(code)
    if mode not in ('setup', 'recover') or len(bare) != CODE_LENGTH or not set(bare) <= set(SETUP_ALPHABET): return None
    if mode == 'recover' and time.time() - info.st_mtime > RECOVER_TTL:
        path.unlink(missing_ok=True)
        if on_expired: on_expired()
        return None
    return mode, code


def setup_log_line(root, port, address):
    """The container log line of 9.2: the file and the command, never the code (REVIEW R22a)."""
    return SETUP_LOG.format(address=address or "the VM's address", port=port, file=Path(root)/SETUP_FILE)


# ---- the record (DESIGN 3) ----
PUBLIC_FIELDS = ('name', 'role', 'disabled', 'must_change_password', 'created', 'created_by', 'password_changed', 'last_signin')
KNOWN_SOURCES = 8


def now():
    return Store.now()


def new_record(name, role, hash_string, *, created_by, must_change_password, known_sources=()):
    if not check_name(name): raise ValueError('invalid user name')
    if role not in ROLES: raise ValueError('invalid role')
    stamp = now()
    return {'name': name, 'role': role, 'password': hash_string, 'disabled': False, 'must_change_password': bool(must_change_password),
            'created': stamp, 'created_by': created_by, 'password_changed': stamp, 'last_signin': None, 'known_sources': list(known_sources)}


def public_user(record, sessions=0):
    """Exactly name, role, disabled, must_change_password, created, created_by, password_changed, last_signin and
    `sessions`: an allowlisted copy, never the record (`password` and `known_sources` never leave the state)."""
    shown = {field: record.get(field) for field in PUBLIC_FIELDS}
    if parse_hash(record.get('password')) is None: shown['password_changed'] = None   # a record that cannot sign in (4.2)
    shown['sessions'] = sessions
    return shown


def remember_source(record, prefix):
    """Appends a source prefix to the private known_sources: 8 distinct prefixes, newest last; a known one moves to the end."""
    sources = record.setdefault('known_sources', [])
    if prefix in sources: sources.remove(prefix)
    sources.append(prefix)
    del sources[:-KNOWN_SOURCES]


def is_last_admin(users, name):
    """True when `name` is the only enabled administrator (the last-admin rule, 3.2); call it under store.lock."""
    record = users.get(name)
    if not record or record['role'] != 'admin' or record['disabled']: return False
    return not any(other['role'] == 'admin' and not other['disabled'] for key, other in users.items() if key != name)


class Accounts:
    """`app.state.accounts`: the record operations, each under store.lock with save → index → audit in one block."""
    def __init__(self, store, sessions=None):
        self.store = store
        self.sessions = sessions   # the Sessions object (S1b); None only in unit tests of this module

    # the functions above, as members (DESIGN 16.1)
    verify_password = staticmethod(verify_password)
    hash_password = staticmethod(hash_password)
    check_name = staticmethod(check_name)
    check_password = staticmethod(check_password)
    message_for = staticmethod(message_for)
    normalize_code = staticmethod(normalize_code)
    async def averify(self, hash_string, password): return await averify(hash_string, password)
    async def ahash(self, password): return await ahash(password)

    def public_user(self, record):
        return public_user(record, self.sessions.count(record['name']) if self.sessions else 0)

    def install(self, app):
        """The admin-only users and audit routes (the module function `install` below, bound to app.state.accounts)."""
        install(app)

    def read_setup_code(self, root=None):
        """(mode, code) of a file that is valid now: an expired recovery file is deleted and audited (9.5), and a
        `mode=setup` file beside existing users is stale, deleted and reported as absent (9.4: setup is closed)."""
        root = self.store.root if root is None else root
        found = read_setup_code(root, on_expired=lambda: self.store.audit('recover.expired', actor='-', source='-', outcome='ok'))
        if found is not None and found[0] == 'setup' and self._users_exist():
            delete_setup_code(root); return None
        return found

    def _users_exist(self):
        return not self.sessions.setup_mode() if self.sessions is not None and hasattr(self.sessions, 'setup_mode') else bool(self.users())

    def users(self):
        return self.store.state.get('users', {})

    def record(self, name):
        return self.users().get(name)

    def _writable_users(self):
        return self.store.state.setdefault('users', {})

    def _save_or_restore(self, record, prior):
        try: self.store.save()
        except OSError:
            record.clear(); record.update(prior)
            raise

    def _save_or_drop(self, name):
        try: self.store.save()
        except OSError:
            self._writable_users().pop(name, None)
            raise

    def _index(self, record):
        if self.sessions: self.sessions.set_user(record)

    def create(self, name, role, hash_string, *, actor, source='', created_by=None, must_change_password=True, known_sources=()):
        """POST /api/users: a new record, must_change_password by default; 409 exists, 422 invalid_name."""
        if not check_name(name): raise AccountError(422, 'invalid_name')
        if role not in ROLES: raise ValueError('invalid role')
        with self.store.lock:
            users = self._writable_users()
            if name in users: raise AccountError(409, 'exists', 'POST /api/users')
            record = users[name] = new_record(name, role, hash_string, created_by=created_by or actor,
                                              must_change_password=must_change_password, known_sources=known_sources)
            self._save_or_drop(name)
            self._index(record)
            self.store.audit('user.created', actor=actor, source=source, outcome='ok', target=name, detail=f'role={role}')
            return record

    def complete_setup(self, name, hash_string, *, code, mode, source, prefix):
        """POST /api/setup in setup (`mode='setup'`) or recovery (`'recover'`) mode: one new admin who chose their own
        password; an existing name answers 409 exists and writes nothing (REVIEW R11). The file is read again under
        store.lock and must still exist, still hold `code` and still say `mode` (and a setup file beside existing
        users is no file at all): a second submit of a used code, inside the hash window of the first, is refused
        404 setup_closed, so one code creates one administrator (9.2, 9.5). Save, index, delete the file and audit
        run in one locked block; a failed save leaves the file and raises OSError (the route's 500)."""
        if not check_name(name): raise AccountError(422, 'invalid_name')
        with self.store.lock:
            users = self._writable_users()
            found = self.read_setup_code()
            if found is None or found[0] != mode or not code_matches(found[1], code):
                raise AccountError(404, 'setup_closed', 'POST /api/setup')
            if name in users: raise AccountError(409, 'exists', 'POST /api/setup')
            record = users[name] = new_record(name, 'admin', hash_string, created_by=mode, must_change_password=False,
                                              known_sources=[prefix] if prefix else [])
            record['last_signin'] = now()
            self._save_or_drop(name)
            self._index(record)
            delete_setup_code(self.store.root)
            self.store.audit('setup', actor=name, source=source, outcome='ok', detail=mode)
            return record

    def update(self, name, *, actor, source='', role=None, disabled=None):
        """PATCH /api/users/{name}: role and/or disabled. 404; 409 self_change (own record); 409 last_admin."""
        if role is not None and role not in ROLES: raise ValueError('invalid role')
        with self.store.lock:
            users = self._writable_users()
            record = users.get(name)
            if record is None: raise AccountError(404, 'user_not_found')
            if name == actor:
                if disabled is True: raise AccountError(409, 'self_change', 'PATCH /api/users/{name} disabled')
                if role is not None: raise AccountError(409, 'self_change', 'PATCH /api/users/{name} role')
            disables = disabled is True and not record['disabled']
            demotes = role == 'operator' and record['role'] == 'admin'
            if (disables or demotes) and is_last_admin(users, name): raise AccountError(409, 'last_admin')
            prior = dict(record); changes = []
            if role is not None and role != record['role']:
                record['role'] = role; changes.append(('user.role', f'role={role}'))
            if disabled is not None and bool(disabled) != record['disabled']:
                record['disabled'] = bool(disabled); changes.append(('user.disabled' if disabled else 'user.enabled', ''))
            if not changes: return record
            self._save_or_restore(record, prior)
            self._index(record)
            if disables and self.sessions: self.sessions.end_user(name, 'user_disabled')
            for event, detail_text in changes:
                self.store.audit(event, actor=actor, source=source, outcome='ok', target=name, detail=detail_text)
            return record

    def delete(self, name, *, actor, source=''):
        """DELETE /api/users/{name}: 404; 409 self_change; 409 last_admin."""
        with self.store.lock:
            users = self._writable_users()
            record = users.get(name)
            if record is None: raise AccountError(404, 'user_not_found')
            if name == actor: raise AccountError(409, 'self_change', 'DELETE /api/users/{name}')
            if is_last_admin(users, name): raise AccountError(409, 'last_admin')
            users.pop(name)
            try: self.store.save()
            except OSError:
                users[name] = record
                raise
            if self.sessions:
                self.sessions.drop_user(name)
                self.sessions.end_user(name, 'user_deleted')
            self.store.audit('user.deleted', actor=actor, source=source, outcome='ok', target=name)

    def reset_password(self, name, hash_string, *, actor, source=''):
        """POST /api/users/{name}/password: sets the password and must_change_password, moves the stamp, ends every
        session of the user; 404; 409 self_change for the own name (REVIEW R12)."""
        with self.store.lock:
            record = self.record(name)
            if record is None: raise AccountError(404, 'user_not_found')
            if name == actor: raise AccountError(409, 'self_change', 'POST /api/users/{name}/password')
            prior = dict(record)
            record['password'] = hash_string; record['password_changed'] = now(); record['must_change_password'] = True
            self._save_or_restore(record, prior)
            self._index(record)
            if self.sessions: self.sessions.end_user(name, 'password_reset')
            self.store.audit('user.password_reset', actor=actor, source=source, outcome='ok', target=name)
            return record

    def change_password(self, name, hash_string, *, session_id, source=''):
        """POST /api/session/password, after the current password verified: the new string and stamp, then in this
        order rotate the current session, refresh the index, end the other sessions (DESIGN 5.5). Returns the new id."""
        with self.store.lock:
            record = self.record(name)
            if record is None: raise AccountError(404, 'user_not_found')
            # The session must still be there to rotate: a second submit of the same change (the first rotated the
            # id) or a session an admin ended meanwhile is refused signed_out before anything is written; otherwise
            # `rotate` would answer None and `end_user(keep=None)` would end the rotated session too.
            if self.sessions and self.sessions.get(session_id) is None: raise AccountError(401, 'signed_out')
            prior = dict(record)
            record['password'] = hash_string; record['password_changed'] = now(); record['must_change_password'] = False
            self._save_or_restore(record, prior)
            new_id = None
            if self.sessions:
                new_id = self.sessions.rotate(session_id, record['password_changed'])
                self.sessions.set_user(record)
                self.sessions.end_user(name, 'password_changed', keep=new_id)
            self.store.audit('password.changed', actor=name, source=source, outcome='ok')
            return new_id

    def replace_hash(self, name, hash_string):
        """The rehash of 4.2: a new string, the same stamp (the password did not change; sessions stay valid)."""
        with self.store.lock:
            record = self.record(name)
            if record is None: return False
            prior = dict(record)
            record['password'] = hash_string
            self._save_or_restore(record, prior)
            return True

    def rehash(self, name, password):
        """Synchronous rehash on sign-in when the record's parameters differ from PARAMS; the hash runs outside the
        lock. An async route awaits `ahash` and calls `replace_hash` instead. True when a new string was written."""
        record = self.record(name)
        if record is None or not needs_rehash(record['password']): return False
        return self.replace_hash(name, hash_password(password))

    def record_signin(self, name, prefix, source):
        """A successful sign-in: last_signin and the private known_sources in one save, then the `signin` entry."""
        with self.store.lock:
            record = self.record(name)
            if record is None: raise AccountError(404, 'user_not_found')
            prior = dict(record); prior['known_sources'] = list(record.get('known_sources', []))
            record['last_signin'] = now()
            if prefix: remember_source(record, prefix)
            self._save_or_restore(record, prior)
            self.store.audit('signin', actor=name, source=source, outcome='ok')
            return record


# ---- the admin-only routes (DESIGN 7.3; BUILD.md S1b) ----
class NewUser(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(max_length=256)
    role: str = Field(max_length=32)
    password: str = Field(max_length=1024)


class UserPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: str | None = Field(default=None, max_length=32)
    disabled: bool | None = None


class NewPassword(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(max_length=1024)


class EmptyBody(BaseModel):
    model_config = ConfigDict(extra='forbid')


def install(app):
    """The users routes and GET /api/audit, every one behind `require_admin`. The hashes of the `def` routes run on
    SCRYPT_EXECUTOR through a submitted future (4.1); the record operations are those of `app.state.accounts`."""
    from .sessions import require_admin, client_address   # here, not at module level: sessions imports this module
    accounts = app.state.accounts; store = accounts.store; sessions = accounts.sessions

    def refused(exc):
        return HTTPException(exc.status, exc.detail)

    def policy(name, password):
        reasons = check_password(name, password)
        if reasons: raise HTTPException(422, detail(422, 'weak_password', reasons=reasons))

    def hashed(password):
        return SCRYPT_EXECUTOR.submit(hash_password, password).result()

    def shown(record):
        return accounts.public_user(record)

    @app.get('/api/users')
    def list_users(user: dict = Depends(require_admin)):
        with store.lock: records = [dict(record) for record in accounts.users().values()]
        return {'users': [shown(record) for record in sorted(records, key=lambda r: r['name'])]}

    @app.post('/api/users')
    def create_user(data: NewUser, request: Request, user: dict = Depends(require_admin)):
        name = data.name.strip().lower()
        if not check_name(name): raise HTTPException(422, detail(422, 'invalid_name'))
        if data.role not in ROLES: raise HTTPException(422, {'code': 'invalid_role', 'message': 'Choose admin or operator.'})
        policy(name, data.password)
        try: record = accounts.create(name, data.role, hashed(data.password), actor=user['name'], source=client_address(request))
        except AccountError as exc: raise refused(exc)
        except OSError: raise HTTPException(500, 'Could not save the account; nothing was changed. Check manager storage and retry.')
        return {'user': shown(record)}

    @app.patch('/api/users/{name}')
    def patch_user(name: str, data: UserPatch, request: Request, user: dict = Depends(require_admin)):
        if data.role is not None and data.role not in ROLES: raise HTTPException(422, {'code': 'invalid_role', 'message': 'Choose admin or operator.'})
        try: record = accounts.update(name, actor=user['name'], source=client_address(request), role=data.role, disabled=data.disabled)
        except AccountError as exc: raise refused(exc)
        except OSError: raise HTTPException(500, 'Could not save the account; nothing was changed. Check manager storage and retry.')
        return {'user': shown(record)}

    @app.delete('/api/users/{name}')
    def delete_user(name: str, data: EmptyBody, request: Request, user: dict = Depends(require_admin)):
        try: accounts.delete(name, actor=user['name'], source=client_address(request))
        except AccountError as exc: raise refused(exc)
        except OSError: raise HTTPException(500, 'Could not save the removal; nothing was changed. Check manager storage and retry.')
        return {'deleted': True}

    @app.post('/api/users/{name}/password')
    def reset_user_password(name: str, data: NewPassword, request: Request, user: dict = Depends(require_admin)):
        with store.lock: exists = accounts.record(name) is not None
        if not exists: raise HTTPException(404, detail(404, 'user_not_found'))
        if name == user['name']: raise HTTPException(409, detail(409, 'self_change', 'POST /api/users/{name}/password'))
        policy(name, data.password)
        try: record = accounts.reset_password(name, hashed(data.password), actor=user['name'], source=client_address(request))
        except AccountError as exc: raise refused(exc)
        except OSError: raise HTTPException(500, 'Could not save the password; nothing was changed. Check manager storage and retry.')
        return {'user': shown(record)}

    @app.get('/api/audit')
    def audit(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), event: str = Query('', max_length=1000),
              actor: str = Query('', max_length=64), outcome: str = Query('', max_length=16), since: str = Query('', max_length=64),
              address: str = Query('', max_length=64), user: dict = Depends(require_admin)):
        sessions.flush_failures()   # closed buckets go to their file first, so the merge below sees them once
        entries, total = store.audit_entries(limit, offset, event=event, actor=actor, outcome=outcome, since=since, address=address,
                                             extra=sessions.open_failures())
        return {'entries': entries, 'total': total}
