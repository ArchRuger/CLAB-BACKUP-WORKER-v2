# Sign-on build: slices, ownership and contracts

The lead's build plan for the sign-on stream. It replaces the slice table of `DESIGN.md` 16 after the
design review ([REVIEW.md](REVIEW.md)); the behaviour every slice builds is the one
[DESIGN.md](DESIGN.md), [UI.md](UI.md) and [EXPOSURE.md](EXPOSURE.md) state, as amended with the
review's answers. Written 2026-11-01 by the lead of the second session. The base commit of every slice
worktree is named in section 5 when the worktrees are made.

## 1. Every worker

- **Your worktree.** The lead made one Git worktree per slice under `.claude/worktrees/<slice>` on the
  branch `signon/<slice>`, from the base commit. `cd` into it first and work only there; every path in
  this file is relative to it. Commit your work there with clear messages, as often as you like. Never
  push, never switch branches, never write to the main checkout at `/home/user/CLAB-BACKUP-WORKER-v2`.
- **Python.** A worktree has no virtual environment of its own. From `<worktree>/clab-backup-ui` run
  `PATH="/home/user/CLAB-BACKUP-WORKER-v2/clab-backup-ui/.venv/bin:$PATH" python -m unittest discover -s tests -t tests -p <file>`.
  The tests import `app` from the working directory, so the worktree's code is what runs. The deploy
  tests that CI runs before any virtual environment exists run with the system `python3` and stay
  standard-library only. Node is 22: `node --test tests/<file>.js`.
- **Only your files.** Section 2 is the ownership. Edit no file another slice owns or no slice owns;
  if you need such a change, stop and put it in your hand-back as a request to the lead. Where two
  slices meet, build against section 3 exactly and guard optional globals with `typeof … === 'function'`.
- **Test first.** Write the failing test of a behaviour before its code (`test-driven-development`).
  Every behavioural claim of an existing test stays: a pinned label or count is rewritten with its
  reason, never deleted, and an assertion is never weakened to get green.
- **Known red that is not yours:** `test_release_consistency.py` `CiListTests` fails for each new test
  file until the lead adds it to `.github/workflows/release-check.yml`, and `verify-release.py` does not
  yet know the new pages. Every other failure in your worktree is yours.
- **Never** point a test or a `Store` at `/srv/containerlab-node-manager/data`. Never print, log or
  return a password, a setup code, a session id, a cookie value or a hash string, in code or in tests'
  output.
- **Hand back** (your final answer): the changed paths; your commits; every test command you ran with
  its exit code; the contracts of section 3 that you provide, exactly as built (names, signatures,
  bodies); open gaps; requests to the lead.

## 2. Slices and ownership

Paths are relative to the repository root; `app/` and `tests/` mean `clab-backup-ui/app/` and
`clab-backup-ui/tests/`.

| Slice | Builder | Owns | Worktree, order |
|---|---|---|---|
| **S1a** accounts and store | `clab-fable-specialist` | `app/store.py`, `app/accounts.py` (new; no HTTP routes yet), `app/recover.py` (new), `app/runner.py` (`secrets_to_hide` only), `tests/test_password.py`, `tests/test_users.py`, `tests/test_audit.py`, `tests/test_setup.py` (new; their unit-level parts), `tests/test_manager_reset.py` | `core`, first |
| **S1b** gate, sessions and wiring | `clab-fable-specialist` | `app/sessions.py`, `app/origin.py`, `app/headers.py` (new), `app/main.py`, `app/allowed_hosts.py`, `app/discovery.py` (the admin dependency of `PUT /api/host` only), `app/diagnostics.py` (the admin dependency of the debug routes only), the HTTP routes of `app/accounts.py` (its `install(app)`), `tests/session_fixture.py`, `tests/test_session.py`, `tests/test_signon_load.py` (new), the route-level parts of the four test files of S1a, and the migration of every `TestClient(` site in the 23 existing test files | `core`, after S1a |
| **S2** sockets and capture | `clab-opus-specialist` | `app/node_services.py`, `app/capture_sessions.py`, `tests/test_ticket_binding.py`, `tests/test_socket_session.py` (new), the socket assertions of `test_nodes.py`, `test_capture_sessions.py`, `test_capture_proxy.py`, `test_capture.py` | `core`, after S1b |
| **S3** probe and redirect | `clab-opus-specialist` | `app/probe.py`, `app/redirect.py`, `tests/test_probe.py`, `tests/test_redirect.py` (new) | `probe` |
| **S4** TLS and container | `clab-fable-specialist` | `deploy/setup-tls.sh`, `deploy/setup_tls.py` (new), `clab-backup-ui/Dockerfile`, `clab-backup-ui/compose.yml`, `deploy/compose.image.yml`, `deploy/start-manager.sh`, `deploy/recreate-manager.sh`, `deploy/verify-release.py` (the `verify_docs` rule only), `tests/test_setup_tls.py` (new), `tests/test_release_consistency.py` | `tls` |
| **S5a** host doors | `clab-opus-specialist` | `deploy/setup-firewall.sh`, `deploy/setup-ssh-hardening.sh`, `deploy/manager-recover-admin.sh` (new), `tests/test_setup_firewall.py`, `tests/test_setup_ssh_hardening.py`, `tests/test_manager_recover_admin.py` (new) | `doors` |
| **S5b** installer | `clab-devops-engineer` | `deploy/install-manager.py`, `deploy/install-prerequisites.sh`, `deploy/installer_tui/**`, `tests/test_install_manager.py`, `tests/test_install_tui_*.py` | `installer` |
| **S6** health check | `clab-devops-engineer` | `deploy/check_install.py`, `deploy/check_host.py`, `tests/test_check_install.py`, `tests/test_check_host.py` | `health` |
| **S7** exposed pages | `clab-ui-builder` | `app/static/{login.html,login.css,login.js,setup.html,setup.js}` (new), `tests/test_login_ui.js`, `tests/test_setup_ui.js` (new) | `pages` |
| **S8** the app's session | `clab-ui-builder` | `app/static/{session.js,account.js}` (new), `app/static/{shell.js,app.js,index.html,style.css,status.js,management.js,home.js}`, `tests/test_session_ui.js`, `tests/test_account_ui.js` (new), `tests/{test_page_load_ui,test_shell_ui,test_status_ui,test_home_ui,test_vm_password_ui,test_readiness_ui,test_download_ui,test_telemetry_retired_ui}.js` | `appsession` |
| **S9** people page | `clab-ui-builder` | `app/static/{users.html,users.js}` (new), `tests/test_users_ui.js` (new) | `people` |
| **S10a** feature scripts | `clab-ui-builder` | `app/static/{operations,network-design,load,restore,git-progress,device-diagnostics,map-tools,device-impairments,workspace}.js`, `app/static/workspace.html`, `tests/{test_operations_ui,test_network_design_ui,test_load_ui,test_restore_ui,test_git_progress_ui,test_device_diagnostics_ui,test_map_tools_ui,test_device_impairments_ui}.js` | `features` |
| **S10b** standalone pages | `clab-ui-builder` | `app/static/{debug,lab-builder-page,map-editor-page,terminal,capture-session}.js`, `app/static/{debug,lab-builder,map-editor,terminal,capture-session,capture-setup,vm-connection}.html`, `tests/{test_debug_ui,test_lab_builder_ui,test_lab_builder_check_ui,test_lab_builder_yaml_ui,test_map_editor_ui,test_terminal_ui,test_capture_session_ui,test_topology_ui}.js` | `standalone` |
| **S11** tools and fixture | `clab-ui-qa` with `clab-test-engineer` | `docs/redesign/tools/fixture_manager.py`, `docs/sign-on/tools/**` and `docs/sign-on/TOOLS.md` (new), the live tools of REVIEW R15 | after S1, S7, S8 are integrated |
| **S12** documentation | `docs-auditor` (two, split by file) | the living guides that `EXPOSURE.md` 8.1 and `DESIGN.md` 12 name | after the code is integrated |
| **Lead** | the lead | `.github/workflows/release-check.yml`, `deploy/verify-release.py` FIELDS, `deploy/set-release.py`, `CLAUDE.md`, `.claude/**`, `docs/redesign/DESIGN-SPEC-ADDENDUM.md`, the three release records, `docs/sign-on/{PICKUP,BUILD,REVIEW}.md` | integration |

## 3. Contracts between slices

The exact names are those of `DESIGN.md` 16 ("Names shared between slices"), `UI.md` 3.2 (the
`session.js` globals) and `EXPOSURE.md` 6.1 (the probe subcommands) and 9 (the interfaces). The
summary below is the lead's index into them; where it and those sections differ, those sections win
and the lead corrects this file.

| Contract | Provider | Users |
|---|---|---|
| `request.state.user` and `ws.scope['state']['user']`: `None` or `{name, role, session_id, must_change_password}` | S1b | S1b routes, S2 |
| `app.state.sessions` (`resolve`, `touch`, `end`, `end_user`, the user index, the throttle) | S1b | S2, S11 |
| `app.state.accounts`, `public_user`, the policy and its sentences | S1a | S1b |
| `Store.audit` and the failures file, `Store.event(actor=…)` | S1a | S1b, S2 |
| `require_admin`, `EXEMPT`, `origin.scheme(scope)`, the security headers of `app/headers.py` | S1b | S2, S3 |
| Error bodies `{detail:{code, message, …}}` of every sign-on route and of the gate | S1b | S7, S8, S9 |
| `/api/state` `user:{name, role, must_change_password}` | S1b | S8, S9 |
| The setup-code file `<DATA_DIR>/setup-code` (`mode=setup` or `mode=recover`, `code=…`, 0600), written by `create_app` | S1a, S1b | S5a, S5b, S6, S11 |
| `python -m app.recover` output | S1a | S5a |
| `python -m app.probe <name>` and its one-line JSON | S3 | S6 |
| TLS files, modes and `setup-tls.sh` options | S4 | S5b, S6 |
| `setup-firewall.sh`, `setup-ssh-hardening.sh`, `manager-recover-admin.sh` options and output | S5a | S5b, S6 |
| `session.js` globals, `signedOut()`, `sessionOnResume(fn)`, the `sessionEnded:true` error marker | S8 | S9, S10a, S10b |
| `diagnosticsAdvice(role)` in `status.js` | S8 | S10a, S10b |

## 4. The slices

Each slice reads section 1, its row of section 2, the design sections named here, and the REVIEW
answers named here. The acceptance checks are what the independent verification attacks.

### S1a accounts and store

Design: DESIGN 3 (the record, `known_sources`, `last_signin`, uniqueness, the last-admin and
self-change rules, Start fresh), 4 (scrypt, the hash string, verify, rehash, `DUMMY_HASH`, the policy),
9.2 and 9.5 (the setup-code file and its normalisation, `app.recover`), 10 (the audit files, the one
vocabulary, the actors, `Store.event(actor=…)`), 12.2 (`ui.token` out of the read path). REVIEW R2,
R3, R5 (the record side of `known_sources`), R8, R11 (no overwrite), R12, R22, U11, U13.

Acceptance: the hash string and every malformed case of DESIGN 4.2; `maxmem` on every call and one
verify under 500 ms with the shipped parameters; exactly one scrypt per sign-in attempt whatever the
name (a patched counter); every policy reason code with its sentence; the name rule; no record is ever
overwritten; the last-admin and self-change rules under `store.lock`; `Store.reset` keeps `users` and
both audit files, and a journal of an older release applies; the audit entry fields, the failures file
with its own rotation, per-minute summing, the actor `-` for an unknown name; `events.jsonl` gains
`actor` and never `source`; `app.recover` refuses in setup mode, writes a 0600 `mode=recover` file,
prints the code and its validity and nothing else, and never opens `state.enc` for writing; no secret in
any log (`assert_not_logged`).

### S1b gate, sessions and wiring

Design: DESIGN 5 (sessions, the cookie, renewal only on acts, sign-out everywhere, the user index and
the lock order), 6 (the gate, `EXEMPT`, every refusal including the restricted session, the bodies, the
health route), 7 (authorization and every route), 8 (the L1, L2 and L3 throttle, the executor), 9.3 and
9.4 (setup mode and the setup route, recovery's `409 exists`), 10.3 (the guard's actor), 13 (the
fixture, the 52 sites, the `HostCheckTests` cookies), 19. REVIEW R1, R4, R5, R6, R7, R8, R9, R10 (the
`DELETE /api/session` response clears `clab_capture_owner` with `Path=/api/capture`), R11, R12, R14
(`GET /login` with a session), R21 (no fixture code in `app/`), R22, U11.

`login.html` and `setup.html` are S7's: in this worktree they do not exist, so a test of a 200 from
`GET /login` or `GET /setup` is skipped while the file is absent and every redirect and refusal test runs.
The setup-code file is written by `create_app`, not by the lifespan, because the tests build
`TestClient` without running the lifespan.

Acceptance: the route walk of `test_session.py` (every route and both sockets classified; without a
session each answers by DESIGN 6.4 except the `EXEMPT` rows); the restricted session reaches the change
and nothing else, with no redirect loop (follow every redirect to a final 200); the cookie attributes
under `http` and `https`; idle and absolute expiry on a patched monotonic clock; no `GET /api/…` renews;
sign-out everywhere on disable, delete, admin reset and own change; the throttle sequences of L1, L2 and
L3 and the 30-users-behind-one-address case; one scrypt per attempt and never on a throttled one; 50
concurrent sign-ins while `GET /api/state` still answers; the gate takes no store lock (a test that holds
`store.lock` in another thread while a request passes the gate); session fixation; `/api/state` holds
neither `users` nor `scrypt$`; no `api.request` event for the sign-in and setup routes; the guard's actor
`-` without a session; every existing test passes through `SignedInClient` with its claim intact.

### S2 sockets and capture

Design: DESIGN 5.6 (the scheme rule for both sockets and the capture cookie), 11 (the ticket bound to
the session, the capture cookie, sockets that close when their session ends, `touch` on socket input).
REVIEW R9, R10.

Acceptance: a ticket minted by session A is refused on a socket of session B and outlives neither its
30 s nor its session; terminal, console and capture sockets close 1008 `signed_out` within 5 s of the
session's end; socket input renews the session at most once a minute; both Origin checks stay and still
refuse a foreign origin; the capture cookie's `secure` follows `origin.scheme`.

### S3 probe and redirect

Design: EXPOSURE 4.1 (the redirect listener; REVIEW R19's sentence; `Location` from `raw_path` and
`query_string`, REVIEW R20) and 6.1 (every probe subcommand, what it reads and the JSON it prints);
DESIGN 6.7. REVIEW R16.

The five probes are `design-engine`, `capture`, `vm-connection`, `browse <path>` and `git-registry`, with
the shared read-only `read_state()` (EXPOSURE 6.1).

Acceptance: the redirect answers 301 to the manager's own HTTPS origin after `host_allowed`, 400 (a refused
Host or a target that is not a path), 405 with `Allow: GET, HEAD`, and a socket close 1008, and nothing else; no per-request log; CR/LF, `%3F` and UTF-8 paths are safe; a probe
never constructs a `Store`, never writes, never prints a secret, and prints exactly its documented JSON
line.

### S4 TLS and container

Design: EXPOSURE 2 (2.4: the manager service gains `UI_PORT` in its environment, so its container log line
can name the port), 3 (with REVIEW R18's certificate names, `--name` and the read-only `--primary`), 4.1 (the
compose service), 5.1, 7.1 (its rows), 7.4 (with REVIEW R17's sentence), 8.2; RECONCILIATION 4 (E-Q1, E-Q5,
E-Q6, E 9.4).

Acceptance: uvicorn serves TLS with the certificate paths and `--no-proxy-headers --no-server-header` in
both compose files and the Dockerfile `CMD`; `UI_TLS` absent from both compose files; the redirect
service; `setup-tls.sh` modes, file owners and modes, the filtered certificate names; `ensure` regenerates
only for a lost or expiring certificate or a missing filtered address; the `verify_docs` rule refuses an
`http://…:8081` manager URL in a living guide and leaves the history files alone.

### S5a host doors

Design: EXPOSURE 5.2 (firewall), 5.4 (SSH hardening), 7.1 (`manager-recover-admin.sh`, which builds the
`https://<address>:<UI_PORT>/setup?recover=1` URL from `.env` as `start-manager.sh` does, REVIEW R11).

Acceptance: the firewall script never locks out the current SSH session's port, never runs `ufw reset`,
adds only its own commented rules and removes only those; the SSH drop-in writes only directives whose
effective value is still the default, validates with `sshd -t`, rolls back on failure; the recovery
script prints the code from `app.recover` and the URL; the tests are standard-library only.

### S5b installer

Design: EXPOSURE 7 (installer changes, the order of a fresh installation with the setup code printed
last, REVIEW U13; prepared images; the upgrade; the full-screen installer's summary stops listing the
`hostname -I` addresses of `vm_addresses()`, REVIEW R18). REVIEW R11, R17, R18, U13.

Acceptance: the installer runs the TLS, firewall and SSH steps in EXPOSURE 7.2's order with their
opt-outs, verifies the manager over HTTPS `/api/health`, prints the address, the fingerprint and, while
setup is open, the setup code read from the file (never persisted); the full-screen installer shows the
same; existing installer tests keep their claims.

### S6 health check

Design: EXPOSURE 6 (every check, its source, the new `Context.probe`, the SKIP table, the test pattern;
REVIEW R16's table; R17's INFO `tls.hsts-scope`). The probes are S3's: build against the JSON lines of
EXPOSURE 6.1 with a mocked `Context.probe`, exactly as the tests mock `ctx.http` today.

Acceptance: every manager HTTP call of `check_install.py` is either `GET /api/health` or replaced by its
probe or an explicit SKIP with the reason, as EXPOSURE 6.1 lists; every exposure check of 6.2 with its
OK, WARN and FAIL; no case of `test_check_install.py` is deleted (each is rewritten to its new source);
`check_install.py` and its tests stay standard-library only.

### S7 exposed pages

Design: UI 1 (the sign-in page: the load-time session check, the change view with Sign out, the
countdown, `next` with the hash), 2 (setup and recovery), 8, 9.1; RECONCILIATION 2 (`login.css`);
DESIGN 15 (the `next` rule). REVIEW R1, R11, R14, U7, U13, U15.

Acceptance: `login.css` names no application selector; neither page links `style.css`; the `next` rule
of DESIGN 15 with every listed attack and the hash; the load check with 200, restricted 200, 401 and a
network failure; the change view's current-password handling after a reload; the countdown announced
once; the setup and recovery wording; every page asset carries `?v=` of `clab-backup-ui/VERSION`; house
style and `esc()`; no inline styles.

### S8 the app's session

Design: UI 3 (the `session.js` contract, the guard in `api()`, `refresh()`, `signedOut()` with the
dialog and save-panel banners, resume), 4 (the account chip and group, the menu reasons, the role-aware
VM dialog, Diagnostics hidden for an operator, `diagnosticsAdvice`), 6 (the voluntary change dialog;
sign-out with the capture `end-all` first), 7, 8, 9.1; `docs/redesign/DESIGN-SPEC-ADDENDUM.md` J1-J4 (the
lead records amendment M). REVIEW R10, R13, U4, U5, U8, U9.

Acceptance: no request after the first 401 from any `api()` caller, and every registered chain resumes
after *Try again*; the banner keeps an open dialog's fields and the save panel's typed text; the account
group and chip by role; `#vm-settings` and `#manager-settings` disabled with *Administrators only* for an
operator; every VM-dialog entry point sends no `PUT /api/host` as an operator; sign-out ends capture
sessions first; `test_page_load_ui.js` loads every script in one context; the listener pins of
`test_shell_ui.js` hold or are rewritten with their reason.

### S9 people page

Design: UI 5 (the People and the Audit cards, the own-row rules including Reset password, the one
vocabulary), 8, 9.1. REVIEW R3, R12.

Acceptance: rows are text (a name `<b>x</b>` renders as text); the last-admin and own-row buttons are
disabled with their sentences; 403 shows `#users-forbidden`; the audit query carries every filter; the
label map covers exactly the backend's event and outcome codes; no CSS change (reuse `style.css` classes;
a needed rule is a request to the lead).

### S10a feature scripts

Design: UI 3.3 (every polling chain: no request while signed out, no retry spent, resume through
`sessionOnResume`), 3.5 (`workspace.js`), 4.4 and 8 (`diagnosticsAdvice` in the strings that say "see
Diagnostics"). REVIEW U5, U8.

Acceptance: per chain, no request after the first 401 and a resume after `sessionRetry()`; the Load and
Git watches check `sessionEnded()` at their start; the operator form of every Diagnostics hint; pinned
labels rewritten, never deleted.

### S10b standalone pages

Design: UI 3.5 (each standalone page and its sentence), 8, 9.1. REVIEW U5.

Acceptance: each page loads `session.js` with `?v=`, guards its request helper, and answers a 401 as
UI 3.5 says (redirect, overlay, toast or status line); the terminal and the capture viewer stop their
heartbeats and keep their Reconnect; `vm-connection.html` has the role-neutral Diagnostics sentence;
CSP and inline-style rules unchanged.

### S11 tools and fixture

Design: REVIEW R15 and R21; UI 9.2; DESIGN 13.2.

Acceptance: `fixture_manager.py` completes setup with fixture credentials, signs requests in by default,
switches with `--signed-out` and `--role operator`, and owns the expire route, with nothing added to
`app/`; the existing Playwright checks that use the fixture run unchanged; `manager_http.py` signs in over
HTTPS with a pinned certificate and never takes a password on the command line; `TOOLS.md` lists every tool
that talks HTTP with its status; `check_signon.py` exercises sign-in, the restricted change, sign-out, the
cross-site link and an operator at 1440, 1280, 760 and 390 px.

## 5. Worktrees and integration

Filled in by the lead when the worktrees are made (base commit, one line per worktree) and as each
slice is integrated (its merge commit and the full-suite result).
