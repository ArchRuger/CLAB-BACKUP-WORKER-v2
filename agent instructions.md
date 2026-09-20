# UI review 001 (in progress) — 1.30.8

The maintainer's UI review is implemented as a series of patch releases, one requirement chunk each, on
`claude/ui-review-001`. **Read `docs/ui-review-001/PICKUP.md` first** (what is done, what is next, how
each chunk is validated and pushed) and `docs/ui-review-001/CHECKLIST.md` (UI-001 … UI-008 with their
acceptance criteria). This section grows with each step; the newest facts are in the pickup file.
(1) **1.30.2, UI-001**: Home has no *Also running on the VM* section. `#discovered-labs`,
`#excluded-labs` and `#discovery-files` kept their ids and handlers and now live in
`#vm-labs-dialog` (markup in `management.js`), opened by `#manager-vm-labs` in the Manager menu;
`homeVmLabs(discovery)` in `home.js` is the pure count behind the menu's note line. Do not put a
discovery list back on Home. `docs/ui-review-001/` may name any release (`HISTORY_DIRS` in
`verify-release.py`).
(2) **1.30.3, UI-005**: `#lab-actions-menu` ends with `#lab-actions-advanced-toggle`
(`data-menu-group`) and `#lab-actions-advanced` (`data-menu-panel`, `hidden`) holding `menu-import-map`,
`menu-map-edit`, `menu-telemetry`, `menu-operation-history` (ids, `data-proxy` mirrors and handlers
unchanged). `initMenu()` in `shell.js` owns the behaviour for any menu: the toggle is a `menuitem` that
never closes the menu, `items()` skips a hidden panel's items, ArrowRight/ArrowLeft expand and
collapse, `open()` collapses every group. Only those four items were reviewed for the move; do not
sweep other entries into the group. `#lab-actions-menu` has a `max-height` and scrolls inside itself.
(3) **1.30.4, UI-004**: `.git-save-options` is a grid of `.git-save-list` (the `role="menu"`) and
`#git-save-help`; `gitSaveHelp(action, binding)` in `git-progress.js` is the pure source of every
explanation and must follow `execute()` in `app/git_progress.py` (a local save never uploads; history
reads and saves nothing); `gitRenderSaveHelp()` fills the four `#git-save-help-<action>` entries on each
render without rewriting unchanged text, `gitShowSaveHelp()` shows one on `mouseover`/`focusin`, and
`gitSaveMenuPlacement()` (pure) + `gitPlaceSaveMenu()` set `menu-from-left` / `menu-stacked` on
`.git-save-control` when the `<details>` opens. A new option in that menu needs a help entry, an
`aria-describedby` and a case in `GIT_SAVE_HELP_ACTIONS`. UI-007 C will change the upload wording.
(4) **1.30.5, UI-007 A + B**: on the Save location card only `.git-location-tech` reads *Git repo
details*. `#git-change-folder` renders `open` unless the lab id is in `gitFolderCollapsed` (a `Set` in
`git-progress.js`, filled and emptied by the disclosure's own `toggle` event, page lifetime only);
`gitPlacesState.open` (Browse the repository…) opens it for one render and is the only thing that
scrolls to the save settings. The card is rendered by `gitShowRepository()`, not by the 4 s poll.
(5) **1.30.6, UI-007 C — the review before an upload is mandatory; do not reintroduce an opt-out.**
Manager (`app/git_progress.py`): the save route sets `review = data.push`, so `want_push` is never true
for a save and it ends `review_pending`; `Retry` has `reviewed`, and a push retry of a job with a commit
needs `data.reviewed` or a recorded `job['reviewed']` (else 409), a push retry without a commit becomes
a local retry with `review_before_push=True`, a `move` job is exempt; `reviewed` is in `PUBLIC_JOB`.
`review_before_push` stays in the `Link`/`Connect` models for old pages and is ignored; new bindings
store `True`; **never rewrite stored bindings** (pending jobs compare `digest(binding)`). Page
(`git-progress.js`): `gitNeedsReview(job)`, `gitUploadLabel(job)`, `gitReviewJob(job)` is the only
place that sends `{push:true, reviewed:true}`; a quiet save that ends `review_pending` opens it by
itself; the job window and Recent saves route unreviewed uploads to it. A push sends every earlier
unpushed commit of the branch too; the review says so when such saves exist.
(6) **1.30.7, UI-008 part 1 — empty folders.** Git has no empty folders and the VM registry holds only the
folder a lab saves to now (`register-prefix` with `retire` removes the previous one; nested lab folders
"cannot overlap"), so the manager keeps `state['git_folders'][<checkout path>]` = prefixes made or chosen
through it (`remember_folders()` in `git_progress.py`: `POST …/folders`, with `plan: true` for a folder
that is only listed; the `destination` route remembers the folder the lab leaves and the new one;
`DELETE …/folders` forgets one; capped at `MAX_PLANNED_FOLDERS`; never in `/api/state`). The tree route
adds `planned`; `gitTreeModel(files, folders, planned)` sets `dir.planned`, and `pending` means "no
saved file yet". Never word a pending folder as existing in the repository. Do not change
`host_git.py` for this. The fixture's scripted helper must keep matching the real one (retire, overlap
refusal, a flat `register-prefix` answer).
(7) **1.30.8, UI-008 part 2 — the tree's state belongs to the student.** `gitPlacesState.expanded` (a
`Set`, `''` always in it) is the only source of open branches; `gitPlacesMarkup` takes it as
`view.expanded`. It changes only through `gitToggleFolder` (the `.git-twist` button, ArrowRight /
ArrowLeft on a focused `<summary>`) and `gitRevealFolder` (a selection). `gitPlacesShow` resets it to
`gitDefaultExpanded` only when the checkout path differs (`expandedFor`), otherwise `gitKeepExpanded`;
`revealed` makes a page-made selection visible once. Never derive `open` from the selection again.
`summary.current` = the folder the lab saves to, `summary.selected` = the browsed folder,
`holds-current` = a closed branch with the destination inside. `draw()` restores the focused control
and the outline's scroll position after each redraw. Children of a closed branch are not rendered.

# Lab builder quality pass — 1.30.1

Read docs/CHANGELOG.md "Changes in 1.30.1" and docs/lab-builder/QA-FINDINGS.md (every finding with its
evidence, fix and what is still open). Frontend and manager only; the helpers changed by their lockstep
version alone, and the independent security review of `publish` / `revise` that this pass asked for did
**not** happen (the reviewer was stopped by the model's safety filter; see S-1 in the register). Facts to
preserve, all in `app/static/lab-builder-page.js` unless another file is named.
(1) **Never show as kept what is not.** `persist()` throws when `draftWrite` fails and then holds the
editor's texts in `builderUnstored`; while that is set the pill is *Last change not kept in this browser*,
Save is off, and Download / View YAML read `builderUnstored` first. `draftWrite` errors carry
`code: 'storage' | 'conflict'` (main.tsx passes it to `problem()`; *Try to store it again* shows for
storage only, and a successful retry reloads because the editor heard the edit fail). Revisions are
tokens (`draftToken()`), compared for equality only.
(2) **The topology text is the authority for the lab name.** `builderYamlName()`; a draft without `vm`
takes the YAML's name in `persist()` (the id `new:<first name>` stays); `builderNameProblem()` blocks Save
with the reason for an unusable name and for a changed name on a draft that has `vm`. `builderVmPath()`
derives the path like the helper does.
(3) **Every way a save can end reaches the draft.** `builderSave()` stores `saving:true` before the
review; `opJobDone()` clears it (success, `already_published`, failure); `builderReconcile()` asks the VM
once on the next visit. In `operations.js` `opShowJob` keeps polling after its dialog is closed **only on
a page that defines `opJobDone`** (`follows`), and repeats a failed poll up to ten times everywhere.
`builderSaveRefused()` is the only place a refusal is shown: a dialog, never a toast; when the VM's files
differ from `draft.vm` it offers the rebase (`vm` := what `builderVmRead()` just returned, then
`builderSave()` again, which is an ordinary reviewed `revise`). Do not add an automatic retry or an
automatic rebase.
(4) `builderVmRead()` keeps the helper's `sha256` values and `builderSaveRequest()` sends them as the
revise base (`vm.hash`, `vm.layoutHash`); after the page's own save there are none and the texts are
hashed. `builderOpenFromVm()` reuses any draft whose `vm.path` is the file (one draft per lab).
(5) **main.tsx** refuses a draft whose YAML has a parse error (`yaml` `parseDocument`, first error,
`code: 'unreadable'`) before it constructs the engine: the engine acknowledges edits to such a document
and writes none. `importCustomNodes` uses the editor's own `parseCustomNodeTemplatesExport` /
`mergeCustomNodeTemplates` from `@containerlab/clab-ui/session` and the page's `chooseTemplates()`.
(6) `builderStart()` asks for state, capabilities and known images **before** the editor mounts (the
editor takes its templates once, at mount), capped at five seconds so a draft still opens when the manager
is away. `builderStore` is `localStorage` or an in-memory stand-in with a standing note; with the stand-in
`builderGo()` must not reload.
(7) Layout: `body.lab-builder` is a flex column (bar, note, `.builder-stage`, credit); `#root`, the
welcome and the problem overlay are absolute inside the stage, so the note never covers the editor's
toolbar. `lab-builder.html` loads `topology-render.js` for the Topology file dialog's preview.
(8) `style.css`: `#operation-review .dialog-actions` is sticky with `bottom: -24px` (the sticky box is the
dialog's content box, so the padding has to be compensated). `operations.js` closes `op-editor` and
`op-browser` on confirm; `opJobHint()` is pure and its `hint` key exists only when there is one (older
tests compare the banner object exactly).
(9) The entry bundle is `/static/lab-builder/assets/main.js?v=<release>` with `immutable` caching and no
content hash in its name: a change to `main.tsx` reaches browsers only with a new release number.
(10) Tooling: `fixture_manager.py` marks a lab it deployed as running and drops it on destroy;
`student_workflow.py` (40 checks) waits for that before it expects the refusal; the exploratory scripts
and all screenshots of this pass are in `~/research/lab-builder/qa/` on the dev VM.

# Lab builder — 1.30.0

Read docs/LAB-BUILDER.md, docs/CHANGELOG.md "Changes in 1.30.0" and docs/lab-builder/PICKUP.md
(decisions and their reasons; the research, the independent review and the throwaway prototype are
outside the repository in `~/research/lab-builder/` on the dev VM). Facts to preserve.
(1) **The editor is embedded, not forked.** `@containerlab/clab-ui` is pinned exactly in
`clab-backup-ui/lab-builder/package.json`; `src/main.tsx` is the whole adapter: a custom
`ClabUiHost` (the package's documented custom-host pattern), `TopologySessionCore` running in the
page over `DraftFiles` (an in-memory two-document store: the engine's temporary and backup names
never leave it), one engine operation at a time, and `labBuilderPage.persist()` called after each
operation settles and **before** the editor hears the answer. Never flush on a timer: the engine's
save is write-temp, rename-to-backup, rename, unlink, and a timer can catch the moment the topology
is missing. The editor has no drift detection in this version; `draftWrite()`'s revision check is it.
(2) **`script-src 'self'` is not negotiable.** The editor's YAML/JSON tabs compile a schema with
ajv (`new Function`), so they are off (`disabledTabIds`) and the Monaco chunk is replaced by
`src/monaco-stub.ts` at bundle time (the editor preloads it even with the tabs off). A build-time
precompiled validator substituted for `ajv` was proven to work in the prototype if editable YAML is
ever wanted; it is not a supported upstream hook. Embedded fonts are moved out of the CSS into files
by `build.mjs` (font-src falls back to 'self'). Only `/static/lab-builder.html` gets inline styles;
`/` must keep none (two older tests assert it).
(3) **Hidden controls.** This editor version has no switch for its deploy menu, Geo layout, split
view or Grafana export; `lab-builder.css` hides them by `data-testid` and
`tests/test_lab_builder_ui.js` fails when the bundled editor no longer contains one of those ids.
The host still answers `runLifecycle` (a `lifecycleStatus` event, then the manager's save), because
without an answer the editor freezes. On an editor upgrade: rebuild, run that test, run
`docs/lab-builder/tools/student_workflow.py`, and check whether upstream's `lifecycleActionsAvailable`
prop has been published (it removes the need to hide the deploy menu).
(4) **Helper contract** (`app/host_operations.py`, security-sensitive): `publish` takes only a
trusted root, a name and the texts, derives every path, works relative to the open folder
(`place()`: exclusive 0600 temporary, write, fsync, fchmod, link or replace, fsync the folder),
layout first and topology last, rollback by inode of its own files only, `publish_state()` =
new / reuse / resume / published where resume accepts only what that write order can leave behind.
`revise` needs an undeployed lab (by name and by topology path), the opened versions' hashes in
`options.base`, keeps recovery copies and the file mode. `delete` takes the layout file along. The
digest binds the whole request including both texts; there is no run retry, recovery is a fresh
preview. Keep the option whitelist exact. The 1.12.0 removal of `write` stands and its tests are
untouched: `revise` is a different action with a narrower contract.
(5) **Manager side** (`lab_operations.py`): publish/revise previews run `parse_definition`, pin the
name on revise, refuse a name registered with another topology file, cap the encoded options at
1.5 MiB, turn an unreadable layout into a warning (never a refusal: the editor writes shapes the
manager's map rejects, e.g. one id in both node arrays), and add a unified diff for revise. Job
records never hold file text. `GET /api/operations/known-images` reads `definition_yaml` only.
(6) **Page** (`lab-builder-page.js`, plain house-style JavaScript loaded with `operations.js`, like
`workspace.js`): drafts under `clab-builder:` in localStorage, `builderSaveRequest()` chooses publish
or revise, `opJobDone()` (called by `operations.js` when a job it showed finishes) records the saved
version and re-registers a lab that is in My labs after a revision. `lab-builder.css` must keep
`.lab-builder #root svg{max-width:none}`: the manager's `img, svg {max-width:100%}` collapses the
editor's zero-width link overlay and the wires vanish.
(7) **Release tooling**: `lab-builder.html` is in `verify-release.py`'s versioned-page list; the
assets' folder must not be called `dist/` (git-ignored) and notices must not be `.md` (dropped from
the image); CI rebuilds the assets with Node 24 and compares the manifest.
(8) Known and left alone: `setup-engineer-access.sh --refresh` re-modes the trusted roots
recursively, which loosens existing `.clab-manager-history` recovery copies from 0600 to 0660
(group `clab_admins`); removing a lab with `prevent_reimport` keeps its name in `ignored_labs`.
Live-validated on the dev VM with Linux hosts only (VALIDATION.md).

# Student UI screenshot pass and layout fixes — 1.29.1

**Released as 1.29.1** directly on `main` (the user asked for a patch push, no feature branch).
Eight layout defects found by screenshotting every student page on the live dev VM
`clab-llm-dev2` (`docs/redesign/PICKUP.md` §7 lists them with their root causes,
`clab-backup-ui/VALIDATION.md` has the evidence); frontend only (`style.css`, `app.js`
`jobMarkup`, `operations.js` *Open all CLIs*, `git-progress.js` error state), backend and
helpers untouched apart from the lockstep version. Facts to preserve: `.map-expanded` needs
`align-items: stretch` on `.topology-layout` and on its first child (the map column has no class
of its own and the grid rule says `start`); the rail `.device-row` is a named-area grid
(`name state / platform platform / reason reason / actions actions`) with its wrapper divs at
`display: contents`, so a new child of `deviceRow()` needs a grid area; the `.map-tools` button
rule keeps `:not(.menu-list *)`; `.tool-grid` is `auto-fit` (an empty track collapses); the backup
summary's `<small>` wraps its date and its count in spans so a narrow card breaks at the
separator only; the Progress error card leads with `error.message` unless the error is a
`TypeError` (network). Tooling for a repeat pass: the sweep script lives outside the repository
(`~/ui-review/student_shots.py` on the VM: Playwright over the live manager, one screenshot per
student state at several viewports, a probe for right-edge overflow and clipped text,
console/page errors collected); `verify_after.py` against the fixture manager stays the
regression gate (93 checks × 3 viewports, 0 console / 0 page errors) and its 1440×900 shots are
the tour images (timestamps differ per run, so replace only the images whose layout changed).
Known non-defects: the capture setup page's `pre` scrolls (headless hides the bar); a full-page
screenshot draws the sticky top bar mid-page; the `sr-only` label is reported as clipped.
Upgrading an installed VM needs the helper refresh (`start-manager.sh`, or `setup-git.sh
--refresh` for the Git helper alone), otherwise `/api/git/repositories` answers 409 and the
Progress tab shows its error state.

# Student-centred UI redesign, live-validated, plus the Git helper and Saved versions fixes — 1.29.0

**Released as 1.29.0** from `claude/1.29-release-validation` (the redesign merged as PR #35, then the
live-lab pass on the dev VM `clab-llm-dev2`; `docs/redesign/PICKUP.md` §7 is the log). Two fixes
shipped with it: `app/host_git.py` counts a folder's `.jcfg` restore artifacts (schema-2
`restore_artifact`) as manifest-owned files, so repeat saves and checkpoints into a Junos folder
work (blocker found live; refresh the helper); `git-progress.js` `gitVersionGroups` lists the saved
folders one level below a sibling without its own `latest/` (the scaffold's `reference/<state>`).
Live facts to keep: a saved candidate carries the node's management address, so apply after a
redeploy only works with pinned `mgmt-ipv4` (otherwise the commit-confirmed rollback fires, proven
live); this cJunosEvolved image's data ports start at `eth4` (use the `et-0/0/0` aliases);
`Sync topology from VM` keeps the drawing when the VM has no annotations file. Before touching the frontend read `docs/redesign/PICKUP.md`, then
`docs/redesign/DESIGN-SPEC.md` and `docs/redesign/DESIGN-SPEC-ADDENDUM.md` (the addendum is the
binding contract; §J9 is the migration order). Plan steps 1–5 are done: `status.js` (student
vocabulary, pure), `shell.js` (hash router, menus, storage — the only file allowed to touch
`window`/`location`/`localStorage`/document listeners), `home.js`, the new `index.html` (Home →
Lab workspace with Topology · Devices · Progress · Tools · Advanced → device panel), map states
and the student context menu (`topology.js`, `topology-render.js`), the Progress tab
(`git-progress.js`, `git-places.js`, `restore.js`), the operations / management / capture copy
and dialogs, the standalone pages (CLI launcher, terminal, network dashboard, Diagnostics), the
design system (`style.css`, `terminal.css`), the tests (`tests/test_status_ui.js`,
`test_shell_ui.js`, `test_home_ui.js`, `test_topology_menu_ui.js`; every pinned label of the
older suites rewritten with its claim kept), and the functional-parity review (four modules,
every inventory row present, "Intentionally removed: none"). **Zero functional regression is the
rule**: every capability in `docs/redesign/inventory/*.md` and `docs/redesign/parity/*.md` keeps
working, the backend and helpers are untouched. Facts to preserve: the Junos apply-from-any-folder
workflow (`restoreFromFolder`, no rebinding, `{type:'folder',path}` sources); "Compare with my
latest save" never "running configuration"; backend `readiness === 'Ready'` is backup
eligibility, `deviceState()` is SSH readiness; `data-proxy` mirrors instead of duplicate ids;
`setMarkup()` diffing on the 4 s poll; legacy tab names via `TAB_ALIAS`; `shell.js` renders once
more on `DOMContentLoaded` because a fast first `/api/state` can beat the later deferred scripts.
Browser validation runs without a VM: `docs/redesign/tools/fixture_manager.py` (the real app on a
scratch data directory, VM answers scripted in-process: readiness, discovery, jobs, Git helper,
restore probe, operations helper) and `docs/redesign/tools/verify_after.py` (three viewports, zero
console/page errors; Chromium's "Failed to load resource" for a handled non-2xx is reported apart).
`docs/redesign/` is exempt from the living-doc release check. The release-validation pass of 2026-09-17 first ran on `clab-llm-dev2` before it was a dev VM
(decision BLOCKED), then the host was installed with `docs/QUICK-INSTALL.md`, the lab
`clab-llm-dev2` (PTX1 cJunosEvolved, SW1 vJunos-switch) was deployed through the UI and every
gate was exercised live (VALIDATION.md); `tests/test_topology_menu_ui.js` is in the workflow's
browser step. Telemetry was observed but not gated (the maintainer is deprecating it).

# Live Junos configuration restore and nested Git folders — 1.28.0

Read docs/CHANGELOG.md "Changes in 1.28.0", docs/GIT-PROGRESS.md "Apply a saved configuration
to a running node" and docs/LAB-OPERATIONS.md "Apply a saved configuration to a running node".
Feature: apply a saved Junos config to a running node with no reboot/redeploy, and create a
nested Git save folder in one step.

(1) Restore mechanism — proven live, do not regress. Junos `show configuration | display set`
is merge-only (`load set`) and cannot remove stale statements; the restore loads the
**hierarchical** candidate (`show configuration`) with `load override terminal`, runs
`commit check`, then `commit confirmed <minutes>`; the manager reconnects (proving management)
and runs a plain `commit` to confirm, else the node auto-rolls-back. `juniper_cjunosevolved`
(image 26.2R1.7-EVO) has **no `root-authentication`** and rejects every real commit with
"missing mandatory statement" — `load override`/`load update` both fail — so the candidate
must carry root-authentication; when absent the driver synthesises it from the candidate's own
superuser login encrypted-password. `juniper_vjunosswitch` already has it. PyEZ/ncclient/lxml
are NOT installed and `junipernetworks.junos` 11.1.1 is a deprecation shim over
`juniper.device`, so NETCONF/`junos_config` are unavailable; the CLI path is the only option.
Do not add those deps. (2) Capture: inventory.py Junos platforms gain `restore`
(`show configuration | no-more`), `restore_format` (`junos-hierarchical`), `restore_suffix`
(`jcfg`); `runner.make_inventory` sets `restore_command` for backup ops only; `ansible/backup.yml`
has a second task *Fetch restore artifact* guarded by `restore_command is defined`;
`runner._execute` routes `RESTORE_TASK` events to `restore_results` (never sets node status or
fails the backup) and stores a companion `<base>-<hash>.jcfg`, recording `restore_file`/
`restore_format` in the outcome. `git_progress.captured_snapshot` adds the artifact to snapshot
`files` and per-file manifest fields `restore_artifact`/`restore_size`/`restore_sha256`/
`restore_format`/`restore_capable` (manifest `schema=2`, `restore_capable_nodes`);
`decoded_snapshot` validates artifacts too (`take()` helper); `downloads.stored_restore_path`;
the `/git/version` route reports `restore_supported`/`restore_nodes`. Old snapshots have no
artifact → view/download only; never silently claim they are restorable.
(3) Driver `app/restore_junos.py`: `JunosShell` (ANSI-stripped prompt driver like
telemetry_provision), `apply_shell` (configure exclusive→load override terminal + Ctrl-D→
`_ensure_root_authentication`→`show | compare`→commit check→commit confirmed; discards on any
failure), `confirm_shell` (fresh session `commit`), `capture_shell`, `SUPPORTED_KINDS`,
`supports_restore`. (4) Service `app/restore.py` `RestoreService(store,runner,git_progress,connector)`:
`restore_jobs`, single-worker pool, restart marks RESTORE_BUSY jobs `interrupted`;
`lab_operations.operation_busy` gained `RESTORE_BUSY` (progress_id excludes the restore's own
job so its pre/post backups run); `resolve_source` (git via helper `read-version`+`decoded_snapshot`,
backup via `captured_snapshot`) maps saved node→running node by exact name + platform match;
`preflight` live-probes SSH reachability and a current-state match; `submit` guards
(idle+acknowledge+host identity+idempotent `request_id`); `execute` = preflight → **mandatory**
pre-restore backup (`runner.submit` source `restore-pre`; a node whose backup fails is not
changed) → per node `apply_candidate`+reconnect+`confirm` → post backup (`restore-post`) +
`compare_states` (tolerates the synthesised root-authentication and volatile version lines) →
`_finalize`. `compare_states`/`mask_line` redact; `public_job` never exposes `_candidates` or
`host_identity`. Routes `GET /api/labs/{id}/restore/sources`, `POST …/restore/preflight`,
`POST …/restore`, `GET /api/restore/jobs/{id}`; `/api/state` carries `restore_jobs`;
`remove_lab` drops them. (5) UI: `app/static/restore.js` (`restoreReview` posts preflight and
renders the *Replace running configuration* review; `restoreShowJob` polls; danger button);
`git-progress.js` `gitViewVersion` shows **Apply to running lab…** when `restore_supported`.
Apply straight from the folder browser too: `resolve_source` accepts `{type:'folder',path:'<repo>/latest'}`
and reads it at HEAD, so a lab applies a saved state from any folder **without rebinding**
(`host_git.allowed_repo_version` lets `read_version` reach any snapshot folder of the checkout;
`git_tree` model marks a folder `restorable` when its `latest/` has a `.jcfg`, and `gitPlacesShow`'s
`onApply` runs `restoreFromFolder`). `git-places.js` `gitFolderPath`/`gitDestinationPreview` create a nested destination in one step
with a live result preview; `restore.js?v=<release>` in index.html; every interpolation via
`esc()`; new `.button.danger` + `.restore-*` CSS. (6) Tests: `tests/test_restore_junos.py`
(scripted fake channel), `tests/test_restore.py` (fake connector+runner, backup source),
restore-artifact tests in `tests/test_git_progress.py`, `tests/test_restore_ui.js`, nested-folder
tests in `tests/test_git_places_ui.js`; release-check runs test_restore*.py and test_restore_ui.js.
Preserve: display-set stays the canonical human/diff form; pre-backup is mandatory; do not fake
commit-confirmed; restore uses the direct node-SSH path, never a host helper; Junos only until
XR/EOS replace+verify is validated. `host_git.py` `snapshot`/`read_manifest`/`read_version` accept
schema 1 and 2 and validate/return each file entry's `restore_artifact` (via small `take`/`check`/
`read_one` helpers); refresh the helper with `setup-git.sh --refresh` and rebuild the manager image.
Prepared on `claude/junos-live-restore-and-git-destinations` from main `c1d22f3` (1.27.0);
live-validated on the dev VM (VALIDATION.md): the manager-orchestrated restore was proven on
cJunosEvolved (root-auth synthesis path), and the mechanism directly on both Junos kinds.

# Repository folder browser, folder moves and connect by URL — 1.27.0

Read docs/CHANGELOG.md "Changes in 1.27.0", docs/GIT-PROGRESS.md "Where this lab lives" and
docs/GIT-SETUP.md "Connect or switch a repository from the manager".
(1) Helper `app/host_git.py` (installed by `setup-git.sh --refresh`; VERSION must equal the
manager): owner-level modes `browse` (ls-tree of HEAD bounded by MAX_TREE, last-save times, and
the sibling registrations of the same checkout as `folders`, injected by main() as `_siblings`)
and `move` (moves every `latest/`, `baseline/` and `checkpoints/` file of `source_prefix` into
this binding's prefix through the same journal, `finish_export`, verify_tree and push machinery
as a save; the staged-set checks use `diff --cached --no-renames`). Root-level modes
`register-prefix` (plan_prefix, then `GitRepository.register()` in a privilege-dropped child via
run_as_owner; `retire: true` removes the source registration afterwards so a lab registered at
the repository root can move into a subfolder) and `connect` (plan_connect: owner = the single
registered owner or /etc/clab-manager/engineer.json, path = an existing checkout of that push
URL or `~/labs/<repository>`; `GitRepository.connect()` clones or adopts, `check_permission`
runs gh auth status / setup-git / `api repos/... .permissions.push`, `ensure_identity` derives
name and noreply email from `gh api user` when the checkout has none, then `register()`).
`tool()` runs from the owner's home while the checkout does not exist yet. `register()` mirrors
the inline child of deploy/setup-git.sh; keep the two equivalent. Keys starting with `_` never
reach the registry. (2) Manager `app/git_progress.py`: `GET /api/git/repositories/{id}/tree`
(folders decorated with the bound lab), `POST /api/git/repositories/{id}/folders`,
`POST /api/labs/{id}/git/destination` (idle + pending guard, other-lab conflict check before the
helper call, register-prefix with retire, rebind with the same devices and review flag, optional
job with target `move` that execute() runs without any capture and pushes when wanted) and
`POST /api/labs/{id}/git/connect` (acknowledge required; devices default to the previous
selection or every supported node). (3) UI: `app/static/git-places.js` holds the pure tree
model (`gitTreeModel`), the folder rules that mirror the VM rules (`gitFolderChoice`,
`gitCanCreateIn`) and the panel renderer (`gitPlacesMarkup`, `gitPlacesShow`);
`git-progress.js` renders the connected card with the folder path, the "Where this lab lives"
panel and the dialogs Save this lab here, New folder, Use a different repository and Connect by
URL; move jobs read as *Folder move* and open `latest`. Every interpolation goes through
`esc()`; no inline styles (self-only CSP); the new script is `git-places.js?v=<release>`.
(4) Tests: `HostGitPlacesTests` in tests/test_host_git.py (real git), `GitPlacesTests` in
tests/test_git_progress.py (fake helper), tests/test_git_places_ui.js; the release-check
workflow now runs test_host_git.py and both git UI suites. Preserve: no tokens or command text
in the manager, pending saves block moves and reconnects, one registration per lab, retire only
on a destination change, overlap and root-versus-subfolder rules on the VM. Prepared on
`claude/git-folder-browser` from main 609fd4b and live-validated on the dev VM (VALIDATION.md);
no push of the source and no image publication is implied.

# Map positions, destroy cleanup, Grafana on demand — 1.26.0

Read docs/CHANGELOG.md "Changes in 1.26.0", docs/TELEMETRY.md and docs/LAB-OPERATIONS.md.
(1) Map positions: `parse_drawing` returns `placed` (True when at least one annotation
node carried a position) and `topology.unplaced(drawing)` tells a default-grid drawing
from a placed one (a drawing without the key, saved before 1.26.0, is judged by its
coordinates against `grid_position(i)`). `PUT /api/labs/{id}/layout` sets `placed=True`
(a person's layout is never replaced). `POST /api/operations/parse-yaml` takes
`options.annotations` (the text of `<topology>.annotations.json`, read by the browser
through the helper's `read` mode, which allows `.json`) and answers `annotations_used`;
a broken file falls back to the grid. In operations.js `opParse(path, text)` reads the
file and parses, `opWorkspaceForm(path, source, parsed)` adds the `annotations` part to
the `/api/lab-definitions` form, and Validate/preview, Save to manager and Deploy lab
all go through them (`opMapPreview` takes a third argument for its note). In
`discovery.update_sources` a linked lab whose drawing is `unplaced` takes
`candidate['drawing']` from a bundle that carries annotations (event
`topology.positions`); everything else still waits for Sync from VM
(`test_vm_files.test_annotations_beside_the_deployed_topology_place_a_grid_only_map_without_a_sync`).
(2) Destroy: `opDestroyOptions(caps)` returns `{cleanup:true}` unless
`caps.actions.destroy.cleanup === false`; both the menu's Destroy and the quick button
use it, the "+ cleanup" extras are deploy/redeploy only; the helper's plan logic is
unchanged. (3) Grafana on demand: `deploy/compose.telemetry.yml` has
`container_name: clab-manager-grafana`, `restart: "no"`, Prometheus
`--storage.tsdb.retention.time=15m` plus `--storage.tsdb.min/max-block-duration=15m`
(hidden Prometheus flags; keep them together with the pinned image and never add a
`=true/false` flag) and 64 MB tmpfs volumes. `setup_telemetry.py` writes
`TELEMETRY_GRAFANA_IDLE_MINUTES` (default 15, 0-1440, 0 = never stop) and knows
`GRAFANA_CONTAINER`; `setup-telemetry.sh` runs `stop grafana` after the `--wait` gate
(test_telemetry_setup checks the order). `host_operations.py` mode `grafana` with
`action` status/start/stop runs `docker start|stop -t 10|inspect` of that fixed name
only. `app/grafana_control.py` (`GrafanaControl`, `app.state.grafana`,
`GET /api/telemetry/grafana`, `POST /api/telemetry/grafana/start|stop`, monitor thread
`run()`/`close()` in the lifespan after telemetry) probes `/api/health` and sums
`grafana_http_request_duration_seconds_count` over every handler except `/metrics` and
`/api/health` (`activity()`); a changed sum is a viewer; stop after the idle time once
`GRACE` (90 s) has passed since the start; a failed stop backs off 300 s; the counter
baseline is taken at start. `static/grafana.html` + `grafana.js` (in verify-release
FIELDS and in the CI node list as tests/test_grafana_ui.js) take only `#path=` and
`#title=`, validate the path against `^/d/[A-Za-z0-9_-]+(\?[A-Za-z0-9_=&%+.-]*)?$` and
build the origin from `location` plus the manager-announced port; app.js
`renderGrafanaLink` links there (`grafanaLaunch(lab)`, `grafanaPath(lab)`; `grafanaUrl`
is gone). `openTelemetrySettings` shows `telemetryGrafanaText` and a "Stop Grafana now"
button. `check_install.check_telemetry_dashboards` reads `/api/telemetry/grafana`:
`running is False` means PASS "provisioned and stopped" after the Prometheus and maps
checks, without any Grafana request; `deploy/telemetry/smoke.py` stops and starts the
container and expects the dashboards, map and Flow panel back. Store: `WINDOW=900`,
`WINDOWS=(300, 900)`, `POINTS=130`. The POST routes of the guard need a body
(`content-length` 0 is refused), so the page posts `{}`.

# Documentation and installation audit — 1.25.0

Read docs/CHANGELOG.md "Changes in 1.25.0", docs/REPOSITORY-MAINTENANCE.md and
docs/INSTALL.md. (1) Telemetry UI: `static/telemetry.js`, `telemetry-charts.js` and
`tests/test_telemetry_ui.js` are deleted; `topology-render.js` and `style.css` are
byte-identical to their 1.22.0 versions (no `tele-*` classes, `data-link-index` or
`tele-dot`), and `capture.js` handles link right-clicks itself again. Never put a
stroke rule (a `stroke-dasharray` above all) on `.topology-wire path` without
excluding `path.capture-hit`: the 16 px transparent hit path uses
`pointer-events: stroke`, so a dashed stroke makes the hover zone flicker along the
wire (the bug this release fixed). The only telemetry UI left is `renderGrafanaLink`
in app.js (reads `lab.telemetry.grafana` = `{enabled, port, map_uid}` from
`TelemetryManager.grafana_link`, now part of `lab_summary`) and
`openTelemetrySettings` in operations.js (Lab actions → Telemetry settings…; reads
`/api/labs/{id}/telemetry`, PUTs `settings`, POSTs `retry` and `remove-config`). The
`/series` and `/bgp-series` routes are gone and `WINDOWS` is no longer imported;
`TelemetryStore.series()` stays for the store tests. (2) Install flow:
install-manager.py phases are 1 admin, 2 prerequisites, 3 `start-manager.sh
--manager-only`, 4 `setup-capture.sh`, 5 `setup-telemetry.sh`, 6 verify, 7 engineer
access; menu 4 = both stacks (`stacks()`), 5 = check, 6 = exit. `start-manager.sh`
runs `setup-capture.sh --no-recreate` and `setup-telemetry.sh --no-recreate` after
`setup-vm.sh` and before the image build unless `.env` has
`CAPTURE_PROVIDER=disabled` / `TELEMETRY_STACK=disabled` or `--manager-only`
(test_release_consistency checks that order). Both setup scripts end with
`recreate-manager.sh` (`up -d --no-build --no-deps backup-ui` when a container exists)
unless `--no-recreate`; both accept `--remove` (`setup_capture.py --remove` writes
CAPTURE_PROVIDER=disabled and keeps the token); `setup-telemetry.sh` runs `setup-vm.sh`
when the data directory is missing; VM scripts call `verify-release.py --runtime`.
`check_install`: capture and dashboards are WARN (not INFO) when disabled, the capture
title is *Browser Wireshark capture*, advice is built with `ctx.repair`, `ctx.command`
and `ctx.compose` so every `Next:` is absolute; check_host's constants use `SOURCE`.
(3) Release tracking: `verify-release.py` gained `verify_docs()` (rules in
REPOSITORY-MAINTENANCE.md: living docs name only the current release, history as
"since x.y.z"/"x.y.z or later", third-party versions named by component, no
`projects/v1.x.y` or `clab-backup:1.x.y`, and README/CHANGELOG/VALIDATION/this file
must lead with the current release); the default run does both checks, `--runtime`
only the lockstep set. `set-release.py NEW` rewrites FIELDS and the current-release
tokens in living docs (history phrases untouched). To cut a release: run set-release,
write the three history sections, run verify-release. Docs convention: source folder
`~/projects/clab-manager`, absolute commands (`bash "$HOME/projects/clab-manager/deploy/…"`),
no version pins in guide headings; docs/DOCKER-HUB-SETUP.md and the 1.15.1 audit
narrative are in docs/archive/. (4) See VALIDATION.md "Documentation and installation
audit — 1.25.0" for what was run on the dev VM.

# Grafana lab map — 1.24.0

Read docs/GRAFANA-MAP.md and docs/CHANGELOG.md "Changes in 1.24.0". (1) `app/telemetry_map.py`
is pure (stdlib + telemetry_names/telemetry_metrics): `render(drawing, lab)` draws the
SVG from the bound drawing with the same geometry as `static/topology-render.js` (node at
x+20/y+20, 40 px body, wire radius 20/max(|ux|,|uy|), label offsets) and returns the Flow
panel cells; `dashboard(lab, drawing)` is the provisioned dashboard (uid `clab-map-` + 24
chars of the lab id, one `andrewbmchugh-flow-panel` panel with inline `svg` and
`panelConfig`, queries `clab_interface_receive_bits_per_second{lab=…}` →
`{{node}}:{{interface}}:in`, `clab_interface_oper_up` → `oper:{{node}}:{{interface}}`,
`clab_telemetry_node_state_code` → `state:{{node}}`). One SVG element per cell, ids
`cell-link:<short>:<drawn>`, `cell-rate:…`, `cell-port:…`, `cell-node:<short>`: the plugin
replaces the text of a leaf with one text node (the rate label starts as "↑" and
`separator: space` appends the value), sets fill/stroke on the cell's elements and only
sets animation-duration/direction, so the dash keyframes live in the SVG `<style>`. A half
link binds to the FAR end's receive series (cEOS containers report zero transmit octets);
unmatched drawing nodes get static grey elements without cells. The panel configuration is
emitted as JSON (a YAML subset) with `cellIdPreamble: cell-`, `datapoint: lastNotNull` and
a fixed canvas `background` for both themes. (2) `MapPublisher` writes
`<store.root>/telemetry/dashboards/<uid>.json` (0644, atomic) from `TelemetryManager.scan`
via `publish_maps` (signature = lab id, name, drawing revision, node identities), deletes
files of vanished labs, removes all generated files while the stack is disabled, never
raises (`stats()['error']`). (3) Deployment: `setup_telemetry.py` writes
`TELEMETRY_MAPS_DIR` (default `/srv/containerlab-node-manager/data/telemetry/dashboards`,
created for uid 10001; refuses when the data directory is missing, before touching .env),
creates `TELEMETRY_CONFIG_DIR/plugins` (uid 472) and `--plugin` installs the pinned Flow
panel with `docker run --entrypoint grafana <pinned image> cli --pluginsDir /plugins plugins
install andrewbmchugh-flow-panel 1.20.1` (as 472 when root, else the caller); compose
mounts both folders read-only (`GF_PATHS_PLUGINS=/var/lib/grafana-plugins`,
`/etc/grafana/dashboards-labs`) and `clab.yml` has a second provider (folder *Lab maps*,
`disableDeletion: false`, 30 s). `wait_ready` reports `flow_panel` from Grafana's
anonymous `/api/frontend/settings`; check_install warns without it or with `maps.error`.
Keep `PLUGIN`/`PLUGIN_VERSION` identical in setup_telemetry.py and telemetry_map.py
(tested). (4) UI: `telemetry.js` opens `grafana.map_uid` when the lab view carries one.
(5) CI smoke installs the plugin for real and provisions a generated map. Thresholds
(`TRAFFIC_LEVELS`, `FLOW`) are constants documented in GRAFANA-MAP.md.

# Telemetry live fixes — 1.23.1

Read docs/CHANGELOG.md "Changes in 1.23.1" and docs/TELEMETRY.md. Everything below was
found by running 1.23.0 on the dev VM (cEOS 4.35.0F) and is verified there; keep it.
(1) `deploy/compose.telemetry.yml`: Prometheus (kingpin) boolean flags take `--flag` or
`--no-flag`; `--flag=false` aborts start-up with "unexpected false" and the stack
crash-loops while every Grafana panel shows "An error occurred within the plugin". Never
add such a flag; `test_telemetry_setup` rejects `=true/=false` command entries.
`deploy/setup-telemetry.sh` calls `setup_telemetry.py ENV --wait` (`wait_ready`) after
`up` and exits 1 with `compose ps` and `logs` when Prometheus `/-/ready` or Grafana
`/api/health` do not answer within 90 s; CI runs `deploy/telemetry/smoke.py` (stdlib
only: fixture manager on a free port, real stack, data source health, three provisioned
dashboards, every panel and variable query, anonymous `/api/ds/query`). (2)
`telemetry_store`: device timestamps order the samples of ONE leaf only
(`Series.accept`, per-leaf `stamps`; records with `synthetic=True`, whose device time
the collector replaced, are never compared); rates, chart points, `at` and `last_sample`
use `record['received']` (the collector's receive time; the store falls back to `ts`).
cEOS stamps each notification with the last change time of its leaves, so one cycle is
several notifications minutes apart; the old per-interface clock dropped half of them.
`POINT_MERGE` (5 s) joins the notifications of one cycle into one chart point and
`Series.rates` keeps the newest rate per field so a direction never flips to n/a between
two notifications. (3) `EosAdapter.subscriptions`: the on-change state leaves carry
`heartbeat_interval=SAMPLE_NS` because cEOS answers a plain on-change subscription with
the sync marker only (no initial value); verified with a raw pygnmi probe. (4)
`NodeCollector`: a group without notifications for `GROUP_IDLE` is reported `idle` and
stays subscribed (EOS sends nothing for an empty sampled path such as BGP without
neighbours); it returns to subscribed/streaming when data arrives; never close it as
failed. (5) `TelemetryManager.schedule_retry`: reason `connect` caps the backoff at
`RETRY_CONNECT_MAX` (30 s) because a `docker restart` keeps the node's signature and
nothing else resets it; other reasons keep doubling, `auth` stays at `RETRY_MAX`. (6)
cEOS in a container reports 0 transmit octets on data ports; TX rates of 0 on cEOS links
are the platform, not a bug. (7) `check_install.check_telemetry_dashboards` reports a
Prometheus that does not answer separately (compose ps/logs hint) and classifies scrape
errors with `scrape_problem` (never echoes them). Hot-loading changed `app/*.py` into the
running manager container with `docker cp` + `docker restart` is a fast way to try a
fix on the VM before the full `start-manager.sh` rebuild; the final validation must come
from a re-stage of the commit. See VALIDATION.md "Telemetry live fixes — 1.23.1".

# Automatic network telemetry — 1.23.0

Read docs/TELEMETRY.md and docs/CHANGELOG.md "Changes in 1.23.0". No live device was
touched in this session; VALIDATION.md "Automatic network telemetry — 1.23.0" lists
what is fixture-only. Facts to preserve. (1) The collector is in-process:
`app/telemetry.py` (`TelemetryManager`, started in the lifespan after the readiness
monitor) owns a per-node state machine (disabled, waiting, configuring, connecting,
streaming, stale, unsupported, failed) and only starts work for a running node of a
linked lab whose `lab['telemetry']['auto']` is true, after
`NodeServices.checks[(lab, node)]['status'] == 'reachable'` (the readiness monitor's
real `show version` answer), and never while `operation_busy` or a backup/test job
runs for that lab. `streaming` is set only by an accepted record in the store
(`ingest_one`) or a collector `group streaming` event, never by a login or a commit.
(2) `app/telemetry_provision.py` opens a paramiko shell with the node's SSH login,
runs `adapter.show_commands()`, applies only `plan.add` with the NOS's scoped commit
(EOS running-config only, never `write`; XR `commit`; Junos `configure private` +
`commit and-quit`), reads again to verify and records the exact lines in
`lab['telemetry']['applied'][node]`; `mode='remove'` deletes only those recorded
lines. Adapters live in `app/telemetry_adapters.py` (EOS 6030, XR 57400 in plain text: the
adapter ensures `no-tls` and records it as manager-owned, the operator's choice; Junos
Evolved 32767 clear-text; XR paths carry the
`openconfig-interfaces:`/`openconfig-network-instance:` origin, the others none;
`subscriptions(group)` returns fallback variants, EOS state on-change first).
(3) `app/telemetry_collector.py` uses pygnmi: `connect()` calls `capabilities()`
itself and raises on a refused login; the transport recorded on the node is tried
first and the other only after a transport error; `first_update` polls
`subscriber.peek()/error` so a rejected variant fails in seconds, not after the 45 s
first-sample timeout; `normalize()` flattens prefix+path+JSON/typed values into
canonical leaf paths (module prefixes stripped, keyed lists expanded) before
`classify()`. (4) `app/telemetry_store.py` is memory only: rates from counter deltas
over device time, resets (value < previous) and gaps > 300 s give no rate,
out-of-order samples and foreign generations are dropped; bounds POINTS 400,
96 interfaces, 64 peers, 512 nodes; `_expire` is destructive. A generation is a
fresh uuid per boot cycle and per provisioning attempt (`TelemetryManager.new_generation`),
so a redeploy at the same address never merges. Runtime signature changes,
lifecycle operations (`review_operations`), removal (`forget_lab`) and reset clear
buffers. (5) Settings: `app/telemetry_settings.py` `default_settings()` is attached
to labs created by inventory upload, YAML registration and VM import; older labs
have no key and stay `decided=False` (no device writes) until
`PUT /api/labs/{id}/telemetry/settings`. gNMI needs a password login; key profiles
fail with an actionable message. `TELEMETRY_COLLECTOR=disabled` turns it off.
(6) UI: `telemetry.js` (`var teleState`, `renderTelemetry` from `render()`,
`refreshTelemetry` polls at most every 4.5 s on the telemetry/topology tabs,
`applyTelemetryOverlay` sets `tele-*` classes on `[data-link-index]` wires and
`[data-map-node]` devices, `openLinkMenu` reuses `nodeMenu`), `telemetry-charts.js`
(pure SVG). `topology-render.js` adds `data-link-index` and a `tele-dot`;
`capture.js` delegates link right-clicks to `openLinkMenu` when defined.
(7) Optional Grafana stack: `app/telemetry_metrics.py` renders Prometheus text at
`/api/telemetry/metrics` from `lab_view()` (names, rates, states only; stale series
keep state but drop rates); `deploy/compose.telemetry.yml` runs Prometheus v3.14.0
and Grafana OSS 13.0.2 by digest with `network_mode: host`, tmpfs volumes and
limits; `deploy/setup_telemetry.py` writes `TELEMETRY_STACK`, ports, bind, a kept
admin password and `TELEMETRY_CONFIG_DIR` into `.env` and renders
`/srv/containerlab-node-manager/telemetry/prometheus.yml` for the real `UI_PORT`;
dashboards are generated JSON under `deploy/telemetry/grafana/dashboards/` (uids
`clab-lab-overview`, `clab-interface`, `clab-bgp`; `test_telemetry_setup.py` checks
they only use exported metric names); the manager announces `{enabled, port,
prometheus_port}` as `grafana` in `/api/telemetry/health` and the lab view, and
`telemetry.js` builds links from `location.hostname`. (8) Tests:
`tests/test_telemetry_*.py` (the gNMI server test drives the real
pygnmi client), `tests/test_telemetry_ui.js`, fixtures under
`tests/fixtures/telemetry/` (modelled on the models and public examples, not
captured from the lab images). CI runs `test_telemetry*.py` and the UI file.
Version markers are 1.23.0 in lockstep (verify-release.py). Prepared source only:
no push, image build, VM deployment or live NOS validation happened here.

# Deploy-first UI and automatic NOS login — 1.22.0

Read docs/CHANGELOG.md "Changes in 1.22.0". (1) `inventory.DEFAULT_CREDENTIALS` holds the
login containerlab documents for each supported kind; `runner.effective_credentials`
falls back to it after profiles and inventory logins, `runner.credential_source` names
the origin, and the public node row carries `credential_source`, `login_configured`
and `nos_login`, with `nos_readiness` on the lab. Keep the order profile > inventory
> default and never add a kind default that is not published on containerlab.dev.
(2) `app/node_readiness.py` (`ReadinessMonitor`, started in the lifespan) probes
running nodes in linked labs (fresh discovery, `node_available`, never during a lab
operation) by SSH login plus `show version` over an exec channel (`cli_answers`,
judged with `runner.CLI_ERROR`; SSH can authenticate while the cEOS CLI is still
starting), stores results in `NodeServices.checks` with `source: 'automatic'`,
forgets a node whose runtime signature changes, reports a refused login only after
three consecutive refusals, submits one `test` job per boot cycle through
`runner.submit(..., source='automatic')` (jobs now carry `source`), and on a failed
automatic test (`review_tests`) sends the failed nodes back to booting and allows
`MAX_TEST_ATTEMPTS` tests per boot. `runner.job_environment` gives every
ansible-playbook run HOME = its temp dir and `ANSIBLE_HOST_KEY_CHECKING=False`: lab
containers regenerate SSH host keys on each deploy and the recorded keys in the
manager's `~/.ssh/known_hosts` made every job after a redeploy fail with "host key
mismatch" (seen live on the dev VM); never let a job read or write a shared
known_hosts again. For linked labs
`ssh_ready` requires `nos_login.status == 'ready'`; unlinked labs keep the old rule
(login configured). Tests build a linked lab with a fresh discovery snapshot and an
inline pool (tests/test_node_readiness.py). (3) `vm_files.prepare_lab` fills a blank
saved login from the generated inventory on sync and never replaces a saved one. (4)
operations.js `opSaveWorkspace` registers the workspace (POST /api/lab-definitions,
PUT operations-settings) before a Deploy lab review; `openDeploy` opens the topology
browser from the landing page and header; `opJobBanner` is the pure function behind
the operation banner. (5) capture.js reads the lab drawing (`/api/labs/{id}/topology`)
once per dialog open and lists the node's wired ports first (`mapInterfacesFor`); the
other live interfaces render in `capture-interfaces-all`, so `captureChecked()` reads
both lists; scope, search and target live in the `capture-advanced` details, which
unfolds only when no target resolved; a link opens on its first endpoint. (6)
management.js `renderLanding` and `renderNosReadiness` draw the landing page and the
deployment-bar readiness line; `vm-reset-key` defaults to checked. New browser tests
(`test_readiness_ui.js`, plus `test_vm_password_ui.js` and `test_download_ui.js`) and
`test_node_readiness.py` / `test_vm_files.py` run in CI. Validated on the dev VM; see
VALIDATION.md "Deploy-first UI and automatic NOS login — 1.22.0".

# Browser Wireshark fixes — 1.21.1

Read docs/CHANGELOG.md "Changes in 1.21.1" and docs/CAPTURE.md. Three facts learned on the live
VM must survive future edits. (1) The pinned wireshark-vnc-docker image's websockify
answers HTTP 400 to any WebSocket handshake that does not offer the `binary`
subprotocol; the service then closed before accept, which Starlette reports as 403,
so every 1.21.0 viewer failed. capture_service.desktop and capture_sessions.desktop
offer VNC_SUBPROTOCOL upstream and echo it only when the client offered it (noVNC in
that image offers none, and a browser drops a reply that ignores its offer). (2) The
Docker archive API and docker cp read the container filesystem through the daemon:
volumes are visible, a tmpfs mounted inside the container is not. /pcaps is
therefore a tmpfs-backed anonymous local volume (PCAPS_VOLUME_OPTIONS, labelled,
removed with v=true, dangling ones swept by cleanup_orphans); /tmp and /config stay
container tmpfs, so smoke.py reads /tmp with docker exec tar and saves into /pcaps
with docker exec tar -x, never docker cp. (3) Compose only restarts containers whose
service config hash is unchanged even when the project network was renamed, so
setup-capture.sh runs up with --force-recreate --remove-orphans; keep that. The
service refuses a directory-only archive with 409 (tar_has_regular_file on the first
64 KiB chunk), the manager passes the service's own detail through, and
capture-session.js fetches the download first and only then hands the URL to the
browser (tests/test_capture_session_ui.js). Validated on the dev VM; see
VALIDATION.md "Browser Wireshark fixes — 1.21.1".

# Browser Wireshark — 1.21.0

This supersedes the 1.20.x workstation handoff instructions below. Read docs/CAPTURE.md.
Browser sessions replace all native workstation launches; cshargextcap only runs
inside the pinned VM Wireshark image. capture.py keeps Edgeshark discovery and HMAC
identity fields (exclude interface churn). capture_sessions.py is the manager
adapter and same-origin HTTP/WS relay; capture_service.py alone has Docker access.
Never expose its socket/API to browsers or accept client image/command/mount/URL
parameters. Preserve browser cookie ownership, fixed network/image, labels,
revalidation in both manager and service, resource limits and expiry/cleanup.
setup-capture.sh/setup_capture.py migrate the old public URL and preserve other
.env values and the service token. Service restart deletes its labelled temporary
sessions; never delete other lab containers or manager data. Keep pinned image
values consistent. See VALIDATION.md: local mocked/transport checks and CI smoke
configuration do not establish a real VM capture until smoke/live acceptance runs.

# Wireshark capture — 1.20.0 (Codex) and 1.20.1 fixes

Read docs/CHANGELOG.md "Changes in 1.20.0/1.20.1" and docs/CAPTURE.md. The provider boundary is
app/capture.py (Edgeshark only, explicit factory, no client-supplied URLs) and the
dialog is static/capture.js; everything else only registers routes and entry points.
Contract verified live on the dev VM against Edgeshark packetflix 0.9.7: the real
/discover/mobyshark payload passes normalize_targets, and the manager-built
`packetflix:ws://.../capture?container=<json>&nif=a%2Fb` URI streams valid pcapng with
one IDB per interface (Packetflix decodes the percent-encoded slash). Keep
IDENTITY_FIELDS (name, type, prefix, netns, pid, starttime) as the HMAC input and keep
the interface list OUT of it: selected interfaces are re-validated at launch, and
hashing the whole list made every container start/stop on the host (a new veth)
invalidate a selected host-namespace target. Do not describe Packetflix's
`container=` identity as a stale-namespace check: 0.9.7 captured with a wrong pid,
starttime, name and even another live netns; only re-discovery at Prepare and the 60 s
link expiry guard against reuse. merge_shared_namespaces applies only to the unfiltered
host view (lab/node views must keep every container row for exact name matching);
host-networked containers such as the manager share the host netns and are listed as
aliases of the init entry. normalize_targets skips and counts malformed rows but still
fails closed on a bad shape or when no row validates. capture.js: Prepare needs a target
plus a ticked interface (an imported-port hint renders ticked); captureActionAttrs()
disables node/menu Capture only when the manager reported capture disabled; the search
box is disabled during discovery, so typing cannot race an in-flight refresh.
check_install.check_capture is INFO when disabled, PASS/FAIL from a read-only
/api/capture/targets through the manager. Enabling capture needs the three CAPTURE_*
values in clab-backup-ui/.env of the source folder start-manager.sh runs from, then a
recreate. The workstation needs cshargextcap and the SSH tunnel; the manager cannot
observe whether Wireshark opened or packets arrived.

# Engineer access for VS Code — 1.19.4

Read docs/CHANGELOG.md "Changes in 1.19.4" and docs/FRESH-VM-GUIDE-V2.md "VS Code Remote -
SSH and the Containerlab extension". deploy/setup-engineer-access.sh is the
only place that grants an ordinary account docker and clab_admins, makes the
trusted lab roots (read from /etc/clab-manager/operations.json) group-writable
clab_admins setgid folders and restores containerlab SUID; it records the account
in /etc/clab-manager/engineer.json. start-manager.sh must keep calling it with
--refresh after setup-operations.sh, because setup-operations resets the projects
root to root:root 0755 and install-prerequisites strips SUID on a fresh
containerlab install; --refresh must stay a no-op without engineer.json or
operations.json. install-manager.py asks for it only when operations are enabled,
runs it as phase 5 after verification, and offers it as menu option 3 (Check is 4,
Exit is 5). check_host._engineer reads both JSON files with cat through the
privileged runner, is INFO when unconfigured and FAIL naming each missing piece.
host_operations.py create publishes 0664 in a setgid parent, else 0644; keep the
0600 temporary. The manager never needs any of this and must keep working with
root-owned roots. Validated on the dev VM: fresh-login groups, mkdir in
/etc/containerlab as the engineer, sudo-less containerlab inspect, manager browse
and read of the engineer-created folder through the gateway.

# Bug-fix report follow-up — 1.19.3

Read docs/CHANGELOG.md "Changes in 1.19.3", docs/HEALTH-CHECK.md and docs/GIT-SETUP.md "One
repository, one subfolder per lab". diagnostics.failure_hint must keep the
gateway/account/permission fragments ahead of the password rules ('authentication
failed', 'password setup required'): a bare 'password' match misreported the
reachable-account operations failure as a rejected password even though connected
discovery proves the password. lab_operations.operation_connection_error's
command-not-found text must contain "did not run the operations gateway" (the hint
keys on it) and must not tell the user to save the password. check_install's
http-browse next step branches on discovery connected. management.js: openVmDialog
plus maybePromptVmConnection prompt once when state.discovery has loaded and is
unconfigured, never for a configured or dismissed connection; test it by calling
context.maybePromptVmConnection (renderManagement needs app.js globals).
git-onboard.py: selected_registration calls ask_subfolder() for a fresh
registration and offers "new" for an already-registered checkout; new_binding labels
"repo / subfolder"; subfolder rules mirror host_git.relpath; the manager UI cannot
register (root, CLI or guided setup only); a root ('') registration and subfolders in
one repository overlap by design. success_banner colours only on a TTY. Validated on
a fresh Ubuntu 24.04 dev VM without KVM: probe browse/capabilities, a cEOS deploy
through the gateway, NOS login/backup and a subfolder Git save all passed;
check-install 57 pass / 0 fail. On Windows run app tests with
`python -m unittest discover -s tests -t tests -p test_X.py` from clab-backup-ui;
the WinError 5 state.enc rename flake remains and passes on isolated rerun.

# Post-install paste-in fixes — documentation on 1.19.2

docs/FRESH-VM-GUIDE-V2.md (step 3 and step 7), docs/INSTALL.md and docs/WIKI-MASTER-GUIDE.md
(Step 1.2, Part 5) now carry three copy-paste blocks; README links them. Clock:
after a Proxmox snapshot rollback with memory state the guest keeps the snapshot
time until timesyncd's next poll, so the fix is set-ntp true plus a timesyncd
restart; the manual `timedatectl set-time "... UTC"` sequence is only a
bootstrap when no time server is reachable, and set-ntp must be off for it.
WinSCP: the passwordless root SFTP sudoers rule is written with tee + visudo -cf
into /etc/sudoers.d/<owner>-sftp and tested with `sudo -k; sudo -n
/usr/lib/openssh/sftp-server </dev/null`; WinSCP keeps `sudo -n
/usr/lib/openssh/sftp-server` and check-install --require-admin-sftp verifies
the same rule. VS Code: the vscode-containerlab extension runs `id -nG` in the
VS Code server and refuses to activate without both clab_admins and docker
("Extension activation failed. Insufficient permissions..."), so the block
creates clab_admins, adds the engineer account to both groups and restores the
upstream 4755 SUID mode on /usr/bin/containerlab; the user must then kill the
VS Code server on the host and reconnect. The installer is unchanged: it still
strips SUID on a fresh containerlab install and keeps the suid_setup_done marker,
so the VS Code block must be rerun after a containerlab package upgrade. The
manager never needs these groups. docs/QUICK-INSTALL.md is the paste-only ordered
walkthrough of the same route; its prompt wording is copied from
install-manager.py, setup-password.sh (passwd) and git-onboard.py, so update
it when those prompts change. Documentation only; no version bump, no code
change, no fresh-VM run of the blocks by the author.

# Transport EOF and helper timeouts — 1.19.1

Read docs/CHANGELOG.md "Changes in 1.19.1". The 1.18.1 operations reader fix (wait for
stream EOF; exit status is metadata OpenSSH may send before draining the helper
pipe) now also applies to discovery.py inspect_host and git_progress.remote_git.
Keep all three loops identical in shape; new SSH readers must copy it and carry
the status-before-tail regression tests. host_files.py allows 25 s for
containerlab inspect and 8 s per label lookup; discovery waits 60 s
(INSPECT_DEADLINE) and check_install helper_request 60 s. Keep helper budget +
18 s file reads below the manager deadline. app.js's footer fallback is part of
the lockstep version set checked by verify-release.py. collections.yml pins
current major versions; raise deliberately after a Linux build test.
.gitattributes normalizes all text to LF; commit with git, not web uploads.
Prepared on published main 2d34415 (1.19.0) in branch
claude/transport-eof-and-helper-timeouts; no image build, fresh-VM run or live
device validation was performed. Windows full-suite runs can show WinError 5
on state.enc rename; rerun failures alone or trust Linux CI.

# Consolidated terminal installation — 1.16.0

Read docs/INSTALL.md. Ordinary users run deploy/install.sh, which delegates privileged
prerequisites/launcher tasks to sudo and keeps Git auth/config in the original
owner HOME. Retain step retry/cancel, existing data/password/.env and custom Git
registrations. APT media repair requires runtime confirmation and backups; other
sources/signature checks stay intact. Source --list reads only bounded public
registry descriptors before helper installation. No router labs are deployed.
Prepared on e64790a plus latest fetched main 0658562; no VM deployment is implied.

# Git owner and identity recovery — 1.15.3

Guided setup supports --guided --repo PATH for an existing checkout. Identity
prompts repair invalid values locally and keep valid values. Explicit sudo
registration stays noninteractive and reports the absolute guided recovery
command on failure. Preserve custom registration settings on retries. The guide
distinguishes source directory, config checkout, Linux owner and commit identity.
Based on merged main 0658562; no publication or VM deployment is implied.

# Guided Git setup recovery — 1.15.2

Reject GitHub browser page URLs before login/clone and reprompt for Code > HTTPS.
Keep the checkout in the ordinary owner's persistent home. Package failures must
identify APT recovery, without changing sources or bypassing signature checks.
docs/GIT-SETUP.md and the master wiki describe obsolete file:/cdrom source repair.
Prepared on main 698fabb; older release and audit notes below are historical.

# CLAB Backup Worker — Agent Instructions

## 1.15.1 repository consistency repair

GitHub main b0389ba had VERSION 1.15.0 with 1.15.1 app/helpers. Read
docs/REPOSITORY-MAINTENANCE.md and run deploy/verify-release.py before delivery.
The launcher checks consistency before host changes. Old root patch artifacts
and the unused deploy/clab_manager_files.py development shim were removed;
historical references below do not require restoring them. The production
installer still installs app/host_files.py under the original helper path.
Retain dotfiles in source packages and Git commits. Keep generated archives,
runtime data and credentials out of the repository and Docker context.

## Release 1.15.1 — guided Git setup

Read docs/GIT-SETUP.md first. `bash deploy/setup-git.sh` as the ordinary VM account
launches the wizard; explicit sudo registration and --refresh remain supported.
Standalone uses the existing Linux account, not a new engineer account. Keep all
Git, clone, config and GitHub login commands under that owner's account and HOME.
The wizard does not collect tokens, create remote repositories or publish commits.
It checks identity, GitHub write permission and registration readiness; a push dry
run cannot guarantee later commits pass branch rules. Never overwrite a nonempty
non-checkout, chown existing projects recursively, reset work or disable hooks.
Catch missing identity before export/staging. Retry the original preserved save.
Identical registration settings retain revision/anchor; --refresh retains bindings.
The user's setup log confirms their 1.15.0 manual HTTPS push succeeded. New 1.15.1
Linux interactive onboarding still needs VM validation; local tests are not that.

## Release 1.15.0 — Save lab progress to Git

The approved Git architecture is implemented as owner-scoped VM repository export,
commit and push. Read docs/GIT-PROGRESS.md. Save progress captures an explicit node scope
and frozen topology provenance, then exports only a complete immutable job snapshot.
Do not use the rolling latest directory or claim current topology for a legacy job.
Keep capture success independent of manager-internal Git failure and remote push.

The restricted host helper validates registered repositories and drops privileges
before Git, using the registered owner's external HTTPS credential helper. The
manager must not collect tokens, accept arbitrary Git command text, push unrelated
history, stage unrelated files, force push, stash or destructively reset a checkout.
Persist job IDs and host journals; retries reuse the same snapshot/commit. Guard
active operations and pending saves against reset/removal/rebinding/host identity
changes. Explicit Keep snapshot only dismissal retains backup files and commits.

The UI has no login: repository owner is an execution account, not web identity.
Version retrieval is download-only; live NOS restore adapters remain unavailable
until tested on each supported NOS. Existing backup schedules do not imply Git
publication. Version 1.15.0 is local source delivery, not a Hub publication, deployed
VM upgrade or live network-device validation. Preserve VM password restrictions,
persistent data, device credentials, diagram behavior and operation confirmations.

## Release 1.14.0 — UI Changes 2 and master wiki

The user authorized the UI changes from UI Changes 2.eml and a password-aware update
of their supplied master wiki. Sidebar actions are static and ordered; Topology is
the default tab, with Credentials/Action logs under More. The basic diagram editor
persists visual annotations only, with revision conflict checks and JSON/draw.io
exports. VM YAML and wiring are not edited. Preserve imported annotation styles.
docs/WIKI-MASTER-GUIDE.md supersedes its old key instructions and uses source builds by
default. The supplied Proxmox/Ubuntu sections are retained. Version 1.14.0 is a local
source delivery, not a published Hub image. Continue preserving password restrictions,
persistent data, device credentials and explicit host-operation review.

## Release 1.13.0 — VM account password

User requested password-only VM connections, superseding all key-retention instructions
below for the dedicated host account. Latest source cloned from origin/main 160fe5e.
Use deploy/start-manager.sh for setup/build/launch; first setup or key migration prompts
through passwd in an interactive VM terminal. --reset-password rotates explicitly.
Host password hash persists in /etc/shadow; manager credential persists encrypted under
/srv/containerlab-node-manager/data. API/UI no longer accept VM private keys. Legacy
key state cannot connect; saving the password removes its client key/passphrase and
preserves the VM fingerprint. Device credential key support remains intact.
The shared gateway is forced by a Match User clab-discovery policy in sshd_config;
setup verifies effective restrictions before reload and revokes old authorized_keys.
Preserve helpers/operations permissions, all labs/history and state.key on upgrades.
Read docs/VM-CONNECTION.md. This is local source delivery; no push or live deployment.


## Release 1.12.1 addendum — deployment navigation

Email UI changes approved. Deploy New Lab is same-tab navigation to an explicit
landing page; no automatic topology dialog. Lab Topologies filters .clab.yaml and
.clab.yml plus navigation folders in both UI and host helper before the 500-entry
limit. Start/Destroy on deployment status use existing preview/confirmation APIs;
Start selects deploy only for fresh Not deployed status, otherwise start. Unknown,
disconnected, busy and missing-source states disable the quick actions. Remove lab
remains manager-only. Source folder ~/projects/v1.12.1; update both helpers while
retaining keys. Hub image 1.12.0 is the last user-supplied reference, not the new UI.
Git fetch failed because this machine's git remote-https helper is unavailable;
no remote synchronization or push was performed for this release.

## Release 1.12.0 addendum — approved simplification

This supersedes the 1.11.0 feature inventory. Retain VM connection and document
setup/recovery in docs/VM-CONNECTION.md. UI token login and lock removed; retain
same-origin API/WS protections and SSH ticket/credential handling. Remove VM YAML
editing, path/link/folder lab shortcuts, separate layout menu, SSHX/GoTTY and fcli
from UI/API/helper/setup. Retain New topology, VM browser, clone/catalog, source
delete, lifecycle and favorites. Only interactive draw.io remains, with full
editable XML export (annotations, labels, grouping, colors and coordinates).
Inspect output is a table; topology header has SSH all / Backup all review.
Clear exclusion forgets ignored_labs without import. Start fresh is confirmed,
manager-only and preserves VM authentication/fingerprint. Its journal recovers
interrupted deletion; busy jobs/discovery/SSH prevent reset. Never reset real
user data for validation. Browser fixture and unit tests use isolated data.
Source folder ~/projects/v1.12.0; latest fetched origin/main 7c5cef6 exactly
matches the delivered 1.11.0 ZIP. Source packages/patches remain in ignored dist/.

## Release 1.11.0 addendum — approved lab-level operations

User approved all lab-level commands in LAB-COMMANDS-PLAN.md. This supersedes
older read-only-only scope statements for explicitly enabled host operations.
No individual node lifecycle/interface tools were requested. Read docs/LAB-OPERATIONS.md.
Host helper uses a forced SSH gateway, structured stdin, fixed argv, trusted roots,
review digests and one host flock. Keep Remove lab manager-only; VM source deletion
is separate and preserves recovery copies. Existing keys/data survive setup.
Operations, output and favorites persist; pending operations become Interrupted
on restart. Guard backups/sync/import/removal against concurrent operations.
Never operate real training deployments as a test without specific authorization.
VM source folder is ~/projects/v1.11.0. Latest origin/main b20468e matches the
1.10.0 delivery except three ignore files. Keep release ZIP/patches in ignored dist/.

## Release 1.10.0 addendum — setup preflight and import confirmation

User requested normal setup to avoid stale helpers and confirmation for VM imports.
Normal host setup/upgrade entry point is deploy/start-manager.sh: existing account
updates retain keys; first launch takes a public key and refuses replacing an
existing account's key. It verifies installed helper protocol/version, prepares
storage, builds and recreates Compose. It rejects another running manager using
the same data. Docker builds alone cannot mutate the host helper. Script remains
LF. VM connection/sidebar report inspection-only helpers before import attempts.
Background discovery now caches bundles in memory and advertises pending imports;
it MUST NOT save new workspaces. import-preview returns paths/counts/warnings and
a five-minute token bound to name, bundle digest, host revision and exclusion.
import requires that token, fresh files and a successful persistent save. Cancel
sends no commit. Import again previews without clearing exclusion; successful
confirmation clears it. Old allow-import endpoint returns 409 rather than bypassing
confirmation. Existing sync/settings/history remain intact. Tests cover rollback,
expired/changed confirmations, unauthenticated requests and old client paths.
VM source folder: ~/projects/v1.10.0 with deploy/ and clab-backup-ui/ directly inside.
Latest fetched origin/main 0c0182c matches 1.9.1 delivery except three ignore files.

## Release 1.9.1 addendum — automatic file lookup and UI retry

Use inspect's absolute YAML path and adjacent clab-<name> folder even without
Docker labels. Verified labels may supply a custom generated directory. The shared
stdlib collector is app/host_files.py, installed root-owned by setup-discovery.sh;
deploy/clab_manager_files.py is a development launcher only. Upgrade the installed
helper for 1.9.1 with --update-helper, retaining the existing SSH key.
Direct inspection also reads exact known files via SFTP over the same pinned SSH
connection, bounded by channel timeout/watchdog. It uses existing file permissions.
No directory scan, remote mutation or authorized_keys/Nornir reads are added.
New lab imports can skip bad optional files with warnings; existing sync remains
atomic and rejects inconsistent files. Never apply credentials from mismatched
inventory. Detected lab clicks call /api/discovery/import before manual fallback.
Expose only sanitized path/status reports. General Import a lab offers VM retry
for an unimported detected name. Retain remove/exclusion behavior and saved data.
VM source folder convention: ~/projects/v1.9.1 contains deploy/ and clab-backup-ui/.
Latest fetched GitHub d84c76b matches 1.9.0 delivery except three ignore files.

## Release 1.9.0 addendum — remove saved lab

Remove lab deletes only saved workspace/job metadata. Retain backup files and
shared audit logs; never issue Containerlab lifecycle commands or delete host files.
The UI confirmation describes the exact scope. Block removal during this lab's
queued/running jobs. Default persistent ignored_labs entries prevent background
reimport (including in-flight polls). Import again clears an exclusion; the dialog
also permits immediate rediscovery for testing. Manual YAML import/linking clears
its matching exclusion. Preserve other labs and host credentials. No helper or
SSH key upgrade is required from 1.8.0.

## Release 1.8.0 addendum — automatic VM file import

The user authorized reading deployment files through the existing SSH connection.
The restricted helper now reads the original YAML, adjacent annotations, generated
inventory and topology export using verified deployment metadata. No arbitrary
commands/paths, disk scanning, host metrics or lifecycle actions were added.
`deploy/clab_manager_files.py` is installed root-owned and uses stdlib only.
`app/vm_files.py` validates bundles and prepares atomic settings-preserving imports.
New deployed labs import automatically; existing workspaces require Sync from VM.
Only source hashes/paths/status are public. Raw file bundles stay in memory; accepted
YAML, drawings and normalized credentials persist through the existing Store.
Keep old-helper/direct inspection compatibility. Missing labs/files retain state.
Read docs/archive/FRESH-VM-GUIDE.md for fresh Ubuntu setup and helper/key-preserving upgrades.

## Release 1.7.0 addendum — standalone persistent manager

The user explicitly authorized host SSH discovery, overriding earlier statements
that the worker must not connect to its host. Scope is fixed read-only inspection;
do not add host metrics, Docker socket mounts or lab lifecycle commands.

Default compose.yml now runs independently of containerlab, with Linux host
networking, UI port 8081, fixed project name and a /srv/containerlab-node-manager/data
bind mount. Image UID/GID are both 10001. Read docs/STANDALONE-SETUP.md for setup,
restricted SSH helper/account, migration, key handling and old-worker removal.

app/discovery.py owns YAML registration, optional layout import, VM configuration,
30-second SSH polling, 90-second freshness, host-key pinning, exact container
matching, and automatic-address updates. Original YAML and host credentials live
only in encrypted state; main.py excludes them from public responses. First-use
VM host-key trust is explicit in the UI. Errors/logs never include raw SSH output.
Host configuration revisions prevent stale in-flight results from being applied.

Saved labs use deployment_name/container_prefix; names are unique per configured
VM. One host connection per manager is intentional. Manual node endpoints are
preserved. New YAML nodes are automatic; legacy inventory endpoints remain manual.
Stable node names retain history even when a deployment name changes. Discovery
does not delete saved workspaces or deploy/restore device configurations.
Linked schedules require a fresh Running lab; manual actions require a fresh,
matched running node. Unlinked legacy labs retain their prior connection/schedule
behavior. Use Update lab YAML to link/migrate an existing workspace deliberately.

Keep setup/migration shell scripts LF-terminated for Linux. Source delivery remains
ZIP plus verified patches; do not claim Docker/Linux deployment or GitHub push.

## Release 1.6.1 addendum — v2 repository

Current repository: https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2.
Baseline is `06b8624` (1.6.0 upload); changes prepared on `codex/map-import-fixes`.
This addendum supersedes the older repository/baseline and demo-only validation below.
The user supplied the actual BGP annotation, YAML, export, and inventory files.

Drawing schema 3 fixes top-left node coordinates, legacy unsized note margins,
explicit shape opacity, endpoint offsets, and XRv9k exported interface aliases.
Regression fixtures in tests/fixtures/map preserve geometry with credentials and
connection details removed. Do not add raw uploaded files or preview state to source.
Both YAML and topology-data imports produce the same 13 nodes and 16 links.
Right-click SSH was connected to a local fixture; right-click backup selected only
PE1 through the real API with background execution stubbed. No live NOS was touched.
Versioned static URLs prevent older browser assets from hiding the menu after upgrade.

See docs/archive/FRESH-IMAGE.md before replacing the worker: the supplied YAML has no /data mount.
Preserve its data and encryption key before recreation. The screenshot was v1.5.0;
verify the actual running container and footer are 1.6.1, then reimport the drawing.
Keep source ZIP/patch delivery; no GitHub push, Docker build, or deployment is implied.

## Release 1.6.0 addendum

The user approved the demonstrated map design. The application name is now
**Containerlab Node Manager**. SuperPuTTY downloads use `<lab-name>.xml` via the
server Content-Disposition header. Keep the existing image/repository identifiers.

`app/static/topology-render.js` renders whitelisted drawing styles and measured SVG
bounds. `topology.js` adds an accessible right-click menu for SSH, backup and details,
plus expanded map mode. The importer stores drawing schema 2 and avoids duplicate
nodes when topology-data keys are long names and annotations use short names.
Old schema drawings stay readable but must be reimported to recover discarded styles.
This is not the complete upstream VS Code renderer. No actual user topology files
were supplied; visual approval used demonstration data. See NODE-FEATURES.md for limits.

## Release 1.5.0 addendum

Topology map import and SuperPuTTY XML export are implemented in app/topology.py
and static/topology.js. Read NODE-FEATURES.md for schema limits and credential rules.
Drawing nodes bind only to unique inventory aliases; raw YAML/configs are not retained.
Password export is opt-in. The inventory list remains available.

## Release 1.4.0 addendum (2026-09-10)

The former product name was **Lab Fabric**; the current name is **Containerlab Node Manager**. It uses the approved coral `#F15B40`,
slate `#416377`, cyan `#79E8F6`, peach `#FFAA99`, gray and white palette, with an
original fiber-line mark. Do not add company branding, service-provider/ISP themes,
or Segment Routing/EVPN motifs. Node details are a right-side drawer. SSH and backup
actions remain on each node row; login tests and connection editing are in the drawer.

Host resource utilization was explicitly removed at the user's request. Do not
reintroduce collectors, Docker host access, CPU/memory displays, or host mappings.
Legacy monitoring values in encrypted state are ignored and omitted from public
state; preserving profiles, jobs, schedules, and snapshot files remains essential.

- `app/node_services.py` supplies on-demand SSH checks, node backup summaries,
  single-use terminal tickets, and origin-checked/authenticated WebSockets.
- Generic `ssh` profiles support Linux/unmapped nodes, with a generic default.
  They do not enable unsupported platform configuration backups.
- `Runner.submit(..., node_names=...)` targets named nodes independently of their
  inclusion in scheduled backups, without changing `next_run`.
- Interactive terminals permit commands allowed by the saved account. Automated
  backup commands and vendor drivers remain unchanged. Terminal assets are local
  under `app/static/vendor/`, with upstream licenses.
- Read `clab-backup-ui/NODE-FEATURES.md` for upgrades and `VALIDATION.md` for evidence.
  Source is prepared locally; no push, image build, or deployment is implied.
  Complete source ZIP and patches are in ignored `dist/`.

## 1. Purpose and baseline

Read this file before modifying the project. It is a handoff for the next coding agent, including architecture, established requirements, implementation details, operational context, and validation expectations.

- Repository: https://github.com/ArchRuger/CLAB-BACKUP-WORKER
- Document baseline: **2026-09-10**, application **1.2.0**.
- Source checked: GitHub `main` at `edeaa70` (`Update README.md`), following `adce15d` (`v5, fixed file names`).
- The user calls working directories/releases things such as `CLAB-Backup_V5`. Those labels are not necessarily the Docker/application semantic version.
- Re-check the current repository and version markers before changing anything. This document describes the baseline, not a guarantee that a later checkout is identical.
- This is an existing Python/FastAPI application with a plain JavaScript UI. Extend the existing implementation unless the requested feature genuinely requires an architectural change.

This file has the user-requested name `agent instructions.md`. Some agent tools automatically discover only `AGENTS.md`; do not assume automatic loading. Explicitly open this file, or reference it from the agent tool's repository instructions.

## 2. User context and collaboration

The user is a network engineer running a containerlab lab on Ubuntu, typically as `archtop` on `clab-2`. The worker backs up actual NOS configurations from Juniper cJunosEvolved, Cisco XRv9k, and Arista cEOS containers. The user accesses the browser UI and downloads configurations to Windows.

Historical examples, not application defaults:

- Lab: `BGP_TheoryToPractice`.
- Worker node: `Backup-Worker`, Linux kind.
- Network nodes include `GTW-1`, `GTW-2`, `PE1`, `PE2`, `UP-1`, `UP-2`, and `IXP-L2-Switch`.
- Host interface: `ens18`; previously reported address `10.150.2.212`.
- Published NOS SSH ports have started at `30000` in this lab.
- Images used include cJunosEvolved `26.2R1.7-EVO`, XRv9k `24.3.1`, and cEOS `4.35.0F`.

Never hardcode these addresses, names, image versions, or port assignments. Obtain current deployment details when needed.

Working expectations:

1. Inspect the latest source and preserve existing user changes. Use a separate branch/worktree when the working tree contains unrelated work.
2. For feature requests, briefly list the intended changes before implementation. If the user explicitly requests approval first, wait for that approval. Once the scope is approved, complete it without repeatedly asking for the same permission.
3. Preserve functioning EOS/IOS-XR/Junos backups and existing stored history.
4. Report what changed, how it was tested, the release version, and precise build/deployment instructions.
5. Distinguish prepared source from pushed commits, a built image, and a deployed container. Do not claim a GitHub push, Docker build, or live-device test that did not happen.
6. The prior delivery workflow was a complete source ZIP plus a patch; the user uploaded the changes to GitHub. Continue that workflow unless the current request authorizes a different one.

## 3. Product scope and architecture

The worker is a browser-managed configuration collector. It imports inventory data, stores connection profiles, connects over SSH to each device's NOS, retrieves configuration, writes snapshots, and serves downloads.

Runtime flow:

1. Browser loads static HTML/CSS/JavaScript from FastAPI.
2. User unlocks the UI using the worker's access token.
3. Browser sends authenticated REST requests to FastAPI.
4. FastAPI uses `Store` for state and `Runner` to queue backup/login-test jobs.
5. `Runner` starts an `ansible-playbook` subprocess using a generated, private inventory.
6. Ansible `network_cli` with Paramiko and a vendor driver connects to the NOS SSH service.
7. A custom callback writes private result events to a temporary JSON Lines file.
8. `Runner` consumes the events, updates UI-visible state/logs, validates returned text, and writes successful backups.
9. Successful configurations are recorded in local Git history; FastAPI serves individual files or an assembled ZIP.

Important scope boundaries:

- No Docker socket is mounted into or required by the application.
- No host VM credentials are required by the running worker.
- The worker does not discover containerlab files on the host; users upload generated inventories.
- It does not use `docker exec` to collect configurations.
- It does not back up VM disks, restore configurations, commit candidate changes, or write device startup configuration.
- Local Git history tracks collected configurations. It is separate from the application's GitHub source repository and does not automatically push anywhere.

Do not introduce device configuration writes or Docker/host control as a side effect of adding backup features.

## 4. Repository map

Paths below are relative to the repository root. Extracted deployment folders may put these files at a different depth.

| Path | Responsibility |
|---|---|
| `clab-backup-ui/app/main.py` | FastAPI factory, authentication/security middleware, REST endpoints, profile validation, download responses, static serving |
| `clab-backup-ui/app/store.py` | Encrypted persisted state, lock, atomic writes, token/key initialization, operational logs and rotation |
| `clab-backup-ui/app/inventory.py` | Bounded YAML/JSON inventory parser, kind aliases, supported platforms, connection input validation |
| `clab-backup-ui/app/runner.py` | Credentials/readiness, generated Ansible inventory, job queue/scheduler, subprocess execution, events, configuration writes and Git |
| `clab-backup-ui/app/downloads.py` | Download naming, short names, UTC timestamps, safe historical file lookup, metadata migration, archive names |
| `clab-backup-ui/app/ansible/backup.yml` | Controlled `cli_command` playbook for the selected backup or login-test command |
| `clab-backup-ui/app/ansible/ansible.cfg` | Ansible defaults, YAML inventory plugin, persistent-connection defaults |
| `clab-backup-ui/app/ansible/callback_plugins/backup_events.py` | Private task-start/result IPC, stdout capture, capture timestamp |
| `clab-backup-ui/app/static/index.html` | UI markup, views, dialogs and controls |
| `clab-backup-ui/app/static/app.js` | UI state, polling, forms, history, log viewer, authenticated downloads |
| `clab-backup-ui/app/static/style.css` | UI styling |
| `clab-backup-ui/app/__init__.py` | Application `__version__` |
| `clab-backup-ui/Dockerfile` | Runtime image, dependencies, non-root account, OCI version, startup command |
| `clab-backup-ui/compose.yml` | Optional Compose deployment, published UI port, external network and persistent volume |
| `clab-backup-ui/requirements.txt` | Python dependency ranges |
| `clab-backup-ui/collections.yml` | Ansible collections installed during image build |
| `clab-backup-ui/VERSION` | Release version text |
| `clab-backup-ui/tests/` | Backend, download, logging, optional SSH-fixture and JavaScript UI tests |
| `clab-backup-ui/README.md` | Operator workflow and deployment details |
| `clab-backup-ui/VALIDATION.md` | Test evidence and limitations |

Historical patch files may also be present at the repository root. They are delivery artifacts, not runtime inputs. Do not blindly apply an old patch to an already-updated tree.

## 5. Runtime and dependency model

The image uses Python 3.12 slim, Git, OpenSSH client, and `tini`. It creates the `worker` user with UID **10001**, prepares `/data`, and starts:

```text
uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8080 --workers 1
```

The application directory inside the image is `/opt/nos-backup`. `DATA_DIR` defaults to `/data`. Ansible collections are installed under `/usr/share/ansible/collections` and exposed through `ANSIBLE_COLLECTIONS_PATH`.

Key Python dependencies: FastAPI, Uvicorn, Paramiko, ansible-core, python-multipart, cryptography/Fernet, and PyYAML. At this baseline, ansible-core is constrained to `>=2.19,<2.20`, Paramiko to `>=3.5,<4`, while other ranges and collection versions are not fully locked.

The image records resolved packages at `/opt/python-packages.txt` and collections at `/opt/ansible-collections.txt`. A repeated build of the same source can resolve different dependencies. Do not describe a version tag alone as a fully reproducible build.

The frontend has no bundler, framework, package-install step, or third-party CDN dependency. Node is useful for the JavaScript test harness, not required in the runtime image.

## 6. Supported NOS behavior — preserve exactly

| Containerlab kind | Ansible NOS driver | Backup command | Download type/extension |
|---|---|---|---|
| `juniper_cjunosevolved` | `junipernetworks.junos.junos` | `show configuration \| display set \| no-more` | `cjunosevo` / `.cfg` |
| `cisco_xrv9k` | `cisco.iosxr.iosxr` | `show running-config` | `IOS-XR` / `.txt` |
| `arista_ceos` | `arista.eos.eos` | `show running-config` | `CEOS` / `.conf` |

All three use `ansible.netcommon.network_cli` with Paramiko. A login test runs `show version` instead of retrieving configuration.

### EOS regression history

EOS backups previously failed. The implementation lacked explicit enable handling. The preceding change added:

```yaml
ansible_become: true
ansible_become_method: enable
```

An optional `ansible_become_password` comes from an EOS profile or imported inventory. The enable password is distinct from the SSH login password. The EOS terminal driver handles an initial `>` prompt and sessions already at `#`, and manages terminal paging.

The user subsequently reported that the changes worked. Preserve this tested-in-the-user's-lab behavior. Do not remove privilege escalation or replace the vendor driver with a generic shell connection.

### Junos

The Junos terminal plugin can enter CLI from a `%` shell prompt and configures terminal behavior. Explicit `| no-more` is also included in the backup command. Output is committed configuration in **set-command syntax**. Its downloaded extension is `.cfg`; changing the extension did not convert it to hierarchical syntax. Do not promise an untested restore/startup workflow based solely on the extension.

### IOS-XR

Connect to the NOS SSH service through the container management endpoint or published NOS port. XRv9k is a VM inside a container; its Linux wrapper is not the intended configuration source. The normalizer removes selected configuration-building and timestamp header lines to reduce irrelevant changes.

For all three, a running container does not prove that the NOS finished booting or accepts SSH. Credentials and management connectivity may differ with custom startup configuration.

## 7. Inventory, credentials and input handling

`parse_inventory()` accepts static YAML/JSON inventories, nested groups/host variables, and dynamic-script JSON output **as data**. It does not execute inventory scripts. Optional `topology-data.json` supplies kinds and short names.

Supported kind groups and recognized `ansible_network_os` aliases determine the platform. Unknown nodes remain disabled until explicitly assigned a supported NOS. Uploaded groups and host connection variables are flattened into controlled node records.

Accepted connection fields include `ansible_host`, `ansible_port`, `ansible_user`, `ansible_password`, `ansible_ssh_pass`, `ansible_network_os`, `clab_kind`, and `ansible_become_password`. A missing address falls back to the inventory hostname.

The parser limits files to 1 MiB, labs to 2,000 nodes, and nested static inventory depth to 16. It rejects YAML aliases/anchors, template syntax, invalid addresses/ports, and conflicting connection data. Unrecognized execution-related inventory settings are ignored. Preserve these boundaries when adding fields.

Credential precedence:

1. Explicit node profile.
2. Lab default profile for the platform.
3. Username/password imported with that node.

Profiles support password or uploaded RSA/ECDSA/Ed25519 private-key authentication, with a key passphrase where applicable. Uploaded keys are validated with Paramiko. Key files used by Ansible are temporary and mode `0600`. Empty-password profiles are permitted, while imported username-only records do not satisfy current readiness rules.

The baseline key path supplies the key passphrase via the existing Paramiko/Ansible password variable mechanism. Preserve or validate that path explicitly when changing key authentication; do not assume upload validation proves a live login.

Inventory replacement retains matching profile assignments, supported enabled state, and available short names. Newly uploaded addresses/ports replace earlier endpoint overrides. Profiles remain stored. A now-incomplete inventory can disable an existing schedule.

## 8. State and persistence

`Store` owns an in-process reentrant lock and one encrypted JSON state document. Its top-level collections are `labs` and `jobs`.

| Record | Important fields |
|---|---|
| Lab | `id`, `name`, `nodes`, `profiles`, `defaults`, `interval`, `next_run`, timestamps and inventory source |
| Inventory node | `name`, `short_name`, `address`, `port`, `platform`, `enabled`, `profile_id`, imported credentials, groups |
| Profile | `id`, label, platform, username, authentication type, password/key/passphrase/enable password |
| Job | `id`, `lab_id`, frozen `lab_name`, operation, status, timestamps, message, ordered node outcomes |
| Successful node outcome | `name`, status, message, internal `file`, frozen platform/short name, `captured_at`, `capture_time_source`, `download_metadata_version` |

Public API objects omit profile secrets and imported node passwords. Public jobs are copied and decorated with `archive_name`, `download_timezone`, and per-device `download_name`. Download code must not mutate persisted internal filenames while preparing a response.

Persistent paths:

| Path | Contents |
|---|---|
| `/data/state.enc` | Fernet-encrypted application state |
| `/data/state.key` | Key required to read the state |
| `/data/ui.token` | Persistent browser/API access token |
| `/data/events.jsonl` and `.1`–`.3` | Operational event log and rotations |
| `/data/backups/<lab-id>/latest/` | Latest successful configurations plus a local `.git` repository |
| `/data/backups/<lab-id>/history/<job-id>/` | Immutable-per-job configuration snapshots |

Atomic writes use a temporary sibling and `os.replace`, with mode `0600`. This is atomic replacement, not a cross-file transaction or an explicit fsync durability guarantee. Preserve the key alongside encrypted state during migrations and recovery.

The default Compose volume is named `nos-backup-ui-data`; its service mount is `/data`. Containerlab deployments may use another mount. Inspect the actual running container before assuming the default volume applies.

Use **one application process and one active container per data volume**. The Python lock and queue are not distributed. Startup marks queued/running jobs interrupted. Do not instantiate another `Store` against a live production volume just to inspect it: construction writes startup state and restart status.

No automatic configuration/history retention pruning exists. Operational log rotation is separate from configuration retention. Encryption with a colocated key does not protect against an administrator who controls the volume; configuration files themselves may contain NOS secrets.

## 9. Job execution and scheduling

`Runner` uses a `ThreadPoolExecutor(max_workers=1)` and rejects new submissions if any job is queued/running. It snapshots the lab/nodes for the job so subsequent inventory edits do not change the in-flight operation.

Execution details:

1. Validate enabled nodes, supported platform and credentials.
2. Create a job and update the next scheduled run.
3. Create private temporary inventory/key/event/process files.
4. Generate internal host aliases such as `node_0`; never use user names as executable inventory patterns.
5. Start the controlled playbook with up to five Ansible forks.
6. Poll callback events approximately every 0.5 seconds. UI state records task progress before process exit.
7. Enforce shutdown/deadline handling and terminate the subprocess process group as needed.
8. Normalize output; reject empty, unexpected-type, and recognized CLI-error/not-ready responses.
9. Write successful history and latest files and retain failed nodes' earlier latest files.
10. Stage latest files in local Git; commit only if the staged configuration changes.
11. Finalize job and node results. Some successful nodes can make a job `partial`; a nonzero Ansible exit or Git failure prevents an overall clean success.

Generated inventory currently sets connect timeout to 30 seconds and command timeout to 300 seconds; the generated variables override the 180-second command default in `ansible.cfg`. Whole-job deadline is `max(600, number_of_nodes * 360)` seconds. Do not change these blindly to mask boot, authentication or privilege failures.

Configuration files finalize after the Ansible pass, even though task events are visible while it runs. There is no current UI cancellation feature or complete terminal transcript view.

The scheduler checks approximately every two seconds. Intervals are minutes, `0` means manual, and API validation permits up to 10,080 minutes. A submitted manual job also resets that lab's next run. A blocked due schedule is deferred approximately one minute and logged.

## 10. Logging contract

Keep private result IPC separate from public operational diagnostics:

- Temporary callback events can contain raw retrieved configuration because the worker needs those bytes.
- Persistent action logs must contain controlled metadata and sanitized diagnostics, not configuration dumps, passwords, private keys, or SSH transcripts.
- `Runner` suppresses known credential values and selected sensitive diagnostic sections. `Store.event()` is **not a general-purpose secret scrubber**; callers remain responsible for safe messages.
- Keep Ansible persistent command logging and debug/verbosity disabled unless deliberately building a safe diagnostic feature.

Event fields: UTC `time`, `action`, `message`, `level`, `lab_id`, `job_id`, and `node`. Logs cover job lifecycle, node preparation, task start/result, Ansible exit/diagnostics, validation/writes, Git, schedules, inventory/profile/node changes, API actions, and downloads.

Rotation occurs at approximately 5 MiB for the active file, retaining three older files. The API supports lab/job/level/node filters and a result limit up to 2,000. UI polling is every four seconds; the viewer shows up to 1,000 matching events, newest first, and exports the displayed subset.

A logged `download.device` or `download.archive` means the server accepted/prepared the request. It does not prove the user's browser completed saving the bytes. Avoid labeling these as guaranteed client-side delivery.

## 11. Download and naming contract — user requirements

Individual devices must remain downloadable independently. Keep **Download all (ZIP)** available for the successful devices in a completed backup, including partial jobs. Do not offer config downloads for login tests or failed nodes.

Exact normal filename examples:

```text
cjunosevo_GTW-2_2026-09-10_01-04UTC.cfg
IOS-XR_PE1_2026-09-10_01-04UTC.txt
CEOS_IXP-L2-Switch_2026-09-10_01-04UTC.conf
BGP_TheoryToPractice_2026-09-10_01-02.zip
```

Rules:

- Config: `DeviceType_DeviceName_YYYY-MM-DD_HH-mmUTC.extension`.
- ZIP: `LabName_YYYY-MM-DD_HH-mm.zip` — no `nos-backup-<id>` prefix and no UTC suffix; UI identifies the timezone.
- Config time is the device's capture completion time. ZIP time is the job start time, with stored timestamp fallbacks.
- Download time must not replace backup time.
- The user initially expressed separators as `|`; underscores were approved because literal pipes and colons are invalid in Windows filenames.
- Exact output extensions are `.cfg` for cJunosEvolved, `.txt` for IOS-XR, and `.conf` for cEOS.
- The same config filenames must appear in individual responses, ZIP entries, and the ZIP manifest.
- HTTP `Content-Disposition` is authoritative. The JavaScript blob-download handler must honor it rather than inventing a client-side name.

**Internal storage names are intentionally different.** `runner.filename()` retains stable sanitized names plus a hash; internal suffixes remain `.set` for Junos and `.cfg` for XR/EOS. Changing only these suffixes will not correctly implement downloaded naming. Use `downloads.py` for download behavior and preserve stable storage paths for Git/backup compatibility.

Short-name selection uses explicit saved metadata/override, then exact removal of `clab-<lab name>-`, then a matching NOS hostname for an ambiguous container prefix. Hyphenated lab and device names must not be split heuristically at the last dash. Preserve ambiguous names and offer **Edit node → Download device name** as an override. New backups freeze the selected metadata.

Filename cleanup removes Windows-unsafe characters, protects reserved names, bounds component length, and handles case-insensitive collisions by adding a numeric suffix to the device name. Minute-level names can still repeat across separate jobs; browsers may append a local number when saving repeated downloads.

### Historical backups

At startup, `migrate_download_metadata()` backfills legacy outcomes that lack naming metadata. It uses known suffixes, recognizable NOS headers, existing inventory platform data, and historical timestamps. It does not rewrite configuration files or Git history.

Legacy timestamp order is captured time, finish/start/create job time, then file modification time. The UI identifies legacy job timing because the old worker did not record true per-device capture times. If platform recovery is impossible, retain download access using `Device_<name>_<time>UTC.<original-extension>` instead of guessing a NOS.

Once metadata is frozen, current inventory renaming or platform edits must not relabel historical snapshots. For future schema changes, keep migrations additive, repeat-safe, and compatible with existing `/data`.

Safe file lookup must resolve only successful job-owned snapshot files. Preserve rejection of invalid indexes, path traversal, unsafe filenames and symlinks. A missing file makes that device unavailable; the existing ZIP endpoint fails clearly rather than silently omitting a manifest-listed successful file. Other available devices remain individually downloadable.

## 12. API and UI map

Every `/api/` route requires `Authorization: Bearer <ui-token>`. Mutating requests require an acceptable Content-Length; request size is capped at 2.5 MB. Specific inventory/key limits also apply.

| Method / endpoint | Purpose |
|---|---|
| `GET /api/state` | Public labs, decorated jobs, platforms and application version |
| `GET /api/logs` | Filtered operational events |
| `POST /api/inventory` | Import/replace inventory, optional topology metadata; multipart form |
| `PUT /api/labs/{lab_id}/node` | Edit endpoint, NOS, profile, enabled state and optional short name |
| `POST /api/labs/{lab_id}/profiles` | Add credential profile; multipart form/key upload |
| `PUT /api/labs/{lab_id}/schedule` | Configure interval |
| `POST /api/labs/{lab_id}/jobs` | Start `backup` or `test` |
| `GET /api/jobs/{job_id}/download` | Complete job ZIP |
| `GET /api/jobs/{job_id}/nodes/{node_index}/download` | Single successful device snapshot |
| `GET /` and `/static/*` | UI assets |

The node index is the saved outcome array index, not a filesystem path or current inventory position. Preserve job node order.

The UI has Inventory, Credentials, Backup history, and Action logs views. It stores the UI token and active lab selection in sessionStorage. Password/private-key profile data are not returned after saving. Browser text interpolation uses `esc()` or textContent; apply equivalent escaping for new untrusted fields.

The middleware sets security/cache headers and a self-only Content Security Policy. Prefer existing local static scripts/styles over inline scripts or external assets. No additional frontend framework is necessary for ordinary controls.

## 13. Development and validation

First locate the **application directory containing Dockerfile, requirements.txt and app/**. Run the following from that directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -v
node --test tests/test_download_ui.js
node --check app/static/app.js
git diff --check
```

For tests using real NOS drivers, install collections:

```bash
.venv/bin/ansible-galaxy collection install -r collections.yml
RUN_SSH_FIXTURES=1 PATH="$PWD/.venv/bin:$PATH" \
  .venv/bin/python -m unittest discover -s tests -p test_eos_ssh.py -v
```

Test responsibilities:

- `test_app.py`: API/authentication/import/profile/readiness behavior and real local Ansible callback → files → Git → ZIP pipeline.
- `test_logging.py`: driver/enable settings, redaction, live events, failed-backup preservation, event persistence/filtering/rotation.
- `test_downloads.py`: names/extensions/UTC, file bytes, ZIP/manifest consistency, legacy backfill, stable historical names, authorization/path checks, collisions.
- `test_download_ui.js`: production UI handlers in a DOM/fetch harness; correct device endpoint, attachment filename handling and download controls.
- `test_eos_ssh.py`: opt-in real EOS driver against a simulated local Paramiko SSH server that requires enable authentication.

At release 1.2.0, **23 Python tests passed**, **one opt-in SSH fixture was skipped**, and **three JavaScript behavior tests passed**. The earlier attempt at the opt-in fixture was blocked by an environment `Operation not permitted` error. That is not evidence of successful live SSH verification or proof of a deployment-host defect.

Offline fixture tests are not real Junos/IOS-XR/cEOS validation. JavaScript harness tests are not interactive browser visual tests. No Docker build or live device access was available for the previous generated release. The user separately confirmed that the preceding EOS/logging changes worked in their lab.

For a new feature, add focused tests for the real failure risks and preserve meaningful existing tests. If changing drivers, prompts, credentials or commands, validate on the relevant live NOS when access is available. If adding UI behavior, check the actual controls/download behavior where a browser is available. Report remaining gaps honestly.

## 14. Versioning, build and deployment

At baseline, keep these version locations consistent:

- `app/__init__.py` (`__version__`, exposed by API and footer).
- `VERSION`.
- Dockerfile OCI version label.
- Compose image tag.
- UI fallback/static footer version in JavaScript/HTML.
- README, validation report and release instructions.

The current release is `1.2.0`. Choose the next version from the current checkout: patch for a compatible fix, minor for a compatible feature, major for a breaking change. Do not overwrite an existing numbered release tag with different contents. `webui` is the moving compatibility tag.

### The build-directory mistake to avoid

The user ran this from `~/CLAB-Backup_V5`:

```bash
docker build -t clab-backup:1.2.0 -t clab-backup:webui ./clab-backup-ui
```

Docker returned `path "./clab-backup-ui" not found`. The problem was the build-context path, not the image tags. Do not repeat an assumed subfolder path without checking the extraction layout.

Find the Dockerfile if needed:

```bash
find . -maxdepth 4 -type f -name Dockerfile
```

If already in the directory containing Dockerfile:

```bash
BACKUP_VERSION=1.2.0
docker build -t "clab-backup:${BACKUP_VERSION}" -t clab-backup:webui .
docker image ls clab-backup
```

If in a repository root that actually contains `clab-backup-ui/`:

```bash
BACKUP_VERSION=1.2.0
docker build -t "clab-backup:${BACKUP_VERSION}" -t clab-backup:webui ./clab-backup-ui
```

Use the next intended version when preparing a new release; the examples above describe the baseline.

### Deploying safely

The user may run the worker as a containerlab node or with Compose. Identify which applies. Rebuilding an image does not update an existing container; a restart of that same container does not substitute the rebuilt image. Recreate the worker through its existing deployment mechanism and retain its existing `/data` mount.

For containerlab, pin the intended image in the existing node definition:

```yaml
Backup-Worker:
  kind: linux
  image: clab-backup:1.2.0
```

This is only the relevant fragment. Preserve the user's current ports, network, mounts and other node settings. Do not invent a full topology or redeploy the entire router lab just to replace the worker.

For the included Compose deployment, from the directory containing `compose.yml`:

```bash
docker compose up -d --build
docker compose logs backup-ui
```

Compose uses the external network `${CLAB_NETWORK:-clab}`, host UI binding `${UI_BIND:-0.0.0.0}:${UI_PORT:-8080}:8080`, and named volume `nos-backup-ui-data`. Existing environment settings must be preserved. Custom bind mounts require ownership usable by UID 10001; do not assume named-volume initialization fixes arbitrary host-folder permissions.

Never delete `/data`, `state.key`, or the persistent volume to solve an upgrade issue. Do not use `docker compose down -v` when retaining data. Inspect mounts before replacing a worker; if no persistent mount exists, establish a data-preservation plan before deleting the container.

A rollback needs the older image and a compatible state schema. Do not promise rollback compatibility after a future migration without checking it.

### Git and packaging

Commit the intended release changes before creating an annotated source tag. When authorized to publish that release:

```bash
git tag -a v1.2.0 -m "Individual config downloads and readable filenames"
git push origin v1.2.0
```

Adapt the version/message; these are not instructions to re-tag an existing release. A Git tag identifies source; a Docker tag identifies a built image. Neither implies deployment.

If delivering an archive, include complete current source, accurate build instructions and a patch against the stated baseline when useful. Exclude `.git`, virtual environments, Python caches, live `/data`, UI tokens, keys, inventories containing credentials and real configuration backups. Git/Docker ignore files prevent accidental cache inclusion, but inspect the package content rather than assuming ignores cover every archive workflow.

## 15. Troubleshooting and known limits

| Symptom | First checks |
|---|---|
| Build context not found | Locate Dockerfile; use `.` from its directory |
| UI still reports older version | Check running container image, recreation and browser refresh; verify API/footer |
| Lost profiles/history after replacement | Verify original `/data` volume/mount and key; do not initialize over the only original copy |
| EOS backup/login fails | EOS driver, enable behavior/password, account authorization, SSH endpoint and action logs |
| Junos/XRv9k connection fails | NOS boot readiness, reachable management/published SSH endpoint, credentials and correct driver |
| ZIP still uses `nos-backup-<id>` | Ensure both backend filename and UI blob-download handler were updated |
| Config has wrong visible extension | Inspect `downloads.FORMATS`; internal `PLATFORMS` suffixes intentionally differ |
| Historical file keeps a full container name | Check saved metadata and ambiguous prefix; avoid guessing hyphen boundaries |
| Logs show task success but job is partial | Check file validation/write failures, Ansible exit and Git result |
| Download returns 404 | Verify successful node index, recorded history file and safe path; latest files are not substitutes for a missing historical snapshot |

Known architectural limits to consider, not automatic extra scope:

- One process/queue, no multi-instance coordination.
- Growing encrypted state and history with no backup pruning; full-state polling can become expensive.
- Log filtering reads rotated files under the Store lock; future scale work may need indexing/pagination.
- Basic output validation is not a complete parser or restore-readiness guarantee.
- No full raw SSH transcript, interactive cancel, restore workflow or registry publishing integration.
- No general profile deletion/edit workflow in the baseline; rotation typically adds/reassigns a profile.
- No proven cross-file transactional durability or protection from disk loss.
- Default HTTP and disabled SSH host-key verification reflect the existing isolated-lab workflow; do not silently expand its trust boundary.

## 16. Next-change checklist

1. Read the current request and this file; identify relevant source files and current version.
2. Fetch/read the latest repository without overwriting local work. Compare differences before reusing earlier patches.
3. State the proposed behavior and preserve the user's established naming, logging and platform requirements.
4. Implement approved scope through backend, callback/worker and UI layers as needed.
5. Make state changes backward-compatible; retain snapshot identity and secrecy boundaries.
6. Add logs for new meaningful actions using controlled metadata.
7. Run focused tests and applicable regression coverage; validate relevant UI/NOS behavior where possible.
8. Update version markers, README and validation evidence.
9. Deliver source/patch or push only as authorized. Include commands appropriate to the user's actual folder layout.
10. State exactly what was verified and what still requires deployment-host/live-device confirmation.

## 17. Reference sources

Prefer current source code and official documentation when behavior needs verification:

- [Project repository](https://github.com/ArchRuger/CLAB-BACKUP-WORKER)
- [Containerlab XRv9k kind](https://containerlab.dev/manual/kinds/vr-xrv9k/)
- [Containerlab cJunosEvolved kind](https://containerlab.dev/manual/kinds/cjunosevolved/)
- [Containerlab cEOS kind](https://containerlab.dev/manual/kinds/ceos/)
- [Containerlab inventory](https://containerlab.dev/manual/inventory/)
- [EOS terminal driver source](https://github.com/ansible-collections/arista.eos/blob/main/plugins/terminal/eos.py)
- [Junos terminal driver source](https://github.com/ansible-collections/junipernetworks.junos/blob/main/plugins/terminal/junos.py)
- [Ansible network_cli documentation](https://docs.ansible.com/projects/ansible/latest/collections/ansible/netcommon/network_cli_connection.html)
- [Docker build reference](https://docs.docker.com/reference/cli/docker/buildx/build/)

Do not treat a vendor's default credentials or example addresses as the user's current configuration. Never replace missing deployment evidence with a confident guess.
