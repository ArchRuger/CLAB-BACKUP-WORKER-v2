# Inventory: repository folder browser (git-places.js) and live configuration restore (restore.js)

Read completely (every line): 
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/git-places.js` (103 lines, 12,185 bytes)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/restore.js` (143 lines, 9,945 bytes)

Skimmed for wiring, ids, response shapes and tests that pin behaviour:
- `app/static/index.html` (all 100 lines)
- `app/static/git-progress.js` lines 55-175 and 280-320 (the caller of `gitPlacesShow`, the `onUse`/`onNew`/`onApply` callbacks, the "Use a different repository" and "Connect by URL" dialogs, the version dialog that calls `restoreFromVersion`)
- `app/static/app.js` lines 1-16 and 92 (`$`, `esc`, `state`, `notify`, `api`, `json`, `refresh`, `utcDisplay`), `app/static/operations.js` lines 5-14 (`opDialog`, `opTask`)
- `app/static/style.css` rules for every class the two files emit
- `tests/test_git_places_ui.js`, `tests/test_restore_ui.js` (pin exact markup and helper outputs)
- `app/git_progress.py` (routes `/tree`, `/folders`, `/destination`, `folder_value`), `app/restore.py` (preflight/submit/job routes, reason and message strings), `app/host_git.py` (`browse()`: `MAX_TREE = 4000`, `saved` keys)

Neither assigned file touches `sessionStorage`, `localStorage`, `IndexedDB`, `window.onkeydown` or any URL/hash routing. Neither is an ES module: both are classic scripts loaded with `defer` after `app.js`, `operations.js` and `git-progress.js` (index.html line 5), and the unit tests run them with `vm.runInContext`, so every top-level `function`/`const`/`let` is a global that the tests and other files reach by name.

---

## 1. Where these files appear in the UI

- **Git repository tab** (`index.html` line 50 tab `data-tab="git"`, section `#git-view`, content `#git-repository-content`, button `#git-repository-refresh` "Refresh status"). `git-progress.js` `gitRenderRepository` draws, in order: optional `status.problem` notice, the "CONNECTED REPOSITORY" card (with `data-git-repo-action="switch"` "Use a different repository…", `history`, `update`, `unlink` "Disconnect"), the **"Where this lab lives"** section (`<section class="git-places" aria-label="Where this lab lives">` with `<h3>Where this lab lives</h3>` and `<div id="git-places-panel">`), then the binding form `#git-binding-form` (select `#git-binding-id` "Repository and folder", inline text button `data-git-repo-action="connect"` "Connect a repository by its URL", device checkboxes `name="git-node"`, `#git-review-before-push`, `#git-exposure`), or, when no repository is registered on the VM, a blank state with `data-git-repo-action="connect"` "Connect a repository by URL".
- The "Where this lab lives" section is rendered only when `repositories.length || activeBinding`. Its description text: connected → "The folders of the connected repository, as they are in Git right now. Select a folder and choose **Save this lab here** to move this lab, or create a new folder."; not connected → "The folders of the selected repository. Choose a folder for this lab, or create a new one, then confirm the connection below."
- `showPlaces(bindingId)` (git-progress.js line 89-94): if no bindingId → panel shows `<p class="git-empty-folder">Choose a repository folder above to see what is in it.</p>`; else `connected = !!binding && !!browsed && browsed.path === repo.path` (the registration selected in the form lives in the same checkout as the lab's binding) and calls `gitPlacesShow(panel, labId, bindingId, {current: binding?.binding_id || '', connected, onUse: gitUseFolder, onNew: gitNewFolder, onApply: restoreFromFolder if defined})`. `canAct` is never passed (defaults to true).
- Which registration is browsed: when the binding form exists, the `#git-binding-id` select's `onchange` calls `showPlaces(selectedRepo?.id || binding?.binding_id || '')` and the same runs once at render; when there is no form but there is a binding, `showPlaces(binding.binding_id)`. So changing the select re-fetches the tree for another registration (repo + prefix).
- **Saved configuration version dialog** (`git-version-dialog`, git-progress.js line 295): button `#git-version-restore` "Apply to running lab…" (class `button danger`) appears only when `data.restore_supported` and `restoreFromVersion` exists; it closes the version dialog and calls `restoreFromVersion(id, {type:'git', commit, path}, label)`. Help text there: "This version has a restore-grade Junos candidate. **Apply to running lab** loads it onto the running node (no reboot); the current configuration is backed up first." / "View or download only — this saved version predates live restore support, so it cannot be applied to a running device."
- There is **no other entry** to `restoreShowJob`: it is only called right after submitting a restore. No screen lists past restore jobs; the dialog text says the result "stays in the action log" (Action logs tab, `#logs-view`).

---

## 2. git-places.js — globals defined

| Name | Kind | Purpose | Used outside file |
|---|---|---|---|
| `gitManagedFolders` | const object | Descriptions of manager-owned folders: `latest` → "Most recent save", `baseline` → "Reference version set with Set baseline", `checkpoints` → "Named milestones", `checkpoint` → "Milestone saved with Save checkpoint" | no |
| `gitPlacesState` | const object `{labId, bindingId, model, tree, selected, request}` | In-memory browser state (selected folder path, last tree, stale-request counter). **Not persisted.** | yes: git-progress.js sets `gitPlacesState.selected` at lines 112 (after destination change), 143 (after new folder), 167 (after connect by URL) |
| `gitSize(bytes)` | function | Human size: non-finite/negative → `''`; `<1024` → `N B`; `<1 MiB` → KB with 1 decimal below 10 KB else 0 decimals; else MB with 1 decimal | tests only |
| `gitFolderName(value)` | function | Single segment rule: `/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,180}$/`, not `.git` (any case), not `.` or `..`; throws "Use letters, numbers, dashes, dots or underscores for the folder name, without slashes." | tests only (in-file by `gitFolderPath`) |
| `gitFolderPath(value)` | function | Nested destination typed in one go: trims, strips leading/trailing `/`, splits on `/`, trims and drops empty segments; empty → throws "Enter a folder name."; each segment through `gitFolderName` | yes: git-progress.js lines 140 (New folder confirm) and 162 (Connect by URL folder) |
| `gitDestinationPreview(parent, typed)` | function | Returns `parent/nested` (or `nested`) for the live "Result" preview; `''` for empty/invalid input | yes: git-progress.js line 136 |
| `gitPathChips(path)` | function | Breadcrumb chips starting with root `{name:'', path:''}` | no |
| `gitTreeModel(files, folders)` | function | Builds `{root, nodes: Map}` from flat committed file list plus registered folders (see rules below) | no (tests) |
| `gitOwningFolder(model, path)` | function | Deepest registered folder whose path equals `path`, is `''` (root registration owns everything) or is an ancestor of `path` | no |
| `gitLabFolder(model, bindingId)` | function | The registered folder node whose `registration.id === bindingId`, or null | yes: git-progress.js lines 126, 133 (to count files to move) |
| `gitFolderChoice(model, path, current)` | function | `{allowed, reason}` for "Save this lab here"/"Choose this folder" (rules below) | no (tests) |
| `gitCanCreateIn(model, path, current)` | function | New folder allowed unless the selected folder is owned by another lab's registration | no (tests) |
| `gitFolderTag(dir, current, long)` | function | Tag markup `This lab[ saves here]` / `<Lab>[ saves here]` / `Lab folder[ · not connected to a lab]` | no |
| `gitPlacesMarkup(model, view)` | function | Whole browser markup (head, outline, listing, foot) | no (tests) |
| `gitPlacesShow(container, labId, bindingId, options)` | async function | Fetches the tree, builds model, draws, binds clicks | yes: git-progress.js line 93 |

### Tree model rules (`gitTreeModel`)
- A file entry is skipped when `path` is not a non-empty string, starts with `/`, or ends in `/` (empty name). A folder entry is skipped when `prefix` is not a string.
- Every intermediate directory is created (`ensure`). Directories and files are sorted with `localeCompare`; `size` and `count` are aggregated recursively (count = number of files in subtree).
- A registered folder (`registration` set from `folders[]`, each `{id, label, prefix, lab: {id,name} | null}` from `GET /api/git/repositories/{id}/tree`) is **pending** when its subtree has zero files ("created on first save").
- Only under a registered folder: direct children named `latest`, `baseline`, `checkpoints` get `managed = <name>`; grandchildren under `checkpoints` get `managed = 'checkpoint'`.
- `restorable` = the folder has a direct child `latest` containing a file matching `/\.jcfg$/i` (a Junos restore artifact), regardless of registration. A parent folder is not itself restorable (test line 125).

### Folder choice rules (`gitFolderChoice(model, path, current)`) — exact reasons
1. Path not in model → `{allowed:false, reason:'Choose a folder.'}`
2. Managed folder: `checkpoint` → "This is a saved milestone. Choose a folder outside the lab folder that holds it."; `latest`/`baseline`/`checkpoints` → "The lab manager fills `<name>` folders itself. Choose the folder above it."
3. Owned by another lab's registration (owner path ≠ path and owner id ≠ current) → "This folder is inside `<Lab name>`'s lab folder." or "This folder is inside another lab folder." (registration without a lab). A lab may move deeper inside its own folder (test line 36).
4. Registered folder: `id === current` → "This lab already saves here."; has `lab` → "`<Lab>` already saves here."; else allowed with reason "A lab folder no lab is using."
5. Root selected while other labs are registered in subfolders → "This repository already has lab folders. Pick one of them or create a new folder."
6. Subfolder selected while another lab is registered at root → "A lab saves at the root of this repository, so it cannot also use folders."
7. Folder contains other labs' registered folders → "This folder contains other lab folders."
8. Otherwise allowed with reason `''`.

`gitCanCreateIn` → true when no owner or owner is the current lab's registration; else "New folder…" is disabled with title "Folders cannot be created inside a lab folder".

---

## 3. git-places.js — rendered pieces (all inside the `container` = `#git-places-panel`)

| # | Piece | Markup / trigger | Behaviour |
|---|---|---|---|
| P1 | Loading status | `<p role="status" class="git-empty-folder">Reading the repository folders on the VM…</p>` | Shown immediately on `gitPlacesShow`; `GET /api/git/repositories/{bindingId}/tree` |
| P2 | Load error | `<p class="form-error" role="alert">{error.message}</p><p class="form-help">Check the VM connection and choose Refresh status.</p>` | Only if this request is still the newest (`gitPlacesState.request` counter); returns null |
| P3 | Stale-response guard | `request !== gitPlacesState.request` → return null | A slower older tree fetch never overwrites a newer one |
| P4 | Selection memory | `gitPlacesState.selected` | Reset to the current lab's registered folder path (or `''`) when the bindingId changes or the remembered path no longer exists in the new tree; otherwise kept across redraws/refreshes |
| P5 | Breadcrumb chips | `<nav class="git-crumbs" aria-label="Repository folder">` with `<button type="button" data-git-place="{path}" aria-current="page">{name}</button>` separated by `<span aria-hidden="true">›</span>` | Root chip label = `gitRepoName(tree.repository)` (last segment of repo path, else label, else "Repository"). Click → select + redraw |
| P6 | Folder outline (left) | `<div class="git-outline" aria-label="Folders">` nested `<details open?>` with `<summary data-git-place class="selected?">` + `<i class="git-folder-icon lab|managed pending">` + name + short tag | A `<details>` is `open` when it is root, the selected node, or an ancestor of it; `git-leaf` class when it has no subfolders (marker hidden by CSS). Click handler calls `event.preventDefault()` so the native details toggle is suppressed; open state is purely derived from the selection on redraw |
| P7 | Listing table | `<table>` thead "Name" / "What it is" / "Size" | Folder rows: `<tr class="row folder" data-git-place>` (click navigates). Description: managed → `gitManagedFolders` text; registered → "Lab folder · empty until its first save" (pending) or "Lab folder"; else "Folder". Plus long tag and, if pending, `<b class="git-tag pending">created on first save</b>`; size blank when pending. File rows: `<i class="git-file-icon">`; description `manifest.json` → "Save details: devices, checksums, capture time"; `.cfg/.conf/.txt/.set` → "Device configuration"; else "File"; size via `gitSize` |
| P8 | Empty folder | `<p class="git-empty-folder">` | "This folder appears in the repository after the first save." (pending registered folder) else "Nothing here yet." |
| P9 | Folder tags | `<b class="git-tag">This lab</b>` (+ " saves here" in listing), `<b class="git-tag other">{Lab name}</b>` (+ " saves here"), `<b class="git-tag other">Lab folder</b>` (+ " · not connected to a lab") | `current` = the lab's own binding id |
| P10 | Footer left | `<div class="git-places-foot"><span>…` | "Last save {utcDisplay(saved.latest*1000)}" when `tree.saved.latest` (epoch seconds from `git log -1 --format=%ct` on the `latest` scope) else "No save yet" when the current lab has a registered folder in this tree, else ''; then " · as of commit {head[0..10]}" when `tree.head`; then " · list shortened to the first 4000 files" when `tree.truncated` (backend `MAX_TREE = 4000`) |
| P11 | Footer right | second `<span>` | Always `choice.reason` (both branches of the ternary are identical), e.g. "A lab folder no lab is using." or the blocking reason, or empty |
| P12 | **Apply to running lab…** | `<button type="button" class="button danger" data-git-places-action="apply" title="Load this saved configuration onto the running lab (no reboot)">` | Rendered only when `options.onApply` was passed (i.e. `restoreFromFolder` is defined) **and** the selected folder is `restorable`. Rendered even when `canAct` is false. Click → `opTask(null, () => restoreFromFolder(labId, selectedPath, tree))` |
| P13 | **New folder…** | `<button type="button" class="button secondary" data-git-places-action="new" [disabled] title="Create a folder here" \| "Folders cannot be created inside a lab folder">` | Only when `canAct` (always in current wiring). Click → `opTask(null, () => gitNewFolder(labId, selectedPath, model, tree))` |
| P14 | **Save this lab here** / **Choose this folder** | `<button type="button" class="button primary" data-git-places-action="use" [disabled] title="{choice.reason}">` | Label "Save this lab here" when `view.connected`, else "Choose this folder". Disabled unless `gitFolderChoice(...).allowed`. Click → `opTask(null, () => gitUseFolder(labId, selectedPath, model, tree))` |

Handlers are re-bound after every draw with `element.onclick =` (no delegation). `opTask(null, fn)` with a null dialog means an error surfaces only as a toast (`notify(e.message)`).

---

## 4. Flows wired in git-progress.js (lines 108-170) that the panel buttons open

### 4a. Save this lab here (`gitUseFolder(id, path, model, tree)`)
- Loads `GET /api/labs/{id}/git` (forced).
- **Not connected to this repository** (no binding, or `binding.repository.path !== tree.repository.path`): takes the folder's existing registration or creates one with `POST /api/git/repositories/{tree.repository.id}/folders {prefix: path}` (backend `folder_value` validation; event `git.folder`); sets `gitPendingSelection = registration.id`; re-renders the Git tab (the new registration is preselected in `#git-binding-id`); toast "Folder chosen: {path | the repository root}. Confirm the devices below to connect {Lab}."; scrolls `#git-binding-form` into view. No move, no binding change yet — the user must submit the form ("Connect repository") which does `PUT /api/labs/{id}/git`.
- **Connected**: opens dialog `git-folder-dialog` titled **"Save this lab here?"**: "**{Lab}** will keep its progress in `{repo} › {path}` from now on." If the lab's current folder has files (`gitLabFolder(model, binding.binding_id).count`): checkbox `#git-move-files` (checked) "Also move the {N} files already saved under `{from prefix | the repository root}` into the new folder. This makes one commit and pushes it."; otherwise "Nothing is saved under the current folder yet, so there is nothing to move." Help: "Earlier versions stay in Git history either way. Scheduled backups and the device selection do not change." Buttons: Cancel (`#git-folder-cancel`), **Save here** (`#git-folder-confirm`).
- Confirm → `gitApplyDestination`: `POST /api/labs/{id}/git/destination {prefix, move_files}`; clears cached context; `gitPlacesState.selected = prefix`; `refresh()`; re-render Git tab; if a move job was returned, remembers it and opens the Git job dialog (`gitShowJob`, target "Folder move → …"); toast "{Lab} now saves to {prefix | the repository root}."
- Backend refusals shown in the dialog's form-error: "This lab already saves to that folder.", "Reconnect the original VM before changing the folder.", "This folder is already connected to another lab ({name}). Choose a different folder.", "The VM did not return the new folder registration.", "The folder changed, but the file move could not be queued.", "Use folder names with letters, numbers, dashes or underscores; use / to nest. No leading slash, no .. and no .git parts."

### 4b. New folder (`gitNewFolder(id, parent, model, tree)`)
- Dialog `git-new-folder-dialog` titled **"New folder"**: path line `<p class="op-path">{repo} › {parent} › <em>new folder</em></p>`; label "Folder name"; input `#git-new-folder-name` (maxlength 360, placeholder `Week-04/BGP/Final-State`, autocomplete off, spellcheck off); help "Letters, numbers, dashes, dots and underscores. Use `/` to create nested folders in one step. Git shows a folder once something is saved in it."; live preview `#git-new-folder-result` (`<p class="git-destination-line" hidden><span>Result</span><code>{repo} / {full path}</code>`) updated on `input` via `gitDestinationPreview` — hidden while the entry is empty or invalid.
- Connected: checkbox `#git-new-folder-use` (checked) "Save {Lab} here from now on"; if the current folder has files: checkbox `#git-new-folder-move` (checked) "Also move the {N} files already saved under `{from}` into it. This makes one commit and pushes it." Not connected: help "The folder is prepared for this lab. Confirm the devices below afterwards to connect it."
- Buttons: Cancel (`#git-new-folder-cancel`), **Create folder** (`#git-new-folder-confirm`).
- Confirm → `gitFolderPath(name)` (errors "Enter a folder name." / "Use letters, numbers, dashes, dots or underscores…" shown in the dialog's form-error); `prefix = parent ? parent/nested : nested`. If connected and "use" checked → `gitApplyDestination(id, prefix, moveChecked)` and close. Else `POST /api/git/repositories/{tree.repository.id}/folders {prefix}`; close; `gitPlacesState.selected = prefix`; if not connected `gitPendingSelection = created.repository.id`; re-render; toast "Folder {prefix} is ready for a lab."

### 4c. Use a different repository (`gitSwitchRepository(id)`, connected-card button `data-git-repo-action="switch"`)
- Loads context + `GET /api/git/repositories`; lists registrations other than the current binding.
- Dialog `git-switch-dialog` titled **"Use a different repository"**: "Pick another repository already set up on this VM, or connect a new one by its URL. Files already saved in the current repository are not deleted." If any: label "Repositories on this VM", select `#git-switch-id` with options "{repo} › {prefix | repository root} · {branch}", button **Choose this repository** (`#git-switch-choose`, secondary) → `gitPendingSelection = value`; close; re-render Git tab (option preselected, tree shown for it); toast "Choose the folder and confirm the devices below."; scroll to the form. Else "No other repository is set up on this VM yet." Then `<h3>Connect a repository by URL</h3>`, help "For a repository that is not on this VM yet. You need its HTTPS clone URL and the GitHub login already set up on the VM.", button **Connect by URL…** (`#git-switch-connect`, primary) → closes and opens 4d.

### 4d. Connect a repository by URL (`gitConnectByUrl(id)`; reached from 4c, from the blank-state button "Connect a repository by URL", from the inline text button "Connect a repository by its URL" in the binding form, and from `gitRunAction('connect')`)
- Dialog `git-connect-dialog` titled **"Connect a repository by URL"**: "Paste the HTTPS clone URL from GitHub (Code › HTTPS). The manager clones it on the VM as its Git account, using the GitHub login already set up there. It never asks for a token or password."; label "Repository URL", input `#git-connect-url` (placeholder `https://github.com/you/your-lab-repo`); label "Folder for this lab *optional*", input `#git-connect-folder` prefilled with `gitSuggestedFolder(labName)` (non `[A-Za-z0-9_.-]` runs → `-`, leading non `[A-Za-z0-9_]` stripped, trailing `-` stripped, max 60 chars, fallback `lab`), maxlength 180; help "One repository can hold several labs, each in its own folder. Clear it to save at the repository root of a single-lab repository."; checkbox `#git-connect-ack` "I understand that full device configurations, including any secrets they contain, will be committed and pushed to this repository."; help "If no commit name and email are set on the VM yet, the GitHub account's name and its private noreply address are used."; Cancel (`#git-connect-cancel`), **Connect repository** (`#git-connect-confirm`).
- Confirm: URL must match `/^https:\/\/[^\s/]+\/\S+/` else "Paste the HTTPS clone URL, for example https://github.com/you/your-lab-repo."; folder normalised with `gitFolderPath` when non-empty; ack required else "Acknowledge exporting full configurations to this repository."; button text becomes "Connecting… this can take a minute" for the duration; `POST /api/labs/{id}/git/connect {url, prefix, acknowledge:true, node_names: existing binding's or [], review_before_push: existing or false}`; close; clear cached context; `gitPlacesState.selected = folder`; `refresh()`; re-render; toast "{Lab} is connected to {repo}."; button label restored in `finally`.

### 4e. Apply from folder (`restoreFromFolder`, restore.js lines 44-51)
- `prefix` = selected path with trailing slashes removed; empty (repository root) → toast "Choose a saved folder to apply." and stop (the root can never be applied, even if `latest/*.jcfg` exists at root, because the button requires `dir.restorable` on the selected node and the guard rejects `''`).
- Source sent: `{type:'folder', path: prefix + '/latest'}`; label "{repo} · {last path segment} (latest saved state)". Then the review dialog (section 6).

---

## 5. restore.js — globals defined

| Name | Kind | Purpose | Used outside file |
|---|---|---|---|
| `restoreActiveJob` | Set | Statuses that keep polling: queued, preflight, backing_up, applying, confirming, verifying | no |
| `restoreJobLabels` | object | Job status → label (section 8) | no |
| `restoreTargetLabels` | object | Per-node status → label (section 8) | no |
| `restoreGoodTarget` | Set(applied, verified) | **Defined but never used** (restoreBadge hard-codes its own lists) | no |
| `restoreBadTarget` | Set(failed, rollback_expected, ineligible, verify_mismatch) | **Defined but never used** | no |
| `restoreWatch`, `restoreWatchTimer`, `restoreDialogJob` | let | Current polled job id, its timer, the job id whose dialog is open | no |
| `restoreRequestId()` | function | 32 hex chars from `crypto.getRandomValues` (idempotency key; backend pattern `^[0-9a-f]{32}$`) | tests |
| `restoreBadge(status, labels)` | function | `<span class="badge good|running|bad|warn">{label or raw status}</span>`: good for succeeded/verified/applied; running for any `restoreActiveJob` status (also target statuses backing_up/applying/confirming); bad for failed/preflight_failed/rollback_expected; warn for everything else (partial, needs_attention, interrupted, dismissed, pending, applied_unverified, verify_mismatch, ineligible) | tests |
| `restoreSourceLabel(source)` | function | "Git version · {commit[0..10] or path}", "Saved capture · {backup_job_id[0..10]}", else "Saved configuration" (note: a `folder` source falls to "Saved configuration"; callers pass an explicit label instead) | tests |
| `restoreFromVersion(labId, source, label)` | async | Entry from the Git version dialog → `restoreReview` | yes: git-progress.js line 296 (guarded by `typeof restoreFromVersion==='function'` at 291) |
| `restoreFromFolder(labId, folderPrefix, tree)` | async | Entry from the folder browser → `restoreReview` | yes: git-progress.js line 93 (guarded by typeof) |
| `restoreReview(labId, source, label)` | async | Preflight + review dialog + submit | no |
| `restoreShowJob(id, known)` | async | Opens the job status dialog and starts polling if active | no (only from restoreReview) |
| `restoreRenderJob(job)` | function | Renders into `#restore-job-detail` if the dialog for that job is open | no |
| `restoreStartWatch(job)` / `restoreStopWatch()` | function | 1200 ms first poll, then every 1500 ms while active | no |

---

## 6. Live configuration restore — review dialog (`restoreReview`)

1. `opDialog('restore-review-dialog', 'Replace running configuration', '<p role="status">Checking the lab, the saved version and each running node…</p>')` — opDialog's standard head (eyebrow "NODE MANAGER", × `data-op-close` aria-label "Close"), `<h2>Replace running configuration</h2>`, the status paragraph, and a trailing `<p class="form-error" role="alert">`. Opened with `showModal()` (Escape closes natively).
2. `POST /api/labs/{labId}/restore/preflight {source}`. On error the first `<p>` is replaced with `<span class="form-error" role="alert">{message}</span>`; the dialog stays open with only the × to close. Backend messages include: "Choose a saved folder to apply.", "Saved capture not found in this lab.", "Choose a saved Git version, a saved folder or a saved capture as the restore source.", "Lab not found.", "Finish the storage reset first.", and pass-through Git/manifest errors.
3. On success `dialog.innerHTML` is replaced wholesale (the NODE MANAGER head disappears):
   - Head: eyebrow **LIVE CONFIGURATION RESTORE**, × `data-op-close` (aria-label "Close").
   - `<h2>Replace running configuration</h2>`
   - "This loads the selected saved configuration onto the running device. The node is **not** rebooted or redeployed. The current configuration is backed up first."
   - `<dl class="health-grid">`: **Source** = passed label or `restoreSourceLabel(review.source)`; **Saved at** = `utcDisplay(review.source.captured_at)` or "unknown"; **Target lab** = lab name from `state.labs` or the id.
   - `<fieldset class="restore-targets"><legend>Target nodes</legend>` one `<label class="checkbox-label restore-target [disabled]">` per preflight target: `<input type="checkbox" name="restore-node" value="{name}" checked|disabled>`, `<strong>{short_name || name}</strong>`, `<small>` detail: eligible → "Junos · already matches the saved state" (`matches_saved`) or "Junos · {pending_changes} change(s) to apply" or "Junos · ready" (no `pending_changes`); ineligible → `reason` or "Not eligible". Backend reasons: "No running node in this lab matches this saved node.", "Live restore is not supported for this platform yet.", "The saved platform does not match the running node.", "The node is not currently running or discovery is stale.", "Assign NOS credentials to this node first.", "Refresh VM discovery before restoring.", "SSH probe failed: {ExceptionClassName}". Empty list → "No saved node maps to a running node in this lab."
   - `<ul class="restore-safety">`: "The current configuration is backed up first; a node whose backup fails is not changed." / "The configuration is validated (commit check) and activated with a commit that rolls back on its own if management is lost." / "Unsupported or unreachable nodes are not modified."
   - `<details class="restore-advanced"><summary>Safety options</summary>`: label "Automatic rollback if not confirmed (minutes)", `<input id="restore-confirm-minutes" type="number" min="2" max="60" value="5">`, help "After the configuration is loaded the manager reconnects to prove the node is reachable, then confirms. If it cannot reconnect in time, the node rolls back to the pre-restore state."
   - `<label id="restore-ack-label" class="checkbox-label"><input id="restore-ack" type="checkbox"> I understand the running configuration on the selected nodes will be replaced with the saved configuration.</label>`
   - `<p class="form-error" role="alert"></p>`
   - Actions: **Cancel** (`button secondary`, `data-op-close`), **Replace configuration** (`#restore-run`, `button danger`, `disabled` when no eligible target).
4. **Replace configuration** → `opTask(dialog, …)` (clears form-error, disables all enabled buttons during the call, writes thrown messages into the form-error): chosen = checked `restore-node` values; none → "Select at least one eligible node."; ack unchecked → "Acknowledge that the running configuration will be replaced."; minutes = clamp(parseInt, 2, 60), NaN → 5; `POST /api/labs/{labId}/restore {request_id, source, node_names, confirm_minutes, acknowledge: true}`. The `request_id` is generated once when the review dialog is built, so a retry after a network failure reuses it (backend idempotency). Then `dialog.close()`, `restoreShowJob(job.id, job)`, `refresh()`.
   - Backend refusals (400/409/422): "Acknowledge that the running configuration will be replaced.", ineligible nodes listed as "{name}: {reason}; …", pydantic validation errors surface as "Check the form fields and try again." (api() maps non-string `detail`).

## 7. Live configuration restore — job status dialog (`restoreShowJob` / `restoreRenderJob`)

- `opDialog('restore-job-dialog', 'Live configuration restore', '<div id="restore-job-detail"></div>')` — head eyebrow "NODE MANAGER", × close, `<h2>Live configuration restore</h2>`, trailing empty form-error.
- `dialog.onclose` → `restoreDialogJob = ''` and, if this job is being polled, `restoreStopWatch()`. The × button closes the dialog (`dialog.close()`); Escape closes it natively (same onclose path).
- Content (`#restore-job-detail`):
  - `<div class="git-job-summary">{badge(job.status, restoreJobLabels)}<p>{job.message}</p></div>`
  - `<div class="restore-targets-status">` one `<div class="restore-target-row">` per target: `{badge(t.status, restoreTargetLabels)} <strong>{short_name||name}</strong><p>{t.message}</p>` and, when `status === 'verify_mismatch'` and counts exist, `<p class="form-help">{missing_statements} desired statement(s) missing, {extra_statements} unexpected remaining.</p>`
  - `<dl class="health-grid">`: **Pre-restore backup** `{pre_backup_job_id[0..12]}` (mono) when set; **Verification backup** `{post_backup_job_id[0..12]}` when set; **Rollback timer** "{confirm_minutes || 5} min".
  - While the job is active: `<p class="form-help" role="status">You can close this window; the restore continues and its result stays in the action log.</p>`
- Polling (`restoreStartWatch`): no-op if already watching this id; first `GET /api/restore/jobs/{id}` after **1200 ms**, then every **1500 ms** while `status ∈ restoreActiveJob`; each response is rendered only when `restoreDialogJob === job.id` and `#restore-job-dialog.open`; on a terminal status → stop and `refresh()` (updates action logs / state); on any fetch error → stop silently (no message, dialog keeps the last rendered state).
- Job `status` values from backend: queued, preflight, backing_up, applying, verifying, succeeded, partial, needs_attention, failed, preflight_failed, interrupted, dismissed ("confirming" is in the UI map but the backend uses it only for targets). Target `status` values: pending, backing_up, applying, confirming, applied, applied_unverified, verified, verify_mismatch, rollback_expected, failed, ineligible, interrupted.
- Backend job messages shown verbatim include: "Restore queued.", "Checking the lab and target nodes.", "Backing up the current configuration first.", "Applying the saved configuration.", "Verifying the restored configuration.", "The lab was removed.", "The VM connection changed before the restore started.", "VM discovery is stale; refresh discovery and retry.", "None of the selected nodes are currently running; no configuration was changed.", "The pre-restore backup could not start (…); no configuration was changed.", "The pre-restore backup did not complete; no configuration was changed.", "Manager is stopping. Retry later." Target messages: "Waiting to restore.", "Node is not currently running.", "Capturing current configuration.", "Pre-restore backup failed for this node; it was not changed.", "Loading the saved configuration (commit confirmed).", "Configuration loaded; reconnecting to confirm.", "Configuration replaced and the commit confirmed.", "Commit was armed but not confirmed; the node rolls back automatically. …", "Configuration was not changed: …", "… Connectivity: …", "Configuration replaced, but the post-restore backup did not confirm it. Re-check by hand.", "Configuration replaced, but its verification capture is unavailable.", "Verification capture unreadable.", "Configuration replaced and verified against the saved desired state.", "Configuration replaced, but N desired statement(s) are missing …".

---

## 8. Status vocabulary

**Job labels (`restoreJobLabels`)**: queued "Restore queued"; preflight "Checking the lab and nodes"; backing_up "Backing up current configuration"; applying "Replacing configuration"; confirming "Confirming the commit"; verifying "Verifying the result"; succeeded "Configuration applied successfully"; partial "Some nodes restored"; needs_attention "Applied — post-check needs attention"; failed "Restore failed"; preflight_failed "Preflight failed"; interrupted "Restore interrupted"; dismissed "Restore dismissed".

**Target labels (`restoreTargetLabels`)**: pending "Waiting"; backing_up "Backing up first"; applying "Loading configuration"; confirming "Confirming commit"; applied "Applied (confirmed)"; applied_unverified "Applied — verify by hand"; verified "Applied and verified"; verify_mismatch "Applied — differences remain"; rollback_expected "Rolled back automatically"; failed "Not changed"; ineligible "Skipped"; interrupted "Interrupted".

**Badge colour classes**: `good` (succeeded, verified, applied), `running` (queued, preflight, backing_up, applying, confirming, verifying), `bad` (failed, preflight_failed, rollback_expected), `warn` (all other statuses including pending, partial, needs_attention, interrupted, dismissed, applied_unverified, verify_mismatch, ineligible). Unknown status → raw status text, escaped.

**Folder browser**: "This lab" / "This lab saves here"; "{Lab} saves here"; "Lab folder" / "Lab folder · not connected to a lab" / "Lab folder · empty until its first save"; "created on first save"; "Folder"; "Most recent save"; "Reference version set with Set baseline"; "Named milestones"; "Milestone saved with Save checkpoint"; file kinds "Save details: devices, checksums, capture time" / "Device configuration" / "File"; footer "Last save {UTC}" / "No save yet" / "as of commit {10 chars}" / "list shortened to the first 4000 files"; review details "Junos · already matches the saved state" / "Junos · N change(s) to apply" / "Junos · ready" / "Not eligible"; source labels "Git version · {hash}" / "Saved capture · {id}" / "Saved configuration" / "{repo} · {folder} (latest saved state)".

---

## 9. Element ids and data attributes

- Emitted by git-places.js: `data-git-place="{path}"` (chips, outline summaries, folder rows), `data-git-places-action="apply|new|use"`, classes `git-places-head`, `git-crumbs`, `git-places-body`, `git-outline`, `git-outline-children`, `git-leaf`, `selected`, `git-folder-icon [lab|managed] [pending]`, `git-file-icon`, `git-tag [other|pending]`, `git-listing`, `row`, `folder`, `name`, `desc`, `size`, `git-empty-folder`, `git-places-foot`, `actions`, `button primary|secondary|danger`, `form-error`, `form-help`.
- Consumed container: `#git-places-panel` (created by git-progress.js).
- Emitted by restore.js: ids `restore-review-dialog`, `restore-confirm-minutes`, `restore-ack-label`, `restore-ack`, `restore-run`, `restore-job-dialog`, `restore-job-detail`; attribute `data-op-close`; `name="restore-node"`; classes `dialog-head`, `eyebrow`, `icon-button`, `health-grid`, `restore-targets`, `restore-target [disabled]`, `checkbox-label`, `restore-safety`, `restore-advanced`, `dialog-actions`, `git-job-summary`, `restore-targets-status`, `restore-target-row`, `badge good|running|bad|warn`, `mono`, `form-help`, `form-error`.
- Related ids in git-progress.js for the focus flows: `git-repository-content`, `git-repository-refresh`, `git-binding-form`, `git-binding-id`, `git-binding-destination`, `git-exposure`, `git-exposure-label`, `git-review-before-push`, `git-folder-dialog`, `git-move-files`, `git-folder-cancel`, `git-folder-confirm`, `git-new-folder-dialog`, `git-new-folder-name`, `git-new-folder-result`, `git-new-folder-use`, `git-new-folder-move`, `git-new-folder-cancel`, `git-new-folder-confirm`, `git-switch-dialog`, `git-switch-id`, `git-switch-choose`, `git-switch-connect`, `git-connect-dialog`, `git-connect-url`, `git-connect-folder`, `git-connect-ack`, `git-connect-cancel`, `git-connect-confirm`, `git-version-dialog`, `git-version-restore`; attributes `data-git-repo-action="switch|history|update|unlink|connect"`.

## 10. API calls

- `GET /api/git/repositories/{bindingId}/tree` → `{repository:{id,label,owner,path,remote,push_url,branch,prefix,revision}, head, files:[{path,size}], truncated, saved:{latest,baseline,checkpoints: epoch seconds|null}, folders:[{id,label,prefix,lab:{id,name}|null}]}` (git-places.js line 88)
- `POST /api/labs/{labId}/restore/preflight {source}` → `{source:{type,…,captured_at,lab_name}, targets:[{name,short_name,platform,eligible,reason,requested,reachable?,matches_saved?,pending_changes?}], eligible_count}` (restore.js line 57)
- `POST /api/labs/{labId}/restore {request_id, source, node_names, confirm_minutes, acknowledge}` → job (restore.js line 99)
- `GET /api/restore/jobs/{jobId}` → `{id, lab_id, lab_name, created, finished, status, message, source, confirm_minutes, pre_backup_job_id, post_backup_job_id, targets:[{name,short_name,platform,status,message,missing_statements?,extra_statements?}]}` (restore.js lines 107, 134)
- Wiring in git-progress.js for the focus flows: `GET /api/labs/{id}/git`, `GET /api/git/repositories`, `POST /api/git/repositories/{repoId}/folders {prefix}`, `POST /api/labs/{id}/git/destination {prefix, move_files}`, `POST /api/labs/{id}/git/connect {url, prefix, acknowledge, node_names, review_before_push}`, `PUT /api/labs/{id}/git {binding_id, node_names, review_before_push}`, `GET /api/state` (via `refresh()`).

## 11. Timers, polling, persistence, keyboard

- Restore job polling: 1200 ms initial, then 1500 ms while active; stopped on dialog close, terminal status, or fetch error.
- Toast (`notify`) auto-hides after 5000 ms (app.js).
- No timers in git-places.js; the tree is fetched only on `gitPlacesShow` (tab render, select change, after actions, "Refresh status").
- Persistence: none in the browser for these files (`gitPlacesState` is in-memory; lost on reload). Backend state written: folder registration on the VM (`register-prefix`), lab `git_binding` (destination/connect), queued `git_jobs` move job, restore job in the store, events `git.folder`, `git.destination`, `git.connect`, `restore.*`.
- Keyboard: nothing custom. `<details>/<summary>` in the outline are keyboard-toggleable but the click handler's `preventDefault` means Enter/Space selects the folder instead of toggling; dialogs use native `<dialog>` Escape; the Git save menu (`git-progress.js`) has a document-level Escape handler unrelated to these files.

## 12. Microcopy a CCNA-level student may not understand

See the structured `microcopy_issues` list; highlights: "as of commit abcdef1234", "checksums", "Set baseline"/"Save checkpoint"/"Named milestones", "The lab manager fills latest folders itself", "Git version · {hash}", "Saved capture · {job id}", "commit check", "Confirming the commit"/"Applied (confirmed)"/"commit confirmed", "Preflight failed", "desired statement(s) missing … unexpected remaining", "Pre-restore backup {id}"/"Verification backup {id}", "Rollback timer", "discovery is stale"/"Refresh VM discovery", "SSH probe failed: {PythonExceptionName}", "NOS credentials", "restore-grade Junos candidate", "HTTPS clone URL", "Git account"/"GitHub login already set up on the VM", "commit name and email"/"private noreply address", "This makes one commit and pushes it", "Git history", "Git helper installation", "registered repositories", "repository root".

## 13. Redesign risks

1. The panel is fully re-rendered (`container.innerHTML = …`) on every click; handlers are attached with `element.onclick` after each draw. Any new markup must keep `data-git-place` on chips/summaries/folder rows and `data-git-places-action="new|use|apply"` on the three buttons, or clicks silently stop working.
2. Outline `<details>` open state is derived from the selection (root, selected, ancestors) and native toggling is suppressed with `preventDefault`; replacing `<details>` needs the same "ancestors open" rule.
3. Disabled-state explanations live only in `title` attributes (plus the footer right span for the "use" button). Touch users never see titles; the "New folder…" reason is title-only.
4. `tests/test_git_places_ui.js` asserts exact substrings: `data-git-places-action="use"  title="">Choose this folder` (two spaces), `aria-current="page">`, `data-git-places-action="new" disabled`, "Most recent save", "Save details: devices, checksums, capture time", "Device configuration", "shortened to the first 4000 files", "as of commit abcdef1234", "{name} saves here", `id="git-places-panel"`, `data-git-repo-action="switch|unlink|connect"`, `<option value="new-folder" selected>`. `tests/test_restore_ui.js` asserts badge classes and source labels. Both run the files as plain scripts in a `vm` context with stubbed globals (`$`, `esc`, `state`, `utcDisplay`, `crypto`, `api`, `json`, `opDialog`, `opTask`, `refresh`, `setTimeout`, `clearTimeout`), so converting to modules or renaming globals breaks them.
5. `restoreReview` error path does `dialog.querySelector('p').innerHTML = …` — assumes the first `<p>` in the dialog is the status line produced by `opDialog`.
6. `restoreRenderJob` refuses to draw unless `restoreDialogJob === job.id` and `$('restore-job-dialog').open`; the `#restore-job-detail` container must exist inside that dialog id.
7. `restoreShowJob` binds `dialog.querySelector('[data-op-close]').onclick` — depends on opDialog's head markup; `dialog.onclose` is what stops the poll, so any custom close control must call `dialog.close()`.
8. The `request_id` idempotency key is created once per review dialog; regenerating it on each click would defeat retry safety.
9. `confirm_minutes` is clamped client-side (2..60, default 5) and enforced server-side; the input is inside a collapsed `<details>` ("Safety options").
10. Footer "Last save" multiplies `tree.saved.latest` by 1000 (epoch seconds from git); "No save yet" only appears when the current lab has a registered folder in the browsed tree.
11. "Save this lab here" vs "Choose this folder" label depends on `connected = browsed registration path === binding repo path` computed in git-progress.js; the same flag decides whether `gitUseFolder` opens the move dialog or just preselects the form.
12. The Apply button requires `latest/*.jcfg` in the selected folder and `restoreFromFolder` being defined (restore.js loaded after git-places.js — order in index.html line 5 matters only for the `typeof` checks at call time).
13. CSS layout: `.git-places-body` is a 250px + 1fr grid collapsing to one column at the small breakpoint (style.css line 153); `.git-outline` and `.git-listing` cap at 420px with their own scrollbars; `.git-tag`/`.git-folder-icon` colours encode registration/managed/pending state.
14. `gitPlacesState.selected` is set by git-progress.js before re-rendering after destination/new-folder/connect so the newly chosen folder stays selected; the reset rule in `gitPlacesShow` only resets when the bindingId changes or the path vanished.
15. Restore polling stops silently on a fetch error; there is no retry and no message — a redesign that hides the dialog's last state would lose the only feedback.
16. `restoreGoodTarget`/`restoreBadTarget` are dead code; badge colours are decided inside `restoreBadge`.
