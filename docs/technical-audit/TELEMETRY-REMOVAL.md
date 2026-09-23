# Telemetry and Grafana retirement

The one intentional product change of the technical audit: the network telemetry feature (gNMI dial-in
collection, device provisioning, Prometheus exposition) and the Grafana dashboards with the generated lab
maps are removed from the manager, the deployment tooling, the tests and the current guides. The removal
is traced here from the user entry points to the persisted state, so that every deleted surface, every
retained shared dependency and every migration step has a recorded reason. History files (the changelog,
the validation record, the handoff notes and the dated work-stream folders) keep describing the feature as
it was; they are not rewritten.

## 1. Producer and consumer map (base `main` `b1ced1d`, 1.30.38)

| Surface | Files and symbols | Consumers outside the feature | Disposition |
|---|---|---|---|
| Composition and lifecycle | `main.py`: `TelemetryManager(store, services)`, `GrafanaControl(store, operations, telemetry)`, `telemetry.start()/close()`, `grafana.run()/close()`, `app.state.telemetry`, `app.state.grafana`, `telemetry.reset()` in the manager reset, `telemetry.forget_lab()` in *Remove lab*, `row['telemetry']` and `result['telemetry']` in `public_lab`, `default_settings()` for a new inventory lab | none | removed; `public_lab` keeps `telemetry` in its private-key list (a stale key must never leak) and gains `telemetry_retired` |
| Manager module | `telemetry.py` (state machine, scan loop, provisioning pool, collectors, `/api/telemetry/health`, `/api/telemetry/metrics`, `/api/labs/{id}/telemetry`, `…/telemetry/settings`, `…/telemetry/retry`, `…/telemetry/remove-config`, `…/telemetry/map.{svg,yml,json}`) | `diagnostics.py` lists the routes it does not count as activity | deleted; `diagnostics.py` list trimmed |
| Adapters, provisioning driver, collector, store, names, metrics, map | `telemetry_adapters.py`, `telemetry_provision.py`, `telemetry_collector.py`, `telemetry_store.py`, `telemetry_names.py`, `telemetry_metrics.py`, `telemetry_map.py` | `topology.py` cites `telemetry_names.nos_interface` in a comment only (the interface rules live in `topology.PORT_RULES`) | deleted; the comment is reworded |
| Persistent setting and ledger | `telemetry_settings.py` (`default_settings()` with `auto: True`, `settings_of()`), `lab['telemetry'] = {auto, decided, profile_id, applied: {node: {lines, at, kind}}}` | `discovery.py` and `vm_files.py` seed new labs with `default_settings()` | module deleted; the seeding removed; a startup migration in `telemetry_retirement.py` moves a non-empty `applied` ledger into the private `lab['telemetry_retired']` record and drops everything else |
| Grafana control | `grafana_control.py` (`/api/telemetry/grafana`, `…/start`, `…/stop`, idle monitor), helper `host_operations.py` `grafana` mode (`GRAFANA_CONTAINER`, `GRAFANA_ACTIONS`) | `lab_operations.invoke({'mode': 'grafana'})` from the control only | deleted; the helper's mode is removed (the helper version moves with the release, so the launcher refreshes the installed copy and the retired mode answers `Unknown request mode.`) |
| Manager UI | `index.html`: `#i-telemetry` symbol, `#menu-telemetry`, the Telemetry tool card (`#grafana-caption`, `#telemetry-line`, `#grafana-open`, `#tools-telemetry-settings`); `app.js`: `grafanaPath`, `grafanaLaunch`, `renderGrafanaLink`, `renderTelemetryLine`, the two click bindings; `operations.js`: the *Telemetry settings…* local action and `openTelemetrySettings` with its helpers; `status.js`: `STATUS_TELEMETRY_LINES`, `telemetryLine`; `style.css` `#grafana-headline` and the page list comment; `grafana.html`, `grafana.js` | `test_operations_ui.js`, `test_status_ui.js`, `test_readiness_ui.js`, `test_shell_ui.js` (menu item lists), `docs/redesign/tools/verify_after.py`, `docs/ui-review-001/tools/check_ui005.py` | removed; the tests keep their retained claims and lose the telemetry ones; the tools stop querying the removed ids |
| Manager environment | `compose.yml` and `deploy/compose.image.yml`: `TELEMETRY_COLLECTOR`, `TELEMETRY_STACK`, `TELEMETRY_GRAFANA_PORT`, `TELEMETRY_PROMETHEUS_PORT`, `TELEMETRY_GRAFANA_IDLE_MINUTES` | `test_release_consistency.py` pins the two files equal | removed from both; the test keeps the equality claim without the telemetry key |
| Dependencies | `requirements.txt` `pygnmi>=0.8.15,<0.9` and its exclusive transitives `grpcio`, `protobuf`, `dictdiffer` (`cryptography` and `typing-extensions` are shared with paramiko, ansible-core and pydantic) | Dockerfile installs `requirements.txt`; CI installs it for the tests | `pygnmi` removed; nothing else changes |
| VM stack | `deploy/compose.telemetry.yml` (project `clab-manager-telemetry`: Prometheus with restart `unless-stopped`, Grafana `container_name: clab-manager-grafana` with restart `no`, two tmpfs-backed volumes), `deploy/setup-telemetry.sh`, `deploy/setup_telemetry.py`, `deploy/telemetry/grafana/` (provisioning, three dashboards), `deploy/telemetry/smoke.py`, `deploy/TELEMETRY-THIRD-PARTY-NOTICES.md` | `start-manager.sh` (runs the setup unless `TELEMETRY_STACK=disabled`), `install-manager.py` (phase 5 and menu 4), `recreate-manager.sh` (comment), `check_install.py` (`check_telemetry`, `check_telemetry_dashboards`, `compose('telemetry')`), `verify-release.py` (`grafana.html` in the asset list; the third-party regex), CI (`bash -n`, `compose config`, the smoke test, the `test_telemetry*.py` glob) | deleted; replaced by `deploy/retire-telemetry.sh` + `retire_telemetry.py` (teardown), one health-check row for leftovers, and the CI entries removed |
| VM files written by the feature | `/srv/containerlab-node-manager/telemetry/prometheus.yml`, `…/telemetry/plugins/andrewbmchugh-flow-panel` (uid 472), `/srv/containerlab-node-manager/data/telemetry/dashboards/clab-map-*.json` (uid 10001), `clab-backup-ui/.env` `TELEMETRY_*` keys (including the Grafana admin password) | none after the removal | archived by the retirement script by default (`--purge` deletes); the `.env` keys are removed |
| Device configuration written by the feature | `lab['telemetry']['applied'][node]['lines']`; audit events `telemetry.configure` | the lines live on the devices | the migration keeps the ledger; the manager removes the lines on request, reads the device back and drops the entry only when the lines are absent |
| Guides | `docs/TELEMETRY.md`, `docs/GRAFANA-MAP.md`, telemetry sections of `README.md`, `docs/README.md`, `ARCHITECTURE.md`, `INSTALL.md`, `HEALTH-CHECK.md`, `LAB-OPERATIONS.md`, `WIKI-MASTER-GUIDE.md`, `QUICK-INSTALL.md`, `FRESH-VM-GUIDE-V2.md`, `STANDALONE-SETUP.md`, `TOUR.md`, `VM-CONNECTION.md`, `NODE-FEATURES.md`, `REPOSITORY-MAINTENANCE.md`, `CLAUDE.md` | readers | rewritten; `docs/TELEMETRY.md` becomes the retirement notice; `GRAFANA-MAP.md` and the notices file are deleted |

## 2. What stays although the words appear

- `lab-builder/src/main.tsx` `exportGrafanaBundle` and the `lab-builder.css` rule hiding
  `svg-export-grafana-*`: the upstream editor's own export feature, part of its adapter interface;
  the stub refuses it. Unchanged (and unchanged means the committed bundle still matches its source).
- `grpc` and `gnmi` lines in lab base configurations and in the quick-start example configurations: device
  content, not the manager's.
- `topology.py` interface rules: proven live on their own; only a comment cited the retired module.
- History: `docs/CHANGELOG.md`, `clab-backup-ui/VALIDATION.md`, `agent instructions.md`, `docs/redesign/`,
  `docs/ui-review-001/`, `docs/maintenance-audit/`, `docs/multi-platform-restore/`, `docs/save-location-fix/`,
  `docs/student-quick-start/`, `docs/ui-ux-cleanup/`.

## 3. Migration and teardown

**Manager state** (`app/telemetry_retirement.py`, run by `create_app()` after the download-metadata migration,
every start, idempotent). For each lab the old `telemetry` key is popped. A ledger of manager-added device lines
(`applied[node].lines`, non-empty) is kept under the private `telemetry_retired` key (`applied`, `retired_at`);
a record already there is merged per node (the newer `at` wins). A value that is not in the expected shape is
kept verbatim under `telemetry_retired.malformed` (bounded to 4 KiB) and reported by a warning event, never
replaced by a default. Everything else about the lab is untouched: the rehearsal tool
(`tools/upgrade_rehearsal.py`) proves it on an isolated copy of the real pre-change data (protected fields
identical before and after, second run a no-op). Events: `telemetry.retired` (per lab, names and counts),
`telemetry.retired.malformed`, `telemetry.retired.removed`, `telemetry.retired.absent`, `telemetry.retired.failed`,
`telemetry.retired.save_failed`; no configuration text in any of them. The public lab view carries only
`telemetry_retired: {nodes: [{name, short_name, lines: <count>}], total, malformed}` and only while a record exists.

**Device lines** (`GET/POST /api/labs/{id}/telemetry-retired[/remove]`, the lab notice *Review and remove…*, dialog
*Retired telemetry configuration*). Removal runs over direct node SSH with the lab's effective credentials, per
kind (EOS `management api gnmi`, IOS XR `grpc`, Junos Evolved `extension-service request-response grpc`), inside
the NOS's own configuration mode with the restore drivers' shell classes. It refuses (nothing changed) when the
block carries statements the manager did not add, when a change is waiting for confirmation or an exclusive
session is held, when the login does not reach the privileged prompt or the block cannot be read, and on any
NOS error (candidate discarded where the NOS allows it). It deletes a whole block only when the block holds
nothing but the manager's lines (Junos: the whole `… grpc` service, so no empty stanza is left; IOS XR:
a `no-tls` recorded alone into a pre-existing block is removed without touching the block). Outcomes:
`removed` (read back, lines gone, ledger entry dropped), `absent` (already gone after a redeploy, or the block
now holds only foreign statements: entry dropped, device untouched), `failed` (entry kept, controlled message),
`skipped` (not removable: device not running, login not proven, kind changed, node gone, or a removal already
running). An entry recorded before the lab's last manager-driven deploy is cleared without contacting the device
(`absent`: the device boots from its own files, and identical text such as containerlab's default cEOS `management
api gnmi` block is not proof of authorship); a redeploy run outside the manager is not known to this rule, so the
read-back still limits any deletion to recorded lines. Entries the manager can never act on (`permanent: true`:
device gone, unsupported or changed kind, invalid lines, redeployed lab) and an unreadable record can be dropped
with `POST …/telemetry-retired/forget` (`{node}` or `{malformed: true}`, event `telemetry.retired.forgotten`).
Guards: `operation_busy`, in-flight restores and recheck, running backup jobs, one removal per lab; while a
removal runs the lab record carries `telemetry_retired.removing` (never exposed), which `operation_busy` now
honours, so a restore, backup, Git save, import or lab operation cannot start over a removal (on Junos a commit
would otherwise confirm a foreign pending change); a stale flag is cleared by the next start. 120 s per node,
four workers. The lab notice, the dialog and the *Advanced options › Retired telemetry configuration…* menu item
are the entry points.

**VM stack** (`deploy/retire-telemetry.sh` → `retire_telemetry.py`, root, `start-manager.sh` runs it with
`--no-recreate` before every image build; options `--purge`, `--dry-run`, `--no-recreate`). Discovery is by the
Compose label `com.docker.compose.project=clab-manager-telemetry` only (containers, volumes, networks); a
container merely named `clab-manager-grafana` without the label is left alone; the two pinned image digests are
removed only when no other container uses them; only the two fixed folders `/srv/containerlab-node-manager/telemetry`
and `…/data/telemetry` are moved into `/srv/containerlab-node-manager/telemetry-retired-<UTC stamp>/{config,dashboards}`
(`--purge` deletes), each only when `path.resolve() == path` and no component is a symlink (a `.env` value naming
another folder is printed and skipped: the old setup never honoured it); every `TELEMETRY_*` line leaves
`clab-backup-ui/.env` as bytes (`\n`-split, terminators kept, archived as `env-telemetry.txt` mode 600 before the
rewrite unless `--purge`), every other byte of the file kept. Everything is read and validated before the first
destructive step (an unreadable or non-UTF-8 `.env` stops the run with a `Next:` hint before anything is removed).
A mixed tree (`deploy/compose.telemetry.yml` still present) is refused; the first failed step stops the run with a
non-zero exit; a clean VM reports nothing to do. `start-manager.sh` runs it twice, before the image build (frees
the Grafana image, stops Prometheus) and again after the manager is recreated (the old manager's loop may have
recreated the maps folder while the image was building). The
health check row `Retired telemetry stack` warns while any of these leftovers exist. Retention policy: the
Prometheus and Grafana volumes were tmpfs-backed and session-only (nothing to keep); the archive holds the
scrape file, the Flow panel plugin, the generated lab-map dashboards and the removed `.env` lines (including the
Grafana admin password), and is the operator's to delete.

**Rollback.** The pre-migration data copy is the rollback path: an older release started on migrated data would
recreate telemetry defaults but never see the removed ledger, so a downgrade needs the pre-upgrade copy of
`/srv/containerlab-node-manager/data` restored first (the audit's own copies are listed in [PICKUP.md](PICKUP.md)).

## 4. Residual references

Every remaining match of `telemetry|grafana|prometheus|gnmi|pygnmi|flow panel|andrewbmchugh` outside the history
folders, with its reason (search: `git ls-files` plus new files, 2026-09-23):

| Where | Reason |
|---|---|
| `app/telemetry_retirement.py`, `tests/test_telemetry_retirement.py`, `tests/test_telemetry_absence.py`, `tests/test_telemetry_retired_ui.js`, `deploy/retire_telemetry.py`, `retire-telemetry.sh`, `tests/test_retire_telemetry.py` | the migration, the teardown and their negative tests |
| `app/main.py` (retirement hooks, the `telemetry` key in the private list of `public_lab`), `app/host_operations.py` (comment: the `docker` key of old `operations.json` files is ignored), `app/static/app.js`, `operations.js` (the notice and the dialog), `deploy/check_install.py` (the `Retired telemetry stack` row), `deploy/start-manager.sh` (runs the teardown), `.github/workflows/release-check.yml` (runs the tests) | retained code that names the retired feature to migrate away from it |
| `tests/test_check_install.py`, `test_install_manager.py`, `test_release_consistency.py`, `test_lab_operations.py` | negative tests: the phase, the rows, the env keys and the helper mode are gone |
| `docs/TELEMETRY.md` | the retirement notice (kept at its path for existing links) |
| `README.md`, `docs/README.md`, `ARCHITECTURE.md`, `INSTALL.md`, `HEALTH-CHECK.md`, `LAB-OPERATIONS.md`, `WIKI-MASTER-GUIDE.md`, `VM-CONNECTION.md`, `NODE-FEATURES.md`, `CLAUDE.md` | one sentence each on the upgrade behaviour, the health-check row or the notice |
| `docs/LAB-BUILDER.md`, `lab-builder/src/main.tsx`, `app/static/lab-builder.css`, `app/static/lab-builder/assets/*.js` | the upstream editor's own Grafana-export hook, stubbed and hidden; the committed bundle is unchanged |
| `agent-instructions.md` | the symlink to the handoff history |
| History folders and files | untouched records of releases 1.23.0 to 1.30.38 |
