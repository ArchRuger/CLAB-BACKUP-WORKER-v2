# Manager UI Index (Release 1.30.32)

Quick-start Playwright guide: exact UI labels, selectors, file locations, and existing tooling.

---

## 1. Home page

### Deploy box
- **Label**: "Choose a file on the lab VM…" → `#home-deploy` → `home.js:86`
- **Label**: "Upload a file from this computer…" → `#home-upload` → `home.js:87`
- Onclick handlers call `openDeploy()` and `opUpload()` respectively

### Build box
- **Label**: "Open the lab builder" → `#home-build` href="/static/lab-builder.html" → `index.html:58`

### Lab cards
- **Container**: `#lab-cards` .lab-grid → `index.html:66`
- **Card markup**: `<article class="lab-card" data-lab-id="{id}">` → `home.js:48` (homeCard function)
- **Card actions**: 
  - **Open lab**: `[data-lab="{id}"]` → `home.js:74`
  - **Start lab**: `[data-lab-start="{id}"]` → `home.js:75`
  - **More actions**: `[data-lab-more="{id}"]` → `home.js:76`
  - **Favorite**: `[data-lab-favorite="{id}"]` → `home.js:77`
- **Lab card tabs**: Recent labs → `#home-tab-recent`, All labs → `#home-tab-all` → `index.html:64`

### Manager ▾ menu
- **Button**: "Manager" → `#manager-button` → `index.html:29`
- **Menu items**:
  - "VM connection…" → `#vm-settings` → `index.html:31`, handled in `management.js:172`
  - "Refresh lab list" → `#vm-refresh` → `index.html:32`, data-label attribute
  - "Deploy a new lab…" → `#vm-projects` → `index.html:34`, calls `openDeploy()`
  - "Labs found on the VM…" → `#manager-vm-labs` → `index.html:37`, managed in `management.js:158`
  - "Diagnostics" → link to `/static/debug.html` → `index.html:42`

### First-run (empty state)
- **Container**: `#empty` .empty-state → `index.html:68`
- **Actions when My labs is empty**:
  - "Connect the VM" → `#vm-connect-empty` → `index.html:68`
  - "Import lab files…" → `#import-empty` → `index.html:68`
  - "Import an Ansible inventory…" → `#import-inventory-empty` → `index.html:68`
- **Discovered labs under empty state**: `#empty-discovered` → `management.js:140–141`

---

## 2. Topology browser dialog (Deploy a new lab)

### Dialog launch
- Called via `openDeploy()` in `operations.js` (drives the full deploy flow)
- **Dialog id**: `#op-file-tree` or `#op-deploy` (dynamic)

### Folder and file browser
- **File tree**: `#op-file-tree` → `operations.js` (folder/file picking)
- **Folders**: `#op-file-tree summary[data-folder]` → clickable folder headers
- **YAML files**: `.op-tree-file` class → clickable `.clab.yml` entries
- **Deploy/Add buttons**:
  - "Deploy lab" (start and open) → `#op-deploy-project` → `operations.js`
  - "Add to My labs without starting" → offers second option in review

### Review dialog
- **Dialog heading**: "Start {lab name}?" or similar → `#operation-review h2`
- **Confirm button label**: "Start lab" → `#op-confirm` → `operations.js:142` (opReviewCopy table)
- **Output/banner**: `#op-job-banner` shows result → `operations.js`
- **Tool**: `student_workflow.py:48–50` (reaches browser, clicks deploy, waits for review)

---

## 3. Lab page

### Header
- **Lab name**: `#title` → `app.js` renders on lab select
- **State pill**: `#lab-state` (classes: `pill neutral|ok|warn|danger`) → `app.js`
  - States: "Not running", "Running", "Starting", "Partial", etc. → `status.js`
- **Ready line**: `#lab-ready` → "n of m devices ready" format → `app.js`
- **Progress**: `#lab-progress` → shows operation status → `app.js`

### Tabs
- **Container**: `#lab-tabs` role="tablist" → `index.html:110`
- **Tab ids**: 
  - `#tab-topology` (data-tab="topology", controls `#topology-view`)
  - `#tab-devices` (data-tab="devices", controls `#devices-view`)
  - `#tab-progress` (data-tab="progress", controls `#progress-view`)
  - `#tab-tools` (data-tab="tools", controls `#tools-view`)
  - `#tab-advanced` (data-tab="advanced", controls `#advanced-view`)

### Devices tab rows
- **List**: `#device-list` → `app.js:205` renders via `deviceRow()`
- **Device row**: `<li class="device-row state-{key}">` → `app.js:200` (deviceRow function)
- **State pills**: class `pill {key}` where key ∈ {Starting, Ready, Needs credentials, Needs attention} → `status.js:deviceState()`
- **Row markup**:
  - Device name: `.node-name [data-details="{name}"]` → click opens details
  - Platform badge: `.badge.platform` → "EOS", "Junos", "IOS XR"
  - State: `.pill` → "Ready", "Needs credentials", "Starting", "Needs attention"
  - Actions: `[data-terminal="{name}"]` (Open CLI), `[data-capture="{name}"]` (Capture), `[data-backup="{name}"]` (Back up), `[data-details="{name}"]` (Details)
- **Open CLI**: `[data-terminal="{device-name}"]` button → `app.js:189, 277` (handleNodeAction)
  - Opens `/terminal.html?device={device-name}&lab={lab-id}` or similar
  - Terminal page: `/static/terminal.html` → `index.html` shows xterm

### Open CLI / Terminal
- **URL pattern**: `/terminal.html?device={name}&lab={lab-id}&token={ticket}` (single-use ticket)
- **Terminal page** (`terminal.html`):
  - Heading: `<strong id="title">Device CLI</strong>` → device name
  - Status: `<span id="status">` role="status" → "Connected", "Disconnected"
  - Buttons: `#connect` (Reconnect), `#disconnect`
  - Terminal div: `#terminal` aria-label="Interactive SSH terminal"
  - Session closes after 15 minutes of inactivity (shown in notice)
- **Playwright**: `qa_lib.py` does not directly test terminal; `student_workflow.py` focuses on page structure

---

## 4. Progress tab (Save progress flow)

### Save location card
- **Container**: `#git-progress-bar` .card aria-label="Save lab progress" → `index.html:141`
- **Destination line**: `#git-destination` text-button → opens settings, calls `gitOpenRepository()` → `git-progress.js:161`
- **Status text**: `#git-progress-status` → shows current state or last save

### "Connect a repository by URL" dialog
- **Dialog id**: opened via button in the form, created dynamically
- **Fields** (from git-progress.js and git-places.js):
  - Repository URL (HTTPS): input field → `git-progress.js:205` mentions "Connect a repository by URL"
  - Folder browser: `#git-places-panel` → tree of folders → `git-progress.js:225–230` (gitPlacesShow)
  - Devices checkbox group**: `fieldset.git-node-scope` → checkboxes for included devices → `git-progress.js:209`
  - Acknowledgement: `#git-exposure` checkbox → `git-progress.js:213` (GIT_EXPOSURE_TEXT)
  - Confirm button**: "Connect save location" (new) or "Save settings" (bound) → `#git-binding-form submit` → `git-progress.js:238`

### Save location card (bound)
- **Container**: `#git-save-location` .card aria-labelledby="git-save-location-title" → `git-progress.js:219`
- **Destination**: shows "Lab saves to {repo} › {folder} › latest/" → `git-progress.js:219`
- **Change folder…**: `#git-change-folder` details → open to browse and "New folder…" → `git-progress.js:203, 225`
  - Folder browser: `#git-places-panel` → tree navigation → `git-places.js` (not shown here but driven via `go_to()` in `qa_lib.py:79`)
  - "New folder…": in the panel, click to create → `git-places.js` (creates inline input)
  - "Save this lab here": `[data-git-places-action="use"]` → moves the binding → `git-progress.js:229`

### Save progress button and menu
- **Button**: "Save progress" → `#git-save-progress` or `#progress-save` → `index.html:76, 142`
  - Calls `gitSaveProgress()` → `git-progress.js`
- **Menu** (details element): `#git-save-menu` → `index.html:76`
  - "Create checkpoint…" → `[data-git-action="checkpoint"]` → opens dialog → `git-progress.js:142`
  - "Save on this VM only" → `[data-git-action="local"]` → no review → `git-progress.js:142`
  - "Saved versions & history" → `[data-git-action="history"]` → opens full history → `git-progress.js:142`
  - "Save location settings…" → `[data-git-action="settings"]` → opens settings form → `git-progress.js:142`

### First-save dialog (when unbound)
- Opens form at `#git-save-location` (the whole card becomes the form) → `git-progress.js:219–222`
- **Repository dropdown**: `#git-binding-id` select → list of registered repos
- **Folder browser**: `#git-places-panel` within a details element → `git-progress.js:203–207`
- **Devices checkboxes**: under fieldset.git-node-scope → `git-progress.js:209`
- **Exposure checkbox**: "I understand that complete device configurations will be saved…" → `#git-exposure` → `git-progress.js:213`
- **Submit**: "Connect save location" → calls form onsubmit → `git-progress.js:234–240`

### Review before uploading dialog
- **Dialog id**: `#git-diff-dialog[open]` → created by `gitShowDiff()` → `git-progress.js`
- **Title**: "Review before uploading" or "Review changes"
- **Buttons**:
  - "Upload these changes" → `#git-review-push` → submits with push=true → `git-progress.js`
  - "Not now — keep it on the VM" → close/cancel
- **Tool**: `c1_prepare.py:56–61` (do_save → click_save_with_retry → upload_review)

### Job status texts (after save)
- **Saved to Git**: "Progress saved to Git" → status='synced' → `gitSaveSentences` → `git-progress.js:9`
- **Waiting for your review**: "Saved on this VM — review before uploading" → status='review_pending' → `git-progress.js:9`
- **Saved on VM**: "Saved on this VM — not uploaded" → status='committed' → `git-progress.js:9`
- **Job dialog**: `#git-job-dialog[open]` → shows job title and summary → `git-progress.js`

### Recent saves rows
- **Container**: `#git-saves-list` → `index.html:147`
- **Row**: `<li ... [data-git-job="{job_id}"]>` → `git-progress.js` (gitRenderSaves)
- **Row actions**: `[data-git-job-upload]` (Upload these changes), `[data-git-job-restore]` (Apply to running lab)
- **Tool**: `c1_prepare.py:106–134` (complete_pending_via_recent opens Recent saves, clicks row, finds upload button)

### Saved versions rows (Latest, Checkpoints, Baseline, etc.)
- **Container**: `#git-saved-versions` → `index.html:146`
- **Version rows**: `li.git-version-row` → one per group (Latest, Checkpoints, etc.) → `git-progress.js` (gitRenderVersions)
- **Version actions**:
  - "View" → `[data-git-version-action="view"]` → opens read-only version → `git-progress.js`
  - "Compare" → `[data-git-version-action="compare"]` → shows diff vs. latest → `git-progress.js`
  - "Apply to running lab…" → `[data-git-version-action="apply"]` → opens restore review → `git-progress.js`, calls `restoreFromFolder()` → `restore.js:119`
- **Tool**: `c_apply.py:77–86` (reach_review_via_saved_versions opens row, clicks apply button, finds restore review dialog)

### Apply review dialog (restore configuration)
- **Dialog id**: `#restore-review-dialog[open]` → `index.html` dynamic + `restore.js:131`
- **Title**: "Replace running configuration"
- **Source line**: "Source: {label} · {commit}" → built in `restore.js:163`
- **Device rows** (restore targets):
  - Container: `fieldset.restore-targets` → `restore.js:165`
  - Row: `<label class="checkbox-label restore-target">` → per device → `restore.js:145–154`
  - Checkbox: `input[name="restore-node" value="{name}"]` → checked/disabled per eligibility
  - Detail text**: "Already matches", "{n} differences", "Ready to apply", "Skipped — {reason}"
  - Per-device statuses (pills): "Waiting", "Backing up…", "Applying…", "Confirming…", "Replaced", "Replaced and verified", "Replaced — not verified", "Replaced — differences remain", "Not confirmed — the device undoes it", "Undone — previous configuration is back", "Unknown — check this device", "Not changed", "Skipped", "Interrupted"
    - Sourced from `restoreTargetLabels` → `restore.js:14–19`
- **Advanced options**: `details.restore-advanced` → confirm timeout (minutes) → `restore.js:172–175`
- **Acknowledgement**: "I understand the running configuration on the selected devices will be replaced." → `#restore-ack` checkbox → `restore.js:176`
- **Confirm button**: "Replace configurations" → `#restore-run` → `restore.js:183`
- **Tool**: `c_apply.py:65–122` (reach_review_via_folder / reach_review_via_saved_versions / reach_review_via_history, then check source line, toggle devices, screenshot, submit)

### Restore result (status after apply)
- **Job dialog**: `#restore-job-dialog[open]` → shows title and result → `restore.js:196–203`
- **Title**: "Configuration replaced", "Configuration replaced — needs attention", "Configuration not replaced", etc. → `restore.js:100–107`
- **Result sentence**: "Configuration replaced on {n} devices. {m} devices need attention. {p} devices undid the change. {q} devices were not changed." → `restore.js:85–99`
- **Per-device rows**: `div.restore-target-row` → one per device with status badge and detail → `restore.js:206–219`
  - Badges: "Replaced", "Replaced and verified", "Replaced — not verified", "Replaced — differences remain", "Not confirmed — the device undoes it", "Undone — previous configuration is back", "Unknown — check this device", "Not changed", "Skipped", "Interrupted"
  - Sourced from `restoreTargetLabels` → `restore.js:14–19`
  - Details for mismatch: "{n} expected lines missing, {m} unexpected lines remain"
  - Details for rollback: "The change was not confirmed in time. The device is set to undo it by itself."
  - Details for uncertain: "The manager could not check this device after the change. Look at it before relying on it."
  - Not-saved warning: "Replaced, but the device did not save it as its startup configuration; a device restart would lose it."

### Full history… / Update from repository
- **Button**: More menu → "Full history…" → `[data-git-action="history"]` → opens `#git-history-dialog[open]` → `git-progress.js`
- **Button**: "Update from the repository" → `[data-git-action="update"]` → calls `gitUpdateFromRepository()` → `git-progress.js`
- **Dialog**: `#git-history-dialog` shows commits and paths to apply from; click commit → choose path if multiple → click "View" → opens read-only version

---

## 5. Lab actions ▾ menu

- **Button**: "Lab actions" → `#lab-actions-button` → `index.html:78`
- **Menu**: `#lab-actions-menu` role="menu" → `index.html:79`
- **Menu items**:
  - "Start lab" → `#lab-start` (or `[data-op-action="start"]`) → calls `opReview()` → `operations.js`
  - "Stop devices" → `[data-op-action="stop"]` → `operations.js`
  - "Restart devices" → `[data-op-action="restart"]` → `operations.js`
  - "Sync topology from VM" → `#menu-sync-vm` data-proxy="sync-vm" → calls `syncVmTopology()` → `management.js:195–202`
  - "Packet capture…" → `#menu-capture` data-proxy="capture-open" → calls `openCapture()` → `capture.js`
  - "Lab files…" → `#menu-lab-files` → shows deployed files on the VM
  - "All lab operations…" → `#lab-actions` → full operations dialog → `openLabOperations()` → `operations.js:34`
  - **Destructive**:
    - "Redeploy lab…" → `[data-op-action="redeploy"]` → `operations.js`
    - "Destroy lab…" → `#menu-destroy` data-proxy="lab-destroy" → `operations.js`
    - "Remove from this manager…" → `#menu-remove-lab` data-proxy="remove-lab" → calls `openRemoveLab()` → `management.js:204–218`
  - **Advanced options**:
    - "Edit map" → `#menu-map-edit` data-proxy="map-edit" → opens map editor → `lab-builder.html` in map mode
    - "Operation history…" → `#menu-operation-history` → shows operation log
    - "Telemetry settings…" → `#menu-telemetry` → opens telemetry config dialog

---

## 6. Lab builder page (lab-builder.html + lab-builder-page.js)

### Page layout
- **Header bar**: `#builder-bar` class="builder-bar"
  - Back link: `← My labs` → href="/"
  - Title: "Lab builder"
  - Lab name: `#builder-name` (shows current draft name)
  - Status pill: `#builder-status` (class="pill {tone}") → shows "Draft · kept in this browser only", "Saved on the VM", "Changes not saved to the VM yet", "Last change not kept"
  - Buttons:
    - "Drafts…" → `#builder-drafts` → opens draft list dialog
    - "Download draft" → `#builder-download` (disabled until draft exists)
    - "View YAML" → `#builder-yaml` (disabled until draft exists)
    - "Save to the VM…" → `#builder-save` (disabled if blocked) → calls `builderSave()`

### Welcome screen (no draft yet)
- **Container**: `#builder-welcome` (main.builder-welcome class)
- **Title**: "Build a lab"
- **Buttons**:
  - "New lab…" → `#builder-welcome-new` → opens new-lab dialog
  - "Open a draft…" → `#builder-welcome-drafts` → opens drafts list

### New lab dialog
- **Dialog id**: `#builder-new` (created via `opDialog()`)
- **Fields**:
  - Lab name: `#builder-new-name` input → must match `/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,59}$/` → `lab-builder-page.js:22`
  - Start from: `#builder-new-starter` select → "Blank canvas", "Two devices, one link", "Three devices in a triangle"
  - Device type: `#builder-new-template` select → "Arista cEOS", "Juniper cJunosEvolved", "Juniper vJunos-switch", "Cisco XRv9k", "Linux host"
  - Lab folder on the VM: `#builder-new-root` select → list of roots (`/srv/containerlab-node-manager/projects` or similar)
- **Submit button**: "Create draft" → `#builder-new-create` → calls `builderUse()` → `lab-builder-page.js:189`

### Drafts dialog
- **Dialog id**: `#builder-drafts-list` (created dynamically)
- **Rows**: one per draft → name, updated time, status
- **Actions**: Open, Delete, Download

### View YAML dialog
- **Dialog id**: `#builder-yaml-dialog`
- **Content**: `#builder-yaml-text` (read-only pre with YAML text)
- **Close button**: `[data-op-close]`

### Editor canvas
- **Container**: `#root` → mounted React app (embedded editor from `lab-builder/assets/main.js`)
- **Hint text**: `#builder-hint` → "Drag a device from the palette on the right onto the canvas to begin."
- **Editor controls** (hidden):
  - `[data-testid="navbar-deploy"]` → hidden (deploy/revise through the manager)
  - `[data-testid="navbar-deploy-menu"]` → hidden
  - `[data-testid="navbar-split-view"]` → hidden
  - `[data-testid="navbar-layout"]` → visible (layout controls); geo layout hidden
  - `[data-testid="navbar-undo"]` → visible
  - YAML/JSON tabs → hidden
- **Nodes**: `.react-flow__node` (draggable from palette or on canvas)
- **Links**: `.react-flow__edge` (drawn between nodes)
- **Node actions** (right-click menu):
  - "Edit Node" → opens inline edit dialog
  - "Create Link" → awaits second node click
  - "Delete Node" → removes node and its links
- **Undo**: `[data-testid="navbar-undo"]` → restores deleted nodes/edges

### Save review dialog (save to the VM)
- **Dialog id**: `#operation-review` (created via `opReview()`)
- **Title**: "Save {lab name} to the VM?" or "Save the changes to {lab name}?"
- **Content**: Shows lab folder path, YAML content (in details), diff if revising
- **Confirm button**: "Save lab" or "Save changes" → `#op-confirm` → calls `opConfirm()` → `operations.js:145`
- **Cancel button**: "Cancel" → `#op-cancel`

### Deploy or add dialog (after save)
- **Dialog id**: `#operation-output` (job result dialog)
- **Title**: "Save lab" or "Save topology changes" (shows job name)
- **Content**: Job banner showing "succeeded" + options to deploy or add
  - "Deploy lab" → `#op-open-published` (or similar) → goes to deployment dialog
  - "Add to My labs without starting" → returns to Home

### Problem overlay (browser storage error)
- **Overlay id**: `#builder-problem` role="alertdialog"
- **Message**: Explanation of why editing is paused
- **Buttons**:
  - "Download this version" → `#builder-problem-download`
  - "Try to store it again" → `#builder-problem-retry` (if storage error)
  - "Reload" → `#builder-problem-reload`

### Note below header (when deployed or no storage)
- **Note**: `#builder-note` role="status" (text + optional "Check again" button)
- **Messages**:
  - "This browser does not let the page store drafts. Your work lives in this tab only."
  - "{Lab name} is deployed. You can edit the draft, but it can only be saved to the VM after the lab is destroyed."
  - "Checking whether saving to the VM is available…"
  - "Saving to the VM is not available right now. You can keep building."

### Tool**: `student_workflow.py`
- Opens builder from Deploy dialog → `args.base + '/'`, clicks `#home-deploy`, clicks `#op-build`
- Creates new lab → fills `#builder-new-name`, selects starter/template, clicks `#builder-new-create`
- Waits for editor: `.react-flow__node` visible, 1.5s timeout
- Checks status: `#builder-status` text contains "not on the VM yet"
- Adds device: drags from palette (`.react-flow__node-output` or similar), drop on canvas, waits 0.9s
- Right-click: uses center() + `pg.mouse.click(x, y, button='right')`, then clicks menu item
- Saves: clicks `#builder-save`, waits for review dialog `#operation-review`
- Downloads: clicks `#builder-download`, uses `pg.expect_download()`
- Tests multi-tab conflict: opens draft in another tab, deletes a node there, then tries to delete in first tab; expects `#builder-problem` overlay

---

## 7. Existing Playwright tool functions

### qa_lib.py (docs/save-location-fix/tools/qa_lib.py)

| Function | Signature | Purpose |
|---|---|---|
| `open_lab` | `open_lab(page, reload=False)` | Open lab page, click Progress tab, wait for save location card |
| `poll_job` | `poll_job(page, job_id, timeout=180)` | Poll `/api/git/jobs/{job_id}` until final state (synced, failed, etc.) |
| `upload_review` | `upload_review(page, timeout=30000)` | Click "Upload these changes" in open review dialog; return (job_id, response) |
| `click_save_with_retry` | `click_save_with_retry(page, max_attempts=4, wait_each=45000)` | Click Save progress; retry on transient read miss; wait for review or job dialog |
| `open_change_folder` | `open_change_folder(page)` | Open `#git-change-folder` details if closed; wait for panel header |
| `go_to` | `go_to(page, path)` | Click folder path in panel via `[data-git-place="{path}"]`; wait for breadcrumb current |
| `destination_line` | `destination_line(page)` | Return text of `#git-save-location .git-destination-line` (the "saves to" label) |
| `legacy_notice` | `legacy_notice(page)` | Return text of `#git-legacy-notice` (warning if saving to a reserved folder name) |

### c_lib.py helpers (docs/save-location-fix/tools/c_lib.py)

| Function | Purpose |
|---|---|
| `api(page, method, path, body)` | Fetch from inside page context (same-origin) |
| Various helper functions for state classification (A/B/C markers), drift, readback checks |

### c1_prepare.py (docs/save-location-fix/tools/c1_prepare.py)

| Function | Purpose |
|---|---|
| `create_checkpoint(page, name, note)` | Click checkpoint button, fill name/note, submit; return job_id |
| `set_baseline_from(page, job_id)` | Set baseline from a prior save job; return job_id |
| `do_save(page, record, key)` | Full save workflow: click Save, upload review, poll job; record steps |
| `update_from_repository(page, record)` | Click Update from repository, submit; record response |

### c_apply.py (docs/save-location-fix/tools/c_apply.py)

| Function | Purpose |
|---|---|
| `reach_review_via_folder(page, path_parts, record)` | Navigate folder browser to path, click Apply → opens restore review |
| `reach_review_via_saved_versions(page, match_text, record, group_hint)` | Reload, click row matching text, click apply → opens restore review |
| `reach_review_via_history(page, commit_match, path_match, record)` | Open history dialog, click commit, choose path if prompted, view, restore |
| `readback_saved(nodes, expect, saved, timeout)` | Run `readback.py` subprocess to verify device configs against saved folder |
| `boot_identity(nodes)` | Get boot timestamps/uptime before/after restore (verify no reboot) |

### student_workflow.py (docs/lab-builder/tools/student_workflow.py)

| Function | Purpose |
|---|---|
| `run(p)` | Full lab builder flow: new lab → edit nodes/links → save to VM → deploy → verify in My labs → edit existing draft |
| Helpers: `node()`, `nodes()`, `edges()`, `draft()`, `menu()`, `wait_job()` | Locators and async waits for Playwright |
| Checks builder UI elements, validates YAML, tests multi-tab conflict detection, captures screenshots at key steps |

---

## Discrepancies

None found between source and docs/LAB-BUILDER.md, docs/GIT-PROGRESS.md, docs/LAB-OPERATIONS.md on the labels indexed here. All button labels, dialog titles, and status pills match the documented UI text.

