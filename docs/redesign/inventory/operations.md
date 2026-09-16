# Inventory: operations.js (lab lifecycle operations)

Source: `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/operations.js` (284 lines, 31,259 bytes; read completely, every line).
Reference markup: `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/index.html` (100 lines) and `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/workspace.html` + `workspace.js` (standalone "Deploy New Lab" / SSH launcher tab that also loads operations.js).

Line 2 comment: "Shared by the main workspace and independent VM-folder / SSH-launcher tabs."

## 1. Load context

- index.html loads (all `defer`, in order): app.js, topology-render.js, topology.js, management.js, **operations.js**, diagram-editor.js, git-progress.js, git-places.js, restore.js, capture.js. `v=1.28.0` cache-buster.
- workspace.html loads: workspace.js, topology-render.js, **operations.js**, diagram-editor.js. `<body class="standalone-workspace">`. It has `#workspace-open` ("Lab Topologies" card → `opTask(null,()=>opBrowse(params.get('path')||'',activeId))`) and `#workspace-history` ("Operation history" card → `opHistory()`), a "← Back to lab manager" link to `/`, and a "Debug panel" link. Hash params: `mode=folder` (browse) or `mode=ssh&lab=<id>` (SSH launcher: lists nodes, "Open all ready sessions ↗", per-node "SSH ↗" links to `/static/terminal.html#lab=&node=&label=`, max 32 popups). Those SSH-launcher behaviours live in workspace.js, not operations.js.
- The whole bottom wiring block of operations.js (lines 274-284) runs only when `#import-top` exists, i.e. only on index.html.
- `api(path)` (app.js / workspace.js) prefixes `/api`, so every path below is really `/api/...`. `json(path,method,data)` = api + JSON body + `.json()`.

## 2. Globals defined (all top-level in a classic script → window globals)

| Name | Kind | Purpose | Called from other files |
|---|---|---|---|
| `opLabels` | const object | action → visible label: deploy "Deploy lab", redeploy "Redeploy", destroy "Destroy deployment", apply "Apply topology", start "Start lab nodes", stop "Stop lab nodes", restart "Restart lab nodes", save "Save configurations (clab)", inspect "Inspect lab", inspect-all "View running lab details", create "Create VM topology", delete "Delete undeployed VM YAML", clone "Clone repository" | no |
| `opCaps` | let (null) | cached result of GET /operations/capabilities | **written** by management.js:215 (`opCaps=null` after Remove lab) |
| `opMenuLab` | let ('') | set to the lab id in openLabOperations; never read anywhere | no |
| `opOutputTimer` | let | setTimeout handle of the job-output 1 s poll | no |
| `opEditorContext` | let (null) | set in opEdit to `{path,labId,isNew}`; never read anywhere | no |
| `opDialog(id,title,body)` | function | get-or-create `<dialog id class="operations-dialog">` appended to body; sets innerHTML = dialog-head (eyebrow "NODE MANAGER" + `×` close button `[data-op-close]` aria-label "Close") + `<h2>` title (escaped) + body + `<p class="form-error" role="alert">`; close button → dialog.close(); showModal() if not open; returns dialog | diagram-editor.js:13; git-progress.js:127,134,149,156,195,218,237 |
| `opTask(dialog,fn)` | async function | clears `.form-error`; disables every currently-enabled `button` in the dialog; runs fn; on error writes `e.message` into `.form-error` (or `notify(e.message)` when dialog is null); re-enables those buttons in finally; returns fn's value | diagram-editor.js:80-82; git-places.js:98-100; git-progress.js:98 (passes a `<form>`), 107; workspace.js:24 |
| `opPath(lab)` | function | `lab.vm_project_path || lab.vm_source.files.definition.path || ''` | no |
| `opName(lab)` | function | `lab.deployment_name || lab.name || ''` — **unused everywhere** | no |
| `opCapabilities()` | async | GET /operations/capabilities → opCaps | no |
| `opCommand(action,label,options)` | function | HTML for `<button class="button secondary" data-op-action data-op-options=JSON>`; when `opCaps.actions[action]` exists and `.available` is false: `disabled` + `<small>Unavailable on this VM</small>` | no |
| `opDestroyOptions(caps)` | function | `{}` when `caps.actions.destroy.cleanup===false`, otherwise `{cleanup:true}` (also when caps unreadable) | no |
| `openLabOperations(id=activeId)` | async | the "Lab actions" dialog (section 4) | no (only from within: button, context menu, keyboard) |
| `teleStateLabels` | const | telemetry node state → word: disabled "off", waiting, configuring, connecting, streaming, stale, unsupported, failed, unmonitored | no |
| `telemetrySummaryText(data)` | function | summary sentence for the telemetry dialog | no |
| `telemetryGrafanaText(g)` | function | Grafana state sentence | no |
| `openTelemetrySettings(id=activeId)` | async | Telemetry settings dialog (section 5) | no |
| `opReview(request)` | async | POST /operations/preview then the confirmation dialog; confirm → POST /operations/confirm (section 6) | no |
| `opInspectionRows(output)` | function | tolerant parser of `containerlab inspect` JSON (scans up to 100 leading/trailing lines for the JSON block); returns rows `{topology,lab,node,kind,image,state,ipv4,ipv6}`; hard cap 10,000 rows | no |
| `opInspectionTable(rows)` | function | `<div class="op-inspection"><table>` with caption "{n} deployed nodes" and columns Topology, Lab, Node, Kind / image, State / health, IPv4 / IPv6 | no |
| `opJobBanner(job)` | function | `{tone:'good'|'bad'|'running', title, detail}` | no |
| `opShowJob(id)` | async | Operation output dialog with polling (section 7) | no |
| `opHistory(labId='')` | async | Operation history dialog (section 8) | workspace.js:24 |
| `opReadAnnotations(path)` | async | POST /operations/read `{path: path+'.annotations.json'}` → text or '' (errors swallowed) | no |
| `opParse(path,text)` | async | reads annotations then POST /operations/parse-yaml `{options:{text,annotations}}`; returns parsed + `annotations` (kept only when `parsed.annotations_used`) | no |
| `opWorkspaceForm(path,source,parsed)` | function | FormData: `definition` = Blob(source.text, text/yaml) named basename; `annotations` = Blob(json) named basename+'.annotations.json' when present | no |
| `opSaveWorkspace(path,source,parsed,labId='')` | async | reuse lab whose `deployment_name===parsed.name` or `opPath(l)===path`, else POST /lab-definitions (multipart); then PUT /labs/{id}/operations-settings `{path}`; sets `activeId` and `sessionStorage.activeLab`; returns id | no |
| `openDeploy()` | function | `opTask(null,()=>opBrowse())` | management.js:111 (`#import-top` click when no current lab) |
| `opNewTab(values)` | function | `window.open('/static/workspace.html#'+URLSearchParams,'_blank')`; if blocked → dialog `op-open-tab` "Open workspace": "Your browser may have blocked the new tab." + `<a class="button primary" target=_blank rel=opener>Open workspace ↗</a>` | management.js:226 (`#map-ssh-all`) |
| `opTopologyEntries(entries)` | function | keeps directories and names matching `/\.clab\.ya?ml$/i` | no |
| `opBrowse(path='')` | async | "Lab Topologies" browser dialog (section 9) | workspace.js:24 (passes a 2nd arg `activeId` which the signature ignores) |
| `opEdit(path,labId='',newPath='')` | async | topology viewer/creator dialog (section 10) | no |
| `opClone(url='',project='')` | function | Clone dialog (section 11) | no |
| `opPopular()` | async | Popular labs dialog (section 12) | no |
| `opMapPreview(drawing,name,positioned=false)` | function | topology preview dialog (section 13) | no |
| `opLayout(id)` | async | `editDiagram(id)` (diagram-editor.js) | no |
| `opQuickActions(lab,discovery,isBusy)` | function | gating for Start/Destroy buttons (section 3) | no |
| `opQuickRun(kind)` | async | runs the quick Start/Deploy or Destroy review | no |
| `renderLabOperations()` | function | per-render gating of deployment-bar buttons and sidebar summary (section 3) | app.js:52 inside `render()` (after `renderManagement()`, before `renderGitProgress()`) |

## 3. Globals consumed (defined elsewhere)

`$` (app.js:3 / workspace.js:2), `esc` (app.js:3 / workspace.js:2), `notify` (app.js:7 / workspace.js:5; 5 s toast into `#toast`), `api` (app.js:8 / workspace.js:6), `json` (app.js:15 / workspace.js:7), `state` (app.js:4 / workspace.js:3; fields used: `labs`, `operations`, `discovery`), `activeId` (read and **assigned**), `refresh` (app.js:16 = GET /state + render(); workspace.js:9 = GET /state only, no render), `current()` (app.js:5 / workspace.js:4), `busy()` (app.js:6 / workspace.js:4), `topologyMarkup` + `measureTopology` (topology-render.js:41,45), `editDiagram` (diagram-editor.js:11), `sessionStorage` (key `activeLab`), native `window.confirm`.

## 4. Main-page wiring block (lines 274-284, runs only if `#import-top` exists)

1. Injects `<button class="button secondary" id="lab-actions" hidden>Lab actions ▾</button>` **before** `#import-top` (the "↑ Import inventory" primary button in `.page-heading`).
2. `#map-edit` ("Edit diagram", topology view `.map-tools`) → `opTask(null,()=>opLayout(activeId))`. No null guard.
3. `#deploy-empty` ("Deploy a new lab", empty panel) → `openDeploy` (guarded with `if`). Its disabled state and title ("Connect the VM to browse its topologies") are set by management.js `renderLanding`.
4. `#lab-actions` → `openLabOperations()` (active lab).
5. `#vm-projects` (sidebar "Deploy New Lab", class side-button side-primary) → `location.assign('/static/workspace.html#mode=folder')` (same-tab navigation).
6. `#lab-start` (deployment bar "Start lab", primary) → `opTask(null,()=>opQuickRun('start'))`.
7. `#lab-destroy` (deployment bar "Destroy lab", danger-outline) → `opTask(null,()=>opQuickRun('destroy'))`.
8. `#operations-history` (sidebar "Operation history") → `opHistory()` (all labs).
9. `#inspect-all` (sidebar "View running lab details") → `opTask(null,()=>opReview({action:'inspect-all'}))`.
10. `#labs` `contextmenu` on a `[data-lab]` element → preventDefault + `openLabOperations(lab.dataset.lab)`.
11. `#labs` `keydown`: key `ContextMenu` or `Shift+F10` on a `[data-lab]` → preventDefault + `openLabOperations(...)`.

### renderLabOperations() (called on every render)
- `quick = opQuickActions(current(), state.discovery, busy())`:
  - `known` = deployment.status ∈ {"Not deployed","Running","Stopped","Partially running"}.
  - `available` = lab && opPath(lab) non-empty && `discovery.connected` && known && !busy.
  - `startAction` = status==="Not deployed" ? 'deploy' : 'start'.
  - `canStart` = available && status!=="Running". `canDestroy` = available && status!=="Not deployed".
- `#lab-start.disabled = !canStart`; title = "Deploy this topology and start its devices" (deploy) or "Start stopped devices in this lab" (start). Visible label stays "Start lab" (from index.html) in both cases.
- `#lab-destroy.disabled = !canDestroy`.
- `#lab-actions.hidden = !current()`.
- `#operation-summary` (sidebar `role=status`) = "Lab command running · view operation history" when any `state.operations` job is queued/running, else "".
- When `busy()`: disables `#remove-lab`, `#sync-vm`, `#update-definition`, `#link-deployment`. When not busy: re-enables only `#update-definition` and `#link-deployment` (remove-lab / sync-vm are re-enabled by management.js `renderManagement` under its own rules; because renderManagement runs first, the busy disable here wins).
- No explanation text is shown for the disabled Start/Destroy/Remove/Sync buttons except the two Start titles.

### opQuickRun(kind)
- Returns silently if no lab or the corresponding `canStart`/`canDestroy` is false.
- For destroy: refreshes capabilities (on error `opCaps=null`), `options = opDestroyOptions()` (→ `{cleanup:true}` unless destroy.cleanup===false).
- Calls `opReview({lab_id, action: 'deploy'|'start'|'destroy', options})`.

## 5. Lab actions dialog — `openLabOperations(id)` → dialog id `lab-operations-dialog`

- `opMenuLab=id`; returns if the lab is not in `state.labs`.
- Phase 1 body: `<p>Checking installed VM commands…</p>` while GET /operations/capabilities. If that throws: `opCaps=null`, `problem=e.message`. If the dialog was closed meanwhile, stop.
- Phase 2 (re-render same dialog, title = lab.name):
  - `.op-path`: `opPath(lab)` or "Import the original VM lab files before using host commands."
  - `.op-notice` with the capabilities error message when present.
  - Section **"Deployment & configuration"** (`.op-grid`): buttons via opCommand for deploy, redeploy, apply, start, stop, restart, inspect, save; then destroy with `opDestroyOptions()`; then, for each of deploy/redeploy whose `caps.actions[a].cleanup` is truthy, an extra "Deploy lab + cleanup" / "Redeploy + cleanup" button with `{cleanup:true}`. Any button whose capability reports `available:false` is disabled and shows `<small>Unavailable on this VM</small>`. When capabilities could not be read, nothing is disabled.
  - Help: "Destroy removes the containers and the generated lab folder (containerlab destroy --cleanup); redeploy keeps that folder unless you choose its cleanup variant. Containerlab save supports selected device kinds; manager backups remain in Backup history."
  - Section **"Workspace & access"** (`.op-grid`, `data-local` buttons): "SSH all nodes ↗", "Favorite lab" / "Remove favorite" (label from `lab.favorite`), "Edit topology diagram", "Telemetry settings…", "Operation history", and opCommand('delete') = "Delete undeployed VM YAML" (capability-gated like the others).
- Handlers:
  - any `[data-op-action]` → `opTask(dialog,()=>opReview({lab_id:id,action,options}))` (options parsed from `data-op-options`).
  - ssh → `opNewTab({mode:'ssh',lab:id})`.
  - favorite → PUT /labs/{id}/operations-settings `{favorite:!lab.favorite}` → `refresh()` → dialog.close(). (app.js:42 sorts favorites first and prefixes "★ ".)
  - interactive → `opLayout(id)` (editDiagram).
  - telemetry → dialog.close() then `openTelemetrySettings(id)`.
  - history → `opHistory(id)` (filtered to this lab).
- Close `×` (data-op-close). Dialog is not closed after running a command; opReview opens on top.

## 6. Telemetry settings dialog — `openTelemetrySettings(id)` → dialog id `telemetry-settings-dialog`

Data: GET /labs/{id}/telemetry (`enabled, unavailable, linked, settings{decided,auto,profile_id}, summary{total,streaming,stale,waiting,configuring,connecting,failed,unsupported}, password_profiles[{id,label,platform}], nodes[{name,short_name,state,message}]`) and GET /telemetry/grafana (`enabled, running, port, idle_minutes`; failure → null). `usable = data.enabled && data.linked`. `failed` = nodes with state failed or stale.

Rendered text (`telemetrySummaryText`), first match wins:
1. `!data.enabled` → `data.unavailable` or "The telemetry collector is disabled in this manager."
2. `!data.linked` → "Telemetry is collected for labs linked to a VM deployment; this lab is not linked."
3. `!settings.decided` → "This lab was saved before automatic telemetry existed. Nothing is written to a device until you turn it on here."
4. `!settings.auto` → "Automatic telemetry is off for this lab; Grafana shows nothing for it."
5. else "Automatic telemetry is on: {total} supported node(s) · {n} streaming · {n} stale · {n} waiting · {n} configuring · {n} connecting · {n} failed · {n} unsupported. Read the data in Grafana." (only non-zero counts, in that order).

Then: a `<ul>` of failed/stale nodes "**short_name** (state word): message"; `#tele-grafana` line from `telemetryGrafanaText`:
- null → "Grafana: state unavailable."; `!enabled` → "Grafana: not installed on this manager."; running → "Grafana: running on TCP {port}; stops after {n} minute(s) without an open dashboard" or "; the automatic stop is off" (when idle_minutes falsy); `running===false` → "Grafana: stopped; it starts when you open it from the lab header."; else "Grafana: not checked yet."
- plus `#tele-grafana-stop` "Stop Grafana now" only when `grafana.running`.

Controls:
- `#tele-auto` checkbox: "Automatic telemetry: configure the gNMI service on supported nodes and stream counters to Grafana" — checked from settings.auto; **disabled unless usable**.
- Help: "Applies to cEOS, XRv9k and cJunosEvolved nodes once they answer show version. The manager adds only the missing service lines with each NOS's own scoped commit and never saves the whole running configuration. The manager keeps the last 15 minutes in memory for Prometheus to scrape; a stop, destroy, redeploy or removal clears it."
- `#tele-profile` select "gNMI login": option "" = "Each node's saved password login (profile, inventory or containerlab default)", then each password profile "{label} · {platform}" (selected when id===settings.profile_id); **disabled unless usable**.
- Help: "gNMI needs a username and password; nodes that log in with an SSH key need a password profile here. Secrets never leave the manager."
- `.dialog-actions`: `#tele-retry` "Retry failed nodes" (only rendered when failed.length) → POST /labs/{id}/telemetry/retry `{}` → notify "Retry requested for the failed nodes." → close. `#tele-remove` "Remove manager-added lines…" — `disabled title="Disable automatic telemetry first"` when `settings.auto || !usable` → native `confirm("Remove the telemetry configuration lines the manager added on the running nodes of this lab?")` → POST /labs/{id}/telemetry/remove-config `{}` → notify "Removal started on {a, b}." or "Nothing to remove on running nodes." → close. `#tele-save` "Save" (primary; disabled unless usable) → PUT /labs/{id}/telemetry/settings `{auto, profile_id}` → notify "Automatic telemetry enabled. Supported nodes are configured as they become ready; open Grafana to watch them." or "Automatic telemetry disabled; collection stopped." → close → refresh().
- `#tele-grafana-stop` → POST /telemetry/grafana/stop `{}` → replaces `#tele-grafana` text with telemetryGrafanaText(result) (this drops the Stop button from the line) → notify "Grafana stopped on the VM; it starts again when you open it."
- Trailing help: "Remove deletes only the telemetry configuration lines this manager recorded as its own, on running nodes, over SSH. Disabling telemetry alone leaves the device configuration as it is."
- Note: the Grafana **open** link (`#grafana-open`, "Grafana ↗" / "Lab map in Grafana ↗") is rendered by app.js `renderGrafanaLink`, not here; grafana.html/grafana.js start Grafana via POST /api/telemetry/grafana/start.

## 7. Review / confirmation dialog — `opReview(request)` → dialog id `operation-review`

- POST /operations/preview with the request (`{lab_id?, action, options?, path?, name?}`); response fields used: `action, name, path, warnings[], affected[{name,state}], steps[][] | argv[], diff, token`.
- Title "{label}?" (label from opLabels or raw action).
- Body: `<strong>{name}</strong>`; `.op-path` = path or "All deployed labs on the configured VM"; each warning as `.op-notice`; for stop/restart/redeploy/destroy/apply: `.op-notice` "This can interrupt lab connectivity and open SSH sessions."; for delete: `.op-notice` "Deletes the original YAML on the VM after preserving a recovery copy. The saved manager workspace remains."; then "Creates and starts the devices defined in this topology." (deploy) or "{n} deployed containers affected"; `<details><summary>Affected containers</summary>` list "name · state" when any; `<details><summary>Containerlab command</summary><pre class="op-output">` with each step/argv rendered as JSON-quoted words joined by spaces, one step per line (falls back to the label); `<details open><summary>YAML changes</summary><pre>` when `diff`; help "Confirm to run this action on the VM. If the topology or deployment changes, open this confirmation again."; buttons `#op-cancel` "Cancel" and `#op-confirm` "{label}" (primary).
- Confirm → POST /operations/confirm `{token}` → returns job → dialog.close(); if `#op-editor` dialog is open it is closed; `refresh()`; `opShowJob(job.id)`.
- Errors from preview (e.g. missing path) surface through the caller's opTask (form-error of the calling dialog, or toast when called with null).

## 8. Operation output dialog — `opShowJob(id)` → dialog id `operation-output`

- Body: `#op-job-banner.op-banner` (hidden until first poll), `<pre class="op-output" id="op-job-output" tabindex="0">`, `#op-job-result`.
- `poll()` (immediately, then every **1000 ms** while `status ∈ {queued,running}` and the dialog is open; timer in `opOutputTimer`, cleared on dialog close and at each opShowJob start): GET /operations/{id} → fields `action, status, name, exit_code, message, output, result{recovery_path, project_path}`.
- Banner (`opJobBanner`): tone `good` (succeeded), `bad` (failed | interrupted), else `running`; title "✔ {label} succeeded" / "✖ {label} {status}" / "{label} {status}…"; detail "{name} · Exit {exit_code} · {message}" (parts omitted when empty; exit shown when not null/undefined).
- Output text = job.output or "Waiting for command output…"; auto-follows to bottom only if the reader was within 30 px of the bottom.
- Inspect rendering: for action inspect/inspect-all the dialog gets class `inspection-dialog` (CSS `#operation-output.inspection-dialog{width:min(1680px,97vw)}`); when succeeded and rows parsed → the `<pre>` is hidden and `#op-job-result` shows the table (caption "{n} deployed nodes"; "—" for empty topology cell; kind + image, state · health, ipv4 + ipv6). When succeeded and output is `[]`/`{}` → pre hidden, "No deployed nodes found."
- Extras in `#op-job-result`: "Recovery copy: `<code>path</code>`" when `result.recovery_path`; `#op-open-clone` "Browse cloned lab topologies" when `result.project_path` → `opBrowse(project_path)`.
- When the job leaves queued/running: `await refresh()` (main page re-renders; standalone page only refetches).
- Fetch errors → `.form-error` of the dialog (polling stops because no new timer is set).

## 9. Operation history dialog — `opHistory(labId='')` → dialog id `operation-history`

- GET /operations (list of `{id, lab_id, name, action, status, created}`); filtered by `lab_id===labId` when given.
- Text "Saved command output remains in persistent manager storage." then `.op-history` list of `<button data-job>`: `<strong>{name} · {label}</strong><small>{status} · {created toLocaleString()}</small>`; or "No lab operations yet."
- Click → `opShowJob(id)`.

## 10. Lab Topologies browser — `opBrowse(path='')` → dialog id `op-browser`

- POST /operations/browse `{path}` → `{path, parent, entries[{name, path, directory}]}`.
- Title "Lab Topologies"; `.op-path` = result.path or "Lab topology folders".
- `.actions` buttons: `#op-roots` "Lab folders" → opBrowse(''); `#op-up` "Parent folder" → opBrowse(result.parent||''); `#op-create` "New topology" → `opEdit('','',(result.path||'/srv/containerlab-node-manager/projects')+'/new-lab.clab.yaml')`; `#op-clone` "Clone repository" → opClone(); `#op-popular` "Popular labs" → opPopular().
- `#op-file-tree` (aria-label "Lab topology files"): entries filtered by `opTopologyEntries` (folders + `*.clab.yaml|*.clab.yml`). Empty → "No lab topologies or subfolders here." Folders render as `<details><summary>{name}</summary><div class="op-tree-children">`; first open (`ontoggle`) lazily loads POST /operations/browse `{path:entry.path}` with "Loading…" placeholder; on error "{message} Close and reopen this folder to retry." (not marked loaded, so reopening retries). Files render as `<button class="op-tree-file">◇ {name}</button>` → `opTask(dialog,()=>opEdit(entry.path))` (no labId is passed).
- Help: "Expand a folder and select a .clab.yaml or .clab.yml topology to view or deploy. Other files are hidden. Each folder shows at most 500 matching entries."
- Clone and Popular start **disabled**; after `opCapabilities()` resolves: `clone.disabled = !caps.network || caps.actions.clone.available===false`; `popular.disabled = !caps.network`; if `!caps.network` help += " Online downloads are disabled. Enable --allow-downloads in VM setup for cloning and the catalog." If capabilities fail: help += " Files are available, but command checks failed. Open the Debug panel to check VM helpers. Online actions remain disabled." (Both skipped if the dialog was re-rendered meanwhile: `clone.isConnected` check.)

## 11. Topology viewer / creator — `opEdit(path,labId='',newPath='')` → dialog id `op-editor`

- Existing file: POST /operations/read `{path}` → `{text, path}`. New: text `name: new-lab\ntopology:\n  nodes:\n    r1:\n      kind: linux\n      image: alpine:latest\n`, path = newPath. `isYaml = /\.ya?ml$/i`. `opEditorContext={path,labId,isNew:!path}` (never read). If `path` is empty, `labId` is forced to ''.
- Title "Lab topology" (existing) / "Create lab topology" (new).
- Fields: `#op-edit-path` "Absolute VM path" (readonly for existing); `#op-edit-text` textarea (`.op-code`, spellcheck=false) labelled "Topology YAML" (yaml) or "File contents" (other); **readonly for existing files and for non-yaml**.
- Help: "Choose Deploy lab to save this topology as a workspace and start its devices on the VM; the lab appears in the manager right away and SSH opens as the devices boot. Save to manager keeps the workspace without deploying. Existing files are read-only; edit them on the VM."
- Buttons (`.actions`): `#op-validate` "Validate / preview topology" (yaml only) → `opParse(path,textarea)` → `opMapPreview(drawing,name,annotations_used)`; `#op-save-yaml` "Review creation on VM" (new only, primary) → `opReview({action:'create',lab_id:labId,path:#op-edit-path,options:{text:textarea}})`; for existing yaml: `#op-add-project` "Link topology" (labId set) / "Save to manager" (no labId) and `#op-deploy-project` "Deploy lab" (primary). Because opBrowse never passes labId, the "Link topology" wording is unreachable from the current UI.
- Save to manager (`#op-add-project`): re-reads the VM file (comment: unsaved editor contents are never linked/imported), `opParse`, then confirmation dialog id `op-add-confirm` titled "Link lab topology?" / "Save lab to manager?" with "{parsed.name} · {n} nodes[ · positions from the annotations file]", `.op-path` path, text "This saves a manager workspace and links its original VM source. It does not deploy containers. Device credentials can be imported from discovered VM files after deployment.", button `#op-add-confirm-button` "Link topology"/"Save lab" → (no labId) POST /lab-definitions multipart (definition + annotations) → PUT /labs/{id}/operations-settings `{path}` → `activeId=id`, `sessionStorage.activeLab=id` → close both dialogs → `refresh()` → notify "Lab topology saved to the manager."
- Deploy lab (`#op-deploy-project`): re-read + parse → `opSaveWorkspace(path,source,parsed,labId)` (reuses a lab matching `deployment_name===parsed.name` or same path, else creates one; PUT operations-settings `{path}`; sets activeId + sessionStorage) → `opReview({action:'deploy',lab_id:id,path,name:parsed.name})`. On confirm, opReview closes `#op-editor`.

## 12. Clone dialog — `opClone(url='',project='')` → dialog id `op-clone-dialog`

- Title "Clone a lab repository". Fields: `#op-clone-url` "HTTPS repository URL" (type=url, placeholder `https://github.com/owner/repository`), `#op-clone-name` "New project folder name" (maxlength 120). Prefilled from arguments (Popular labs).
- Text: "Requires --allow-downloads on the VM. The destination is /srv/containerlab-node-manager/projects. Existing folders are never overwritten. After cloning, browse the project, review its files, and choose a topology to deploy."
- `#op-clone-review` "Review clone" (primary) → `opReview({action:'clone',options:{url,project}})`. The finished job offers "Browse cloned lab topologies" (section 8).

## 13. Popular labs — `opPopular()` → dialog id `op-popular-dialog`

- GET /operations/popular → `{items[{name, description, url}]}`.
- Title "Popular lab topologies"; text "SRL Labs repositories tagged clab-topo, ordered by GitHub stars. Cloning and deployment are separate reviewed steps."; `.op-history` list of `<button data-repo>` name + description → `opClone(item.url,item.name)`.

## 14. Topology preview — `opMapPreview(drawing,name,positioned)` → dialog id `op-map-preview`

- Title "Topology preview · {name}"; `<svg id="op-preview-map" class="topology-map op-layout-map" role="img" aria-label="Proposed topology">` filled with `topologyMarkup(drawing)` and viewBox from `measureTopology(svg)`.
- Text: positioned → "Wiring from the YAML, node positions from the annotations file beside it; the saved workspace starts from this layout." else "Wiring from the YAML; the nodes sit on the default grid because no annotations file was found beside the topology (Edit diagram moves them later)."

## 15. All API calls made by this file (each prefixed `/api` by `api()`)

| Method | Path | Where |
|---|---|---|
| GET | /operations/capabilities | opCapabilities (Lab actions dialog, browser, quick destroy) |
| POST | /operations/preview | opReview |
| POST | /operations/confirm | opReview confirm |
| GET | /operations/{id} | opShowJob poll |
| GET | /operations | opHistory |
| POST | /operations/browse | opBrowse (root + lazy folders) |
| POST | /operations/read | opEdit, opReadAnnotations, save/deploy re-read |
| POST | /operations/parse-yaml | opParse |
| GET | /operations/popular | opPopular |
| POST | /lab-definitions (multipart FormData) | opSaveWorkspace, Save to manager |
| PUT | /labs/{id}/operations-settings | `{favorite}` (Lab actions) and `{path}` (save/deploy) |
| GET | /labs/{id}/telemetry | openTelemetrySettings |
| PUT | /labs/{id}/telemetry/settings | Save telemetry |
| POST | /labs/{id}/telemetry/remove-config | Remove manager-added lines |
| POST | /labs/{id}/telemetry/retry | Retry failed nodes |
| GET | /telemetry/grafana | openTelemetrySettings |
| POST | /telemetry/grafana/stop | Stop Grafana now |
| GET | /state | via `refresh()` (app.js / workspace.js) after favorite, save, telemetry save, job completion, confirm |
| GET | /labs/{id}/topology | via `editDiagram` (diagram-editor.js) from Edit diagram / Edit topology diagram |

## 16. Persistence

- `sessionStorage.activeLab` — set in `opSaveWorkspace` and in the Save-to-manager confirm (both after creating/linking a workspace). Read by app.js:4 at load.
- Backend state written: lab favorite flag; lab `vm_project_path` (operations-settings `{path}`); new lab definitions; telemetry settings (auto, profile_id); telemetry remove-config/retry jobs; Grafana stop; operation jobs (confirm). Operation output is persisted server-side ("Saved command output remains in persistent manager storage.").
- No localStorage use in this file.

## 17. Timers / polling

- `opOutputTimer`: `setTimeout(poll,1000)` inside opShowJob while status is queued/running and the dialog is open; cleared on `dialog.onclose` and at the start of every opShowJob call. Nothing else in this file polls (the 30 s discovery check, 4 s action logs and toast timer live elsewhere).

## 18. Status vocabulary seen in this file

- Operation job `status`: `queued`, `running`, `succeeded`, `failed`, `interrupted` (banner text uses the raw word for failed/interrupted and for any other status).
- `lab.deployment.status` values matched exactly for the quick buttons: "Not deployed", "Running", "Stopped", "Partially running" (index.html/app.js also show "Unlinked" for missing).
- Telemetry node states (`teleStateLabels`): disabled→"off", waiting, configuring, connecting, streaming, stale, unsupported, failed, unmonitored. Retry/failed list uses `failed` and `stale`.
- Capability flags: `caps.network`, `caps.actions[a].available`, `caps.actions[a].cleanup`.
- Banner tones: `good`, `bad`, `running`. Inspection state cell falls back to "unknown". Affected containers list shows the raw container `state`.
- Grafana: `enabled`, `running` (true/false/undefined), `port`, `idle_minutes`.

## 19. Element ids and data attributes touched

Existing in index.html: `import-top`, `map-edit`, `deploy-empty`, `vm-projects`, `lab-start`, `lab-destroy`, `operations-history`, `inspect-all`, `labs`, `operation-summary`, `remove-lab`, `sync-vm`, `update-definition`, `link-deployment`, `toast` (via notify).
Created by this file: `lab-actions` (button); dialogs `lab-operations-dialog`, `telemetry-settings-dialog`, `operation-review`, `operation-output`, `operation-history`, `op-open-tab`, `op-browser`, `op-editor`, `op-add-confirm`, `op-clone-dialog`, `op-popular-dialog`, `op-map-preview`; inner ids `tele-grafana`, `tele-grafana-stop`, `tele-auto`, `tele-profile`, `tele-retry`, `tele-remove`, `tele-save`, `op-cancel`, `op-confirm`, `op-job-banner`, `op-job-output`, `op-job-result`, `op-open-clone`, `op-roots`, `op-up`, `op-create`, `op-clone`, `op-popular`, `op-file-tree`, `op-edit-path`, `op-edit-text`, `op-validate`, `op-save-yaml`, `op-add-project`, `op-deploy-project`, `op-add-confirm-button`, `op-clone-url`, `op-clone-name`, `op-clone-review`, `op-preview-map`.
Data attributes: `data-op-close`, `data-op-action`, `data-op-options`, `data-local` (ssh|favorite|interactive|telemetry|history), `data-job`, `data-repo`, `data-lab` (rendered by app.js:42 on sidebar lab buttons).
CSS classes relied on: `operations-dialog`, `dialog-head`, `eyebrow`, `icon-button`, `form-error`, `form-help`, `dialog-actions`, `actions`, `checkbox-label`, `button primary|secondary`, `op-path`, `op-notice`, `op-sections`, `op-grid`, `op-output`, `op-banner (+good|bad|running)`, `inspection-dialog` (on `#operation-output`), `op-inspection`, `op-history`, `op-file-tree`, `op-tree-children`, `op-tree-file`, `op-code`, `topology-map`, `op-layout-map`.

## 20. Microcopy a CCNA-level student may not understand (visible strings)

- Eyebrow "NODE MANAGER" on every operations dialog (internal product framing, not the action).
- "Checking installed VM commands…"; "Import the original VM lab files before using host commands." (what are host commands?).
- "Unavailable on this VM" with no reason.
- Button labels "Apply topology", "Save configurations (clab)", "Inspect lab", "Destroy deployment", "Deploy lab + cleanup", "Redeploy + cleanup", "Delete undeployed VM YAML", "Create VM topology", "Clone repository".
- Help "Destroy removes the containers and the generated lab folder (containerlab destroy --cleanup); redeploy keeps that folder unless you choose its cleanup variant. Containerlab save supports selected device kinds; manager backups remain in Backup history." (Docker containers, CLI flag, "device kinds").
- Review dialog: "{n} deployed containers affected", "Affected containers", "Containerlab command" with JSON-quoted argv, "All deployed labs on the configured VM", "YAML changes", "Deletes the original YAML on the VM after preserving a recovery copy. The saved manager workspace remains.", "Confirm to run this action on the VM."
- Output dialog: "Exit 0/1" codes, "Waiting for command output…", "Recovery copy: <path>", "Browse cloned lab topologies", table headers "Kind / image", "State / health", raw image names, "No deployed nodes found."
- History: "Saved command output remains in persistent manager storage."
- Browser: title "Lab Topologies" plus "Lab folders", "Parent folder", "Clone repository", "Popular labs"; ".clab.yaml or .clab.yml"; "Each folder shows at most 500 matching entries."; "Enable --allow-downloads in VM setup for cloning and the catalog."; "Files are available, but command checks failed. Open the Debug panel to check VM helpers. Online actions remain disabled."; "◇" file glyph; "{error} Close and reopen this folder to retry."
- Editor: "Absolute VM path", "Topology YAML" / "File contents", "Existing files are read-only; edit them on the VM.", "Review creation on VM", "Save to manager", "Link topology", "Validate / preview topology", default YAML `kind: linux / image: alpine:latest`, "This saves a manager workspace and links its original VM source. It does not deploy containers. Device credentials can be imported from discovered VM files after deployment.", "positions from the annotations file".
- Preview: "annotations file beside it", "default grid".
- Clone: "HTTPS repository URL", "New project folder name", "Requires --allow-downloads on the VM. The destination is /srv/containerlab-node-manager/projects. Existing folders are never overwritten."
- Popular: "SRL Labs repositories tagged clab-topo, ordered by GitHub stars."
- Telemetry: "gNMI service", "gNMI login", "cEOS, XRv9k and cJunosEvolved", "each NOS's own scoped commit", "running configuration", "Prometheus to scrape", "password profile", "containerlab default", "Remove manager-added lines…", "Disable automatic telemetry first", "Grafana: running on TCP {port}", "The telemetry collector is disabled in this manager.", "labs linked to a VM deployment".
- Sidebar: "Lab command running · view operation history"; deployment bar titles "Deploy this topology and start its devices" / "Start stopped devices in this lab" (the visible label stays "Start lab" even when it will deploy).
- New-tab fallback: "Your browser may have blocked the new tab." / "Open workspace ↗".

## 21. Redesign risks (behaviours easy to break)

1. All main-page handlers are wired inside `if($('import-top'))`; removing/renaming `#import-top` silently disables Lab actions, Edit diagram, Deploy a new lab, Deploy New Lab, Start/Destroy, Operation history, View running lab details, and the sidebar context-menu/keyboard shortcuts.
2. Inside that block `#map-edit`, `#lab-actions`, `#vm-projects`, `#lab-start`, `#lab-destroy`, `#operations-history`, `#inspect-all`, `#labs` are dereferenced without null guards; a missing one throws and stops the rest of the wiring.
3. `#lab-actions` is injected by JS immediately before `#import-top` (`insertAdjacentHTML('beforebegin')`) and hidden when no lab is selected — a new heading layout must keep a slot for it.
4. Sidebar right-click / ContextMenu key / Shift+F10 rely on lab buttons carrying `data-lab` (app.js:42) inside `#labs`.
5. `renderLabOperations()` is invoked by app.js `render()` after `renderManagement()`; the busy-state disabling of `#remove-lab`/`#sync-vm` depends on that order and on those ids existing; when not busy it re-enables `#update-definition`/`#link-deployment` unconditionally.
6. Quick Start/Destroy gating matches deployment status strings exactly ("Not deployed", "Running", "Stopped", "Partially running") and requires `state.discovery.connected` and a non-empty `opPath(lab)`; no explanatory text exists for the disabled state beyond the two Start titles.
7. `opDialog` replaces the dialog's entire innerHTML each call and is reused by diagram-editor.js and git-progress.js; `opTask` depends on a `.form-error` child and on `button:not(:disabled)` enumeration (it also disables the `×` close button during work). git-progress.js passes a `<form>` to opTask.
8. Job output polling runs only while `#operation-output` is open; closing it stops the poll and skips the final `refresh()`. The follow-scroll test uses the `<pre>`'s own scroll metrics (`max-height:48vh; overflow:auto`); if the pre stops being the scroll container the auto-follow breaks.
9. Inspection view depends on `#operation-output.inspection-dialog` CSS widening and on hiding the `<pre>`; the `.op-banner.good/.bad/.running` tone classes carry the pass/fail colouring.
10. Folder tree uses native `<details>` `ontoggle` with load-once + error-retry semantics; "Clone repository"/"Popular labs" start disabled and are enabled asynchronously after the capabilities call (guarded by `isConnected`).
11. `opBrowse` ignores its 2nd argument (workspace.js passes `activeId`); `opEdit` therefore never gets a labId, so the "Link topology"/"Link lab topology?" branch is dead in the current UI. `opEditorContext`, `opMenuLab`, `opName` are set/defined but never read — safe to drop only if no future code depends on them.
12. `opReview` confirm closes `#op-editor` by id if open; the editor dialog id must remain `op-editor`.
13. `opCaps` is a shared cache reset by management.js (`opCaps=null` on Remove lab); capability errors deliberately leave every command enabled and fall back to `cleanup:true` for destroy.
14. Destroy always sends `{cleanup:true}` unless capabilities explicitly say `destroy.cleanup===false`; the "+ cleanup" variants for deploy/redeploy appear only when capabilities report `cleanup` for that action.
15. `opNewTab` opens `/static/workspace.html#mode=ssh&lab=<id>` and falls back to a dialog with an `<a target=_blank rel=opener>` link when popups are blocked; `#vm-projects` navigates the same tab to `#mode=folder`.
16. Telemetry: `#tele-remove` is disabled while auto is on (title "Disable automatic telemetry first"); Remove uses native `confirm()`; Stop Grafana rewrites `#tele-grafana` text only (button disappears) without re-rendering the dialog.
17. The Save-to-manager and Deploy flows re-read the file from the VM (editor text is ignored for existing files) and write `sessionStorage.activeLab`; the Deploy flow reuses an existing lab by `deployment_name` or path match before creating a new one.
18. `data-op-options` stores JSON in an attribute (escaped) and is `JSON.parse`d on click; any templating change must keep it valid JSON.
19. Error handling convention: dialog-scoped errors go to the dialog's `.form-error` (`role=alert`, hidden when empty via CSS), non-dialog errors to the toast.

## 22. Cross-file pointers for the same focus area (not defined in operations.js; located, not fully inventoried)

- Deployment bar text: management.js `renderManagement` (≈lines 72-89) sets `#deployment-status` (= lab.deployment.status or "Unlinked"), `#deployment-message` (or "Link this workspace to a deployed lab."), `#deployment-checked` ("Last successful inspection: …"), `#vm-files-status` (e.g. "VM file sync is unavailable until discovery reconnects.", "Update the installed VM helper to enable file transfer, or use direct inspection + SFTP. …", "No deployed source files found. Saved workspace retained.") and `renderNosReadiness` → `#deployment-nos` ("NOS ready · x/y nodes accept SSH login", "NOS booting · …", classes ready/booting/failed).
- `#sync-vm` ("Sync from VM"): management.js:150-153; hidden unless `lab.deployment_name`; disabled when syncing, not connected, or `!vm_source.can_sync`; POST /labs/{id}/sync; label "Syncing…" while running.
- `#update-definition` ("Update lab YAML"): management.js:112 → `openSetup(true)` (setup-dialog "Update lab definition").
- `#link-deployment` ("Link deployment"): management.js:147 → binding-dialog; PUT /labs/{id}/deployment `{deployed_name,prefix}`; notify "Deployment link saved."
- `#remove-lab` ("Remove lab"): management.js:14-17 dialog "Remove lab from this manager?" (`remove-lab-dialog`), DELETE /labs/{id} with confirm-name and `prevent_reimport`; disabled by management.js when a backup job for the lab is queued/running, and by operations.js when anything is busy.
- Grafana link `#grafana-open`: app.js `renderGrafanaLink` (≈lines 30-38) → `/static/grafana.html#path=&title=`; grafana.js starts Grafana (POST /api/telemetry/grafana/start).
- `#deploy-empty` gating + `#empty-vm-note`: management.js `renderLanding` (≈lines 90-95).
