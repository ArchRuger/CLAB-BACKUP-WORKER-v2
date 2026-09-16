# UI inventory: management.js + vm-connection.html

Scope: landing page, discovery sidebar, VM connection dialog, deploy-new-lab entry point, import previews, manager settings ("Start fresh"), manual discovery (setup dialog), excluded labs, discovery file details, helper-update prompts, deployment bar (status / sync / link / remove), and the two topology-view bulk actions that management.js binds.

Files read completely:

- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/management.js` (232 lines)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/vm-connection.html` (196 lines)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/index.html` (100 lines, skimmed for ids)
- Cross-checked (partial reads): `app.js` (helpers, `render()`, polling), `operations.js` (`opDialog`, `opTask`, `opNewTab`, `openDeploy`/`opBrowse`, line 280-281 bindings), `style.css` (rules for the elements below), `main.py` and `discovery.py` (route existence and error strings surfaced in these dialogs).

Script load order in index.html (all `defer`, so later files override `onclick` set by earlier ones): app.js → topology-render.js → topology.js → **management.js** → operations.js → diagram-editor.js → git-progress.js → git-places.js → restore.js → capture.js.

Consequences of load order that a redesign must preserve:

- app.js line 101 binds `new-lab`, `import-empty` → `openImport()` and `import-top` → `openImport(!!current())`. management.js lines 107 and 111 **override** these: `new-lab`/`import-empty` → `openSetup()` (lab-definition dialog), `import-top` → `current() ? openImport(true) : openDeploy()`.
- operations.js line 280 binds `deploy-empty` → `openDeploy` (management.js only sets its `disabled`/`title`).
- operations.js line 281 binds `vm-projects` (→ `location.assign('/static/workspace.html#mode=folder')`), `lab-start`, `lab-destroy`, `operations-history`, `inspect-all`. Those are outside this file's scope but live in the same sidebar/deployment bar.

## 1. Globals

### Defined in management.js

| Name | Kind | Purpose | Called from other files |
|---|---|---|---|
| `vmSyncBusy` | `let` boolean | Guards the Sync from VM button while a sync is in flight | no |
| `renderManagement()` | function | Renders sidebar VM summary, discovered/excluded lists, discovery file details, landing page, deployment bar, NOS readiness | **yes** – `app.js` `render()` line 51 calls it on every refresh (guarded by `typeof renderManagement==='function'`) |
| `renderNosReadiness(lab)` | function | Writes the `deployment-nos` line and its status class | no |
| `renderLanding(discovery,lab)` | function | Landing (empty) panel: connect button, deploy button gating, note, "Already running on the VM" list | no |
| `openSetup(replace=false, deployedName='')` | function | Opens `setup-dialog` (lab definition import / update) | no |
| `openVmDialog()` | function | Opens `vm-dialog` prefilled from `state.discovery.host` | no |
| `vmPromptShown` | `let` boolean | One-shot guard for the automatic VM-connection prompt | no |
| `maybePromptVmConnection()` | function | Auto-opens the VM dialog once per page load when discovery is not configured | no |
| `autoImportBusy` | `let` boolean | Guards `importDiscovered` re-entry | no |
| `importPreview` | `let` object/null | Holds the last `/discovery/import-preview` result (name + token) for confirmation | no |
| `importDiscovered(name)` | async function | Preview-then-confirm flow for importing a discovered lab | no |
| `openExclusionMenu(name)` | function | Opens the "Excluded lab" dialog with Clear exclusion | no |

Dialog markup injected at load by `document.body.insertAdjacentHTML('beforeend', …)`: `auto-import-dialog`, `remove-lab-dialog`, `setup-dialog`, `vm-dialog`, `binding-dialog`. Dialogs created lazily via `opDialog(id,…)` (operations.js): `manager-settings-dialog`, `exclusion-menu`, `backup-all-review`.

### Consumed from other files

From `app.js`: `$` (getElementById), `esc` (HTML escaper), `state`, `activeId`, `tab`, `current()`, `busy()`, `api()`, `json()`, `refresh()`, `notify()`, `withForm()`, `openImport()`.
From `operations.js`: `opDialog()`, `opTask()`, `opNewTab()`, `openDeploy()`, `opCaps` (reset to null on manager reset).

Helper semantics that matter for behaviour:

- `withForm(form, fn)`: disables the form's `button[type=submit]`, clears `.form-error`, runs `fn`, on error writes `e.message` into `.form-error` (or toasts if none), re-enables the button.
- `opDialog(id,title,body)`: creates/reuses `<dialog class="operations-dialog">`, renders eyebrow **"NODE MANAGER"**, a `×` close button (`data-op-close`), `<h2>title</h2>`, the body, and a trailing `.form-error`; calls `showModal()`.
- `opTask(dialog, fn)`: clears the dialog's `.form-error`, disables every enabled button in the dialog while `fn` runs, writes `e.message` to `.form-error` (or toasts when `dialog` is null), re-enables.
- `notify(msg)`: writes `#toast`, auto-hides after 5000 ms.
- `api()` throws `Error(detail)` for non-2xx; if `detail` is not a string the message is `'Check the form fields and try again.'`; unparsable body → `'Request failed'`.
- `refresh()`: `GET /api/state`, falls back to first lab when `activeId` is stale, calls `render()`.

## 2. Timers, polling, storage

- `app.js` line 180: `setInterval(()=>refresh(), 4000)` → `render()` → `renderManagement()` every **4 s**. All sidebar status text, discovered/excluded lists, landing note, deployment bar and NOS readiness are therefore re-rendered every 4 s from `state`.
- Toast auto-hide: 5000 ms (`notify`).
- Text shown to the user claims the backend inspects the VM "every 30 seconds" / "checks every 30s" (backend discovery interval, not a browser timer).
- `sessionStorage['activeLab']`: **set** after a successful setup-dialog save (`/lab-definitions`) and after a confirmed auto-import (`/discovery/import`); **removed** when the active lab is removed (`remove-lab-form`) and on manager reset.
- Module state (not persisted): `vmPromptShown`, `vmSyncBusy`, `autoImportBusy`, `importPreview`.
- No `localStorage` use in these files.

## 3. Capabilities (every control and every rendered string)

### 3.1 Sidebar (index.html `<aside class="sidebar">`)

**S1 – VM status line** `#vm-summary` (`<p class="side-hint" role="status">`), rendered by `renderManagement` every refresh. Exact text by condition (checked in this order):

1. `!discovery.configured` → `VM discovery is not configured.`
2. `!discovery.host.enabled` → `VM discovery is paused.`
3. `discovery.helper_update_required` → `VM connected · helper update required. On the VM, run sudo bash deploy/start-manager.sh from the current source.`
4. `discovery.connected` → `VM connected · checks every 30s`
5. else → `discovery.error` or `VM status unknown; refresh discovery.`

CSS: `#vm-summary{overflow-wrap:anywhere}`.

**S2 – Discovered labs list** `#discovered-labs`. One `<button class="side-button" data-setup-name="…">` per `discovery.discovered[]` entry with `!imported && !excluded`. Content: lab name, then `<small>`: `{Discovered|Last seen} · {running}/{nodes} running · {detail}` where the first word is `Discovered` when `discovery.connected` else `Last seen`, and `detail` = `discovery.file_errors[name]` if present, else `Ready to import · confirmation required` when `discovery.pending_imports[name]` is truthy, else `Try importing VM files`. Click (delegated on the container) → `importDiscovered(name)`.

**S3 – Excluded labs list** `#excluded-labs`. Only when `discovery.ignored_labs` is non-empty: hint `<p class="side-hint">Excluded from automatic import</p>` then one `<button class="side-button" data-allow-import="…">` per name with `<small>Import again · Right-click to clear exclusion</small>`.
- Click → `importDiscovered(name)` (re-import flow; the preview will show the "also removes the lab from your excluded list" note).
- **Right-click** (`contextmenu`, `preventDefault`) → `openExclusionMenu(name)`.
- **Keyboard**: `ContextMenu` key or `Shift+F10` on the button → `openExclusionMenu(name)`.

**S4 – Discovery file details** `<details id="discovery-files"><summary>Discovery file details</summary><div id="discovery-file-list">`. Rendered from `discovery.file_reports` (`{labName: {kind: {message, paths[]}}}`): per lab `<p><strong>{lab}</strong></p>`, then per kind `<p>{kind}: {message}<small>{paths joined by <br>}</small></p>`. When empty: `No file results yet. Refresh discovery. If using an older helper, update it on the VM.` CSS: `#discovery-files{font-size:12px;…}`, `summary{cursor:pointer}`, list `p{overflow-wrap:anywhere}`, `small{display:block;font-size:10px;opacity:.8}`.

**S5 – "VM connection" button** `#vm-settings` (`side-button`) → `openVmDialog()`.

**S6 – "Refresh discovery" button** `#vm-refresh` (`side-button`). On click: button disabled, text → `Checking VM…`; `POST /api/discovery/refresh {}`; `refresh()`; toast = `result.error` or (`!result.configured` → `Configure the VM connection first.`; `result.connected` → `Discovery updated.`; else `Discovery is paused or still checking.`); on exception toast `e.message`; finally re-enabled, text → `Refresh discovery`.

**S7 – "Manual discovery" button** `#new-lab` (`side-button`) → `openSetup()` (opens the "Import a lab" lab-definition dialog; the label does not match the dialog's purpose). Overrides the app.js binding to `openImport()`.

**S8 – "Manager settings" text button** `#manager-settings` (in `.side-bottom`, next to the `Debug panel` link to `/static/debug.html`) → opens `manager-settings-dialog` (see D6).

**S9 – Automatic VM-connection prompt** (no visible control). `maybePromptVmConnection()` runs inside every `renderManagement`. Once per page load (`vmPromptShown`), when `state.discovery` exists and `discovery.configured` is false, and `vm-dialog` is not already open and **no other `dialog[open]` exists**, it calls `openVmDialog()`. A dismissed dialog is never reopened automatically in the same page load.

Also in the sidebar but bound elsewhere (listed for completeness of the sidebar, do not drop): `#vm-projects` "Deploy New Lab" (`side-primary`, operations.js → `/static/workspace.html#mode=folder`), `#inspect-all` "View running lab details", `#operations-history` "Operation history", `#operation-summary` status, brand block, `#supported-release` caption (app.js sets `Supported device types as of release {version}`), `Junos / IOS-XR / EOS` mono line.

### 3.2 Landing page (`<section id="empty" class="empty-panel">`, shown when no lab is selected)

Static copy: file-icon `LAB`; `<h2>Deploy a lab on your VM</h2>`; `Browse the topology files on your VM, pick one and deploy it. The workspace, map and node logins are ready the moment the devices finish booting. Nothing to import by hand.`; platform pills `Junos`, `IOS-XR`, `Arista EOS`; note `Have lab files instead? [Import a lab definition] · [Import an Ansible inventory]`.
Page heading (set by app.js `render`): title `Your next lab starts here.`, breadcrumb `Overview`, subtitle `Deploy a topology from your VM, or pick up a lab that is already running.` (the index.html initial subtitle `Import your nodes. Connect, experiment, and keep your configurations close.` is overwritten on first render), footer `No lab selected`.

`renderLanding(discovery, lab)` returns early when a lab is selected or `#deploy-empty` is missing.

**L1 – "Deploy a new lab"** `#deploy-empty` (`button primary`). `disabled = !discovery.connected`; `title` = `Connect the VM to browse its topologies` when disabled, else empty. Click (operations.js) → `openDeploy()` = `opTask(null, opBrowse())` → `POST /api/operations/browse {path:''}` and opens the `op-browser` dialog **"Lab Topologies"** with: current path line (`Lab topology folders` at the root), buttons `Lab folders`, `Parent folder`, `New topology`, `Clone repository`, `Popular labs`, a lazy-loading folder tree (`◇ file` buttons open `opEdit(path)`), help `Expand a folder and select a .clab.yaml or .clab.yml topology to view or deploy. Other files are hidden. Each folder shows at most 500 matching entries.` `Clone repository`/`Popular labs` start disabled and are enabled after `GET /api/operations/capabilities` when `caps.network` (help text appended: ` Online downloads are disabled. Enable --allow-downloads in VM setup for cloning and the catalog.` or ` Files are available, but command checks failed. Open the Debug panel to check VM helpers. Online actions remain disabled.`). Full browser behaviour belongs to the operations.js inventory.

**L2 – "Connect the VM"** `#vm-connect-empty` (`button secondary`). `hidden = discovery.configured`. Click → `openVmDialog()`.

**L3 – Landing VM note** `#empty-vm-note` (`role=status`, amber, hidden via `:empty`):
- `!configured` → `Connect this manager to your containerlab VM first. Deployment, discovery and node logins all run over that connection.`
- configured but `!connected` → `discovery.error` or `Waiting for the VM connection. Deployment opens as soon as discovery answers.`
- connected → empty.

**L4 – "Already running on the VM"** `#empty-discovered` (`<h3>` + `#empty-discovered-list`). `hidden` when no `discovery.discovered[]` entry has `!imported` (note: **excluded labs are included here**, unlike the sidebar list). Each row `.empty-lab`: `<strong>{name}</strong><small>{running}/{nodes} containers running{ · removed from this manager earlier when excluded}</small>` and a `button secondary` **Import** (`data-setup-name`) → `importDiscovered(name)`.

**L5 – "Import a lab definition"** `#import-empty` (`link-button`) → `openSetup()`.

**L6 – "Import an Ansible inventory"** `#import-inventory-empty` (`link-button`) → `openImport()` (app.js `import-dialog` "INVENTORY UPLOAD / Import a lab").

**L7 – Page-heading button** `#import-top` (`button primary`, above the panel). Text by app.js: `Deploy a new lab` when no lab selected, `↑ Replace inventory` when a lab is selected. Click (management.js) → `current() ? openImport(true) : openDeploy()`. Note: this button is **not** gated on `discovery.connected` (unlike L1); with no VM the browse call fails and the error is toasted by `opTask(null,…)`.

### 3.3 Deployment bar (`<section class="deployment-bar">`, shown when a lab is selected)

**B1 – Deployment status** `#deployment-status` (strong): `lab.deployment?.status` or `Unlinked`.

**B2 – Deployment message** `#deployment-message`: `lab.deployment?.message` or `Link this workspace to a deployed lab.`

**B3 – Last inspection** `#deployment-checked` (small): `Last successful inspection: {toLocaleString(lab.deployment.last_success)}` or empty.

**B4 – NOS readiness** `#deployment-nos` (`role=status`, class `deployment-nos {status}`; colours ready=green `#256447`, booting=amber `#805510`, failed=red `#a13135`; hidden via `:empty`). From `lab.nos_readiness` (default `{status:'idle'}`):
- `ready` → `NOS ready · {ready}/{total} nodes accept SSH login`
- `booting` → `NOS booting · {ready}/{total} nodes accept SSH login so far. SSH and the login test open automatically when they answer.`
- `failed` → `NOS login failed on {failed} of {total} nodes · assign credentials, then Test login`
- anything else → empty.

**B5 – VM files status** `#vm-files-status` (`role=status`):
- no `lab.deployment_name` → empty
- `!discovery.connected` → `VM file sync is unavailable until discovery reconnects.`
- `!discovery.file_import_supported` → `Update the installed VM helper to enable file transfer, or use direct inspection + SFTP. Manual uploads remain available.`
- `lab.vm_source` present → `VM files: {source.status}` + ` · Last synced {toLocaleString(source.synced_at)}` (if any) + ` · {source.message}` (if any)
- else → `discovery.file_errors[lab.deployment_name]` or `No deployed source files found. Saved workspace retained.`

**B6 – "Sync from VM"** `#sync-vm` (`button secondary`). `hidden = !lab.deployment_name`. `disabled = vmSyncBusy || !discovery.connected || !lab.vm_source?.can_sync` (no title/explanation; B5 is the only hint). Click: guard `!lab || vmSyncBusy`; set busy; text → `Syncing…`; `POST /api/labs/{id}/sync {}`; `refresh()`; toast `VM files synced. Saved connections, credentials and backup history retained.`; on error toast `error.message`; finally busy=false, text → `Sync from VM`, `renderManagement()`. Backend errors: `Fresh VM files are unavailable. Refresh discovery, upgrade the helper, or import manually.`, `VM files are invalid or inconsistent; the saved workspace was retained.`, `Lab not found`.

**B7 – "Update lab YAML"** `#update-definition` (`button secondary`) → `openSetup(true)`: dialog title `Update lab definition`, hidden `lab_id` = current lab id, deployed name prefilled with `lab.deployment_name`, auto-import button hidden.

**B8 – "Link deployment"** `#link-deployment` (`button secondary`) → clears binding form error; `#binding-name` = `lab.deployment_name || lab.name`; `#binding-prefix` = `lab.container_prefix ?? 'clab'`; datalist `#deployment-names` = every `discovery.discovered[].name`; opens `binding-dialog` (D5).

**B9 – "Remove lab"** `#remove-lab` (`button secondary`). `disabled` when any `state.jobs` entry for this lab is `queued`/`running` (no explanation text). Click → resets `remove-lab-form`, fills hidden `#remove-lab-id`, hidden `#remove-lab-confirm-name` = `lab.name`, visible `#remove-lab-name` = `lab.name`, opens `remove-lab-dialog` (D2).

Also in this bar but bound in operations.js: `#lab-start` "Start lab" (initially disabled), `#lab-destroy` "Destroy lab" (initially disabled).

### 3.4 Topology-view bulk actions bound by management.js

**T1 – "SSH all nodes ↗"** `#map-ssh-all`. Gating (app.js `render`): `disabled` when no node has `ssh_ready`; `title` = `Waiting for the NOS to accept SSH logins; this opens automatically` if any node `nos_login.status==='booting'`, else `No node is ready for SSH`. Click (management.js) → `opNewTab({mode:'ssh', lab:lab.id})` → `window.open('/static/workspace.html#mode=ssh&lab={id}','_blank')`; if the popup is blocked, `opDialog('op-open-tab','Open workspace', 'Your browser may have blocked the new tab.' + link 'Open workspace ↗')`.

**T2 – "Back up all configs"** `#map-backup-all`. Gating (app.js): `disabled = busy() || no node with readiness==='Ready'`. Click (management.js) → `opDialog('backup-all-review','Back up all configurations', …)`:
- `{ready} of {total} nodes are ready for a configuration backup. This includes ready nodes that are unchecked in the inventory.`
- if any skipped: `These nodes will be skipped:` + `<ul>` of `{short_name||name} · {readiness}`
- button `Back up {ready} nodes` (`#backup-all-confirm`), disabled when `ready.length===0 || busy()`.
- Confirm → `POST /api/labs/{id}/jobs {operation:'backup', node_names:[ready names]}`; close; `refresh()`; toast `Configuration backup started. View progress in Backup history.`

### 3.5 Dialogs

All five injected dialogs share: `.dialog-head` with an uppercase eyebrow and an `×` `icon-button[data-dismiss][aria-label=Close]`; a `.form-error[role=alert]` (hidden via `:empty`); `.dialog-actions` with `Cancel` (`data-dismiss`) and a primary submit. Every `[data-dismiss]` button closes its closest `<dialog>` (management.js line 59). Submit handling goes through `withForm`.

**D1 – `auto-import-dialog` / form `auto-import-form`** — eyebrow `IMPORT FROM VM`, h2 `Import this discovered lab?`.
- `#auto-import-summary`: `{preview.name} · {preview.nodes} nodes · {preview.links} links`
- static: `The manager will save the lab definition, available layout and inventory credentials in persistent storage. The backup schedule starts as Manual.`
- `#auto-import-files`: per `preview.files` entry `<p><strong>{kind}</strong><br><small>{file.path}</small></p>`
- `#auto-import-warnings` (`form-help`): `preview.warnings[]` joined with spaces plus `Unavailable optional files: {missing.join(', ')}` when `preview.missing` is non-empty
- `#auto-import-excluded` (hidden unless `preview.excluded`): `This also removes the lab from your excluded list. Previous workspace settings and backup history are not restored.`
- buttons: `Cancel`, `Import lab` (submit).
- Submit: if `importPreview` is null → form error `Preview the lab again before importing.`; else `POST /api/discovery/import {name, token}` → `activeId = lab.id`, `sessionStorage.activeLab`, `tab='inventory'`, close, `refresh()`, toast `Lab imported from VM files and saved.`
- `close` event clears `importPreview` (so Cancel/× forces a new preview).
- Backend errors surfaced in the form: `Import confirmation expired. Preview the lab again.`, `The VM, lab files or import setting changed. Preview the lab again before confirming.`, `Could not save the imported lab. Your confirmation can be retried.`

Entry flow `importDiscovered(name)` (used by S2, S3, L4, D3's auto-import button):
1. no-op if `autoImportBusy`; sets busy; disables `#setup-auto-import`.
2. toast `Reading deployed lab files from the VM…`
3. `POST /api/discovery/import-preview {name}`; closes `setup-dialog` if open; fills D1; `showModal()`; toast `Review the lab files and confirm to save this workspace.`
4. On error: if `setup-dialog` is not open → `openSetup(false, name)`; setup form error `Automatic import: {error.message} You can retry or upload the files below.`; toast `Automatic import needs attention. Check the file details or upload manually.`; `refresh()`.
5. finally busy=false, `#setup-auto-import` re-enabled.
Backend preview errors: `A fresh VM connection is required. Refresh discovery and try again.`, `This deployment already has a saved workspace. Open it or use Sync from VM.`, `A saved workspace has this name. Link its deployment and use Sync from VM.`, `Import again now requires a preview and confirmation. Refresh the browser and choose Import again.`

**D2 – `remove-lab-dialog` / form `remove-lab-form`** — eyebrow `REMOVE SAVED WORKSPACE`, h2 `Remove lab from this manager?`, `#remove-lab-name` shows the lab name.
- copy: `This removes the imported nodes, map, saved credentials, schedule and backup history entries. Saved backup files and audit logs remain on disk.` / `Your running containers and lab files on the VM are unaffected. The VM connection and other saved labs remain available.`
- checkbox `#remove-lab-exclude` **Keep this lab excluded from automatic import** (default checked; form reset restores checked).
- help: `Uncheck to test discovery: the deployed lab can return as Ready to import on the next check, and still requires confirmation. Otherwise, use Import again in the sidebar when ready.`
- buttons `Cancel`, `Remove saved lab` (submit).
- Submit: `DELETE /api/labs/{encodeURIComponent(id)}` with JSON body `{name: hidden confirm name, prevent_reimport: checkbox}`; close; if the removed lab was active → `activeId=''`, `sessionStorage.removeItem('activeLab')`, `tab='inventory'`, closes `details-dialog` if open; `refresh()`; toast `Saved lab removed. Use Import again to rediscover it.` (excluded) or `Saved lab removed. Discovery can offer it for import again; confirmation is required.`
- The name confirmation is a hidden field auto-filled from `lab.name` (no typing required). Backend errors: `The lab name changed. Reopen Remove lab and try again.`, `Wait for this lab backup or login job to finish before removing it.`, plus Git pending-save guard.

**D3 – `setup-dialog` / form `setup-form`** — eyebrow `PERSISTENT LAB WORKSPACE`, h2 `#setup-title` = `Import a lab` (new) or `Update lab definition` (replace).
- intro: `For a detected lab, try automatic import from the VM first. Use the file fields for manual import. The workspace remains saved when the lab is stopped or removed.`
- `#setup-auto-import` **Try automatic import from VM** (`button secondary`): `hidden = replace || !deployedName || !state.discovery.configured`; disabled while `importDiscovered` runs; click → `importDiscovered($('setup-deployed-name').value)`.
- hidden `lab_id` `#setup-lab-id` (current lab id when replacing).
- `Lab definition (.clab.yaml)` `<input name=definition type=file accept=.yaml,.yml required>`.
- `Deployed lab name` (optional) `#setup-deployed-name`, maxlength 120, placeholder `Use the name in the YAML`; prefilled with `lab.deployment_name` (replace) or the passed name or the first discovered lab that is `!imported && !excluded`. Help: `Use an override if you deploy with a different lab name. Existing saved labs with this deployment name are updated in place.`
- `Topology annotations` (optional) `<input name=annotations type=file accept=.json>`. Help: `Without annotations, a simple map is generated. Importing does not deploy containers. Use VM connection to discover node addresses, then add NOS credentials.`
- `#legacy-import` **Import an Ansible inventory instead** (`button secondary`) → closes setup dialog, `openImport(!!lab_id)`.
- buttons `Cancel`, `Save lab` (submit).
- Submit: `POST /api/lab-definitions` multipart `FormData(form)` → `activeId=result.id`, `sessionStorage.activeLab`, `tab='inventory'`, close, form reset, `refresh()`, toast `Lab saved. Discovery updates automatic addresses when the lab is running.`
- Opening always resets the form and clears the error.

**D4 – `vm-dialog` / form `vm-form`** — eyebrow `VM DISCOVERY`, h2 `VM connection`.
- link `VM setup and troubleshooting guide ↗` → `/vm-connection-guide` (new tab, `rel=noopener`).
- intro: `This standalone manager inspects deployed labs over SSH every 30 seconds. Device SSH credentials are configured separately.`
- `VM address` `#vm-address` required, placeholder `127.0.0.1`; prefilled `host.address || '127.0.0.1'`.
- `SSH port` `#vm-port` number 1–65535, default 22; prefilled `host.port || 22`.
- `VM username` `#vm-user` required, maxlength 128, `autocomplete=off`; prefilled `host.username || 'clab-discovery'`.
- `VM password` `#vm-password` type password, maxlength 4096, `autocomplete=current-password`; `required = !host.auth || host.auth !== 'password'` (i.e. optional only when a password is already saved). Help: `Create the clab-discovery password in the VM terminal during setup, then enter it here. Leave blank to retain a saved password for the same account. It is encrypted in the VM's persistent manager storage.`
- `#vm-password-migration` (hidden unless `host.auth === 'key'`): `This connection previously used an SSH key. Run sudo bash deploy/setup-discovery.sh on the VM to create its password, then enter that password here.`
- `Inspection method` `#vm-command` select: `helper` = `Installed discovery and file helper (recommended)`, `direct` = `Direct inspection + SFTP (existing VM account)`; prefilled `host.command_mode || 'helper'`. Help: `Install the supplied VM setup script for the helper. The restricted helper reads deployment state and the original YAML, annotations, generated inventory and topology export. New labs appear for import confirmation. Direct mode reads these files through SFTP with the same VM account. The installed helper supports root-owned lab files.`
- checkbox `#vm-enabled` **Enable automatic discovery**; prefilled `host.enabled !== false`.
- `#vm-fingerprint` (`form-help`): `Saved fingerprint: {host.fingerprint}` or `No VM fingerprint saved yet.` Followed by static help `The first successful connection trusts and saves the VM SSH fingerprint. Later key changes block discovery.`
- checkbox `#vm-reset-key` **Trust a replacement SSH host key on the next connection** — always reset to **checked** each time the dialog opens (comment: rebuilt lab VMs get re-keyed).
- buttons `Cancel`, `Save and test connection` (submit).
- Submit: `PUT /api/host {address, port:Number, username, auth:'password', password, command_mode, enabled, reset_fingerprint}`; clears the password field and sets it not-required; `POST /api/discovery/refresh {}`; `refresh()`; if `(result.error || result.helper_update_required) && !result.checking` → keep dialog open with form error `result.error` or `Connected, but the installed VM helper is outdated. On the VM, run sudo bash deploy/start-manager.sh from the current source, then retry.`; else close and toast `VM connected. Lab discovery is active.` (connected) or `VM settings saved. Check the discovery status for the connection result.`
- Backend error on save: `Finish pending Git saves or choose Keep snapshot only before changing the VM identity.`
- Opened by S5, L2, S9 (auto prompt).

**D5 – `binding-dialog` / form `binding-form`** — eyebrow `DEPLOYMENT MATCHING`, h2 `Link deployed lab`.
- intro: `Associate this saved workspace with a lab on the configured VM. Existing inventory addresses stay manual until changed in Edit connection.`
- `Deployed lab name` `#binding-name` maxlength 120, `list=deployment-names` (datalist of discovered names).
- `Container prefix` `#binding-prefix` maxlength 120, default `clab`. Help: `Usually clab. An empty prefix matches bare node names. Leave the deployed name empty to unlink discovery.`
- buttons `Cancel`, `Save link` (submit).
- Submit: `PUT /api/labs/{activeId}/deployment {deployed_name: trimmed, prefix: trimmed}`; close; `refresh()`; toast `Deployment link saved.` Backend errors: `That deployment is already linked to another workspace`, `Lab not found`.

**D6 – `manager-settings-dialog`** (via `opDialog`, eyebrow `NODE MANAGER`, title `Manager settings`).
- `<h3>Start fresh</h3>`; copy: `Remove all imported labs, device credentials, schedules, saved backup files, job and operation history, logs, and discovery exclusions from this manager.` / **`Your VM connection, SSH key and trusted fingerprint are retained.`** `Running labs, original VM files and the installed helper account stay as they are.` / `Discovery will offer deployed labs for import again. Each import still requires confirmation.` / `Close SSH sessions and wait for active jobs before resetting.`
- input `Type RESET to confirm` `#manager-reset-confirm` (`autocomplete=off spellcheck=false`).
- buttons `Cancel` `#manager-reset-cancel` (closes), `Start fresh` `#manager-reset` (`disabled` until the input equals exactly `RESET`, re-evaluated on `input`).
- Confirm → `opTask`: `POST /api/manager/reset {confirmation}`; `activeId=''`, `sessionStorage.removeItem('activeLab')`, `tab='inventory'`, `importPreview=null`, `opCaps=null`; closes **every** open dialog; `refresh()`; toast `Manager data cleared. VM connection retained; deployed labs can be imported again.`
- Backend errors: `Type RESET to confirm.`, `Discovery is checking the VM. Retry after it finishes.`, `Close SSH sessions and wait for connection checks before resetting.`, `Storage reset could not finish. Check data directory permissions and free space, then retry Start fresh or restart the manager.`; while a reset is pending every other `/api/*` call returns 503 `A storage reset needs completion. Retry Start fresh or restart the manager.`

**D7 – `exclusion-menu`** (via `opDialog`, title `Excluded lab`) — opened by right-click / ContextMenu / Shift+F10 on an excluded lab (S3).
- shows the lab name; copy `Clear forgets this exclusion so discovery can offer the lab again. This does not import or change the lab.`
- button `Clear exclusion` `#clear-exclusion` → `POST /api/discovery/forget-exclusion {name}`; close; `refresh()`; toast `Exclusion cleared. The lab can appear for import again.` Backend error: `Could not save the change. Exclusion retained.`

**D8 – `backup-all-review`** — see T2.

**D9 – `op-open-tab`** fallback — see T1.

### 3.6 vm-connection.html (served at `GET /vm-connection-guide`; stylesheet `/static/style.css?v=1.28.0`, `<main class="vm-guide">`)

Static reference page, no scripts. Links: `← Containerlab Node Manager` → `/`; `Open Debug panel` → `/static/debug.html`; `the installation guide` → `https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2/blob/main/docs/INSTALL.md`; `OpenSSH's SSH server configuration reference` → `https://man.openbsd.org/sshd_config`.
Sections: `VM connection — password setup and recovery` (intro); `First launch or migration from an SSH key` (installer command `sudo bash "$HOME/projects/clab-manager/deploy/start-manager.sh" --enable-operations --lab-root /etc/containerlab`, password prompt behaviour, key→password migration, settings table VM address/SSH port/VM username/VM password/Inspection method/Automatic discovery, fingerprint check `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`); `Persistent storage` (table of VM paths: `/etc/shadow`, `/srv/containerlab-node-manager/data/state.enc`, `state.key`, `data/backups/`, `/etc/ssh/clab-manager-password.conf`, `/etc/ssh/sshd_config`, `/usr/local/sbin/clab-manager-gateway`, `/etc/sudoers.d/clab-manager-discovery`, `/etc/clab-manager/operations.json`; Compose `/data` mount, ownership `10001:10001 700`, `sudo bash deploy/setup-vm.sh`); `Upgrades and password changes` (`setup-discovery.sh`, `setup-operations.sh --lab-root`, `--update-helper`, `--reset-password`); `Troubleshooting` table (Password setup required; Authentication failed; Setup needs an interactive terminal; Conflicting SSH account policy; Connection refused / timed out; Interactive SSH / SFTP denied; Fingerprint changed; Helper outdated / commands unavailable; Save failed); closing note on `Manager settings → Start fresh` and `Remove lab`.

## 4. Status vocabulary

| Term | Where | Meaning in source |
|---|---|---|
| `VM discovery is not configured.` / `paused` / `VM connected · checks every 30s` / `helper update required` / `VM status unknown` | `#vm-summary` | discovery.configured / host.enabled / helper_update_required / connected / error |
| `Discovered` vs `Last seen` | discovered-lab `<small>` | whether discovery.connected is currently true |
| `Ready to import · confirmation required` | discovered-lab `<small>` | `discovery.pending_imports[name]` truthy |
| `Try importing VM files` | discovered-lab `<small>` | default when no file error / no pending import |
| `Excluded from automatic import` / `Import again` | `#excluded-labs` | name is in `discovery.ignored_labs` |
| `removed from this manager earlier` | landing "Already running" row | `discovered[].excluded` |
| `Unlinked` | `#deployment-status` | `lab.deployment` absent |
| `NOS ready` / `NOS booting` / `NOS login failed` | `#deployment-nos` | `lab.nos_readiness.status` ready/booting/failed; idle renders nothing |
| `VM files: {status}` | `#vm-files-status` | raw `lab.vm_source.status` string from backend |
| `Ready` (node readiness) | backup-all review | `node.readiness === 'Ready'` |
| `Manual` | auto-import copy | backup schedule interval 0 |
| `Worker idle` / `SSH job in progress` / `Saving lab progress` | topbar (app.js) | `busy()` / git job status |

## 5. Element ids referenced by management.js

Sidebar/landing/bar: `vm-summary`, `discovered-labs`, `discovery-file-list`, `excluded-labs`, `remove-lab`, `sync-vm`, `vm-files-status`, `deployment-status`, `deployment-message`, `deployment-checked`, `deployment-nos`, `deploy-empty`, `vm-connect-empty`, `empty-vm-note`, `empty-discovered`, `empty-discovered-list`, `new-lab`, `import-empty`, `import-inventory-empty`, `import-top`, `update-definition`, `vm-settings`, `vm-refresh`, `link-deployment`, `manager-settings`, `map-ssh-all`, `map-backup-all`, `details-dialog`.
Injected dialogs: `auto-import-dialog`, `auto-import-form`, `auto-import-summary`, `auto-import-files`, `auto-import-warnings`, `auto-import-excluded`, `remove-lab-dialog`, `remove-lab-form`, `remove-lab-name`, `remove-lab-id`, `remove-lab-confirm-name`, `remove-lab-exclude`, `setup-dialog`, `setup-form`, `setup-title`, `setup-auto-import`, `setup-lab-id`, `setup-deployed-name`, `legacy-import`, `vm-dialog`, `vm-form`, `vm-address`, `vm-port`, `vm-user`, `vm-password`, `vm-password-migration`, `vm-command`, `vm-enabled`, `vm-fingerprint`, `vm-reset-key`, `binding-dialog`, `binding-form`, `binding-name`, `binding-prefix`, `deployment-names`.
Lazily created: `manager-settings-dialog`, `manager-reset-confirm`, `manager-reset-cancel`, `manager-reset`, `exclusion-menu`, `clear-exclusion`, `backup-all-review`, `backup-all-confirm`.
Data attributes: `data-setup-name`, `data-allow-import`, `data-dismiss`.

## 6. API calls (all under `/api`, via `api()`/`json()`)

- `POST /lab-definitions` (multipart: `lab_id`, `definition`, `deployed_name`, `annotations`)
- `PUT /host` (JSON)
- `POST /discovery/refresh` `{}` (from VM dialog save and Refresh discovery)
- `POST /discovery/import-preview` `{name}`
- `POST /discovery/import` `{name, token}`
- `POST /discovery/forget-exclusion` `{name}`
- `PUT /labs/{id}/deployment` `{deployed_name, prefix}`
- `POST /labs/{id}/sync` `{}`
- `DELETE /labs/{id}` `{name, prevent_reimport}`
- `POST /labs/{id}/jobs` `{operation:'backup', node_names}`
- `POST /manager/reset` `{confirmation}`
- indirectly: `GET /state` (refresh), `POST /operations/browse`, `GET /operations/capabilities` (via `openDeploy`)
- Non-API navigation: `/vm-connection-guide` (new tab), `/static/workspace.html#mode=ssh&lab=…` (new tab), `/static/debug.html` (guide + sidebar link), `/` (guide back link).

## 7. Microcopy a CCNA-level student would not understand

See structured output for the full list. Highlights: "helper", "discovery", "inspection method", "Direct inspection + SFTP", "SSH fingerprint / host key", "container prefix", "bare node names", "Link deployment", "worktree/Git saves" (in host error), "persistent storage", "state.enc/state.key", "sudo bash deploy/start-manager.sh", "topology annotations", "Ansible inventory", "root-owned lab files", "Compose mounts … /data", "Match rules / PermitUserEnvironment", "SuperPuTTY" (elsewhere), "NOS", "containers running", "deployment matching".

## 8. Redesign risks

- Handler precedence depends on script order: management.js must keep overriding app.js for `new-lab`, `import-empty`, `import-top`; operations.js must keep binding `deploy-empty`.
- `renderManagement` is called by app.js `render()` via `typeof` check; renaming it silently drops all sidebar/landing/deployment-bar rendering.
- `renderLanding` bails out when `#deploy-empty` is absent — removing/renaming that id disables the whole landing update path (connect button, note, running list).
- All list clicks are delegated on the container ids (`discovered-labs`, `excluded-labs`, `empty-discovered-list`) using `data-setup-name` / `data-allow-import`; both container ids and data attributes are load-bearing.
- Right-click + ContextMenu/Shift+F10 on excluded labs is the only path to "Clear exclusion" (clicking them re-imports instead).
- Every dialog relies on `.form-error` inside the `<form>` (withForm/opTask write there) and `button[type=submit]` for the busy-disable; `[data-dismiss]` closes via `closest('dialog')`.
- `#deployment-nos`, `#empty-vm-note`, `.form-error` are hidden with `:empty` CSS rather than `hidden`; whitespace inside them would show an empty box.
- `#sync-vm` uses `hidden` (no deployment name) and `disabled` (not connected / cannot sync / busy) with no visible explanation; `#remove-lab` disabled state has no tooltip.
- The auto VM prompt checks `document.querySelector('dialog[open]')`; any redesign that keeps a non-modal `<dialog open>` (e.g. a drawer) permanently open will suppress the first-run prompt.
- `#vm-reset-key` is forced to checked on every open; the password field's `required` flips based on `host.auth`.
- `importPreview` is cleared on dialog `close`; a redesign that hides the dialog without closing it could allow a stale token submit (backend rejects with "Import confirmation expired").
- Sidebar `<small>` inside `.side-button` and `.side-button.side-primary` styling carry the status detail lines.
- `#setup-auto-import` visibility depends on a deployed name being known at open time (`deployedName` argument or first eligible discovered lab).
- The `Manual discovery` label on `#new-lab` opens the "Import a lab" definition dialog, not a discovery action; keep the id→handler mapping while fixing the label.
- Text `checks every 30s` is hard-coded; the browser polls every 4 s.
- `vm-connection.html` is served at `/vm-connection-guide` by FastAPI (`main.py` line 407); the dialog link and the guide's `/static/style.css?v=1.28.0` reference must survive.
