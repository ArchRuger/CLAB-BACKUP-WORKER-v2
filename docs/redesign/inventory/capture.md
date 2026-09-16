# Packet capture UI inventory (pre-redesign)

Source of truth: read completely, no guessing.

- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/capture.js` (149 lines, classic deferred script, `'use strict'`, loaded LAST in index.html)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/capture-session.js` (67 lines, `type="module"`, standalone viewer page)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/capture-session.html` (3 lines)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/capture-setup.html` (5 lines, static, no JS)
- Skimmed for referenced ids / callers: `index.html` (#capture-dialog markup, #capture-open), `app.js` (helpers, `handleNodeAction`, `nodeActions`), `topology.js` (`map`, `closeNodeMenu`, `openNodeMenu`), `topology-render.js` (`topologyLink` renders `data-capture-endpoints`), `style.css` (capture rules), backend `capture.py` / `capture_sessions.py` (response shapes only).

Version tag on all static assets: `?v=1.28.0`.

---

## 1. Module boundaries

### 1.1 Globals DEFINED by capture.js (all top-level, shared window scope with the other classic scripts)

| Name | Kind | Purpose | Called from other files |
|---|---|---|---|
| `captureDialog` | const (HTMLDialogElement) | `$('capture-dialog')` | no |
| `captureRequest` | let number | monotonically increasing race guard for target discovery / launch; every `invalidateCapture()` bumps it | no |
| `captureTargets` | let array | last `/capture/targets` result (`{id,name,kind,prefix,interfaces[],aliases[]}`) | no |
| `captureLab` | let string | lab id snapshot taken from `activeId` when the dialog opens | no |
| `captureNode` | let string | inventory node name the dialog is scoped to ('' = lab/host) | no |
| `captureHint` | let string | imported (topology) port name to pre-tick, from a link endpoint | no |
| `captureStarting` | let bool | launch in flight; blocks double submit, keeps Start disabled | no |
| `captureLaunchId` | let string | 64-hex idempotency key sent as `request_id`; kept across failed retries, cleared on success | no |
| `captureDrawing` | let (undefined/null/object) | cached `GET /labs/{lab}/topology` for this dialog open; `undefined` = not fetched yet, `null` = fetch failed | no |
| `captureMapInterfaces` | let array | interface names the saved topology wires to `captureNode` | no |
| `captureEnabled` | let (null/true/false) | provider status; `null` until known | no (read via `captureActionAttrs`) |
| `captureActionAttrs()` | function | returns `disabled title="Packet capture is not enabled. Open Capture packets for setup."` when `captureEnabled===false`, else `''` | **YES**: `app.js:72 nodeActions()` (node table row + details drawer "Capture" button) and `topology.js:20 openNodeMenu()` (context-menu "Capture packets"), both guarded by `typeof captureActionAttrs==='function'` |
| `clearCaptureLaunch()` | function | hides `#capture-launch` and removes its `href` | no |
| `invalidateCapture()` | function | `captureRequest++`, `captureLaunchId=''`, `clearCaptureLaunch()` | no |
| `captureSelected()` | function | target object whose id equals `#capture-target.value` | no |
| `captureChecked()` | function | values of `input:checked` inside `#capture-interfaces` and `#capture-interfaces-all` | no |
| `updateCapturePrepare(preselected=false)` | function | `#capture-prepare.disabled = captureStarting || !(target && (preselected || checked.length))` | no |
| `mapInterfacesFor(drawing,node)` | function | pure: node ids where `inventory_name===node`, then every link endpoint `interface` on those ids (deduped) | no |
| `captureBox(name,checked)` | function | HTML for one `<label class="capture-interface"><input type="checkbox" value=name [checked]> <span>name</span></label>` | no |
| `renderCaptureInterfaces()` | function | rebuilds both interface lists, legend, "more" toggle, status hint, Start state (see 3.3) | no |
| `captureTargetLabel(t)` | function | option label text (see 3.7) | no |
| `filterCaptureTargets()` | function | rebuilds `#capture-target` options from search query (see 3.6) | no |
| `refreshCaptureTargets()` | async function | full discovery flow (see 3.2) | no |
| `openCapture(node='',hint='',ends=null)` | function | opens/re-scopes the dialog (see 3.1) | **YES**: `app.js:107 handleNodeAction` → `openCapture(b.dataset.capture)` for any `[data-capture]` button (node table, details drawer, node context menu) |
| `captureSessionRequest` | let number | race guard for sessions list | no |
| `refreshCaptureSessions()` | async function | reloads "Sessions in this browser" list | no |
| `openLinkCapture(element)` | function | parses `data-capture-endpoints` JSON and calls `openCapture('','',pair)` | no (only via capture.js map listeners) |

Also an anonymous async IIFE at load: `captureEnabled = !!(GET /capture/status).enabled` (catch → `null`).

### 1.2 Globals CONSUMED by capture.js (defined elsewhere)

| Name | Defined in | Notes |
|---|---|---|
| `$` | app.js:2 | `document.getElementById` |
| `esc` | app.js:3 | HTML escaper |
| `activeId` | app.js:4 | current lab id (seeded from `sessionStorage['activeLab']` by app.js, not by capture.js) |
| `current()` | app.js:5 | current lab object (`.name`, `.nodes`) |
| `notify(message)` | app.js:7 | toast `#toast`, 5 s |
| `api(path,options)` | app.js:8 | `fetch('/api'+path)`; throws `Error(detail)` on non-2xx (`detail` string or 'Check the form fields and try again.'; 'Request failed' if body not JSON) |
| `json(path,method,data)` | app.js:15 | JSON POST helper via `api` |
| `map` | topology.js:3 | `$('topology-map')` SVG |
| `closeNodeMenu()` | topology.js:16 | closes node context menu |
| Browser: `crypto.getRandomValues`, `confirm`, `URLSearchParams`, `HTMLDialogElement.showModal/close` | — | |
| Markup contract: `[data-capture-endpoints]` | topology-render.js `topologyLink()` | `<g class="topology-wire" data-capture-endpoints='[{"node","label","interface"},{...}]' tabindex="0" role="button" aria-label="Capture A:ifA to B:ifB">` with an invisible 16px-wide `path.capture-hit` for hit testing |

### 1.3 capture-session.js (module; nothing leaks to window)

Module-local: `$`, `sid` (= `location.hash.slice(1)`), `rfb`, `rfbConnected`, `ended`, `heartbeat`, `valid` (= `/^[0-9a-f]{64}$/.test(sid)`), `base` (= `'/api/capture/sessions/'+sid`), `status()`, `connectViewer()`, `downloadCaptures(event)`. Uses raw `fetch` (NOT app.js `api`), and dynamic `import(base+'/assets/core/rfb.js')` for noVNC's `RFB` class served same-origin by the manager.

---

## 2. API calls (all relative to `/api`, via app.js `api()` unless noted)

| Call | Where | When |
|---|---|---|
| `GET /capture/status` | capture.js:13 IIFE | once at page load → `captureEnabled` |
| `GET /capture/status` | `refreshCaptureTargets` | every discovery; `{enabled, provider, message, setup_url}`; if `!enabled` show `status.message` and stop |
| `GET /labs/{captureLab}/topology` | `refreshCaptureTargets` | once per dialog open (when `captureDrawing===undefined && captureLab`); failure → `null`, silent |
| `GET /capture/targets?lab_id=&node=` | `refreshCaptureTargets` | params only when `#capture-scope !== 'host'` and `captureLab` set; `node` added when `captureNode` set. Response `{targets:[{id,name,kind,prefix,interfaces,aliases}],message}` |
| `POST /capture/launch` body `{target_id, interfaces[], request_id}` | form submit | returns `{id,url,message}`; front-end REQUIRES `url` to match `^/static/capture-session\.html#[0-9a-f]{64}$` else `Error('Unsupported capture launch address.')` |
| `GET /capture/sessions` | `refreshCaptureSessions` | on every discovery, after launch, on "Refresh sessions", after "End session"; `{sessions:[{id,name,interfaces[]}]}`; rows with non-64-hex id are skipped |
| `POST /capture/sessions/{id}/end` body `{}` | dialog list "End session" | |
| raw `fetch GET /api/capture/sessions/{sid}` (cache:no-store) | session page `status()` | on connect and every 30 s heartbeat; uses `name`, `interfaces`, `running`, `remaining_seconds`, error `detail` |
| raw `fetch GET /api/capture/sessions/{sid}/assets/core/rfb.js` | session page | readiness probe, up to 20 × 1.5 s; then `import()` of the same URL |
| WebSocket `ws(s)://{host}/api/capture/sessions/{sid}/websockify` | session page | noVNC transport |
| raw `fetch GET /api/capture/sessions/{sid}/download` | session page | probe with AbortController; if ok abort and trigger anchor download named `wireshark-captures.tar`; if not ok show `detail` or 'Capture files unavailable.' |
| raw `fetch POST /api/capture/sessions/{sid}/end` body `{}` | session page End | |

Backend-side facts relevant to UI wording (from capture.py / capture_sessions.py, for reference only): "in this browser" = httponly cookie `clab_capture_owner` (path `/api/capture`, 24 h, SameSite=Strict) set on first `GET /api/capture/sessions` or launch; status messages `'Ready to discover live interfaces.'` / `'Packet capture is optional. Follow Capture setup to enable it.'`; targets message `'Live Linux interfaces. Edgeshark omits DOWN interfaces. Use All host targets for bridges, host NICs and other namespaces.'` (+ `' N discovered namespace(s) were unreadable and are not listed.'`); launch message `'Wireshark session started on the VM. Open the browser viewer to inspect packets.'`; launch errors `'Capture target changed or disappeared. Refresh interfaces and select it again.'`, `'Select interfaces from the refreshed live list.'`, `'Browser capture is disabled. Follow Capture setup.'`, `'Browser capture service returned an invalid session.'`; session errors `'Capture session not found in this browser.'`, `'Capture session not found.'`, `'Capture session ended or is not owned by this browser.'`, `'Capture files unavailable. Check the session and save files in /pcaps first.'`, `'Viewer asset unavailable. Reopen the capture session.'`, `'Browser viewer unavailable.'`.

---

## 3. Capture dialog (`#capture-dialog`, index.html) — behaviour in detail

Markup (index.html line 100), in order:
`<dialog id="capture-dialog" class="capture-dialog" aria-labelledby="capture-title">` → `<form id="capture-form">` →
1. `.dialog-head`: `<h2 id="capture-title">Capture packets</h2>` + `<button type="button" class="icon-button" id="capture-close" aria-label="Close packet capture">×</button>`
2. `<p id="capture-context">` (dynamic)
3. `<div id="capture-endpoints" class="actions">` (dynamic link-endpoint buttons)
4. `<p class="form-help">Wireshark runs on the lab VM and opens in your browser; nothing is installed on the workstation.</p>`
5. `<fieldset><legend id="capture-primary-legend">Topology interfaces</legend><div id="capture-interfaces" class="capture-interfaces"></div></fieldset>`
6. `<details id="capture-more" class="capture-more" hidden><summary id="capture-more-label">All live Linux interfaces</summary><p class="form-help">Management, fabric and internal interfaces of the same namespace. Tick any of them to add it to the capture.</p><div id="capture-interfaces-all" class="capture-interfaces"></div></details>`
7. `<p id="capture-status" role="status" aria-live="polite"></p>`
8. `.dialog-actions`: `<button class="button primary" id="capture-prepare" type="submit" disabled>Start browser capture</button>` + `<a class="button primary" id="capture-launch" target="_blank" rel="noopener" hidden>Open Wireshark in browser ↗</a>`
9. `<details id="capture-advanced" class="capture-advanced"><summary>Advanced: other capture targets</summary><p class="form-help">The target is the node you clicked. Use this for bridges, host NICs, other namespaces, or a node that discovery did not match.</p><div class="capture-controls"><label>Scope<select id="capture-scope"><option value="lab">Selected lab / node</option><option value="host">All host targets</option></select></label><button type="button" id="capture-refresh" class="button secondary">Refresh interfaces</button></div><label>Find a target or interface<input id="capture-search" type="search" placeholder="Node, bridge, host NIC or interface"></label><label>Capture target<select id="capture-target"></select></label><p class="form-help">Requires the optional browser capture services on the lab VM. <a href="/static/capture-setup.html" target="_blank" rel="noopener">Capture setup and troubleshooting ↗</a></p></details>`
10. `<h3>Sessions in this browser</h3><button type="button" id="capture-sessions-refresh" class="button secondary">Refresh sessions</button><ul id="capture-sessions"></ul>`

### 3.1 Entry points (`openCapture(node, hint, ends)`)

Common steps: `captureLab=activeId; captureNode=node; captureHint=hint; captureDrawing=undefined; captureMapInterfaces=[]`; closes `#details-dialog` if open; resets `#capture-search=''`, `#capture-scope='lab'`, `#capture-advanced.open=false`; if the dialog is not already open → `showModal()`; then `refreshCaptureTargets()`.

| Entry | Trigger | Gating | `#capture-context` text |
|---|---|---|---|
| Toolbar | `#capture-open` "Capture packets" button in `.control-row .actions` (next to Grafana / Export sessions / Test NOS login / Back up now), only visible inside `#lab-content` | never disabled (so setup link stays reachable) | `Lab: {current().name}` or `Lab: All targets` when no lab |
| Node table row / details drawer | `<button data-capture="{name}">Capture</button>` from `nodeActions()`; handled by `handleNodeAction` | `disabled title="Packet capture is not enabled. Open Capture packets for setup."` when `captureEnabled===false` (evaluated at render time) | `Node: {name}` |
| Node context menu (map right-click / ContextMenu key / Shift+F10) | `<button role="menuitem" data-capture="{name}">Capture packets</button>` | same gating | `Node: {name}` |
| Topology link, left click | `map` click on `.closest('[data-capture-endpoints]')` | none | see below |
| Topology link, right click | `map` contextmenu → `preventDefault()`, `closeNodeMenu()`, open | none | |
| Topology link, keyboard | `map` keydown `Enter` or `' '` on focused wire (`tabindex=0 role=button`) → `preventDefault()`, open | none | |
| Link JSON unreadable | `JSON.parse` throws | — | toast `Could not read this link. Use Capture packets to browse live interfaces.` |

Link opening (`ends` = `[{node,label,interface},{node,label,interface}]`): opens on the FIRST endpoint if it has a `node` (`captureNode=ends[0].node; captureHint=ends[0].interface`). Context text:
- endpoint resolved: `Link endpoint: {label}: {interface}`
- no endpoint resolved for both ends: `Choose either link endpoint below, then select its live Linux interface.`
- node entry with hint (not currently produced by callers but coded): `Node: {name} · imported port: {hint}`

`#capture-endpoints` gets one `<button type="button" class="button secondary" data-capture-end="{i}">{label}: {interface}</button>` per end (empty when not opened from a link). Delegated click: sets `captureNode=ep.node||''`, `captureHint=ep.interface`, context `Link endpoint: {label}: {interface}` + `' · unmatched map node; select the namespace explicitly'` when `ep.node` is empty, `#capture-scope = ep.node ? 'lab' : 'host'`, clears search, `refreshCaptureTargets()`. The `onclick` handler is REPLACED on every `openCapture` (set to `null` when not a link).

### 3.2 Discovery (`refreshCaptureTargets`)

1. `invalidateCapture()`; snapshot `request`.
2. Reset UI: `captureTargets=[]`, `#capture-target` emptied, both interface lists emptied, `#capture-more` hidden, `#capture-prepare` disabled, `#capture-search` DISABLED, status `Discovering live capture targets…`.
3. Fire `refreshCaptureSessions()` (not awaited).
4. `GET /capture/status` → `captureEnabled`. Abort if stale request or dialog closed. If `!enabled`: status = `status.message`, re-enable search, `#capture-advanced.open=true`, return.
5. If `captureDrawing===undefined && captureLab`: `GET /labs/{lab}/topology` (error → `null`). `captureMapInterfaces = mapInterfacesFor(captureDrawing, captureNode)`.
6. `GET /capture/targets` with `lab_id` (+`node`) unless scope is `host` or no lab.
7. Store targets, re-enable search, status = `data.message` if any targets else `No live target matched. Refresh after starting the node, or choose All host targets under Advanced to select its namespace explicitly.`
8. `filterCaptureTargets()` (which also renders interfaces).
9. `#capture-advanced.open = !captureSelected()` — Advanced auto-unfolds only when no target could be auto-selected.
10. Any error (still current request, dialog open): status = `error.message`, re-enable search, `#capture-advanced.open=true`.

Re-triggered by: `#capture-refresh` "Refresh interfaces", `#capture-scope` change (also clears `captureHint`), endpoint buttons, every `openCapture`.

### 3.3 Interface lists (`renderCaptureInterfaces`)

- Starts with `invalidateCapture()` (so any re-render hides the Open Wireshark link).
- `live` = selected target's `interfaces`; `mapped` = `captureMapInterfaces` when `captureNode` set.
- `primary` = mapped ∩ live; `missing` = mapped − live; `rest` = live − primary (only when primary non-empty).
- `hinted` = `captureHint` if it is in `live`; otherwise, if exactly one primary interface, that one; else ''.
- Legend `#capture-primary-legend`: `Topology interfaces` when primary non-empty, else `Live Linux interfaces`.
- `#capture-interfaces` content: no target → `<p>Choose a capture target under Advanced, or open Capture from a node on the map.</p>`; otherwise checkboxes for `primary` (or all `live` if no primary), ticked only for `hinted`; if that yields nothing → `<p>No capturable interfaces in this namespace.</p>`.
- `#capture-interfaces-all` = checkboxes for `rest`, all unticked. `#capture-more.hidden = !rest.length`, `#capture-more.open=false` (collapsed on every render), `#capture-more-label = All live Linux interfaces ({rest.length})`.
- `updateCapturePrepare(!!hinted)`.
- Status hints (only when a target exists), first match wins:
  1. hinted → `Selected live interface {hinted}.`
  2. `captureHint` set but not live → `Imported port {hint} is not a live Linux interface name here. Select its Linux interface explicitly; NOS aliases can differ.`
  3. `missing.length` → `Topology port{s} {a, b} {are|is} not a live Linux interface name here; choose from the live list.`
  4. `primary.length>1` → `Tick the interfaces to capture.`
  (else status untouched)
- Checkbox change (either list, delegated `onchange`): `invalidateCapture()`, `updateCapturePrepare()`, status `Selection changed. Start a capture for these interfaces.`

### 3.4 Start browser capture (`#capture-form` submit)

- Enter inside `#capture-search` (type=search, inside the form) implicitly submits the form → same handler.
- Guard: `if(captureStarting) return`; `clearCaptureLaunch()`.
- Validation: no target or no ticked interface → status `Choose a target and at least one interface.` and return.
- `request=++captureRequest; captureStarting=true; #capture-prepare.disabled=true;` status `Checking interfaces and starting Wireshark on the VM…`.
- `captureLaunchId` generated (32 random bytes → 64 hex) only if empty; sent as `request_id` (idempotent retry key). Cleared ONLY on success ("A deliberate subsequent Start creates a new session; uncertain retries reuse their key.").
- `POST /capture/launch`; then `refreshCaptureSessions()`.
- If request stale or dialog closed → return silently.
- URL must match `^/static/capture-session\.html#[0-9a-f]{64}$`, else `Unsupported capture launch address.`
- Success: `#capture-launch.href=result.url; hidden=false;` status = `result.message`.
- Error (current request, dialog open): status = `error.message`.
- finally: `captureStarting=false; updateCapturePrepare()` (Start re-enabled per normal rule).

### 3.5 Open Wireshark in browser (`#capture-launch`)

`<a class="button primary" target="_blank" rel="noopener">` hidden until a successful launch. Clicking sets status `Browser viewer opened. Sessions and saved files remain on the VM until ended or expired.` (link still opens normally). Hidden again + href removed by ANY `invalidateCapture()`: target change, interface tick, scope change, refresh, endpoint switch, re-render, dialog `close` event.

### 3.6 Search (`#capture-search`)

`oninput → filterCaptureTargets()`: lowercase substring match of query against `[name, prefix, kind, ...aliases, ...interfaces].join(' ')`. Rebuilds `#capture-target` with placeholder `<option value="">Choose a capture target</option>` + matching rows. Keeps previous selection if still present; else auto-selects when exactly one row matches; then `renderCaptureInterfaces()`. Disabled during discovery; re-enabled after (including on error/disabled provider).

### 3.7 Target select (`#capture-target`)

Option label from `captureTargetLabel(t)`: `{name}[ · {prefix}] ({kind}) · {n} interfaces[ · shares namespace with {alias1, alias2}[ +N more]][ · loopback only]` — "loopback only" when the only interface is `lo`. `onchange → renderCaptureInterfaces()`.

### 3.8 Sessions in this browser

- `refreshCaptureSessions()`: race-guarded by `captureSessionRequest`; `GET /capture/sessions`; each session with a 64-hex id → `<li><a href="/static/capture-session.html#{id}" target="_blank" rel="noopener">{name} · {interfaces.join(', ')}</a> <button type="button" class="button secondary" data-end-capture="{id}">End session</button></li>`; none → `<li>No sessions in this browser.</li>`; fetch error → `#capture-sessions.textContent = 'Browser capture service unavailable or disabled. See Capture setup.'`.
- Triggered: at every discovery start, after launch (success or failure), `#capture-sessions-refresh` "Refresh sessions", after End.
- End session (delegated click on `[data-end-capture]`): `confirm('End this Wireshark session and delete its temporary captures? Download saved files first.')`; cancel → nothing. Button disabled; `POST /capture/sessions/{id}/end {}`; then refresh list. Error → `#capture-status = error.message` and button re-enabled.
- NOT auto-polled.

### 3.9 Close / invalidation

`#capture-close` → `captureDialog.close()`. Native `<dialog>` `close` event (× button, Escape key) → `invalidateCapture()`. Closing does not end sessions.

---

## 4. Session viewer page (`/static/capture-session.html#{sid}`)

`<body class="capture-viewer">` full-height flex column; `<title>Wireshark · Containerlab Node Manager</title>`; favicon `/static/fabric-mark.svg`.

Toolbar `<header class="capture-viewer-toolbar">`, in order:
1. `<a href="/" target="_blank" rel="noopener">Manager ↗</a>`
2. `<strong id="capture-name">Wireshark</strong>` → after status: `{name} · {ifaces}`
3. `<span id="viewer-status" role="status" aria-live="polite">Connecting to the VM…</span>`
4. `<details class="capture-viewer-help"><summary>How to save a capture</summary>` — text: "Stop the capture in Wireshark, choose **File → Save As**, save under **/pcaps** and type the full file name ending in **.pcapng**: Wireshark on the VM does not add the extension for you. Then click **Download saved captures** and extract the archive." / "Ending the session deletes its files. Closing this tab leaves the session for up to 15 minutes; every session expires after 2 hours." (when `[open]`, CSS moves it to full width, `order:10`)
5. `<a id="capture-download" class="button secondary" hidden>Download saved captures (.tar)</a>`
6. `<button id="capture-reconnect" type="button" class="button secondary">Reconnect viewer</button>`
7. `<button id="capture-end" type="button" class="button danger" disabled>End session</button>`

Then `<div id="capture-screen" aria-label="Remote Wireshark desktop"></div>` (noVNC canvas container; `flex:1; min-height:0; background:#263340`).

Behaviour (`connectViewer()` runs on load):
- Invalid hash (not 64 hex): status `Invalid session link. Open Capture packets in the manager.`; download stays hidden, End stays disabled, no heartbeat.
- Valid: `#capture-download.href = base+'/download'`, unhidden; `#capture-end.disabled=false`.
- `status()`: GET session; non-ok → `Error(detail || 'Session unavailable.')`; sets `#capture-name`; `!running` → `Error('Wireshark exited. Download saved files or end this session and start a new capture.')`.
- Readiness: up to 20 attempts, 1.5 s apart, `GET …/assets/core/rfb.js`; while waiting status `Starting the Wireshark desktop…`; abort if `ended`; give up → `The viewer is not ready. Check the capture service and click Reconnect viewer.`
- `import(rfb.js)`; `new RFB($('capture-screen'), ws(s)://host/api/capture/sessions/{sid}/websockify)`; `scaleViewport=true; resizeSession=true`.
- RFB events: `connect` → `Connected to Wireshark on the VM.`; `disconnect` (when not ended) → `Viewer disconnected. Reconnect to the existing session; capture may still be running.`; `securityfailure` → `Viewer authentication failed. Check the pinned capture image and service configuration.`
- Any thrown error → status = message.
- Download (`onclick`, preventDefault): status `Checking for saved captures…`; probe GET with AbortController; non-ok → `detail` or `Capture files unavailable.`; ok → abort probe, create `<a href=…/download download="wireshark-captures.tar">`, click, remove; status `Downloading saved captures. Extract the archive to get your .pcapng files.`; AbortError → `Download cancelled.`
- Reconnect → `location.reload()`.
- End: `confirm('End this session and delete its temporary captures? Download saved files first.')`; POST end; non-ok → `detail || 'Could not end session.'`; success: `ended=true`, clear heartbeat, `rfb.disconnect()` only if connected, End disabled, Download hidden, status `Session ended. Temporary captures were removed from the VM.`
- Heartbeat (valid sid only): `setInterval(30000)` → `status()`; if `remaining_seconds<300` → `Session expires in {ceil(remaining/60)} minutes. Save and download captures now.`; errors → status text. Not cleared on disconnect, only on End.

---

## 5. Setup page (`/static/capture-setup.html`) — static, no script

`<title>Browser capture setup · Containerlab Node Manager</title>`; `<main class="capture-guide">`.
- Link `<a href="/">← Manager</a>`
- H1 "Browser Wireshark setup"; intro "Wireshark runs on the lab VM and opens in your browser. No workstation plugin, VNC client or capture-port tunnel is needed."
- H2 "1. The VM services": install.sh / `sudo bash "$HOME/projects/clab-manager/deploy/setup-capture.sh"` (pre); "It pulls the pinned Wireshark image, builds the session service, starts Edgeshark, updates the capture settings while preserving unrelated configuration, and recreates the manager so it loads them. Download active browser captures before upgrading: restarting the service removes temporary sessions."; "The bundled stack needs free localhost ports 5001 and 5801. Setup does not remove another tool's Edgeshark installation; resolve conflicts first. Keep the manager on a trusted management network or use an authenticated HTTPS reverse proxy with WebSocket support."
- H2 "2. Capture in your browser": "Open **Capture packets**, a node's **Capture** action, or a topology link. Choose a live target and Linux interfaces, then **Start browser capture → Open Wireshark in browser**. On a link choose either endpoint. **All host targets** includes host NICs, bridges and other namespaces."
- H2 "3. Save, download and end": File → Save As under /pcaps; Download saved captures (.tar); End session deletes the container and its temporary files. "Four sessions can run at once. Closing a viewer leaves it available for up to 15 minutes under **Sessions in this browser**. Every session expires after two hours. The capture folder holds 256 MiB. Save and download before expiry; files do not enter backup or Git history."
- H2 "Troubleshooting" list: Disabled/unavailable; Viewer disconnected; Session not found; No matching interface; Download reports no saved captures; No packets. Then a `<pre>` with `sudo docker compose … ps`, `… logs --tail=80 sessions`, `bash "$HOME/projects/clab-manager/deploy/check-install.sh"`; "See **docs/CAPTURE.md** … Replace `$HOME/projects/clab-manager` if you cloned the source elsewhere."

---

## 6. Timers, polling, race guards

- capture.js: no periodic timers. One-shot `GET /capture/status` at load. `captureRequest` counter invalidates in-flight discovery/launch responses; `captureSessionRequest` invalidates stale session-list responses. Every async continuation also checks `captureDialog.open`.
- capture-session.js: `setInterval(30000)` heartbeat (valid sid only, cleared on End); readiness loop ≤20 × `setTimeout(1500)`.
- app.js toast (`notify`) 5 s timeout used by link-parse error.

## 7. Persistence

- No `sessionStorage` / `localStorage` reads or writes in any assigned file. (`activeId`, consumed for `captureLab`, is seeded by app.js from `sessionStorage['activeLab']`.)
- Browser cookie `clab_capture_owner` (set by backend, httponly) defines "Sessions in this browser".
- In-memory only: `captureLaunchId` idempotency key; `captureDrawing` per dialog open.
- URL hash carries the session id on the viewer page; the viewer page has no other state.
- Backend events recorded: `capture.launch`, `capture.end` (visible in Action logs, not by this UI).

## 8. Element ids / data attributes / classes relied on

Ids (index.html): `capture-dialog`, `capture-form`, `capture-title`, `capture-close`, `capture-context`, `capture-endpoints`, `capture-primary-legend`, `capture-interfaces`, `capture-more`, `capture-more-label`, `capture-interfaces-all`, `capture-status`, `capture-prepare`, `capture-launch`, `capture-advanced`, `capture-scope`, `capture-refresh`, `capture-search`, `capture-target`, `capture-sessions-refresh`, `capture-sessions`, `capture-open`, `details-dialog`, `topology-map` (as `map`), `node-context-menu` (via `closeNodeMenu`), `toast` (via `notify`).
Ids (capture-session.html): `capture-name`, `viewer-status`, `capture-download`, `capture-reconnect`, `capture-end`, `capture-screen`.
Data attributes: `data-capture` (node buttons, consumed by app.js), `data-capture-end` (endpoint buttons), `data-capture-endpoints` (SVG wires, produced by topology-render.js), `data-end-capture` (session list).
Classes with CSS: `.capture-dialog` (width min(740px,94vw), max-height 90vh, scroll; `[hidden]{display:none!important}` override; `fieldset` border; `.dialog-actions{flex-wrap:wrap}`; `h3{margin-top:22px}`), `.capture-controls`, `.capture-interfaces` (grid auto-fill 145px, max-height 240px scroll), `.capture-interface`, `.capture-more`, `.capture-advanced`, `.capture-viewer`, `.capture-viewer-toolbar`, `.capture-viewer-help`, `.capture-guide`, `.topology-wire[role="button"] path.capture-hit`, plus shared `.button.primary/.secondary/.danger`, `.icon-button`, `.form-help`, `.dialog-head`, `.dialog-actions`, `.actions`.

## 9. Redesign risks (easy to break)

1. `captureActionAttrs` is looked up by NAME with `typeof` guards in app.js and topology.js; renaming it silently removes the disabled/tooltip gating on node "Capture" buttons.
2. `openCapture(nodeName)` is called from app.js `handleNodeAction` for every `[data-capture]` button; signature and global name must survive.
3. Map wires must keep `data-capture-endpoints` (JSON of `[{node,label,interface}]`), `tabindex="0"`, `role="button"`, `aria-label`, and the invisible `path.capture-hit`; capture.js listens on `map` for click / contextmenu / Enter+Space via `closest('[data-capture-endpoints]')`. topology.js `pointerdown` pan handler also skips these elements.
4. Everything in the dialog sits inside `<form id="capture-form">`: Enter in the search box submits (= Start). Any new `<button>` inside the form without `type="button"` would trigger a launch.
5. `#capture-launch` and `#capture-more` are shown/hidden via the `hidden` attribute; `.capture-dialog [hidden]{display:none!important}` exists because `.button` sets its own display. Moving the link out of `.capture-dialog` or dropping that rule leaves the link always visible.
6. `#capture-more` and `#capture-advanced` are `<details>` whose `.open` property is set programmatically (auto-collapse of "more", auto-unfold of Advanced on disabled/error/no-target). A custom disclosure must expose the same property semantics.
7. `#capture-endpoints.onclick` is reassigned on every open (null when not a link); a persistent delegated handler would need to read the current `ends` array.
8. Interface selection is read from the DOM (`input:checked` values in the two containers by id); checkbox `value` must remain the raw interface name. Both containers must exist even when empty.
9. `#capture-target` selection is preserved across filtering by option `value` = target id; option label is derived text. The empty placeholder option must keep `value=""`.
10. Legend text (`Topology interfaces` / `Live Linux interfaces`) and `#capture-more-label` count are written via `textContent`; ids must persist.
11. Every visual re-render path calls `invalidateCapture()`; skipping it lets a stale "Open Wireshark" link survive a target/interface change.
12. `captureDialog.addEventListener('close', …)` relies on the native `<dialog>` close event (× and Escape). A non-dialog panel must emit the same invalidation.
13. `openCapture` closes `#details-dialog` first (drawer and capture dialog are never both open).
14. `#capture-search` is disabled during discovery and re-enabled in all completion branches; a re-implementation must not leave it disabled after an error.
15. Race guards (`captureRequest`, `captureSessionRequest`, `captureDialog.open` checks) prevent responses from an earlier node/scope overwriting the current view; rapid endpoint switching depends on them.
16. Session page defines its own `$` and uses raw `fetch` (no `/api` prefix helper); noVNC is loaded by dynamic `import()` from the same-origin `/api/capture/sessions/{sid}/assets/core/rfb.js`, and `#capture-screen` must be a sized block element (RFB needs a container with real dimensions; CSS gives `flex:1;min-height:0`, body `height:100vh;overflow:hidden`).
17. `#capture-download` is an `<a>` whose click is intercepted (`preventDefault`); the real download happens through a temporary anchor with `download="wireshark-captures.tar"`. Turning it into a plain link would render the JSON error body as a page (the comment in source says so).
18. Heartbeat is only started when the hash is valid and is only cleared on End; navigating within a SPA-style viewer would need to clear it.
19. `.capture-viewer-help[open]` gets `flex-basis:100%; order:10` so the help paragraph drops below the toolbar row.
20. capture-setup.html is pure static HTML and is linked from the dialog's Advanced section (`target=_blank`) and from `status.setup_url` in the backend; keep the path `/static/capture-setup.html`.
21. `?v=1.28.0` cache-busting query on `style.css` and `capture-session.js` in both standalone pages.

## 10. Microcopy that a CCNA-level student may not understand

| Text | Where | Problem |
|---|---|---|
| "live Linux interfaces", "Live Linux interfaces", "live list" | legend, status hints, more-toggle, link hint | assumes the student knows the NOS port maps to a Linux netdev in a container namespace |
| "namespace", "same namespace", "shares namespace with …", "select the namespace explicitly", "No capturable interfaces in this namespace." | option labels, more-help, status, context | Linux network-namespace / container concept |
| "NOS aliases can differ" | status hint, setup troubleshooting | "alias" here means the vendor interface name (ge-0/0/0) vs the Linux name (eth1) |
| "Imported port … is not a live Linux interface name here" / "Topology port(s) … not a live Linux interface name here" | status | "imported port" refers to the topology import feature |
| "unmatched map node" / "a node that discovery did not match" | context line, Advanced help | "discovery" and "map node" are app internals |
| "Edgeshark omits DOWN interfaces" | targets message (backend) | Edgeshark is the capture provider tool |
| "bridges, host NICs, other namespaces" | Advanced help, scope option, setup page | host-side Linux constructs |
| "Requires the optional browser capture services on the lab VM." | Advanced help | "services" = docker compose stack |
| "Browser capture service unavailable or disabled. See Capture setup." | sessions list error | |
| "Unsupported capture launch address." | status | internal URL validation |
| "Sessions in this browser" / "No sessions in this browser." | heading, list | browser-cookie ownership model is invisible |
| "Sessions and saved files remain on the VM until ended or expired." | status after opening viewer | |
| "Check the pinned capture image and service configuration." | viewer securityfailure | "pinned image" = Docker image tag |
| "Starting the Wireshark desktop…" / "Remote Wireshark desktop" | viewer status / aria-label | VNC desktop concept |
| "Download saved captures (.tar)" / "Extract the archive to get your .pcapng files." | viewer toolbar / status | tar archive step |
| "save under /pcaps and type the full file name ending in .pcapng: Wireshark on the VM does not add the extension for you." | viewer help | container path |
| "Ending the session deletes its files." / "deletes the container and its temporary files" | viewer help / setup page | container concept |
| "Refresh after starting the node" | no-target status | node lifecycle |
| "Topology interfaces" | legend | means ports wired in the saved diagram |
| "Selected lab / node" vs "All host targets" | scope select | "host" = the VM's own network stack |
| "Kind" in option label `({kind})` | target select | containerlab kind / Edgeshark type value |
| "Capture target" / "capture targets" | labels | Edgeshark discovery terminology |
| Setup page: "install.sh", "setup-capture.sh", "docker compose … ps/logs", "check-install.sh", "recreates the manager", "Edgeshark", "localhost ports 5001 and 5801", "HTTPS reverse proxy with WebSocket support", "browser profile", "nested VMs", "files do not enter backup or Git history", "docs/CAPTURE.md", "capture-port tunnel", "VNC client", "workstation plugin" | setup page | operator-level content mixed into a page the dialog links students to |
| "Packet capture is not enabled. Open Capture packets for setup." | disabled node-button tooltip | fine, but "setup" leads to the operator page |

## 11. Status / vocabulary reference

See section 2 (backend strings), 3.2–3.8 (dialog strings), 4 (viewer strings). Node-button tooltip: `Packet capture is not enabled. Open Capture packets for setup.` Toast: `Could not read this link. Use Capture packets to browse live interfaces.`

## 12. Confirmations

- Dialog list End session: `End this Wireshark session and delete its temporary captures? Download saved files first.` (native `confirm`)
- Viewer End session: `End this session and delete its temporary captures? Download saved files first.` (native `confirm`)
- No confirmation on Start, on closing the dialog, or on closing the viewer tab (help text explains the 15 min / 2 h retention instead).
