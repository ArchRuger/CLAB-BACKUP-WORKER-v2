# Sign-on: accounts, sessions, authorization and auditing

The binding design of the account, session, authorization and audit parts of the sign-on campaign.
The task is [PROMPT.md](PROMPT.md) (D1 local accounts, D2 Admin + Operator with shared labs, D3 the
threat model); the facts it fits are [INVENTORY.md](INVENTORY.md). Base: `main` at 1.31.8
(`fac28de`); every file:line below is to that commit. Written 2026-11-01, before code.

Amended with the lead's rulings of RECONCILIATION.md (2026-11-01); where this file and RECONCILIATION differ, RECONCILIATION's ruling has been applied here.

Amended with the answers of REVIEW.md (2026-11-01).

| Part | Where |
|---|---|
| Threat model, accounts, hashing, sessions, the gate, roles, throttling, bootstrap, audit, tickets, migration, tests | this file |
| TLS, the firewall, the installer, the health check, the recovery script's host side | [EXPOSURE.md](EXPOSURE.md) |
| The sign-in and setup pages, 401 handling in every script, the account menu, the Users and Audit pages | [UI.md](UI.md) |
| The Opus design review and the answer to each finding | [REVIEW.md](REVIEW.md) |
| The build slices, their builders and the file ownership | [BUILD.md](BUILD.md) |

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
| **source key** | What the throttle counts a source as: the IPv4 address, or the IPv6 `/64`; an IPv4-mapped IPv6 address is unmapped first (section 8.1). |
| **familiar source** | A source whose prefix (IPv4 `/24`, IPv6 `/64`) signed in successfully as a given name before (section 8.1). |
| **restricted session** | A session whose user has `must_change_password` set: it can only change that password or sign out (section 6.3). |
| **actor** | The user name of the session that made a request, or `-` when there is none: a request without a user and a background thread both write `-` (the one value for "nobody", 10.3). |

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
| **A1 Internet scanner** with credential lists | Finds the port within hours; sends thousands of sign-in attempts from many addresses; fingerprints the product from any unauthenticated page or header. | Nothing but `/login`, `/setup`, four static assets and `/api/health` answers without a session (6.3). scrypt makes each guess cost about 50 ms of CPU and 32 MiB of memory on the server, in a four-thread executor that a flood cannot widen (4.1); throttling slows a source-and-name pair after five failures, a source after a hundred in 15 min and an unfamiliar source after ten failures per name (8); no response differs between an unknown user and a wrong password (8.5); a flood is summed per source and minute so it cannot rotate the audit record away (10.1); the setup page is not reachable once an admin exists (9.4). |
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
| Logs | `events.jsonl` without actor or source (store.py:115-138) | `events.jsonl` gains `actor` (and nothing else); a new `audit.jsonl` holds the security events and `audit-failures.jsonl` the sign-in failures, summed per source key and minute (10). |
| The user on the poll | `/api/state` carries no user (main.py:247-261) | `/api/state` gains `user:{name, role, must_change_password}` for the session's own user (3.4). |
| `ui.token` | Read into `Store.token` (store.py:22-23), hidden by the runner (runner.py:420), sent by `test_app.py:47` | Removed from the read path (12.2). |
| Startup banner | `'UI login is disabled for this lab VM.'` (main.py:72) | `'Containerlab Node Manager ready; sign-in required.'` or, in setup mode, the setup notice, which names the file and the command and never the code (9.2). |
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
| `last_signin` | ISO 8601 UTC or `null` | Updated on every successful sign-in (and the setup sign-in); `null` before the first. An admin of an exposed system sees it without opening the audit log (RECONCILIATION 1). |
| `known_sources` | list of strings | The last 8 source prefixes (IPv4 `/24`, IPv6 `/64`, written `203.0.113.0/24`, `2001:db8:1:2::/64`; 8.1) that signed in successfully as this user, newest last, appended in the same save that writes `last_signin`; a prefix already in the list moves to the end instead of being added again, so the list holds 8 **distinct** prefixes and eight sign-ins from one classroom never push a person's home prefix out; `[]` on a new record. **Private**: never copied by `public_user`, never in `/api/state`, never in a log. It decides which sources the per-name throttle treats as familiar (REVIEW R5). |

No email and no display name in the record; `last_signin` and the private `known_sources` are the only
sign-in facts it keeps, and the rest of the history is the audit log (10). The record minus `password`
and `known_sources` is what `/api/users` may show.

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
- **No self-reset either.** `POST /api/users/{own name}/password` answers 409
  `{detail:{code:'self_change', message:'Use Manager ▾ › Change password… for your own account.'}}`
  (REVIEW R12): a reset sets `must_change_password` and ends every session of the target, which for
  the caller would mean landing in the restricted state on their own act. The own change is
  `POST /api/session/password` (5.5), and the Users page disables the own row's **Reset password…** with
  that sentence (UI.md 5.4).

### 3.3 Start fresh keeps users and the audit log

`Store.reset` (store.py:98-111) builds the fresh document from a fixed list of keys
(`labs, jobs, operations, git_jobs, ignored_labs, host, reset_id`, store.py:106-107) and moves
`backups`, `network-design`, the event log and `ui.token` aside (store.py:102). The design adds
`users` to the copied keys, next to `host`, and adds **neither `audit.jsonl` nor `audit-failures.jsonl`**,
nor any of their rotations (`.1` to `.3`), to either move list (`finish_reset`, store.py:81, and `reset`,
store.py:102): the two audit files are never moved, deleted or truncated by the manager except by their
own rotation (10.1, ruling 7).

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

- `/api/state` (main.py:247-261) gains one key, `user:{name, role, must_change_password}`, for the
  session's own user (read from `request.state.user` and the record), so the 4 s poll carries a role
  change without a second request. `users` is a top-level key that none of its copies read; nothing
  has to be stripped. A test asserts that the JSON of `/api/state` contains neither
  `users`, `known_sources` nor the substring `scrypt$` (13.1).
- `GET /api/users` and every users route answer through one function `public_user(record)` that
  copies exactly `name, role, disabled, must_change_password, created, created_by, password_changed,
  last_signin` and adds `sessions` (the count of live sessions, from memory). Allowlisted copies, never the record:
  `password` and `known_sources` never leave the state (CLAUDE.md "Public views strip secrets").
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

**Where scrypt runs (REVIEW R7).** A verify holds 32 MiB. The sign-in, setup and own-password routes
are `async def` routes: scrypt never runs on the event loop and never in Starlette's shared pool of 40
worker threads, where a `def` sign-in route waiting on a semaphore would hold a pool token and a flood
of 120 sign-ins was measured to stall `GET /api/state` at 1.9 s. Every scrypt call, verify and hash
alike, runs in one dedicated `concurrent.futures.ThreadPoolExecutor(max_workers=4,
thread_name_prefix='scrypt')`, `accounts.SCRYPT_EXECUTOR`: the `async` routes await
`loop.run_in_executor(SCRYPT_EXECUTOR, …)` through `accounts.averify` and `accounts.ahash` (16.1); the
`def` users routes (admin-only, few) call `.result()` on a submitted future. At most 4 verifies run and
16 wait: the event-loop counter `accounts.pending` is compared with `VERIFY_LIMIT = 20` before a verify
is queued, and an attempt beyond it answers `429 {detail:{code:'throttled', retry_after: 2, message}}`
(8.3) without hashing, audited as `signin.throttled` with reason `busy` (10.2). The memory bound is
therefore 4 × 32 MiB whatever the load. Every store read and write on these `async` paths runs off the
event loop through `starlette.concurrency.run_in_threadpool` (each is short: a dictionary lookup, one
save, one audit append), so the event loop never blocks on `store.lock`. A legitimate sign-in under
load waits at most a few hundred milliseconds. Test: 50 concurrent sign-ins while `GET /api/state`
answers within its normal time (`test_signon_load.py`, 13.1).

### 4.2 The hash string

```
scrypt$<n>$<r>$<p>$<salt>$<hash>
```

`n`, `r`, `p` decimal; `salt` and `hash` URL-safe base64 without padding. Parsing: split on `$`, exactly
six parts, first part `scrypt`, integers in range (`n` a power of two between `2**14` and `2**20`,
`r` 1 to 32, `p` 1 to 16), salt 16 to 64 bytes, hash 32 bytes. A record whose string does not parse
cannot sign in (verify returns False; audited as `signin.failed`, outcome `failed`, reason `bad_record`
in `detail`, 10.2) and is shown to admins with `password_changed: null`.

Verify: parse the string, recompute with the string's own parameters, compare with
`hmac.compare_digest`. **Rehash on sign-in**: when the string's parameters differ from the shipped
constants and the password verified, the route writes a new string with the shipped parameters
under `store.lock` and saves. This is how a future parameter change reaches old records without a
migration step. The `password_changed` stamp does **not** move on a rehash (the password did not
change; sessions stay valid).

**Dummy verify.** When the submitted name is not a user, or the user is disabled, the route verifies
the submitted password against a fixed constant hash string `DUMMY_HASH` (computed once at import
from a random password with the shipped parameters) and discards the result. Every sign-in attempt
therefore costs one scrypt whether the user exists or not (8.5).

### 4.3 Policy

| Rule | Value | Why (NIST SP 800-63B, section 5.1.1.2 of the 2017 text and section 3.1.1 of revision 4) |
|---|---|---|
| Minimum length | 12 characters | NIST requires at least 8 and recommends 15 for user-chosen passwords; 12 is the floor this product accepts for an account that opens a shell on every lab device. Counted in Unicode code points after NFKC normalization. |
| Maximum length | 128 characters | NIST requires at least 64 be accepted; 128 bounds the scrypt input. Longer: the reason `too_long` of the one 422 `weak_password` (7.4). |
| Composition rules | None | NIST forbids requiring character classes; they shift users to predictable substitutions. |
| Equal to the user name (case-insensitive), or the user name inside the password | Refused | A credential list pairs them. |
| Deny-list | The top 100 of a published breached-password list, embedded as a frozen set in `app/accounts.py` with its source and date in a comment | NIST requires a check against known-compromised values; 100 entries cover what a spraying scanner tries first; a larger list is a file the image does not need. |
| Whitespace | Leading and trailing whitespace is kept (not stripped); an all-whitespace password fails the length rule after NFKC like any other | Stripping would make two passwords equal that the user typed differently. |
| Expiry | None | NIST forbids periodic rotation; `must_change_password` (3.1) is the only forced change, after an admin set the password. |

The policy function `check_password(name, password)` returns a list of reason codes (`too_short`,
`too_long`, `equals_name`, `common`) and the route answers 422 `{detail:{code:'weak_password',
reasons:[...], message}}`, where `message` joins the sentences of the reasons (7.4; REVIEW U11). The
sign-in page never runs the policy (a sign-in verifies what is stored); the setup, create, reset and
own-change paths do.

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
  'role': 'operator',              # copied at sign-in; the user index decides on every request (5.5)
  'provider': 'local',             # fixed; a later OIDC provider writes its own value
  'created': <monotonic>, 'created_at': <iso>,
  'last_seen': <monotonic>,
  'password_changed': <the user's stamp at sign-in>,
  'source': '203.0.113.7',         # for the audit log only
}
```

`must_change_password` is not copied into the session: the user index (5.5) holds it, so the gate reads
one place for the role and the restriction.

- `id` is `secrets.token_urlsafe(32)` (256 bits). It is the dictionary key and the cookie value, and
  it is never written to any log, event, audit entry or error (10.4). The audit log names a session by
  its user and source, never by id.
- Monotonic times decide expiry (a wall-clock jump must not extend a session); the ISO time is for
  the audit entry only.
- Bounds: at most 32 sessions per user and 512 in the process. Above either bound a sign-in evicts
  the oldest `last_seen` session of that user, then of the process, and audits `session.ended` with
  the reason `evicted` (10.2).

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
| `Max-Age` | 604800 (`ABSOLUTE`, the absolute limit) | Set once, by the response that creates or rotates the session (sign-in, setup, the own change), and **never re-sent**: the server's idle and absolute rules decide (5.4), and the browser drops the cookie at the absolute limit, which the server counts from the same moment. A shorter browser lifetime would be false: socket input renews a session (11.3) and a socket cannot send `Set-Cookie`, so a person who only typed in a terminal for 12 h would hold a live server session that the browser had already forgotten. |

Sign-out (`DELETE /api/session`) answers `Set-Cookie: clab_session=; Max-Age=0; ...` with the same
attributes and deletes the record, and the same response always clears `clab_capture_owner` with
`Path=/api/capture` (11.2; REVIEW R10), whether or not a session existed.

### 5.4 Timeouts and renewal

| Limit | Value | Why |
|---|---|---|
| Idle | 12 hours | A lab day with a lunch break; a laptop left open overnight is signed out by morning (A3). |
| Absolute | 7 days | Bounds a session that a tab keeps alive. A course runs a week; a cookie older than that is more likely stolen than in use. |

- **Renewal on acts of the person only (REVIEW R9, fail-closed).** `last_seen` moves, through
  `sessions.touch(id)` (16.1), on exactly three kinds of request: a request with any method but `GET`
  and `HEAD` that passes the gate; a page navigation (`GET` or `HEAD` whose `Accept` includes
  `text/html`) that passes the gate; and client input on an open terminal, console or capture socket
  (the handlers call `touch` on input, at most once a minute, 11.3). **No `GET /api/...` renews a
  session**: not the 4 s poll, not the Topology tab's timers, not an open drawer or a capture viewer,
  so no poller keeps a tab signed in; an open tab in which nobody acts expires after 12 h and the
  next poll's 401 sends it to `/login`. The earlier special list (`/api/state`, `/api/session`) is gone.
- Renewal changes nothing in the browser: the cookie is never re-sent (5.3), so `Set-Cookie:
  clab_session=…` appears only on the sign-in, setup and own-change responses and the clearing one of
  sign-out. `touch` is a dictionary write under the sessions lock and nothing else.
- Expiry is checked by the gate on every request: `now - last_seen > 43200` or
  `now - created > 604800` → the record is deleted, the request is refused as signed out, and
  `session.expired` is audited **once**, with the reason: `resolve` queues the entry and the sweep
  writes it (the gate itself does no I/O, 5.5). Later requests with the dead cookie find no session and
  are logged nowhere (6.4).
- A sweep (`sessions.sweep()`) runs on every sign-in and at most once a minute from the gate, in the
  thread pool (`run_in_threadpool`, fire-and-forget), deleting expired records, writing the queued
  expiry entries and flushing the closed failure buckets (10.1). There is no timer thread: the
  lifespan's thread list (main.py:71-88) stays as it is.

### 5.5 Sign out everywhere: the user index

The gate takes **no store lock** and makes no blocking call (REVIEW R4: `store.lock` is a threading
lock that `/api/logs` holds while it parses up to 20 MiB, and an `async` layer waiting on it would
stall every request and every terminal; the order between it and the sessions lock would also be
undefined). Instead `Sessions` keeps a **user index** `{name: UserFacts(role, disabled,
password_changed, must_change_password)}` under its own lock:

- built by `create_app` from the state (`sessions.load_users(store.state.get('users', {}))`), right
  after the `Store` and before any route is installed; not in the lifespan, which the tests do not run;
- refreshed by every route that writes a user record (the users routes, `POST /api/setup` in setup
  and in recovery mode, the own change): the route calls `sessions.set_user(record)` or
  `sessions.drop_user(name)` **after its state save, inside the same `store.lock` block**, so the index
  never shows a record the state does not hold and two admins cannot interleave;
- **setup mode is "the index is empty"** (`sessions.setup_mode()`, 9.1).

On every request the gate reads the session and the index together, under the sessions lock only,
and deletes the session, refusing the request as signed out, when any of these holds:

| Condition | Who causes it |
|---|---|
| The name is not in the index | `DELETE /api/users/{name}` |
| `disabled` is true in the index | `PATCH /api/users/{name}` |
| `password_changed` in the index differs from the session's copy | `POST /api/users/{name}/password` (admin reset: every session of the user) or `POST /api/session/password` (own change: every session but the current one, whose copy `rotate` re-stamped first, below) |

The routes also end the sessions eagerly (`sessions.end_user(name, reason)`, 16.1), so the audit log
carries one `session.ended` entry per ended session with its reason (`user_disabled`, `user_deleted`,
`password_reset`, `password_changed`). The index check is the safety net for any path that forgets.

**Lock order: `store.lock` before the sessions lock, never the reverse; and the sessions lock is never
held across I/O** (a file write, a state save, an audit append, a network call). A route that writes a
user record does so as above; the gate and the sweep collect under the sessions lock what must be
audited and write after releasing it. `test_session.py` pins the order (13.1).

The own change (`POST /api/session/password`) takes no option: it always ends every other session of the
user (there is no "sign out everywhere" checkbox) and **rotates the current session's id**; **the
current session survives the own change**, re-stamped. Inside the one `store.lock` block, after the
state save, the route runs exactly this order:

1. `new_id = sessions.rotate(session_id, record['password_changed'])` (16.1): mints the new id, moves
   the record to it **and writes the new stamp into the kept record**, so the session's copy already
   equals what the index is about to show;
2. `sessions.set_user(record)`: the index now carries the new stamp; the current session (under its
   new id) matches it, every other session of the user no longer does;
3. `sessions.end_user(name, 'password_changed', keep=new_id)`: ends every other session eagerly, with
   its audit entry; the kept id is skipped.

Because the stamp is written into the session before the index changes, there is no window in which a
concurrent request on the current session is refused by the index check, and the first request on the
rotated cookie, the page's `location.replace(next)`, answers 200 (`test_session.py`, 13.1). A request
that still carries the old id after step 1 finds no session and is refused as signed out, which is the
intended fate of the old cookie. The role is read from the index on every request, so a `PATCH` of
the role takes effect on the next request without ending the session.

### 5.6 The scheme rule (interface with EXPOSURE.md)

Nothing reads `X-Forwarded-*` (INVENTORY 6.6, last item). Three places today derive "own origin" from
the request alone: the guard compares `Origin` with `request.base_url` (main.py:123), the two sockets
compare the Origin's scheme with `ws.url.scheme` (node_services.py:573-574; capture_sessions.py:318-319),
and the capture cookie sets `secure` from `request.url.scheme` (capture_sessions.py:114). They stay
correct only while the scope's scheme is true, which is why EXPOSURE.md terminates TLS in uvicorn itself
(EXPOSURE.md section 2) and not in a proxy in front of the manager.

The rule, binding for both designs (RECONCILIATION 4, E-Q1: `UI_TLS` is dropped):

1. One function `app/origin.py: scheme(scope)` answers `https` when `scope['scheme']` is `https` or
   `wss`, otherwise `http`. It reads the ASGI scope only: no environment variable, no header.
2. The guard, both sockets, the capture cookie, the session cookie and HSTS (6.1) use it. The guard's
   comparison becomes `origin == f'{scheme(scope)}://{host}'` with the `Host` the request carries.
3. uvicorn runs with an explicit `--no-proxy-headers` in both compose files (`compose.yml`,
   `deploy/compose.image.yml`) and in the Dockerfile `CMD`. uvicorn 0.54 enables proxy headers by
   default and trusts loopback, so the feature is active today; INVENTORY 4 is corrected by EXPOSURE.md
   section 2.1. `test_release_consistency.py` asserts that `UI_TLS` is absent from both compose files
   and pins `--no-proxy-headers`.
4. The source address is `scope['client'][0]` in every case. `X-Forwarded-For` is not read; a later
   design that supports a remote proxy adds `--forwarded-allow-ips` with an explicit list and is
   reviewed then.

## 6. The gate

### 6.1 Where it lives

`SessionGate` is a pure ASGI class in `app/sessions.py`, shaped like `HostCheck` (allowed_hosts.py:79-99):
it handles `http` and `websocket` scopes and passes `lifespan` through. It is added in `create_app`
with `app.add_middleware(SessionGate, sessions=app.state.sessions)` **immediately before** the `HostCheck`
line (main.py:515); it receives the `Sessions` object and nothing else, in particular no `Store` (the
gate takes no store lock and does no I/O, 5.5; a builder holding a store reference would be invited to
read it). Starlette inserts each added middleware at the front of the list
(`Starlette.add_middleware` → `user_middleware.insert(0, ...)`), so the order outermost first becomes:

| Layer | Added at | Role |
|---|---|---|
| `HostCheck` | main.py:515 (last) | Host allowlist; stays outermost, as the invariant requires. |
| `SessionGate` | new line before main.py:515 | Session, setup mode, role default. |
| `diagnostics.requests` | diagnostics.py:113 via main.py:159 | `X-Request-ID`, the in-memory request list. |
| `guard` | main.py:119 | Origin, reset pending, content length, the `api.request` event, the security headers. |
| router | | |

A refusal by the gate is therefore not in the diagnostics request list and does not reach the guard;
it is **logged nowhere** (REVIEW R8: a scanner's requests are noise that must not rotate the audit
record away; the one entry an expiry produces is the `session.expired` of 5.4). The gate's own
responses carry the same fixed headers as `HostCheck` (allowed_hosts.py:31-33) plus `Cache-Control:
no-store`, because the guard's headers (main.py:145-155) are not applied to a response the guard never
sees (the same gap INVENTORY 6.1 notes for the guard's own early returns). Ruling (RECONCILIATION 3,
Dq5): one function `security_headers(scope, *, status=200, refusal=False)` in a new `app/headers.py`
(signature and contents in 16.3) is used by `HostCheck`, the gate and the guard, in scope for the
build; it closes the gap that the guard's early returns carry no headers. `Strict-Transport-Security:
max-age=15552000` (180 days, no `includeSubDomains`, no `preload`) lives in it and is sent when
`scheme(scope) == 'https'` (RECONCILIATION 4, E-Q5).

### 6.2 What the gate does, in order

1. Read the single `Cookie` header, find `clab_session`. A repeated cookie name takes the first value.
2. Resolve under the sessions lock and nothing else (no store lock, no I/O; REVIEW R4): look the id
   up, check expiry (5.4), check the user index (5.5). The result is a session or nothing. Put
   `scope['state']['user'] = {'name', 'role', 'session_id', 'must_change_password'}` (the role and the
   flag from the index at this request) or `None`; `scope['state']` is the dictionary `Request.state`
   wraps, so routes read `request.state.user` and socket handlers `ws.scope['state']['user']` (16.2).
3. Setup mode (9.3) is decided before anything else: while the index is empty, only the setup
   exemptions answer; everything else redirects or refuses as in 9.3.
4. If the path is exempt (6.3), pass through; `GET /login` and `GET /setup` decide themselves what a
   live session gets (6.3).
5. If no session: refuse (6.4), and log nothing.
6. If the session is **restricted** (`must_change_password` in the index) and the request is not in
   the restricted allowlist (6.3): a page request (`GET` or `HEAD` whose `Accept` includes `text/html`)
   answers `302 /login?change=1&next=<path+query, percent-encoded>`, any other HTTP request `403
   {detail:{code:'password_change_required', message}}` (7.4), a socket closes 1008 with reason
   `password_change_required` before accept (REVIEW R1).
7. Renew (`touch`) when the request is an act of the person (5.4), then pass through; the response is
   not changed (the cookie is never re-sent, 5.3).

The gate never raises; a malformed cookie is "no session".

### 6.3 The exemption list

Exact. Everything not in this table needs a session. The table is a constant `EXEMPT` in
`app/sessions.py` and a test walks it (13.1). **Matching is on the exact `scope['path']` string the
router receives, with no normalisation**: no `posixpath.normpath`, no case folding, no folding of `//`,
no tolerance for a trailing slash. Any other spelling (`..`, `//`, a trailing slash, other case) is
simply not in the table and needs a session; the gate and the router therefore always see the same
string, and a path that contains `..` is routed exactly as it is spelled (today's one `{path:path}`
route, capture_sessions.py:244, refuses `..` itself, :246). The same rule applies to `RESTRICTED` below.
A gate that normalised before matching could read `/api/capture/sessions/x/assets/../../../../session`
as the exempt `GET /api/session` while the router dispatched it to the protected handler; `test_session.py`
sends that spelling without a cookie and expects 401 (13.1).

| Method | Path | Why |
|---|---|---|
| `GET` | `/login` | Serves `login.html` (page `<title>` `Sign in`). The only page reachable without a session. The route, not the gate, answers `302 /` to an **unrestricted** live session and **serves the page to a restricted one**, whose `login.js` shows the change view (`#signin-change`, UI.md 1.5) after `GET /api/session` says `must_change_password: true` (REVIEW R1). |
| `GET` | `/setup` | Serves `setup.html` in setup mode or recovery (9), loading `login.css` and `setup.js` only; 404 otherwise. With a live session it answers `302 /`. |
| `GET` | `/static/login.css`, `/static/login.js`, `/static/setup.js`, `/static/fabric-mark.svg` | What those two pages need. `login.css` is a small self-contained stylesheet: `style.css` (2760 lines of every feature's class names, INVENTORY 3) is a product fingerprint and stays behind the gate. `login.css` holds the colour, spacing, radius and font tokens copied verbatim from `style.css:55-120`, the dark-scheme overrides for those tokens, and the rules for `body`, the card, the form fields, the primary button, the error and help lines, the banner and the brand mark; nothing else. A test asserts that it names no application selector (`#save-chip`, `.topbar`, `.panel`, …). |
| `POST` | `/api/session` | Sign in. |
| `GET` | `/api/session` | Answers 200 with the user or 401 cleanly; the pages use it to decide where to go. |
| `DELETE` | `/api/session` | Sign out. Always answers 200 with the cookies cleared, also when the session is already gone; never 401 (a signed-out tab can still clear its cookie). |
| `POST` | `/api/setup` | The first admin (9). |
| `GET` | `/api/health` | `{"ready": true}` and nothing else (6.7). |

What is **not** exempt, stated because a reader might expect it: `/` (redirects to `/login`),
`/static/*` including `style.css`, every manager script and the editor bundle, `/student-guide`
(main.py:505), `/vm-connection-guide` (main.py:501), `/api/logs`, every download, every socket.

Allowlist for a **restricted** session (`must_change_password`; REVIEW R1): the exempt rows above (so
`GET /login` serves the change view, `GET /api/session` says `must_change_password: true` and
`DELETE /api/session` is the way out, **Sign out** on that view) plus `POST /api/session/password`;
the constant is `RESTRICTED` in `app/sessions.py` (16.3). Nothing else: not `/`, not `/api/state`, no
static file behind the gate, no socket. The forced change therefore lives on the sign-in page, in the
same card: *Choose your own password* / *The password you signed in with was set by an administrator.
Choose your own before you continue.*, **Change password and continue**, **Sign out**; success is
`location.replace(next)` (UI.md 1.5). A live session never *becomes* restricted: the flag is set only
when an admin creates a user (no session exists yet) or resets a password (which ends every session of
that user, 5.5), and cleared only by the own change; so `index.html` has no required-change dialog
and no live tab is ever thrown into the restricted state.

### 6.4 The refusals

| Scope | Condition | Answer |
|---|---|---|
| `http`, any path, any method but a page request (below) | no session | `401` JSON `{"detail":{"code":"signed_out","message":"Your session ended. Sign in again."}}`, `WWW-Authenticate` is **not** sent (it would make browsers show a basic-auth prompt on a `fetch` in some configurations; the JSON code is the contract). |
| `http`, `GET` or `HEAD` whose `Accept` includes `text/html` | no session | `302` to `/login?next=<path+query, percent-encoded>`. Page against API is decided by `Accept`, not by the path: this covers `/student-guide`, `/vm-connection-guide` and `window.open('/api/labs/<id>/design/export')`; every other request (a `fetch`, another method) gets the 401 JSON above. `next` is the path and query only (the hash never reaches the server), built from `scope['path']` and `scope['query_string']`, never from a header, so it always starts with a single `/` (the open-redirect rule is checked again by `login.js`, 15). |
| `websocket` | no session | `websocket.close` code 1008 before accept, reason `signed_out`, as `HostCheck` does (allowed_hosts.py:92-95). |
| `http`, a page request as above | restricted session, path not in `RESTRICTED` | `302` to `/login?change=1&next=<path+query, percent-encoded>` (REVIEW R1). |
| `http`, any other request | restricted session, path not in `RESTRICTED` | `403` JSON `{"detail":{"code":"password_change_required","message":"Choose your own password before you continue."}}`. |
| `websocket` | restricted session | close 1008 before accept, reason `password_change_required`. |
| any | setup mode | section 9.3 |

A refusal for a missing, expired or ended session is **logged nowhere**: not in `events.jsonl`, not in
the audit files, not in the diagnostics list (REVIEW R8). Every refusal body of the gate carries a
`message` (7.4; REVIEW U11), so a page script without the 401 hook shows a sentence instead of its
generic fallback.

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
ticket binding (11.1). A session that ends while a socket is open closes the socket: the terminal,
console and capture socket handlers check the session on every idle tick (at most 5 s) and close 1008
with reason `signed_out` when it is gone (11.3).

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
through an admin credential stored on the VM. The facts for the design engine and the capture service
come from `python -m app.probe <name>` (RECONCILIATION 4, E-Q2, narrowed by REVIEW R16): a probe
never constructs a `Store`, never writes and never logs a value, but it **may decrypt `state.enc`
read-only** with `state.key`, exactly as `STORAGE_PROBE` (check_install.py:299-331) already does, which
serves the VM connection and discovery facts and the list of Git bindings; the end-to-end checks
(`http-browse`, `git-http`) become probes that run the manager's own clients read-only from that state,
and where a probe cannot be built without a `Store` the check stays and answers SKIP with the reason and
*Open Manager ▾ › Diagnostics, which runs the same check.* The probe names and their JSON are
EXPOSURE.md 6.1's table; none of today's checks is dropped silently. A version-less health route is a weaker fingerprint
than today's unauthenticated `/api/state`, but it still says "this is a web service that answers
`/api/health`". The alternative, no route at all, would leave the installer polling a 302 from `/`,
which is a worse signal to an operator and the same signal to a scanner. EXPOSURE.md removes
uvicorn's `server:` header (`--no-server-header`) and the gate's own responses carry no product name.

## 7. Authorization

### 7.1 The rule

Every route that passes the gate is **operator** unless it declares **admin**. The gate enforces
"signed in"; the handful of admin routes declare `Depends(require_admin)` from `app/sessions.py`,
which reads `request.state.user`, returns it, and raises `403 {detail:{code:'admin_required',
message:'Administrators only.'}}` after recording `forbidden`, summed per actor, route template and
minute like the sign-in failures (10.1; 16.2). A middleware
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
| `POST /api/session` (`async`) | `{username, password}` | `200 {user:{name,role,must_change_password}, expires}` + cookie (with `must_change_password: true` the session is restricted and the page shows the change view, 6.3); `401 invalid_credentials`; `429 throttled` + `Retry-After` (8.3; also the `busy` refusal of 4.1); `503 setup_required` in setup mode | exempt |
| `GET /api/session` | | `200 {user:{name,role,must_change_password}, expires}`; `401 signed_out` | exempt |
| `DELETE /api/session` | `{}` | `200 {signed_out: true}` + the two clearing cookies (`clab_session`, `clab_capture_owner` with `Path=/api/capture`, 11.2), always, also when the session is already gone; no 401 | exempt |
| `POST /api/session/password` (`async`) | `{current, password}` | `200 {changed: true}` + rotated cookie; `401 invalid_credentials` when `current` fails (a failure for the three levels of 8 under the session's own name; the sentence *The current password is not right.*); `422 weak_password`; `429 throttled` | signed in (also restricted) |
| `GET /api/users` | | `200 {users:[public_user…]}` | admin |
| `POST /api/users` | `{name, role, password}` | `200 {user}`; `409 exists`; `422 weak_password` or `invalid_name`. The new record has `must_change_password: true` and `known_sources: []`. | admin |
| `PATCH /api/users/{name}` | `{role?, disabled?}` | `200 {user}`; `409 last_admin` / `self_change`; `404 user_not_found` | admin |
| `DELETE /api/users/{name}` | `{}` | `200 {deleted: true}`; `409 last_admin` / `self_change`; `404 user_not_found` | admin |
| `POST /api/users/{name}/password` | `{password}` | `200 {user}` (ends the user's sessions, sets `must_change_password`); `409 self_change` when `{name}` is the caller's own (3.2; REVIEW R12); `422 weak_password`; `404 user_not_found` | admin |
| `GET /api/audit` | query `limit` (1..500, default 100), `offset`, `event` (one code of 10.2 or a comma-separated list of them; an unknown code matches nothing), `actor`, `outcome`, `since` (ISO), `address` (filters the row field `source`) | `200 {entries:[…], total}` newest first, merged from both audit files and the open failure buckets (10.1) | admin |
| `POST /api/setup` (`async`) | `{code, username, password}` | `200 {user}` + cookie; `401 invalid_code`; `404 setup_closed` when not in setup or recovery; `409 exists` in recovery mode when the name is an existing record's (it never overwrites, 9.5; REVIEW R11); `422 weak_password` / `invalid_name`; `429 throttled` | exempt |
| `GET /api/health` | | `200 {ready: true}` | exempt |

Every body model is a Pydantic model with `extra='forbid'` (the house pattern, main.py:221-223).
Every mutating route needs a body because the guard requires a content length (main.py:127-131);
that is why `DELETE` routes take `{}`. The three `async` routes are the ones that verify or hash a
password on an unauthenticated or throttled path (4.1).

### 7.4 Every error body

Every 4xx and 503 body the sign-on code sends is `{detail:{code, message, …}}`, one sentence per code
and reason (REVIEW U11): the sentences are the manager's own voice, written from UI.md section 8, and
the pages show `detail.message`, keeping a sentence of their own only for a network failure. The
sentences are the constant `MESSAGES` in `app/accounts.py`, one place for the test that every refusal
carries one (13.1).

| Status | `code` | `message` | Sent by |
|---|---|---|---|
| 401 | `signed_out` | Your session ended. Sign in again. | the gate; `GET /api/session` |
| 401 | `invalid_credentials` | Wrong username or password. | `POST /api/session` |
| 401 | `invalid_credentials` | The current password is not right. | `POST /api/session/password` |
| 401 | `invalid_code` | That setup code is not right. On the VM, run: sudo cat /srv/containerlab-node-manager/data/setup-code | `POST /api/setup` (REVIEW U13) |
| 403 | `admin_required` | Administrators only. | `require_admin` |
| 403 | `password_change_required` | Choose your own password before you continue. | the gate (6.4) |
| 404 | `setup_closed` | Setup is closed. Sign in, or ask the VM administrator to run the recovery command. | `POST /api/setup`; `GET /setup` answers a plain 404 (9.4) |
| 404 | `user_not_found` | No account has that name. | the users routes |
| 409 | `exists` | That name already exists. | `POST /api/users` |
| 409 | `exists` | That name already exists. Choose a new name for the recovery administrator. | `POST /api/setup` (REVIEW R11) |
| 409 | `last_admin` | The last administrator stays. | `PATCH`, `DELETE /api/users/{name}` |
| 409 | `self_change` | You cannot deactivate your own account. Sign out instead. | `PATCH /api/users/{own name}` with `disabled: true` |
| 409 | `self_change` | You cannot change your own role. Ask another administrator. | `PATCH /api/users/{own name}` with `role` |
| 409 | `self_change` | You cannot remove your own account. Ask another administrator. | `DELETE /api/users/{own name}` |
| 409 | `self_change` | Use Manager ▾ › Change password… for your own account. | `POST /api/users/{name}/password` (REVIEW R12) |
| 422 | `invalid_name` | Use lowercase letters, digits, dot, dash or underscore, 2 to 32 characters. | setup, create |
| 422 | `weak_password` (+ `reasons`) | the sentences of its reasons, joined by one space, in this order: `too_short` *Use at least 12 characters.*; `too_long` *Use at most 128 characters.*; `equals_name` *Choose a password that is not your username.*; `common` *That password is too common. Choose another.* | setup, create, reset, own change |
| 429 | `throttled` (+ `retry_after`) | Too many sign-in attempts. Try again in {n} s. | sign-in, setup, own change (8.3; `busy` too, with `n` = 2) |
| 503 | `setup_required` | This manager is not set up yet. Open /setup to create the first administrator. | the gate in setup mode (9.3) |

Not in this table and unchanged: the guard's own 403, 413 and 503 strings (main.py:124-131), FastAPI's
422 for a body that does not parse (its `detail` is a list, which the pages' generic fallback covers), the
capture relay's refusals.

## 8. Sign-in throttling

Three levels, all in memory in `app/sessions.py` under the sessions lock, process-local, consulted in
the order L1, L2, L3 and then the executor's `busy` bound (4.1), **every one of them before any
hashing** (REVIEW R5 and R6; this model replaces the two tables of the first draft, whose per-address
key made a classroom NAT one source and whose fixed per-name delay let a distributed attacker hold a
known name at one failure every 30 s). The paths they guard are `POST /api/session`,
`POST /api/setup` and `POST /api/session/password` (a wrong `current` is a failure of the session's
own name from its source).

### 8.1 Source key and familiar source

| Term | Definition |
|---|---|
| source key `S` | `source_key(address)`: the IPv4 address itself, or the IPv6 `/64` network of the address. An IPv4-mapped IPv6 address (`::ffff:a.b.c.d`, what IPv4 clients look like when `UI_BIND` is `::`) is unmapped first, so IPv4 clients never share the `::/64` bucket; the IPv6 part matters only when an operator binds an IPv6 address (the default `0.0.0.0` is IPv4 only). |
| prefix `P` | `source_prefix(address)`: the IPv4 `/24` or the IPv6 `/64` network, written as `203.0.113.0/24` or `2001:db8:1:2::/64`. |
| familiar | A source is familiar for a name when its prefix is in that record's `known_sources` (3.1): the last 8 prefixes that signed in successfully as that name. A classroom NAT is one familiar prefix for everyone who signed in from it; a name that does not exist has no familiar source. |

### 8.2 The three levels

| Level | Key | Counts | Delay | Cleared by |
|---|---|---|---|---|
| **L1** pair | `(S, name)`, the submitted name lowercased, whether or not it exists | the pair's consecutive failures | 5 failures are free; the 5th starts a 30 s delay and each further failure doubles it (60 s, 120 s, …) up to 15 min; the delay counts from the last failure | a success of that pair; an entry idle for 1 h is pruned |
| **L2** source | `S` | a sliding 15 min window of the source's failure records `(time, name)` | while the window holds 100 or more records the source is delayed 30 s, doubling with each further failure, up to 15 min; the delay ends when the window falls below 100 (records older than 15 min drop) | a success of `(S, N)` removes only `S`'s records for `N`, never another name's and never another source's |
| **L3** name, unfamiliar sources only | the submitted name, lowercased | a token bucket of 10 tokens, one given back every 30 s; every failure from an *unfamiliar* source spends one | an empty bucket refuses every attempt from an unfamiliar source with `retry_after` = the seconds to the next token (at most 30) | time only: a success refills nothing. A familiar source never consults L3. |

Rules shared by the levels:

- A **failure** is an attempt that ran the verify and did not succeed (`invalid_credentials`,
  `disabled`, `bad_record`, `invalid_name`, a wrong setup code, a wrong `current`). It increments the
  L1 pair, appends to the L2 window and, from an unfamiliar source, spends an L3 token.
- A **throttled** attempt (any level, or `busy`) is refused without a verify, audited as
  `signin.throttled` (10.2) and changes no counter: otherwise a throttled attacker would extend their
  own delay indefinitely, and so would the person they impersonate.
- A **success** clears the L1 pair, removes the pair's records from L2, leaves L3 alone and appends
  the source's prefix to `known_sources` (3.1).
- `retry_after` is the largest of the delays of the levels that refuse the attempt, as an integer number
  of seconds.
- Bounds: each level holds at most 10 000 entries (pairs, sources, names) and a source's window at most
  200 records; above a bound the entry with the oldest activity is evicted, so a flood of spoofed
  sources cannot grow memory. An L3 bucket that is full is dropped by the prune (full is the default
  state), so the tables stay small while nothing is attacked.

### 8.3 The answer

`429 {detail:{code:'throttled', retry_after: <n>, message:'Too many sign-in attempts. Try again in <n> s.'}}`
with a `Retry-After: <n>` header, the one sentence for every 429 (REVIEW R5). The `busy` refusal of 4.1
answers the same body with `retry_after: 2`.

### 8.4 Never permanent, and the person always gets in

- L1 and L2 cap at 15 min and count from the last failure; nothing is locked out. The counters reset
  when the process restarts, which is acceptable: a restart is an operator action on the VM, and an
  attacker cannot cause one from the network (nothing unauthenticated reaches a code path that exits
  the process). If a restart ever became attacker-triggerable, the counters would need persistence;
  the audit log would show the pattern either way. The CLI recovery path (9.5) does not use the
  sign-in route and is not throttled by it.
- A classroom behind one NAT: thirty students' ordinary typos are thirty different L1 pairs, and the
  L2 window needs 100 failures within 15 min before that source is delayed at all; a success of one
  student clears nothing of another's.
- A distributed attack on one name (one failure every 30 s from ever-new addresses) cannot lock that
  person out: their own network is a familiar prefix, which never consults L3, and L1 and L2 are keyed
  by the attacker's sources. **Accepted remainder:** a person signing in from a *new* network while
  their own name is under such an attack waits for an L3 token (up to 30 s each; an attacker who
  spends each token first keeps them waiting), and the audit log shows the attack (`signin.throttled`
  with reason `name`, summed per source and minute).
- An insider cannot reset their counters by signing in as themselves between guesses at the admin's
  name: the success clears only their own pair and their own records for their own name (REVIEW R6),
  so the guesses at the admin's name stay in their L2 window and their L1 pair with that name.

### 8.5 No enumeration, constant work

- The route runs exactly one scrypt per non-throttled attempt: the user's hash when the user exists
  and is enabled, `DUMMY_HASH` otherwise (4.2). The branch that decides which hash is a dictionary
  lookup, which is not a measurable difference beside a 50 ms verify.
- The answer for an unknown name, a wrong password and a disabled user is the same 401
  `invalid_credentials` with the same sentence. L1 and L2 do not depend on whether the name exists;
  L3 treats every source of a non-existent name as unfamiliar, which is also how it treats a new
  source of an existing name, so a 429 does not reveal existence either.
- `POST /api/setup` answers a wrong code with 401 `invalid_code`, compares the normalised codes with
  `hmac.compare_digest` (9.2) and is throttled by the same three levels under the submitted name.

## 9. First-run bootstrap and recovery

### 9.1 Setup mode

The manager is in setup mode while `state['users']` is empty, which the gate reads as "the user index
is empty" (`sessions.setup_mode()`, 5.5). This is the state of a new install and of an upgraded
install on its first start (12.1).

### 9.2 The setup code

- In setup mode **`create_app`** generates the code, not the lifespan: the tests build a `TestClient`
  without running the lifespan, and the user index of 5.5 is built in the same place. The code is
  24 characters from the alphabet `abcdefghjkmnpqrstuvwxyz23456789` (31 symbols, no `0/o/1/l/i`,
  about 119 bits), shown as four groups of six (`xxxxxx-xxxxxx-xxxxxx-xxxxxx`), by `secrets.choice`.
- It writes the file `<DATA_DIR>/setup-code` (mode 0600 through `Store.atomic`, store.py:34-44; owner
  is the container user `worker`, uid 10001, Dockerfile:12) with two lines: `mode=setup` and
  `code=<code>`. It prints to the container log the file and the command, **never the code** (REVIEW
  R22a; `docker logs` is readable by the docker group and kept by the daemon): *Setup required: open
  https://<address>:<port>/setup and enter the code from <DATA_DIR>/setup-code (on the VM: sudo cat
  /srv/containerlab-node-manager/data/setup-code).* `<port>` is `UI_PORT` from the environment
  (default 8443) and `<address>` the first name of `UI_ALLOWED_HOSTS` or the words *the VM's address*.
  The installer and the recovery command print the code to the operator's terminal, which is not a log.
- The file is the source of truth. `GET /setup` and `POST /api/setup` read it on each request
  (`accounts.read_setup_code(root)`, 16.1: a `stat` and a small read; refuse a symlink and a file
  whose mode is wider than 0600, as the capture `.env` pattern does, `deploy/setup_capture.py
  read_env`). No code is kept in memory, so the recovery command (9.5) can replace the file from
  another process.
- Matching forgives how a code was copied (REVIEW U13): both sides go through
  `accounts.normalize_code` (`strip`, lowercase, dashes and spaces removed) before
  `hmac.compare_digest`, so a code typed in capitals, without its dashes or with a space after a
  group matches; a wrong code answers the sentence of 7.4 that names the command to read it again.
- The code is valid until used. A restart in setup mode regenerates it (the old code is gone with the
  file; a stale code in an operator's notes stops working, which is the point; the installer therefore
  prints the code at its very end, after every step that recreates the manager, EXPOSURE.md 7.2).
- The bind mount makes the file readable on the VM as root or as uid 10001 under
  `/srv/containerlab-node-manager/data/setup-code`. **Interface for EXPOSURE.md:** the installer
  reads it there (or with `docker exec <container> cat /data/setup-code`) and prints it to the
  operator's terminal with the setup URL; the health check reports `Setup not completed` while the
  file exists with `mode=setup` and never prints the code.

### 9.3 What answers in setup mode

| Request | Answer |
|---|---|
| `GET /setup`, the four static assets of 6.3, `POST /api/setup`, `GET /api/health` | served (`EXEMPT` is one constant; setup mode has no asset list of its own) |
| `GET /login` | `302 /setup` |
| any other page | `302 /setup` |
| any other `/api/` path, including `POST /api/session` | `503 {detail:{code:'setup_required', message}}` (7.4) |
| any socket | close 1008, reason `setup_required` |

`POST /api/setup {code, username, password}`: run the throttle (8), compare the normalised codes
(`hmac.compare_digest`, 9.2), apply the name rule and the password policy, refuse an existing name with
`409 exists` without writing anything (only possible in recovery mode; REVIEW R11), create the record
with `role: admin`, `created_by: 'setup'` (or `'recover'`), `must_change_password: false` (the person
chose it), `known_sources: [<this prefix>]`, save the state, update the user index, **delete the
file**, audit `setup`, mint a session and answer like a sign-in. The steps "save, index, delete, audit"
run under `store.lock`; if the save fails the file stays and the route answers 500 (the house pattern,
main.py:165-172).

### 9.4 After setup

`GET /setup` answers a plain 404 and `POST /api/setup` answers `404 setup_closed` (7.4) whenever the
file is absent, so the page is not a scanner signal once the first admin exists. The only way to make
them answer again is the recovery command.

### 9.5 Recovery of a lost admin password

**`deploy/manager-recover-admin.sh`** (EXPOSURE.md owns the script's host side: it must be root on the
VM, find the container as `recreate-manager.sh` does, and be added to CI's `bash -n` loop). It runs
one command inside the container:

```
docker exec <container> python -m app.recover
```

`app/recover.py` (this design's) does, as the container user:

1. Refuse when `<DATA_DIR>/setup-code` already exists with `mode=setup` (the manager is in setup mode;
   nothing to recover): print *The manager is in setup mode: use the setup code in
   <DATA_DIR>/setup-code.* and exit 1.
2. Generate a code as 9.2, write the file with `mode=recover` and `code=<code>`, append
   `recover.requested` to `audit.jsonl` through the static `Store.append_audit(root, entry)` (no
   `Store` is constructed), and print two lines: `Recovery code: <code>` and *Valid for 15 minutes.
   Create one new administrator on the setup page; existing accounts are not changed.* It prints no
   URL: `deploy/manager-recover-admin.sh` builds `https://<address>:<UI_PORT>/setup?recover=1` from
   `.env` exactly as `start-manager.sh` does and prints it after these lines (REVIEW R11), so the
   port is right and the page knows it is a recovery.
3. Exit 0. It never touches `state.enc`, never deletes or changes a user, never resets users.

While a `mode=recover` file exists and is younger than 15 minutes (the file's mtime; the manager
deletes an older one at the next `/setup` or `/api/setup` request and audits `recover.expired`),
`GET /setup` serves the page and `POST /api/setup` accepts the code and creates **one** admin with
`created_by: 'recover'` under a name no record has (an existing name answers `409 exists` and writes
nothing, 7.4), leaving every existing user as it was, including the admin whose password was lost: the
new admin resets its password or deactivates it from People and sign-ins (the page has no Delete,
RECONCILIATION U-Q3; the route stays). The file is deleted on success. The setup page, opened by the
printed `?recover=1` address, shows the heading *Recovery: create one new administrator* and the lead
*Enter the code the recovery command printed, then choose a new administrator account. Existing
accounts are not changed.* (UI.md 2), so an operator who finds it open understands what it is.

Why this shape: nothing opens a network door that was closed (the only new reachable path needs a
119-bit code that exists only in a 0600 file on the VM for 15 minutes), the person who can run it is
already root on the VM, and no user record is destroyed by a recovery.

## 10. The audit log

### 10.1 The files

Two files under `<DATA_DIR>`, both written by `Store` with the creation mode (0600) and the rotation
(5 MiB × 4) of `Store.event` (store.py:122-130), each with its own rotation and its own write-failure
flag (`audit_error`, `audit_failures_error`: the same warning once, then silence, store.py:132-137).
They are separate from `events.jsonl` because that file is served to every operator by `GET /api/logs`
(main.py:304-306) and is moved aside by *Start fresh* (store.py:102); the audit files are admin-only
and survive a reset (3.3).

| File | Holds | Written by |
|---|---|---|
| `audit.jsonl` | the security record: `setup`, `signin`, `signout`, `password.*`, `user.*`, `session.*`, `forbidden` (summed, below), `manager.reset`, `recover.*` | `Store.audit(event, *, actor, source, outcome, target='', detail='')`; the `forbidden` buckets through it from `Sessions.flush_failures()` |
| `audit-failures.jsonl` | `signin.failed`, `signin.throttled`, `setup.failed`: what a scanner can produce at will, **summed per source key per minute**, so a flood cannot push the security record out of `audit.jsonl` (REVIEW R8) | `Store.audit_failure(event, *, actor, source, outcome, detail)`, called by `Sessions.flush_failures()` |

Summing: `Sessions.record_failure(event, source_key, actor, reason, *, target='', retry_after=0)` keeps
one open bucket per `(event, source key, actor, target, reason)` and UTC minute, under the sessions
lock (at most 10 000 open buckets; above that the oldest is flushed). A bucket is written as one entry
when its minute has passed, checked by the next failure of any source, by the sweep of 5.4, by
`GET /api/audit` and at shutdown (`flush_failures(force=True)` from the lifespan's close), with the time
of its first failure, `source` = the source key, and `detail` `<reason> count=<n>` (`signin.throttled`
adds ` retry_after=<largest>`). `flush_failures` writes the three failure events through
`Store.audit_failure` and a **`forbidden`** bucket through `Store.audit` into `audit.jsonl`: a 403 from
`require_admin` is part of the security record, but an operator session could otherwise repeat an
admin-only request without limit and rotate the record away (5 MiB × 4), which is REVIEW R8's outcome
produced by an insider instead of a scanner; summed per `(actor, route template)` and minute it costs
one line per route and minute, with the actor's name on it. `GET /api/audit` lists the open buckets
too, so an attack in progress is visible at once. `Store.audit_entries(limit, offset, *, event='',
actor='', outcome='', since='', address='', extra=())` (`event` is one code or a comma-separated list, lead's ruling after the UI amendment) reads both current files and their rotations,
merges them with `extra` (the open buckets) by `time`, newest first, and answers `(entries, total)`.

Entry: `{time, event, actor, source, outcome, target, detail}`; the `address` filter of `GET /api/audit`
matches the `source` field. `detail` is a short string of controlled vocabulary (10.2: a reason code,
a count, a role), never user input, never longer than 200 characters, never a password, a code, a
session id or a hash (10.4).

### 10.2 The events: the one vocabulary

This table is the vocabulary (REVIEW R3): the constants `AUDIT_EVENTS`, `AUDIT_OUTCOMES = ('ok',
'failed', 'throttled')` and `AUDIT_REASONS` in `app/accounts.py` are built from it; the label maps of
`users.js` (`AUDIT_EVENT_LABELS`, `AUDIT_OUTCOME_LABELS`, UI.md 5.6) and the page's filter lists name
exactly these codes, and `test_audit.py` reads `users.js` and compares the two sets (13.1). An
`outcome` is one of the three values; a reason goes in `detail`.

| `event` | `actor` | `target` | `outcome` | `detail` |
|---|---|---|---|---|
| `setup` | the new admin | | `ok` | `setup` or `recover` |
| `setup.failed` | † | | `failed` | `<reason> count=<n>`; reasons `invalid_code`, `weak_password`, `invalid_name`, `exists` |
| `recover.requested` | `-` | | `ok` | (written by `app.recover` itself, 9.5) |
| `recover.expired` | `-` | | `ok` | |
| `signin` | the user | | `ok` | |
| `signin.failed` | † | | `failed` | `<reason> count=<n>`; reasons `invalid_credentials`, `disabled`, `bad_record`, `invalid_name` |
| `signin.throttled` | † | | `throttled` | `<reason> count=<n> retry_after=<largest>`; reasons `pair`, `source`, `name` (the levels of 8.2), `busy` (4.1) |
| `signout` | the user | | `ok` | |
| `session.expired` | the user | | `ok` | `idle` or `absolute` |
| `session.ended` | the user | | `ok` | `user_disabled`, `user_deleted`, `password_reset`, `password_changed` or `evicted` |
| `password.changed` | the user | | `ok` | |
| `password.changed` | the user | | `failed` | `invalid_credentials` (a wrong `current` on the own change) |
| `user.created` | the admin | the user name | `ok` | `role=<role>` |
| `user.deleted`, `user.disabled`, `user.enabled`, `user.password_reset` | the admin | the user name | `ok` | |
| `user.role` | the admin | the user name | `ok` | `role=<new>` |
| `forbidden` | the user | the route template | `failed` | `admin_required count=<n>` (every 403 from `require_admin`, summed per actor, target and minute, 10.1) |
| `manager.reset` | the admin | | `ok` | |

† **The actor of a failed or throttled attempt is the submitted name only when it equals an existing
record's name; otherwise `-`** (REVIEW R2): a password typed into the username field (a common slip,
and the form lowercases it) must never reach a file or an admin's screen. No log, response or `detail`
field carries a submitted name otherwise; the throttle tables of section 8 hold submitted names in
memory only. `test_audit.py` signs in with the real password typed as the username and
`assert_not_logged` finds nothing (13.3).

Not audited here: ordinary mutating requests. They are in `events.jsonl` with their actor (10.3).

### 10.3 The actor on operational events

`Store.event()` gains a keyword `actor='-'` written into every `events.jsonl` entry, **and nothing
else**: the source address stays in the audit files (REVIEW R22b: `events.jsonl` is served to every
operator by `GET /api/logs`, and every user's address is not an operator's business). `Store.events()`
gains an `actor` filter. The guard's `api.request` event (main.py:143-144) passes `actor=user['name']`
when `request.state.user` is set and `'-'` otherwise (REVIEW R22c: an exempt route such as
`DELETE /api/session` without a session reaches the guard with no user, and the subscript on `None`
was reproduced as a 500); the event's message is unchanged. The guard writes **no `api.request` event
for `POST /api/session` and `POST /api/setup`** (REVIEW R8): their outcome is in the audit files only,
so a scanner cannot write two lines per attempt. Other callers of `Store.event` (terminal open and
close, downloads, jobs) pass the actor where a request is in hand; a background thread has none and
writes the default `-`, the same value as a request without a user (one value for "nobody", so the
`actor` filter of `Store.events()` has one spelling to match; its own default `''` means "no filter").
This keeps one operational log with one reader (`GET /api/logs`) and puts "who" next to
"what" where operators already look. Security events stay in the audit files because they must
survive a reset and must not be readable by operators.

### 10.4 What is never logged

A password (submitted, stored or dummy), a setup code, a session id, a cookie header, a hash string,
an `Authorization` header, the body of any sign-in or setup request. The tests grep the three log files
(`events.jsonl`, `audit.jsonl`, `audit-failures.jsonl`, with their rotations) and the open failure
buckets after every sign-in, setup and failure path for the password, the code and the cookie value (13.3).

## 11. Tickets and the capture cookie

### 11.1 The terminal ticket is bound to the session

Today the ticket tuple is `(expiry, lab_id, name, protocol)` (node_services.py:567) and the socket
pops it by key alone (node_services.py:588-591). The design adds the minting session's id as a fifth
element: `(expiry, lab_id, name, protocol, session_id)`, taken from `request.state.user['session_id']`.
On consume the handler compares it with `ws.scope['state']['user']['session_id']` using
`hmac.compare_digest`; a mismatch closes 1008 like an unknown ticket. A leaked ticket is then useless
from another browser, and a ticket outlives neither its 30 s nor the session that minted it:
`node_services` registers a callback in `sessions.on_end` (16.1) that drops the tickets of an ended
session (the dictionary is small, 32 entries at most, node_services.py:564). `services.tickets.clear()`
on reset (main.py:241) and on `close()` (node_services.py:219) are unchanged.

### 11.2 The capture cookie, and sign-out ends this browser's Wireshark sessions

`clab_capture_owner` (capture_sessions.py:107-115) isolates desktop sessions per browser and is kept
as it is. Because the gate sits in front of every capture route and the socket, the cookie is now only
ever set for a signed-in user. Its `secure` flag follows the scheme rule (5.6). Capture routes need the manager session **and** the
owner cookie (RECONCILIATION 1), and the owner identity the manager sends to the capture service is the
person's within the browser (below).

**Sign-out ends this browser's capture sessions (REVIEW R10).** The cookie is set with
`Path=/api/capture` (capture_sessions.py:113-114), so `DELETE /api/session` never receives it and
cannot end the sessions itself. Sign-out is therefore two steps, the first the page's, the second the
manager's:

1. `account.js` calls the existing owner-scoped `POST /api/capture/sessions/end-all`
   (capture_sessions.py:213-232) with `{}`, best effort: skipped when capture is disabled, and a
   failure is reported nowhere and does not stop the sign-out.
2. `DELETE /api/session` ends the session and **always** answers two clearing cookies: `clab_session`
   (`Path=/`) and `clab_capture_owner` (`Path=/api/capture`, `HttpOnly`, `SameSite=Strict`, `Secure`
   per 5.6, `Max-Age=0`), so a later person in the same browser can never inherit a desktop session
   even when step 1 failed; a session left behind by a failed step 1 ends at the capture service's
   own limit.

The sign-out menu item says so: *Signing out also closes this browser's Wireshark sessions.* (UI.md
6.4). **Expiry ends nothing**: the owner cookie stays, and the same browser signing in again finds its
sessions; ending the manager session by any means but sign-out does not end the capture container.

**Two people in one browser (the lead's ruling after the review, closing what the designer had named an
accepted remainder).** `owner(request, response)` (capture_sessions.py:107-115) keeps reading and setting the
cookie as it does today, but the identity it returns, which every owner-scoped call sends to the capture
service (the listing, `end`, `end-all`, the assets, the download and the `websockify` socket, and
`Captures.launch` through the same function), becomes
`hashlib.sha256((cookie_value + '\n' + user_name).encode()).hexdigest()`, with `user_name` from
`request.state.user` (`ws.scope['state']['user']` for the socket). It is still 64 hexadecimal characters,
which is all the service and `TOKEN` (capture_sessions.py) require, and it holds no secret of its own. So
after an expiry, or when a second person signs in over a live session (`POST /api/session`, 6.4), the next
person in that browser derives another identity and sees and reaches none of the first person's desktop
sessions, while the first person, signing in again in that browser, derives the same identity and finds
theirs. No secret of the process is mixed in, so a manager restart keeps the identities. Desktop sessions
launched before this release carry the raw cookie as their owner and are found by nobody; they end at the
capture service's own limit (the upgrade signs everyone out in any case, 12.1). Sign-out still ends the
person's sessions in this browser first (the two steps above).

### 11.3 Sockets close when their session ends, and renew it on input

The close reason is `signed_out`. The terminal, console and capture socket handlers check that the
session still resolves on every idle tick (at most 5 s) and close 1008 `signed_out` when it is gone
(ended by sign-out, expiry, a disabled or deleted user, or a password change, 5.5). On client input
(a keystroke on the terminal or console, a VNC frame from the viewer) they call
`sessions.touch(session_id)`, at most once a minute, because typing in a terminal is an act of the
person (5.4; REVIEW R9); the socket's own data never renews anything.

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
| `tests/test_session.py` | The gate on every route: a walk of `app.routes` (and the two sockets) without a cookie gets 401, 302 or 1008 by the rules of 6.4, except the exempt rows of 6.3; the classification table of 7.1 names every route (a route absent from the table fails); every gate body carries `message` (7.4). Cookie attributes exactly as 5.3, under `http` and under `https` (`base_url='https://testserver'`). Idle and absolute expiry with a patched monotonic clock. **Renewal (R9):** no `GET /api/...` moves `last_seen` (the poll, `/api/session`, a drawer's GET), a `POST` and a page navigation do; `Set-Cookie: clab_session` appears on the sign-in, setup, own-change and sign-out responses and on no other (never re-sent, 5.3). **The restricted session (R1):** sign in as a user an admin created, follow every redirect to a final 200 on `/login?change=1&next=…`, see `GET /api/session` answer `must_change_password: true`, see `/api/state` answer 403 `password_change_required` and a socket close 1008 with that reason, change the password, land on `next`; the allowlist resists `/api/session/password/../../state`, `/API/state` and a trailing slash. **No normalisation (6.3):** `GET /api/capture/sessions/x/assets/../../../../session` without a cookie answers 401, not the exempt route. Sign-out everywhere: disable, delete, admin reset, own change (other sessions end, the current id rotates). **The own change keeps the current session (R1/R4):** after `POST /api/session/password` the very next request on the rotated cookie (a page `GET /` and a `GET /api/state`) answers 200, the old cookie answers 401, and the other sessions of the user are gone; a request on the current session that runs concurrently with the own change is never refused. **Lock order (R4):** the sessions lock and `store.lock` are wrapped by recording locks, every route runs once, and no `store.lock` acquisition happens while the same thread holds the sessions lock; the gate acquires `store.lock` never. **Gate refusals are logged nowhere (R8):** a dead cookie polled ten times adds no line to `events.jsonl` or either audit file beyond the one `session.expired`. Constant work: a wrong user and a wrong password both call the verify function exactly once (patched). Session fixation: the id after sign-in differs from any cookie sent with the request. `/api/state` contains neither `users`, `known_sources` nor `scrypt$`. |
| `tests/test_setup.py` | Setup mode answers of 9.3 with their messages; the code file's mode and content, written by `create_app`; the container log line names the file and never the code; `POST /api/setup` creates the admin, deletes the file, signs in; a code typed in capitals, without dashes and with spaces matches (U13); a second setup is `404 setup_closed`; `app.recover` writes a `mode=recover` file and prints no URL, one admin is created, existing users untouched, an existing name answers `409 exists` and changes nothing (R11), a 16-minute-old file is refused and deleted; `Store.reset` keeps `users`, `audit.jsonl` and `audit-failures.jsonl`. |
| `tests/test_users.py` | Name rule, role values, `extra='forbid'`, uniqueness, last-admin and self-change refusals, `POST /api/users/{own name}/password` is `409 self_change` with its sentence (R12), `public_user` fields and nothing more (never `known_sources`), role change effective on the next request, every 4xx of the users routes carries `message`. |
| `tests/test_audit.py` | Every event of 10.2 is written with its fields and one of the three outcomes; the two files and their rotation; **summing (R8):** 50 failures from one source under 50 distinct unknown names (actor `-`, reason `invalid_credentials`, so L1 never fires and L2's 100 is not reached) in one minute are one `signin.failed` entry with `count=50`, visible through `GET /api/audit` before the minute closes; 30 admin-only requests by one operator in one minute are one `forbidden` entry in `audit.jsonl` with `admin_required count=30` and the route template as `target`; **the actor rule (R2):** the real password typed as the username leaves no trace (`assert_not_logged`), a failure under an existing name carries that name, an unknown name carries `-`; `GET /api/audit` paging and filters merge both files; the actor on `api.request` in `events.jsonl` and no `source` key there (R22b); no `api.request` event for `POST /api/session` or `POST /api/setup`; `test_users_js_labels_match_vocabulary` parses `AUDIT_EVENT_LABELS` and `AUDIT_OUTCOME_LABELS` out of `app/static/users.js` and compares them with `AUDIT_EVENTS` and `AUDIT_OUTCOMES` (R3). |
| `tests/test_password.py` | The hash string format and parser (every malformed case), round trip, `compare_digest` use (patched), rehash on sign-in when parameters differ without moving `password_changed`, `DUMMY_HASH` parses, the policy's reason codes and their joined `message`, the deny-list, NFKC length, the 500 ms bound of one verify with the shipped parameters and `maxmem`; every `hashlib.scrypt` call runs on a `scrypt` executor thread (patched to record the thread name); the 21st queued verify is `429 throttled` with `retry_after: 2` while 20 are held (R7). |
| `tests/test_signon_load.py` | **Throttling (R5, R6):** the L1 delay sequence (five free, then 30, 60, 120 … s, the 15 min cap, a success clears only the pair); the L2 sequence (100 failures in the window, then the delays; a success removes only that name's records); 30 users behind one address making ordinary typos all sign in; a distributed attack of one failure every 30 s from fresh sources against one name while the familiar source still signs in and an unfamiliar one waits for a token; an insider's own success does not clear their guesses at another name; the IPv4-mapped address keys like its IPv4 address; the table bounds. **Load (R7):** 50 concurrent sign-ins while `GET /api/state` answers within its normal time. |
| `tests/test_ticket_binding.py`, `tests/test_socket_session.py` | A ticket minted by session A is refused on a socket with session B; a ticket survives neither its 30 s nor the end of its session; an open socket closes 1008 `signed_out` within 5 s of its session ending; a restricted session's socket closes 1008 `password_change_required`; client input calls `touch` at most once a minute and the socket's own output never does (R9). |
| `tests/test_login_ui.js`, `tests/test_setup_ui.js` | UI.md's (the `next` rule of section 15 with the hash, the change view with **Sign out**, the load check through `GET /api/session`, the countdown, the recovery heading are asserted there). |

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
the jar for `testserver`, so the fixture signs in and those tests then pass `cookies=` explicitly
(RECONCILIATION 3, Dq2). This is the one place that needs care; the fixture file documents it.

For the browser fixture and the tools (RECONCILIATION 3, U-Q5, re-decided by REVIEW R15 and R21):
**`app/` contains no fixture code**, not even behind an environment variable (a hook gated by
`FIXTURE_DATA` would be shipped code outside the route walk of `test_session.py`). Instead
`docs/redesign/tools/fixture_manager.py` (its own build slice, BUILD.md S11) completes setup with
fixture credentials and, by default, wraps the app it serves in a fixture-only ASGI wrapper that adds
the fixture admin's `clab_session` cookie to every request that carries none, so the Playwright checks
that run against the fixture keep working unchanged; `--signed-out` and `--role operator` switch it,
and the sign-on checks use them. The `/__fixture/expire` hook is a route of that wrapper, not of the
app, and calls `app.state.sessions.end_user(name, reason)` (16.1). For the live tools, a
standard-library helper `docs/sign-on/tools/manager_http.py` (an `https` base URL, `--cafile` or
`--pin <cert.pem>`, credentials from `CLAB_USER` and `CLAB_PASSWORD` or a prompt, never a command-line
value, a cookie jar) replaces their bare `urllib` calls; `docs/sign-on/tools/TOOLS.md` lists every
tool that talks HTTP with its status (works through the fixture, migrated, or needs the helper and
why it was not migrated).

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

A helper `assert_not_logged(app, *secrets, captured='')` in `tests/session_fixture.py` first calls
`app.state.sessions.flush_failures(force=True)`, then reads, under `app.state.store.root`,
`events.jsonl*`, `audit.jsonl*` **and `audit-failures.jsonl*`** (the current file and every rotation
of each), plus the entries of `app.state.sessions.open_failures()` (empty after the forced flush; read
anyway so the helper does not depend on it) and the text `captured` (the container log a test captured
with `assertLogs`, where it has one: the setup line of 9.2), and asserts that no secret appears in any
of them. Without the third file the R2 test would pass even when it should fail: `signin.failed`,
`signin.throttled` and `setup.failed` go only there or to the open buckets (10.1), so a password typed
as the username would never be checked. **Every new Python test file calls it** (`test_session.py`,
`test_setup.py`, `test_users.py`, `test_audit.py`, `test_password.py`, `test_signon_load.py`,
`test_ticket_binding.py`, `test_socket_session.py`) after every sign-in, setup, failure and throttle
path, with the password, the code and the cookie value (ruling 5).

### 13.4 Environment

The scrypt timing test asserts under 500 ms with `maxmem=64 MiB`, so it passes on the image's
`python:3.12-slim` and in CI. The backend builder re-measures inside `python:3.12-slim` in CI (the
figure measured on 3.13 in 4.1 is not the image's) and records the figure in `clab-backup-ui/VALIDATION.md`; it also asserts that the shipped `maxmem` is passed, because the
default refuses the shipped parameters (4.1).

## 14. The CLAUDE.md invariant

Replacement for the bullet that begins "There is no login:" under "VM boundary and data" (the lead
applies it at the release step):

> - Sign-in is required for everything but `/login`, `/setup`, their four static assets (`login.css`, `login.js`, `setup.js`, `fabric-mark.svg`), `POST`/`GET`/`DELETE /api/session`,
>   `POST /api/setup` and `GET /api/health` (`EXEMPT` in `app/sessions.py`; `test_session.py` walks every
>   route). `SessionGate` resolves the `clab_session` cookie (`HttpOnly`, `SameSite=Strict`, `Secure` under
>   TLS, idle 12 h renewed only by an act of the person, never by a `GET /api/` poll, absolute 7 d, in
>   memory only) for HTTP and WebSocket scopes, takes no store lock, and sits directly inside
>   `allowed_hosts.HostCheck`, which stays the outermost ASGI layer (added last in `create_app`): a `Host`
>   that outside DNS could control is refused unless `UI_ALLOWED_HOSTS` lists it (DNS rebinding), nothing
>   bypasses it and `X-Forwarded-Host` is never read. Behind it `/api/` keeps the same-origin `guard` in
>   `main.py` (a mutating request needs a body; content-length 0 is refused, so pages post `{}`); every
>   WebSocket still checks `Origin` itself, and a terminal ticket is single-use and bound to the session
>   that minted it. Never add a route or socket outside this; the one exception is the redirect listener:
>   `app/redirect.py` is the one listener outside the gate and the guard: it holds no data and answers 301
>   to the manager's own HTTPS origin after `host_allowed`, 400 for a refused Host, 405 for any method but
>   GET and HEAD, closes a socket 1008, and nothing else. Admin-only routes declare `Depends(require_admin)`;
>   every other route is operator. Passwords are `hashlib.scrypt` strings (`scrypt$n$r$p$salt$hash`)
>   verified in a four-thread executor, never in the shared pool; a sign-in always runs one verify (a dummy
>   for an unknown name) and is throttled per source-and-name pair, per source and, for unfamiliar sources,
>   per name, never permanently. Users survive *Start fresh*; the first admin is created once through a
>   setup code from `<DATA_DIR>/setup-code` (never printed to a log), and `deploy/manager-recover-admin.sh`
>   is the only way to reopen that page. Security events go to `audit.jsonl` and sign-in failures, summed
>   per source and minute, to `audit-failures.jsonl` (both admin-only, both survive a reset); a gate
>   refusal is logged nowhere; no log ever holds a password, a code, a session id or a hash. "Own origin"
>   is `origin.scheme(scope)` (the ASGI scope only), never a forwarded header, and uvicorn runs with
>   `--no-proxy-headers`.

The replacement keeps the three sentences of the current bullet that the first draft dropped (*Never add a
route or socket outside this*, the DNS-rebinding sentence, *`X-Forwarded-Host` is never read*), with the
redirect named as the one exception (REVIEW R19). The redirect sentence above is the one sentence
used everywhere (CLAUDE.md, EXPOSURE.md 4.1 and 8.1, `app/redirect.py`'s docstring): *`app/redirect.py`
is the one listener outside the gate and the guard: it holds no data and answers 301 to the manager's
own HTTPS origin after `host_allowed`, 400 for a refused Host, 405 for any method but GET and HEAD,
closes a socket 1008, and nothing else.* At the release step the lead also adds the new security
files (`app/accounts.py`, `app/sessions.py`, `app/origin.py`, `app/headers.py`, `app/recover.py`,
`app/redirect.py`, `app/probe.py`) to `.claude/rules/routing-privileged-paths.md` once they exist
(`test_path_globs_match_a_repository_file` refuses a glob without a file), and a row "Sign-on,
sessions, TLS" to the CLAUDE.md routing table.

## 15. The `next` parameter

The gate builds `next` from the request's own path and query (6.4). `login.js` (UI.md) accepts `next`
only when it matches `^/(?![/\\])[^\s]*$` (one leading slash, not `//` or `/\`, no whitespace) and
does not start with `/login` or `/setup`; otherwise it goes to `/`. The server never redirects to
`next` itself (the sign-in answer is JSON; the page navigates), so an open redirect would have to pass
the page's rule. The hash never reaches the server, so `loginNext` appends `location.hash` to the safe
`next` when that `next` has no `#`, through the same character checks: a bookmarked lab address
(`/#lab=…&view=devices`) is sent to `/login?next=%2F#lab=…` by the browser and, after sign-in, lands on
its lab, tab and device (REVIEW U7). `test_login_ui.js` asserts the rule with `//evil.example`,
`/\evil.example`, `https://evil.example`, `javascript:`, `/login?next=/login` and the hash case.

## 16. Build slices and the contract between them

The slices, their builders, their files and their order are [BUILD.md](BUILD.md) section 2, owned by
the lead; this section fixes only what one slice provides and another uses. Every name below is a
contract: a builder who needs to change one stops and reports it to the lead instead of changing it.

### 16.1 Objects on `app.state`

**`app.state.sessions`**, a `Sessions` object from `app/sessions.py`, built in `create_app` right after
the `Store` and loaded from the state before any route is installed (5.5). Its `lock` is a
`threading.Lock`, acquired after `store.lock` when both are needed and never held across I/O.

| Member | Signature → return | Behaviour |
|---|---|---|
| `create(record, source)` | `(session_id: str, session: dict)` | Mints `secrets.token_urlsafe(32)`; evicts per 5.2 (audits `session.ended`, `evicted`); copies `password_changed` from the record; the record shape is 5.2. |
| `resolve(session_id)` | `dict \| None` | The session with its `id` added, or `None` after deleting an expired one (queues `session.expired` once, with `idle` or `absolute`) or one whose user is gone, disabled or re-stamped in the index (queues `session.ended` with the reason). No I/O under the lock; the queued entries are written by `sweep`. |
| `touch(session_id)` | `None` | Sets `last_seen` to now under the sessions lock; nothing else (the cookie is never re-sent, 5.3). Called by the gate for an act of the person and by the socket handlers on client input, at most once a minute (11.3). |
| `rotate(session_id, password_changed)` | `str` | The own change (5.5): mints a new id, moves the record to it and writes `password_changed` into the kept record, so its copy equals the stamp the index is about to show; answers the new id. Called inside the route's `store.lock` block after the save and **before** `set_user` and `end_user`. The old id resolves to nothing afterwards. |
| `end(session_id, reason)` | `dict \| None` | Deletes one session and audits it: `signout` for the reason `signout`, `session.ended` with the reason otherwise; runs every `on_end` callback. |
| `end_user(name, reason, keep=None)` | `int` | Ends every session of the user as `end` does, except the one whose id equals `keep`; answers the count. Used by the users routes (no `keep`), the own change (`keep=new_id`, so the rotated current session survives) and the fixture wrapper (13.2). |
| `on_end` | `list[callable(session_id)]` | Callbacks run after a session ends; `node_services` registers the one that drops that session's tickets (11.1). |
| `count(name)` | `int` | Live sessions of a user (`public_user`'s `sessions`). |
| `sweep()` | `None` | Deletes expired sessions, writes the queued audit entries, flushes the closed failure buckets; run in the thread pool by the gate at most once a minute and by every sign-in (5.4). |
| `load_users(users)` | `None` | Replaces the user index from `state['users']` (`create_app`). |
| `set_user(record)` / `drop_user(name)` | `None` | Upserts or removes one index entry; called inside the writing route's `store.lock` block, after the save (5.5). |
| `user(name)` | `UserFacts \| None` | `UserFacts(role, disabled, password_changed, must_change_password)`, a `typing.NamedTuple`. |
| `setup_mode()` | `bool` | The index is empty (9.1). |
| `check(source, name, familiar)` | `int` | `0` when an attempt may proceed, else `retry_after` in seconds, the largest of the refusing levels (8.2); records the throttled bucket itself. |
| `failure(source, name, familiar, reason)` / `success(source, name)` | `None` | The counters of 8.2; `failure` records the failure bucket. |
| `record_failure(event, source_key, actor, reason, *, target='', retry_after=0)` | `None` | One open bucket per `(event, source key, actor, target, reason)` and UTC minute (10.1); `require_admin` calls it with `event='forbidden'`, `reason='admin_required'` and the route template as `target`. |
| `flush_failures(force=False)` / `open_failures()` | `None` / `list[dict]` | Writes the closed buckets (every bucket with `force`, at shutdown and from `assert_not_logged`): the three failure events through `Store.audit_failure`, a `forbidden` bucket through `Store.audit` (10.1); `open_failures()` answers the open buckets as entries for `GET /api/audit`. |
| module functions `source_key(address)`, `source_prefix(address)` | `str` | 8.1. |

**`app.state.accounts`**, an `Accounts` object from `app/accounts.py`, constructed with the `Store` and
the `Sessions`:

| Member | Signature → return | Behaviour |
|---|---|---|
| `verify_password(hash_string, password)` | `bool` | The only caller of `hashlib.scrypt` for a verify: `DUMMY_HASH` when `hash_string` is `None` or does not parse (then always `False`), always `maxmem=64*1024*1024`, `hmac.compare_digest`. Synchronous; called on a `SCRYPT_EXECUTOR` thread only (4.1). |
| `hash_password(password)` | `str` | A new string with the shipped `PARAMS` (4.2). Synchronous, same rule. |
| `async averify(hash_string, password)` / `async ahash(password)` | `bool` / `str` | The awaitables of the `async` routes: `run_in_executor(SCRYPT_EXECUTOR, …)` behind the `pending` counter; raise `accounts.Busy` when `pending >= VERIFY_LIMIT` (4.1). |
| `check_name(name)` | `bool` | The name rule of 3.1. |
| `check_password(name, password)` | `list[str]` | The reason codes of 4.3 (`too_short`, `too_long`, `equals_name`, `common`), empty when acceptable; `message_for(reasons)` joins their sentences (7.4). |
| `public_user(record)` | `dict` | Exactly `name, role, disabled, must_change_password, created, created_by, password_changed, last_signin, sessions`; never `password`, never `known_sources` (3.4). |
| `read_setup_code(root)` | `(mode: str, code: str) \| None` | The file of 9.2: `None` when absent, a symlink, wider than 0600, malformed, or a `recover` file older than 15 min (which it deletes and audits `recover.expired`). |
| `normalize_code(text)` | `str` | `strip`, lowercase, dashes and spaces removed (9.2). |
| constants | | `PARAMS`, `DUMMY_HASH`, `SCRYPT_EXECUTOR`, `VERIFY_LIMIT = 20`, `MESSAGES` (7.4, keyed by `(status, code, route)`), `AUDIT_EVENTS`, `AUDIT_OUTCOMES`, `AUDIT_REASONS` (10.2), `COMMON_PASSWORDS` (4.3), `SETUP_ALPHABET`, `CODE_LENGTH = 24` (9.2). |

**`app.state.store`** (the existing `Store`) gains: `event(action, message, *, level='info', lab_id='',
job_id='', node='', actor='-')` (10.3; `-` is the one value for "nobody"); `events(..., actor='')` (its
`''` means "no filter"); `audit(event, *, actor, source,
outcome, target='', detail='')` → the entry; `audit_failure(event, *, actor, source, outcome, detail)`
→ the entry; `audit_entries(limit, offset, *, event='', actor='', outcome='', since='', address='',
extra=())` → `(entries, total)`; the static `append_audit(root, entry)` that `app.recover` uses
without a `Store`; `reset()` copies `users` (3.3). `store.root/'setup-code'`, `store.root/'audit.jsonl'`
and `store.root/'audit-failures.jsonl'` are the files of 9.2 and 10.1.

### 16.2 The request's user

`request.state.user` (HTTP) and `ws.scope['state']['user']` (WebSocket) are the same object, set by the
gate on every scope it passes through: `None`, or a dict with exactly the keys `name` (`str`), `role`
(`'admin'` or `'operator'`), `session_id` (`str`) and `must_change_password` (`bool`), the role and
the flag taken from the user index at this request (6.2). On an exempt route it may be `None`; on
every other route it is a dict. `require_admin(request) -> dict` (`app/sessions.py`, used as
`Depends(require_admin)`) returns that dict or raises `HTTPException(403, {'code': 'admin_required',
'message': 'Administrators only.'})` after `sessions.record_failure('forbidden', source_key(source),
user['name'], 'admin_required', target=<the route template>)`: summed per actor, route and minute,
written to `audit.jsonl` by the flush (7.1, 10.1).

### 16.3 Constants and functions shared across modules

| Name | Where | Contract |
|---|---|---|
| `EXEMPT` | `app/sessions.py` | A `frozenset` of `(method, path)` pairs, exactly the rows of 6.3; a `HEAD` request matches a `GET` row. `RESTRICTED = EXEMPT \| {('POST', '/api/session/password')}` is the allowlist of a restricted session (6.3). |
| `COOKIE = 'clab_session'`, `IDLE = 43200`, `ABSOLUTE = 604800` | `app/sessions.py` | The cookie of 5.3 and the limits of 5.4. |
| `SessionGate(app, sessions)` | `app/sessions.py` | The pure ASGI class of 6.1; `create_app` adds it with `app.add_middleware(SessionGate, sessions=app.state.sessions)` on the line before `HostCheck`. |
| `scheme(scope)` | `app/origin.py` | `'https'` when `scope['scheme']` is `https` or `wss`, else `'http'`; reads the scope only (5.6). |
| `security_headers(scope, *, status=200, refusal=False)` | `app/headers.py` | A `dict[str, str]`: `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY`, `Cache-Control` (`no-store`, or `public, max-age=31536000, immutable` for `/static/lab-builder/assets/` at status 200, main.py:148), `Content-Security-Policy` (the guard's value by path, main.py:150-152; `default-src 'none'; frame-ancestors 'none'` when `refusal=True`) and `Strict-Transport-Security: max-age=15552000` when `scheme(scope) == 'https'` (6.1). `HostCheck` and the gate encode it into their ASGI header lists (`refusal=True`); the guard does `response.headers.update(security_headers(request.scope, status=response.status_code))`. |
| `host_allowed(host, allowed)`, `configured_hosts(value)` | `app/allowed_hosts.py` (existing) | Used unchanged by `app/redirect.py` (EXPOSURE.md 4.1). |

### 16.4 HTTP, cookies, files and the test fixture

- Routes, bodies and answers: 7.3; every error body with its `code` and `message`: 7.4; the throttle
  answer: 8.3; setup mode's answers: 9.3; the restricted session's answers: 6.4.
- Cookies: `clab_session` with the attributes of 5.3; on sign-out the two clearing cookies, `clab_session`
  (`Path=/`) and `clab_capture_owner` (`Path=/api/capture`), 11.2.
- `<DATA_DIR>/setup-code`: two lines, `mode=setup` or `mode=recover`, then `code=<24 symbols in four
  groups of six>`; mode 0600; written by `create_app` in setup mode (9.2) and by `python -m app.recover`
  (9.5); read per request by `read_setup_code`; deleted in the block that saves the new admin (9.3).
- `python -m app.recover`: prints `Recovery code: <code>` and *Valid for 15 minutes. Create one new
  administrator on the setup page; existing accounts are not changed.*, exits 0; in setup mode prints
  *The manager is in setup mode: use the setup code in <DATA_DIR>/setup-code.* and exits 1; never a URL
  (the script prints it, 9.5). `DATA_DIR` as `create_app` reads it (main.py:51, default `/data`).
- `<DATA_DIR>/audit.jsonl` and `<DATA_DIR>/audit-failures.jsonl`: 10.1; the entry shape
  `{time, event, actor, source, outcome, target, detail}` and the vocabulary: 10.2.
- `events.jsonl` entries gain the key `actor` (10.3) and nothing else.
- `python -m app.probe <name>`: the names and their JSON are EXPOSURE.md 6.1's table; the rule of 6.7
  (no `Store`, no write, no logged value; `state.enc` decrypted read-only at most).
- `tests/session_fixture.py` (13.2, 13.3): `SignedInClient(app, role='admin', name='tester',
  password='correct horse battery staple')`, `complete_setup(client, app, name, password)`,
  `assert_not_logged(app, *secrets, captured='')` (flushes the buckets, then reads the three log files
  with their rotations, the open buckets and `captured`, 13.3); `accounts.PARAMS` may be lowered by a
  test process before `create_app`. The setup code the fixture reads was written by `create_app`, so no test needs the lifespan.
- The fixture wrapper and its `/__fixture/expire` route live in `docs/redesign/tools/fixture_manager.py`
  and call `app.state.sessions.end_user(name, reason)` (13.2); `app/` has no fixture code.

## 17. Contract as delivered to UI.md

UI.md was briefed with the contract in the first column. The second column is the final shape; a row
marked **changed** or **added** differs from the brief.

| Briefed | Final | Status |
|---|---|---|
| `GET /login` serves `login.html`, the only page without a session | As briefed. Its assets are `/static/login.css`, `/static/login.js`, `/static/fabric-mark.svg` only; `style.css` is behind the gate (6.3). | **changed**: no `style.css`; page `<title>` `Sign in`; with a live session `302 /` (**changed (reconciliation)**) |
| | `GET /setup` serves `setup.html` with `/static/setup.js` and `login.css`; 404 unless setup or recovery mode. In setup mode every page redirects here, `/login` too. There is no `GET /api/setup`: the page is a static file, calls `POST /api/setup` only, and shows the recovery sentence when its own address carries `?recover=1` (the URL the recovery command prints, 9.5). | **added**; with a live session `302 /` (**changed (reconciliation)**) |
| `POST /api/session {username,password}` → 200 `{user:{name,role}}` + cookie; 401 generic; 429 with `retry_after` | 200 `{user:{name,role,must_change_password}, expires}`; 401 `{detail:{code:'invalid_credentials', message}}`; 429 `{detail:{code:'throttled', retry_after, message}}` + `Retry-After`, the sentence *Too many sign-in attempts. Try again in {n} s.* (8.3); 503 `{detail:{code:'setup_required', message}}` in setup mode | **changed**: `must_change_password`, `expires`, the 503; `message` and the one 429 sentence **changed (review U11, R5)** |
| `DELETE /api/session` body `{}` | As briefed; the response always clears `clab_session` and `clab_capture_owner` (the latter with `Path=/api/capture`), also when the session is already gone, never 401. Sign-out is two steps: `account.js` first calls `POST /api/capture/sessions/end-all` best effort (11.2) | **changed (reconciliation)**: always 200; **changed (review R10)**: the two-step sign-out and the cookie path |
| `GET /api/session` → user or 401 | 200 `{user:{name,role,must_change_password}, expires}` or 401 `{detail:{code:'signed_out', message}}`; `login.js` asks it once on load, form hidden behind *Checking…*, and goes to `next` on 200 (review R14) | **changed**: fields |
| | `GET /api/state` gains `user:{name, role, must_change_password}` for the session's own user; the `users` table never reaches it | **added (reconciliation)** |
| Every other page and `/api/` route → 401 `{detail:{code:'signed_out'}}`; pages redirect to `/login?next=` | Decided by `Accept` (**changed (reconciliation)**): a `GET`/`HEAD` whose `Accept` includes `text/html` gets `302 /login?next=<path+query>`; every other request gets the 401 JSON with its `message`. A restricted session (`must_change_password`) gets `302 /login?change=1&next=<path+query>` on a page, 403 `{detail:{code:'password_change_required', message}}` on anything else and 1008 `password_change_required` on a socket; it may use only the exempt rows and `POST /api/session/password`. **The forced change is a view of the sign-in page** (`#signin-change`, with **Sign out**), shown when `POST /api/session` or `GET /api/session` answers `must_change_password: true`; `GET /login` serves the page to a restricted session and answers `302 /` only to an unrestricted one; `index.html` has no required-change dialog | **added**: the restricted state; **changed (review R1)**: where the change happens |
| WebSockets refuse without a session | Close 1008 before accept, reason `signed_out`; open terminal, console and capture sockets close 1008 `signed_out` within 5 s of their session ending (11.3); client input on a socket renews the session, nothing else on it does | **changed (reconciliation)**: reason and idle-tick rule; **changed (review R9)**: renewal |
| Admin routes `GET/POST /api/users`, `PATCH/DELETE /api/users/{name}`, `POST /api/users/{name}/password` | As briefed with the bodies and codes of 7.3 and the sentences of 7.4: `exists`, `last_admin`, `self_change`, `weak_password` (with `reasons`), `invalid_name`, `user_not_found`; a new user starts with `must_change_password: true`; `public_user` fields of 3.4 including `sessions` and `last_signin`; `POST /api/users/{own name}/password` is `409 self_change` with *Use Manager ▾ › Change password… for your own account.* and the own row's **Reset password…** is disabled with that caption | **changed**: codes and fields made exact; `last_signin` **changed (reconciliation)**; the own-row reset **changed (review R12)** |
| `POST /api/session/password` (own change) | `{current, password}`; no option or checkbox: the other sessions always end; the cookie is rotated in the response; 401 `invalid_credentials` carries *The current password is not right.* | **changed**: `current` required; no checkbox (reconciliation) |
| `GET /api/audit` (admin) | `?limit&offset&event&actor&outcome&since` → `{entries, total}`, newest first; entry fields of 10.1; operators get 403 `{detail:{code:'admin_required', message:'Administrators only.'}}` (every `require_admin` refusal carries that message). Filters `limit offset event actor outcome since address`, `limit` at most 500, row field `source`. The entries come from `audit.jsonl`, `audit-failures.jsonl` (failures summed per source key and minute, `detail` `<reason> count=<n>`) and the open buckets; the vocabulary is the one table of 10.2 (`outcome` is `ok`, `failed` or `throttled`; `users.js`'s label maps name exactly those codes); the actor of a failed or throttled attempt is `-` unless the submitted name is an existing record's | **changed (reconciliation)**: `address` filter, `message`; **changed (review R2, R3, R8)**: the actor rule, the one vocabulary, the second file |
| First-run bootstrap with a one-time setup code | `POST /api/setup {code, username, password}` → like a sign-in; 401 `{detail:{code:'invalid_code', message}}` with the sentence that names `sudo cat /srv/containerlab-node-manager/data/setup-code`; the code is matched after `strip`, lowercase, dashes and spaces removed; 404 `setup_closed` when unavailable; 409 `exists` in recovery mode (never overwrites); 422 with `message`; 429 | **changed**: made exact; **changed (review R11, U13)**: `409 exists`, the normalisation, the sentence |
| | `GET /api/health` → `{ready:true}`, no session; pages never call it | **added** (for EXPOSURE.md) |
| | The `next` rule of section 15 is `login.js`'s to enforce; `loginNext` appends `location.hash` (review U7) | **added** |
| | Capture routes need the manager session and the owner cookie; expiry does not end the capture container, sign-out does (11.2) | **added (reconciliation)**; **changed (review R10)** |
| | `/api/logs` entries gain `actor` and no `source`; the Audit page is a different log (`audit.jsonl` and `audit-failures.jsonl`) | **added**; **changed (review R22b)** |
| | **Every 4xx and 503 body of the sign-on code carries `message`** (7.4), the gate's own 401, 403 and 503 included; the pages show `detail.message` and keep a sentence of their own only for a network failure | **added (review U11)** |

On the `/setup` row: the page is a static file and cannot know the mode. Final ruling: `setup.html`
has one heading, "Create the first administrator"; its script reads `?recover=1` from its own address
(set by the recovery command's printed URL, 9.5) and then shows the heading *Recovery: create one new
administrator* with its lead (review R11); the server's 404 on `GET /setup` is rendered by the browser
as "not found", which is correct outside the two modes.

## 18. Decisions that differ from the prompt

| Prompt | Decision | Why |
|---|---|---|
| Sessions "stored in memory with the record's hash persisted?" | In memory only, nothing persisted | 5.1: no session secret on disk, no write amplification from the 4 s poll, one process by compose. |
| `Secure` "when the request scheme is https or the env `UI_TLS=1`" | Through one function `origin.scheme(scope)` that the guard and both sockets must also use. `UI_TLS` was later dropped (RECONCILIATION 4, E-Q1): the scope alone decides, because uvicorn terminates TLS itself | 5.6: a TLS edge in front of the manager breaks the guard and both sockets, not only the cookie. |
| Login assets "`/static/style.css`, `/static/login.js`, `/static/login.css`?" | `login.css`, `login.js`, `setup.js`, the favicon; not `style.css` | 6.3: `style.css` names every feature of the product. |
| Health route "a version-less `{ready:true}`" | `{ready:true}`, and the installer's version check moves to `docker exec` | 6.7. |
| "extend the guard's `api.request` event with `actor` and `source`? or keep events.jsonl as is" | Extend `Store.event` with `actor`; security events in a separate `audit.jsonl` | 10.3: one operational log for operators, one security log for admins, the second survives a reset. |
| Per-name throttling with the same exponential schedule | Three levels (8.2): per source-and-name pair exponential to 15 min, per source a 100-failure window then exponential to 15 min, per name a token bucket that only unfamiliar sources spend (first draft: per source exponential, per name fixed 30 s; replaced by REVIEW R5 and R6) | 8.4: an exponential per-name schedule would let a botnet lock the admin out for 15 min at a time; a fixed per-name delay let a botnet hold a name at one failure every 30 s; a per-address key made a classroom NAT one source. |
| `GET /api/setup` implied by "the login page needs to know whether to show setup" | No such route; the gate redirects to `/setup` in setup mode and `/setup` is 404 otherwise | 9.3, 9.4: one fewer unauthenticated route. |
| Recovery "writes a new setup code allowing the creation of ONE more admin" | Same, with a 15 min validity and a `mode=recover` file the manager reads per request | 9.5: no in-memory code, so a second process can create it. |
| "`public_*` keeps the hash out of `/api/state`" | No stripping needed: `users` is a top-level key `/api/state` never copies; a test pins it | 3.4. |
| `must_change_password` named but not specified | A restricted session that can only change its password or sign out, and does so on the sign-in page (`/login?change=1`), never in a dialog of `index.html` | 6.2 step 6, 6.3, 17; REVIEW R1 (a live session never becomes restricted, and a restricted one cannot read `/api/state`, which the dialog needed). |
| `git_binding` owner, path, push_url "strip for operators?" | Not stripped | 19: shared labs (D2) make operators the people who place a lab in a folder; `save-drawers.js:418-419` shows these fields to them; the VM account name is not an asset the threat model protects from a signed-in user. |
| Sliding renewal on every request | Only an act of the person: a non-`GET`/`HEAD` request, a page navigation, socket input; no `GET /api/...` at all (the first draft excepted only `/api/state` and `/api/session`; REVIEW R9) | 5.4: the poll would make the idle timeout meaningless, and so would the Topology tab's timers, an open drawer or a capture viewer. |

## 19. Rulings that bind the build

1. `HostCheck` stays the outermost layer; `SessionGate` is added on the line before it and nowhere
   else (6.1).
2. The gate is a pure ASGI class, not `@app.middleware('http')`: it must see WebSocket scopes.
3. `EXEMPT` is one constant and the only place that names an unauthenticated path. A route added
   without a classification fails `test_session.py`.
4. `verify_password` and `hash_password` are the only callers of `hashlib.scrypt`; they always pass
   `maxmem`; every call runs on `SCRYPT_EXECUTOR` (four threads, never the shared pool); the sign-in,
   setup and own-password routes are `async` and refuse the 21st queued verify with `429 throttled`;
   `DUMMY_HASH` is verified for every name that cannot sign in (REVIEW R7).
5. No log, event, audit entry, exception message or HTTP response contains a password, a code, a
   session id, a cookie value or a hash string; the container log never carries the setup code; the
   actor of a failed or throttled attempt is `-` unless the submitted name is an existing record's;
   `events.jsonl` carries no source address. `assert_not_logged` (13.3: the three log files with their
   rotations, the open failure buckets after a forced flush, and the captured container log) runs in
   every new test file (REVIEW R2, R22).
6. The session table, the three throttle levels and the open failure buckets are bounded (5.2, 8.2,
   10.1); the sweep has no thread.
7. `Store.reset` copies `users`; `audit.jsonl` and `audit-failures.jsonl`, with their rotations, are
   never in either reset move list (store.py:81, :102) and are never moved, deleted or truncated by the
   manager except by their own rotation (3.3, 10.1).
8. `POST /api/session` always mints a new id; `POST /api/session/password` rotates it with
   `rotate(session_id, password_changed)` before `set_user`, so the current session survives the own
   change (5.5); the role is read from the user index on every request (5.5), never from the record.
9. The ticket tuple carries the session id and the socket compares it; the Origin checks of both
   sockets stay.
10. `scope['client'][0]` is the source everywhere; no `X-Forwarded-*` header is read by any new code.
11. The gate's refusals carry the fixed security headers plus `Cache-Control: no-store`, all from the one
    function `security_headers(scope, *, status=200, refusal=False)` in `app/headers.py`, which
    `HostCheck`, the gate and the guard also use (it adds HSTS when `scheme(scope) == 'https'`); every
    refusal body of the gate and of the sign-on routes carries a `message` (7.4).
12. `create_app` gains no test-only argument and `app/` contains no fixture code, not even behind an
    environment variable; tests sign in through `/api/setup` and `/api/session`, and the browser
    fixture's wrapper and `/__fixture/expire` live in `docs/redesign/tools/fixture_manager.py` (REVIEW
    R15, R21).
13. `runner.job_environment` (runner.py:152) keeps passing `os.environ` to Ansible; therefore
    **no secret of this design is placed in the environment**: the setup code is a file, sessions are
    memory. A review of EXPOSURE.md's environment keys applies the same rule.
14. The guard's `api.request` event and every security event name the actor by user name, never by
    session id.
15. `/setup` and `POST /api/setup` answer 404 whenever `<DATA_DIR>/setup-code` is absent; the file is
    deleted in the same locked block that saves the new admin; `POST /api/setup` never overwrites a
    record (`409 exists`); the file is written by `create_app`, not by the lifespan.
16. The gate takes no store lock and does no I/O; the user index of `Sessions` is the gate's only source
    for a user's role, state and stamp, refreshed by every route that writes a user record inside that
    route's `store.lock` block after the save; **`store.lock` is acquired before the sessions lock, never
    the reverse, and the sessions lock is never held across I/O** (REVIEW R4).
17. No `GET /api/...` request renews a session; renewal is `sessions.touch` on a non-`GET`/`HEAD`
    request, a page navigation or socket input only (REVIEW R9).
18. A gate refusal is logged nowhere; `POST /api/session` and `POST /api/setup` write no `api.request`
    event; `signin.failed`, `signin.throttled` and `setup.failed` go to `audit-failures.jsonl`, summed
    per source key and minute, and never to `audit.jsonl` (REVIEW R8).
19. The restricted allowlist is exactly `RESTRICTED` (the exempt rows and `POST /api/session/password`).
    `EXEMPT` and `RESTRICTED` are matched against the exact `scope['path']` string the router receives,
    with **no normalisation** (no `normpath`, no case folding, no slash folding, no trailing-slash
    tolerance): any other spelling is not in the table and is refused, so the gate and the router never
    see different paths (6.3). A live session never becomes restricted (REVIEW R1).
20. A throttle decision is made before any hashing, from the three levels of 8.2 and the executor bound,
    never from the address alone; a success clears only its own pair and its own L2 records (REVIEW R5, R6).
21. `DELETE /api/session` always clears `clab_capture_owner` with `Path=/api/capture` (REVIEW R10).

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
   `docker exec … cat` (never through `docker logs`: the log line names the file, not the code, 9.2).
   The docker group is root on a VM in any case. Check that the file is deleted on success, that a
   15 min old `mode=recover` file is refused, and that the normalisation of 9.2 cannot make two
   different codes equal (it removes only dashes, spaces and case from an alphabet that has neither).
5. **The 4 s poll after expiry.** `refresh()` swallows poll errors (app.js:576); UI.md's 401 handling
   must redirect. Until it does, an expired tab polls a 401 every 4 s: harmless on the server (no hash,
   no log line per poll: the gate queues `session.expired` once, the sweep writes it, and every later
   poll with the dead cookie is refused and logged nowhere, 6.4).
6. **The sockets' Origin check now redundant?** No (6.5). Check that removing it would still fail a
   test (`test_app.py:348-371` keep the Origin assertions).
7. **The `git_binding` fields in `/api/state`** (`owner`, `path`, `push_url`, host_git.py:154, 421; main.py:174
   copies `git_binding`): shown to operators by design (18). Attack the premise: is a VM account name
   plus a checkout path useful to A2 with an operator session? They already have a terminal on every
   device and the Git save surface.
8. **`runner.py:152` passes the environment to Ansible.** Ruling 13: nothing of this design is in the
   environment. Check EXPOSURE.md's keys against the same rule (a TLS key path is
   fine; a TLS key is not).
9. **Memory growth.** 512 sessions × a small dict; three throttle levels × 10 000 entries, an L2 window
   of at most 200 records per source, at most 10 000 open failure buckets; the ticket dictionary
   unchanged at 32. Attack the eviction order: can an attacker evict a legitimate admin's session by
   flooding sign-ins? Only with valid credentials (a session needs a success); failures never create
   sessions. Can they evict throttle entries to escape their own delay? The eviction is oldest-first by
   last activity; the attacker's own entries are the newest. Can 10 000 spoofed sources flush the open
   buckets of a real attack before their minute closes? Each flush writes the bucket, it does not drop
   it. Check all three.
10. **The health route as a fingerprint.** `{ready:true}` with no server header. Compare with what a
    302 from `/` to `/login` already reveals (a sign-in page with the product's name in its title, by
    UI.md): the page is the larger fingerprint and is unavoidable. Decided (RECONCILIATION 2): the page
    `<title>` is `Sign in`; the brand mark and product name appear on the page itself so a student
    recognises where they are, and the title is what a scanner indexes.
11. **`SameSite=Strict` and the external link.** A student who follows a link from a course page lands on
    `/login`, which immediately redirects to `next` because `GET /api/session` is same-site. Check that
    this does not loop and that a signed-out student sees the form.
12. **Setup mode on an upgrade.** Between the upgrade's restart and the operator's setup, the manager
    answers nothing but `/setup`, which needs the code from the VM. Attack: is there any way for A1 to
    reach `POST /api/setup` usefully? 119 bits, throttled by the three levels of 8.2 (in practice L2:
    every setup name is unfamiliar and new, so L3 spends a token per failure too), no enumeration.
    Attack the file-read path for a symlink or a mode widening on the bind mount.
13. **Two admins editing users at once.** Every users route reads and writes under `store.lock`; the
    last-admin rule is evaluated inside the same block. Check `PATCH` on two admins each demoting the
    other: the second one is refused.
14. **The restricted session.** A user with `must_change_password` holds a session that can only change
    the password or sign out, on the sign-in page. Check that the gate's allowlist for it cannot be
    widened by a path trick (`/api/session/password/../../state`, `/API/state`, a trailing slash): the
    gate matches the exact `scope['path']` string and never normalises (6.3), so each of those is simply
    not in the table; the test tries those spellings, and the reverse trick too (a `..` spelling that
    would normalise *to* an exempt path must still need a session).
    Check the loop the first draft had (REVIEW R1): `GET /login` must serve the page to a restricted
    session, `login.js` must reach the change view without `/api/state`, and **Sign out** must work from
    it; follow every redirect from a fresh user's first sign-in to a final 200.
15. **The audit log's own integrity.** 0600, append-only by convention, rotated by size. An admin with
    a session reads it; nobody writes to it through HTTP. Attack whether a 4000-character `detail`
    could be injected through a user name (the name rule caps it at 32 and the alphabet excludes
    everything but `[a-z0-9._-]`), and whether a submitted name can reach either file at all (only when
    it equals an existing record's name, 10.2; the test types the password as the username).
16. **The user index against the state.** The index is refreshed inside the writing route's `store.lock`
    block after the save, so there is no window in which a disabled user's session still resolves.
    Attack a route that writes `state['users']` by another pattern (a future migration, `finish_reset`
    at startup: `load_users` runs after it in `create_app`), and the `/api/manager/reset` path, which
    keeps `users` and must leave the index as it is.
17. **`known_sources` as a record of where a person has been.** Eight `/24` or `/64` prefixes per user,
    private, never in `public_user`, never in `/api/state`, never logged. Attack whether an admin can read
    them (no route returns them), whether they leak through timing (L3 is consulted only after L1 and L2
    and never hashes), and whether an attacker on a familiar prefix gains anything (they skip L3 only;
    L1 and L2 still apply to them).
18. **L3 and the traveller.** A person on a new network while their name is under a distributed attack
    waits for tokens that the attacker may keep spending (8.4, the accepted remainder). Attack the
    alternative: without L3 the attacker gets 10 free guesses per fresh `/24` forever; with a per-name
    delay that familiar sources also meet the attacker locks the person out of their own network, which
    is what REVIEW R5 refused. Check that the bucket refills at one token per 30 s and that a familiar
    source is never refused by L3 even with an empty bucket.
19. **The executor bound as a denial of service.** Twenty queued verifies make the 21st attempt a `429
    busy` for everyone. Each attempt costs the attacker a connection and counts against L1 and L2, and
    L2 delays a source after 100 failures; from a hundred sources an attacker can still keep the
    executor busy, at the price of one `signin.throttled` bucket per source and minute in
    `audit-failures.jsonl`. Attack whether anything cheaper than a full attempt reaches the executor (a
    throttled attempt never does; a `busy` refusal never does; the own change needs a session).
20. **The failure buckets.** A bucket is written when its minute has passed, by the next failure, the
    sweep, `GET /api/audit` or shutdown. Attack the loss case: a crash loses the open buckets (at most
    one minute of failures, never a line of `audit.jsonl`, which is written synchronously). Attack the
    merge: `audit_entries` must order the two files and the open buckets by `time` with `total` counting
    all three; a reader comparing counts between two files must find the summed `count=<n>`.
21. **The two-step sign-out.** Step 1 (`end-all`) can fail or be skipped; step 2 always clears the
    owner cookie. Attack the inheritance case directly: sign in, start a capture, fail step 1 (stop
    the capture service), sign out, sign in as another user in the same browser: `GET
    /api/capture/sessions` must answer an empty list (a new owner cookie), and the old session must be
    gone within the capture service's own limit. Then attack the named remainder of 11.2: let the
    first session *expire* instead (or sign in as a second name over the live session) and sign in as
    another user in the same browser: that person **does** inherit the desktop sessions, because only
    sign-out separates two people in one browser. Check that the design says so and that the sign-out
    menu item carries the sentence; the lead decides whether the remainder is accepted or whether
    `POST /api/session` should also clear `clab_capture_owner` when it replaces a live session of
    another name (which still leaves the expiry case open).
