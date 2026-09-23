# Inventory: git-progress.js (Save Progress / Git repository workflow)

Source read completely: `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/git-progress.js` (320 lines, 45,526 bytes; longest line 1,347 chars).
Markup skimmed: `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/index.html` (lines 5, 48, 50, 52).
Supporting reads for behaviour semantics only: `app.js` (lines 2-18, 45, 53, 81, 92-93, 124, 180), `operations.js` (lines 5-14), `git-places.js` (lines 1-50, 84-100), `restore.js` (lines 36-52), `style.css` (lines 71-83).

Script load order in index.html (all `defer`): app.js, topology-render.js, topology.js, management.js, operations.js, diagram-editor.js, **git-progress.js**, git-places.js, restore.js, capture.js. git-progress.js calls into git-places.js and restore.js at event time only, and guards `restoreFromFolder` / `restoreFromVersion` with `typeof ... === 'function'`.

---

## 1. Module-level state and constants

| Name | Kind | Value / purpose |
|---|---|---|
| `gitActiveStates` | `Set` | `queued, capturing, exporting, pushing` — job is still running; drives polling, "running" badge, disabled Save button and menu items |
| `gitPendingStates` | `Set` | `committed, push_pending, export_pending, review_pending, interrupted` — job needs a user decision (push / retry / dismiss) |
| `gitStateLabels` | object | status → user label (see Status vocabulary) |
| `gitContexts` | `Map<labId, context>` | cached response of `GET /api/labs/{id}/git` |
| `gitLoads` | `Map<labId, Promise>` | in-flight context loads (dedupe) |
| `gitViewLab` | string | lab whose Git tab is currently rendered (skip re-render unless forced) |
| `gitViewRequest` | number | sequence counter; stale Git-tab responses are discarded |
| `gitWatch` | `{id, lab_id}` or null | the job currently being polled |
| `gitWatchTimer` | timeout handle | poll timer |
| `gitDialogJob` | string | job id shown in `#git-job-dialog` (cleared on dialog close) |
| `gitSubmitting` | boolean | a save POST is in flight |
| `gitPendingSelection` | string | registration id to preselect in `#git-binding-id` after choosing a folder / switching repository (consumed once) |

## 2. Globals defined in this file

| Name | Kind | Purpose | Called from other files |
|---|---|---|---|
| `gitActiveStates`, `gitPendingStates`, `gitStateLabels`, `gitContexts`, `gitLoads`, `gitPendingSelection`, `gitViewLab`, `gitViewRequest`, `gitWatch`, `gitWatchTimer`, `gitDialogJob`, `gitSubmitting` | const/let | see table above | no |
| `gitLabel(job)` | function | label for job status; fallback raw status, then `'No progress saved yet'` | no |
| `gitJobTime(job)` | function | `created || finished || ''` for sorting | no |
| `gitTime(value)` | function | numeric epoch seconds ×1000 → `utcDisplay` | no |
| `gitLabJobs(id, context?)` | function | merges `context.jobs` and `state.git_jobs` for this lab (jobs with no `lab_id` included), dedupes by id, sorts newest first | no |
| `gitRepository(binding)` | function | `binding.repository || {}` | no |
| `gitBindingChanged(binding, repository)` | function | true if no binding/repo, or `binding_id !== repository.id`, or `binding.revision !== repository.revision` | no |
| `gitRegisteredDestination(repo)` | function | `owner · path · remote / branch · Push to <push_url> · <prefix or 'repository root'>` joined by ` · ` | no |
| `gitRepoName(repo)` | function | last path segment of `repo.path`, else `repo.label`, else `'Repository'` | **yes: restore.js:48, git-places.js:95** |
| `gitDestination(binding)` | function | `<repoName or binding_id> › <prefix without trailing /> › latest/ · <branch>` | no |
| `gitTargetPath(job)` | function | `'latest'` for move; `checkpoints/<checkpoint>` for checkpoint; else `job.target || 'latest'` | no |
| `gitTargetLabel(job)` | function | move → `Folder move → <snapshot_path minus /latest, or 'repository root'>`; checkpoint → `checkpoints/<name>`; else `target || 'latest'` | no |
| `gitCompleteBackups(jobs, id, names)` | function | filters `state.jobs`: `lab_id===id`, `operation==='backup'`, status `succeeded` or `partial`, node count == required count, unique node names == required, every node `status==='succeeded'` and in the required set; empty when `names` empty | no |
| `gitSavePayload(values, requestId)` | function | builds `{request_id, target('latest'), checkpoint(''), push(true unless false), note(''), backup_job_id(''), replace_baseline(bool), expected_baseline(''), allow_removed(bool)}` | no |
| `gitRequestId()` | function | 32 hex chars from `crypto.getRandomValues` | no |
| `gitJobMarkup(job)` | function | job summary HTML (badge, message, Saved target, Started, Commit, Changed files) | no |
| `gitFilesDiffMarkup(files, beforeLabel, afterLabel)` | function | per-file `<details>` holding a unified diff table (`diffFileMarkup` / `diffMarkup` in `diff-view.js`: line-number gutters, add/del/context rows) | no |
| `gitLoadContext(id, force)` | async | `GET /api/labs/{id}/git`, cached in `gitContexts`, in-flight dedupe via `gitLoads` | no |
| `renderGitProgress()` | function | renders the top progress bar + Save button + menu gating; starts watch for an active job | **yes: app.js:53 (`render()`), guarded by typeof** |
| `gitOpenRepository()` | function | `showTab('git')` and closes `#extra-views` | no |
| `gitShowRepository(force)` | async | loads context + catalog and renders the Git tab | **yes: app.js:93 (`showTab('git')`), guarded by typeof** |
| `gitRenderRepository(id, context, catalog)` | function | builds the whole Git tab HTML and wires it | no |
| `gitLabName(id)` | function | lab name or `'This lab'` | no |
| `gitApplyDestination(id, prefix, moveFiles, labName)` | async | `POST /api/labs/{id}/git/destination` | no |
| `gitUseFolder(id, path, model, tree)` | async | "Save this lab here" (onUse callback for git-places) | no (passed as callback) |
| `gitNewFolder(id, parent, model, tree)` | async | "New folder" dialog (onNew callback for git-places) | no (passed as callback) |
| `gitSwitchRepository(id)` | async | "Use a different repository" dialog | no |
| `gitSuggestedFolder(name)` | function | lab name → safe folder name (non `[A-Za-z0-9_.-]` → `-`, strip leading non-alnum/underscore, strip trailing `-`, max 60, fallback `'lab'`) | no |
| `gitConnectByUrl(id)` | async | "Connect a repository by URL" dialog | no |
| `gitSubmitSave(id, values, requestId)` | async | `POST /api/labs/{id}/git/save` with idempotent request id; sessionStorage dedupe | no |
| `gitSaveProgress()` | async | Save button handler (target latest, push true) | no |
| `gitSaveOptions(target, id)` | async | Save locally / Save checkpoint / Set baseline dialog | no |
| `gitRememberJob(job)` | function | upserts job into `gitContexts[lab].jobs` and `state.git_jobs` (front of list) | no |
| `gitShowJob(id, known)` | async | opens `#git-job-dialog` ("Lab progress save"); fetches `GET /api/git/jobs/{id}` when not supplied | no |
| `gitRenderJob(job)` | function | fills job dialog detail + action buttons | no |
| `gitReviewJob(job)` | async | "Review this save" diff dialog | no |
| `gitStartWatch(job)` | function | polls `GET /api/git/jobs/{id}` | no |
| `gitDismissJob(job)` | async | "Keep this snapshot only?" dialog | no |
| `gitPushPending(id)` | async | "Push saved progress" menu action | no |
| `gitUpdateRemote(id)` | async | "Update from remote" dialog | no |
| `gitUnlink(id)` | async | "Disconnect this repository?" dialog | no |
| `gitHistory(id)` | async | "Lab versions and Git history" dialog | no |
| `gitOpenCommit(id, commit, versions)` | async | resolves a commit to a snapshot folder, or asks | no |
| `gitViewVersion(id, version)` | async | "Saved configuration version" dialog (view / compare / download / apply) | no |
| `gitRunAction(action, id)` | function | dispatcher for `data-git-action` and `data-git-repo-action` | no |

## 3. Globals consumed (defined elsewhere)

From `app.js`: `$`, `esc`, `state` (`labs`, `jobs`, `platforms`, `git_jobs`, `operations`), `activeId`, `tab`, `current()`, `busy()`, `notify()`, `api()`, `json()`, `refresh()`, `selectLab()`, `platformLabel()`, `utcDisplay()`, `showTab()`, `attachmentName()`.
From `operations.js`: `opDialog(id,title,body)`, `opTask(dialog,fn)`.
From `git-places.js`: `gitPlacesState`, `gitPlacesShow()`, `gitLabFolder()`, `gitDestinationPreview()`, `gitFolderPath()`.
From `restore.js` (optional, typeof-guarded): `restoreFromFolder(labId, prefix, tree)`, `restoreFromVersion(labId, source, label)`.
Browser: `crypto.getRandomValues`, `sessionStorage`, `URL.createObjectURL/revokeObjectURL`, `document`, `setTimeout/clearTimeout`.

Semantics that shape behaviour:
- `api(path)` prefixes `/api`; on non-OK throws `Error(detail)` or `'Check the form fields and try again.'` (or `'Request failed'` if body not JSON).
- `opDialog(id,title,body)` creates/reuses a `<dialog id=… class="operations-dialog">`, sets innerHTML to: header (`NODE MANAGER` eyebrow + `×` close button `data-op-close` aria-label "Close"), `<h2>{title}</h2>`, body, then a trailing `<p class="form-error" role="alert"></p>`; calls `showModal()` if not open.
- `opTask(dialog, fn)` clears the dialog's `.form-error`, disables every enabled button in the dialog while `fn` runs, and on error writes `e.message` to `.form-error` (or `notify(e.message)` toast when `dialog` is null). This is the universal error path in this file.
- `notify(message)` = toast `#toast` for 5 s.
- `busy()` = any `state.jobs`/`state.operations` job queued/running OR any `state.git_jobs` in an active git state.
- `refresh()` = `GET /api/state` → `render()` → `renderGitProgress()`. `app.js:180` runs `refresh()` every **4000 ms**.
- `utcDisplay()` → `YYYY-MM-DD HH:MM:SS UTC` or `'Time unavailable'`.
- `selectLab(id)` sets `sessionStorage['activeLab']`, resets tab to topology and re-renders.

## 4. Element ids / selectors referenced

**Static (index.html):** `git-progress-bar`, `git-open-settings`, `git-destination`, `git-progress-status`, `git-save-progress`, `git-save-menu` (with `[data-git-action]` buttons: local, checkpoint, baseline, history, load, push, update, settings), `extra-views`, `git-view`, `git-repository-refresh`, `git-repository-content`.

**Created by gitRenderRepository:** `git-places-panel`, `git-binding-form`, `git-binding-id`, `git-binding-destination`, `git-review-before-push`, `git-exposure-label`, `git-exposure`, `git-saves-list`; inputs `name="git-node"`; buttons `[data-git-repo-action]` (switch, history, update, unlink, connect) and `[data-git-job]`.

**Dialog ids (opDialog):** `git-folder-dialog` (`git-move-files`, `git-folder-cancel`, `git-folder-confirm`), `git-new-folder-dialog` (`git-new-folder-name`, `git-new-folder-result`, `git-new-folder-use`, `git-new-folder-move`, `git-new-folder-cancel`, `git-new-folder-confirm`), `git-switch-dialog` (`git-switch-id`, `git-switch-choose`, `git-switch-connect`), `git-connect-dialog` (`git-connect-url`, `git-connect-folder`, `git-connect-ack`, `git-connect-cancel`, `git-connect-confirm`), `git-save-options` (`git-baseline-job`, `git-replace-baseline`, `git-checkpoint-name`, `git-save-note`, `git-save-push`, `git-allow-removed`, `git-save-cancel`, `git-save-confirm`), `git-job-dialog` (`git-job-detail`, `git-job-actions`, `[data-git-job-action]`), `git-diff-dialog` (`git-review-files`, `git-review-push`), `git-dismiss-dialog` (`git-dismiss-cancel`, `git-dismiss-confirm`), `git-pending-dialog` (`[data-git-pending]`), `git-update-dialog` (`git-update-confirm`), `git-unlink-dialog` (`git-unlink-cancel`, `git-unlink-confirm`), `git-history-dialog` (`[data-git-version]`, `[data-git-commit]`), `git-commit-dialog` (`git-commit-path`, `git-commit-view`), `git-version-dialog` (`git-version-restore`, `git-version-compare`, `git-version-download`).

**Cross-module selectors:** `.job[data-job]` (`<details>` elements rendered by app.js:81 in the Backup history view) for the "View configuration capture" hand-off; `.form-error` inside `#git-job-dialog` (appended by opDialog) for polling errors.

## 5. API calls (all relative to `/api`)

| Method | Path | Body | Called from |
|---|---|---|---|
| GET | `/labs/{id}/git` | — | `gitLoadContext` (Save button, all dialogs, Git tab) |
| GET | `/git/repositories` | — | `gitShowRepository`, `gitSwitchRepository` |
| PUT | `/labs/{id}/git` | `{binding_id, node_names[], review_before_push}` | binding form submit |
| POST | `/labs/{id}/git/destination` | `{prefix, move_files}` | `gitApplyDestination` (Save here / New folder + use) |
| POST | `/git/repositories/{repoId}/folders` | `{prefix}` | `gitUseFolder` (not-connected path), `gitNewFolder` (not connected or "use" unchecked) |
| POST | `/labs/{id}/git/connect` | `{url, prefix, acknowledge:true, node_names[], review_before_push}` | `gitConnectByUrl` |
| POST | `/labs/{id}/git/save` | `gitSavePayload(...)` | `gitSubmitSave` |
| GET | `/git/jobs/{jobId}` | — | `gitShowJob` (when job not supplied), `gitStartWatch` poll |
| POST | `/git/jobs/{jobId}/retry` | `{push: true|false}` | job dialog Push / Retry buttons, review dialog Push |
| POST | `/git/jobs/{jobId}/dismiss` | `{acknowledge:true}` | `gitDismissJob` |
| POST | `/labs/{id}/git/compare` | `{job_id}` or `{commit, path}` | `gitReviewJob`, version dialog Compare |
| POST | `/labs/{id}/git/update` | `{}` | `gitUpdateRemote` |
| POST | `/labs/{id}/git/unlink` | `{}` | `gitUnlink` |
| GET | `/labs/{id}/git/history` | — | `gitHistory` |
| POST | `/labs/{id}/git/version` | `{commit, path}` | `gitViewVersion` |
| POST | `/labs/{id}/git/version/download` | `{commit, path}` (raw `api` call, response as blob) | version dialog Download |
| GET | `/git/repositories/{bindingId}/tree` | — | inside `gitPlacesShow` (git-places.js), triggered by `showPlaces` here |
| GET | `/state` | — | `refresh()` (app.js), called after every mutation here |

State fields read from `/api/state`: `state.labs[].id/name/git_binding/git_status`, `state.git_jobs[]` (`id, lab_id, status, message, created, finished, commit, target, checkpoint, snapshot_path, changed_files, backup_job_id`), `state.jobs[]` (`operation, status, nodes[].name/status, created, id`), `state.platforms`.
Context fields (`/labs/{id}/git`): `binding` (`binding_id, revision, node_names[], review_before_push, repository{id, path, label, owner, branch, remote, push_url, prefix, revision}`), `jobs[]`, `supported_nodes[]` (`name, short_name, platform`), `unsupported_nodes[]`, `repository_status` (`problem, baseline_revision`).
Catalog (`/git/repositories`): `repositories[]` (`id, path, label, prefix, owner, branch, remote, push_url, revision`).

## 6. Timers, polling, storage, keyboard

- **Job polling** (`gitStartWatch`): first `GET /git/jobs/{id}` after **1000 ms**, then every **1500 ms** while status is in `gitActiveStates`. On completion: `refresh()`, and if the Git tab is open for that lab, `gitShowRepository(true)`. On fetch error: watch dropped; if the job dialog for that job is open its `.form-error` shows `"<error> Reopen this save to check its current state."`
- **Watch auto-start**: `renderGitProgress()` (runs on every `render()`, i.e. every 4 s via app.js `setInterval(refresh, 4000)` and on lab selection) starts a watch when the current lab has an active job and none is watched. A watch for another lab is cancelled on lab switch unless `#git-job-dialog` is open.
- **Blob URL** revoked 1000 ms after download click.
- **sessionStorage key** `git-save-request:<labId>`: only on the plain "Save progress" button path (no `requestId` argument). Before POST, if a stored request exists whose payload (ignoring `request_id`) equals the new one, the stored `request_id` is reused so a lost response does not capture twice; key removed after a successful POST. Dialog-driven saves generate their `request_id` when the dialog opens and skip sessionStorage.
- **sessionStorage `activeLab`** is written indirectly through `selectLab()` (View configuration capture).
- **Keyboard**: document-level `keydown` — `Escape` closes `#git-save-menu`. Native `<dialog>` Escape closes every opDialog (browser default). `<pre tabindex="0">` blocks in diff/version dialogs are keyboard-scrollable.
- **Outside click**: document-level `click` closes `#git-save-menu` when the click is outside it.

---

## 7. Capabilities (every user-facing control and rendered information)

### 7.1 Top progress bar (`#git-progress-bar`, aria-label "Save lab progress") — rendered by `renderGitProgress()`

| id | Label / text | Trigger | Behaviour | Gating |
|---|---|---|---|---|
| git.bar | section | automatic on every `render()` | `hidden` when no current lab; when no lab also clears the poll timer and `gitWatch` | hidden = `!current()` |
| git.destination-link | `#git-open-settings` text-button, title "Git repository settings", containing `<strong id="git-destination">` | click | `gitOpenRepository()`: `showTab('git')`, closes `#extra-views` "More" menu | always enabled |
| git.destination-text | `#git-destination` | automatic | binding → `gitDestination(binding)` e.g. `repo › folder › latest/ · main`; else `Connect a repository to save your lab progress`. Binding source: `gitContexts[lab].binding` or `lab.git_binding` from state | — |
| git.progress-status | `#git-progress-status` (`role="status"`) | automatic | last job (`gitLabJobs(lab)[0]` or `lab.git_status`) → `<label> · <commit first 10> · <utc created>` (empty parts dropped); no job → `Capture configurations, commit and push in one step.` | — |
| git.save-progress | `#git-save-progress` primary button; text `Save progress` (binding) / `Connect Git repository` (no binding); title `Capture the configured Git devices, commit and push to <destination>` / `Choose a registered VM repository` | click → `opTask(null, gitSaveProgress)` | loads context (cached); no binding → opens Git tab; else `gitSubmitSave(id,{target:'latest',push:true})` → POST save → opens job dialog → `refresh()`. Errors → toast | `disabled = gitSubmitting || activeJob || (binding && busy())` |
| git.save-menu | `#git-save-menu` `<details>`; summary `▾` aria-label "More save progress actions" | click summary | opens dropdown `.git-save-options`; closes on outside click, Escape, or when any action runs | `hidden = !binding`; each item `disabled = (gitSubmitting||activeJob) && action not in {history, load, settings}` |
| git.menu.local | `Save locally` | `data-git-action="local"` | `gitSaveOptions('local')` | see menu gating |
| git.menu.checkpoint | `Save checkpoint…` | `data-git-action="checkpoint"` | `gitSaveOptions('checkpoint')` | see menu gating |
| git.menu.baseline | `Set baseline…` | `data-git-action="baseline"` | `gitSaveOptions('baseline')` | see menu gating |
| git.menu.history | `View changes / History` | `data-git-action="history"` | `gitHistory(id)` | never disabled by activity |
| git.menu.load | `Load version…` | `data-git-action="load"` | `gitHistory(id)` (identical to History) | never disabled by activity |
| git.menu.push | `Push saved progress` | `data-git-action="push"` | `gitPushPending(id)` | see menu gating |
| git.menu.update | `Update from remote` | `data-git-action="update"` | `gitUpdateRemote(id)` | see menu gating |
| git.menu.settings | `Git repository settings` | `data-git-action="settings"` | `gitOpenRepository()` | never disabled by activity |

All menu actions go through `gitRunAction` → `opTask(null, …)` so errors surface as toasts. If context has no binding, `gitSaveOptions` redirects to the Git tab.

### 7.2 Git repository tab (`#git-view`) — `gitShowRepository` / `gitRenderRepository`

| id | Label / text | Trigger | Behaviour |
|---|---|---|---|
| git.tab | nav button `Git repository` (`data-tab="git"`, app.js) | click | `showTab('git')` → `gitShowRepository()` (skips if already rendered for this lab and not forced) |
| git.tab.heading | `Git repository` / `Choose where this lab saves its progress. Git authentication belongs to the repository owner on the VM.` | static | — |
| git.refresh-status | `#git-repository-refresh` `Refresh status` | click | `gitShowRepository(true)` (force reload context + catalog) |
| git.tab.loading | `Reading registered repositories and saved progress…` (`role="status"`) | automatic | shown while loading |
| git.tab.error | `<error message>` (`.form-error role="alert"`) + `Check the VM connection and Git helper installation, then choose Refresh status.` | automatic | on load failure (only if request still current) |
| git.status-problem | `repository_status.problem` in `.op-notice` (`role="status"`) | automatic | shown at top when backend reports a problem |
| git.connected-card | eyebrow `CONNECTED REPOSITORY`, h3 repo name, optional `Verified push destination: <push_url>`, `Branch <b> · VM account <owner> · <path>`, destination line `<lab> saves to <repo> › <prefix> › latest/`, `Save progress includes <N> configured devices. Scheduled backup selection is independent.` | automatic when binding | N = `binding.node_names.length` (or all supported if none) |
| git.card.switch | `Use a different repository…` (`data-git-repo-action="switch"`) | click | `gitSwitchRepository` dialog |
| git.card.history | `View changes / History` (`data-git-repo-action="history"`) | click | `gitHistory` |
| git.card.update | `Update from remote` (`data-git-repo-action="update"`) | click | `gitUpdateRemote` |
| git.card.unlink | `Disconnect` (`data-git-repo-action="unlink"`) | click | `gitUnlink` |
| git.card.help | `Connected the wrong repository? Choose **Use a different repository**. Nothing is deleted from either repository, and files already saved stay where they are.` | static | — |
| git.places | section `Where this lab lives` (aria-label same) with intro text: connected → `The folders of the connected repository, as they are in Git right now. Select a folder and choose **Save this lab here** to move this lab, or create a new folder.`; not connected → `The folders of the selected repository. Choose a folder for this lab, or create a new one, then confirm the connection below.` | automatic when `repositories.length || binding` | `#git-places-panel` filled by `showPlaces(bindingId)` |
| git.places.empty | `Choose a repository folder above to see what is in it.` | automatic | when no repository selected in `#git-binding-id` and no binding |
| git.places.panel | folder browser (git-places.js) | automatic | `gitPlacesShow(panel, labId, bindingId, {current: binding.binding_id, connected: selected repo path === bound repo path, onUse: gitUseFolder, onNew: gitNewFolder, onApply: restoreFromFolder (if defined)})`; re-runs whenever `#git-binding-id` changes |
| git.binding-form | `#git-binding-form` h3 `Devices and settings` (bound) / `Connect this lab to Git` (unbound) | rendered when catalog has ≥1 repository | — |
| git.binding.select | label `Repository and folder`, `#git-binding-id` `<select required>`; placeholder option `Choose a repository folder` only when nothing is preselected; options `<repo> › <prefix or 'repository root'> · <owner> · <branch>` | change | updates `#git-binding-destination` (`gitRegisteredDestination`), shows/hides exposure checkbox (`gitBindingChanged`), unchecks exposure, re-renders folder browser for that repository; preselect = `gitPendingSelection` (if in catalog) else current `binding_id` |
| git.binding.destination | `#git-binding-destination` `.op-path` | automatic | `owner · path · remote / branch · Push to <push_url> · <prefix or 'repository root'>` |
| git.binding.connect-inline | `Not the repository you want? [Connect a repository by its URL]` (`.text-button data-git-repo-action="connect"`) | click | `gitConnectByUrl` |
| git.binding.devices | fieldset legend `Devices included in every progress save`; one checkbox per `supported_nodes` (`name="git-node"`, label `short_name` + small `platformLabel(platform)`), checked if in `binding.node_names` (or all when unbound); else `No supported configuration devices in this lab.` | change | collected on submit |
| git.binding.excluded | `Unsupported devices are excluded: a, b, c.` | automatic | when `unsupported_nodes` non-empty |
| git.binding.offline-note | `An offline included device makes the capture incomplete. Its previous configuration is never silently substituted.` | static | — |
| git.binding.review | `#git-review-before-push` checkbox `Review changes before pushing` | change | initial = `binding.review_before_push` |
| git.binding.exposure | `#git-exposure-label`/`#git-exposure` checkbox `I understand that full device configurations, including any secrets they contain, will be committed and pushed to this repository.` | change | `hidden` and not required unless the selected repository differs from the current binding (id or revision); always unchecked on repository change |
| git.binding.account-note | `Git runs as the registered VM account using its existing Git login and commit identity. Configure that login on the VM outside this application.` | static | — |
| git.binding.submit | `Save repository settings` (bound) / `Connect repository` (unbound), `type=submit` | submit → `opTask(form, …)` | validations: no device checked → `Select at least one supported device for progress saves.`; binding changed and exposure unchecked → `Acknowledge exporting full configurations to the selected repository.`; then `PUT /labs/{id}/git`; `gitShowRepository(true)`; `refresh()`; toast `Git repository connected. Save progress is ready.` Errors → form's `.form-error` | `disabled` when no supported nodes; buttons in form disabled while running |
| git.blank-state | `No repository connected to this VM yet` / `Paste the HTTPS URL of your GitHub repository. The manager clones it on the VM with the GitHub login already set up there, creates this lab's folder and connects it.` | rendered when catalog is empty | — |
| git.blank.connect | `Connect a repository by URL` primary (`data-git-repo-action="connect"`) | click | `gitConnectByUrl` |
| git.blank.wizard | `<details>` summary `Prefer the terminal wizard?` → `From the release source directory on the VM, run guided setup as your ordinary account, without sudo:` `bash deploy/setup-git.sh` `The wizard handles checkout, Git login and registration. Refresh status after setup.` | click summary | static info |
| git.saves-section | h3 `Progress saves`, `Every save links to its original configuration capture. Git history contains committed versions.` | static | — |
| git.saves.list | `#git-saves-list` buttons `.git-saved-job` (`data-git-job`): `<strong>label</strong><span>utc created · target label · commit10</span>`; else `No Git progress saves yet.` | click | `opTask(null, gitShowJob(jobId))` → fetches job and opens job dialog |

### 7.3 Folder actions from "Where this lab lives" (callbacks supplied to git-places.js)

| id | Dialog / text | Behaviour |
|---|---|---|
| git.folder.use (not connected to that repo) | no dialog | uses the folder's existing registration or `POST /git/repositories/{repo}/folders {prefix}`; sets `gitPendingSelection`; `gitShowRepository(true)`; toast `Folder chosen: <path or 'the repository root'>. Confirm the devices below to connect <lab>.`; smooth-scrolls to `#git-binding-form` |
| git.folder.use (connected) | `#git-folder-dialog` **Save this lab here?** — `<lab> will keep its progress in <repo › path> from now on.`; if current folder has N files: checkbox `#git-move-files` (checked) `Also move the N files already saved under <from> into the new folder. This makes one commit and pushes it.`; else `Nothing is saved under the current folder yet, so there is nothing to move.`; `Earlier versions stay in Git history either way. Scheduled backups and the device selection do not change.`; buttons `Cancel`, `Save here` | `Save here` → `gitApplyDestination`: `POST /labs/{id}/git/destination {prefix, move_files}`; clears cached context; `gitPlacesState.selected=prefix`; `refresh()`; `gitShowRepository(true)`; if response has `job` → remember + open job dialog; toast `<lab> now saves to <prefix or 'the repository root'>.`; dialog closes |
| git.folder.new | `#git-new-folder-dialog` **New folder** — path line `<repo> › <parent> › new folder`; label `Folder name`, input `#git-new-folder-name` (maxlength 360, placeholder `Week-04/BGP/Final-State`); help `Letters, numbers, dashes, dots and underscores. Use / to create nested folders in one step. Git shows a folder once something is saved in it.`; live preview `Result <repo> / <full path>` (hidden until valid); connected → checkbox `#git-new-folder-use` (checked) `Save <lab> here from now on` and, if files exist, `#git-new-folder-move` (checked) `Also move the N files already saved under <from> into it. This makes one commit and pushes it.`; not connected → `The folder is prepared for this lab. Confirm the devices below afterwards to connect it.`; buttons `Cancel`, `Create folder` | `Create folder` → `gitFolderPath(name)` (throws `Enter a folder name.` or `Use letters, numbers, dashes, dots or underscores for the folder name, without slashes.`); prefix = parent + '/' + nested; if connected and "use" checked → `gitApplyDestination(prefix, move checked)`; else `POST /git/repositories/{repo}/folders {prefix}`, close, select the folder, set `gitPendingSelection` when not connected, `gitShowRepository(true)`, toast `Folder <prefix> is ready for a lab.` |
| git.folder.apply | (button rendered by git-places.js) | `restoreFromFolder(labId, path, tree)` — only wired when restore.js is loaded |

### 7.4 Repository connection dialogs

| id | Dialog | Fields / text | Behaviour |
|---|---|---|---|
| git.switch | `#git-switch-dialog` **Use a different repository** | `Pick another repository already set up on this VM, or connect a new one by its URL. Files already saved in the current repository are not deleted.`; if other repositories: label `Repositories on this VM`, `#git-switch-id` select (`<repo> › <prefix or 'repository root'> · <branch>`, excludes current binding), button `Choose this repository`; else `No other repository is set up on this VM yet.`; h3 `Connect a repository by URL`, `For a repository that is not on this VM yet. You need its HTTPS clone URL and the GitHub login already set up on the VM.`, button `Connect by URL…` | Choose → `gitPendingSelection`, close, `gitShowRepository(true)`, toast `Choose the folder and confirm the devices below.`, scroll to form. Connect by URL → close, `gitConnectByUrl` |
| git.connect-url | `#git-connect-dialog` **Connect a repository by URL** | `Paste the HTTPS clone URL from GitHub (Code › HTTPS). The manager clones it on the VM as its Git account, using the GitHub login already set up there. It never asks for a token or password.`; label `Repository URL`, `#git-connect-url` (placeholder `https://github.com/you/your-lab-repo`); label `Folder for this lab optional`, `#git-connect-folder` (default `gitSuggestedFolder(labName)`, maxlength 180); `One repository can hold several labs, each in its own folder. Clear it to save at the repository root of a single-lab repository.`; `#git-connect-ack` checkbox `I understand that full device configurations, including any secrets they contain, will be committed and pushed to this repository.`; `If no commit name and email are set on the VM yet, the GitHub account's name and its private noreply address are used.`; buttons `Cancel`, `Connect repository` | validation: URL must match `^https://<host>/<path>` else `Paste the HTTPS clone URL, for example https://github.com/you/your-lab-repo.`; folder normalised by `gitFolderPath` (may throw); ack unchecked → `Acknowledge exporting full configurations to this repository.`; button text becomes `Connecting… this can take a minute` during POST; `POST /labs/{id}/git/connect`; close; clear context; select folder; `refresh()`; `gitShowRepository(true)`; toast `<lab> is connected to <repo>.`; button text restored in `finally` |
| git.unlink | `#git-unlink-dialog` **Disconnect this repository?** | `Remove this lab's repository connection. Existing configuration backups and Git files remain available. Resolve or dismiss any pending saves before disconnecting.`; buttons `Cancel`, `Disconnect repository` | `POST /labs/{id}/git/unlink {}`; close; clear context; `refresh()`; `gitShowRepository(true)` (no toast) |
| git.update-remote | `#git-update-dialog` **Update from remote** | `Fetch the registered remote and fast-forward the current branch when the working repository is clean and its history allows it.` `Your running devices are unchanged. A conflict keeps the existing checkout and reports what needs attention.`; button `Update from remote` (no Cancel button; × header close only) | `POST /labs/{id}/git/update {}`; close; force reload context; if Git tab active for this lab → `gitShowRepository(true)`; toast `result.message` or `Repository updated from remote.` |

### 7.5 Save dialogs

| id | Dialog | Fields / text | Behaviour |
|---|---|---|---|
| git.save.options | `#git-save-options`, title `Set baseline` / `Save checkpoint` / `Save locally` (`Save progress` for any other target) | path line `gitDestination(binding)`. **Baseline**: `Choose one complete recorded capture for the baseline. This does not recapture devices or apply configurations.`; label `Saved configuration capture`, `#git-baseline-job` select (`Choose a complete backup` + one option per complete backup `<utc> · <n> devices · <jobId>`); if none: `.op-notice` `No complete backup covers the configured devices. Save progress first, then set the baseline.`; `Older backups retain their recorded provenance. A successful capture alone does not verify restore compatibility.`; if `repository_status.baseline_revision` set: `#git-replace-baseline` checkbox `Replace the existing baseline with this selected capture. The previous version remains in Git history.` **Local**: `Capture and commit to the VM repository without pushing.` **Checkpoint/other**: `Capture the configured devices and preserve this milestone under checkpoints/ as well as latest/.` **Checkpoint only**: label `Checkpoint name`, `#git-checkpoint-name` (maxlength 100, placeholder `bgp-peering-working`, pattern `[A-Za-z0-9][A-Za-z0-9_-]*`), help `Use letters, numbers, underscores or hyphens. Checkpoint names cannot be reused.` **All**: label `Note optional`, `#git-save-note` (maxlength 300, placeholder `What changed in this experiment?`). **Not local**: `#git-save-push` checkbox (checked) `Push after saving` + ` (review preference still applies)` when `binding.review_before_push`. **All**: `<details>` `Changed device scope` → `#git-allow-removed` checkbox `Allow this save to remove previously managed config files for devices no longer in the configured scope. Their older versions remain in Git history.` Buttons `Cancel`, `<title>` (`#git-save-confirm`, `disabled` for baseline when no complete backup exists) | Confirm validations: checkpoint name must match `^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$` else `Enter a checkpoint name using letters, numbers, underscores or hyphens.`; baseline without selection → `Choose a complete saved capture.`; existing baseline and replace unchecked → `Confirm replacing the existing baseline.`; payload: `target` (`latest` for local, else target), `checkpoint`, `push` (`false` for local, else checkbox), `note`, `backup_job_id`, `replace_baseline` (baseline && existing), `expected_baseline` (baseline revision), `allow_removed`; `gitSubmitSave(id, values, requestId)` → close dialog. `gitSubmitSave` opens the job dialog and refreshes |
| git.save.submit | (internal) | — | guard `gitSubmitting`; `renderGitProgress()` before/after; sessionStorage dedupe for button path; `POST /labs/{id}/git/save`; `gitRememberJob`; `gitShowJob`; `refresh()` |

### 7.6 Job dialog (`#git-job-dialog` **Lab progress save**) — `gitShowJob` / `gitRenderJob`

| id | Rendered item | Rule |
|---|---|---|
| git.job.badge | `.badge` + label | class `running` (active states), `good` (`synced`, `unchanged`), `bad` (`failed`, `capture_incomplete`), `warn` (all other, i.e. pending/dismissed/unknown) |
| git.job.message | `job.message` | shown as-is (pre-wrap) |
| git.job.target | dt `Saved target` | `gitTargetLabel(job)` |
| git.job.started | dt `Started` | `utcDisplay(job.created)` |
| git.job.commit | dt `Commit` (mono) | only when `job.commit` |
| git.job.changed | dt `Changed files` | only when `changed_files` defined (array length or number) |
| git.job.empty | `No Git saves yet. Save progress captures every device selected in Git repository settings.` | when `job` falsy (not reachable through current callers) |
| git.job.view-capture | `View configuration capture` | only when `job.backup_job_id`; closes dialog, `selectLab(job.lab_id)` (resets tab, stores `activeLab`), `showTab('backups')`, finds `.job[data-job="<backup_job_id>"]`, sets `open=true`, smooth-scrolls it into view |
| git.job.review | `Review changes` | only when `job.commit`; `gitReviewJob(job)` |
| git.job.push | `Push saved progress` (has commit) / `Retry export and push` (no commit), primary | only when status in `gitPendingStates`; `POST /git/jobs/{id}/retry {push:true}`; remember result; re-open job dialog with result; `refresh()` |
| git.job.retry-local | `Retry export locally` | only when pending **and** no commit; `POST /git/jobs/{id}/retry {push:false}` |
| git.job.dismiss | `Keep snapshot only` | only when pending; `gitDismissJob(job)` |
| git.job.active-hint | `You can close this window. The save continues and its result remains in Git repository settings.` (`role="status"`) | only when status active |
| git.job.poll | automatic | active job → `gitStartWatch(job)`; dialog contents re-rendered on each poll; `onclose` clears `gitDialogJob` so later polls do not touch a closed dialog |
| git.job.poll-error | `.form-error` in dialog: `<error> Reopen this save to check its current state.` | on poll failure while this dialog is open |

### 7.7 Review / diff dialogs (`#git-diff-dialog`)

| id | Title / text | Behaviour |
|---|---|---|
| git.review | **Review this save** — `Changes introduced by commit <hash>. Full configuration files can contain device secrets.` + diff (`Before this save` / `Saved configuration`); buttons `View complete saved version`, and `Push saved progress` (primary) when job pending | `POST /labs/{lab}/git/compare {job_id}`; View → `gitViewVersion(lab, {commit, path: gitTargetPath(job)})`; Push → `POST /git/jobs/{id}/retry {push:true}`, close, open job dialog, `refresh()` |
| git.compare-latest | **Changes compared with latest** — `<path> at <commit> compared with the latest saved configuration files.` + diff (`Selected version` / `Latest saved version`) | from version dialog `Compare with latest`: `POST /labs/{id}/git/compare {commit, path}` |
| git.diff.file | per file `<details>` summary `<name>` + badge `<status or 'changed'>`; two columns with `<pre tabindex=0>`; missing side shows `File absent` | — |
| git.diff.empty | `No file differences in this version.` | when `files` empty |

### 7.8 Dismiss / pending / history / version dialogs

| id | Dialog | Text / fields | Behaviour |
|---|---|---|---|
| git.dismiss | `#git-dismiss-dialog` **Keep this snapshot only?** | `Keep the configuration backup and any existing Git commits. Stop tracking this pending export or push so the lab can be disconnected or removed.` `This does not delete files or undo a commit. Any local commit remains in the repository and may be included in a later push.` `<label> · <jobId>`; buttons `Cancel`, `Keep snapshot only` | `POST /git/jobs/{id}/dismiss {acknowledge:true}`; remember; close; re-open job dialog with result; `refresh()`; if Git tab active → `gitShowRepository(true)` |
| git.push-pending | menu `Push saved progress` | none pending → toast `No saved progress is waiting to be pushed.`; exactly one → job dialog; several → `#git-pending-dialog` **Saved progress awaiting a push** listing buttons `<label> · <utc created>` | each button → `gitShowJob(id)` (fetch) |
| git.history | `#git-history-dialog` **Lab versions and Git history** | `View, download or apply saved configuration versions. Open a Junos version to **apply it to the running lab**; the current configuration is backed up first and the node is not rebooted.`; h3 `Saved versions`, help `Each saved state shows its folder, so you can tell base, working, final or broken apart — not just “latest”.`; version buttons `<strong>label|name|path</strong><small>path[ · this lab] · commit10</small>`; empty → `No baseline, latest capture or checkpoints saved yet.`; h3 `Commits`; commit buttons `<strong>message</strong><small>commit10 · time</small>`; empty → `No progress commits available.` | `GET /labs/{id}/git/history`; version → `gitViewVersion`; commit → `gitOpenCommit` |
| git.open-commit | (no dialog when resolvable) | finds a known save job with that commit and target `latest`/`baseline`/`checkpoint`, preferring one with non-empty `changed_files`, else the `latest` one → `gitViewVersion` with that job's path | — |
| git.commit-folder | `#git-commit-dialog` **Choose a saved folder** | `<commit message or 'Historical configuration version'>`, `<commit hash>`, label `Snapshot folder at this commit`, `#git-commit-path` select (`latest`, `baseline`, then every history version path, deduped), help `A folder must already exist at this commit. Choose another folder if this version predates it.`, button `View saved files` | `gitViewVersion(id, {commit, path})` |
| git.version | `#git-version-dialog` **Saved configuration version** | path line `<label> · <commit>`; actions: `Apply to running lab…` (danger; only when `data.restore_supported` and `restoreFromVersion` exists), `Compare with latest`, `Download version (ZIP)` (primary); note: supported → `This version has a restore-grade Junos candidate. **Apply to running lab** loads it onto the running node (no reboot); the current configuration is backed up first.`; unsupported → `View or download only — this saved version predates live restore support, so it cannot be applied to a running device.`; `<details>` `Capture manifest` with pretty JSON; one `<details>` per file (`name`, `<pre>` text); empty → `No configuration files in this version.` | `POST /labs/{id}/git/version {commit,path}`; Apply → close, `restoreFromVersion(id,{type:'git',commit,path}, label)`; Compare → see git.compare-latest; Download → `POST /labs/{id}/git/version/download` → blob → `<a download>` named from `Content-Disposition` or `lab-version.zip` |

---

## 8. Status vocabulary (every status string)

| Term (raw status) | Shown as | Where |
|---|---|---|
| `queued` | `Waiting to save` (badge `running`) | bar status, job dialog, saves list |
| `capturing` | `Capturing configurations` (running) | same |
| `exporting` | `Saving to repository` (running) | same |
| `pushing` | `Pushing to remote` (running) | same |
| `synced` | `Saved to Git` (good) | same |
| `committed` | `Saved on VM · not pushed` (warn; pending) | same |
| `unchanged` | `No configuration changes` (good) | same |
| `push_pending` | `Saved on VM · push pending` (warn; pending) | same |
| `export_pending` | `Snapshot saved · export pending` (warn; pending) | same |
| `review_pending` | `Saved on VM · review before pushing` (warn; pending) | same |
| `interrupted` | `Save interrupted · snapshot retained` (warn; pending) | same |
| `capture_incomplete` | `Capture incomplete` (bad) | same |
| `failed` | `Save needs attention` (bad) | same |
| `dismissed` | `Snapshot kept locally` (warn) | same |
| unknown status | raw status string (warn) | `gitLabel` fallback |
| no job | `No progress saved yet` | `gitLabel(undefined)` |
| no job (bar) | `Capture configurations, commit and push in one step.` | `#git-progress-status` |
| no binding (bar) | `Connect a repository to save your lab progress` | `#git-destination` |
| diff file status | `file.status` or `changed` | diff badge |
| `File absent` | — | diff column when side missing |
| `Time unavailable` | — | `utcDisplay` on bad date |
| `this lab` | suffix on history versions with `connected` | history dialog |
| `repository root` / `the repository root` | empty prefix | many places |
| worker header (app.js:45) | `Saving lab progress` while any git job active | `#worker-state` (outside this file, driven by `state.git_jobs`) |
| targets | `latest`, `checkpoints/<name>`, `baseline`, `Folder move → <path>` | `gitTargetLabel` |

## 9. Dialogs summary

| id | Title | Opened by |
|---|---|---|
| git-folder-dialog | Save this lab here? | folder browser "Save this lab here" when connected to the browsed repository |
| git-new-folder-dialog | New folder | folder browser "New folder" |
| git-switch-dialog | Use a different repository | connected card `Use a different repository…` |
| git-connect-dialog | Connect a repository by URL | blank state button, inline link in binding form, switch dialog `Connect by URL…` |
| git-save-options | Set baseline / Save checkpoint / Save locally | menu items |
| git-job-dialog | Lab progress save | Save progress, saves list, pending list, retry/dismiss results, destination move job |
| git-diff-dialog | Review this save / Changes compared with latest | job dialog `Review changes`; version dialog `Compare with latest` |
| git-dismiss-dialog | Keep this snapshot only? | job dialog `Keep snapshot only` |
| git-pending-dialog | Saved progress awaiting a push | menu `Push saved progress` with >1 pending |
| git-update-dialog | Update from remote | menu / card `Update from remote` |
| git-unlink-dialog | Disconnect this repository? | card `Disconnect` |
| git-history-dialog | Lab versions and Git history | menu `View changes / History`, `Load version…`, card `View changes / History` |
| git-commit-dialog | Choose a saved folder | history commit with no matching known save |
| git-version-dialog | Saved configuration version | history version, commit resolution, review `View complete saved version` |

Every dialog shares the opDialog chrome: `NODE MANAGER` eyebrow, `×` close (aria-label "Close"), `<h2>` title, trailing `.form-error[role=alert]`, native `<dialog>` modal (Escape closes).

## 10. Microcopy a CCNA-level student may not understand

| Text | Where | Problem |
|---|---|---|
| `Connect a repository to save your lab progress` / `Git repository settings` | bar | "repository" assumes Git knowledge |
| `Capture configurations, commit and push in one step.` | bar default status | "commit", "push" are Git internals |
| `Choose a registered VM repository` | Save button title | "registered", "VM" are implementation terms |
| `Saved on VM · not pushed`, `Saved on VM · push pending`, `Pushing to remote`, `Saved on VM · review before pushing` | status labels | "VM", "push", "remote" |
| `Snapshot saved · export pending`, `Retry export and push`, `Retry export locally`, `Snapshot kept locally`, `Save interrupted · snapshot retained` | status / job buttons | "snapshot", "export" are internal pipeline stages |
| `Keep snapshot only` / `Stop tracking this pending export or push …` / `Any local commit remains in the repository and may be included in a later push.` | dismiss dialog | Git internals (local commit, push) |
| `Check the VM connection and Git helper installation, then choose Refresh status.` | Git tab error | "Git helper installation" is a deployment detail |
| `Git authentication belongs to the repository owner on the VM.` | Git tab heading | auth/ownership model exposed |
| `Verified push destination: <url>` | connected card | "push destination" |
| `Branch main · VM account alice · /home/alice/repo` | connected card | branch, VM account, filesystem path |
| `Scheduled backup selection is independent.` | connected card | cross-feature coupling |
| `The folders of the connected repository, as they are in Git right now.` | Where this lab lives | "in Git" |
| `owner · path · remote / branch · Push to <url> · repository root` | `#git-binding-destination` | raw remote/branch/owner/path tuple |
| `Unsupported devices are excluded: …` | binding form | "unsupported" without saying why |
| `An offline included device makes the capture incomplete. Its previous configuration is never silently substituted.` | binding form | "capture" pipeline semantics |
| `Review changes before pushing` | binding form | "pushing" |
| `I understand that full device configurations, including any secrets they contain, will be committed and pushed to this repository.` | exposure checkbox (form + connect dialog) | commit/push jargon (though the warning itself is important) |
| `Git runs as the registered VM account using its existing Git login and commit identity. Configure that login on the VM outside this application.` | binding form | "registered VM account", "commit identity" |
| `Acknowledge exporting full configurations to the selected repository.` | validation | "exporting" |
| `Paste the HTTPS URL of your GitHub repository. The manager clones it on the VM with the GitHub login already set up there…` / `HTTPS clone URL (Code › HTTPS)` / `It never asks for a token or password.` | blank state, connect dialog | clone, token |
| `From the release source directory on the VM, run guided setup as your ordinary account, without sudo:` `bash deploy/setup-git.sh` `The wizard handles checkout, Git login and registration.` | blank state | shell, sudo, checkout, registration |
| `If no commit name and email are set on the VM yet, the GitHub account's name and its private noreply address are used.` | connect dialog | git config internals |
| `Every save links to its original configuration capture. Git history contains committed versions.` | Progress saves | "capture", "committed versions" |
| `Fetch the registered remote and fast-forward the current branch when the working repository is clean and its history allows it.` `A conflict keeps the existing checkout and reports what needs attention.` | Update from remote | fetch, fast-forward, working repository clean, checkout, conflict |
| `Capture and commit to the VM repository without pushing.` | Save locally | commit/push |
| `Capture the configured devices and preserve this milestone under checkpoints/ as well as latest/.` | Save checkpoint | filesystem paths |
| `Older backups retain their recorded provenance. A successful capture alone does not verify restore compatibility.` | Set baseline | "provenance", "restore compatibility" |
| `Replace the existing baseline with this selected capture. The previous version remains in Git history.` | Set baseline | Git history |
| `Push after saving (review preference still applies)` | save dialog | push, "review preference" |
| `Changed device scope` / `Allow this save to remove previously managed config files for devices no longer in the configured scope. Their older versions remain in Git history.` | save dialog details | "managed config files", "scope" |
| `Saved target` / `checkpoints/<name>` / `latest` / `Folder move → …` | job dialog | paths as labels |
| `Commit <hash>` / `Changed files <n>` | job dialog | Git internals |
| `You can close this window. The save continues and its result remains in Git repository settings.` | job dialog | fine but refers to a tab by another name ("Git repository") |
| `Changes introduced by commit <hash>. Full configuration files can contain device secrets.` | review dialog | commit hash |
| `Snapshot folder at this commit` / `A folder must already exist at this commit. Choose another folder if this version predates it.` | commit dialog | commit/folder model |
| `Historical configuration version` | commit dialog fallback | vague |
| `This version has a restore-grade Junos candidate.` / `predates live restore support` | version dialog | "restore-grade", "candidate" (Junos term), "live restore support" |
| `Capture manifest` (raw JSON) | version dialog | internal metadata dump |
| `Download version (ZIP)` → `lab-version.zip` | version dialog | fine, but file naming is internal |
| `No baseline, latest capture or checkpoints saved yet.` / `No progress commits available.` | history dialog | baseline/checkpoint/commit trio |
| `Each saved state shows its folder, so you can tell base, working, final or broken apart — not just “latest”.` | history dialog | assumes folder convention |
| `Reading registered repositories and saved progress…` | Git tab loading | "registered" |
| `Choose a repository folder` / `Repository and folder` | select | Git term |
| `NODE MANAGER` eyebrow | every dialog | product name, not a task label |
| `File absent` | diff | terse |
| `Time unavailable` | any time field | terse |
| `Generic SSH / Linux`, `Unmapped` (platformLabel fallbacks) | device list | SSH/mapping jargon |
| toast `Git repository connected. Save progress is ready.` / `<lab> is connected to <repo>.` / `Folder <prefix> is ready for a lab.` / `Repository updated from remote.` / `No saved progress is waiting to be pushed.` | toasts | "remote", "pushed" |

## 11. Redesign risks (easy to break)

1. **Id-bound wiring.** Every control is located with `$(id)` after `innerHTML` replacement; renaming any id listed in section 4 silently breaks handlers (`$('x').onclick` on null throws).
2. **`data-*` dispatch tables.** `data-git-action` (bar menu), `data-git-repo-action` (tab), `data-git-job` (saves list), `data-git-job-action` (job dialog), `data-git-pending`, `data-git-version`, `data-git-commit` and input `name="git-node"` are the contract; the action names `local|checkpoint|baseline|history|load|push|update|settings` and `switch|history|update|unlink|connect` are hard-coded, and the disabled exemption list `['history','load','settings']` lives in `renderGitProgress`.
3. **`#git-save-menu` must stay a `<details>`.** Open/close is done via the `.open` property, outside-click uses `menu.contains(event.target)`, and CSS `.git-save-control:has(.git-save-menu[hidden])>.button` restores the Save button's right corners when the menu is hidden.
4. **Button label swap and gating on the same element.** `#git-save-progress` doubles as "Connect Git repository" (no binding) and "Save progress"; its `disabled` rule mixes `gitSubmitting`, an active git job, and global `busy()` (backups/operations) only when bound. Its `title` carries the destination.
5. **opDialog chrome contract.** Every dialog relies on opDialog appending `<p class="form-error" role="alert">`; `opTask` writes validation/API errors there and disables all enabled buttons for the duration. `gitStartWatch` also writes into `#git-job-dialog .form-error`. The binding form embeds its own `.form-error` because it is not a dialog.
6. **Dialog re-use by id.** `opDialog` reuses an existing `<dialog>` with the same id and replaces its innerHTML; `git-diff-dialog` is shared by two different titles/flows. `gitRenderJob` refuses to render unless `gitDialogJob===job.id` and `#git-job-dialog.open`.
7. **Polling lifecycle.** Watch starts from the job dialog and from `renderGitProgress` (every 4 s state refresh); it is cancelled on lab switch unless the job dialog is open; completion triggers `refresh()` and a forced Git-tab re-render only when `tab==='git' && activeId===lab`. Any redesign that changes `tab` naming or the `render()` hook order loses auto-watch.
8. **Stale-response guards.** `gitViewRequest` (Git tab) and `gitPlacesState.request` (folder browser) discard late responses; `gitViewLab` makes `showTab('git')` a no-op for the same lab until `Refresh status` (forced) — a redesign that renders the tab elsewhere must keep calling `gitShowRepository(true)` after mutations.
9. **Cross-view hand-off.** "View configuration capture" depends on Backup history rendering `<details class="job" data-job="<id>">` and on `selectLab` + `showTab('backups')` order; it sets `.open=true` and scrolls.
10. **Optional restore integration.** `Apply to running lab…` and the folder browser's Apply are only wired when `restoreFromVersion` / `restoreFromFolder` exist; `data.restore_supported` also gates the button.
11. **Exposure checkbox semantics.** `#git-exposure` is hidden *and* `required` toggled by `gitBindingChanged` (id or revision change); it is force-unchecked on every select change and revalidated on submit.
12. **Preselection and scrolling.** `gitPendingSelection` is a one-shot preselect consumed in `gitRenderRepository`; three flows (`Use folder` not-connected, `New folder` not-connected, `Choose this repository`) rely on it plus `scrollIntoView` on `#git-binding-form`.
13. **Idempotent save.** The plain Save button path stores `git-save-request:<labId>` in sessionStorage and reuses `request_id` for an identical retry; dialog saves generate `requestId` at dialog open. Changing when `gitRequestId()` is called changes duplicate-capture protection.
14. **Two separators encode meaning.** `›` is used for path hierarchy (`repo › folder › latest/`), `·` for attribute lists; `aria-hidden` spans wrap the `›` in the destination line.
15. **`gitCompleteBackups` exact-match rule** (node set must equal `binding.node_names` and every node succeeded) determines whether Set baseline is even possible; the notice and the disabled confirm button depend on it.
16. **Download uses a raw `api()` call** (not `json()`) to get a blob and the `Content-Disposition` filename; must remain a POST with JSON body.
17. **Empty-catalog vs connected states.** The tab has three layouts (blank state; catalog without binding; connected card + form) and the "Where this lab lives" section appears only when `repositories.length || binding`.
18. **`gitLabJobs` merges two sources** (`context.jobs` and `state.git_jobs`, including jobs with no `lab_id`) and sorts by `created||finished` string compare; the bar shows `jobs[0] || lab.git_status`.
19. **Keyboard/a11y hooks**: `role="status"` on bar status and loading text, `role="alert"` on errors, `aria-label` on the bar, menu summary and places section, `tabindex="0"` on `<pre>` blocks, document-level Escape handler for the menu.
