# Documentation inventory — clab-manager UI (release 1.28.0)

Read-only inventory of what the documentation establishes about the existing web UI,
compiled before the redesign. Everything below is taken from the source documents; nothing
is inferred from code. Where a document is stale relative to 1.28.0 it is flagged, because a
redesign that follows the stale wording would regress the shipped behaviour.

Sources read in full: `docs/ARCHITECTURE.md`, `docs/LAB-OPERATIONS.md`, `docs/GIT-PROGRESS.md`,
`docs/GIT-SETUP.md`, `docs/TELEMETRY.md`, `docs/CAPTURE.md`, `docs/DEBUG-PANEL.md`,
`docs/VM-CONNECTION.md`, `docs/TOUR.md`, `docs/NAMING.md`, `docs/GRAFANA-MAP.md`, `README.md`,
`clab-backup-ui/NODE-FEATURES.md`, `agent instructions.md` lines 1–570 (1.28.0 back to 1.15.2),
`clab-backup-ui/VALIDATION.md` lines 1–670 (1.28.0 → 1.22.0), `docs/CHANGELOG.md` lines 1–393
(1.28.0 → 1.22.0), `deploy/verify-release.py`. `docs/WIKI-MASTER-GUIDE.md`: headings grepped,
bold UI names grepped, and only the UI-screen sections read (Parts 11–14, the removal-action
table, Step 21.3 and "Folders and buttons").

---

## 1. Screen structure the docs establish (1.28.0)

| Area | What the docs say |
|---|---|
| Entry | `http://VM_IP:8081`, no UI login, no access token (README, VM-CONNECTION, wiki Part 11). |
| Sidebar | Saved labs (click to open; right-click or Shift+F10 for **Lab actions**; **Favorite** sorts a lab above others). Sidebar actions in this order (wiki Part 14): **Deploy New Lab**, **View running lab details**, **VM connection**, **Refresh discovery**, **Operation history**, **Manual discovery**. **Debug panel** at the bottom of the sidebar (DEBUG-PANEL). Sidebar reports **VM connected** after a successful connection (wiki Part 11). Excluded labs: right-click → **Clear exclusion** (wiki Part 17). |
| Landing page (no lab saved) | **Deploy a new lab** (opens the VM topology browser in place), a list of labs *Already running on the VM* with one-click **Import**, two import links (lab definition, Ansible inventory), asks for the VM connection first when none exists; no **Lab actions** button (CHANGELOG 1.22.0, VALIDATION 1.22.0, TOUR). |
| Workspace tab row | **Topology**, **Nodes**, **Git repository**, **Backup history**; **More** holds **Credentials** and **Action logs** (CHANGELOG 1.28.0). Pre-1.28.0 wording (wiki Part 13, CHANGELOG 1.27.0) has Git repository under More. |
| Lab header | Deployment bar with NOS readiness line (*NOS booting 1/2 nodes accept SSH login so far* → *NOS ready 2/2*), the quick destroy button ("Destroy lab from the deployment bar", VALIDATION 1.22.0), **Grafana ↗** or **Lab map in Grafana ↗** (opens `/static/grafana.html#path=…&title=…` in a new tab, `target=_blank`, title ends *Grafana starts on the VM when it is not running*), **Save progress** bar showing where the lab is saved (TOUR), **Lab actions** button. |
| Topology toolbar | **Edit diagram**, **SSH all nodes**, **Back up all configs** (also in expanded view), zoom, **Fit map**, **Expand map**, **Import topology**; legend "Links show imported wiring, not live status". |
| Lab toolbar | **Export sessions** (SuperPuTTY XML) with checkbox **Include saved passwords as plain text**. |
| Footer | Shows `v<release>`; app.js holds a fallback `state.version||'<release>'` that is part of the lockstep version set. |
| Standalone pages (each carries `?v=<release>` on its assets) | `index.html`, `terminal.html`, `workspace.html`, `vm-connection.html`, `debug.html`, `capture-setup.html`, `capture-session.html`, `grafana.html` (verify-release.py FIELDS). |

---

## 2. Documented user workflows

### 2.1 First connection — VM connection dialog (VM-CONNECTION.md, wiki Part 11, README step 3)
1. Open `http://VM_IP:8081`. The **VM connection** dialog opens by itself when no connection is saved (prompt once when `state.discovery` has loaded and is unconfigured, never for a configured or dismissed connection — agent instructions 1.19.3, `openVmDialog` + `maybePromptVmConnection`).
2. Fields: **VM address** (`127.0.0.1`), **SSH port** (`22`), **VM username** (`clab-discovery`), **VM password** (masked), **Inspection method** (*Installed discovery and file helper*), **Enable automatic discovery** (checked by default), **Trust a replacement SSH host key on the next connection** (checkbox `vm-reset-key`, checked by default since 1.22.0).
3. Click **Save and test connection**. Password is saved encrypted and never returned; reopening shows an empty password field; blank retains the saved password for the same address/port/account; changing any of those requires the password again.
4. First connection records the host fingerprint; later fingerprint changes block connection until explicitly accepted via the checkbox. Sidebar reports **VM connected**.
5. Troubleshooting strings the UI surfaces: *Password setup required*, *Authentication failed*, *Setup needs an interactive terminal*, *Conflicting SSH account policy*, *Connection refused / timed out*, *Interactive SSH / SFTP denied*, *Fingerprint changed*, HTTP 409 for folders and Git when the session does not run the operations gateway, *Helper outdated / commands unavailable*, *Save failed*.

### 2.2 Deploy a lab from a VM topology (LAB-OPERATIONS, TOUR, README step 4, CHANGELOG 1.22.0/1.26.0, VALIDATION 1.22.0/1.26.0)
1. **Deploy a new lab** (landing page) or **Deploy New Lab → Lab Topologies** (sidebar/header; same-tab landing page with an explicit browser button; description "Choose a lab topology from your VM to launch").
2. Expand a trusted root (e.g. `/etc/containerlab`), expand a folder, pick a `.clab.yaml`/`.clab.yml`. Existing files are read-only. Browse is capped at 500 entries per folder, 1 MiB per file read, no symlinks.
3. File is shown read-only. **Validate / preview topology** draws the map (note *Wiring from the YAML, node positions from the annotations file beside it* when annotations were used). The browser reads `<topology>.annotations.json` through the helper's `read` mode and sends it with the YAML (`opParse`, `opWorkspaceForm`, `opMapPreview`).
4. **Save to manager** saves a workspace without deploying; **Deploy lab** saves the workspace first (nodes, map, VM source path; `opSaveWorkspace`: POST `/api/lab-definitions`, PUT operations-settings) and then opens the containerlab command review.
5. Review screen shows the exact containerlab command, affected containers and warnings; nothing runs until confirmed. Review tokens expire after five minutes and bind VM connection, file digest and deployment state.
6. **Operation output** streams; banner turns green *✔ Deploy lab succeeded · Exit 0 · Operation completed* (red for failure, blue while running; `opJobBanner`).
7. Deployment bar shows *NOS booting …* then *NOS ready n/n*; SSH actions and **SSH all nodes** open per node as they answer; **Test NOS login** runs once automatically; result appears in **Backup history**; Nodes table *Last SSH check* column records automatic checks.
8. Other topology-browser actions: **New topology** (structure preview + confirmation; never replaces an existing file), **Clone repository / popular labs** (only with downloads enabled; clone/catalog buttons remain disabled until capability checks succeed), **Delete undeployed VM YAML** (refused while deployed; keeps a recovery copy in `.clab-manager-history`; result records the path).
9. Failure hint: *Operations helper is unavailable* in the topology browser (wiki Part 18) → repair with the launcher.

### 2.3 Lab actions menu (LAB-OPERATIONS "Retained commands", wiki Part 14, VALIDATION 1.26.0)
Open **Lab actions** or right-click a saved lab (Shift+F10). Items:
- **Deploy** / **Redeploy** (+ **Redeploy + cleanup** variant) / **Destroy deployment** (always `containerlab destroy --cleanup`; the review shows *Cleanup removes generated lab artifacts. Expected lab directory: …*; `opDestroyOptions(caps)` returns `{cleanup:true}` unless `caps.actions.destroy.cleanup === false`; the separate *Destroy + cleanup* entry is gone since 1.26.0).
- **Apply** (original VM YAML, when supported).
- **Start / stop / restart** (all nodes; *Restart lab nodes* named in TELEMETRY step 7).
- **Inspect lab / View running lab details** (table: topology, lab, node, kind/image, state/health, IPv4/IPv6; wider dialog; long paths wrap; failed output stays visible; supported-device caption shows the release).
- **Save configurations** (containerlab kind-dependent; separate from manager backups).
- **SSH all nodes** (launcher tab with per-node links and **Open all ready sessions**; browser popups required; max 32 concurrent terminals/checks).
- **Favorite**.
- **Edit topology diagram**.
- **Telemetry settings…**.
- **Delete undeployed VM YAML**.
- **Deploy New Lab → Lab Topologies**, **New topology**, **Save to manager / Deploy lab**, **Clone repository / popular labs**.
Removed (must not reappear; rejected by helper): existing VM YAML editing, copy topology path, Select/link VM project, Open VM folder, separate Edit layout, horizontal/vertical diagram exports, SSHX/GoTTY, SR Linux fcli.

### 2.4 Import a lab already running on the VM (TOUR, wiki Part 12, VM-CONNECTION)
1. Discovery sees the lab within 30 s; landing page lists it; or click **Refresh discovery**.
2. Click the discovered lab labelled **Ready to import**; review name, node counts, files, warnings; click **Import lab**. Cancelling leaves it unsaved; new labs always require import confirmation.
3. For saved labs, **Sync from VM** refreshes imported data without overwriting saved connection settings (fills a blank saved login from the generated inventory; a topology reimport can replace a manager-edited layout).
4. Fallback: **Discovery file details** shows attempted paths/errors; **Manual discovery** (sidebar) uploads YAML, inventory, topology/annotations through import forms.

### 2.5 Node actions and Node details (NODE-FEATURES, TOUR, wiki Part 13)
- Nodes table columns: address, platform, which login is in use (*Containerlab default login* when the default applies), **Last SSH check**, last backup, actions per row; **Include in backups** checkbox per node.
- Row actions: **Capture**, **SSH** (new browser tab; gated on readiness for linked labs), **Back up** (queues only this node; works even when excluded from schedules; one backup job at a time), **Details**.
- **Node details** drawer: latest and historical successful configuration downloads, **Test login** (SSH + `show version`; timestamped last check), **Edit connection** (address, port, NOS, profile, download device name). Correcting a node's short name here resolves an *Unmatched* map node.
- **More → Credentials**: NOS credential profiles, including **Generic SSH / Linux (terminal only)**; a generic default applies to unmapped nodes; each kind has its own default-profile selection; the manager supplies no default password.
- Map right-click on a matched node: **Capture packets**, **SSH**, **Back up configuration**, **Node details**; click a link to capture either endpoint. Keyboard: focus node → Shift+F10, arrow keys to navigate, Escape closes. Ambiguous/unknown nodes have no actions. Map status counts unsupported/one-ended links.
- Map: pan by dragging background, zoom, **Fit map** (rendered bounds), **Expand map**; **Topology → Import topology** uploads YAML/annotations by hand.

### 2.6 Browser SSH terminal (NODE-FEATURES, wiki Part 13)
- Opens directly in a new tab with a short-lived single-use terminal ticket and WebSocket origin check. **Disconnect** or close the tab ends it; **Connect / reconnect** starts a new session; resize and standard keys supported; disconnected shells are not resumed. Only open/close and login-check results are logged. `terminal.html` is the only document whose CSP permits inline styles (xterm needs them).

### 2.7 Backups (NODE-FEATURES, wiki Part 13, LAB-OPERATIONS)
- Per-node **Back up**; **Back up all configs** (topology header; reviews all ready nodes including unchecked ones and lists unavailable/unsupported nodes it will skip); scheduled lab backups (selected nodes only); **Backup history** with per-job downloads and archive; **Test NOS login**.
- Manager backups/import changes are blocked during an active lab operation. Every backup/login test runs with its own empty `known_hosts`.

### 2.8 Git repository tab — connect, save, browse (GIT-PROGRESS, GIT-SETUP, NAMING, wiki 21.3, CHANGELOG 1.27.0/1.28.0)
1. Connect: choose the **Git repository** tab (or **Connect Git repository**), select the registered checkout (subfolder registrations are listed with their subfolder), select devices (independent of backup schedule checkboxes), review branch/destination, **acknowledge that device configurations will be committed there**, optional *review before push* preference, save. **Git repository settings** is also reachable from the save action menu.
2. With no repository connected: **Connect a repository by URL** button. With the wrong one connected: **Use a different repository** → pick another registered checkout (opens the folder browser; pick folder; confirm devices) or **Connect by URL** (paste HTTPS clone URL — `/tree/main` page links are converted; keep or change the lab's folder; acknowledge full configurations will be pushed; confirm). Refused before cloning when the VM account cannot push (*The GitHub account signed in on the VM cannot push to …*) or when a folder would overlap another lab's folder. Switching never deletes anything.
3. Connected card: push URL, branch, VM account, folder path (`REPO › folder › latest/`).
4. **Where this lab lives** panel: folder path at top, folder outline left, contents of the selected folder right; folders tagged **This lab** or with the other lab's name; `latest/`, `baseline/`, `checkpoints/` described in plain words; a registered-but-unsaved folder reads *created on first save*; footer with last save/commit; listing rows like `latest · Most recent save · 2.4 KB`.
   - **Save this lab here**: moves the lab's registered destination to the selected folder (device selection and review preference kept; old registration retired); when files exist under the old folder, the confirmation offers to move them (one commit, pushed, recorded as a *Folder move* job with retry/review/push handling). Disabled with *This lab already saves here.* when already there. Refusals: "already saves to that folder", "cannot overlap". A pending save blocks a move.
   - **New folder…**: accepts a nested path (`Week-04/BGP/Final-State`) and shows the resulting `repository / folder` destination as you type (`gitFolderPath`/`gitDestinationPreview`); with *Save this lab here* ticked the lab moves into it, otherwise the folder is only registered. `latest/`, `baseline/`, `checkpoints/` cannot be chosen; no nesting inside another lab's folder; root registration vs subfolders exclusive.
   - **Apply to running lab…** button on any folder whose `latest/` holds a restore-grade candidate (no rebinding needed; `restoreFromFolder`).
5. Everyday buttons: **Save progress** (capture selected devices, export `latest`, commit, push; review preference pauses before push), **Save locally** (no push), **Save checkpoint…** (`checkpoints/<name>`; a new name per milestone), **Set baseline…** (select a complete recorded capture; replacing an existing baseline requires explicit review), **View changes / History** (versions labelled by folder, e.g. `labs/BGP-LAB/Broken · latest`, the connected one tagged *this lab*; compare configurations), **Push saved progress** (publish existing commit without recapture), **Update from remote** (fast-forward only), **Load version…** (baseline/checkpoint/commit; review manifest; download ZIP; never applies to devices), **Apply to running lab…**, **Git repository settings**, **Use a different repository…**.
6. Outcome words: **Saved on VM** (snapshot/commit exists locally), **Pushed** (push verified). Progress saves list (e.g. *Folder move → labs/clabllm-dev* under Progress saves).
7. Failed save recovery: open the **original failed save** from progress history → **Retry export** / **Retry export and push** or **Push saved progress**; **Keep snapshot only** (explicit confirmation; dismisses the pending export, keeps backup and any commit, then permits disconnect/removal). Messages: *A selected device failed*, *Complete snapshot; repository needs attention*, *Commit exists; push failed or review is required*, *Remote advanced / push rejected*, *Unexpected branch, URL, owner or repository identity*, *Helper unavailable or older than the manager*, *Manager restarted during a save*, *Git authentication expired*.
8. Limits: 500 devices, 2 MiB per config, 16 MiB total; oversized/incomplete captures do not replace the snapshot.

### 2.9 Apply a saved Junos configuration to a running node (GIT-PROGRESS, LAB-OPERATIONS, NAMING, CHANGELOG 1.28.0, agent instructions 1.28.0, VALIDATION 1.28.0)
1. From **Where this lab lives** (select a restorable folder → **Apply to running lab…**) or from **View changes / History** (open a version → **Apply to running lab…**, shown only when `restore_supported`).
2. Review screen *Replace running configuration* (`restoreReview` posts `POST /api/labs/{id}/restore/preflight`): source version, target nodes, each node's NOS, whether each already matches the saved state (`matches_saved`, `pending_changes`), the safety notes, *Safety options* with the rollback timer (default five minutes). Danger-styled confirm button (**Replace configuration**; `.button.danger`). Acknowledge required; idempotent `request_id`.
3. Job: preflight → mandatory pre-restore backup (`restore-pre`; a node whose backup fails is not changed) → `load override terminal` → `commit check` → `commit confirmed` → reconnect → `commit` → post backup (`restore-post`) + compare. `restoreShowJob` polls; result e.g. *All 1 node(s) restored and verified against the saved state.*; per-node `verified`, `root_authentication synthesized`, `missing 0`, `extra 0`, pre/post backup job ids.
4. Supported: `juniper_cjunosevolved`, `juniper_vjunosswitch`. IOS-XR/EOS and pre-1.28.0 snapshots are view/download only (never claim restorable). Errors: 400 *Select at least one saved node to restore.*; 409 *The selected commit is outside this repository branch history.*
5. Mapping is by exact node name (`clab-<lab>-<node>`) and platform (NAMING).

### 2.10 Telemetry settings and Grafana (TELEMETRY, GRAFANA-MAP, LAB-OPERATIONS, CHANGELOG 1.25.0/1.26.0)
- **Lab actions → Telemetry settings…** (`openTelemetrySettings` in operations.js; reads `/api/labs/{id}/telemetry`, PUTs `settings`, POSTs `retry` and `remove-config`): summary text (e.g. *Automatic telemetry is on: 2 supported nodes · 2 streaming. Read the data in Grafana.*), **Automatic telemetry** checkbox (labs saved before 1.23.0 show *This lab was saved before automatic telemetry existed* and nothing is written until ticked and saved), **gNMI login** profile select (password profile required; key profiles fail with that exact reason), **Remove manager-added lines…** (enabled only while automatic telemetry is off), **Retry failed nodes** (shown only when a node has failed), per-node state with reason (Off, Waiting, Configuring, Connecting, Streaming, Stale, Unsupported, Failed), Grafana state text (`telemetryGrafanaText`) and **Stop Grafana now**.
- **Grafana ↗** / **Lab map in Grafana ↗** (`renderGrafanaLink`, `grafanaLaunch(lab)`, `grafanaPath(lab)`; reads `lab.telemetry.grafana` = `{enabled, port, map_uid}`): opens `/static/grafana.html`, which takes only `#path=` and `#title=`, validates the path against `^/d/[A-Za-z0-9_-]+(\?[A-Za-z0-9_=&%+.-]*)?$`, shows *Starting Grafana on the VM; this takes a few seconds…*, POSTs `{}` (empty bodies refused) to start Grafana, then navigates to the dashboard on the manager's host name. Button hides when the stack is disabled.
- Grafana stops after `TELEMETRY_GRAFANA_IDLE_MINUTES` (15) without a dashboard request; dashboards refresh every 10 s; Prometheus scrapes every 10 s; lab maps re-provisioned within 30 s.

### 2.11 Browser Wireshark capture (CAPTURE, TOUR, CHANGELOG 1.22.0, agent instructions 1.20.0/1.22.0)
1. Open from lab-level **Capture packets**, a node's **Capture** action, or either endpoint of a topology link (a link opens on its first endpoint).
2. Dialog: *Topology interfaces* wired to the node listed first (a single one is pre-ticked); *All live Linux interfaces (n)* collapsed; *Advanced: other capture targets* (scope, search, capture-target selector, **All host targets**) unfolds only when no target resolved. Prepare/Start needs a target plus a ticked interface; the search box is disabled during discovery; node/menu Capture is disabled only when the manager reports capture disabled (`captureActionAttrs()`). The dialog reads the lab drawing (`/api/labs/{id}/topology`) once per open.
3. **Start browser capture** → **Open Wireshark in browser** (noVNC in a tab).
4. Viewer: one toolbar row with status inline; *How to save a capture* toggle (File → Save As under `/pcaps`, full name ending `.pcapng`); **Download saved captures (.tar)** (answers *No saved captures yet …* in place when empty; fetches first, then hands the URL to the browser); **Reconnect viewer**; **Sessions in this browser**; **End session** (with confirmation).
5. Limits: 4 concurrent sessions, 15 min idle, 2 h lifetime, cleanup every 15 s. Sessions are cookie-owned per browser profile.

### 2.12 Diagram editor (LAB-OPERATIONS, wiki Part 14, GRAFANA-MAP)
- **Edit diagram** (topology toolbar) or **Edit topology diagram** (Lab actions). Select node/annotation on canvas or from the item list; drag or enter coordinates; add text, boxes, circles, lines; properties panel for text, size, colours, opacity, border style; **Undo**; **Fit diagram**; **Save diagram** (persists to manager; sets `placed`); closing with unsaved edits offers **Keep editing** / **Discard changes**; saving is rejected if another session changed the map (reopen to load). **Download annotations JSON** and **Export draw.io** include unsaved edits and never write VM files. Structural changes belong in the VM YAML. Saving regenerates the Grafana lab map.

### 2.13 SuperPuTTY export (NODE-FEATURES, wiki Part 13)
- **Export sessions** in the lab toolbar → `<lab-name>.xml`, sessions as `Lab name/Node short name`; all inventory nodes included; duplicate session names rejected; passwords omitted unless **Include saved passwords as plain text** is checked; unknown kinds prompt for a username.

### 2.14 Debug panel (DEBUG-PANEL)
- **Debug panel** (sidebar bottom; also linked from **Deploy New Lab** and the VM connection guide; `/static/debug.html`). Controls: **Refresh**, **Failures only**, **VM folder** input, **Run read-only checks**, independent **browse** and **capabilities** results, **Download report** (JSON), **Last audit write** flag, **Release** display. Latest 200 API requests; one probe at a time; 90 s per helper response; reports omit credentials, hosts, paths, bodies.

### 2.15 Manager-only removal (VM-CONNECTION, wiki Part 17, GIT-PROGRESS)
- **Remove lab** (one workspace; backup files and audit logs remain; default exclusion; **Clear exclusion** re-offers it).
- **Manager settings → Start fresh** (type `RESET`; clears workspaces, credentials, schedules, backups, jobs/logs, exclusions; retains VM connection, password, fingerprint, `state.key`; reset journal resumes if interrupted). Close terminals, wait for jobs, resolve pending Git saves (or **Keep snapshot only**) first.
- Neither deletes VM sources or containers.

---

## 3. Terminology the docs establish

| Term | Meaning | Doc |
|---|---|---|
| Lab / workspace | A saved manager record: nodes, map, VM source path, logins, jobs | LAB-OPERATIONS, ARCHITECTURE |
| Linked lab | A workspace matched to a VM topology path by discovery | LAB-OPERATIONS, agent instr 1.22.0 |
| NOS booting / NOS ready | Deployment-bar readiness states from `show version` probes every 20 s | LAB-OPERATIONS, TOUR |
| Containerlab default login | Kind default credentials used when no profile/inventory login exists; order profile > inventory > default | CHANGELOG 1.22.0 |
| Credential profile | Saved NOS login (More → Credentials); *Generic SSH / Linux (terminal only)* for unmapped kinds | NODE-FEATURES |
| Last SSH check | Nodes-table column; automatic or manual `show version` result with timestamp | LAB-OPERATIONS |
| Test NOS login / Test login | Ansible/SSH `show version` check; automatic once per boot, manual in Node details | LAB-OPERATIONS, NODE-FEATURES |
| Lab actions | The lab's command menu (also right-click / Shift+F10) | LAB-OPERATIONS |
| Review / preview | Mandatory pre-execution screen for every host command; 5-minute token | LAB-OPERATIONS |
| Operation output / Operation history | Streamed helper output with banner; persisted outcomes | CHANGELOG 1.22.0, wiki |
| Destroy deployment (+ cleanup) | `containerlab destroy --cleanup`; removes containers and `clab-<name>` | CHANGELOG 1.26.0 |
| Save configurations | Containerlab kind-dependent save; not a manager backup | LAB-OPERATIONS |
| Manager backup / Backup history | Ansible-captured configs under `backups/<lab>/latest` and `history/<job>` | ARCHITECTURE, NODE-FEATURES |
| Back up all configs | Topology-header action reviewing all ready nodes | LAB-OPERATIONS |
| Include in backups | Per-node schedule selection checkbox | wiki Part 13 |
| Save progress | Capture selected devices → export `latest/` → commit → push | GIT-PROGRESS |
| Saved on VM / Pushed | Local snapshot-or-commit exists / push verified | GIT-PROGRESS |
| latest / baseline / checkpoints | Repository folders: rolling save, explicit reference, named milestones | GIT-PROGRESS |
| Registration / subfolder (prefix) | A checkout + branch + folder bound as a lab's destination | GIT-SETUP |
| Where this lab lives | Folder-browser panel of the connected repository | GIT-PROGRESS |
| This lab / created on first save | Folder tags in the browser | GIT-PROGRESS |
| Folder move | Job that moves saved files to a new folder | GIT-PROGRESS |
| Keep snapshot only | Explicit dismissal of a pending export | GIT-PROGRESS |
| Retry export / Push saved progress | Recovery actions on a failed save | GIT-SETUP |
| Load version | Read/download a version as ZIP; never applies to devices | GIT-PROGRESS |
| Apply to running lab… / Replace running configuration | Managed Junos restore job (load override + commit confirmed) | GIT-PROGRESS, agent 1.28.0 |
| Restore-grade candidate / `.jcfg` | Hierarchical `show configuration` artifact captured with each Junos backup | GIT-PROGRESS |
| Safety options | Rollback-timer control in the restore review | GIT-PROGRESS |
| reference / work / start / solution / broken-NN | Recommended course folder vocabulary | NAMING |
| Automatic telemetry | Per-lab setting enabling gNMI provisioning and collection | TELEMETRY |
| Telemetry node states | Off, Waiting, Configuring, Connecting, Streaming, Stale, Unsupported, Failed | TELEMETRY |
| Remove manager-added lines… | Deletes only recorded gNMI lines; only while telemetry off | TELEMETRY |
| Grafana ↗ / Lab map in Grafana ↗ | Header button; on-demand start | TELEMETRY, GRAFANA-MAP |
| Lab overview / Interfaces / BGP neighbours / Lab maps | Grafana dashboards and folder | TELEMETRY |
| Capture packets / Capture / Start browser capture / Open Wireshark in browser | Capture entry points and dialog buttons | CAPTURE |
| Topology interfaces / All live Linux interfaces / Advanced / All host targets | Capture dialog sections | CAPTURE |
| Session (capture) | A labelled Wireshark container; Reconnect viewer, End session | CAPTURE |
| Edit diagram / Save diagram / annotations | Manager map editor and its persisted drawing | LAB-OPERATIONS |
| Unmatched | Drawing node not mapped to inventory | GRAFANA-MAP, NODE-FEATURES |
| Export sessions | SuperPuTTY XML download | NODE-FEATURES |
| Sync from VM | Refresh imported files without overwriting saved connection settings | LAB-OPERATIONS |
| Ready to import / Import lab | Discovery states and confirmation | wiki Part 12 |
| Manual discovery / Discovery file details | Fallback upload and diagnostics | wiki Part 12 |
| Remove lab / Clear exclusion / Start fresh (`RESET`) | Manager-only removal actions | wiki Part 17 |
| VM connection / Save and test connection / Trust a replacement SSH host key | Connection dialog and its actions | VM-CONNECTION |
| Debug panel | `/static/debug.html` diagnostics | DEBUG-PANEL |
| clab-discovery | Restricted VM SSH account; forced gateway | ARCHITECTURE |

---

## 4. Persistence domains and the actions that affect each

| Domain | Where | Actions that write it | Actions that only read it |
|---|---|---|---|
| Running configuration on nodes | Device memory | Apply to running lab… (Junos; full replacement, pre-backup first); telemetry provisioning (adds only missing gNMI lines, scoped commit); Remove manager-added lines…; user commands in the SSH terminal; Save configurations (containerlab kind save); lifecycle deploy/redeploy/destroy/restart (reboot to startup) | Back up / Back up all configs / scheduled backups / Test login / readiness probes (read only) |
| Manager backups | `/srv/containerlab-node-manager/data/backups/<lab>/latest` + `history/<job-id>` | Back up (node), Back up all configs, scheduled backups, Test NOS login results, Save progress / Save locally / Save checkpoint (capture step), restore pre/post backups (`restore-pre`, `restore-post`), Start fresh (deletes all) | Node details downloads, Backup history downloads, Set baseline (selects a recorded capture), Git export (uses one completed job, not rolling latest) |
| Git latest / checkpoints / baseline | Registered checkout on VM (`~/labs/<repo>`) + remote | Save progress, Save locally, Save checkpoint…, Set baseline…, Push saved progress, Update from remote (fast-forward), Retry export, Save this lab here (Folder move), Connect by URL (clone), scaffold-lab.py | View changes / History, Load version…, Apply to running lab…, Where this lab lives tree, Keep snapshot only (dismisses; no repo change) |
| Git registration / connection | `/etc/clab-manager/git.json` (host), lab record in `state.enc` (manager) | Git repository settings save, Save this lab here, New folder…, Use a different repository…, Connect by URL, terminal wizard/`setup-git.sh` | Status refresh |
| Topology / source files on VM | Trusted roots (`/etc/containerlab`, `/srv/containerlab-node-manager/projects`), `.clab-manager-history` | New topology (create only), Delete undeployed VM YAML (recovery copy kept), Clone repository / popular labs, deploy (creates `clab-<name>`), destroy --cleanup (removes `clab-<name>`), Save configurations (containerlab writes) | Topology browser read (1 MiB cap), annotations read for map, Sync from VM, discovery bundles; Save diagram / exports never write VM files |
| Annotations / layout (manager drawing) | Encrypted state (`state.enc`), whitelisted drawing fields, schema 3, `placed` flag | Save diagram (sets `placed=True`, never replaced afterwards), Import topology, Sync from VM / topology reimport (can replace an edited map), Deploy lab / Save to manager (parse with annotations), discovery `topology.positions` (only for grid-only drawings), Remove lab, Start fresh | Fit map, exports (Download annotations JSON, Export draw.io), Grafana map generator (`clab-map-<id>.json`) |
| Encrypted manager state | `state.enc` + `state.key` | VM connection save, lab import/registration, credential profiles, Edit connection, schedules, jobs (backup, progress, restore, operations), telemetry settings and applied lines, favorites, exclusions, Start fresh (`RESET`) | `/api/state` polling |
| Audit log | `events.jsonl` (bounded) | Every action (e.g. `telemetry.configure`, `telemetry.clear`, `grafana.start/stop`, `lab.register`, `topology.positions`); terminal keystrokes never logged | Action logs tab, Debug panel *Last audit write* |
| Telemetry session store | Manager memory only (15 min, 130 points) | Collector; cleared by stop/destroy/redeploy/removal/reset/restart/turning telemetry off | Prometheus scrape `/api/telemetry/metrics` |
| Generated lab-map dashboards | `data/telemetry/dashboards/clab-map-<id>.json` | Publisher on lab save/rename/redraw/removal (within 5 s; Grafana picks up within 30 s) | Grafana |
| Capture sessions | Wireshark containers + tmpfs-backed `/pcaps` volume | Start browser capture, End session, expiry sweeps | Download saved captures (.tar) |
| Operations config | `/etc/clab-manager/operations.json`, `engineer.json` | VM scripts only | Topology browser roots, clone/catalog capability |
| Browser-local storage | — | The assigned docs name no sessionStorage/localStorage keys; only capture cookies (session ownership per browser profile) are documented | — |

---

## 5. Security and behavioural rules a UI redesign must not break

Front-end code rules (agent instructions 1.25.0–1.28.0, NODE-FEATURES):
1. Self-only Content Security Policy: scripts only from this origin, no CDN, no inline styles anywhere except `terminal.html` (xterm); no frontend build step; vendored xterm.js under `app/static/vendor/`.
2. Every interpolation into markup goes through `esc()`.
3. Every static asset is referenced with `?v=<release>` in every HTML page; `app.js` keeps the footer fallback `state.version||'<release>'`; both are checked by `verify-release.py`.
4. Never apply a stroke rule (especially `stroke-dasharray`) to `.topology-wire path` without excluding `path.capture-hit` (the 16 px transparent hit path uses `pointer-events: stroke`).
5. POST routes behind the guard need a body; the Grafana page posts `{}`.
6. `grafana.html` accepts only `#path=` and `#title=` and validates the path with the fixed regex; the origin is built from `location` plus the manager-announced port.
7. `capture.js` reads the drawing once per dialog open; `captureChecked()` must read both interface lists; `capture-advanced` unfolds only when no target resolved; Capture disabled only when the manager reports capture disabled; search box disabled during discovery.
8. `openVmDialog`/`maybePromptVmConnection` prompt once when discovery is loaded and unconfigured, never for a configured or dismissed connection.

Command execution and confirmations:
9. Every host command (deploy, redeploy, destroy, start, stop, restart, apply, save, new topology, delete YAML, clone) shows a preview and requires confirmation; tokens expire after five minutes and bind the VM connection, file digest and deployment state; any change needs a new preview.
10. Destroy always sends `--cleanup` unless the helper reports it unsupported; the review names the generated folder.
11. Deploy lab saves the workspace before the review; Save to manager saves without deploying.
12. Manager backups and import changes are blocked during an active lab operation; interrupted jobs need inspection before retrying.
13. Removed commands (YAML editing, copy path, link project, open folder, edit layout, directional exports, SSHX/GoTTY, fcli) must not be re-added.

Git:
14. UI sends only registration IDs, folder names and reviewed choices; never command text, tokens or passwords; helper re-validates every path.
15. Connect by URL and Git repository settings require an explicit acknowledgement that full configurations will be committed/pushed.
16. Pending saves block Remove lab, Start fresh, replacing the repository connection, changing VM identity and folder moves; password rotation for the same VM/account stays allowed.
17. Keep snapshot only requires explicit confirmation; Set baseline over an existing baseline requires review; Save checkpoint needs a new name.
18. Folder rules mirrored in the browser (`gitFolderChoice`, `gitCanCreateIn`): no overlap, no nesting inside another lab's folder, `latest/`/`baseline/`/`checkpoints/` not selectable, root vs subfolder exclusive; every nested-path segment validated like a single name.
19. No force push, stash, reset or `git add .`; Update from remote is fast-forward only.

Restore:
20. Apply to running lab… appears only when `restore_supported`; legacy snapshots and non-Junos nodes are view/download only; pre-restore backup is mandatory; commit-confirmed is real, never faked; danger-styled confirm; acknowledge + idempotent request id; direct node-SSH path, no host helper.

Connection, terminals, capture:
21. VM password never returned to the browser; blank keeps it; fingerprint change blocks until the *Trust a replacement SSH host key* checkbox is used; dialog defaults: automatic discovery on, trust-replacement on.
22. Terminals use a single-use ticket and origin check; max 32 concurrent terminals/checks; SSH all nodes needs popups; SSH for linked labs opens only after NOS readiness.
23. Capture: End session confirms; 4 sessions / 15 min idle / 2 h; the browser never receives the service token; Download reports *No saved captures yet* instead of an empty archive.

Telemetry:
24. Remove manager-added lines… only while automatic telemetry is off; pre-1.23.0 labs need the explicit tick before any device write; Retry failed nodes only for failed/stale nodes; Stop Grafana now in the same dialog; Grafana button hides when the stack is disabled.

Map and editor:
25. Links show imported wiring, never live status (live state lives in Grafana); right-click menu is Capture packets / SSH / Back up configuration / Node details; Shift+F10, arrow keys, Escape; unmatched nodes have no actions.
26. Editor: Undo; concurrent-edit rejection; Keep editing / Discard changes on close; exports include unsaved edits and never write VM files; Save diagram never rewrites the VM annotations file.

Removal:
27. Start fresh requires typing `RESET`; retains VM connection, password, fingerprint, `state.key`; Remove lab affects one workspace and sets an exclusion (Clear exclusion re-offers).

Timers documented (must survive): discovery every 30 s; readiness probe every 20 s per node; refused login retried each minute after three refusals; automatic test up to three per boot; telemetry retry backoff 15 s → 5 min (30 s cap for an unreachable port); stale after 45 s; Grafana idle stop 15 min (grace 90 s); dashboards refresh 10 s; Prometheus scrape 10 s; lab maps within 30 s; capture cleanup every 15 s; debug probe 90 s per helper response; review token 5 min; restore rollback timer default 5 min; telemetry poll (removed 1.25.0) was 4.5 s.

---

## 6. Release procedure (verify-release.py + agent instructions)

Version-marker locations (`FIELDS`, must equal `clab-backup-ui/VERSION`):
- `clab-backup-ui/app/__init__.py` — `__version__ = '…'`
- `clab-backup-ui/app/host_files.py` — `'helper_version': '…'`
- `clab-backup-ui/app/host_operations.py` — `VERSION = '…'`
- `clab-backup-ui/app/host_git.py` — `VERSION = '…'`
- `clab-backup-ui/Dockerfile` — `org.opencontainers.image.version="…"`
- `clab-backup-ui/compose.yml` — `image: clab-backup:<v>`
- `deploy/compose.capture.yml` — `image: clab-capture-service:<v>`
- `clab-backup-ui/app/static/app.js` — `state.version||'<v>'` (footer fallback)
- `clab-backup-ui/app/static/{index,terminal,workspace,vm-connection,debug,capture-setup,capture-session,grafana}.html` — every `/static/...?v=<v>` reference

Documentation checks (`verify_docs`): living docs under `README.md`, `docs/`, `deploy/`, `clab-backup-ui/README.md`, `clab-backup-ui/NODE-FEATURES.md`, `clab-backup-ui/app/static/vm-connection.html`, `clab-backup-ui/app/static/capture-setup.html` may name only the current release (history phrased as "since x.y.z" / "x.y.z or later"; third-party versions named by component); no `projects/v1.x.y` folders or `clab-backup:1.x.y` image tags. History files (`docs/CHANGELOG.md`, `clab-backup-ui/VALIDATION.md`, `agent instructions.md`, `docs/archive/`) may name any release. Leads: README `Current release: **x.y.z**`; CHANGELOG first `## Changes in x.y.z`; VALIDATION and agent instructions first `# … x.y.z` heading.

Steps to cut a release (agent instructions 1.25.0; README Development):
1. `python3 deploy/set-release.py NEW` (moves every FIELDS marker and current-release tokens in living docs).
2. Write the three history sections by hand: CHANGELOG "Changes in NEW", VALIDATION "… — NEW", agent instructions "… — NEW" at the top.
3. `python3 deploy/verify-release.py` (both checks; `--runtime` lockstep only, `--docs` docs only); CI (`release-check` workflow) runs it plus the Python and `node --test` suites, including `test_restore*.py`, `test_restore_ui.js`, `test_host_git.py`, both git UI suites, `test_grafana_ui.js`, `test_telemetry*.py`, and the real capture and Grafana smoke tests.
4. VM scripts call `verify-release.py --runtime` before touching the host; upgrade with `install.sh`/`start-manager.sh`; refresh helpers (`setup-git.sh --refresh` when `host_git.py` changes) and rebuild the image; new static scripts must be added with `?v=<release>` and to the CI node test list.

---

## 7. Recently live-validated on the dev VM (VALIDATION.md 1.22.0–1.28.0)

- 1.28.0: nested New folder… (`CCNP-SP/Labs/Week-04/BGP/Final-State`); Save progress capturing the `.jcfg` artifact and pushing; `/git/version` reporting `restore_supported`; Apply to running lab… preflight and restore on cJunosEvolved PTX1 (stale `lo0` removed, hostname reset, root-auth synthesised, container `StartedAt` unchanged); pre-restore backup; legacy-backup refusal (400) and out-of-history commit refusal (409); apply straight from a folder without rebinding (Broken → Final); History/Load version labelling every folder; scaffold-lab `init`/`snapshot`. Not verified: manager-orchestrated restore on vJunos-switch, two-node restore, forced rollback, XR/EOS restore.
- 1.27.0: tree API, destination move with file move (Folder move job pushed), refusals (same folder, nested), folder registration without connecting, Connect by URL refused without push access, page-link adoption of an existing checkout; browser check of the connected card, Where this lab lives, disabled Save this lab here, settings select, Progress saves list. Not verified: fresh clone via URL, auto identity from `gh api user`, moving baseline/checkpoints, dialogs clicked in a browser.
- 1.26.0: annotations placing a flat map on discovery; Grafana on-demand start from `grafana.html` and idle stop; `check-install` PASS with stopped Grafana; Lab actions menu showing Destroy deployment + Redeploy + cleanup only; destroy review with cleanup path; deploy-first path with Validate / preview topology using annotations. Not exercised: Stop Grafana now button, CI Grafana stop/start.
- 1.25.0: guided installer end to end; header tabs Topology/Nodes/Backup history/More with no Telemetry tab; Lab map in Grafana ↗ link; link hover geometry fix; right-click menu without View telemetry; Telemetry settings dialog contents.
- 1.24.0: Flow panel install, map dashboard provisioning, live link colours under traffic and shutdown; Telemetry tab button Open lab map in Grafana ↗ (tab since removed).
- 1.23.1: Prometheus flag fix, cEOS sample ordering, on-change heartbeat, idle BGP groups, retry cap, settings off/remove-config/on cycle, backup while streaming.
- 1.23.0: fixture-only (no live device).
- 1.22.0: readiness on a running pair, automatic NOS login test, VM connection defaults, capture dialog layout and viewer toolbar, destroy banner, landing page states, Deploy a new lab → Deploy lab workspace-first, known_hosts fix and redeploy cycle.

---

## 8. Docs whose wording will need updating when UI labels/locations change

| Doc | Sections naming UI elements |
|---|---|
| docs/LAB-OPERATIONS.md | Retained commands table; NOS readiness after deployment; Telemetry after readiness; Interactive diagram and topology actions; Review and persistence; Recovery; Apply a saved configuration to a running node |
| docs/GIT-PROGRESS.md | One-time setup (Git repository tab); Recovery after manually committing; Everyday buttons; Where this lab lives; Failure and recovery table; Loading an earlier lab version; Apply a saved configuration to a running node |
| docs/GIT-SETUP.md | Intro (**Git repository** tab → Connect a repository by URL); First setup final step; Connect or switch a repository from the manager; One repository, one subfolder per lab; Fix a failed save |
| docs/TELEMETRY.md | What you get; Node states; Settings; Health check; Live acceptance procedure |
| docs/CAPTURE.md | Intro paragraph; Sessions and files; Coverage; Health, troubleshooting and removal |
| docs/DEBUG-PANEL.md | Whole page (panel location, Refresh, Failures only, VM folder, Run read-only checks, Download report, Last audit write, Release) |
| docs/VM-CONNECTION.md | First launch (dialog fields, Save and test connection, trust checkbox); Upgrades and password changes; Troubleshooting; closing paragraph (Manager settings → Start fresh, Remove lab) |
| docs/TOUR.md | Every caption and screenshot (all screenshots will be stale after a redesign); the Grafana ↗ note |
| docs/NAMING.md | What the manager keys on; Git repository structure (Where this lab lives, View changes / History, Save checkpoint); Repositories (Use a different repository → Connect by URL, Update from remote) |
| docs/GRAFANA-MAP.md | What a new lab gets by itself (button labels, Edit diagram); What you still craft per lab; Troubleshooting |
| README.md | What it does; A quick look (screenshots); Quick start steps 3–5 |
| clab-backup-ui/NODE-FEATURES.md | Node actions; Browser terminal behaviour; Deployment checks; Topology map and session export |
| docs/WIKI-MASTER-GUIDE.md | Part 11 (VM connection form); Part 12 (Refresh discovery, Ready to import, Import lab, Sync from VM, Discovery file details, Manual discovery); Part 13 (tabs and More menu — stale: still lists Git repository under More; right-click menu omits Capture packets; says live restore unavailable); Part 14 (Lab actions table — stale "Deploy New Lab in a new tab", "Add project / deploy project"; Edit the diagram and export; Sidebar and running lab details; Review commands); Part 17 removal-action table; Part 18 "Topology browser says operations helper is unavailable"; Step 21.3 and "Folders and buttons" (stale: "Load version downloads files… Live restore remains unavailable") |
| docs/ARCHITECTURE.md | Network telemetry diagram (Lab actions → Telemetry settings, Grafana ↗ button); Module map row for `app/static/` |
| docs/CHANGELOG.md, clab-backup-ui/VALIDATION.md, agent instructions.md | History; not reworded, but any new release must add sections at the top per the release rules |

Known stale wording already present (do not copy into the redesign): wiki Part 13/21 "More → Git repository" and "live restore unavailable"; wiki Part 14 "Deploy New Lab … in a new tab"; TOUR states the header "has since gained Grafana ↗; the rest is as shown".
