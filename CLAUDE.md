# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@agent-instructions.md
@docs/REPOSITORY-MAINTENANCE.md

`agent-instructions.md` is a symlink to `agent instructions.md`, the per-release handoff file
(newest release first). Read the sections that cover the area you touch; older sections are history
and are superseded by newer ones where they disagree. Module-by-module responsibilities are in
`docs/ARCHITECTURE.md` ("Module map"); do not rediscover them from scratch.

## State of `main`

- The current release is whatever `clab-backup-ui/VERSION` says. `main` also carries the **unreleased**
  student-centred UI redesign (merged from `claude/wip-student-centered-ui-redesign`). Before any
  frontend work read `docs/redesign/PICKUP.md`; its §7 "Handoff status" is the single source of truth
  for what is done and what is next, and §4 is the migration order. Do not cut a release until that
  plan is complete and browser + live-lab validation is recorded in `clab-backup-ui/VALIDATION.md`.
- The redesign must not touch the backend or the `host_*.py` helpers, and every existing test keeps
  its behavioural claim: labels pinned by old regexes are rewritten, never deleted.
- This checkout is not the dev VM (no Docker, no `/srv/containerlab-node-manager/data`). The
  container rebuild loop and the live labs are described in `PICKUP.md` §2; never claim a VM or
  live-device validation that did not happen here.

## Commands

Run the application tests from `clab-backup-ui/` (tests import `app` from the working directory;
`-t tests` keeps the test modules top-level). A working `.venv` already exists there; recreate it with:

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
imported node passwords, host identity and restore candidates never reach `/api/state`.

**Three paths out of the container, none of them Docker or root.**

1. *The VM*: one SSH account (`clab-discovery`) whose forced command is `deploy/clab-manager-gateway`.
   It maps exactly three request names to `sudo -n` helpers that are copies of
   `app/host_files.py` (inspect, read-only), `app/host_operations.py` (containerlab lifecycle inside
   trusted roots) and `app/host_git.py` (owner-scoped Git). The manager-side clients are
   `discovery.py`, `lab_operations.py` and `git_progress.py`; they send structured stdin and read
   NDJSON, and all three readers wait for stream EOF rather than exit status (keep new readers
   identical in shape). Helper `VERSION` must equal the manager's; the launcher refuses a mixed
   tree, and `deploy/setup-*.sh --refresh` reinstalls a helper.
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

**Frontend.** Plain scripts, no build step, no framework, no CDN. `index.html` loads them in a fixed
order, each with `?v=<release>` (a new script must carry it in every page, or `verify-release.py`
fails). House style: `'use strict'`, dense one-statement-per-line, `esc()` on every interpolation, no
inline styles (self-only CSP; only `terminal.html` and `capture-session.html` allow inline styles for
xterm). The files share globals rather than modules: `app.js` (state, `render`, `PANELS`), `shell.js`
(hash router, menus, browser storage: keep new `window`/`location`/`history`/`localStorage`/document
listeners here so the other files still load in Node), `status.js` (pure status vocabulary), then the
feature files (`home`, `management`, `operations`, `topology*`, `diagram-editor`, `git-progress`,
`git-places`, `restore`, `capture`). Standalone pages (`terminal`, `workspace`, `grafana`, `debug`,
`vm-connection`, `capture-setup`, `capture-session`) have their own small scripts.

**Browser tests** are `node:test` files that `vm.runInContext` a production script into a context with
a fake `$`, `esc` and `state`. Copy `tests/test_operations_ui.js` for a module of pure functions,
`tests/test_readiness_ui.js` or `tests/test_download_ui.js` for a harness that loads `status.js` and
`app.js` together, and `tests/test_shell_ui.js` for `shell.js` with its router and menus.

## Rules

- Never edit release markers by hand; use `set-release.py`, then write the three history sections
  (CHANGELOG, VALIDATION, agent instructions) and run `verify-release.py`.
- Every code change: run the test suites, then update `clab-backup-ui/VALIDATION.md` and
  `docs/CHANGELOG.md` per `docs/REPOSITORY-MAINTENANCE.md`. VALIDATION records only what was actually
  run; say plainly what is fixture-only.
- `host_*.py` under `clab-backup-ui/app` are installed on the VM as sudoers helpers: treat changes as
  security-sensitive, keep the gateway's command list exact, and never add a helper for device work
  (device access stays on the direct node-SSH path).
- Do not add dependencies the notes rule out (PyEZ/ncclient/lxml for Junos; a Docker socket or host
  metrics in the manager; frontend frameworks or CDN assets).
- Commit with Git (dotfiles included, LF enforced by `.gitattributes`); never replace files through
  a browser upload.
