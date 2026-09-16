# Shell inventory — index.html + app.js

Files read completely:
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/index.html` (100 lines, 21,686 bytes)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/app.js` (180 lines, 24,485 bytes)

Cross-file facts below were verified by grep against the other files in `app/static/` (management.js, operations.js, git-progress.js, topology.js, capture.js, restore.js, diagram-editor.js, git-places.js, grafana.js, workspace.js). Nothing here is guessed; where a handler lives in another file it is stated.

Script load order (all `defer`, cache-busted `?v=1.28.0`): app.js → topology-render.js → topology.js → management.js → operations.js → diagram-editor.js → git-progress.js → git-places.js → restore.js → capture.js. Stylesheet `/static/style.css?v=1.28.0`. Favicon `/static/fabric-mark.svg`. `<title>` "Containerlab Node Manager · Network lab operations".

---

## 1. Globals defined in app.js

| Name | Kind | Purpose | Used by other files |
|---|---|---|---|
| `$` | const fn | `document.getElementById` shorthand | yes (every other file) |
| `esc` | const fn | HTML-escape `& < > " '` | yes (all other files) |
| `state` | let object | `{labs, jobs, platforms, operations?, git_jobs?, version?}` — full `/api/state` payload | yes (management, operations, diagram-editor, git-progress, restore, git-places) |
| `activeId` | let string | selected lab id; seeded from `sessionStorage.activeLab` | yes (management, topology, operations, capture, diagram-editor, git-progress) |
| `tab` | let string | current view: `topology`/`inventory`/`git`/`backups`/`credentials`/`logs`; default `'topology'` | yes (management sets `tab='inventory'` on remove; operations, topology, git-progress read) |
| `toastTimer` | let | toast auto-hide timer | no |
| `current()` | fn | lab object for `activeId` or `undefined` | yes (topology, management, restore, capture, git-progress, operations, git-places) |
| `busy()` | fn | true when any `state.jobs` is queued/running, or any `state.operations` queued/running, or any `state.git_jobs` in queued/capturing/exporting/pushing | yes (management, topology, git-progress, operations) |
| `notify(message)` | fn | toast: sets `#toast` text, unhides, hides after 5000 ms (resets timer) | yes (topology, management, operations, capture, git-progress, restore, diagram-editor) |
| `api(path, options)` | async fn | `fetch('/api'+path)`; on non-OK parses JSON `detail` (string → Error message; otherwise 'Check the form fields and try again.'; unparsable → 'Request failed') | yes (all) |
| `json(path, method, data)` | async fn | `api` with JSON body + `Content-Type: application/json`, returns parsed JSON | yes (all) |
| `refresh()` | async fn | GET `/api/state` → `state`; if current lab gone, `activeId = state.labs[0]?.id || ''`; `render()`; if `tab==='logs'` → `refreshLogs()` | yes (restore, management, git-progress, operations, capture) |
| `selectLab(id)` | fn | closes `#details-dialog` if open; `activeId=id`; `tab='topology'`; `sessionStorage.setItem('activeLab',id)`; clears `#search` and `#log-job`; `render()` | yes (git-progress) |
| `platformLabel(kind)` | fn | `state.platforms[kind]?.label` else `'Generic SSH / Linux'` for `ssh` else `'Unmapped'` | yes (git-progress) |
| `badge(status)` | fn | `<span class="badge {good|bad|running|warn}">status</span>`; good = Ready/succeeded/reachable; bad = failed/unreachable/interrupted; running = queued/running; else warn | yes (git-progress, restore) |
| `profileName(lab,node)` | fn | label of `node.profile_id || lab.defaults[node.platform||'ssh']`; else 'From inventory' (node.inventory_credentials) / 'Containerlab default login' (credential_source==='default') / 'Not configured' | no |
| `sshHint(n)` | fn | disabled-reason for SSH button from `n.nos_login.status` | yes (topology) |
| `grafanaPath(lab)` | fn | `/d/{map_uid||'clab-lab-overview'}?var-lab=<name>&refresh=10s` when `lab.telemetry.grafana.enabled && port`, else `''` | no |
| `grafanaLaunch(lab)` | fn | `/static/grafana.html#path=…&title=…` or `''` | no |
| `renderGrafanaLink(lab)` | fn | shows/hides `#grafana-open` and sets href/text/title | no |
| `render()` | fn | master render of sidebar, topbar, heading, footer, metrics, buttons; calls `renderManagement`, `renderLabOperations`, `renderGitProgress` (if defined), then `renderNodes`, `renderProfiles`, `renderJobs`, `showTab(tab)`, `refreshHealth()` | yes (diagram-editor) |
| `renderNodes()` | fn | nodes table rows (search-filtered), diffed via `$('nodes')._markup` | no |
| `nodeActions(n, details=false)` | fn | action-button markup shared by table row and details drawer | no |
| `renderProfiles()` | fn | credential profile cards | no |
| `renderJobs()` | fn | backup history job accordions | no |
| `utcDisplay(value)` | fn | `YYYY-MM-DD HH:MM:SS UTC` or 'Time unavailable' | yes (git-places, git-progress, restore) |
| `showTab(value)` | fn | sets `tab`, updates `#extra-views-label`, `[data-tab]` active/aria-selected, hides/shows `#{name}-view` for inventory/topology/credentials/backups/logs/git; topology → `refreshMap()`, git → `gitShowRepository()` | yes (git-progress) |
| `openImport(replace=false)` | fn | resets `#import-form`, prefills lab id/name when replacing, sets `#import-title`, `showModal()` | yes (management) |
| `platformOptions(includeUnknown)` | fn | `<option>` list from `state.platforms` (+ blank 'Choose network OS') | no |
| `openProfile()` | fn | no-op without lab; resets profile form; fills `#profile-platform` (+ 'Generic SSH / Linux (terminal only)' value `ssh`); `toggleAuth()`; showModal | no |
| `toggleEnable()` | fn | `#enable-fields.hidden = platform !== 'arista_ceos'` | no |
| `toggleAuth()` | fn | calls toggleEnable; shows password vs key fields; `#private-key.required = isKey` | no |
| `openNode(name)` | fn | fills `#node-form` from node; `#node-endpoint-mode.disabled = !lab.deployment_name`; showModal | no |
| `withForm(form, fn)` | async fn | disables `button[type=submit]`, clears `.form-error`, runs fn, writes error to `.form-error` (or toast if none), re-enables | yes (management, topology) |
| `handleNodeAction(e)` | async fn | delegated click handler for `data-capture/edit/details/terminal/backup/check` buttons | no |
| `startJob(operation, node_names?)` | async fn | POST `/api/labs/{id}/jobs`; `tab='backups'`; refresh; toast | no |
| `attachmentName(response, fallback)` | fn | filename from `Content-Disposition` (`filename*=UTF-8''` then `filename=""`) | yes (topology, diagram-editor, git-progress) |
| `handleDownload(e)` | async fn | `[data-logs]` → jump to logs filtered by job; `[data-download]` → blob download | no |
| `healthState`, `healthRequest`, `detailName` | let | health cache `{lab,nodes}`, request sequence, open-drawer node name | no |
| `nodeHealth(name)` | fn | health entry for node if `healthState.lab===activeId` | no |
| `refreshHealth()` | async fn | GET `/api/labs/{id}/health` with stale-response guard; re-renders nodes + drawer; on error clears health | no |
| `openDetails(name)` | fn | sets `detailName`, `renderDetails()`, showModal | yes (topology) |
| `renderDetails()` | fn | fills drawer; closes drawer if node vanished | no |
| `logEvents`, `logRequest` | let | last log payload, request sequence | no |
| `refreshLogs()` | async fn | GET `/api/logs?…limit=1000`; renders `#log-rows`, `#log-status` | no |

## 2. Globals app.js consumes from other files (all guarded with `typeof … === 'function'` except `openCapture`)

| Name | Defined in | Called from app.js at |
|---|---|---|
| `renderManagement()` | management.js:61 | `render()` |
| `renderLabOperations()` | operations.js:267 | `render()` |
| `renderGitProgress()` | git-progress.js:45 | `render()` |
| `refreshMap(force)` | topology.js:32 | `showTab('topology')` |
| `gitShowRepository(force)` | git-progress.js:61 | `showTab('git')` |
| `captureActionAttrs()` | capture.js:12 | `nodeActions()` — returns `disabled title="Packet capture is not enabled. Open Capture packets for setup."` when `captureEnabled===false` (capture.js fetches `/api/capture/status` once at load) |
| `openCapture(node, hint, ends)` | capture.js:89 | `handleNodeAction` (unguarded; closes `#details-dialog` itself) |

## 3. Handlers app.js sets that a LATER script overwrites (effective behaviour = the later file)

| Element | app.js sets | management.js (loads later) sets → EFFECTIVE |
|---|---|---|
| `#new-lab` "Manual discovery" | `openImport()` | `openSetup()` (management.js:107) |
| `#import-empty` "Import a lab definition" | `openImport()` | `openSetup()` (management.js:107) |
| `#import-top` heading button | `openImport(!!current())` | `current() ? openImport(true) : openDeploy()` (management.js:111) |
| `#map-ssh-all` | (only disabled/title in render) | click → `opNewTab({mode:'ssh', lab:lab.id})` (management.js:226) |
| `#map-backup-all` | (only disabled in render) | click → review dialog `backup-all-review` "Back up all configurations" with "{ready} of {total} nodes are ready for a configuration backup. This includes ready nodes that are unchecked in the inventory." + skip list "These nodes will be skipped:" + `#backup-all-confirm` "Back up N nodes" (disabled if none ready or busy) → POST `/labs/{id}/jobs {operation:'backup', node_names}` → toast 'Configuration backup started. View progress in Backup history.' (management.js:227-232) |

operations.js additionally: inserts `<button class="button secondary" id="lab-actions" hidden>Lab actions ▾</button>` immediately before `#import-top` (operations.js:277), shows it only when a lab is current (operations.js:271), click → `openLabOperations()`; adds `contextmenu` and `keydown` (ContextMenu key or Shift+F10) on `#labs` for `[data-lab]` → `openLabOperations(labId)` (operations.js:282-283). management.js adds the same two handlers on `#excluded-labs` for `[data-allow-import]` → `openExclusionMenu(...)` (management.js:224-225).

---

## 4. Layout and static chrome (index.html)

### Sidebar `<aside class="sidebar">`
- Brand block: `<img class="brandmark" src="/static/fabric-mark.svg" alt="">`, "Containerlab Node Manager", `<small>NETWORK LAB OPERATIONS</small>`.
- `<div class="side-label">LAB WORKSPACES </div>` (note trailing space).
- `<nav id="labs" aria-label="Labs">` — initial `<p class="side-hint">Your labs will appear here.</p>`.
- Buttons (all `class="side-button"`): `#vm-projects` "Deploy New Lab" (`side-primary`), `#inspect-all` "View running lab details", `#vm-settings` "VM connection", `#vm-refresh` "Refresh discovery", `#operations-history` "Operation history", `#new-lab` "Manual discovery".
- `<p class="side-hint" id="operation-summary" role="status">` (operations.js), `<p id="vm-summary" class="side-hint" role="status">` (management.js).
- `#discovered-labs`, `#excluded-labs` (management.js), `<details id="discovery-files"><summary>Discovery file details</summary><div id="discovery-file-list">` (management.js fills list; nothing binds `discovery-files` itself).
- `.side-bottom`: `<span class="side-caption" id="supported-release">Supported device types as of release 1.24.0</span>` (app.js rewrites to current version), `<p>Junos / IOS-XR / EOS</p>`, `<a class="text-button" href="/static/debug.html">Debug panel</a>`, `<button id="manager-settings" class="text-button">Manager settings</button>` (management.js).

### Main / topbar
- `<header class="topbar">`: crumb "Workspace <span>/</span> <strong id="breadcrumb">Overview</strong>", `<span class="worker-state" id="worker-state">Worker idle</span>`.

### Page heading
- `.eyebrow` "NETWORK ENGINEERING WORKSPACE"; `<h1 id="title">Your next lab starts here.</h1>`; `<p class="subtitle" id="subtitle">Import your nodes. Connect, experiment, and keep your configurations close.</p>` (HTML default only — app.js overwrites on first render); `<button class="button primary" id="import-top">↑ Import inventory</button>` (text overwritten by render()).

### Empty panel `<section id="empty" class="empty-panel">` — hidden when a lab is selected
- `.file-icon` "LAB" (aria-hidden), `<h2>Deploy a lab on your VM</h2>`, paragraph "Browse the topology files on your VM, pick one and deploy it. The workspace, map and node logins are ready the moment the devices finish booting. Nothing to import by hand."
- `.empty-actions`: `#deploy-empty` "Deploy a new lab" (primary; management.js/operations.js), `#vm-connect-empty` "Connect the VM" (secondary, `hidden` by default; management.js `openVmDialog()`).
- `<p id="empty-vm-note" class="empty-vm-note" role="status">` (management.js).
- `<div id="empty-discovered" class="empty-discovered" hidden><h3>Already running on the VM</h3><div id="empty-discovered-list">` (management.js; click `[data-setup-name]` → `importDiscovered`).
- `.platform-pills`: Junos / IOS-XR / Arista EOS.
- `.empty-note`: "Have lab files instead? " `<button class="link-button" id="import-empty">Import a lab definition</button>` " · " `<button class="link-button" id="import-inventory-empty">Import an Ansible inventory</button>` (management.js → `openImport()`).

### Lab content `<div id="lab-content" hidden>` — shown when a lab is selected
- **Deployment bar** `<section class="deployment-bar">`: `<strong id="deployment-status">`, `<p id="deployment-message">`, `<small id="deployment-checked">`, `<p id="deployment-nos" class="deployment-nos" role="status">`, `<p id="vm-files-status" role="status">` — all management.js. Actions: `#lab-start` "Start lab" (primary, `disabled` in HTML; operations.js `opQuickRun('start')`), `#lab-destroy` "Destroy lab" (`danger-outline`, `disabled`; operations.js `opQuickRun('destroy')`), `#sync-vm` "Sync from VM" (`hidden`; management.js/operations.js), `#update-definition` "Update lab YAML" (management.js `openSetup(true)`), `#link-deployment` "Link deployment" (operations.js/management.js), `#remove-lab` "Remove lab" (management.js/operations.js; on removal of the active lab management.js clears `activeId`, removes `sessionStorage.activeLab`, sets `tab='inventory'`, closes `#details-dialog`).
- **Metrics** `<section class="metrics" aria-label="Lab summary">`: "Lab nodes" `#node-count`, "Selected for backup" `#enabled-count`, "Credentials ready" `#ready-count`, "Backup schedule" `#schedule-summary` (default "Manual").
- **Git progress bar** `<section id="git-progress-bar" class="git-progress-bar" aria-label="Save lab progress">` (git-progress.js): `<button id="git-open-settings" class="text-button git-destination" title="Git repository settings"><strong id="git-destination">Connect a repository to save your lab progress</strong></button>`, `<p id="git-progress-status" role="status">Capture configurations, commit and push in one step.</p>`, `.git-save-control`: `#git-save-progress` "Connect Git repository" (primary), `<details id="git-save-menu" class="git-save-menu" hidden><summary class="button primary" aria-label="More save progress actions">▾</summary>` with `.git-save-options` buttons `data-git-action`: `local` "Save locally", `checkpoint` "Save checkpoint…", `baseline` "Set baseline…", `history` "View changes / History", `load` "Load version…", `push` "Push saved progress", `update` "Update from remote", `settings` "Git repository settings".
- **Control row**: `<nav class="tabs" aria-label="Workspace views">`: `data-tab="topology"` "Topology" (class `active`, aria-selected true), `data-tab="inventory"` "Nodes", `data-tab="git"` "Git repository", `data-tab="backups"` "Backup history", `<details id="extra-views" class="extra-views"><summary id="extra-views-label">More</summary><div class="extra-views-menu">` with `data-tab="credentials"` "Credentials", `data-tab="logs"` "Action logs". `.actions`: `<a class="button secondary" id="grafana-open" target="_blank" rel="noopener" hidden>Grafana ↗</a>`, `#capture-open` "Capture packets" (capture.js), `#export-sessions` "Export sessions" (topology.js), `#test` "Test NOS login", `#backup` "Back up now →".
- **Git view** `<section id="git-view" class="view" hidden>`: h2 "Git repository", p "Choose where this lab saves its progress. Git authentication belongs to the repository owner on the VM.", `#git-repository-refresh` "Refresh status", `#git-repository-content` (git-progress.js).
- **Topology view** `<section id="topology-view" class="view" hidden>`: h2 "Lab topology", p "Right-click a node for SSH, backups and capture. Click a link to capture either endpoint."; `.actions`: `#map-ssh-all` "SSH all nodes ↗", `#map-backup-all` "Back up all configs", `#import-map` "Import topology" (primary; topology.js). `.map-tools`: `#map-expand` "Expand map", `#map-fit` "Fit map", `#map-in` "+" (aria-label "Zoom in"), `#map-out` "-" (aria-label "Zoom out"), `<span>Drag to pan · Links show imported wiring, not live status</span>`, `#map-edit` "Edit diagram" (operations.js). `<p id="map-status" role="status">` (topology.js). `<svg id="topology-map" viewBox="0 0 1000 600" aria-label="Lab topology" role="group">` (topology.js / topology-render.js).
- **Logs view** `<section id="logs-view" class="view" hidden>`: h2 "Action logs", p "Live job steps and application actions. Refreshed every four seconds. Newest first.", `#download-logs` "Download logs". `.log-filters`: "Scope" `<select id="log-scope">` (`lab` "Current lab", `all` "All worker actions"); "Level" `<select id="log-level">` (`""` "All levels", `error`, `warning`, `info`); "Node" `<input id="log-node" placeholder="Filter node name">`; "Job ID" `<input id="log-job" placeholder="All jobs">`; `#refresh-logs` "Refresh". `<p id="log-status" role="status">`. Table headers: "UTC time / level", "Node / job", "Action", "Details"; `<tbody id="log-rows">`.
- **Inventory (Nodes) view** `<section id="inventory-view" class="view">` (the only view not `hidden` in HTML): h2 "Nodes", `<p id="inventory-caption">Select the nodes to include.</p>`, `<input id="search" type="search" placeholder="Filter nodes…" aria-label="Filter nodes">`. Table headers: `<span class="sr-only">Include in scheduled backups</span>`, "Node / SSH endpoint", "Platform / credentials", "Last SSH check", "Last backup", "Actions"; `<tbody id="nodes">`. `.notice`: "Checkboxes select nodes for lab-wide and scheduled backups. SSH checks are on demand; their timestamps show when access was last verified."
- **Credentials view** `<section id="credentials-view" class="view" hidden>`: h2 "NOS credential profiles", p "Use a default account per platform, or assign a profile to an individual node.", `#add-profile` "+ Add credentials" (primary), `<div id="profiles" class="profile-grid">`, `.notice`: "Credentials already present in the inventory are available automatically. An assigned profile takes precedence. Secrets are never displayed after saving."
- **Backups view** `<section id="backups-view" class="view" hidden>`: h2 "Backup history", p "Download individual device configurations or the complete ZIP. All backup timestamps use UTC.", `<form id="schedule-form" class="schedule-form">`: `<label for="interval">Every</label><input type="number" id="interval" min="0" max="10080" value="0"><span>minutes</span><button class="button secondary" type="submit">Save</button><small>0 = manual</small>`; `<div id="jobs">`.
- **Footer**: "Containerlab Node Manager / SSH &amp; configuration history · `<span id="app-version">v1.24.0</span>`", `<span id="updated">No inventory loaded</span>`.

### Global
- `<div id="toast" role="status" hidden>`.
- `<div id="node-context-menu" class="node-context-menu" role="menu" aria-label="Node actions" hidden>` (topology.js).

---

## 5. Dialogs declared in index.html (every control)

### `#import-dialog` / form `#import-form` — handled by app.js (opened by `openImport`, also by management.js `#import-inventory-empty` and `#import-top` when a lab is current)
- `.dialog-head`: eyebrow "INVENTORY UPLOAD", `<button type="button" class="icon-button close" aria-label="Close">×</button>`.
- `<h2 id="import-title">Import a lab</h2>` (→ "Replace lab inventory" when replacing).
- p "Use containerlab’s generated Ansible inventory. No node addresses are built into this image."
- `<input type="hidden" name="lab_id" id="import-lab-id">`.
- "Lab name" `<input id="lab-name" name="name" required maxlength="120" placeholder="A name for this lab">`.
- "Ansible inventory `<span class="required">required</span>`" `.upload-field`: `<input id="inventory-file" name="inventory" type="file" accept=".yml,.yaml,.json" required>`, `<small>YAML or JSON · up to 1 MiB</small>`.
- `<details><summary>Optional: topology metadata</summary>` p.form-help "Upload `topology-data.json` if custom inventory groups do not identify the node kinds." `<input name="topology" type="file" accept=".json">`.
- `<p class="form-error" role="alert">`; actions: "Cancel" (`.close`, type button), "Import and review" (submit).
- Submit: `withForm` → POST `/api/inventory` multipart(FormData: lab_id, name, inventory, topology) → `activeId=result.id`; `sessionStorage.activeLab`; close; reset; `tab='inventory'`; `refresh()`; toast "Inventory imported. Review the nodes and credentials." Errors → `.form-error`.

### `#profile-dialog` / form `#profile-form` — app.js
- eyebrow "NOS AUTHENTICATION", close ×; h2 "Add credentials"; p "These credentials log in to the network operating system."
- "Profile name" `<input id="profile-label" name="label" required maxlength="120" placeholder="Lab administrators">`.
- `.form-grid`: "Network OS" `<select id="profile-platform" name="platform">` (filled by `openProfile`: every `state.platforms` entry + `<option value="ssh">Generic SSH / Linux (terminal only)</option>`); "NOS username" `<input id="profile-user" name="username" required autocomplete="off">`.
- `<div id="enable-fields">` (hidden unless platform `arista_ceos`): "EOS enable password `<span class="muted">optional</span>`" `<input id="enable-password" name="enable_password" type="password" autocomplete="new-password">`, help "EOS sessions enter enable mode before retrieval. Leave blank when the account does not require an enable password."
- "Authentication" `<select name="auth" id="auth-type">`: `password` "Password", `key` "SSH private key". `onchange` → `toggleAuth`.
- `<div id="password-fields">` "NOS password" `<input id="profile-password" name="password" type="password" autocomplete="new-password">` (hidden when key).
- `<div id="key-fields" hidden>` "SSH private key" `<input id="private-key" name="private_key" type="file">` (required when key), "Key passphrase optional" `<input id="passphrase" name="passphrase" type="password" autocomplete="new-password">`.
- `<label class="checkbox-label"><input type="checkbox" id="make-default" checked> Use as the default for this NOS in this lab</label>`.
- `.form-error`; "Cancel" (`.close`); "Save credentials" (submit).
- Submit: FormData + `make_default` = 'true'/'false' → POST `/api/labs/{activeId}/profiles` (multipart) → close; reset; refresh; toast "NOS credentials saved."
- No UI to edit or delete a profile exists in these files.

### `#node-dialog` / form `#node-form` — app.js (opened by "Edit connection" in the details drawer)
- eyebrow "NODE CONNECTION", close ×; `<h2 id="node-title">Edit node</h2>` (→ node inventory name); `<input id="node-name" type="hidden">`.
- "Download device name optional" `<input id="node-short-name" maxlength="200" placeholder="Detected automatically">`, help "Use a short name such as GTW-1 if the inventory name has an ambiguous lab prefix. New backups retain this name."
- `.form-grid.wide`: "NOS management IP or DNS" `<input id="node-address" required>`; "SSH port" `<input id="node-port" type="number" min="1" max="65535" required>`.
- "Address source" `<select id="node-endpoint-mode">`: `manual` "Manual address and port", `auto` "Automatic from VM discovery" — **disabled when `!lab.deployment_name`**. Help "Automatic uses the discovered management address and SSH port 22. Manual preserves your custom endpoint."
- "Network OS" `<select id="node-platform">` (`platformOptions(true)` → leading "Choose network OS" blank option).
- "Credential profile" `<select id="node-profile">`: `""` "NOS default / inventory credentials" + one option per profile "`{label} · {username}`".
- `<label class="checkbox-label"><input type="checkbox" id="node-enabled"> Include in backups</label>`.
- `.form-error`; "Cancel" (`.close`); "Save connection" (submit).
- Submit: PUT `/api/labs/{activeId}/node` JSON `{name, short_name, address, port:Number, endpoint_mode, platform, profile_id, enabled}` → close; refresh; toast "Connection updated."

### `#details-dialog` (class `node-details`, aria-labelledby `details-title`) — app.js
- `.drawer-head`: eyebrow "NODE WORKSPACE", `<button class="icon-button close" aria-label="Close node details">×</button>`, `<h2 id="details-title">`, `<p id="details-endpoint" class="endpoint">`, `<div id="details-actions" class="node-actions drawer-actions">` (filled with `nodeActions(n,true)`: Capture, SSH ↗, Back up, Test login, Edit connection).
- `.drawer-content`: `<div id="details-info">` (rendered sections "Connection settings" and "Last SSH check"), `<section class="drawer-section"><h3>Configuration history</h3><p class="section-description">Saved snapshots, ready when you need them.</p><div id="node-history">`.
- Closed by: its close button, `selectLab`, Edit connection, Back up, `openCapture` (capture.js:91), Remove lab (management.js:169), and `renderDetails` when the node no longer exists. Re-rendered on every health poll while open.

### `#map-dialog` / form `#map-form` — topology.js
- h2 "Import lab topology"; label "VS Code annotations JSON" `<input type="file" name="annotations" accept=".json" required>`; label "Lab topology YAML or topology-data.json" `<input type="file" name="topology" accept=".yaml,.yml,.json">`; help "Annotations supply positions, groups, and notes. Include the topology file to draw links. Imports replace the current map. Connections and credentials remain in your inventory."; `.form-error`; `#cancel-map` "Cancel"; submit "Import map".

### `#export-dialog` / form `#export-form` — topology.js
- h2 "Export SuperPuTTY sessions"; p "One lab folder, with a session for every inventory node using its short name and saved SSH address and port."; help "Saved credentials take priority. Otherwise, known NOS kinds supply the default username. Your workstation must be able to reach these addresses."; `<label class="checkbox-label"><input type="checkbox" id="export-passwords"> Include saved passwords as plain text</label>`; help "Optional passwords use PuTTY's -pw argument. Private keys are not exported. Without a saved password, PuTTY prompts at login."; `.form-error`; `#cancel-export` "Cancel"; submit "Download XML".

### `#capture-dialog` (class `capture-dialog`, aria-labelledby `capture-title`) / form `#capture-form` — capture.js
- `.dialog-head`: `<h2 id="capture-title">Capture packets</h2>`, `<button type="button" class="icon-button" id="capture-close" aria-label="Close packet capture">×</button>` (NOT class `.close`; capture.js binds it).
- `<p id="capture-context">`; `<div id="capture-endpoints" class="actions">`.
- help "Wireshark runs on the lab VM and opens in your browser; nothing is installed on the workstation."
- `<fieldset><legend id="capture-primary-legend">Topology interfaces</legend><div id="capture-interfaces" class="capture-interfaces">`.
- `<details id="capture-more" class="capture-more" hidden><summary id="capture-more-label">All live Linux interfaces</summary>` help "Management, fabric and internal interfaces of the same namespace. Tick any of them to add it to the capture." `<div id="capture-interfaces-all" class="capture-interfaces">`.
- `<p id="capture-status" role="status" aria-live="polite">`.
- actions: `<button class="button primary" id="capture-prepare" type="submit" disabled>Start browser capture</button>`, `<a class="button primary" id="capture-launch" target="_blank" rel="noopener" hidden>Open Wireshark in browser ↗</a>`.
- `<details id="capture-advanced" class="capture-advanced"><summary>Advanced: other capture targets</summary>` help "The target is the node you clicked. Use this for bridges, host NICs, other namespaces, or a node that discovery did not match." `.capture-controls`: "Scope" `<select id="capture-scope">` (`lab` "Selected lab / node", `host` "All host targets"), `<button type="button" id="capture-refresh" class="button secondary">Refresh interfaces</button>`; "Find a target or interface" `<input id="capture-search" type="search" placeholder="Node, bridge, host NIC or interface">`; "Capture target" `<select id="capture-target">`; help "Requires the optional browser capture services on the lab VM. `<a href="/static/capture-setup.html" target="_blank" rel="noopener">Capture setup and troubleshooting ↗</a>`".
- `<h3>Sessions in this browser</h3>`, `<button type="button" id="capture-sessions-refresh" class="button secondary">Refresh sessions</button>`, `<ul id="capture-sessions">`.

---

## 6. Capabilities (every user action and every auto-rendered piece of information)

Format: **id** — label — location — trigger — behaviour — gating — API — state fields — persistence — student relevance.

### Sidebar

1. **sidebar.brand** — "Containerlab Node Manager / NETWORK LAB OPERATIONS" with `fabric-mark.svg` — sidebar top — static — no behaviour. secondary.
2. **sidebar.lab-list** — lab buttons — `#labs` — auto on every `render()` — sorted favourites first; each `<button class="lab-item [active]" data-lab="{id}">` text `★ ` (if `favorite`) + name + `<small>{nodes.length} nodes · {deployment.status || 'Unlinked'}</small>`; empty → `<p class="side-hint">Your labs will appear here.</p>`. Reads `state.labs[].id/name/favorite/nodes/deployment.status`. primary.
3. **sidebar.select-lab** — click a lab — `#labs` delegated click on `[data-lab]` — `selectLab(id)`: closes details drawer, `tab='topology'`, clears `#search` and `#log-job`, writes `sessionStorage.activeLab`, `render()`. primary.
4. **sidebar.lab-context-menu** — right-click / ContextMenu key / Shift+F10 on a lab — operations.js:282-283 → `openLabOperations(labId)`. (Handled in operations.js; listed because it is on a shell element.) secondary.
5. **sidebar.deploy-new-lab** — "Deploy New Lab" — `#vm-projects` — click → `location.assign('/static/workspace.html#mode=folder')` (operations.js:281). primary.
6. **sidebar.view-running-lab-details** — "View running lab details" — `#inspect-all` — operations.js `opTask(null, () => opReview({action:'inspect-all'}))`. secondary.
7. **sidebar.vm-connection** — "VM connection" — `#vm-settings` — management.js. secondary.
8. **sidebar.refresh-discovery** — "Refresh discovery" — `#vm-refresh` — management.js. advanced.
9. **sidebar.operation-history** — "Operation history" — `#operations-history` — operations.js `opHistory()`. secondary.
10. **sidebar.manual-discovery** — "Manual discovery" — `#new-lab` — app.js binds `openImport()` but management.js:107 overwrites with `openSetup()` (effective). Label does not describe either behaviour. advanced.
11. **sidebar.operation-summary** — status text — `#operation-summary` role=status — operations.js. secondary.
12. **sidebar.vm-summary** — status text — `#vm-summary` role=status — management.js. secondary.
13. **sidebar.discovered-labs** — `#discovered-labs` — management.js. secondary.
14. **sidebar.excluded-labs** — `#excluded-labs` — management.js; right-click / ContextMenu / Shift+F10 on `[data-allow-import]` → `openExclusionMenu`. advanced.
15. **sidebar.discovery-file-details** — `<details id="discovery-files">` "Discovery file details" → `#discovery-file-list` — native details toggle; list filled by management.js. advanced.
16. **sidebar.supported-release** — "Supported device types as of release {version}" + "Junos / IOS-XR / EOS" — `#supported-release` — auto in `render()` from `state.version || '1.28.0'` (guarded `if($('supported-release'))`). secondary.
17. **sidebar.debug-panel-link** — "Debug panel" — `<a href="/static/debug.html">` — navigates same tab. advanced.
18. **sidebar.manager-settings** — "Manager settings" — `#manager-settings` — management.js. advanced.

### Topbar / heading / footer

19. **shell.breadcrumb** — "Workspace / {lab name | Overview}" — `#breadcrumb` — auto. secondary.
20. **shell.worker-state** — `#worker-state` — auto: 'Saving lab progress' if any `state.git_jobs[].status` ∈ queued/capturing/exporting/pushing; else 'SSH job in progress' if `busy()`; else 'Worker idle'. secondary.
21. **shell.title** — `#title` = `lab.name` or 'Your next lab starts here.'. primary.
22. **shell.subtitle** — `#subtitle` = lab ? 'Your nodes, connections, and configuration history.' : 'Deploy a topology from your VM, or pick up a lab that is already running.'. secondary.
23. **shell.import-top** — `#import-top` text = lab ? '↑ Replace inventory' : 'Deploy a new lab' — app.js binds `openImport(!!current())`; management.js:111 overrides: lab → `openImport(true)`, no lab → `openDeploy()`. primary.
24. **shell.lab-actions** — "Lab actions ▾" — `#lab-actions` injected by operations.js:277 before `#import-top`; hidden when no lab; click → `openLabOperations()`. secondary.
25. **shell.empty-vs-lab-toggle** — `#empty.hidden = !!lab`, `#lab-content.hidden = !lab`. primary.
26. **shell.footer-version** — `#app-version` = 'v' + (`state.version` || '1.28.0'). secondary.
27. **shell.footer-updated** — `#updated` = 'Inventory updated ' + `new Date(lab.updated).toLocaleString()` or 'No lab selected'. secondary.
28. **shell.toast** — `#toast` — `notify(msg)`: sets text, `hidden=false`, auto-hide after 5000 ms (timer reset per call). Also written by workspace.js. primary.

### Empty panel (no lab selected)

29. **empty.deploy** — "Deploy a new lab" — `#deploy-empty` — management.js / operations.js. primary.
30. **empty.connect-vm** — "Connect the VM" — `#vm-connect-empty` — hidden by default; management.js `openVmDialog()`. secondary.
31. **empty.vm-note** — `#empty-vm-note` role=status — management.js. secondary.
32. **empty.discovered-list** — "Already running on the VM" `#empty-discovered` / `#empty-discovered-list` — hidden by default; management.js; click `[data-setup-name]` → `importDiscovered`. primary.
33. **empty.import-lab-definition** — "Import a lab definition" — `#import-empty` — app.js `openImport()` overridden by management.js `openSetup()`. secondary.
34. **empty.import-ansible-inventory** — "Import an Ansible inventory" — `#import-inventory-empty` — management.js `openImport()` (app.js import dialog). advanced.
35. **empty.platform-pills** — "Junos", "IOS-XR", "Arista EOS" — static. secondary.

### Deployment bar (lab selected; handlers in other files)

36. **deployment.status-text** — `#deployment-status`, `#deployment-message`, `#deployment-checked`, `#deployment-nos`, `#vm-files-status` — management.js. primary.
37. **deployment.start** — "Start lab" `#lab-start` — HTML `disabled`; operations.js `opTask(null, () => opQuickRun('start'))`. primary.
38. **deployment.destroy** — "Destroy lab" `#lab-destroy` — HTML `disabled`; operations.js `opQuickRun('destroy')`. primary.
39. **deployment.sync-vm** — "Sync from VM" `#sync-vm` — HTML `hidden`; management.js/operations.js. secondary.
40. **deployment.update-yaml** — "Update lab YAML" `#update-definition` — management.js `openSetup(true)`. advanced.
41. **deployment.link** — "Link deployment" `#link-deployment` — operations.js/management.js. advanced.
42. **deployment.remove-lab** — "Remove lab" `#remove-lab` — management.js/operations.js; on active lab clears `activeId`, removes `sessionStorage.activeLab`, `tab='inventory'`, closes drawer. secondary.

### Metrics

43. **metrics.node-count** — "Lab nodes" `#node-count` = `lab.nodes.length`. primary.
44. **metrics.enabled-count** — "Selected for backup" `#enabled-count` = nodes with `enabled`. primary.
45. **metrics.ready-count** — "Credentials ready" `#ready-count` = enabled nodes with `readiness==='Ready'`. primary.
46. **metrics.schedule-summary** — "Backup schedule" `#schedule-summary` = `lab.interval` ? (`lab.deployment && status ∉ {Running, Unlinked}` ? 'Paused · ' : '') + interval + ' min' : 'Manual'. primary.

### Git progress bar (git-progress.js)

47. **git.destination** — `#git-open-settings` (title "Git repository settings") / `#git-destination` "Connect a repository to save your lab progress" — git-progress.js. secondary.
48. **git.progress-status** — `#git-progress-status` "Capture configurations, commit and push in one step." — git-progress.js. secondary.
49. **git.save-progress** — "Connect Git repository" `#git-save-progress` — git-progress.js. secondary.
50. **git.save-menu** — `#git-save-menu` (hidden) ▾ "More save progress actions" with `data-git-action` local/checkpoint/baseline/history/load/push/update/settings — git-progress.js. advanced.

### Tabs / control row

51. **tabs.switch** — Topology / Nodes / Git repository / Backup history / More ▸ Credentials, Action logs — `[data-tab]` click → `showTab`, closes `#extra-views`, logs tab → `refreshLogs()` (errors toasted). `showTab`: `#extra-views-label` text 'Credentials'/'Action logs'/'More' and `.active` when tab ∈ credentials/logs; `.active` + `aria-selected` on buttons; toggles `hidden` on `#inventory-view`, `#topology-view`, `#credentials-view`, `#backups-view`, `#logs-view`, `#git-view`; topology → `refreshMap()`; git → `gitShowRepository()`. Default tab `'topology'`; after import `'inventory'`; after a job `'backups'`. primary.
52. **actions.grafana** — `#grafana-open` link — hidden unless `lab.telemetry.grafana.enabled && port`; text 'Lab map in Grafana ↗' (map_uid) / 'Grafana ↗'; title 'Live weathermap of this lab in Grafana: link rates, port and node state.' or 'Live dashboards for this lab in Grafana: interface rates, link state, BGP neighbours.' + ' Grafana starts on the VM when it is not running.'; href `/static/grafana.html#path=/d/{map_uid||clab-lab-overview}?var-lab={name}&refresh=10s&title={name}`; opens new tab. advanced.
53. **actions.capture-open** — "Capture packets" `#capture-open` — capture.js. secondary.
54. **actions.export-sessions** — "Export sessions" `#export-sessions` — topology.js (opens `#export-dialog`). secondary.
55. **actions.test-nos-login** — "Test NOS login" `#test` — `startJob('test')` → POST `/api/labs/{id}/jobs {operation:'test'}`; `tab='backups'`; refresh; toast 'Testing NOS login with show version.'; error toast. Disabled when `busy() || enabled.length===0 || ready.length!==enabled.length`; title 'Complete credentials for enabled nodes' when ready≠enabled. primary.
56. **actions.backup-now** — "Back up now →" `#backup` — `startJob('backup')` → POST `/api/labs/{id}/jobs {operation:'backup'}`; toast 'Backup started.'; same gating/title as 55. primary.

### Topology view (shell-owned bits; map itself is topology.js)

57. **topology.ssh-all** — "SSH all nodes ↗" `#map-ssh-all` — app.js sets `disabled = !lab.nodes.some(ssh_ready)`; title '' if any ready, 'Waiting for the NOS to accept SSH logins; this opens automatically' if any `nos_login.status==='booting'`, else 'No node is ready for SSH'. Click handled by management.js:226 `opNewTab({mode:'ssh', lab:lab.id})`. primary.
58. **topology.backup-all** — "Back up all configs" `#map-backup-all` — app.js `disabled = busy() || !lab.nodes.some(readiness==='Ready')`. Click handled by management.js:227-232 (review dialog + confirm, see §3). primary.
59. **topology.import-map** — "Import topology" `#import-map` — topology.js opens `#map-dialog`. secondary.
60. **topology.map-tools** — Expand map / Fit map / + / - / "Drag to pan · Links show imported wiring, not live status" / Edit diagram (`#map-edit`, operations.js) — topology.js. secondary.
61. **topology.map-status** — `#map-status` role=status — topology.js. secondary.
62. **topology.node-context-menu** — `#node-context-menu` role=menu "Node actions" — topology.js (uses `sshHint`, `openDetails` from app.js). primary.

### Nodes table

63. **nodes.search** — `#search` "Filter nodes…" — `oninput` → `renderNodes()`; case-insensitive substring over `name + ' ' + address + ' ' + platformLabel(platform)`; cleared by `selectLab`. primary.
64. **nodes.caption** — `#inventory-caption` = `${lab.source} · ${enabled.length} selected` (HTML default 'Select the nodes to include.'). secondary.
65. **nodes.row** — one `<tr>` per matching node: [checkbox] [name button + endpoint] [platform badge + credential label] [SSH check badge + timestamp] [backup badge + timestamp] [actions]. Rendered only when markup differs (`$('nodes')._markup`). Empty: `<td colspan="6" class="table-empty">No matching nodes. Try another name, address, or platform.</td>`. primary.
66. **nodes.include-checkbox** — `<input type="checkbox" data-enable="{name}" aria-label="Include {name}">` — checked = `enabled`; **disabled when `!n.platform`**; `change` → PUT `/api/labs/{id}/node {name,address,port,platform,profile_id,enabled}` then `refresh()`; on error revert checkbox, toast, `renderNodes()`. primary.
67. **nodes.name-button** — `<button class="node-name" data-details>` text `short_name || name` + `<span class="endpoint">{address}:{port}</span>` — click → `openDetails`. primary.
68. **nodes.platform-badge** — `<span class="badge platform">{platformLabel}</span>` + `<span class="secondary-text">{profileName}</span>`. primary.
69. **nodes.last-ssh-check** — `badge(h.ssh.status)` or `<span class="status-neutral">Not checked</span>`; `<span class="timestamp">` = `utcDisplay(h.ssh.at)` or 'Run a login check'. primary.
70. **nodes.last-backup** — `badge(h.backup.status)` or 'No backup yet'; timestamp `utcDisplay(h.backup.at)` or ''. primary.
71. **node-actions.capture** — "Capture" `data-capture` — `openCapture(name)`; disabled with title 'Packet capture is not enabled. Open Capture packets for setup.' when capture.js `captureEnabled===false`. secondary.
72. **node-actions.ssh** — "SSH ↗" `.ssh-action data-terminal` — `window.open('/static/terminal.html#lab={activeId}&node={name}&label={lab.name}', '_blank')`; disabled with title `sshHint(n)` when `!n.ssh_ready`: booting → 'NOS is still booting; SSH opens when it accepts a login'; failed → 'SSH login failed with the saved credentials; assign a credential profile'; unavailable → 'Node is not running'; otherwise 'Assign credentials first'. primary.
73. **node-actions.backup** — "Back up" `data-backup` — closes drawer; `startJob('backup',[name])`; disabled title 'Requires a supported NOS, credentials, and an idle worker' when `busy() || readiness!=='Ready'`. primary.
74. **node-actions.details** — "Details →" `.details-action data-details` aria-label 'Details for {name}' (table only) → `openDetails`. primary.
75. **node-actions.test-login** — "Test login" `data-check` (drawer only) — disabled when `!(login_configured ?? ssh_ready)` (no title); click → button disabled during POST `/api/labs/{id}/ssh-check {name}`; toast `result.message`; `refreshHealth()` if same lab; error toast. primary.
76. **node-actions.edit-connection** — "Edit connection" `data-edit` (drawer only) — closes drawer; `openNode(name)`. primary.
77. **nodes.notice** — static notice text under table. secondary.

### Credentials view

78. **credentials.add** — "+ Add credentials" `#add-profile` — `openProfile()` (silently no-op without a lab). primary.
79. **credentials.card** — per profile `<article class="profile-card">`: platform badge, `<h3>{label}</h3>`, `<p>{username}</p>`, `<span class="profile-type">` 'SSH private key' | 'Password authentication', `<small>Default for this NOS</small>` when `lab.defaults[platform]===id`. Empty: blank-state "Add your NOS credentials" / "Create a profile for each platform that needs one.<br>Credentials included in the uploaded inventory work automatically." primary.
80. **credentials.notice** — static notice. secondary.

### Backup history view

81. **backups.schedule-form** — "Every [n] minutes [Save] 0 = manual" — submit → PUT `/api/labs/{id}/schedule {interval:Number}`; refresh; toast 'Backup schedule saved.'; `render()` writes `lab.interval` into `#interval` unless it has focus. primary.
82. **backups.job-accordion** — per job (`state.jobs` where `lab_id===lab.id`, API order): `<details class="job" data-job>`; open state preserved across re-renders; summary: `<strong>` 'NOS login test' (+ ' · automatic' when `source==='automatic'`) or 'Configuration backup'; `<small>{utcDisplay(started||created)} · {nodes.length} nodes</small>`; `badge(status)`. Body: `<p>{message}</p>`. Empty: blank-state "No jobs yet" / "Test the NOS login, then run a backup. Individual configurations and full archives appear here." primary.
83. **backups.view-action-logs** — "View action logs" `data-logs={jobId}` — sets `#log-job`=id, clears `#log-level`/`#log-node`, `showTab('logs')`, `refreshLogs()`. secondary.
84. **backups.job-node-result** — per node: `<strong>{short_name||name}</strong>` badge(status), message, `<small>Captured {utc}` + ' (historical job timestamp)' when `capture_time_source==='legacy job time'`. primary.
85. **backups.download-config** — "↓ Download config" `data-download={jobId} data-node-index={i} data-filename` — shown only when operation backup, job finished, node succeeded with `download_name`; GET `/api/jobs/{id}/nodes/{index}/download` → blob → `<a download>` named from Content-Disposition or `data-filename`; button disabled during; error toast; `URL.revokeObjectURL` after 1 s. primary.
86. **backups.download-zip** — "↓ Download all (ZIP)" `data-download={jobId} data-filename={archive_name}` + `<small>{archive_name} · UTC</small>` — shown when backup finished and any node succeeded with download_name; GET `/api/jobs/{id}/download`. primary.

### Node details drawer

87. **details.open** — `openDetails(name)` → `showModal()`; title `short_name||name`; endpoint `address:port`. primary.
88. **details.actions** — `nodeActions(n,true)` (Capture, SSH ↗, Back up, Test login, Edit connection), diffed via `_markup`. primary.
89. **details.connection-settings** — dl: Inventory name (mono), Network OS, Credential profile, Backup selection ('Included in lab backups' / 'Excluded from lab backups'), Backup readiness (`readiness || 'Choose NOS'`). primary.
90. **details.last-ssh-check** — badge or 'Not checked'; message or 'Run Test login to verify SSH access with the saved credentials.'; `<time>` utc + ' · automatic readiness check' when `h.ssh.source==='automatic'`; help 'Nodes of a deployed lab are checked automatically until the NOS accepts a login; Test login verifies the saved credentials right now.'. primary.
91. **details.configuration-history** — entries from finished backup jobs of this lab where this node succeeded with download_name: `<strong>` 'Latest successful backup' (first) / 'Backup', `<small>utc(captured_at||finished||created)</small>`, `<code>download_name</code>`, "Download config" button (same download path as 85). Empty 'No saved configurations for this node.'. primary.
92. **details.close** — × "Close node details" (`.close`) → `dialog.close()`; native Esc also closes (showModal). primary.

### Action logs view

93. **logs.filters** — Scope (`lab`/`all`), Level (''/error/warning/info), Node text, Job ID text — each `change` → `refreshLogs()`. secondary.
94. **logs.refresh** — "Refresh" `#refresh-logs` → `refreshLogs()`. secondary.
95. **logs.table** — rows `time<br>level | node||'Worker'<br><small>job_id</small> | action | message` from GET `/api/logs?lab_id={activeId or ''}&job_id&level&node&limit=1000` (stale responses dropped via `logRequest`). secondary.
96. **logs.status** — `#log-status`: '{n} events shown (latest 1,000 matching events). Updated {toLocaleTimeString}.' or 'Could not refresh logs: {error}'. secondary.
97. **logs.download** — "Download logs" `#download-logs` → NDJSON blob (`application/x-ndjson`) of `logEvents`, filename `backup-action-logs.jsonl`. advanced.
98. **logs.auto-refresh** — while `tab==='logs'`, every 4 s `refresh()` also calls `refreshLogs()`. secondary.

### Dialog capabilities (app.js-owned)

99. **dialog.import** — see §5; submit POST `/api/inventory`. primary.
100. **dialog.profile** — see §5; submit POST `/api/labs/{id}/profiles`; auth switch shows/hides password vs key fields; EOS enable fields only for `arista_ceos`. primary.
101. **dialog.node** — see §5; submit PUT `/api/labs/{id}/node`; Address source select disabled without `lab.deployment_name`. primary.
102. **dialog.close-buttons** — every element with class `.close` present at load closes its closest `<dialog>` (import, profile, node, details). primary.

### Polling / lifecycle

103. **shell.initial-load** — `refresh()` once; error → toast. primary.
104. **shell.poll-state** — `setInterval(refresh, 4000)` (errors swallowed); each `render()` also calls `refreshHealth()` → GET `/api/labs/{id}/health` (so health is polled every 4 s while a lab is selected; stale responses dropped via `healthRequest`; on error health cleared and rows re-rendered). primary.
105. **shell.active-lab-persistence** — `sessionStorage.activeLab` read at startup; written by `selectLab` and import; removed by management.js on remove-lab; if the stored lab no longer exists, first lab auto-selected. primary.

---

## 7. API calls made by app.js

| Method | Path | Where |
|---|---|---|
| GET | `/api/state` | `refresh()` (load + every 4 s) |
| GET | `/api/labs/{id}/health` | `refreshHealth()` (every render) |
| GET | `/api/logs?lab_id&job_id&level&node&limit=1000` | `refreshLogs()` |
| POST | `/api/inventory` (multipart: lab_id, name, inventory, topology) | import form |
| POST | `/api/labs/{id}/profiles` (multipart: label, platform, username, enable_password, auth, password, private_key, passphrase, make_default) | profile form |
| PUT | `/api/labs/{id}/node` (JSON) | node form; include checkbox |
| PUT | `/api/labs/{id}/schedule` (JSON `{interval}`) | schedule form |
| POST | `/api/labs/{id}/jobs` (JSON `{operation, node_names?}`) | `startJob` (Test NOS login, Back up now, row Back up) |
| POST | `/api/labs/{id}/ssh-check` (JSON `{name}`) | drawer Test login |
| GET | `/api/jobs/{id}/download` | ZIP download |
| GET | `/api/jobs/{id}/nodes/{index}/download` | per-node config download |
| GET | `/api/capture/status` | capture.js (one-shot at load; feeds `captureActionAttrs`) |

## 8. State fields read by app.js

`state.version`, `state.platforms[kind].label`, `state.labs[]`: `id, name, favorite, nodes[], deployment.status, deployment_name, updated, source, interval, profiles[] {id,label,platform,username,auth}, defaults{platform→profileId}, telemetry.grafana{enabled,port,map_uid}`; node: `name, short_name, address, port, platform, profile_id, enabled, readiness, ssh_ready, login_configured, nos_login.status, inventory_credentials, credential_source, endpoint_mode`; `state.jobs[]`: `id, lab_id, operation, status, source, started, created, finished, message, archive_name, nodes[] {name, short_name, status, message, captured_at, capture_time_source, download_name}`; `state.operations[].status`; `state.git_jobs[].status`; health: `nodes[] {name, ssh{status,at,message,source}, backup{status,at}}`; logs: `events[] {time, level, node, job_id, action, message}`.

## 9. Status vocabulary (raw strings shown to the user)

| Term | Where | Meaning |
|---|---|---|
| Worker idle / SSH job in progress / Saving lab progress | `#worker-state` | no job; a backup/test/operation queued or running; a git job running |
| queued, running | job badges, busy() | job lifecycle |
| succeeded, failed, interrupted, partial | job & node badges (partial referenced by git-progress.js) | job outcome |
| Ready | `readiness`, ready-count, Back up gating | node has supported NOS + credentials |
| Choose NOS | drawer Backup readiness fallback | readiness missing |
| reachable / unreachable | health `ssh.status` badges | last SSH check result |
| booting / failed / unavailable | `nos_login.status` → sshHint | why SSH is disabled |
| Not checked / Run a login check | table SSH column | no health entry |
| No backup yet | table backup column | no health backup entry |
| Unlinked, Running (and any other `deployment.status`) | lab list small text, schedule summary | deployment link state |
| Manual / N min / Paused · N min | `#schedule-summary` | schedule |
| From inventory / Containerlab default login / Not configured | credential label | credential source when no profile |
| Included in lab backups / Excluded from lab backups | drawer | `enabled` |
| · automatic | job title, drawer time | `source==='automatic'` |
| (historical job timestamp) | job node capture time | `capture_time_source==='legacy job time'` |
| Password authentication / SSH private key | profile card | `auth` |
| Default for this NOS | profile card | lab.defaults |
| Generic SSH / Linux, Unmapped | platform label fallbacks | kind `ssh` / unknown |
| Time unavailable | utcDisplay | unparsable date |
| error / warning / info | log level | log severity |
| Worker | log Node column | event without node |
| Latest successful backup / Backup | drawer history | ordering label |

## 10. Timers and polling

- `setInterval(() => refresh().catch(()=>{}), 4000)` — state poll; drives `render()` → `refreshHealth()`; and `refreshLogs()` when logs tab open.
- `notify`: `setTimeout(hide, 5000)` with `clearTimeout` on each call.
- Downloads and log export: `setTimeout(() => URL.revokeObjectURL(url), 1000)`.
- Request-sequence guards: `healthRequest`, `logRequest` (stale responses ignored); lab-id guard in `refreshHealth` and drawer Test login.
- capture.js: one-shot `GET /api/capture/status` at load.

## 11. Element ids used by app.js (unguarded unless noted)

labs, toast, app-version, supported-release (guarded), worker-state, empty, lab-content, title, breadcrumb, subtitle, import-top, updated, node-count, grafana-open (guarded), map-ssh-all, map-backup-all, enabled-count, ready-count, schedule-summary, test, backup, inventory-caption, interval, search, nodes, profiles, jobs, extra-views-label (guarded), extra-views (guarded), inventory-view/topology-view/credentials-view/backups-view/logs-view/git-view (guarded), import-form, import-lab-id, lab-name, import-title, import-dialog, profile-form, profile-platform, profile-dialog, enable-fields, auth-type, password-fields, key-fields, private-key, node-form, node-title, node-name, node-short-name, node-address, node-port, node-endpoint-mode, node-platform, node-enabled, node-profile, node-dialog, new-lab, import-empty, add-profile, make-default, schedule-form, details-dialog, details-actions, details-title, details-endpoint, details-info, node-history, log-job, log-level, log-node, log-scope, log-rows, log-status, refresh-logs, download-logs.

Data attributes relied on: `data-lab`, `data-tab`, `data-enable`, `data-details`, `data-capture`, `data-terminal`, `data-backup`, `data-check`, `data-edit`, `data-logs`, `data-download`, `data-node-index`, `data-filename`, `data-job`, `data-git-action` (git-progress.js). Classes relied on: `.close`, `.form-error`, `button[type=submit]`, `.job[open]`, `.lab-item.active`, `.badge`, `.node-actions`.

## 12. Microcopy a CCNA-level student would not understand

See structured output; highlights: "Manual discovery", "Refresh discovery", "Discovery file details", "Worker idle"/"SSH job in progress"/"All worker actions"/"Worker", "Link deployment"/"Unlinked", "Update lab YAML", "Sync from VM", "Containerlab default login", "No node addresses are built into this image", "Ansible inventory", "topology-data.json … node kinds", "NOS" everywhere, "Generic SSH / Linux (terminal only)", "Unmapped", "Automatic from VM discovery", "VS Code annotations JSON", "SuperPuTTY … -pw argument", "Job ID", "backup-action-logs.jsonl", "(historical job timestamp)", "Grafana"/"weathermap", "namespace"/"bridges"/"host NICs", "browser capture services", every Git term (repository, commit, push, checkpoint, baseline, remote), "Requires a supported NOS, credentials, and an idle worker", `lab.source` raw value in the nodes caption, raw badge strings (reachable/unreachable/interrupted/partial), "Time unavailable", "Check the form fields and try again.", "Request failed", "ambiguous lab prefix", "endpoint".

## 13. Redesign risks

1. Script load order: management.js re-assigns `onclick` for `#new-lab`, `#import-empty`, `#import-top`, `#map-ssh-all`, `#map-backup-all` after app.js. Changing ids, order, or moving to `addEventListener` will double-fire or lose the effective behaviour.
2. operations.js inserts `#lab-actions` with `insertAdjacentHTML('beforebegin')` on `#import-top`; `#import-top` must exist at load and the injected button inherits its layout context.
3. Top-level bindings in app.js (lines 101-178) are unguarded `$(...).onclick = …` / `addEventListener`. Removing or renaming any listed id throws at load and aborts every later binding, including the 4 s poll.
4. `.close` buttons are bound once at load for dialogs present in index.html; new/moved dialogs need their own binding.
5. Event delegation: `#nodes`, `#details-actions`, `#jobs`, `#node-history`, `#labs` rely on `closest('button')`/`closest('[data-*]')`. Action controls must stay `<button>` elements carrying the same `data-*` attributes; `data-node-index` must remain the node's index within `job.nodes`.
6. `_markup` diff caches on `#nodes` and `#details-actions`: any other code writing those containers leaves the cache stale.
7. `showTab` derives section ids as `${tab}-view`; `[data-tab]` buttons and `#extra-views`/`#extra-views-label` (with text 'More'/'Credentials'/'Action logs') must be kept or `showTab` rewritten.
8. Job accordion open state is preserved via `.job[open]` + `data-job`; changing `<details>` to another widget loses it across the 4 s re-render.
9. `#interval` keeps the user's typed value only while focused; the poll overwrites it otherwise.
10. Forms depend on `.form-error` inside the form and `button[type=submit]` for `withForm`; FormData field names (`lab_id,name,inventory,topology`; `label,platform,username,enable_password,auth,password,private_key,passphrase,make_default`) are the backend contract.
11. `selectLab` clears `#search` and `#log-job`; `handleDownload` writes `#log-job`, `#log-level`, `#log-node`; log filters must keep those ids/values (`lab`/`all`, `''`/`error`/`warning`/`info`).
12. `#grafana-open` is an `<a>` toggled with `hidden` and `href` removal; `#capture-open` gating text comes from capture.js.
13. Disabled-state rules are computed in app.js (`#map-ssh-all`, `#map-backup-all`, `#test`, `#backup`, per-row buttons) while some click handlers live elsewhere; both halves must survive.
14. `sessionStorage.activeLab` is the only persisted UI state; `tab` resets to `topology` on lab select, `inventory` after import/remove, `backups` after starting a job.
15. `renderDetails` re-renders drawer content every 4 s while open (details-info/node-history replaced wholesale) — a redesign that adds inputs or scroll containers inside the drawer will lose state each poll.
16. Native `<dialog>.showModal()` provides Esc-to-close; replacing with custom panels drops that.
17. Deployment-bar buttons start `disabled`/`hidden` in HTML and are enabled by operations.js/management.js renders; HTML defaults matter.
18. The node checkbox is disabled when `!n.platform`; the `change` handler PUTs the full node record (not just `enabled`).
19. Version strings: `?v=1.28.0` cache busters on all assets and the `'1.28.0'` fallback in `render()`.
20. Lab list ordering (favourites first, `★` prefix) and `deployment.status || 'Unlinked'` sub-text.
