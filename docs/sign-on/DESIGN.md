# Sign-on: accounts, sessions, authorization and auditing

The binding design of the account, session, authorization and audit parts of the sign-on campaign.
The task is [PROMPT.md](PROMPT.md) (D1 local accounts, D2 Admin + Operator with shared labs, D3 the
threat model); the facts it fits are [INVENTORY.md](INVENTORY.md). Base: `main` at 1.31.8
(`fac28de`); every file:line below is to that commit. Written 2026-11-01, before code.

| Part | Where |
|---|---|
| Threat model, accounts, hashing, sessions, the gate, roles, throttling, bootstrap, audit, tickets, migration, tests | this file |
| TLS, the firewall, the installer, the health check, the recovery script's host side | [EXPOSURE.md](EXPOSURE.md) |
| The sign-in and setup pages, 401 handling in every script, the account menu, the Users and Audit pages | [UI.md](UI.md) |
| The Opus design review and the answer to each finding | REVIEW.md (written by the review step) |

Where EXPOSURE.md or UI.md and this file disagree on a route, a record, a cookie or a status code,
this file wins; section 17 states the contract exactly as UI.md was briefed and every change to it.

Defined terms, used with these meanings throughout:

| Term | Meaning |
|---|---|
| **manager** | The FastAPI process built by `create_app` (main.py:50-516), one process (`--workers 1`, compose.yml:8). |
| **user** | A record in `state['users']` (section 3). |
| **admin**, **operator** | The two roles (D2). |
| **session** | An in-memory record created by a successful sign-in, named by a session id, carried by the cookie `clab_session` (section 5). |
| **gate** | The ASGI layer `SessionGate` that resolves the cookie and refuses what has no session (section 6). |
| **guard** | The existing same-origin HTTP middleware `guard` (main.py:119-156). Unchanged by this design except for the actor it logs. |
| **setup mode** | The manager's state while `state['users']` is empty (section 9). |
| **setup code** | The one-time code that `POST /api/setup` requires (section 9). |
| **source** | The client address of a request as the ASGI server reports it (`scope['client'][0]`), never a forwarded header (section 5.6). |
| **actor** | The user name of the session that made a request, or `-` when there is none. |

## 1. Threat model

### 1.1 Assets

| Asset | Where it is today | Why it matters |
|---|---|---|
| Device and VM credentials | `state.enc` under `state.key` (store.py:18-26); profiles store passwords and keys (main.py:385, INVENTORY 6.2) | They open every lab device and the VM's discovery account. |
| Device access itself | the terminal and console sockets (node_services.py:570-658), restore (`restore.py:1497`), design apply, operations confirm | A session on the manager is a shell on every node. |
| Configuration backups and Git checkouts | `/data/backups`, the VM's owner checkouts | Running configurations of real labs. |
| The VM behind the manager | the gateway helpers (CLAUDE.md "Three paths out of the container") | The manager's reach is bounded by the helpers, not by the manager. |
| Account records, the audit log | new in this design | Their loss hides an intrusion; their leak hands over password hashes. |

### 1.2 Attackers

| Attacker | Capability | What stops them |
|---|---|---|
| **A1 Internet scanner** with credential lists | Finds the port within hours; sends thousands of sign-in attempts from many addresses; fingerprints the product from any unauthenticated page or header. | Nothing but `/login`, `/setup`, three static assets and `/api/health` answers without a session (6.3). scrypt makes each guess cost about 50 ms of CPU and 32 MiB of memory on the server (4.1); throttling makes each source slow after five failures (8); no response differs between an unknown user and a wrong password (8.4); the setup page is not reachable once an admin exists (9.4). |
| **A2 A student on the same network** (or on the manager's `.local` link) | Can reach the port, can read the sign-in page, cannot read the cookie of another browser. Can watch plain HTTP traffic if TLS is absent. | Everything that A1 meets, plus TLS (EXPOSURE.md) so the password and the cookie never travel in clear text. The role model: an operator cannot create users, change the VM connection or read the audit log (7). |
| **A3 A stolen laptop with a live session** | Holds a valid cookie until it expires. | Idle timeout 12 h, absolute 7 days (5.4); an admin disables the user or resets the password and every session of that user ends at once (5.5); the audit log shows the source address of each sign-in (10). |
| **A4 A script on an attacker's page** in the victim's browser (CSRF, DNS rebinding) | Can make the browser send requests to the manager. | `SameSite=Strict` keeps the cookie off every cross-site request; the guard's Origin check (main.py:123) and `HostCheck` (allowed_hosts.py:79-99) stay in front of every route (6.6). |

### 1.3 Out of scope

- The VM's own SSH service, Docker, the lab nodes' published ports, the firewall and the TLS edge:
  EXPOSURE.md.
- An attacker with root on the VM, or with a copy of `state.key` and `state.enc`: they hold every
  device credential already (store.py:21-26). Password hashes are stored with scrypt so such a copy
  does not also yield the users' passwords for reuse elsewhere (4).
- A compromised browser extension in a signed-in browser: it has what the user has.
- Per-user labs, per-user Git identities, OIDC: D1 and D2 defer them. Nothing in this design blocks
  a later provider: the session record carries a `provider` field fixed to `local` (5.2).

## 2. What changes, in one table

| Area | Today (file:line) | After this design |
|---|---|---|
| Access to pages and `/api/` | None: `/`, `/static/*`, both guides and every route answer anyone (main.py:501-512; INVENTORY 6.1) | The gate refuses every request without a session except the exemption list (6.3). |
| WebSockets | Origin check only (node_services.py:572-576; capture_sessions.py:317-321) | The gate closes 1008 before accept when no session; the Origin checks stay (6.5). |
| Terminal ticket | Bound to nothing (node_services.py:566-567) | Bound to the session that minted it (11.1). |
| Users | None | `state['users']` (3), admin routes (7.3). |
| Logs | `events.jsonl` without actor or source (store.py:115-138) | `events.jsonl` gains `actor`; a new `audit.jsonl` holds security events (10). |
| `ui.token` | Read into `Store.token` (store.py:22-23), hidden by the runner (runner.py:420), sent by `test_app.py:47` | Removed from the read path (12.2). |
| Startup banner | `'UI login is disabled for this lab VM.'` (main.py:72) | `'Containerlab Node Manager ready; sign-in required.'` or, in setup mode, the setup code notice (9.2). |
| CLAUDE.md invariant "There is no login" | CLAUDE.md "VM boundary and data" | Replaced by the text in section 14. |

## 3. The account model

### 3.1 The record

`state['users']` is a dictionary keyed by user name. A dictionary gives uniqueness by construction;
nothing else in the state needs an ordered user list. Readers use `state.get('users', {})` like every
other lazily added key (INVENTORY 6.5).

| Field | Type | Rule |
|---|---|---|
| `name` | string | The key, repeated in the record. Lowercase, 2 to 32 characters, `^[a-z0-9][a-z0-9._-]{1,31}$`. Compared exactly; the sign-in form lowercases before sending, the route lowercases again. A name is never renamed: delete and create. |
| `role` | `admin` or `operator` | Nothing else is accepted (`extra='forbid'` on every body model, as main.py:222). |
| `password` | string | A self-describing hash string (4.2). Never copied by any `public_*` view. |
| `disabled` | boolean | A disabled user cannot sign in; their sessions end when the flag is set (5.5). |
| `must_change_password` | boolean | Set when an admin sets or resets the password; cleared by the user's own change (3.4). |
| `created` | ISO 8601 UTC | As `Store.event` writes time (store.py:117). |
| `created_by` | string | The actor that created the record; `setup` for the first admin, `recover` for a recovery admin (9.5). |
| `password_changed` | ISO 8601 UTC | Updated by every password set. Each session carries a copy; a mismatch ends the session (5.5). |

No email, no display name, no last-sign-in field in the record: the last sign-in is an audit fact
(10), and the record stays what `/api/users` may show.

### 3.2 Uniqueness and the last-admin rule

- A name exists once. `POST /api/users` with an existing name answers 409 `{detail:{code:'exists'}}`.
  The admin who creates users already knows the names, so this does not leak anything to A1 (the
  route needs an admin session).
- **The last-admin rule.** At least one record with `role: admin` and `disabled: false` must exist
  once setup is complete. `PATCH` that disables or demotes, and `DELETE`, refuse with 409
  `{detail:{code:'last_admin'}}` when the target is that record. The rule is checked under
  `store.lock` in the same block that writes the change.
- **No self-change of role or state.** An admin cannot disable, demote or delete their own record:
  409 `{detail:{code:'self_change'}}`. A second admin does it. This keeps the last-admin rule simple
  and prevents an admin from locking the manager by a slip.
- An admin may reset their own password through `POST /api/users/{name}/password`; the effect is
  the same as `POST /api/session/password` without the current password check, and it ends their
  other sessions like any reset (5.5).

### 3.3 Start fresh keeps users and the audit log

`Store.reset` (store.py:98-111) builds the fresh document from a fixed list of keys
(`labs, jobs, operations, git_jobs, ignored_labs, host, reset_id`, store.py:106-107) and moves
`backups`, `network-design`, the event log and `ui.token` aside (store.py:102). The design adds
`users` to the copied keys, next to `host`, and does **not** add `audit.jsonl` to the moved list.

Reasons:

1. A reset that emptied `users` would put the manager back into setup mode (9), with the setup page
   open on an Internet-exposed address until an operator noticed. PROMPT D3 point 2 forbids a setup
   page left open. *Start fresh* is reachable by any admin from the UI; its blast radius must stay
   "labs, jobs and backups", as the invariant says (CLAUDE.md "*Remove lab* and *Start fresh* are
   manager-only").
2. The VM connection already survives a reset for the same reason (`host` is copied,
   store.py:104-107; the route answers `vm_connection_retained: true`, main.py:245). Users are the
   same kind of installation fact.
3. An audit log that a reset erases is not an audit log. The reset itself is audited (10.2).

`finish_reset` (store.py:63-96) applies a prepared document from the journal; because the prepared
document is built by `reset()` from the running state, it carries `users` without further change.
A journal prepared by an older release (no `users` key) is applied as it is; the manager then enters
setup mode, which is the upgrade behaviour of section 12.1 and is audited.

### 3.4 What reaches the browser

- `/api/state` (main.py:247-261) is not changed. `users` is a top-level key that none of its copies
  read; nothing has to be stripped. A test asserts that the JSON of `/api/state` contains neither
  `users` nor the substring `scrypt$` (13.1).
- `GET /api/users` and every users route answer through one function `public_user(record)` that
  copies exactly `name, role, disabled, must_change_password, created, created_by, password_changed`
  and adds `sessions` (the count of live sessions, from memory). Allowlisted copies, never the record
  (CLAUDE.md "Public views strip secrets").
- `GET /api/session` answers `{user:{name, role, must_change_password}, expires}` for the session's own
  user only.

## 4. Password hashing and policy

### 4.1 scrypt from the standard library

**Decision: `hashlib.scrypt`, no new dependency.** `argon2-cffi` is the better algorithm on paper, but
the Dockerfile installs `requirements.txt` without hashes (Dockerfile:7; INVENTORY 1) and the only
crypto dependency is `cryptography` (requirements.txt:8). Adding a compiled dependency to an
unhashed install widens the supply chain of an exposed product for a gain that the threat model does
not need: A1 is stopped by throttling and the sign-in cost, not by the last factor of hash hardness.
scrypt is memory-hard, in OpenSSL, and needs nothing installed.

Parameters: `n=2**15, r=8, p=1, dklen=32`, salt 32 bytes from `secrets.token_bytes(32)`.

**Measured on the design machine** (system Python 3.13, OpenSSL): a verify with these parameters
takes about 51 ms and needs about 32 MiB; **`hashlib.scrypt` with the default `maxmem` refuses these
parameters** (`ValueError: memory limit exceeded`). Every call passes `maxmem=64*1024*1024`. The image
is `python:3.12-slim` (Dockerfile:1); the build must re-measure there and a test asserts that a verify
with the shipped parameters succeeds and takes less than 500 ms (13.4).

Memory bound: a verify holds 32 MiB. FastAPI runs a `def` route in a thread pool of 40 threads, so 40
concurrent sign-in attempts would hold 1.3 GiB. The verify runs under a process-wide
`threading.BoundedSemaphore(4)`; a fifth concurrent attempt waits for a slot (it does not fail). With
the per-source throttle (8) an attacker cannot keep four slots busy for long, and a legitimate sign-in
waits at most a few hundred milliseconds.

### 4.2 The hash string

```
scrypt$<n>$<r>$<p>$<salt>$<hash>
```

`n`, `r`, `p` decimal; `salt` and `hash` URL-safe base64 without padding. Parsing: split on `$`, exactly
six parts, first part `scrypt`, integers in range (`n` a power of two between `2**14` and `2**20`,
`r` 1 to 32, `p` 1 to 16), salt 16 to 64 bytes, hash 32 bytes. A record whose string does not parse
cannot sign in (verify returns False; the audit event says `outcome: 'bad_record'`, 10.2) and is shown
to admins with `password_changed: null`.

Verify: parse the string, recompute with the string's own parameters, compare with
`hmac.compare_digest`. **Rehash on sign-in**: when the string's parameters differ from the shipped
constants and the password verified, the route writes a new string with the shipped parameters
under `store.lock` and saves. This is how a future parameter change reaches old records without a
migration step. The `password_changed` stamp does **not** move on a rehash (the password did not
change; sessions stay valid).

**Dummy verify.** When the submitted name is not a user, or the user is disabled, the route verifies
the submitted password against a fixed constant hash string `DUMMY_HASH` (computed once at import
from a random password with the shipped parameters) and discards the result. Every sign-in attempt
therefore costs one scrypt whether the user exists or not (8.4).

### 4.3 Policy

| Rule | Value | Why (NIST SP 800-63B, section 5.1.1.2 of the 2017 text and section 3.1.1 of revision 4) |
|---|---|---|
| Minimum length | 12 characters | NIST requires at least 8 and recommends 15 for user-chosen passwords; 12 is the floor this product accepts for an account that opens a shell on every lab device. Counted in Unicode code points after NFKC normalization. |
| Maximum length | 128 characters | NIST requires at least 64 be accepted; 128 bounds the scrypt input. Longer: 422 `{detail:{code:'password_too_long'}}`. |
| Composition rules | None | NIST forbids requiring character classes; they shift users to predictable substitutions. |
| Equal to the user name (case-insensitive), or the user name inside the password | Refused | A credential list pairs them. |
| Deny-list | The top 100 of a published breached-password list, embedded as a frozen set in `app/accounts.py` with its source and date in a comment | NIST requires a check against known-compromised values; 100 entries cover what a spraying scanner tries first; a larger list is a file the image does not need. |
| Whitespace | Leading and trailing whitespace is kept (not stripped); an all-whitespace password fails the length rule after NFKC like any other | Stripping would make two passwords equal that the user typed differently. |
| Expiry | None | NIST forbids periodic rotation; `must_change_password` (3.1) is the only forced change, after an admin set the password. |

The policy function `check_password(name, password)` returns a list of reason codes (`too_short`,
`too_long`, `equals_name`, `common`) and the route answers 422 `{detail:{code:'weak_password',
reasons:[...]}}`. The sign-in page never runs the policy (a sign-in verifies what is stored); the
setup, create, reset and own-change paths do.

## 5. Sessions

### 5.1 In memory only

**Decision: sessions live in the process, not in `state.enc`.** The record is kept in a dictionary
keyed by the session id, under its own `threading.Lock` (never `store.lock`: the gate must not wait
for a backup's state save).

| Option | For | Against |
|---|---|---|
| In memory (chosen) | No session secret touches disk. No write amplification: `GET /api/state` runs every 4 s per browser (app.js:576), and a persisted sliding `last_seen` would encrypt and rewrite the whole state document on that cadence or need a coarse renewal rule. `--workers 1` is fixed in `compose.yml:8` and `deploy/compose.image.yml`, so one process holds every session. A restart is already a full interruption: every terminal and console socket drops (node_services.py:216-221) and the UI reloads. | A restart (upgrade, `recreate-manager.sh`, a crash) signs everyone out. For a lab tool whose restarts are operator actions, this costs one sign-in and is in itself a safe default after an incident. |
| Persisted in `state.enc` | Survives restarts. | Puts a second class of secret in the most sensitive file; needs pruning on every path; the sliding renewal either rewrites the state every 4 s or becomes coarse. |

The restart cost is handled by UI.md: a 401 on the poll redirects to `/login?next=<the current
address>` and the user lands where they were.

### 5.2 The record

```
sessions[id] = {
  'user': 'alice',                 # the user name
  'role': 'operator',              # copied at sign-in; re-read from the record on every request (5.5)
  'provider': 'local',             # fixed; a later OIDC provider writes its own value
  'created': <monotonic>, 'created_at': <iso>,
  'last_seen': <monotonic>,
  'password_changed': <the user's stamp at sign-in>,
  'source': '203.0.113.7',         # for the audit log only
  'must_change_password': False,   # copied at sign-in, cleared by the own change
}
```

- `id` is `secrets.token_urlsafe(32)` (256 bits). It is the dictionary key and the cookie value, and
  it is never written to any log, event, audit entry or error (10.4). The audit log names a session by
  its user and source, never by id.
- Monotonic times decide expiry (a wall-clock jump must not extend a session); the ISO time is for
  the audit entry only.
- Bounds: at most 32 sessions per user and 512 in the process. Above either bound a sign-in evicts
  the oldest `last_seen` session of that user, then of the process, and audits `session.evicted`.

### 5.3 The cookie

| Attribute | Value | Why |
|---|---|---|
| Name | `clab_session` | Distinct from `clab_capture_owner` (capture_sessions.py:24). |
| Value | the session id | |
| `HttpOnly` | yes | No script reads it; UI.md's scripts learn the user from `GET /api/session`. |
| `SameSite` | `Strict` | No cross-site request carries it (A4). A navigation from another site to the manager also does not carry it; the user then lands on `/login`, whose script asks `GET /api/session` (a same-site request, which carries it) and redirects to `next` when it answers 200. |
| `Path` | `/` | The sockets under `/api/` and the pages both need it. |
| `Domain` | none | Host-only. The manager is opened by an address or by one name in `UI_ALLOWED_HOSTS`. |
| `Secure` | when `scheme(scope) == 'https'` (5.6) | A `Secure` cookie on plain HTTP would never come back; a non-`Secure` cookie on TLS would leak to a plain-HTTP request to the same host. |
| `Max-Age` | 43200 (the idle timeout) | The browser drops the cookie when the server would refuse it anyway. Renewed on every response that renews the session (5.4). |

Sign-out (`DELETE /api/session`) answers `Set-Cookie: clab_session=; Max-Age=0; ...` with the same
attributes and deletes the record. The capture cookie is also cleared on sign-out (11.2).

### 5.4 Timeouts and renewal

| Limit | Value | Why |
|---|---|---|
| Idle | 12 hours | A lab day with a lunch break; a laptop left open overnight is signed out by morning (A3). |
| Absolute | 7 days | Bounds a session that a tab keeps alive. A course runs a week; a cookie older than that is more likely stolen than in use. |

- **Sliding renewal.** A request that passes the gate sets `last_seen` to now and re-sends the cookie
  with a fresh `Max-Age`, **except** `GET /api/state` and `GET /api/session`. The 4 s poll must not keep an
  abandoned tab signed in forever; an open tab in which nobody acts expires after 12 h and the next
  poll's 401 sends it to `/login`. Every other request is an act of the person.
- To bound `Set-Cookie` churn, the cookie is re-sent only when `last_seen` moved by more than 60 s.
- Expiry is checked by the gate on every request: `now - last_seen > 43200` or
  `now - created > 604800` → the record is deleted, `session.expired` is audited (once, with the
  reason), and the request is refused as signed out.
- A sweep runs on every sign-in and at most once a minute from the gate, deleting expired records.
  There is no timer thread: the lifespan's thread list (main.py:71-88) stays as it is.

### 5.5 Sign out everywhere

The gate re-reads the user record on every request (one dictionary lookup under `store.lock` is
acceptable: `/api/state` already takes the lock, main.py:249). The session is deleted and the request
refused as signed out when any of these holds:

| Condition | Who causes it |
|---|---|
| The user no longer exists | `DELETE /api/users/{name}` |
| `disabled` is true | `PATCH /api/users/{name}` |
| `password_changed` in the record differs from the session's copy | `POST /api/users/{name}/password` (admin reset) or `POST /api/session/password` (own change) |

The routes also delete the sessions eagerly under the sessions lock, so the audit log carries one
`session.ended` entry per ended session with its reason (`user_disabled`, `user_deleted`,
`password_reset`, `password_changed`). The stamp check is the safety net for any path that forgets.

The own change (`POST /api/session/password`) ends every other session of the user and **rotates the
current session's id**: a new id is minted, the record is moved, the new cookie is sent. The role is
re-read from the record on every request, so a `PATCH` of the role takes effect on the next request
without ending the session.

### 5.6 The scheme rule (interface with EXPOSURE.md)

Nothing reads `X-Forwarded-*` (INVENTORY 6.6, last item) and uvicorn runs without `--proxy-headers`.
Three places today derive "own origin" from the request alone: the guard compares `Origin` with
`request.base_url` (main.py:123), the two sockets compare the Origin's scheme with `ws.url.scheme`
(node_services.py:573-574; capture_sessions.py:318-319), and the capture cookie sets `secure` from
`request.url.scheme` (capture_sessions.py:114). **If EXPOSURE.md terminates TLS in front of the
manager (a reverse proxy on the VM), all three break**: the browser's Origin says `https`, the
manager's scope says `http`, and every socket handshake and every `/api/` request with an Origin
header is refused.

The rule, binding for both designs:

1. One function `app/origin.py: scheme(scope)` answers `https` when `scope['scheme']` is `https` or
   `wss`, or when the environment variable `UI_TLS` is `1`; otherwise `http`. It reads no header.
2. The guard, both sockets, the capture cookie and the session cookie use it. The guard's
   comparison becomes `origin == f'{scheme(scope)}://{host}'` with the `Host` the request carries.
3. `UI_TLS=1` means exactly: *the browser reaches this manager over TLS that something on this VM
   terminates before the manager's socket*. EXPOSURE.md sets it in `compose.yml` and
   `deploy/compose.image.yml` (`test_release_consistency.py:88-99` requires equal key sets) when it
   chooses an edge proxy, and leaves it unset when uvicorn serves TLS itself (then `scope['scheme']`
   is already `https`). **Recommendation to EXPOSURE.md:** uvicorn's own `--ssl-certfile` /
   `--ssl-keyfile`, so that the scheme is true without configuration and `UI_TLS` is only a fallback.
4. The source address is `scope['client'][0]` in every case. Behind a proxy on the same VM every
   source would be `127.0.0.1`; EXPOSURE.md must either avoid a proxy or accept that the audit log
   then shows the proxy. `X-Forwarded-For` is not read; a later design that supports a remote proxy
   adds `--forwarded-allow-ips` with an explicit list and is reviewed then.

## 6. The gate

### 6.1 Where it lives

`SessionGate` is a pure ASGI class in `app/sessions.py`, shaped like `HostCheck` (allowed_hosts.py:79-99):
it handles `http` and `websocket` scopes and passes `lifespan` through. It is added in `create_app`
with `app.add_middleware(SessionGate, sessions=..., store=...)` **immediately before** the `HostCheck`
line (main.py:515). Starlette inserts each added middleware at the front of the list
(`Starlette.add_middleware` → `user_middleware.insert(0, ...)`), so the order outermost first becomes:

| Layer | Added at | Role |
|---|---|---|
| `HostCheck` | main.py:515 (last) | Host allowlist; stays outermost, as the invariant requires. |
| `SessionGate` | new line before main.py:515 | Session, setup mode, role default. |
| `diagnostics.requests` | diagnostics.py:113 via main.py:159 | `X-Request-ID`, the in-memory request list. |
| `guard` | main.py:119 | Origin, reset pending, content length, the `api.request` event, the security headers. |
| router | | |

A refusal by the gate is therefore not in the diagnostics request list (it is in the audit log) and
does not reach the guard. The gate's own responses carry the same fixed headers as `HostCheck`
(allowed_hosts.py:31-33) plus `Cache-Control: no-store`, because the guard's headers (main.py:145-155)
are not applied to a response the guard never sees (the same gap INVENTORY 6.1 notes for the guard's
own early returns; a follow-up may move those headers into one function used by all three).

### 6.2 What the gate does, in order

1. Read the single `Cookie` header, find `clab_session`. A repeated cookie name takes the first value.
2. Resolve: look the id up, check expiry (5.4), check the user record (5.5). The result is a session
   or nothing. Put `scope['state']['user'] = {'name', 'role', 'session_id'}` or `None`; `scope['state']`
   is the dictionary `Request.state` wraps, so routes read `request.state.user`.
3. Setup mode (9.3) is decided before anything else: while `state['users']` is empty, only the setup
   exemptions answer; everything else redirects or refuses as in 9.3.
4. If the path is exempt (6.3), pass through.
5. If no session: refuse (6.4).
6. If the session is restricted by `must_change_password` and the path is not in the restricted
   allowlist (6.3, last rows): refuse with 403 `{detail:{code:'password_change_required'}}` for
   `/api/`, redirect to `/login?change=1` for a page, close 1008 for a socket.
7. Pass through; on the response, renew (5.4).

The gate never raises; a malformed cookie is "no session".

### 6.3 The exemption list

Exact. Everything not in this table needs a session. The table is a constant `EXEMPT` in
`app/sessions.py` and a test walks it (13.1).

| Method | Path | Why |
|---|---|---|
| `GET` | `/login` | Serves `login.html`. The only page reachable without a session. |
| `GET` | `/setup` | Serves `setup.html` in setup mode or recovery (9); 404 otherwise. |
| `GET` | `/static/login.css`, `/static/login.js`, `/static/setup.js`, `/static/fabric-mark.svg` | What those two pages need. `login.css` is a self-contained stylesheet: `style.css` (2760 lines of every feature's class names, INVENTORY 3) is a product fingerprint and stays behind the gate. UI.md may copy the token block of `style.css:55-120` into `login.css`. |
| `POST` | `/api/session` | Sign in. |
| `GET` | `/api/session` | Answers 200 with the user or 401 cleanly; the pages use it to decide where to go. |
| `POST` | `/api/setup` | The first admin (9). |
| `GET` | `/api/health` | `{"ready": true}` and nothing else (6.7). |

What is **not** exempt, stated because a reader might expect it: `/` (redirects to `/login`),
`/static/*` including `style.css`, every manager script and the editor bundle, `/student-guide`
(main.py:505), `/vm-connection-guide` (main.py:501), `/api/logs`, every download, every socket.

Allowlist for a **restricted** session (`must_change_password`): the exempt rows above plus
`DELETE /api/session`, `POST /api/session/password`. UI.md's `/login?change=1` view shows the change
form.

### 6.4 The refusals

| Scope | Condition | Answer |
|---|---|---|
| `http`, path starts with `/api/` | no session | `401` JSON `{"detail":{"code":"signed_out"}}`, `WWW-Authenticate` is **not** sent (it would make browsers show a basic-auth prompt on a `fetch` in some configurations; the JSON code is the contract). |
| `http`, any other path | no session | `302` to `/login?next=<path+query, percent-encoded>` for `GET` and `HEAD`; `401` JSON for any other method. `next` is built from `scope['path']` and `scope['query_string']` only, never from a header, so it always starts with a single `/` (the open-redirect rule is checked again by `login.js`, 15). |
| `websocket` | no session | `websocket.close` code 1008 before accept, as `HostCheck` does (allowed_hosts.py:92-95). |
| any | setup mode | section 9.3 |

`POST /api/session` with a valid session already present signs in again: the old session is deleted,
a new one minted (a sign-in always rotates). `GET /api/session` with no session is a 401 like any
other `/api/` path; it is exempt only so that it reaches the route that answers that JSON with the
cookie-clearing header, not the gate's generic refusal.

### 6.5 WebSockets

The gate closes a socket without a session before the handler runs. Both handlers keep their
Origin checks (node_services.py:572-576; capture_sessions.py:317-321): the gate proves *who*, the
Origin check proves *which page* opened the socket. `SameSite=Strict` already keeps the cookie off a
cross-site socket handshake in every current browser, so the Origin check is a second fence, not a
redundant one: a browser that sends a cross-site cookie on a WebSocket handshake would still be refused.

The terminal handler receives the session through `ws.scope['state']['user']` and uses it for the
ticket binding (11.1).

### 6.6 CSRF: why no token

Three fences stop a cross-site request from acting as the user:

1. `SameSite=Strict`: the browser does not attach the cookie to any request whose initiator is
   another site, including top-level navigations and form posts.
2. The guard refuses an `/api/` request whose `Origin` differs from the own origin or whose
   `Sec-Fetch-Site` is `cross-site` (main.py:123-124). Every browser that sends cookies also sends
   `Origin` on a cross-site `POST`.
3. `HostCheck` refuses a `Host` outside DNS could control (DNS rebinding, allowed_hosts.py:1-21).

A CSRF token would add a fourth fence that defends against a browser that fails at both 1 and 2. None
of the supported browsers does. **When it would become needed:** if the cookie's `SameSite` were ever
relaxed to `Lax` (for example to let an external link open a lab directly), or if a route accepted a
mutation by `GET`, or if the Origin check were removed from the guard. The gate's test asserts the
cookie attributes and the guard's test keeps asserting the foreign-Origin 403 (test_app.py:58), so a
change to either fails a test.

### 6.7 The health route

`GET /api/health` answers `200 {"ready": true}` with `Cache-Control: no-store` and nothing else: no
version, no release, no capture status, no uptime. The installer's `check_manager`
(install-manager.py:118-120) and the health check's `ctx.http('/api/state')` and
`ctx.http('/api/capture/status')` (check_install.py:606) cannot read `/api/state` any more. **Interface
for EXPOSURE.md:** the version comes from the image label or from `docker exec <container> python -c
'import app; print(app.__version__)'` (the pattern of `STORAGE_PROBE`, check_install.py:299-331), and
every other manager fact the health check needs comes the same way, through `docker exec`, never
through an admin credential stored on the VM. A version-less health route is a weaker fingerprint
than today's unauthenticated `/api/state`, but it still says "this is a web service that answers
`/api/health`". The alternative, no route at all, would leave the installer polling a 302 from `/`,
which is a worse signal to an operator and the same signal to a scanner. EXPOSURE.md removes
uvicorn's `server:` header (`--no-server-header`) and the gate's own responses carry no product name.

## 7. Authorization

### 7.1 The rule

Every route that passes the gate is **operator** unless it declares **admin**. The gate enforces
"signed in"; the handful of admin routes declare `Depends(require_admin)` from `app/sessions.py`,
which reads `request.state.user` and raises 403 `{detail:{code:'admin_required'}}`. A middleware
path table was considered and rejected: the admin routes are few, live in three modules, and a
dependency sits next to the handler where a reviewer reads it. The declaration is kept honest by a
test that walks `app.routes` and asserts that every route is in a classification table (13.1): a route
missing from the table fails the test, so a new route must be classified when it is added.

### 7.2 The table

Routes as INVENTORY 6.2 lists them; "operator" is the default and only exceptions are listed in the
third column.

| Module | Routes | Admin-only |
|---|---|---|
| `main.py` | reset, state, remove lab, logs, inventory, node, profiles, schedule, jobs, both downloads | `POST /api/manager/reset` |
| `discovery.py` | discovery, host, refresh, import-preview, import, forget-exclusion, allow-import, sync, deployment, lab-definitions | `PUT /api/host` |
| `lab_operations.py` | every route | none |
| `device_diagnostics.py`, `impairments.py`, `catalog.py` | every route | none |
| `git_progress.py`, `git_place.py` | every route | none |
| `restore.py` | every route | none |
| `node_services.py` | health, ssh-check, ssh-check-all, terminal-ticket, WS terminal | none |
| `topology.py` | topology, superputty | none |
| `capture.py`, `capture_sessions.py` | every route and the socket | none |
| `telemetry_retirement.py`, `network_design.py`, `design_apply.py` | every route | none |
| `diagnostics.py` | debug, probe | `GET /api/debug`, `POST /api/debug/probe` |
| `sessions.py` (new) | session, session password, setup, health | none (the gate exempts what it must) |
| `accounts.py` routes (new) | users, user, user password, audit | all of them |

Decisions the prompt left open:

| Route | Decision | Why |
|---|---|---|
| `POST /api/lab-definitions`, `POST /api/inventory` (registering a lab) | operator | D2: every signed-in user sees and runs every lab; registering is how a lab appears. An operator who may deploy, destroy and restore a lab may register one. |
| `PUT /api/labs/{id}/git`, `/git/connect`, `/git/unlink`, `/git/destination` | operator | They bind a lab to a checkout the VM already registered; the VM-side registration (`deploy/setup-git.sh`, the engineer's account) is the admin act and happens outside the manager. Git runs as the registered owner, never as the UI user (host_git.py:1402; INVENTORY 6.6). |
| `POST /api/labs/{id}/profiles` (stores device passwords) | operator | A device login is lab data under D2. |
| `POST /api/manager/reset` | admin | Erases every lab, job and backup. |
| `PUT /api/host` | admin | D2 names the VM connection as admin-only. |
| `GET /api/debug`, `POST /api/debug/probe` | admin | Metadata about the manager, the VM address and the last 200 requests (diagnostics.py:110): an operator does not need it and A2 should not read it. |
| `GET /api/logs` | operator | Operational events of the labs the operator works on. Entries now carry `actor` (10.3); under shared labs that is intended. |

### 7.3 The new routes

| Route | Body | Answer | Role |
|---|---|---|---|
| `POST /api/session` | `{username, password}` | `200 {user:{name,role,must_change_password}, expires}` + cookie; `401 {detail:{code:'invalid_credentials'}}`; `429 {detail:{code:'throttled', retry_after}}` + `Retry-After` | exempt |
| `GET /api/session` | | `200 {user, expires}`; `401 {detail:{code:'signed_out'}}` | exempt |
| `DELETE /api/session` | `{}` | `200 {signed_out: true}` + clearing cookie | signed in |
| `POST /api/session/password` | `{current, password}` | `200 {changed: true}` + rotated cookie; `401 invalid_credentials` when `current` fails (throttled like a sign-in); `422 weak_password` | signed in (also restricted) |
| `GET /api/users` | | `200 {users:[public_user…]}` | admin |
| `POST /api/users` | `{name, role, password}` | `200 {user}`; `409 exists`; `422 weak_password` or `invalid_name`. The new record has `must_change_password: true`. | admin |
| `PATCH /api/users/{name}` | `{role?, disabled?}` | `200 {user}`; `409 last_admin` / `self_change`; `404` | admin |
| `DELETE /api/users/{name}` | `{}` | `200 {deleted: true}`; `409 last_admin` / `self_change`; `404` | admin |
| `POST /api/users/{name}/password` | `{password}` | `200 {user}` (ends the user's sessions, sets `must_change_password`); `422 weak_password` | admin |
| `GET /api/audit` | query `limit` (1..500, default 100), `offset`, `event`, `actor`, `outcome`, `since` (ISO) | `200 {entries:[…], total}` newest first | admin |
| `POST /api/setup` | `{code, username, password}` | `200 {user}` + cookie; `401 {detail:{code:'invalid_code'}}`; `404` when not in setup or recovery; `422`; `429` | exempt |
| `GET /api/health` | | `200 {ready: true}` | exempt |

Every body model is a Pydantic model with `extra='forbid'` (the house pattern, main.py:221-223).
Every mutating route needs a body because the guard requires a content length (main.py:127-131);
that is why `DELETE` routes take `{}`.

## 8. Sign-in throttling

### 8.1 Counters

Two in-memory tables in `app/sessions.py`, under the sessions lock, process-local:

| Table | Key | Free failures | Then | Cap |
|---|---|---|---|---|
| by source | `scope['client'][0]` | 5 in a row | 30 s, doubling per further failure | 15 min |
| by user name | the submitted name, lowercased, whether or not it exists | 5 in a row | 30 s fixed, not doubling | 30 s |

A failure increments both. A success clears both entries for that source and name. An entry whose
last failure is older than 1 h is pruned at the next attempt. Each table holds at most 10 000 entries;
above that the oldest entry is evicted, so a flood of spoofed sources cannot grow memory.

### 8.2 The answer

While either counter is in its delay, `POST /api/session` answers `429 {detail:{code:'throttled',
retry_after: <seconds, integer, the larger of the two>}}` with a `Retry-After` header, **without running
the hash**. The delay counts from the last failure. A throttled attempt is audited as
`signin.throttled` (10.2) and does not increment the counters (otherwise a throttled attacker would
extend their own delay indefinitely, and so would the admin they are impersonating).

### 8.3 Never permanent, and the admin always gets in

- The per-source delay caps at 15 min; the per-name delay is a fixed 30 s. An attacker who sprays
  the admin's name from many addresses can slow the admin to one attempt per 30 s, never lock them
  out. The per-source cap stops a single address regardless of how many names it tries.
- The counters reset when the process restarts. This is acceptable: a restart is an operator action
  on the VM, and an attacker cannot cause one from the network (nothing unauthenticated reaches a
  code path that exits the process). If a restart ever became attacker-triggerable, the counters would
  need persistence; the audit log would show the pattern either way.
- The CLI recovery path (9.5) does not use the sign-in route and is not throttled by it.

### 8.4 No enumeration, constant time

- The sign-in route runs exactly one scrypt per non-throttled attempt: the user's hash when the user
  exists and is enabled, `DUMMY_HASH` otherwise (4.2). The branch that decides which hash is a
  dictionary lookup, which is not a measurable difference beside a 50 ms verify.
- The answer for an unknown user, a wrong password and a disabled user is the same 401
  `invalid_credentials`. The per-name throttle applies to names that do not exist, so a 429 does not
  reveal existence either.
- The setup route answers the same way for a wrong code (401 `invalid_code`), compares the code with
  `hmac.compare_digest` and is throttled by source with the same table.

## 9. First-run bootstrap and recovery

### 9.1 Setup mode

The manager is in setup mode while `state['users']` is empty. This is the state of a new install and
of an upgraded install on its first start (12.1).

### 9.2 The setup code

- At startup in setup mode the manager generates a code: 24 characters from the alphabet
  `abcdefghjkmnpqrstuvwxyz23456789` (31 symbols, no `0/o/1/l/i`, about 119 bits), shown as four
  groups of six (`xxxxxx-xxxxxx-xxxxxx-xxxxxx`), by `secrets.choice`.
- It writes the file `<DATA_DIR>/setup-code` (mode 0600 through `Store.atomic`, store.py:34-44; owner
  is the container user `worker`, uid 10001, Dockerfile:12) with two lines: `mode=setup` and
  `code=<code>`. It prints to the container log: `Setup required: open https://<address>/setup and
  enter the setup code from <DATA_DIR>/setup-code (also printed below).` followed by the code.
- The file is the source of truth. `GET /setup` and `POST /api/setup` read it on each request (a
  `stat` and a small read; refuse a symlink and a file whose mode is wider than 0600, as the capture
  `.env` pattern does, `deploy/setup_capture.py read_env`). No code is kept in memory, so the recovery
  command (9.5) can replace the file from another process.
- The code is valid until used. A restart in setup mode regenerates it (the old code is gone with the
  file; a stale code in an operator's notes stops working, which is the point).
- The bind mount makes the file readable on the VM as root or as uid 10001 under
  `/srv/containerlab-node-manager/data/setup-code`. **Interface for EXPOSURE.md:** the installer
  reads it there (or with `docker exec <container> cat /data/setup-code`) and prints it to the
  operator's terminal with the setup URL; the health check reports `Setup not completed` while the
  file exists with `mode=setup`.

### 9.3 What answers in setup mode

| Request | Answer |
|---|---|
| `GET /setup`, its three assets, `POST /api/setup`, `GET /api/health` | served |
| `GET /login` | `302 /setup` |
| any other page | `302 /setup` |
| any other `/api/` path, including `POST /api/session` | `503 {detail:{code:'setup_required'}}` |
| any socket | close 1008 |

`POST /api/setup {code, username, password}`: compare the code (`hmac.compare_digest`), apply the name
rule and the password policy, create the first record with `role: admin`, `created_by: 'setup'`,
`must_change_password: false` (the person chose it), save the state, **delete the file**, audit `setup`,
mint a session and answer like a sign-in. The three steps "save, delete, audit" run under
`store.lock`; if the save fails the file stays and the route answers 500 (the house pattern,
main.py:165-172).

### 9.4 After setup

`GET /setup` answers 404 and `POST /api/setup` answers 404 whenever the file is absent, so the page
is not a scanner signal once the first admin exists. The only way to make them answer again is the
recovery command.

### 9.5 Recovery of a lost admin password

**`deploy/manager-recover-admin.sh`** (EXPOSURE.md owns the script's host side: it must be root on the
VM, find the container as `recreate-manager.sh` does, and be added to CI's `bash -n` loop). It runs
one command inside the container:

```
docker exec <container> python -m app.recover
```

`app/recover.py` (this design's) does, as the container user:

1. Refuse when `<DATA_DIR>/setup-code` already exists with `mode=setup` (the manager is in setup mode;
   nothing to recover; print the existing instruction).
2. Generate a code as 9.2, write the file with `mode=recover` and `code=<code>`, print the code and
   `Open https://<address>/setup within 15 minutes and create one new administrator.`
3. Exit 0. It never touches `state.enc`, never deletes or changes a user, never resets users.

While a `mode=recover` file exists and is younger than 15 minutes (the file's mtime; the manager
deletes an older one at the next `/setup` request and audits `recover.expired`), `GET /setup` serves
the page and `POST /api/setup` accepts the code and creates **one** admin with `created_by: 'recover'`,
leaving every existing user as it was (including the admin whose password was lost: the new admin
resets it or deletes the record through the Users page). The file is deleted on success. The setup
page in recovery mode shows "Recovery: create one new administrator" so an operator who finds it open
understands what it is.

Why this shape: nothing opens a network door that was closed (the only new reachable path needs a
119-bit code that exists only in a 0600 file on the VM for 15 minutes), the person who can run it is
already root on the VM, and no user record is destroyed by a recovery.

## 10. The audit log

### 10.1 The file

`<DATA_DIR>/audit.jsonl`, written by a new `Store.audit(event, *, actor, source, outcome, target='',
detail='')`, with the same creation mode (0600) and the same rotation (5 MiB × 4) as `Store.event`
(store.py:122-130). It is separate from `events.jsonl` because `events.jsonl` is served to every
operator by `GET /api/logs` (main.py:304-306) and is moved aside by *Start fresh* (store.py:102);
the audit log is admin-only and survives a reset (3.3). The write failure path is the same warning
once, then silence (store.py:132-137), with its own flag `audit_error`.

Entry: `{time, event, actor, source, outcome, target, detail}`. `detail` is a short string of
controlled vocabulary (a reason code or a count), never user input longer than 200 characters, never
a password, a code, a session id or a hash (10.4).

### 10.2 The events

| `event` | `actor` | `target` | `outcome` / `detail` |
|---|---|---|---|
| `setup` | the new admin | | `ok`; `detail: 'setup'` or `'recover'` |
| `setup.failed` | `-` | | `invalid_code` / `weak_password` / `invalid_name` |
| `recover.requested`, `recover.expired` | `-` | | |
| `signin` | the user | | `ok` |
| `signin.failed` | the submitted name (after the name rule; an invalid name is logged as `invalid`) | | `invalid_credentials` / `disabled` / `bad_record` |
| `signin.throttled` | the submitted name | | `retry_after=<n>` |
| `signout` | the user | | |
| `session.expired` | the user | | `idle` / `absolute` |
| `session.ended` | the user | | `user_disabled` / `user_deleted` / `password_reset` / `password_changed` / `evicted` |
| `password.changed` | the user | | own change |
| `user.created`, `user.deleted`, `user.disabled`, `user.enabled`, `user.role`, `user.password_reset` | the admin | the user name | `role=<new>` for `user.role` |
| `forbidden` | the user | the route template | `admin_required` (every 403 from `require_admin`) |
| `manager.reset` | the admin | | |

Not audited here: ordinary mutating requests. They are in `events.jsonl` with their actor (10.3).

### 10.3 The actor on operational events

`Store.event()` gains a keyword `actor=''` written into every `events.jsonl` entry; `Store.events()`
gains an `actor` filter. The guard's `api.request` event (main.py:143-144) passes
`actor=request.state.user['name']` and `source=request.client.host`; the event's message is
unchanged. Other callers of `Store.event` (terminal open and close, downloads, jobs) pass the actor
where a request is in hand; a background thread has none and writes `''`. This keeps one
operational log with one reader (`GET /api/logs`) and puts "who" next to "what" where operators
already look. Security events stay in the audit log because they must survive a reset and must not
be readable by operators.

### 10.4 What is never logged

A password (submitted, stored or dummy), a setup code, a session id, a cookie header, a hash string,
an `Authorization` header, the body of any sign-in or setup request. The tests grep both log files
after every sign-in, setup and failure path for the password, the code and the cookie value (13.3).

## 11. Tickets and the capture cookie

### 11.1 The terminal ticket is bound to the session

Today the ticket tuple is `(expiry, lab_id, name, protocol)` (node_services.py:567) and the socket
pops it by key alone (node_services.py:588-591). The design adds the minting session's id as a fifth
element: `(expiry, lab_id, name, protocol, session_id)`, taken from `request.state.user['session_id']`.
On consume the handler compares it with `ws.scope['state']['user']['session_id']` using
`hmac.compare_digest`; a mismatch closes 1008 like an unknown ticket. A leaked ticket is then useless
from another browser, and a ticket outlives neither its 30 s nor the session that minted it: the
session routes clear the tickets of a session they end (the dictionary is small, 32 entries at most,
node_services.py:564). `services.tickets.clear()` on reset (main.py:241) and on `close()`
(node_services.py:219) are unchanged.

### 11.2 The capture cookie stays

`clab_capture_owner` (capture_sessions.py:107-115) isolates desktop sessions per browser and is kept
as it is. Because the gate sits in front of every capture route and the socket, the cookie is now only
ever set for a signed-in user. Sign-out clears it in the same response as `clab_session`. Its `secure`
flag follows the scheme rule (5.6). It is not tied to the user: a second sign-in in the same browser
keeps the same desktop sessions, which is the behaviour of a browser, not of an account.

## 12. Compatibility and migration

### 12.1 An existing install

An upgraded manager has a `state.enc` without `users` and enters setup mode on its first start (9.1).
From that moment nothing but `/setup` answers: the operator is locked out until the first admin is
created. This is deliberate (PROMPT D3 point 2: no setup page left open, no default account). The
manager's behaviour is 9.2 and 9.3; the operator's experience (the installer prints the code, the
health check says `Setup not completed`, `start-manager.sh:120` stops saying "opens directly without
a login") is EXPOSURE.md's.

### 12.2 `ui.token`

Removed from the read path: store.py:22-23 (`self.token`) goes, runner.py:420 becomes
`secrets_to_hide=[]`, test_app.py:47 and the `headers=self.auth` of test_app.py:53 go. The file name
stays in the two reset lists (store.py:81, 102) so that an old install's file is still moved aside,
and `test_manager_reset.py:29` keeps its assertion. The legacy header is not read by anything today
and a Bearer header will not be read after this design either: there is one credential, the cookie.

### 12.3 The reset journal, old pages, stored data

- A `.reset-pending` journal prepared by an older release applies without `users` (3.3).
- Every HTML page except `login.html` and `setup.html` is behind the gate; nothing in them changes
  for this design (UI.md changes their scripts for 401 handling).
- No stored lab, job, binding or snapshot shape changes.

## 13. Tests

### 13.1 New files

| File | What it proves |
|---|---|
| `tests/test_session.py` | The gate on every route: a walk of `app.routes` (and the two sockets) without a cookie gets 401, 302 or 1008 by the rules of 6.4, except the exempt rows of 6.3; the classification table of 7.1 names every route (a route absent from the table fails). Cookie attributes exactly as 5.3, under `http` and with `UI_TLS=1`. Idle and absolute expiry with a patched monotonic clock; renewal excludes `GET /api/state`. Sign-out everywhere: disable, delete, admin reset, own change (other sessions end, the current id rotates). Throttling: the fifth failure is free, the sixth is 429 with `retry_after`, doubling, the 15 min cap, the per-name 30 s cap, success clears. Constant work: a wrong user and a wrong password both call the verify function exactly once (patched). Session fixation: the id after sign-in differs from any cookie sent with the request. `/api/state` contains neither `users` nor `scrypt$`. |
| `tests/test_setup.py` | Setup mode answers of 9.3; the code file's mode and content; `POST /api/setup` creates the admin, deletes the file, signs in; a second setup is 404; `app.recover` writes a `mode=recover` file, one admin is created, existing users untouched, a 16-minute-old file is refused and deleted; `Store.reset` keeps `users` and `audit.jsonl`. |
| `tests/test_users.py` | Name rule, role values, `extra='forbid'`, uniqueness, last-admin and self-change refusals, `public_user` fields and nothing more, role change effective on the next request. |
| `tests/test_audit.py` | Every event of 10.2 is written with its fields; rotation; `GET /api/audit` paging and filters; operators get 403 and that 403 is itself audited; the actor on `api.request` in `events.jsonl`. |
| `tests/test_password.py` | The hash string format and parser (every malformed case), round trip, `compare_digest` use (patched), rehash on sign-in when parameters differ without moving `password_changed`, `DUMMY_HASH` parses, the policy's reason codes, the deny-list, NFKC length, the 500 ms bound of one verify with the shipped parameters and `maxmem`. |
| `tests/test_ticket_binding.py` (or inside `test_nodes.py`) | A ticket minted by session A is refused on a socket with session B; a ticket survives neither its 30 s nor the end of its session. |
| `tests/test_login_ui.js`, `tests/test_setup_ui.js` | UI.md's (the `next` rule of section 15 is asserted there). |

New Python and Node test files go to the lead for the CI lists (CLAUDE.md "CI runs an explicit list").

### 13.2 The fixture for existing tests

**Decision: one helper that signs in through the real routes, and a `TestClient` subclass; no test-only
argument to `create_app`.** A bypass in `create_app` would be a code path on the shipped manager that
exists only to skip the gate; a reviewer would have to prove it unreachable from the network on every
release. The real routes are cheap enough: one scrypt per test case (about 50 ms), and the helper may
lower the parameters through a module constant that the test process sets before `create_app`
(`accounts.PARAMS`), which is the same mechanism the rehash test uses.

`tests/session_fixture.py`:

```python
class SignedInClient(TestClient):
    """A TestClient that completed setup as 'tester' (admin by default) and keeps the cookie."""
    def __init__(self, app, role='admin', name='tester', password='correct horse battery staple'):
        super().__init__(app)
        complete_setup(self, app, name, password)     # reads <data>/setup-code, POST /api/setup
        if role != 'admin': ...                        # create an operator with the admin, then sign in as it
```

`complete_setup` reads the code from `app.state.store.root/'setup-code'` and posts `/api/setup`; the
`httpx` cookie jar in `TestClient` keeps the cookie for every later request, and `websocket_connect`
goes through `super().request` (starlette 1.x `TestClient.websocket_connect`), so the sockets receive
it too. `HostCheckTests` (test_app.py:317-399) send explicit `Host` headers; the cookie is host-only in
the jar for `testserver`, so those tests pass `cookies=` explicitly or the subclass sets the jar
without a domain. This is the one place that needs care; the fixture file documents it.

Counting the change on this checkout:

```
grep -l TestClient clab-backup-ui/tests/*.py | wc -l      → 23 files
grep -n 'TestClient(' clab-backup-ui/tests/*.py | wc -l   → 52 construction sites
grep -l websocket_connect clab-backup-ui/tests/*.py        → test_app.py, test_capture_proxy.py, test_capture_sessions.py, test_nodes.py
```

Twenty-three files change by replacing `TestClient(self.app)` with `SignedInClient(self.app)` (a
`mechanical-editor` task once the fixture exists). The four socket tests additionally assert the 1008
without a session. Tests that hit `/api/manager/reset`, `/api/host` or `/api/debug` need the default
admin, which the subclass gives. `test_app.py:57-58` keeps its foreign-Origin 403: the gate passes a
signed-in request to the guard, which refuses it as before (6.1).

### 13.3 Log hygiene

A helper `assert_not_logged(store, *secrets)` reads `events.jsonl*` and `audit.jsonl*` and asserts that
no secret appears; `test_session.py`, `test_setup.py` and `test_password.py` call it after every
sign-in, setup, failure and throttle path with the password, the code and the cookie value.

### 13.4 Environment

The scrypt timing test asserts under 500 ms with `maxmem=64 MiB`, so it passes on the image's
`python:3.12-slim` and in CI; it also asserts that the shipped `maxmem` is passed, because the
default refuses the shipped parameters (4.1).

## 14. The CLAUDE.md invariant

Replacement for the bullet that begins "There is no login:" under "VM boundary and data" (the lead
applies it at the release step):

> - Sign-in is required for everything but `/login`, `/setup`, their three assets, `POST`/`GET /api/session`,
>   `POST /api/setup` and `GET /api/health` (`EXEMPT` in `app/sessions.py`; `test_session.py` walks every
>   route). `SessionGate` resolves the `clab_session` cookie (`HttpOnly`, `SameSite=Strict`, `Secure` under
>   TLS, idle 12 h, absolute 7 d, in memory only) for HTTP and WebSocket scopes and sits directly inside
>   `allowed_hosts.HostCheck`, which stays the outermost ASGI layer (added last in `create_app`). Behind
>   it `/api/` keeps the same-origin `guard` in `main.py` (a mutating request needs a body; content-length
>   0 is refused, so pages post `{}`); every WebSocket still checks `Origin` itself, and a terminal ticket is
>   single-use and bound to the session that minted it. Admin-only routes declare `Depends(require_admin)`;
>   every other route is operator. Passwords are `hashlib.scrypt` strings (`scrypt$n$r$p$salt$hash`); a
>   sign-in always runs one verify (a dummy for an unknown name) and is throttled per source and per name,
>   never permanently. Users survive *Start fresh*; the first admin is created once through a setup code
>   from `<DATA_DIR>/setup-code`, and `deploy/manager-recover-admin.sh` is the only way to reopen that page.
>   Security events go to `audit.jsonl` (admin-only, survives a reset); no log ever holds a password, a
>   code, a session id or a hash. "Own origin" is `origin.scheme(scope)` (the scope, or `UI_TLS=1`),
>   never a forwarded header.

## 15. The `next` parameter

The gate builds `next` from the request's own path and query (6.4). `login.js` (UI.md) accepts `next`
only when it matches `^/(?![/\\])[^\s]*$` (one leading slash, not `//` or `/\`, no whitespace) and
does not start with `/login` or `/setup`; otherwise it goes to `/`. The server never redirects to
`next` itself (the sign-in answer is JSON; the page navigates), so an open redirect would have to pass
the page's rule. `test_login_ui.js` asserts the rule with `//evil.example`, `/\evil.example`,
`https://evil.example`, `javascript:` and `/login?next=/login`.

## 16. Build slices and file ownership

| Slice | Files | Owner (routing) |
|---|---|---|
| Accounts: the record, the hash, the policy, `public_user`, the users routes, `recover.py` | `app/accounts.py`, `app/recover.py` | `clab-fable-specialist` or `clab-opus-specialist` (privileged: the Store and the guard are touched) |
| Sessions: the gate, the sessions table, throttling, the session and setup routes, `origin.py` | `app/sessions.py`, `app/origin.py`, `app/main.py` (the `add_middleware` line, the guard's Origin comparison and actor, the banner), `app/allowed_hosts.py:3` docstring | same |
| Store: `users` in reset, `audit()`, `actor` on `event()` | `app/store.py` | same; `risk-reviewer` on the diff |
| Ticket binding, socket scheme rule | `app/node_services.py`, `app/capture_sessions.py` | `clab-backend-engineer` with the lines specified here |
| The fixture and the 23 test files, the new test files | `tests/session_fixture.py`, `tests/test_session.py`, `test_setup.py`, `test_users.py`, `test_audit.py`, `test_password.py` | `clab-test-engineer`; the 52 replacements by `mechanical-editor` |
| Pages, scripts, 401 handling | `app/static/login.html`, `login.css`, `login.js`, `setup.html`, `setup.js`, the Users and Audit views, every script's 401 path | UI.md's slices |
| `UI_TLS`, `/api/health` in the installer and health check, `manager-recover-admin.sh`, `start-manager.sh:120`, the documents of INVENTORY 4 | `deploy/*`, `docs/*.md` | EXPOSURE.md's slices |
| `verify-release.py:40-41` (the two new pages), the CI lists, `CLAUDE.md` | | the lead |

Names shared between slices, fixed here: `app.state.sessions` (the `Sessions` object with
`create(user, source)`, `resolve(id)`, `end(id, reason)`, `end_user(name, reason)`, `throttle`), `app.state.accounts`
(`verify(name, password)`, `set_password`, `check_password`, `public_user`), `request.state.user`,
`require_admin`, `EXEMPT`, `origin.scheme(scope)`, `Store.audit`, the cookie name `clab_session`, the
file name `setup-code`, the error codes of 7.3.

## 17. Contract as delivered to UI.md

UI.md was briefed with the contract in the first column. The second column is the final shape; a row
marked **changed** or **added** differs from the brief.

| Briefed | Final | Status |
|---|---|---|
| `GET /login` serves `login.html`, the only page without a session | As briefed. Its assets are `/static/login.css`, `/static/login.js`, `/static/fabric-mark.svg` only; `style.css` is behind the gate (6.3). | **changed**: no `style.css` |
| | `GET /setup` serves `setup.html` with `/static/setup.js` and `login.css`; 404 unless setup or recovery mode. In setup mode every page redirects here, `/login` too. There is no `GET /api/setup`: the page is a static file, calls `POST /api/setup` only, and shows the recovery sentence when its own address carries `?recover=1` (the URL the recovery command prints, 9.5). | **added** |
| `POST /api/session {username,password}` → 200 `{user:{name,role}}` + cookie; 401 generic; 429 with `retry_after` | 200 `{user:{name,role,must_change_password}, expires}`; 401 `{detail:{code:'invalid_credentials'}}`; 429 `{detail:{code:'throttled', retry_after}}` + `Retry-After`; 503 `{detail:{code:'setup_required'}}` in setup mode | **changed**: `must_change_password`, `expires`, the 503 |
| `DELETE /api/session` body `{}` | As briefed; the response also clears `clab_capture_owner` | unchanged |
| `GET /api/session` → user or 401 | 200 `{user:{name,role,must_change_password}, expires}` or 401 `{detail:{code:'signed_out'}}` | **changed**: fields |
| Every other page and `/api/` route → 401 `{detail:{code:'signed_out'}}`; pages redirect to `/login?next=` | As briefed, for `GET`/`HEAD` on pages; other methods on pages get the 401 JSON. A restricted session (`must_change_password`) gets 403 `{detail:{code:'password_change_required'}}` on `/api/` and `302 /login?change=1` on pages; only `GET /api/session`, `POST /api/session/password` and `DELETE /api/session` answer it | **added**: the restricted state |
| WebSockets refuse without a session | Close 1008 before accept | unchanged |
| Admin routes `GET/POST /api/users`, `PATCH/DELETE /api/users/{name}`, `POST /api/users/{name}/password` | As briefed with the bodies and codes of 7.3: `exists`, `last_admin`, `self_change`, `weak_password` (with `reasons`), `invalid_name`; a new user starts with `must_change_password: true`; `public_user` fields of 3.4 including `sessions` | **changed**: codes and fields made exact |
| `POST /api/session/password` (own change) | `{current, password}`; other sessions end; the cookie is rotated in the response | **changed**: `current` required |
| `GET /api/audit` (admin) | `?limit&offset&event&actor&outcome&since` → `{entries, total}`, newest first; entry fields of 10.1; operators get 403 `{detail:{code:'admin_required'}}` | **changed**: made exact |
| First-run bootstrap with a one-time setup code | `POST /api/setup {code, username, password}` → like a sign-in; 401 `{detail:{code:'invalid_code'}}`; 404 when unavailable; 429 | **changed**: made exact |
| | `GET /api/health` → `{ready:true}`, no session; pages never call it | **added** (for EXPOSURE.md) |
| | The `next` rule of section 15 is `login.js`'s to enforce | **added** |
| | `/api/logs` entries gain `actor`; the Audit page is a different log (`audit.jsonl`) | **added** |

On the `/setup` row: the page is a static file and cannot know the mode. Final ruling: `setup.html`
has one heading, "Create an administrator"; its script reads `?recover=1` from its own address (set by
the recovery command's printed URL, 9.5) to show the recovery sentence; the server's 404 on
`GET /setup` is rendered by the browser as "not found", which is correct outside the two modes.

## 18. Decisions that differ from the prompt

| Prompt | Decision | Why |
|---|---|---|
| Sessions "stored in memory with the record's hash persisted?" | In memory only, nothing persisted | 5.1: no session secret on disk, no write amplification from the 4 s poll, one process by compose. |
| `Secure` "when the request scheme is https or the env `UI_TLS=1`" | Same, but through one function `origin.scheme(scope)` that the guard and both sockets must also use | 5.6: a TLS edge in front of the manager breaks the guard and both sockets today, not only the cookie. |
| Login assets "`/static/style.css`, `/static/login.js`, `/static/login.css`?" | `login.css`, `login.js`, `setup.js`, the favicon; not `style.css` | 6.3: `style.css` names every feature of the product. |
| Health route "a version-less `{ready:true}`" | `{ready:true}`, and the installer's version check moves to `docker exec` | 6.7. |
| "extend the guard's `api.request` event with `actor` and `source`? or keep events.jsonl as is" | Extend `Store.event` with `actor`; security events in a separate `audit.jsonl` | 10.3: one operational log for operators, one security log for admins, the second survives a reset. |
| Per-name throttling with the same exponential schedule | Per-source exponential to 15 min; per-name fixed 30 s | 8.3: the exponential per-name schedule would let a botnet lock the admin out for 15 min at a time. |
| `GET /api/setup` implied by "the login page needs to know whether to show setup" | No such route; the gate redirects to `/setup` in setup mode and `/setup` is 404 otherwise | 9.3, 9.4: one fewer unauthenticated route. |
| Recovery "writes a new setup code allowing the creation of ONE more admin" | Same, with a 15 min validity and a `mode=recover` file the manager reads per request | 9.5: no in-memory code, so a second process can create it. |
| "`public_*` keeps the hash out of `/api/state`" | No stripping needed: `users` is a top-level key `/api/state` never copies; a test pins it | 3.4. |
| `must_change_password` named but not specified | A restricted session that can only change its password or sign out | 6.2 step 6, 17. |
| `git_binding` owner, path, push_url "strip for operators?" | Not stripped | 19: shared labs (D2) make operators the people who place a lab in a folder; `save-drawers.js:418-419` shows these fields to them; the VM account name is not an asset the threat model protects from a signed-in user. |
| Sliding renewal on every request | Every request except `GET /api/state` and `GET /api/session` | 5.4: the poll would make the idle timeout meaningless. |

## 19. Rulings that bind the build

1. `HostCheck` stays the outermost layer; `SessionGate` is added on the line before it and nowhere
   else (6.1).
2. The gate is a pure ASGI class, not `@app.middleware('http')`: it must see WebSocket scopes.
3. `EXEMPT` is one constant and the only place that names an unauthenticated path. A route added
   without a classification fails `test_session.py`.
4. The verify function is the only caller of `hashlib.scrypt` for passwords; it always passes
   `maxmem`; it runs under the semaphore; `DUMMY_HASH` is verified for every name that cannot sign in.
5. No log, event, audit entry, exception message or HTTP response contains a password, a code, a
   session id, a cookie value or a hash string. `assert_not_logged` runs in every new test file.
6. The session table and the throttle tables are bounded (5.2, 8.1); the sweep has no thread.
7. `Store.reset` copies `users`; `audit.jsonl` is never moved, deleted or truncated by the manager
   except by its own rotation.
8. `POST /api/session` always mints a new id; `POST /api/session/password` rotates it; the record's
   `role` is read on every request.
9. The ticket tuple carries the session id and the socket compares it; the Origin checks of both
   sockets stay.
10. `scope['client'][0]` is the source everywhere; no `X-Forwarded-*` header is read by any new code.
11. The gate's refusals carry the fixed security headers of `HostCheck` plus `Cache-Control: no-store`.
12. `create_app` gains no test-only argument. Tests sign in through `/api/setup` and `/api/session`.
13. `runner.job_environment` (runner.py:152) keeps passing `os.environ` to Ansible; therefore
    **no secret of this design is placed in the environment**: the setup code is a file, sessions are
    memory, `UI_TLS` is a flag. A review of EXPOSURE.md's environment keys applies the same rule.
14. The guard's `api.request` event and every security event name the actor by user name, never by
    session id.
15. `/setup` and `POST /api/setup` answer 404 whenever `<DATA_DIR>/setup-code` is absent; the file is
    deleted in the same locked block that saves the new admin.

## 20. What a reviewer should attack

1. **Open redirect in `next`.** The gate builds it from the scope only; `login.js` enforces section 15.
   Try `//`, `/\`, a scheme, a `%2F%2F` encoding, a `next` that points to `/login` (a loop), and a
   `next` with a fragment.
2. **Session fixation.** There is no pre-authentication session, so there is no id to fix; sign-in
   always mints. Check that a `Cookie: clab_session=<attacker id>` on the sign-in request is ignored
   and that the response's id differs (13.1 asserts it).
3. **The dummy-verify timing.** One scrypt either way; the dictionary lookup and the `disabled` branch
   are the only differences. Check that the disabled path also runs the dummy, not the user's real hash
   (a real hash with a wrong password costs the same, but a real hash with the *right* password of a
   disabled user must not answer differently either: the design verifies the dummy for a disabled user,
   so the result is discarded whatever the password).
4. **The setup code on the bind mount.** `/srv/containerlab-node-manager/data/setup-code` is 0600 owned
   by uid 10001 on the VM; root and the container user read it; the `docker` group reads it through
   `docker exec` or `docker logs` (the code is printed to the container log). The docker group is root
   on a VM in any case. Check that the file is deleted on success and that a 15 min old `mode=recover`
   file is refused.
5. **The 4 s poll after expiry.** `refresh()` swallows poll errors (app.js:576); UI.md's 401 handling
   must redirect. Until it does, an expired tab polls a 401 every 4 s: harmless on the server (no hash,
   no audit entry per poll: the gate audits `session.expired` once and then sees no session).
6. **The sockets' Origin check now redundant?** No (6.5). Check that removing it would still fail a
   test (`test_app.py:348-371` keep the Origin assertions).
7. **The `git_binding` fields in `/api/state`** (`owner`, `path`, `push_url`, host_git.py:154, 421; main.py:174
   copies `git_binding`): shown to operators by design (18). Attack the premise: is a VM account name
   plus a checkout path useful to A2 with an operator session? They already have a terminal on every
   device and the Git save surface.
8. **`runner.py:152` passes the environment to Ansible.** Ruling 13: nothing of this design is in the
   environment except `UI_TLS`. Check EXPOSURE.md's keys against the same rule (a TLS key path is
   fine; a TLS key is not).
9. **Memory growth.** 512 sessions × a small dict; two throttle tables × 10 000 entries; the ticket
   dictionary unchanged at 32. Attack the eviction order: can an attacker evict a legitimate admin's
   session by flooding sign-ins? Only with valid credentials (a session needs a success); failures
   never create sessions. Can they evict throttle entries to escape their own delay? The eviction is
   oldest-first by last failure; the attacker's own entry is the newest. Check both.
10. **The health route as a fingerprint.** `{ready:true}` with no server header. Compare with what a
    302 from `/` to `/login` already reveals (a sign-in page with the product's name in its title, by
    UI.md): the page is the larger fingerprint and is unavoidable. Decide whether the title should be
    generic ("Sign in") rather than the product name; this design recommends the product name stays off
    the sign-in page's `<title>` and heading until after sign-in, and leaves the call to UI.md.
11. **`SameSite=Strict` and the external link.** A student who follows a link from a course page lands on
    `/login`, which immediately redirects to `next` because `GET /api/session` is same-site. Check that
    this does not loop and that a signed-out student sees the form.
12. **Setup mode on an upgrade.** Between the upgrade's restart and the operator's setup, the manager
    answers nothing but `/setup`, which needs the code from the VM. Attack: is there any way for A1 to
    reach `POST /api/setup` usefully? 119 bits, throttled per source, no enumeration. Attack the
    file-read path for a symlink or a mode widening on the bind mount.
13. **Two admins editing users at once.** Every users route reads and writes under `store.lock`; the
    last-admin rule is evaluated inside the same block. Check `PATCH` on two admins each demoting the
    other: the second one is refused.
14. **The restricted session.** A user with `must_change_password` holds a session that can only change
    the password. Check that the gate's allowlist for it cannot be widened by a path trick
    (`/api/session/password/../../state`, `/API/state`, a trailing slash) : the gate matches on the
    normalized `scope['path']` and exact strings, and the test tries those spellings.
15. **The audit log's own integrity.** 0600, append-only by convention, rotated by size. An admin with
    a session reads it; nobody writes to it through HTTP. Attack whether a 4000-character `detail`
    could be injected through a user name (the name rule caps it at 32 and the alphabet excludes
    everything but `[a-z0-9._-]`).
