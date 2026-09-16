# Inventory: secondary pages (SSH terminal, SSH workspace, Grafana launcher, Debug panel)

Read completely (every line): `terminal.js`, `terminal.html`, `terminal.css`, `workspace.js`, `workspace.html`, `grafana.js`, `grafana.html`, `debug.js`, `debug.html`; `index.html` skimmed for ids. Backend handlers, `operations.js` entry points, `style.css` rules, `main.py` CSP and the Node tests were consulted to record exact strings and limits. Nothing was modified.

All paths below are under `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/` unless stated.

---

## 0. Cross-cutting facts that constrain a redesign

| Fact | Source |
|---|---|
| **Content-Security-Policy on every response**: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'`. `style-src` becomes `'self' 'unsafe-inline'` **only** for request paths `/static/terminal.html` and `/static/capture-session.html` (xterm's DOM renderer injects styles). Consequence: no inline `<script>`, no `onclick=` attributes, no inline `<style>` or `style=""` attributes on workspace/grafana/debug, no CDN scripts, no Google Fonts, no external images. | `app/main.py:120-124` |
| Every HTML page references its assets as `/static/<file>?v=1.28.0`. `deploy/verify-release.py` (FIELDS) scans `index.html, terminal.html, workspace.html, vm-connection.html, debug.html, capture-setup.html, capture-session.html, grafana.html` with regex `/static/[^"\s?]+\?v=([^"\s]+)` and requires the version to match; `deploy/set-release.py` rewrites them. Keep the `?v=` pattern on every asset link. | `deploy/verify-release.py:27-43` |
| Node tests execute the page scripts in a bare `vm` context with a fake `document.getElementById`: `tests/test_grafana_ui.js` (loads `grafana.js`, calls `grafanaTarget(params, origin, port)` directly and asserts `#grafana-title/#grafana-status/#grafana-open/#grafana-retry`), `tests/test_debug_ui.js` (loads `debug.js`, calls `debugRun`, `debugDownload`, asserts child ordering inside `#debug-summary` e.g. `children[0].children[1].children[7]` == "Failed — check storage", `#debug-requests` row counts, `#debug-probe`, `#debug-path`, `#debug-errors`, `#debug-download`), `tests/test_operations_ui.js:68-76` (loads `workspace.js` with `location.hash='#mode=folder'`, calls `launchWorkspace()`, asserts `#workspace-title` text `Deploy New Lab` and that `opBrowse` is **not** called on load). Function names, element ids and DOM structure asserted there are part of the contract. | tests |
| Static pages are served by FastAPI `StaticFiles` at `/static`; `/` serves `index.html`. No auth. Every `/api/*` response gets `X-Request-ID`. | `app/main.py:409-411`, `app/diagnostics.py:97-117` |
| Vendored xterm: `@xterm/xterm` 5.5.0 (`vendor/xterm.js`, `vendor/xterm.css`), `@xterm/addon-fit` 0.10.0 (`vendor/addon-fit.js`). Served locally, no CDN. | `vendor/README.md` |
| No `sessionStorage`/`localStorage` access in any of the four page scripts. On the workspace page, `operations.js` (loaded there) writes `sessionStorage.activeLab` when a topology is saved/linked/deployed (`opSaveWorkspace`, `op-add-confirm`), which the main page reads on next load to select that lab. | `operations.js:178,231`; `app.js:4` |

---

## 1. SSH terminal page — `terminal.html` + `terminal.js` + `terminal.css`

### 1.1 Entry points (defined in other files)
- `app.js:110` — any element with `data-terminal="<node>"` (node details drawer / node actions): `window.open('/static/terminal.html#'+URLSearchParams({lab:activeId,node,label:current().name}),'_blank')`.
- `workspace.html#mode=ssh` — per-node `SSH ↗` links and `Open all ready sessions ↗` (see §2).
- Hash contract: `#lab=<lab id>&node=<node name>&label=<lab display name>`. Read with `new URLSearchParams(location.hash.slice(1))`.

### 1.2 Markup (`terminal.html`, one body line)
```
<header>
  <div class="terminal-identity"><img src="/static/fabric-mark.svg" alt="">
    <div><span class="brand-label">CONTAINERLAB NODE MANAGER / SSH SESSION</span>
         <strong id="title">Node SSH</strong><span id="endpoint"></span></div></div>
  <div class="session-controls"><span id="status" role="status">Disconnected</span>
    <button id="connect">Connect / reconnect</button><button id="disconnect">Disconnect</button></div>
</header>
<p class="notice">Commands use your saved account’s permissions. Host keys follow the worker’s trusted-lab policy. Idle sessions close after 15 minutes.</p>
<div id="terminal" aria-label="Interactive SSH terminal"></div>
```
Head: `<title>Containerlab Node Manager · SSH</title>`, favicon `/static/fabric-mark.svg`, stylesheets `/static/vendor/xterm.css` and `/static/terminal.css?v=1.28.0`, scripts (all `defer`, in order) `/static/vendor/xterm.js`, `/static/vendor/addon-fit.js`, `/static/terminal.js?v=1.28.0`. **No link back to the manager on this page.**

### 1.3 Styling (`terminal.css`, single line)
Dark page (`body` background `#152631`, text `#e7eff2`, 13px Segoe UI/Arial), `body` is `display:flex; flex-direction:column; height:100vh; overflow:hidden`. Header: flex-wrap, `padding:20px 24px`, `border-bottom:2px solid #f15b40`, background `#182c38`. `.terminal-identity img` 36×36. `.brand-label` 9px, letter-spacing .15em, `#aec9d7`. `#endpoint` and `#status` 11px Consolas monospace `#79e8f6`. Buttons/inputs: `padding:9px 12px; border:1px solid #587789; radius 4px; background #223e4e`; hover `#345565`; `:disabled` opacity .45; focus-visible outline `2px solid #79e8f6` offset 3px. `#disconnect`: `border-color:#f15b40; color:#ffaa99; background:transparent` (danger outline). `.notice`: `padding:0 24px; color:#a4bbc7; 11px; line-height 1.5`. `#terminal`: `flex:1; min-height:0; margin:12px 24px 20px; overflow:hidden` (required for the fit addon). `@media(max-width:700px)`: header padding 16px, `.session-controls{width:100%}`, notice padding 0 16px, terminal margin 10px 16px 16px.

### 1.4 Script behaviour (`terminal.js`, 30 lines)
Globals (classic script, so top-level `const/let/function` are page-wide): `params`, `lab`, `name`, `get`, `terminal`, `fit`, `socket`, `generation`, `resize()`, `disconnect()`, `connect()`. Consumes `Terminal` (xterm) and `FitAddon.FitAddon` (addon-fit).

1. On load: `document.title = (node||'Node') + ' · Containerlab Node Manager SSH'`; `#title` = `(label||'Lab') + ' / ' + (node||'Unknown node')`.
2. `new Terminal({cursorBlink:true, scrollback:3000, fontSize:14, fontFamily:'Consolas, "Liberation Mono", monospace', theme:{background:'#152631', foreground:'#e7eff2', cursor:'#79e8f6', selectionBackground:'#41637780'}})`, `loadAddon(fit)`, `terminal.open(#terminal)`.
3. `resize()`: `fit.fit()`; if socket OPEN sends `{type:'resize', cols:clamp(terminal.cols,20,400), rows:clamp(terminal.rows,5,150)}`. Bound through `new ResizeObserver(resize).observe(#terminal)`; also called when the server sends status `Connected`.
4. `terminal.onData(data)` → `{type:'input', data}` when socket OPEN (every keystroke, paste, etc.; xterm owns all keyboard handling when focused — no page-level shortcuts).
5. `disconnect()`: `generation++`, closes socket, `socket=null`, `#status='Disconnected'`, `#connect.disabled=false`.
6. `connect()` (async): calls `disconnect()`; `request=++generation`; if `!lab||!name` → `#status='Open this terminal from a node in the dashboard.'` and return (button stays enabled). Else `#connect.disabled=true`, `#status='Connecting…'`; `POST /api/labs/{lab}/terminal-ticket` JSON `{name}`; if `!response.ok` throws `Error(detail if string else 'Connection failed')`; `#endpoint = data.endpoint||''`; opens `WebSocket((https?'wss://':'ws://')+location.host+'/api/terminal')`, `binaryType='arraybuffer'`. `onopen`: sends `{ticket}`, `terminal.reset()`, `terminal.focus()`. `onmessage`: ArrayBuffer → `terminal.write(Uint8Array)`; text → `JSON.parse`, `#status = message.message`, and if it equals `'Connected'` → `resize()`. `onclose`: `socket=null`, `#connect.disabled=false`, `#status += ' · Disconnected'`. `onerror`: `#status='Connection failed'`. Any thrown error: `#status=error.message`, `#connect.disabled=false`. Every handler checks `request!==generation` and ignores stale events from a superseded attempt.
7. Wiring: `#connect.onclick=connect`, `#disconnect.onclick=disconnect`, `window.addEventListener('beforeunload',disconnect)`, then `connect()` runs immediately (auto-connect on page open).

### 1.5 Backend contract (`app/node_services.py`)
- `POST /api/labs/{lab_id}/terminal-ticket` body `{name}` → `{ticket, expires_in:30, endpoint:'address:port'}`. Errors (detail shown verbatim in `#status`): 404 `Lab not found`, 404 `Node not found`, 409 `Node is unavailable; refresh VM discovery before connecting.`, 400 `Assign SSH credentials to this node first.`, 429 `Too many pending terminal sessions` (>32 unexpired tickets).
- `WS /api/terminal`: origin must equal the page origin or the socket closes with 1008 (no message). First text frame within 5 s, ≤512 bytes, `{ticket}`; unknown/expired ticket → close 1008. Then Paramiko connect (AutoAddPolicy host keys, 10 s timeouts, keepalive 30 s), `invoke_shell(term='xterm-256color', width=100, height=30)`; max 32 concurrent SSH clients → 429 `SSH session limit reached; close a session and retry.` (surfaces as the generic error frame). Server sends `{type:'status', message:'Connected'}`, then binary output chunks (16 KiB). Idle >900 s (15 min) or total >14400 s (4 h) → `{type:'status', message:'Session timeout. Reconnect to continue.'}` and close. Any exception → `{type:'error', message:'Session ended. Check credentials, endpoint, and session limits.'}`. Input frames >20000 chars or >16 KiB data rejected; resize outside 20–400 × 5–150 rejected. Audit events `terminal.open` / `terminal.close`.

### 1.6 Status text vocabulary (`#status`)
`Disconnected` · `Connecting…` · `Open this terminal from a node in the dashboard.` · `Connected` · `Session timeout. Reconnect to continue.` · `Session ended. Check credentials, endpoint, and session limits.` · `Connection failed` · `<anything> · Disconnected` (suffix appended on close, can stack, e.g. `Connected · Disconnected`) · any API `detail` string listed above.

---

## 2. Multi-node SSH / Deploy workspace page — `workspace.html` + `workspace.js`

### 2.1 Entry points (other files)
- Sidebar **Deploy New Lab** (`#vm-projects`, `operations.js:281`): `location.assign('/static/workspace.html#mode=folder')` (same tab).
- Topology tab **SSH all nodes ↗** (`#map-ssh-all`, `management.js:226`) and Lab actions dialog **SSH all nodes ↗** (`data-local="ssh"`, `operations.js:42`): `opNewTab({mode:'ssh',lab:id})` → `window.open('/static/workspace.html#mode=ssh&lab=<id>','_blank')`; if the popup is blocked, `opDialog('op-open-tab','Open workspace', 'Your browser may have blocked the new tab.' + <a class="button primary" target=_blank rel=opener>Open workspace ↗</a>)`. `#map-ssh-all` is disabled when no node is `ssh_ready`, with title `Waiting for the NOS to accept SSH logins; this opens automatically` (a node is `booting`) or `No node is ready for SSH` (`app.js:57-58`).
- Hash contract: `#mode=folder|ssh`, `lab=<id>` (ssh mode, also seeds `activeId`), optional `path=<VM folder>` (folder mode start folder; nothing in the code base currently passes it).

### 2.2 Markup (`workspace.html`)
Head: `<title>Deploy New Lab · Containerlab Node Manager</title>`, `/static/style.css?v=1.28.0`, scripts (defer, in order) `workspace.js`, `topology-render.js`, `operations.js`, `diagram-editor.js` (all `?v=1.28.0`). No favicon link on this page.
```
<body class="standalone-workspace"><main class="content">
  <p class="eyebrow">CONTAINERLAB NODE MANAGER</p>
  <h1 id="workspace-title">Deploy New Lab</h1>
  <p id="workspace-message" role="status"></p>
  <a class="workspace-back" href="/">← Back to lab manager</a>
  <p><a href="/static/debug.html">Debug panel</a> · Diagnose VM helper and file-browsing errors</p>
  <div class="workspace-choices">
    <button class="workspace-choice workspace-choice-primary" id="workspace-open"><strong>Lab Topologies</strong><span>Browse topology files on your VM, choose a lab and deploy it.</span><span aria-hidden="true">Browse topologies →</span></button>
    <button class="workspace-choice" id="workspace-history"><strong>Operation history</strong><span>Check the progress and results of previous lab commands.</span></button>
  </div>
  <section id="workspace-content"></section>
</main><div id="toast" role="status" hidden></div></body>
```
Styling (style.css): `.standalone-workspace{background:#f3f6f7}`, `.standalone-workspace main{max-width:1200px;margin:28px auto}`, `.standalone-workspace .actions{margin-bottom:22px}`; `.workspace-choices` 2-column grid (`minmax(280px,2fr) minmax(230px,1fr)`, gap 22, max-width 1000) → 1 column at `max-width:720px` (cards padding 22px, min-height 140); `.workspace-choice` white card, border `#cbd8de`, radius 12, padding 30, min-height 180, `strong` 24px; `.workspace-choice-primary` border `2px solid #f15b40`, background `#fff7f4`, last span `#9c3622` bold; hover shadow; focus-visible outline `3px solid #416377`. `.workspace-back` inline-block, margin `8px 0 24px`, slate, 600. `.op-session-list{margin-top:22px}`, each `p` flex row with 16px gap, bottom border `#dbe3e8`, padding 12 0; `strong{min-width:160px}`. `#toast` fixed bottom-right, dark rail background, cyan left border, z-index 30.

### 2.3 Script behaviour (`workspace.js`, 24 lines)
Defines the same page-level helpers `app.js` defines on the main page, because `operations.js` and `diagram-editor.js` call them: `$`, `esc`, `params`, `activeId` (= hash `lab` or ''), `state` (`{labs:[],jobs:[],operations:[]}`), `toastTimer`, `current()` (lab with id `activeId`), `busy()` (any job/operation with status `queued`/`running`), `notify(message)` (`#toast` text, unhide, hide after 5000 ms), `api(path,options)` (`fetch('/api'+path)`, non-OK → `Error(value.detail||'Request failed.')`), `json(path,method,data)`, `attachmentName(response,fallback)` (parses `Content-Disposition filename*=UTF-8''`), `refresh()` (`GET /api/state` → `state`), `launchWorkspace()`.

`launchWorkspace()` (async, called at `DOMContentLoaded`):
1. `await refresh()`; clear `#workspace-message`.
2. **ssh mode** (`mode==='ssh'`): `lab=current()`; if missing → throw `This saved lab is no longer available.`; `#workspace-title='SSH sessions · '+lab.name`; `#workspace-open.hidden=true` (the Lab Topologies card disappears; Operation history card stays); `nodes=lab.nodes.filter(n=>n.ssh_ready)`; `#workspace-message = '<n> of <total> nodes ready for SSH. Each session opens in its own browser tab. Allow popups for Open all, or use the individual links. Up to 32 simultaneous terminals are supported.'`; `#workspace-content.innerHTML` = `<button class="button primary" id="ssh-launch-all">Open all ready sessions ↗</button>` + `<div class="op-session-list">` with one `<p>` per lab node (all nodes, ready or not): `<strong>{short_name||name}</strong> · {address}` then, if `ssh_ready`, `<a class="button secondary" target="_blank" rel="opener" href="/static/terminal.html#lab=..&node=..&label=..">SSH ↗</a>`, else `<span>Unavailable or missing credentials</span>`. `#ssh-launch-all.onclick`: for the first 32 ready nodes `window.open(link,'_blank')`, counting blocked popups; toast: `'<blocked> popups were blocked. Use the individual SSH links.'` if any blocked, else `'Opened the first 32. Close sessions before opening more.'` if `nodes.length>32`, else `'Sessions opened.'`. The button is never disabled (with 0 ready nodes it toasts `Sessions opened.`).
3. **any other mode**: `#workspace-title='Deploy New Lab'`, `#workspace-message='Choose a lab topology from your VM to launch'`. Nothing else is rendered until a card is clicked (test asserts `opBrowse` is not called on load).
4. Errors → `#workspace-message=e.message`.

Wiring at `DOMContentLoaded`: `#workspace-open.onclick = () => opTask(null, () => opBrowse(params.get('path')||'', activeId))` (opBrowse takes only `path`; the second argument is ignored; with `dialog=null` opTask routes errors to `notify` toast). `#workspace-history.onclick = () => opHistory()` (no lab filter; **not** wrapped in opTask, so a failed `GET /api/operations` is an unhandled rejection with no visible message).

### 2.4 Dialogs reachable from this page (created dynamically by `operations.js` `opDialog`, `<dialog class="operations-dialog">` appended to `<body>`, header eyebrow `NODE MANAGER`, `×` close button `[data-op-close]`, trailing `<p class="form-error" role="alert">`)
- `#op-browser` **Lab Topologies** — `POST /api/operations/browse {path}`; path line (`Lab topology folders` when empty); buttons `#op-roots` Lab folders, `#op-up` Parent folder, `#op-create` New topology, `#op-clone` Clone repository, `#op-popular` Popular labs; `#op-file-tree` (folders as `<details>` lazily loaded, `.clab.yaml|.clab.yml` files as `◇ name` buttons, "No lab topologies or subfolders here.", "Loading…", error + " Close and reopen this folder to retry."); help "Expand a folder and select a .clab.yaml or .clab.yml topology to view or deploy. Other files are hidden. Each folder shows at most 500 matching entries."; `GET /api/operations/capabilities` enables Clone/Popular (`caps.network`), else appends " Online downloads are disabled. Enable --allow-downloads in VM setup for cloning and the catalog." or on failure " Files are available, but command checks failed. Open the Debug panel to check VM helpers. Online actions remain disabled."
- `#op-editor` **Lab topology / Create lab topology** — `POST /api/operations/read`, Absolute VM path, YAML textarea (read-only for existing files), buttons Validate / preview topology, Review creation on VM, Link topology / Save to manager, Deploy lab.
- `#op-add-confirm` **Link lab topology? / Save lab to manager?** — `POST /api/lab-definitions`, `PUT /api/labs/{id}/operations-settings`; writes `sessionStorage.activeLab`; toast `Lab topology saved to the manager.`
- `#op-map-preview` **Topology preview · name** (SVG from topology-render.js).
- `#operation-review` **<Action>?** — `POST /api/operations/preview`, then `POST /api/operations/confirm {token}`; warnings, affected containers, "Containerlab command" `<pre>`, YAML diff; Cancel / confirm.
- `#operation-output` **Operation output** — `GET /api/operations/{id}` polled every **1000 ms** while queued/running (`opOutputTimer`, cleared on dialog close); banner ✔/✖; "Browse cloned lab topologies" button.
- `#operation-history` **Operation history** — `GET /api/operations`; "Saved command output remains in persistent manager storage."; one button per job (`name · label`, `status · created localeString`), "No lab operations yet."
- `#op-clone-dialog` **Clone a lab repository**, `#op-popular-dialog` **Popular lab topologies** (`GET /api/operations/popular`).
- `diagram-editor.js` is loaded but no code path on this page calls `editDiagram`/`opLayout` (those hang off the main page's Lab actions dialog and `#map-edit`).

---

## 3. Grafana launcher page — `grafana.html` + `grafana.js`

### 3.1 Entry point (other files)
`index.html:50` `<a class="button secondary" id="grafana-open" target="_blank" rel="noopener" hidden>Grafana ↗</a>`; `app.js:29-39` `renderGrafanaLink(lab)`: hidden unless `lab.telemetry.grafana.enabled && port`; href `/static/grafana.html#path=<encoded>&title=<lab name>` where path = `/d/${map_uid||'clab-lab-overview'}?var-lab=<lab name>&refresh=10s`; text `Lab map in Grafana ↗` (map_uid) or `Grafana ↗`; title tooltip `Live weathermap of this lab in Grafana: link rates, port and node state.` / `Live dashboards for this lab in Grafana: interface rates, link state, BGP neighbours.` + ` Grafana starts on the VM when it is not running.`
Hash contract: `#path=<dashboard path>&title=<lab name>`.

### 3.2 Markup (`grafana.html`)
Head: `<title>Grafana · Containerlab Node Manager</title>`, favicon, `/static/style.css?v=1.28.0`; script `/static/grafana.js?v=1.28.0` at the end of body (not deferred).
```
<main class="capture-guide">
  <a href="/">← Manager</a>
  <h1 id="grafana-title">Grafana</h1>
  <p id="grafana-status" role="status" aria-live="polite">Checking Grafana on the VM…</p>
  <p class="form-help">Grafana runs on the lab VM only while someone reads it: the manager starts it now if it is stopped and stops it again after a while without an open dashboard. Prometheus keeps the last fifteen minutes.</p>
  <div class="actions"><a class="button primary" id="grafana-open" hidden>Open Grafana ↗</a><button class="button secondary" id="grafana-retry" hidden>Retry</button></div>
</main>
```
Styling: `.capture-guide{max-width:900px;margin:40px auto;padding:24px;line-height:1.65}` (shared with capture-setup.html); `.form-help{font-size:11px!important}`; `.actions` flex gap 8.

### 3.3 Script behaviour (`grafana.js`, 35 lines)
Globals: `$`, `grafanaTarget(params, origin, port)` (unit-tested directly), `grafanaRequest(method,url)`, `launchGrafana()`. Bootstrap guarded by `if(typeof document!=='undefined'&&$('grafana-retry'))` so the file can be evaluated in Node.
- `grafanaTarget`: `raw=params.get('path')||''`; accepted only if it matches `/^\/d\/[A-Za-z0-9_-]+(\?[A-Za-z0-9_=&%+.-]*)?$/`, otherwise `/d/clab-lab-overview`; returns `${origin.protocol}//${origin.hostname}:${port}${path}` — origin is always the manager's own host, never taken from the link.
- `grafanaRequest`: `fetch(url,{method, cache:'no-store', headers: POST?{'Content-Type':'application/json'}:{}, body: POST?'{}':undefined})`; body JSON parsed leniently; non-OK → `Error(detail if string else 'The manager could not reach Grafana.')`.
- `launchGrafana`: title → `'Grafana · '+title` when hash `title` present; hides `#grafana-retry` and `#grafana-open`; `GET /api/telemetry/grafana`; if `!status.enabled` → throw `status.message || 'The Grafana stack is not installed on this manager.'`; `#grafana-status` = `Grafana is running; opening the dashboard…` (running) or `Starting Grafana on the VM; this takes a few seconds…`; if not running `POST /api/telemetry/grafana/start` (body `{}` — the manager refuses empty writes); `url=grafanaTarget(params, location, result.port)` (port from the start/status response); `#grafana-open.href=url`, unhide; `#grafana-status='Grafana is ready.'`; `location.replace(url)` (replaces this tab's history entry). On error: `#grafana-status=error.message`, `#grafana-retry.hidden=false` (Open stays hidden). `#grafana-retry.onclick=launchGrafana`; `launchGrafana()` runs on load.

### 3.4 Backend contract (`app/grafana_control.py`)
- `GET /api/telemetry/grafana` → `{enabled, port, running (null until first probe), idle_minutes, started_at, last_activity, checked_at, error, message}`; `message` ∈ `The Grafana stack is not installed on this manager.` / `Grafana has not been checked yet.` / `Grafana is stopped; it starts when you open it from a lab.` / `Grafana is running; the automatic stop is off (TELEMETRY_GRAFANA_IDLE_MINUTES=0).` / `Grafana is running; it stops after N minute(s) without an open dashboard.`
- `POST /api/telemetry/grafana/start` → same shape after start (waits up to 75 s for `/api/health`). 409 details: `The Grafana stack is not installed on this manager. Run sudo bash deploy/setup-telemetry.sh on the VM.` · `The Grafana container does not exist on the VM. Run sudo bash deploy/setup-telemetry.sh there.` · `Grafana was started but did not answer within 75 s. Inspect it on the VM: sudo docker logs --tail=80 clab-manager-grafana` · `The VM operations helper predates on-demand Grafana. Run sudo bash deploy/start-manager.sh on the VM from this source, then retry.` · any helper error text.
- Monitor thread polls every 30 s and stops Grafana after `idle_minutes` (default 15) without dashboard requests; a dashboard with `refresh=10s` keeps it alive. (`POST /api/telemetry/grafana/stop` is used by the Telemetry settings dialog on the main page, not by this page.)

---

## 4. Debug panel — `debug.html` + `debug.js`

### 4.1 Entry points (other files)
Sidebar `<a class="text-button" href="/static/debug.html">Debug panel</a>` (`index.html:29`); `workspace.html` "Debug panel · Diagnose VM helper and file-browsing errors"; `vm-connection.html` "Open Debug panel to check the running version and VM helpers."; `operations.js` browse help text "Open the Debug panel to check VM helpers." No hash parameters.

### 4.2 Markup (`debug.html`)
Head: `<title>Debug panel · Containerlab Node Manager</title>`, favicon, `/static/style.css?v=1.28.0`, `<script src="/static/debug.js?v=1.28.0" defer>`.
```
<body class="standalone-workspace"><main class="content debug-page">
<a class="workspace-back" href="/">← Back to lab manager</a>
<p class="eyebrow">DEVELOPMENT &amp; SETUP</p>
<div class="section-heading"><div><h1>Debug panel</h1><p>Check the running manager and trace VM file-browsing failures.</p></div>
  <div class="actions"><button class="button secondary" id="debug-refresh">Refresh</button><button class="button secondary" id="debug-download" disabled>Download report</button></div></div>
<p id="debug-status" role="status">Loading diagnostics…</p>
<div id="debug-summary" class="debug-grid"></div>
<section class="debug-card"><h2>VM helper checks</h2>
  <p>Test folder listing and command capabilities using the saved VM connection. Each helper response has a 30-second limit, plus SSH connection time.</p>
  <form id="debug-probe-form"><label for="debug-path">VM folder <span class="muted">optional</span></label>
    <div class="debug-input"><input id="debug-path" maxlength="4096" placeholder="Leave blank to check trusted root listing"><button class="button primary" id="debug-probe" type="submit">Run read-only checks</button></div></form>
  <p class="form-help">Use the folder that failed in Lab Topologies. This does not deploy labs or read file contents.</p>
  <div id="debug-checks" aria-live="polite"><p>No checks run in this page session.</p></div>
  <p>For installation failures before this page is available, run <code>bash deploy/check-install.sh</code> in the VM source folder.</p></section>
<section class="debug-card"><div class="section-heading"><div><h2>Recent API requests</h2><p>Newest first · request IDs, status codes and elapsed time help locate failed steps.</p></div>
  <label class="checkbox-label"><input type="checkbox" id="debug-errors">Failures only</label></div>
  <div class="table-wrap"><table><thead><tr><th>UTC time / request ID</th><th>Request</th><th>Status</th><th>Duration</th></tr></thead><tbody id="debug-requests"></tbody></table></div></section>
<p class="notice">Reports contain versions, readiness flags, counts and request metadata. Credentials, VM paths, file contents and raw logs are excluded. Request history is limited to 200 entries and clears when the manager restarts. Successful state and debug polling is omitted.</p>
</main></body>
```
Styling: `.debug-page{max-width:1400px;margin:auto}`, `td`/`code` `overflow-wrap:anywhere`, `.debug-page .section-heading` column layout; `.debug-grid` 3 equal columns gap 20 → 1 column at `max-width:800px`; `.debug-card` white, border `#dce4e8`, radius 12, padding 24, margin 20 0 (0 inside the grid); `.debug-card dl` 2-column grid gap 10, `dt` slate `#416377`, `dd` margin 0; `.debug-input` flex gap 12 (input `flex:1`) → column at ≤800px; `.debug-failure{color:#a12d1b}`; `.table-wrap table{min-width:730px}` (horizontal scroll on narrow screens); `.notice` 11px grey; `.muted` 10px grey.

### 4.3 Script behaviour (`debug.js`, 57 lines)
Globals: `debugElement`, `debugSnapshot`, `debugProbe`, `debugText(tag,text,className)`, `debugFetch(path,options)`, `debugRows()`, `debugRender()`, `debugRefresh()`, `debugRun(event)`, `debugDownload()`. All rendering uses `textContent` (no innerHTML) — tests assert untrusted strings are shown literally.
- `debugFetch`: `fetch('/api/debug'+path)`; non-OK → `Error('Diagnostic request failed (HTTP '+status+'). Refresh and retry; check the VM terminal if it persists.')` — the backend `detail` is **not** surfaced.
- `debugRefresh` (runs on load and after every probe): disables `#debug-refresh`; `GET /api/debug` → `debugSnapshot`; `debugRender()`; `#debug-status='Snapshot updated '+generated_at`; on error `#debug-status=error.message`; finally re-enable.
- `debugRender`: clears `#debug-summary`; three `<section class="debug-card">` each with `<h2>` and a `<dl>` (`dt` = key with `_`→space, `dd` = `Yes`/`No` for booleans else `String(value)`):
  1. **Running manager**: `Release`=manager_version, `Python`=python_version, `Uptime`=`<n> seconds`, `Last audit write`=`Failed — check storage` if `audit_log_available===false` else `Succeeded`, then one row per package (`fastapi`, `paramiko`, `ansible-core`, `cryptography`; value is the version or `not installed`).
  2. **VM connection**: raw `data.vm` keys → `configured`, `enabled`, `password saved`, `fingerprint saved`, `connected`, `checking`, `file import supported`, `discovery helper version` (`unknown` when not numeric).
  3. **Saved workspace**: `data.saved_counts` → `labs`, `jobs`, `operations`, `git jobs` counts.
  Then `debugRows()`; `#debug-download.disabled=false`.
- `debugRows`: clears `#debug-requests`; rows = `snapshot.requests` filtered by `#debug-errors.checked ? status>=400 : all`; per row cells `time + ' / ' + id`, `method + ' ' + route`, `status`, `duration_ms + ' ms'`; `tr.className='debug-failure'` when status ≥400; empty → one `td colspan=4` `No matching requests recorded. Reproduce the issue, then refresh.`
- `#debug-errors.onchange=debugRows` (client-side re-filter only).
- `debugRun` (form submit): `preventDefault`; disable `#debug-probe`; `debugProbe=null`; `#debug-checks` = `<p>Checking folder listing and helper capabilities…</p>`; `POST /api/debug/probe` JSON `{path: #debug-path.value}`; on success one `<p>` per check: `'{check} · {STATUS} · {duration_ms} ms' + (entry_count!==undefined ? ' · N entries':'') + (helper_version ? ' · helper X.Y.Z':'') + (message ? ' — message':'')`, class `debug-failure` when `status==='fail'`; then `<small>Checked {generated_at}</small>`; then `await debugRefresh()`. Error → `<p class="debug-failure">{message}</p>`. Finally re-enable `#debug-probe`. Backend: checks `browse` (status `pass` + `entry_count`) and `capabilities` (status `pass`/`warning` + `helper_version` + message `Helper matches the manager.` / `Install helpers and manager from the same source release.`); failures carry `status:'fail'`, `code` (`host-trust`, `vm-disabled`, `gateway-permission`, `gateway-account`, `untrusted-folder`, `missing-folder`, `not-directory`, `symlink-folder`, `timeout`, `authentication`, `helper-unavailable`) and a `message` hint (see microcopy). Backend timeout per helper call is 90 s (`PROBE_TIMEOUT`), HTML says 30 s. 409 `A diagnostic check is already running. Wait for it to finish.` / `VM settings changed during the check. Run it again.` are collapsed into the generic `HTTP 409` text.
- `debugDownload`: no-op without a snapshot; builds `{...debugSnapshot, probe: debugProbe}` (probe `null` if none/failed), `Blob` JSON pretty-printed + trailing newline, temporary `<a download="clab-debug-<generated_at with : and . → ->.json">` appended to body, clicked, removed; `URL.revokeObjectURL` after 1000 ms. Test asserts the typed probe path is **not** in the report.
- Wiring: `#debug-refresh.onclick=debugRefresh`, `#debug-download.onclick=debugDownload`, `#debug-errors.onchange=debugRows`, `#debug-probe-form.onsubmit=debugRun`, `debugRefresh()` on load. No polling.

### 4.4 Backend contract (`app/diagnostics.py`)
`GET /api/debug` → `{schema:1, generated_at, manager_version, python_version, packages{}, uptime_seconds, vm{configured,enabled,password_saved,fingerprint_saved,connected,checking,file_import_supported,discovery_helper_version}, audit_log_available, saved_counts{labs,jobs,operations,git_jobs}, requests[{time,id,method,route,status,duration_ms}] (newest first, ≤200, excludes successful `/api/state`, `/api/debug`, `/api/debug/probe`, `/api/telemetry/metrics`, telemetry series routes), scope}`. `POST /api/debug/probe {path≤4096}` → `{generated_at, checks[]}`.

---

## 5. Timers, observers, sockets
- terminal: `ResizeObserver` on `#terminal`; WebSocket `/api/terminal`; server idle 15 min / max 4 h; ticket expiry 30 s; auth frame deadline 5 s; SSH keepalive 30 s. No `setInterval`.
- workspace: toast auto-hide `setTimeout` 5000 ms; `operations.js` `opShowJob` polls `GET /api/operations/{id}` every 1000 ms while queued/running (cleared on dialog close); `GET /api/state` once at load (no polling).
- grafana: none client-side; server start wait ≤75 s; server monitor every 30 s.
- debug: `setTimeout` 1000 ms to revoke the blob URL; no polling.

## 6. Keyboard
- terminal: xterm receives all keystrokes when focused (`terminal.focus()` after the socket opens), including Tab/Ctrl-C/Ctrl-D which are sent to the device; no page shortcuts. Buttons and inputs have a cyan focus ring.
- workspace / grafana / debug: no custom key handlers; native form submit (Enter in `#debug-path` runs the probe); `<dialog>` Esc closes operations dialogs (native `showModal`).

## 7. Element ids referenced by the scripts
terminal: `title`, `endpoint`, `status`, `connect`, `disconnect`, `terminal`.
workspace: `workspace-title`, `workspace-message`, `workspace-open`, `workspace-history`, `workspace-content`, `toast`, dynamic `ssh-launch-all`; via operations.js: `op-browser`, `op-file-tree`, `op-roots`, `op-up`, `op-create`, `op-clone`, `op-popular`, `op-editor`, `op-edit-path`, `op-edit-text`, `op-validate`, `op-save-yaml`, `op-add-project`, `op-deploy-project`, `op-add-confirm`, `op-add-confirm-button`, `op-clone-dialog`, `op-clone-url`, `op-clone-name`, `op-clone-review`, `op-popular-dialog`, `op-map-preview`, `op-preview-map`, `operation-review`, `op-cancel`, `op-confirm`, `operation-output`, `op-job-banner`, `op-job-output`, `op-job-result`, `op-open-clone`, `operation-history`.
grafana: `grafana-title`, `grafana-status`, `grafana-open`, `grafana-retry`.
debug: `debug-refresh`, `debug-download`, `debug-status`, `debug-summary`, `debug-probe-form`, `debug-path`, `debug-probe`, `debug-checks`, `debug-errors`, `debug-requests`.
index.html (entry points): `grafana-open`, `vm-projects`, `map-ssh-all`, `operations-history`, sidebar `Debug panel` link, `import-top` (its presence gates operations.js main-page init).

## 8. Microcopy a CCNA-level student would not understand
See the structured list; highlights: "Host keys follow the worker’s trusted-lab policy" (terminal notice); "Diagnose VM helper and file-browsing errors"; "VM helper checks", "helper response", "trusted root listing", "Run read-only checks", "helper 1.28.0", "Install helpers and manager from the same source release.", "bash deploy/check-install.sh in the VM source folder", "request IDs, status codes", "Last audit write", "discovery helper version", "fingerprint saved", "file import supported", "git jobs", "Successful state and debug polling is omitted." (debug); "Prometheus keeps the last fifteen minutes.", "The Grafana stack…", "sudo docker logs --tail=80 clab-manager-grafana", "The VM operations helper predates on-demand Grafana." (grafana); "Unavailable or missing credentials" (workspace); probe failure hints referencing "operations gateway", "clab-discovery SSH session", "--lab-root", "symlink", "restricted account setup", "VM host fingerprint".

## 9. Redesign risks (summary; full list in the structured output)
CSP (no inline style/script except inline styles on `/static/terminal.html`); `?v=` release-check regex on every HTML page; Node tests bind to ids, function names and DOM child order; `workspace.js` must keep defining the app.js-compatible globals for `operations.js`/`diagram-editor.js`; do not add an element with id `import-top` (or `map-edit`, `labs`, …) to the workspace page or `operations.js` will run its main-page init; hash-parameter contracts; `#terminal` flex/min-height/overflow for the fit addon; `#disconnect` never disabled while `#connect` is the only lock; `location.replace` on the Grafana page; `rel="opener"` on SSH links; duplicate ids across pages (`title`, `status`, `toast`, `grafana-open`) would collide in a single-page merge; the 30-second vs 90-second probe text discrepancy; `debugFetch` hides backend detail.
