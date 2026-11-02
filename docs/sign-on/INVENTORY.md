# Inventory: what the sign-on design must fit

Read-only facts gathered by scouts on 2026-11-01 against `main` at 1.31.8 (commit `fac28de`), for the
designers and the reviewers. File:line references are to that commit. Nothing here is a decision.

## 1. The manager today

- `create_app(data_dir)` in `app/main.py` builds the `Store` and the services and adds
  `allowed_hosts.HostCheck` last (main.py:513-515) as the outermost ASGI layer.
- The `guard` (main.py:119-156): for `/api/` paths it answers 403 *"Use this manager from its own
  browser page."* when `sec-fetch-site` is `cross-site` or an `Origin` differs from
  `request.base_url`; a mutating method needs `0 < content-length <= 2_500_000` (else 413; pages
  and tests post `{}`); 503 while a reset is pending. It sets the CSP
  `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self';
  frame-ancestors 'none'; base-uri 'none'` (main.py:154-155); inline styles are allowed only on
  `terminal.html`, `capture-session.html`, `lab-builder.html`, `map-editor.html`.
- Pages are static HTML under `app/static`; `/` serves `index.html` (main.py:511-512);
  `/vm-connection-guide` serves `vm-connection.html` (main.py:501-502). There is no template engine.
- `store.py`: one Fernet-encrypted JSON document `state.enc` under `state.key` (mode 0600, created
  with `Fernet.generate_key()`, store.py:18-40), a reentrant lock, `Store.event()` for logs (does not
  scrub). A legacy `ui.token` is still read into `self.token` (store.py:22-23) and is unused for
  access; `test_app.py:46` still sends it as a Bearer header (harmless).
- The only crypto dependency is `cryptography>=43` (requirements.txt:8). No bcrypt, argon2, passlib
  or itsdangerous. Stdlib `secrets`, `hmac`, `hashlib` are used in `capture.py`,
  `capture_service.py`, `capture_sessions.py`; neither `hashlib.scrypt` nor `pbkdf2_hmac` is used
  anywhere yet.
- No lock or hash file for the manager's Python dependencies (the installer TUI has its own hashed
  `deploy/installer_tui/requirements.lock`). The Dockerfile installs `requirements.txt` without
  hashes (Dockerfile:7).

## 2. WebSockets and tickets

- Terminal and console: `POST /api/labs/<lab>/terminal-ticket` (`{name}` or
  `{name, protocol:'console'}`, terminal.js:46) then `new WebSocket(ws(s)://host/api/terminal)`
  (terminal.js:51) with `{"ticket":…}` as the first text message. Server side
  (node_services.py:552-600): single-use, 30 s, at most 32 pending, in memory; the socket handler
  checks `Origin` against the socket URL, waits 5 s for the first message (≤512 bytes).
- Capture viewer: noVNC `RFB` connects to `ws(s)://host/api/capture/sessions/<sid>/websockify`
  (capture-session.js:41), no ticket; ownership is the cookie `clab_capture_owner`
  (`capture_sessions.py:24`, `owner()` 107-113: httponly, samesite=strict), set by the HTTP routes
  and read again by the socket handler (315-324) after an `Origin` check.
- No other `new WebSocket` in the manager scripts.

## 3. The browser side

- Script order on `index.html` lines 3-4 (all `defer`, each `?v=<release>`): status, shell, app,
  preferences, topology-render, topology, home, management, clipboard, operations,
  device-diagnostics, device-impairments, map-tools, diagram-editor, diff-view, git-progress,
  save-header, git-places, save-drawers, load, restore, network-design, capture.
  `tests/test_page_load_ui.js:10` pins the exact tag form `<script src="/static/X.js?v=…" defer></script>`.
- Shell: the header `<header class="topbar">` (index.html:23) is static markup; the Manager menu is
  `span.menu#manager-menu` with `#manager-button` and `div.menu-list#manager-menu-list`
  (index.html:28-57), made live by `initMenu` (shell.js:79-123). The menu footer `.menu-foot`
  (index.html:55) holds `#vm-summary`, `#app-version`, `#supported-release`, `#clab-version`.
  Every `window`/`location`/`history`/`localStorage`/document listener lives in `shell.js`
  (DESIGN-SPEC-ADDENDUM J1).
- Requests: `api(path,options)` (app.js:52-63) does `fetch('/api'+path)` with no extra headers and
  default same-origin credentials; `json(path,method,data)` posts JSON; bodyless posts send `{}`.
  `refresh()` polls `GET /api/state` every 4 s (app.js:576) and swallows poll errors. **Nothing
  handles 401 or 403 today**; status checks exist only for 409/404/412/503.
- Standalone pages with their own fetch helpers (bypass `api()`): workspace.js:6-7, debug.js:7-13,
  lab-builder-page.js:17, map-editor-page.js:13-16, terminal.js:46, capture-session.js:7/28/56/69.
  Non-fetch requests: `window.open('/api/labs/<id>/design/export')` (network-design.js:1654), a
  download `<a href>` (capture-session.js:22), the `/student-guide` link (index.html:48).
- Storage: every stored key belongs to a family in `PREFERENCE_FAMILIES` (shell.js:318-333), pinned
  by `test_shell_ui.js` (~972); keys are listed in the frontend scout's report. No key holds a token
  or session today. `sessionStorage.activeLab` is read once by the router (shell.js:35-36).
- CSS: `style.css` (2760 lines; tokens in `:root` 55-120; buttons 479-515; forms 1277-1330;
  `.banner` 935-975; standalone pages 2285-2321). `debug.html` (12 lines: `body.standalone-workspace`,
  `main.content.debug-page`, `.workspace-back`, `section.debug-card` with a form) is the closest
  template for a standalone page with a form and one script; `debug.js` with `tests/test_debug_ui.js`
  (lines 1-15) is the matching test harness.
- Browser test harnesses: `test_page_load_ui.js` (one `vm` context, every script in order,
  `fetch` resolves `{ok:true,status:200,json:{labs:[],jobs:[],git_jobs:[],platforms:{}}}`),
  `test_shell_ui.js` (tree DOM, `harness({hash,session,local,…})`, runs shell.js only),
  `test_capture_session_ui.js` (`fetch` dispatching on URL suffix), `test_terminal_ui.js` (fake
  `WebSocket` recording `sent`/`closed`).

## 4. Deployment, exposure and the installer

- `clab-backup-ui/compose.yml`: `network_mode: host`, `uvicorn app.main:create_app --factory --host
  ${UI_BIND:-0.0.0.0} --port ${UI_PORT:-8081} --workers 1`; environment `DATA_DIR`,
  `UI_ALLOWED_HOSTS`, `CAPTURE_PROVIDER`, `CAPTURE_EDGESHARK_URL`, `CAPTURE_SESSION_URL`,
  `CAPTURE_SESSION_TOKEN`; `cap_drop: [ALL]`, `no-new-privileges`; bind mount
  `/srv/containerlab-node-manager/data` → `/data`. `deploy/compose.image.yml` mirrors it and
  `test_release_consistency.py:88-99` requires equal environment key sets. The capture stack
  publishes `127.0.0.1:5801` and `127.0.0.1:5001` only (asserted at test_release_consistency:140-148).
- **No HTTPS, TLS, certificate or reverse-proxy configuration exists anywhere** (deploy scripts,
  compose, TUI, app). uvicorn runs without `--ssl-*`, `--proxy-headers`, `--forwarded-allow-ips`.
  `allowed_hosts.py:10` never reads `X-Forwarded-Host`. Health URLs are hard-coded `http://`
  (install-manager.py:100-116 `health_url()`, installer_tui/probes.py:94-108).
- `.env` (`clab-backup-ui/.env`, or `deploy/image.env` for a prepared image; both git-ignored):
  keys `UI_BIND`, `UI_PORT`, `UI_ALLOWED_HOSTS`, `CAPTURE_*`, plus `MANAGER_IMAGE`. The installer
  never writes `UI_*` (install-manager.py:244-292). The reusable secret pattern is
  `deploy/setup_capture.py` (`read_env` refuses a symlink, `write_env` tempfile+fsync+0600+chown+
  `os.replace`, `configure()` keeps an existing `CAPTURE_SESSION_TOKEN` or makes
  `secrets.token_hex(32)` and validates `[0-9a-f]{64}`). Changed settings reach the container through
  `deploy/recreate-manager.sh`.
- `deploy/start-manager.sh:120` prints *"The UI opens directly without a login. VM and device SSH
  credentials remain in persistent storage."*
- The health check `deploy/check_install.py` (stdlib-only, runs before any venv): `Context.add(ident,
  status, title, detail, fix)`, `ctx.http(path, payload)` (GET or JSON POST to `ctx.base_url`, no
  redirects), check groups in `main()` 760-764; `check_capture` (600-630) is the template for a check
  that talks to the manager, `check_retired_telemetry` (633-669) for one that reads `.env` key names;
  `STORAGE_PROBE` (299-313) runs inside the container through `docker exec` and decrypts `labs` to
  prove the key. Tests: `test_check_install.py` with `ctx.http = Mock(side_effect=router)` and a
  `PRIVATE` sentinel that asserts values do not leak.
- Documentation that states "no login" and must change: `docs/INSTALL.md:202-248` (Opening the manager
  by a name; DNS rebinding; the reverse-proxy advice at 220-235 and 246-248), `docs/CAPTURE.md:236-243`
  and 280-287, `docs/STANDALONE-SETUP.md:89-90`, `docs/HEALTH-CHECK.md:232-239`, `docs/ARCHITECTURE.md:157`,
  `docs/WIKI-MASTER-GUIDE.md:722-726, 787, 1178, 1500-1520`, `app/allowed_hosts.py:3,18-19`,
  `check_install.py` `Context.manual` 83-86, `deploy/start-manager.sh:120`, `CLAUDE.md` invariants.

## 5. Tests, CI and release mechanics

- `tests/test_app.py`: `create_app(tmp)` + `TestClient`; TestClient sends `Host: testserver` and no
  `Origin`, so `client.post(url, json={})` passes the guard. Foreign Origin → 403 (test_app.py:58).
  `HostCheckTests` (317-399) use `patch.dict(os.environ, {'UI_ALLOWED_HOSTS': …})` and
  `headers={'Host':host,'Origin':'http://'+host,'Sec-Fetch-Site':'same-origin'}`; WebSockets with
  `client.websocket_connect(path, headers={'Host':…,'Origin':…})`, refusal = `WebSocketDisconnect` 1008.
- CI (`.github/workflows/release-check.yml`) names each Python test file with `-p` (stdlib group at
  19-37; venv groups at 73-111 and 115-125; design group 129-146; `test_capture*.py` glob at 159) and
  every browser test in one `node --test` line (149). `test_release_consistency.py` `CiListTests`
  (223-234) fails CI when a `tests/test_*.py` or `tests/test_*.js` is missing from those lists. A new
  `deploy/*.sh` must be added to the `bash -n` loop (40).
- `deploy/verify-release.py` hard-codes the nine HTML pages (40-41); **a new page is checked only if
  added there**, and then every `/static/…` reference on it must carry `?v=<VERSION>`.
  `deploy/set-release.py` rewrites the FIELDS files, `VERSION` and the living docs' current-release
  tokens; the three history files are written by hand.
- `docs/redesign/DESIGN-SPEC-ADDENDUM.md` says nothing about sign-in; its binding rules for a new page:
  shell.js owns browser listeners (J1), load-bearing ids stay in `index.html` (J2), header/menus are
  never re-rendered with innerHTML (J3), menu markup and keyboard contract (J4), standalone pages join
  the file table and get their `?v=` from `set-release.py` (E).

## 6. The API surface in full (backend scout)

### 6.1 Guard details beyond section 1
- The guard is an HTTP middleware: it never sees WebSocket scopes; the two sockets check `Origin`
  themselves. Exempt from every check: `/` (main.py:511), `/static/*` (510, StaticFiles mount),
  `/vm-connection-guide` (501), `/student-guide` (505, inline PDF).
- A request with no `Origin` and no `Sec-Fetch-Site: cross-site` passes (curl passes).
- The guard logs every non-GET `/api/` request and every `/download` with `store.event('api.request', …)`
  (main.py:132-144): **no actor and no client address are recorded.** Its own early returns
  (403/503/400/413) carry none of the security headers (145-155).
- Middleware order (outermost first): `HostCheck` (main.py:513-515), `diagnostics.requests`
  (diagnostics.py:112-131, adds `X-Request-ID`, keeps an in-memory request list), `guard`, router.
- `allowed_hosts.py`: `HostCheck.__call__` (86-99) handles `http` and `websocket` scopes; a bad `Host`
  gets 403 plain text or `websocket.close` 1008; `outside_dns_free` (49-59) accepts IP literals,
  `localhost`, single-label names and `*.local` without configuration.

### 6.2 Routes by module (M mutating, R read, J JSON, H page, D download)
- `main.py`: POST /api/manager/reset (225, M; clears tickets/checks/previews 241-243); GET /api/state
  (247, R); DELETE /api/labs/{lab_id} (267, M); GET /api/logs (304, R, events.jsonl); POST /api/inventory
  (307, M, multipart); PUT /api/labs/{lab_id}/node (356); POST /api/labs/{lab_id}/profiles (385, stores
  passwords/keys); PUT /api/labs/{lab_id}/schedule (430); POST /api/labs/{lab_id}/jobs (446); GET
  /api/jobs/{job_id}/nodes/{node_index}/download (458, D); GET /api/jobs/{job_id}/download (470, D).
- `discovery.py` (install 637): GET /api/discovery (653); PUT /api/host (656, VM address/user/password);
  POST /api/discovery/refresh (695); POST /api/discovery/import-preview (722, in-memory token 300 s/100);
  POST /api/discovery/import (745); POST /api/discovery/forget-exclusion (771); POST
  /api/discovery/allow-import (784); POST /api/labs/{lab_id}/sync (789); PUT /api/labs/{lab_id}/deployment
  (816); POST /api/lab-definitions (837, multipart).
- `lab_operations.py` (install 626): GET /api/operations/capabilities (641); POST /api/operations/read
  (647); GET /api/operations/popular (654); GET /api/operations/known-images (657); POST
  /api/operations/image-check (672); POST /api/operations/parse-yaml (706); POST /api/operations/preview
  (731, token 300 s/50); POST /api/operations/confirm (920, M: containerlab lifecycle); GET /api/operations
  (970); GET /api/operations/{job_id} (974); POST /api/operations/{job_id}/cancel (981); PUT
  /api/labs/{lab_id}/operations-settings (1006); GET /api/labs/{lab_id}/drawio (1036, D); PUT
  /api/labs/{lab_id}/layout (1069); GET/PUT /api/labs/{lab_id}/map-document (1098/1104); POST
  /api/labs/{lab_id}/arrange (1188); POST /api/labs/{lab_id}/annotations (1238, D); POST
  /api/labs/{lab_id}/drawio (1247, D).
- `device_diagnostics.py` (install 358): GET /api/operations/logs, /interfaces, /link-state, /netem,
  /images (363-433); POST /api/operations/browse (436), /view (454).
- `impairments.py` (install 202): GET /api/operations/impairments (206); POST …/impairments/set, /reset,
  /clear (217-261); GET /api/operations/apply-plan (312).
- `catalog.py`: GET /api/catalog (94).
- `git_progress.py` (install 1630): GET /api/git/repositories (1721); GET/PUT /api/labs/{lab_id}/git
  (1726/1742); GET /api/git/repositories/{binding_id}/tree (1777); POST/DELETE
  /api/git/repositories/{binding_id}/folders (1788/1811); POST /api/labs/{lab_id}/git/destination (1825),
  /connect (1907), /unlink (1926), /save (1968), /state (2065); POST
  /api/labs/{lab_id}/design/generations/{generation_id}/git (2142); GET /api/git/jobs/{job_id} (2180);
  POST /api/git/jobs/{job_id}/name, /retry, /dismiss (2184-2271); POST /api/labs/{lab_id}/git/update
  (2279); GET /api/labs/{lab_id}/git/history (2311); POST …/git/version (2336), /version/download
  (2343, D), /compare (2353).
- `git_place.py` (install 462/530): GET /api/labs/{lab_id}/git/places (490); POST …/places/check (503),
  …/place (515); POST /api/git/repositories/{binding_id}/folders/new (525).
- `restore.py` (install 1426): GET /api/labs/{lab_id}/restore/sources (1450), /states (1470); POST
  …/restore/preflight (1492), …/restore (1497, M: replaces device configuration, needs `acknowledge`);
  GET /api/restore/jobs/{job_id} (1503).
- `node_services.py` (install 489): GET /api/labs/{lab_id}/health (490); POST …/ssh-check (508),
  …/ssh-check-all (530), …/terminal-ticket (552); **WS /api/terminal (570)**.
- `topology.py` (install 337): GET/POST /api/labs/{lab_id}/topology (342/345); POST
  /api/labs/{lab_id}/superputty (364, D; `include_passwords` opt-in).
- `capture.py` (install 398): GET /api/capture/status (401), /targets (408); POST /api/capture/launch
  (437, sets the cookie). `capture_sessions.py` (install 185): GET /api/capture/health (196), /sessions
  (206, sets the cookie when missing); POST …/sessions/end-all (213); GET …/sessions/{sid} (234); POST
  …/sessions/{sid}/end (238); GET …/sessions/{sid}/assets/{path} (244, pinned SHA-256 list), …/download
  (273, streamed tar); **WS /api/capture/sessions/{sid}/websockify (315)**.
- `telemetry_retirement.py` (install 1026): GET /api/labs/{lab_id}/telemetry-retired (1038); POST
  …/remove (1042), …/forget (1046).
- `network_design.py` (install 553): GET /api/design/engine (568); GET/PUT /api/labs/{lab_id}/design
  (572/588); POST …/design/validate (576), /clear (616), /renumber (631), /generate (648); POST
  …/generations/{generation_id}/cancel (652); GET …/generations/{generation_id} (661),
  …/artifacts/{node}/{index} (672, text), …/download (684, D); GET …/design/export (708, D); POST
  …/design/import (718, multipart).
- `design_apply.py` (install 932): POST …/generations/{generation_id}/review (949); GET
  …/design/review-jobs (954), …/review-jobs/{job_id} (963); POST …/design/apply (967, M: devices, needs
  the review token); GET …/design/apply/jobs (972); GET /api/design/apply/jobs/{job_id} (976); GET
  …/design/ownership (980).
- `diagnostics.py` (install 112, main.py:159): GET /api/debug (134); POST /api/debug/probe (138).
- Not mounted in the manager: `capture_service.py` (bearer token, `Sessions.auth` 92-94).

### 6.3 Sockets and tickets
- WS /api/terminal (node_services.py:570-658): closes 1008 unless `urlsplit(Origin).scheme` matches
  `ws.url.scheme` and `netloc == ws.url.netloc`; after accept waits 5 s for a ≤512-char JSON `{ticket}`
  frame; `self.tickets.pop()` under the lock. Ticket mint (552-568): `secrets.token_urlsafe(32)`, stored
  `(monotonic+30, lab_id, name, protocol)`, 429 when 32 pending. **The ticket is bound to nothing: not a
  cookie, not an origin, not a client.** Tickets are also cleared at `close()` (219), Start fresh
  (main.py:241) and lab removal (main.py:298). Limits: SSH 32 clients, 900 s idle, 14400 s total (609);
  console 8 (`CONSOLE_LIMIT` 105), one per (lab, node) for the whole manager (292-299). Audit events
  terminal.open/close (603/654), console.open/close (311/391).
- WS …/websockify (capture_sessions.py:315-337): same Origin check plus `sid` `^[0-9a-f]{64}$`;
  `owner(ws)` reads the `clab_capture_owner` cookie, missing → 404 → close; forwards upstream with
  `Authorization: Bearer <CAPTURE_SESSION_TOKEN>` and `X-Capture-Owner`.
- The only cookie: `clab_capture_owner` (capture_sessions.py:24; set at 113: `httponly=True`,
  `samesite='strict'`, `secure=(request.url.scheme=='https')`, `path='/api/capture'`, `max_age=86400`,
  no domain). Set by GET /api/capture/sessions and POST /api/capture/launch; required by every other
  capture route and the socket. Not tied to any user identity.

### 6.4 `/api/state` and what reaches the browser
- Built under `store.lock` (main.py:247-261): `labs` via `public_lab` (173-219), `jobs` via
  `decorate_job` (downloads.py:151-159, strips nothing), `platforms`, `version`, `discovery`
  (`Discovery.public()` 614-635: host cut to address/port/username/auth/command_mode/enabled/fingerprint,
  `password_saved: bool`), `student_guide`, `git_jobs` (`PUBLIC_JOB` allowlist git_progress.py:43-45),
  `restore_jobs` (restore.py:87-96), `design_jobs` (design_apply.py:101-105), `operations` (every key
  except `output` and `result`).
- `public_lab` drops nodes, profiles, monitor_host, drawing, definition_yaml, telemetry,
  telemetry_retired, annotations, annotations_for, network_design, network_generations,
  network_ownership (174); profiles keep id/label/platform/username/auth (175); nodes drop
  username/password/enable_password/container_name (180). **`git_binding` is copied out**, including the
  helper descriptor (`owner`, `path`, `remote`, `push_url`, `branch`, …; host_git.py:154, 421).

### 6.5 Store facts for a user table
- No schema. Top-level keys are added by `setdefault` at service construction (`git_jobs`
  git_progress.py:914-916; `restore_jobs` restore.py:409; `design_jobs` design_apply.py:150; `operations`
  lab_operations.py:572) or lazily at write time (`git_folders`, `host`, `discovery`, `ignored_labs`).
  Readers use `.get(key, default)`. Reset rebuilds the dict from `labs, jobs, operations, git_jobs,
  ignored_labs, host, reset_id` (store.py:106-107) and moves `backups`, `network-design`,
  `events.jsonl*`, `ui.token` aside (81, 102).
- `Store.event()` writes `{time, action, message[:4000], level, lab_id, job_id, node}` to the plain-text
  `events.jsonl` (mode 0600, 5 MiB × 4 rotation). **No actor or client field; the file is not encrypted.**
  `GET /api/logs` serves it (main.py:304).
- `ui.token` legacy: read at store.py:22-23; `runner.py:420` still lists it in `secrets_to_hide`.
- Observation (static): after Start fresh without a restart the fresh document lacks `restore_jobs`,
  `design_jobs`, `git_save_names`, `git_folders` until the next process start; `restore.py:164,833` index
  `state['restore_jobs']` directly.

### 6.6 Single-user assumptions
- main.py:72 prints `'Containerlab Node Manager ready; UI login is disabled for this lab VM.'`;
  allowed_hosts.py:3; capture_sessions.py:3-5.
- Everything is global: labs, profiles, jobs, Git bindings, the one VM connection (`state['host']`);
  server-side dismiss/rename/retry act globally. In-memory process-wide, no user key:
  `NodeServices.checks/tickets/consoles` (one console per (lab,node) for everyone), `GitProgress.statuses`,
  preview/review tokens, `Diagnostics.requests`.
- The Git "registered owner" is a VM Linux account (`host_git.py` `ENGINEER` 37, `registry_owner`
  1307-1320, `account_binding` 1344-1351, `run_as_owner` 1402), not a UI user; `connect` (git_progress.py
  1907-1924) sends no owner.
- Python reads `DATA_DIR` (main.py:51), `UI_ALLOWED_HOSTS` (515), `CAPTURE_*` (capture.py:176-263),
  `RESTORE_NODE_WORKERS` (restore.py:132). `UI_BIND`/`UI_PORT` are Compose interpolation only.
  `runner.py:152` passes the whole `os.environ` into every Ansible job environment (a new secret in the
  environment would reach Ansible).
- Scheme: socket Origin checks use `ws.url.scheme`; the cookie's `secure` uses `request.url.scheme`;
  nothing reads `X-Forwarded-*`; uvicorn runs without `--proxy-headers`.
