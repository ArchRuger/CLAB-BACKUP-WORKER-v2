# CLAUDE.md

Guidance for Claude Code (claude.ai/code) in this repository. This file is loaded into every session,
so it holds only what is current: the state of `main`, commands, architecture, the invariants that
must never regress, and a routing table into the detailed notes. Release history is linked, not
imported.

@docs/REPOSITORY-MAINTENANCE.md

## Where the detail lives

- **`agent instructions.md`** (the symlink `agent-instructions.md` points at it) is the per-release
  handoff file, newest release first. It is large and is **not** loaded automatically. Before you
  change an area, read the sections the [routing table](#routing-table-what-to-read-before-touching-an-area)
  names for it: `grep -nE '^#{1,2} ' "agent instructions.md"` lists the sections (releases up to 1.15.1
  are `##` headings under the old title), then read by line range.
  Newer sections supersede older ones where they disagree; the numbered baseline at the end of the
  file describes the first releases and is history (its token login, SSH-key VM connection, in-lab
  worker deployment and old repository URL are all gone).
- `docs/ARCHITECTURE.md` "Module map" has module-by-module responsibilities; do not rediscover them.
- `docs/maintenance-audit/` holds the documentation audit record (dispositions, the
  feature-to-documentation map, remaining debt) and its pickup file.
- Pickup files of finished work streams stay useful for their open points and tooling:
  `docs/ui-review-001/PICKUP.md`, `docs/redesign/PICKUP.md` (§2 rebuild loop and live labs, §7 log),
  `docs/lab-builder/PICKUP.md` and `docs/lab-builder/QA-FINDINGS.md`. Their branch and pull-request
  lines are a record of when they were written: ask Git and GitHub for live status.

## State of `main`

- The current release is whatever `clab-backup-ui/VERSION` says. The student-centred UI redesign, the
  lab builder and UI review 001 are all released and merged; nothing on `main` is "unreleased". For
  work in flight look at `git log`, the open pull requests and the pickup files, not at this file.
- The redesign's contracts still bind frontend work: `docs/redesign/DESIGN-SPEC-ADDENDUM.md` is the
  binding UI contract, and every capability in `docs/redesign/inventory/*.md` and
  `docs/redesign/parity/*.md` keeps working (zero functional regression).
- Every existing test keeps its behavioural claim: a label pinned by an old regex is rewritten, never
  deleted.
- **Discover the environment, do not assume it.** A checkout may or may not be on a development VM.
  Check for Docker, `/srv/containerlab-node-manager/data`, a running manager and Node 24 before you
  rely on them. The container rebuild loop and the live labs are described in
  `docs/redesign/PICKUP.md` §2. Never claim a VM, browser or live-device validation that did not
  happen in this session, and never point tests or a `Store` at live data.
- `docs/redesign/tools/`, `docs/ui-review-001/tools/` and `docs/lab-builder/tools/` are working
  regression tooling (fixture manager, Playwright checks), not disposable notes.

## Commands

Run the application tests from `clab-backup-ui/` (tests import `app` from the working directory;
`-t tests` keeps the test modules top-level). Recreate the virtual environment with:

```bash
cd clab-backup-ui
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt httpx
```

```bash
# Full suites
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests
node --test tests/*.js

# One Python file, one test by name
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_restore.py -v
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_restore.py -k test_preflight

# One browser (node:test) file, one test by name
node --test tests/test_git_places_ui.js
node --test --test-name-pattern="nested" tests/test_git_places_ui.js

# Static checks used before every handoff
node --check app/static/operations.js
git diff --check

# Opt-in real EOS driver fixture (needs the vendor collections, not installed in the local .venv)
.venv/bin/ansible-galaxy collection install -r collections.yml
RUN_SSH_FIXTURES=1 PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests -p test_eos_ssh.py -v
```

The `PATH` prefix matters: `app/runner.py` starts `ansible-playbook` by bare name and `test_app.py`
drives that real pipeline (callback → files → Git → ZIP).

Release tooling runs from any directory with the system Python:

```bash
python3 deploy/verify-release.py        # lockstep version markers + documentation rules
python3 deploy/set-release.py X.Y.Z     # the only way to move release markers
bash deploy/check-install.sh            # installed VM only
```

Browser validation without a VM: `docs/redesign/tools/fixture_manager.py` (the real app on a scratch
`FIXTURE_DATA` directory with scripted VM answers) and `docs/redesign/tools/verify_after.py`
(Playwright, three viewports); per-feature checks are `docs/ui-review-001/tools/check_ui*.py` and
`docs/lab-builder/tools/student_workflow.py`. Use a fresh `FIXTURE_DATA` per run and restart the
fixture after any `app/*.py` change.

**CI runs an explicit list, not `discover`.** `.github/workflows/release-check.yml` names each Python
test file with `-p` (only `test_telemetry*.py` and `test_capture*.py` are globs) and each browser test
file in one `node --test` line. A new test file that is not appended there never runs in CI. The
deploy-script tests (`test_install_manager.py`, `test_check_*.py`, `test_git_onboard.py`, …) run with the
system `python3` before the venv is created, so they must stay stdlib-only.

## Architecture: what you only see by reading several files

**Composition.** `create_app(data_dir)` in `app/main.py` builds one `Store`, then the service objects
in dependency order (`Runner`, `NodeServices`, `ReadinessMonitor`, `Discovery`, `LabOperations`,
`GitProgress`, `RestoreService`, `TelemetryManager`, `GrafanaControl`, `Captures`, `Diagnostics`).
Each feature module owns its routes through an `install(app)` method and reaches its peers through
`app.state.<name>`; `main.py` itself keeps only inventory, profiles, jobs, downloads and the public lab
view. The lifespan starts the background threads (runner → discovery → readiness → telemetry →
Grafana monitor) and closes everything in reverse. Tests call `create_app(<temp dir>)` with `httpx`;
constructing a `Store` writes startup state, so never point one at live data.

**Public views strip secrets.** Every module that exposes a job or lab has a `public_*` function
(`downloads.decorate_job`, `git_progress.public_job`, `restore.public_job`, the lab summary in
`main.py`). A new persisted field is private until one of those copies it out; profile secrets,
imported node passwords, host identity, restore candidates and a lab's stored annotations document
never reach `/api/state`.

**Three paths out of the container, none of them Docker or root.**

1. *The VM*: one SSH account (`clab-discovery`, password only) whose forced command is
   `deploy/clab-manager-gateway`. It maps exactly three request names to `sudo -n` helpers that are
   copies of `app/host_files.py` (inspect, read-only), `app/host_operations.py` (containerlab lifecycle
   and the reviewed `create` / `publish` / `revise` file actions inside trusted roots) and
   `app/host_git.py` (owner-scoped Git). The manager-side clients are `discovery.py`,
   `lab_operations.py` and `git_progress.py`; they send structured stdin and read NDJSON, and all three
   readers wait for stream EOF rather than exit status (keep new readers identical in shape). Helper
   `VERSION` must equal the manager's; the launcher refuses a mixed tree, and
   `deploy/setup-*.sh --refresh` reinstalls a helper.
2. *The nodes directly*: Ansible `network_cli` (`runner.py`), Paramiko shells (`node_services.py`,
   `node_readiness.py`, `telemetry_provision.py`, `restore_junos.py`) and gNMI dial-in
   (`telemetry_collector.py`). Every Ansible run gets its own `HOME` and host-key checking off
   (`runner.job_environment`); lab containers regenerate host keys on each deploy.
3. *The side stacks*: browser Wireshark (`capture.py` discovery → `capture_sessions.py` same-origin
   relay → `capture_service.py`, the separate container that alone holds the Docker socket) and
   telemetry (Prometheus scrapes `/api/telemetry/metrics`; Grafana is provisioned from
   `deploy/telemetry/` and started on demand by `grafana_control.py`).

**Concurrency is one process, one lock.** `store.py` holds a single encrypted JSON document under a
reentrant lock; the runner is a one-worker pool; `lab_operations.operation_busy` is the shared guard
that backups, Git saves, restores, discovery imports and removal all consult. Startup marks
queued/running work `interrupted`. There is no multi-instance coordination.

**Frontend: three different things.**

1. *The manager UI is plain scripts*: no build step, no framework, no CDN. `index.html` loads them in
   a fixed order, each with `?v=<release>` (a new script must carry it in every page, or
   `verify-release.py` fails). House style: `'use strict'`, dense one-statement-per-line, `esc()` on
   every interpolation, no inline styles. The files share globals rather than modules: `status.js`
   (pure status vocabulary), `shell.js` (hash router, menus, browser storage: keep new
   `window`/`location`/`history`/`localStorage`/document listeners here so the other files still load
   in Node), `app.js` (state, `render`, `PANELS`), then the feature files (`topology-render`,
   `topology`, `home`, `management`, `operations`, `diagram-editor`, `git-progress`, `git-places`,
   `restore`, `capture`). Standalone pages (`terminal`, `workspace`, `grafana`, `debug`,
   `vm-connection`, `capture-setup`, `capture-session`, `lab-builder`, `map-editor`) have their own
   small scripts. Because globals are shared, "no reference in this file" never proves a function
   unused: check the other scripts, the HTML, the tests and the Playwright tools.
2. *The embedded topology editor is built ahead of time.* `clab-backup-ui/lab-builder/` is a
   TypeScript/React project (esbuild, Node 24 or later, `@containerlab/clab-ui` pinned exactly) whose
   only source of ours is the adapter `src/main.tsx`. Its output is committed under
   `app/static/lab-builder/` with a hash manifest, and serves both `lab-builder.html` and
   `map-editor.html`. After a change run `npm ci` and `node build.mjs`, then `node build.mjs --check`;
   CI rebuilds with Node 24 and compares. Never hand-edit the bundle. The entry bundle is cached
   `immutable` under `?v=<release>`, so an adapter change reaches browsers only with a new release
   number. The pages around it (`lab-builder-page.js`, `map-editor-page.js`) are house-style plain
   scripts.
3. *A VM needs neither Node nor npm.* The Docker image serves the committed assets; the build project
   never runs on a lab VM.

CSP is `script-src 'self'` everywhere. Inline styles are allowed only on `terminal.html`,
`capture-session.html` (xterm) and `lab-builder.html`, `map-editor.html` (the editor); `/` must keep
none.

**Browser tests** are `node:test` files that `vm.runInContext` a production script into a context with
a fake `$`, `esc` and `state`. Copy `tests/test_operations_ui.js` for a module of pure functions,
`tests/test_readiness_ui.js` or `tests/test_download_ui.js` for a harness that loads `status.js` and
`app.js` together, and `tests/test_shell_ui.js` for `shell.js` with its router and menus.

## Rules

- Never edit release markers by hand; use `set-release.py`, then write the three history sections
  (CHANGELOG, VALIDATION, agent instructions) and run `verify-release.py`. Keep the new handoff
  section short: what the next agent must preserve, with links to the detail.
- Every code change: run the test suites, then update `clab-backup-ui/VALIDATION.md` and
  `docs/CHANGELOG.md` per `docs/REPOSITORY-MAINTENANCE.md`. VALIDATION records only what was actually
  run; say plainly what is static, unit, fixture/browser, CI or live evidence.
- `host_*.py` under `clab-backup-ui/app` are installed on the VM as sudoers helpers: treat changes as
  security-sensitive, keep the gateway's command list and each helper's option whitelist exact, and
  never add a helper for device work (device access stays on the direct node-SSH path).
- Do not add dependencies the notes rule out (PyEZ/ncclient/lxml for Junos; a Docker socket or host
  metrics in the manager; frontend frameworks or CDN assets in the manager UI).
- Commit with Git (dotfiles included, LF enforced by `.gitattributes`); never replace files through
  a browser upload. Never force-push, tag, publish an image or deploy unless asked.

## Invariants that must not regress

One line each; the handoff section named in the routing table has the reasoning and the detail.

*VM boundary and data*
- The manager never gets a Docker socket or host metrics. Only `capture_service.py` holds the socket;
  its API is never exposed to browsers and takes no client-supplied image, command, mount or URL.
- The VM connection is password-only for the dedicated account (device credentials may still use
  keys); the VM host key is pinned after explicit first-use trust.
- Helpers take structured stdin, fixed argv, trusted roots, review digests bound to the whole request
  and one host lock. The removed `write` mode stays removed; `publish` derives every path itself;
  `revise` needs an undeployed lab and the opened versions' hashes.
- The manager never collects Git tokens or accepts Git command text; Git runs as the registered owner
  in that owner's `HOME`; no force push, stash or destructive reset of a checkout; `register()` in
  `host_git.py` stays equivalent to the child in `deploy/setup-git.sh`.
- There is no login: `/api/` is protected by the same-origin `guard` in `main.py` (a mutating request
  needs a body; content-length 0 is refused, so pages post `{}`); every WebSocket checks `Origin`
  itself and terminals need a single-use ticket. Never add a route or socket outside this.
- Persistent logs and job messages carry controlled metadata only: never configuration text,
  passwords, keys or raw SSH output; `Store.event()` does not scrub. SuperPuTTY password export stays
  opt-in.
- Background discovery never saves a new workspace: imports need the preview token and a
  confirmation. *Remove lab* and *Start fresh* are manager-only and never touch VM files or labs.
- Never delete `/data`, `state.key` or backups to solve a problem; never reset real data to validate.
- Stored-data compatibility code (old state shapes, schema 1 snapshots, `review_before_push`,
  `TAB_ALIAS`, legacy download metadata) is not dead code. Never rewrite stored Git bindings: pending
  jobs compare their digest.

*Devices*
- Supported kinds keep their drivers and commands: EOS with `enable` become, IOS XR
  `show running-config`, Junos `display set` as the canonical human and diff form.
- Login order is profile > inventory > documented kind default; add a default only if containerlab.dev
  publishes it.
- Every Ansible job has its own `HOME` and never reads a shared `known_hosts`.
- For linked labs SSH readiness means a real `show version` answer; backend `readiness === 'Ready'`
  is backup eligibility, `deviceState()` is SSH readiness.
- Restore is Junos only, over direct node SSH: hierarchical candidate, `load override`, `commit check`,
  `commit confirmed`, reconnect, confirm; the pre-restore backup is mandatory; never fake
  commit-confirmed; snapshots without a restore artifact are view and download only.
- Download names follow the contract in `clab-backup-ui/NODE-FEATURES.md` and
  baseline §11 of the handoff; internal storage names intentionally differ and stay stable;
  frozen snapshot metadata is never relabelled from the current inventory.

*Save progress*
- A review before every upload is mandatory; there is no opt-out, and `gitReviewJob` is the only
  sender of `{push: true, reviewed: true}`.
- Pending saves block folder moves and reconnects; one registration per lab; overlap rules are the
  VM's. A planned (empty) folder is never worded as existing in the repository.
- The folder tree's open branches belong to the student (`gitPlacesState.expanded`); never derive
  `open` from the selection.
- A deployment time comes only from `LabOperations.record_deployment()`.

*Maps and the editor*
- The editor is embedded, not forked; never flush drafts on a timer; never show as kept what is not.
- *Edit map* is the builder's editor in map mode behind the `MAP_COMMANDS` whitelist: never add a
  topology command or the engine's `undo`/`redo`; the page owns undo history. `map-editor.html` loads
  neither `operations.js` nor `lab-builder-page.js`.
- A place that replaces `lab['drawing']` from an annotations text calls `layout.keep_document`.
  Background discovery places only an `unplaced` drawing; an explicit *Sync from VM* replaces the
  drawing only when the VM has an annotations file.
- Uploaded topology files go only through `opUpload()` → the reviewed `create`.
- No stroke rule on `.topology-wire path` without excluding `path.capture-hit`.
- `lab-builder.css` keeps `.lab-builder #root svg{max-width:none}`.

*Side stacks*
- Prometheus boolean flags are `--flag` / `--no-flag`, never `=true/false`; the hidden TSDB block
  flags stay together with the pinned image. `PLUGIN`/`PLUGIN_VERSION` are identical in
  `setup_telemetry.py` and `telemetry_map.py`.
- Telemetry state `streaming` is set only by an accepted record; the store is memory only; device
  writes happen only for a decided setting, after real readiness, never during an operation.
- Capture: offer the `binary` VNC subprotocol upstream and echo it only when the client offered it;
  `/pcaps` is a labelled tmpfs-backed *volume*, never a container tmpfs mount (the Docker archive API
  cannot see those); `setup-capture.sh` keeps `--force-recreate
  --remove-orphans`; the HMAC identity excludes the interface list.
- Browser Wireshark and the Grafana dashboards are part of every installation: the installer sets both
  up and the health check warns when either is disabled.

## Routing table: what to read before touching an area

Sections are headings of `agent instructions.md`, named by their release.

| Area | Handoff sections | Guide | Tests and tools |
|---|---|---|---|
| Home, menus, Devices tab, shell, status vocabulary | 1.30.17 items 1, 2, 8–10; 1.29.1; 1.29.0 | `docs/LAB-OPERATIONS.md`, `docs/redesign/DESIGN-SPEC-ADDENDUM.md` | `test_home_ui.js`, `test_shell_ui.js`, `test_status_ui.js`, `verify_after.py`, `check_ui00{1,2a,2b,5,6}.py` |
| Save progress, folders, upload review | 1.30.17 items 3–7; 1.29.0; 1.28.0 (2), (5); 1.27.0; 1.15.3, 1.15.2 (top level); 1.15.1, 1.15.0 (under the old title) | `docs/GIT-PROGRESS.md`, `docs/GIT-SETUP.md` | `test_git_progress.py`, `test_host_git.py`, `test_git_*_ui.js`, `check_ui004.py`, `check_ui007*.py`, `check_ui008*.py` |
| Apply to running lab (restore) | 1.28.0; 1.29.0 (live facts) | `docs/GIT-PROGRESS.md`, `docs/LAB-OPERATIONS.md` | `test_restore*.py`, `test_restore_ui.js` |
| Topology tab, Edit map, map document, drawing, exports | 1.30.17 items 11–16; 1.29.1; 1.29.0; 1.26.0 (1); 1.25.0 (1); 1.14.0, 1.6.x and 1.5.0 addenda | `docs/ui-review-001/MAP-PARITY.md`, `docs/LAB-OPERATIONS.md` | `test_map_editor_ui.js`, `test_lab_builder_ui.js`, `test_lab_operations.py` (map document), `test_topology.py`, `test_topology_ui.js`, `test_topology_menu_ui.js`, `test_diagram_editor*`, `check_ui003.py`, `check_ui003b.py` |
| Lab builder, `publish` / `revise` | 1.30.1; 1.30.0 | `docs/LAB-BUILDER.md`, `docs/lab-builder/QA-FINDINGS.md` | `test_lab_operations.py` (helper and manager side), `test_lab_builder_ui.js`, `student_workflow.py`, `node build.mjs --check` |
| Lab operations, topology browser, upload, destroy, the operations helper | 1.30.17 items 9–10; 1.30.1 (3), (8); 1.30.0 (4)–(5); 1.26.0 (2)–(3); 1.22.0 (4); 1.19.4 (`create` file modes); 1.12.x and 1.11.0 addenda | `docs/LAB-OPERATIONS.md` | `test_lab_operations.py`, `test_operations_ssh.py`, `test_operations_ui.js` |
| Discovery, import, sync, VM connection, helpers' transport | 1.30.17 item 12; 1.26.0 (1); 1.22.0 (2)–(3); 1.19.3; 1.19.1; 1.13.0 and 1.10.0–1.7.0 addenda | `docs/VM-CONNECTION.md`, `docs/DEBUG-PANEL.md` | `test_discovery*.py`, `test_vm_files.py`, `test_import_confirmation.py` |
| Inventory import, readiness, logins, backups, logging, downloads | 1.22.0; baseline §6–§11 | `clab-backup-ui/NODE-FEATURES.md` | `test_node_readiness.py`, `test_app.py`, `test_downloads.py`, `test_readiness_ui.js` |
| Terminals, CLI launcher | 1.12.0 and 1.4.0 addenda | `clab-backup-ui/NODE-FEATURES.md` | `test_nodes.py` |
| Telemetry, Grafana, lab map | 1.26.0 (3); 1.25.0 (1); 1.24.0; 1.23.1; 1.23.0 | `docs/TELEMETRY.md`, `docs/GRAFANA-MAP.md` | `test_telemetry*.py`, `test_grafana_ui.js`, `deploy/telemetry/smoke.py` |
| Browser Wireshark | 1.22.0 (5); 1.21.1; 1.21.0; 1.20.x | `docs/CAPTURE.md` | `test_capture*.py`, `test_capture_ui.js`, `test_capture_session_ui.js`, `deploy/capture/smoke.py` |
| Installer, health check, engineer access | 1.25.0 (2); 1.19.4; 1.19.3; 1.19.2; 1.16.0 | `docs/INSTALL.md`, `docs/HEALTH-CHECK.md`, `docs/FRESH-VM-GUIDE-V2.md` | `test_install_manager.py`, `test_check_*.py`, `test_git_onboard.py` |
| Course structure, lab scaffold | 1.29.0 (live facts) | `docs/NAMING.md` | `test_scaffold_lab.py` |
| Releases and documentation rules | 1.25.0 (3); 1.15.1 | `docs/REPOSITORY-MAINTENANCE.md` | `test_release_consistency.py`, `deploy/verify-release.py` |
