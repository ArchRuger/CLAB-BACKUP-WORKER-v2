# Student-centred redesign — design specification (contract for implementation)

Repository: `/home/clabllm/projects/clab-manager` (app under `clab-backup-ui/`). Target release **1.29.0**.
Frontend stays FastAPI + vanilla JS + HTML + CSS; no framework, no bundler, no CDN, self-only CSP, `esc()` on every interpolation, no inline styles.

Companion documents in this folder: `UX-AUDIT.md` (problems found in the running app), `inventory/MERGED-INVENTORY.md` (every existing capability — the regression checklist), `inventory/vocabulary.md` (backend state values), `inventory/tests.md` (test contracts), `inventory/css.md` (current CSS and the class hooks that must survive), `inventory/docs.md` (rules and release procedure).

---

## 0. Non-negotiables

1. **Zero functional regression.** Every row of `MERGED-INVENTORY.md` must remain reachable and working. Reorganise, relabel, progressively disclose — never delete. If something cannot be preserved, stop and report it.
2. **Backend untouched** unless a genuine UX need appears (none identified). No route, payload, state-schema or helper changes.
3. **Keep the global function names and the production file names** that the JS test harnesses load (`app.js`, `management.js`, `operations.js`, `git-progress.js`, `git-places.js`, `restore.js`, `topology.js`, `topology-render.js`, `diagram-editor.js`, `capture.js`, `capture-session.js`, `debug.js`, `grafana.js`, `workspace.js`, `terminal.js`). New behaviour goes into new files or new functions; existing functions may be extended or have their markup changed, but their names, arguments and return semantics stay.
4. **Keep every element id, data-attribute and class hook** listed in `inventory/css.md` §20 and `inventory/tests.md` §14 unless the spec below explicitly relocates it (relocation keeps the id; only its position in the DOM changes).
5. **Every visible string a CCNA student would not understand moves behind "Details" / "Advanced" or is rewritten.** Backend messages stay precise in the details layer.
6. **Confirmations only for real consequences**: destroy, redeploy/cleanup, replace running configuration, disconnect save location, remove lab, start fresh, folder moves, end capture session, keep-snapshot-only. Read-only actions never confirm (e.g. "View running lab details" must not ask "Confirm to run this action" — it stays as the existing preview/confirm flow because the helper protocol requires a token, but the copy becomes "Refresh the list of running labs on the VM" with the confirm button "Show running labs"; the dialog is moved under Manager ▾ so students rarely meet it).
7. **Accessibility**: real `<button>`s, visible focus, dialogs via `<dialog>`, `aria-label`s on icon-only controls, status text never colour-only, keyboard-operable menus (details/summary based menus close on Escape and on outside click).
8. **Performance**: keep the 4 s state poll, the existing `_markup` diffing pattern (only touch `innerHTML` when the markup string changed), no new polling loops, no per-render re-creation of the SVG map.

---

## 1. Information architecture

```
Home — "My labs"                         (#home)                 activeId === ''
└── Lab workspace — "<Lab name>"         (#lab-content)          activeId === lab.id
    ├── Lab header: name · state pill · "n of m devices ready" · progress state · [Save progress] [Lab actions ▾]
    ├── Situational banner (only when something needs the student's attention or is in progress)
    ├── Tabs: Topology | Devices | Progress | Tools | Advanced        (data-tab values: topology, devices, progress, tools, advanced)
    └── Device workspace — drawer opened from any device (#details-dialog)
Manager ▾ (top bar, every page)          VM connection · Refresh lab list · Deploy a new lab · Import lab files · Running labs on the VM · Operation history · Manager settings · Diagnostics
```

### 1.1 Top bar (`header.topbar`, on index.html only; other pages keep their own headers)
- Left: brand mark + "Containerlab Node Manager" (`#nav-home`, a link to Home).
- Centre: breadcrumb `My labs / <lab name>` — "My labs" is a button (`#crumb-home`); `#breadcrumb` keeps its id and shows the lab name (or is hidden on Home). Next to the lab name a lab switcher `details#lab-switcher` whose summary is "▾" (aria-label "Switch lab") and whose body is the existing `nav#labs` markup (so `render()` keeps writing lab buttons into `#labs`).
- Right: activity indicator `#worker-state` (existing id; text becomes "Saving progress…", "Backing up…", "Restoring…", "Lab operation running…", or hidden when idle — never "Worker idle"), then `details#manager-menu.menu` with summary "Manager ▾". Menu items reuse the existing ids: `#vm-settings` "VM connection…", `#vm-refresh` "Refresh lab list", `#vm-projects` "Deploy a new lab…", `#new-lab` "Import lab files…", `#inspect-all` "Running labs on the VM…", `#operations-history` "Operation history…", `#manager-settings` "Manager settings…", link "Diagnostics" (`/static/debug.html`), and a footer line `#vm-summary` (VM connection status) plus `#supported-release`.
- `#discovered-labs`, `#excluded-labs`, `#discovery-files` (with `#discovery-file-list`) keep their ids and move into the Home page's "Other labs on the VM" section (see 1.2). `#operation-summary` moves into the lab banner area (see 1.3).

### 1.2 Home — My labs (`section#home`)
Shown when `activeId` is empty (`refresh()` must no longer auto-select the first lab; it only clears a stale id). `selectLab(id)` navigates to a lab; `goHome()` returns.
- **Continue card** (`#home-continue`): shown when there is a most-recently-opened lab (localStorage `clab.lastLab`) that still exists: "Continue <lab>" with its state pill, "n of m devices ready", "Saved <relative time>" and a primary [Open lab]. Hidden when only one lab exists and… no: shown whenever a last-opened lab exists.
- **Lab cards** (`#lab-cards.lab-grid`): one `article.lab-card` per lab (favourites first, then by name): name (`h3`), `labState` pill, `n of m devices ready` (or "Not running"), `Last saved <relative>` (from `progressState`), `Last opened <relative>` (localStorage `clab.opened.<id>`), primary [Open lab] (`data-lab` — existing delegated click on `#labs` is generalised: the handler listens on `#home` too). Secondary, subtle: [Start lab] when the lab is not running (navigates to the lab and clicks `#lab-start`). No destroy, no Git internals on cards.
- **Empty state** (existing `section#empty` and its children `#deploy-empty`, `#vm-connect-empty`, `#empty-vm-note`, `#empty-discovered`, `#empty-discovered-list`, `#import-empty`, `#import-inventory-empty`): shown only when there are no labs. Copy: h2 "No labs yet", p "Deploy or import a containerlab topology to get started." Buttons: [Deploy a new lab] [Connect the VM] (existing gating by `renderManagement()`). Keep the "Already running on the VM" list.
- **Other labs on the VM** (`#home-discovered`): when labs exist, the discovered-but-not-imported list (`#discovered-labs`), excluded labs (`#excluded-labs`) and the `details#discovery-files` live here in a collapsed "Details" block. Wording: "Also running on the VM" / "Import".
- **Secondary actions row**: [Deploy a new lab] (`#import-top` keeps its id; on Home its text is "Deploy a new lab", on a lab it is "Replace inventory…" and lives in Advanced) — simpler: `#import-top` stays in the DOM on the lab page inside Advanced → Lab source; the Home row uses `#deploy-empty`-like buttons: [Deploy a new lab] (`#home-deploy` → `openDeploy()`), [Import lab files…] (`#home-import` → the setup dialog, same as `#new-lab`), [Import an Ansible inventory…] (`#home-import-inventory` → `openImport()`).

### 1.3 Lab workspace
**Header** (`header.lab-header`):
- `h1#title` lab name.
- `p.lab-status-line`: `<span id="lab-state" class="pill …">Running</span> · <span id="lab-ready">6 of 6 devices ready</span> · <span id="lab-progress">Saved to Git 12 minutes ago</span>`.
- Actions: `#git-save-progress` (existing id; label managed by git-progress.js: "Save progress" / "Connect a save location…" / "Saving…") with the existing split menu `details#git-save-menu` (summary "▾", aria-label "More save actions"; items keep `data-git-action` values `local, checkpoint, baseline, history, load, push, update, settings` but are relabelled: "Save on this VM only", "Create checkpoint…", "Set baseline…", "Saved versions & history", "Load a saved version…", "Upload saved progress", "Update from the repository", "Save location settings…"). Then `details#lab-actions-menu.menu` (summary "Lab actions ▾").
- **Lab actions ▾ menu** (`.menu-list`, groups separated by `.menu-sep`):
  1. Lifecycle: `#lab-start` "Start lab" (existing id, gating and title preserved; when the lab is running the item reads "Start stopped devices"), `button[data-op-action=stop]` "Stop devices", `[data-op-action=restart]` "Restart devices", `[data-op-action=redeploy]` "Redeploy lab". These reuse the existing operations preview flow (`opTask`/`openLabOperations` handlers) — the agent wires each item to the same function the operations dialog buttons call.
  2. Lab: `#sync-vm` "Sync topology from VM" (hidden unless updates available, as today), "Edit diagram" (`#map-edit` stays in the map toolbar; the menu item triggers it), "Telemetry settings…", "Packet capture…" (`#capture-open` stays on Tools; the item triggers it), "Lab files…" (opens the existing topology/file browser for this lab), "Operation history…" (`#operations-history` equivalent, filtered to the lab if the dialog supports it; otherwise the same dialog), "All lab operations…" (`#lab-actions`, existing id, opens `openLabOperations()`).
  3. Danger (`.menu-danger`): `#lab-destroy` "Destroy lab…", `[data-op-action=redeploy-cleanup]` "Redeploy with cleanup…", `#remove-lab` "Remove from this manager…".
  Existing ids `#update-definition`, `#link-deployment`, `#import-top` (Replace inventory) live in Advanced → Lab source, not in this menu.
- **Situational banner** (`#lab-banner.banner`, hidden when nothing to say). Exactly one of, by priority: operation running ("Starting lab… [View output]" — `#operation-summary` text goes here), restore running, save in progress (only when not already obvious), needs-attention (login failed: "RTR3 is running but SSH login failed. [Check credentials]"), starting ("Lab is starting — 4 of 6 devices ready. SSH becomes available automatically."), stopped/not deployed ("This lab is not running. [Start lab]"), VM unreachable ("The lab VM cannot be reached. Status may be stale. [VM connection]"), unlinked ("This workspace is not linked to a running lab. [Link deployment]"), save needs attention ("Your progress is saved on this VM but could not be uploaded to GitHub. [Retry] [Details]"), source updates available is NOT a banner (it is an Advanced detail).

**Tabs** `nav.tabs` with `button[data-tab]` for `topology`, `devices`, `progress`, `tools`, `advanced` (`aria-selected`). `showTab(name)` maps legacy names: `inventory→devices` (and turns on the technical table), `git→progress`, `backups→tools` (scroll to backups), `credentials→advanced`, `logs→advanced` (scroll to logs). Section ids: `#topology-view`, `#devices-view`, `#progress-view`, `#tools-view`, `#advanced-view`; the legacy sections `#inventory-view`, `#git-view`, `#backups-view`, `#credentials-view`, `#logs-view` keep their ids and are nested inside the new panels (so `for(name of […]) $(name+'-view').hidden=…` keeps working — `showTab` hides only top-level panels and shows the nested ones according to the sub-state).

**Topology tab** (`#topology-view`): the map is the content. Layout: `div.topology-stage` containing `svg#topology-map` sized to fill the available height (min 480px, `calc(100vh - header)` capped), with a compact overlay toolbar `.map-tools` (Fit `#map-fit`, `#map-in` "+", `#map-out` "−", `#map-expand` "Expand", `#map-edit` "Edit diagram", and an overflow `details.menu` "More ▾" holding `#import-map` "Import topology…", `#map-ssh-all` "Open all CLIs ↗", `#map-backup-all` "Back up all configurations"). `#map-status` becomes a small caption under the map. Beside the map on ≥1280px a **device rail** (`aside#topology-devices.device-rail`) lists devices (name, state pill, [Open CLI]); below 1280px it collapses under the map. Hint text: "Click a device to open it. Right-click for more actions." Node visuals: `topology-render.js` adds `class="map-device state-<key>"` and a small `circle.device-state-dot` per node from `deviceState(node)`; colours via CSS only (ready green, starting amber, attention red, unavailable grey, neutral for unmatched/unknown). Left-click on a node opens the Device workspace (`openDetails(name)`) — the existing click handler that only selected/labelled stays as a fallback for unmatched nodes. Right-click menu (`#node-context-menu`) items: "Open CLI ↗", "Capture traffic…", "Back up configuration", "Device details".

**Devices tab** (`#devices-view`): heading "Devices", `input#search` (existing id, filters both lists), `#device-list` — one `.device-row` per node: name (`button.node-name[data-details]`), platform label, state pill + one-line explanation when not Ready, actions [Open CLI] (`button.ssh-action[data-terminal]`, disabled with a `title` and an inline explanation when not ready) and [Details] (`data-details`). A toggle `#devices-technical` "Technical view" swaps in the existing table (`#inventory-view` with `tbody#nodes`, checkboxes, endpoints, last SSH check, last backup, actions) — nothing removed; `renderNodes()` keeps rendering it. `#inventory-caption` keeps its id (shown in the technical view).

**Progress tab** (`#progress-view`) — rendered by `gitShowRepository()` into `#git-repository-content` plus the header pieces:
1. **Status card** (existing `#git-progress-bar` moves here; `#git-destination` shows "Saving to <repository> › <folder>" in words, `#git-progress-status` shows the `progressState` sentence). Buttons: [Save progress] (`#progress-save`, proxies `#git-save-progress`), [Create checkpoint…], [Set baseline…], and a `details.menu` "More ▾" (Save on this VM only, Upload saved progress, Update from the repository, Save location settings…). All carry the same `data-git-action` values.
2. **Saved versions** (`#git-saved-versions`): Latest (this lab's folder `latest/`), Checkpoints (named, newest first), Baseline, then "Other saved states in this repository" (every other folder that has a `latest/` — the list the History dialog shows today, labelled by folder, e.g. `reference/solution`). Each row: name, when, device count, [View], [Compare with current], [Apply to running lab…] (only when `restore_supported`/`restorable`). The existing dialogs (`#git-history-dialog`, `#git-version-dialog`, `#git-diff-dialog`) keep doing the work; this list is the entry point. Empty state: "You haven't saved this lab yet. Save progress creates a configuration snapshot you can return to later." / "No checkpoints yet. Create a checkpoint when you reach an important milestone."
3. **Recent saves** (`#git-saves-list`, existing): each job in student words ("Progress saved to Git · 12 minutes ago", "Saved on this VM — upload needs attention [Retry] [Keep snapshot only]", "Folder move", "Checkpoint 'OSPF done' saved"), expandable **Details** showing repository, commit, push state, devices, job id, technical message.
4. **Save location** (`#git-save-location`): "Repository <name> · Folder <path>" with [Change folder…] (opens the existing "Where this lab lives" panel `gitPlacesShow` inline, collapsed by default) and [Use a different repository…], [Connect by URL…]; the existing `git-binding-form` (devices included, review before pushing) under "Save settings"; [Disconnect] under Advanced.
5. **Advanced repository details** (`details`): push URL, branch, VM account, checkout path, repository status/problem, [Refresh status] (`#git-repository-refresh`).

**Tools tab** (`#tools-view`): a grid of `.tool-card`s: **Packet capture** ("Pick a link or interface, start a capture, Wireshark opens in your browser." [Capture traffic] = `#capture-open`), **Telemetry** ("Live interface rates and link state in Grafana." [Open network dashboard] = `a#grafana-open`; status line from `lab.telemetry.status` in words; [Telemetry settings…]; when the stack is disabled: "Telemetry is not installed on this VM." with the setup link), **Configuration backups** ("Copies of each device's running configuration kept on this VM." [Back up now] = `#backup`, schedule form `#schedule-form`, then the existing `#backups-view` job list with downloads), **Open all CLIs** (`#map-ssh-all` equivalent → the tools card uses its own button that calls the same function), **Export sessions** (`#export-sessions` "Export SuperPuTTY sessions…"), **Lab files** (browse this lab's topology files on the VM — the existing operations browser), **Diagram exports** (annotations JSON / draw.io — existing editor export actions).

**Advanced tab** (`#advanced-view`): stacked panels, each with a plain-language intro:
- **Deployment details**: `#deployment-status`, `#deployment-message`, `#deployment-checked`, `#deployment-nos`, `#vm-files-status` (all existing ids), plus `#sync-vm`… no — `#sync-vm` is in Lab actions; here: `#update-definition` "Update lab YAML…", `#link-deployment` "Link deployment…", `#import-top` "Replace inventory…", and the metrics (`#node-count`, `#enabled-count`, `#ready-count`, `#schedule-summary`) as a small key/value list.
- **Credentials** (`#credentials-view` with `#profiles`, `#add-profile`).
- **Action logs** (`#logs-view`, unchanged controls).
- **Lab operations**: [All lab operations…] (`#lab-actions`), [Operation history…], [Test NOS login] (`#test`).
- **Technical details**: lab id, source file, VM project path, container prefix, deployment name, Git binding id/revision, host identity (read-only `dl.kv`).
- **Danger zone**: `#remove-lab` "Remove this lab from the manager…" (the Lab actions menu item triggers the same button), with the persistence sentence "Removing the lab from the manager does not touch the running devices or your saved progress."

### 1.4 Device workspace (`dialog#details-dialog.drawer`)
- Head: eyebrow "Device", `h2#details-title`, line: platform · `deviceState` pill · `#details-endpoint` (address:port, shown small).
- Primary action row `#details-actions` (existing id; `nodeActions(n,true)` renders it): [Open CLI ↗] primary (`data-terminal`), [Capture traffic] (`data-capture`), [Back up configuration] (`data-backup`). `[data-check]` "Test login" and `[data-edit]` "Edit connection…" move to the Advanced section of the drawer (still rendered by `nodeActions` when `details=true`, just placed by CSS/markup into `.drawer-advanced-actions`).
- Status section: the explanation sentence from `deviceState` ("RTR3 is running, but SSH login failed with the saved credentials." + next action) and, under "Details", the raw `nos_login.message`, `at`, source.
- Configuration history (`#node-history`, existing).
- Advanced (`details`): connection settings `dl.health-grid` (inventory name, network OS, credential profile, backup selection with the enable checkbox `data-enable`, backup readiness), Test login, Edit connection.

### 1.5 Restore review (`restore.js`) — copy
Title "Replace running configuration". Body: "Source: <version label>" · "Devices: RTR1, RTR2" (checkbox list as today) · "Current configurations are backed up first." · "The routers are not rebooted; the change is confirmed automatically or rolled back after <n> minutes." Buttons: [Cancel] [Replace configurations] (danger). Progress: per-device rows "Backing up… / Applying… / Confirming… / Restored ✓ / Needs attention" with a Details expander. Result: "Configuration replaced on 2 devices." / "1 device needs attention." + Details.

### 1.6 Confirmations (rewrite the copy, keep the mechanics)
- Destroy: title "Destroy <lab>?" body "The running devices are removed from the VM. Your saved progress and Git history remain. The generated lab folder is also removed (cleanup)." then the existing details (affected containers, containerlab command) under "Technical details". Confirm: "Destroy lab".
- Redeploy: "Redeploy <lab>?" — "Devices are destroyed and started again from the topology; unsaved device changes are lost. Save progress first if you need them." Confirm "Redeploy lab". Cleanup variant adds the folder sentence.
- Stop/Restart devices: "Stop devices?" — "Devices stop but keep their startup configuration; unsaved running-config changes may be lost on some platforms."
- Remove lab: existing text is good; title "Remove <lab> from this manager?".
- Disconnect save location: "Disconnect this lab from <repository>?" — "Nothing is deleted from the repository. New saves need a save location again."
- Keep snapshot only / Start fresh / End capture: keep.

---

## 2. Status vocabulary (new file `app/static/status.js`, pure functions, harness-tested)

```js
labState(lab, ctx)     // ctx = {operations, restore_jobs, discovery}
// → {key:'running'|'starting'|'stopped'|'attention'|'working'|'unlinked'|'unknown', label, detail, ready, total, pill:'ok'|'warn'|'danger'|'neutral'|'running'}
```
| condition (in priority order) | key | label | detail |
|---|---|---|---|
| operation queued/running for this lab (deploy/redeploy/destroy/start/stop/restart/apply) | working | Starting lab / Stopping lab / Redeploying lab / Restarting devices / Applying topology | operation message |
| restore job busy for this lab | working | Replacing configuration | job message |
| deployment.status Unlinked | unlinked | Not linked | "This workspace is not linked to a running lab." |
| deployment.status Unknown | unknown | Status unknown | discovery error in plain words: "The lab VM cannot be reached." |
| Not deployed / Stopped | stopped | Stopped | "The lab is not running." |
| Partially running | attention | Some devices stopped | "n of m devices are running." |
| Running and nos_readiness.status booting | starting | Starting | "n of m devices ready. SSH becomes available automatically." |
| Running and nos_readiness.status failed | attention | Needs attention | "SSH login failed on k device(s)." |
| Running (ready or idle) | running | Running | "n of m devices ready" (idle: "Devices are running.") |

```js
deviceState(node) // → {key:'ready'|'starting'|'unavailable'|'attention'|'credentials'|'unknown', label, detail, next, cli:boolean, pill}
```
| nos_login.status / fields | key | label | detail (student sentence) | next |
|---|---|---|---|---|
| ssh_ready true | ready | Ready | "Accepting SSH logins." | — |
| booting | starting | Starting | "<Name> is still starting. SSH opens automatically when it answers." | — |
| failed | attention | Needs attention | "<Name> is running, but SSH login failed with the saved credentials." | "Check credentials" (Advanced → Credentials / Edit connection) |
| unavailable / available false | unavailable | Unavailable | "<Name> is not running or the VM status is stale." | "Start lab" |
| needs_credentials | credentials | Needs credentials | "Add login credentials to open the CLI." | "Add credentials" |
| unmonitored (unlinked) with ssh_ready | ready | Ready | "Manual connection." | — |
| anything else | unknown | Unknown | "" | — |

```js
progressState(lab, gitJobs) // → {key:'unconnected'|'none'|'saving'|'git'|'local'|'review'|'attention'|'failed'|'interrupted', label, detail, at, pill}
```
| condition | label | detail |
|---|---|---|
| no git_binding | Not connected | "Choose where this lab's progress is saved." |
| busy (queued/capturing/exporting/pushing) | Saving progress… | phase in words: "Reading device configurations…", "Saving to the repository…", "Uploading to GitHub…" |
| last job synced | Saved to Git | "<relative time>" |
| committed | Saved on this VM | "Not uploaded — upload when you are ready." |
| review_pending | Saved on this VM | "Review the changes before uploading." |
| push_pending / export_pending | Needs attention | "Saved on this VM, but it could not be uploaded to GitHub." / "Configurations were read but could not be saved to the repository." |
| failed / capture_incomplete | Save failed | "The last save did not complete." |
| interrupted | Save interrupted | "The manager restarted during the last save. Retry it." |
| no job yet | Not saved yet | "Save progress creates a snapshot you can return to later." |
"Last job" = the newest git job for the lab whose status is not `dismissed` and whose target is not `update`.

Helpers: `relativeTime(iso, now=Date.now())` ("just now", "3 minutes ago", "2 hours ago", "yesterday", "3 days ago", else date), `operationLabel(action)`, `plural(n, word)`. `utcDisplay()` stays for technical details.

Vocabulary rules: Lab = Stopped / Starting / Running / Needs attention; Device = Starting / Ready / Unavailable / Needs attention / Needs credentials; Progress = Not saved yet / Saving progress… / Saved to Git / Saved on this VM / Needs attention. Never "Online", "Active", "Started", "reachable", "synced", "Worker idle" in student-facing text.

---

## 3. Visual system (rewrite `style.css`; keep `terminal.css` separate but re-tokenised)

**Tokens (`:root`)**: `--bg:#f4f6f8; --surface:#fff; --surface-2:#eef2f5; --line:#d9e1e7; --line-strong:#b9c6cf; --ink:#172430; --text:#24313c; --muted:#5b6b76; --accent:#1d6f8e; --accent-strong:#175d77; --accent-soft:#e2f0f5; --ok:#1f7a4d; --ok-soft:#e4f4ea; --warn:#a85f00; --warn-soft:#fff2dc; --danger:#b3261e; --danger-strong:#8f1d17; --danger-soft:#fbe9e7; --neutral:#5b6b76; --neutral-soft:#eceff2; --rail:#172431 (dark surfaces: toast, terminal chrome, code output); --focus:#1d6f8e; --radius:6px; --radius-lg:10px; --shadow:0 8px 24px rgba(23,36,48,.10); --shadow-menu:0 10px 30px rgba(23,36,48,.16); --font:system-ui,"Segoe UI",Roboto,Arial,sans-serif; --mono:ui-monospace,Consolas,"Liberation Mono",monospace; --space-1:4px … --space-6:32px`.
Primary actions are **teal-blue**, never red. Red is reserved for danger/failed. Green = ready/success, amber = starting/attention-soft, grey = inactive.

**Type**: base 14px/1.5; `h1` 24px/650; `h2` 18px/650; `h3` 15px/650; `.caption` 12px muted; minimum size 11px; uppercase only for `.eyebrow` (11px, .08em) used sparingly (drawer head, dialog head).

**Layout**: `body` grid: top bar (52px) + content. Content max-width 1480px, side padding 24px (16px ≤ 900px). Lab page grid: header, banner, tabs, panel. Topology stage height `min(calc(100vh - 230px), 820px)`, min 460px; at 1366×768 the map must be visible without scrolling (header+tabs ≤ 200px).

**Components** (class names are the contract):
- Buttons: `.button` base (min-height 36px, 13px/600, radius 6, border 1px) + `.primary` (accent bg, white text), `.secondary` (surface bg, line-strong border), `.ghost` (no border), `.danger` (danger bg), `.danger-outline` (danger text/border), `.small` (30px). Keep `.link-button`, `.text-button`, `.icon-button`. Menu item buttons `.menu-list button` (full width, left aligned, 13px, hover `--surface-2`).
- Status pill: `.pill` + `.ok|.warn|.danger|.neutral|.running` — 12px/600, dot before text (running: animated pulse, honours reduced-motion). The old `.badge good|bad|warn|running|platform` classes remain styled (aliases to the same look) because existing markup still emits them.
- Cards: `.card` (surface, line border, radius-lg, padding 20px), `.card-title`, `.lab-card`, `.tool-card`, `.device-row`.
- Menus: `details.menu > summary` (styled as a button; `list-style:none`), `.menu-list` (absolute, right-aligned, min-width 240px, shadow-menu, z-index 20), `.menu-sep`, `.menu-danger button` (danger text). Close on Escape / outside click via a small shared helper in `app.js` (`closeMenus(except)`); `.git-save-menu` and `.extra-views` adopt the same pattern.
- Banner: `.banner` + `.info|.warn|.danger|.ok`, left border 4px, `.banner-actions`.
- Empty state: `.empty-state` (centred, h2 + p + actions).
- Tabs: `.tabs button` (13px/600, muted; `.active` accent underline 2px, ink text), `aria-selected`.
- Drawer: `dialog.drawer` (right side, width min(560px, 100vw), full height, `.drawer-head` light surface not dark, sticky), `.drawer-section`.
- Dialog: `dialog` (radius-lg, width min(680px, calc(100vw - 32px)), max-height 90dvh with scrolling body), `.dialog-head`, `.dialog-actions` (right aligned; danger button rightmost).
- Key/value: `dl.kv` (also keep `.health-grid`).
- Table: `.table-wrap table` (13px, `th` 12px/600 muted, row hover `--surface-2`).
- Toast: `#toast` (dark rail bg, bottom-right, role status).
- Skeleton: `.skeleton` shimmer blocks for the home cards while `state.labs` is empty and the first `/state` has not returned (`state.loaded` flag).
- Map: `.topology-stage`, `#topology-map` (surface bg, subtle dot grid), `.map-device.state-ready .device-state-dot{fill:var(--ok)}` etc., `.map-tools` overlay (top-right, small buttons), `.map-expanded` retained.
- Keep and restyle every family that existing JS emits: `.op-*`, `.git-*`, `.restore-*`, `.diagram-*`, `.capture-*`, `.job*`, `.device-download`, `.archive-download`, `.profile-card`, `.blank-state`, `.table-empty`, `.node-context-menu`, `.workspace-choice*`, `.debug-*`, `.vm-guide`, `.capture-viewer*`, `.empty-panel` etc. — consult `inventory/css.md` §4–§16 for the full list; every selector there must still have a sensible rule (re-tokenised) unless it is documented dead CSS (`.dark`, `.full`, `.guide-row`, `#login-dialog`).
- Focus: `:focus-visible{outline:3px solid var(--focus);outline-offset:2px}`; `@media (prefers-reduced-motion:reduce)`.
- Breakpoints: 1280 (device rail collapses), 1100 (tool grid 2→1 columns, lab grid 3→2), 900 (side padding 16px, tabs scroll horizontally, header actions wrap), 760 (dialogs full-width, drawer full-width, lab grid 1 column).

---

## 4. Files, ownership and migration order

| File | Change |
|---|---|
| `app/static/index.html` | New shell: top bar, `#home`, lab header, banner, tabs and five panels wrapping the legacy sections; all dialogs retained verbatim except relabelled copy; new script tags `status.js?v=…`, `home.js?v=…` (before `management.js`). |
| `app/static/style.css` | Full rewrite per §3 (single file, readable multi-line, sectioned). |
| `app/static/status.js` | New: vocabulary functions (§2). |
| `app/static/home.js` | New: `renderHome()` (continue card, lab cards, discovered section), `goHome()`, localStorage helpers `rememberOpened(id)`. |
| `app/static/app.js` | Navigation: `refresh()` no longer auto-selects; hash routing `#lab=<id>&view=<tab>&device=<name>` (read on load and `hashchange`; write on `selectLab/showTab/openDetails`); `render()` renders header pieces via `status.js`; `showTab` legacy mapping; `renderDeviceList()` new; `renderNodes()` unchanged behaviour; `nodeActions()` relabelled ("Open CLI", "Capture traffic", "Back up configuration"; drawer extras "Test login", "Edit connection…"); `renderDetails()` per §1.4; `closeMenus()` helper; banner renderer `renderLabBanner()`. |
| `app/static/management.js` | Same functions; render targets are the Home page; copy updated (VM connection dialog wording stays technical because it is an admin task, but title/help sentences get the plain-language first line). |
| `app/static/operations.js` | `renderLabOperations()` also feeds the header/banner; Lab actions menu wiring; confirmation copy (§1.6); dialog copy; "View running lab details" → "Running labs on the VM". |
| `app/static/git-progress.js` | `gitShowRepository()` composes the Progress tab (§1.3); status strings via `progressState`; save-menu labels; history dialog title "Saved versions & history"; job rows in student words with Details. |
| `app/static/git-places.js` | Copy only ("Where this lab lives" → "Folders in this repository"; "Save this lab here" stays — user-approved wording). |
| `app/static/restore.js` | Copy per §1.5. |
| `app/static/topology.js`, `topology-render.js` | State classes + dot; left-click opens device; context-menu labels; map tools relocation. |
| `app/static/capture.js` | Copy: "Capture traffic", step hints. |
| Tests | Update markup regexes that broke while keeping each behavioural claim; add `tests/test_status_ui.js`, `tests/test_home_ui.js`, `tests/test_shell_ui.js` (navigation, showTab mapping, banner, device list gating, escaping); add the new files to the CI node test list. |
| Docs | `docs/TOUR.md`, `docs/LAB-OPERATIONS.md`, `docs/GIT-PROGRESS.md`, `docs/GIT-SETUP.md`, `docs/TELEMETRY.md`, `docs/CAPTURE.md`, `docs/NAMING.md`, `docs/WIKI-MASTER-GUIDE.md` (Parts 12–14, 17, 21), `README.md`, `clab-backup-ui/NODE-FEATURES.md`, `docs/ARCHITECTURE.md` module map, `agent instructions.md` (new top section), `docs/CHANGELOG.md`, `clab-backup-ui/VALIDATION.md`. |

**Order** (each step ends with `node --test tests/*.js`, `node --check`, and a Playwright screenshot pass on the rebuilt container):
1. `status.js` + tests (pure).
2. `style.css` rewrite + `index.html` shell + `app.js` navigation/home/header (with `home.js`) + `management.js` targets. Old tabs still reachable (Devices technical view, Progress = old Git tab content, Tools/Advanced hold the old sections). **App fully functional at this point.**
3. Topology/devices/device workspace.
4. Progress tab composition (git-progress.js) + restore copy.
5. Tools + Advanced + Lab actions menu + confirmations + microcopy sweep (operations.js, management.js, capture.js, git-places.js).
6. Tests, docs, release 1.29.0, live validation, report.

---

## 5. Student journeys — acceptance checks

1. **Resume**: open `/` → Home shows "Continue clabllm-dev" → Open lab → Topology with 2/2 ready → click PTX1 → drawer → [Open CLI] → terminal page connects. No other steps.
2. **Launch**: Home → a stopped lab card → [Start lab] → the existing deploy review → confirm → header shows "Starting lab…" then "Starting — 1 of 2 devices ready" then "Running — 2 of 2 devices ready" (live, 4 s poll), map dots turn green.
3. **Save**: header [Save progress] → "Saving progress…" → "Saved to Git just now" (or "Saved on this VM — upload needs attention" with Retry).
4. **Checkpoint**: Progress → [Create checkpoint…] → name → appears under Checkpoints.
5. **Final state**: Progress → Saved versions → `reference/solution` → [View] / [Compare with current] / [Apply to running lab…] → review → restore runs → result sentence.
6. **Troubleshoot**: a device with failed login shows "Needs attention" on the map, list and drawer with the sentence and a "Check credentials" action; raw message under Details.
7. **Capture**: Tools → [Capture traffic] → pick interface → start → Wireshark opens.
