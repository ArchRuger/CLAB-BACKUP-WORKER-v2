# CLAB Backup Worker — Agent Instructions

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
Read FRESH-VM-GUIDE.md for fresh Ubuntu setup and helper/key-preserving upgrades.

## Release 1.7.0 addendum — standalone persistent manager

The user explicitly authorized host SSH discovery, overriding earlier statements
that the worker must not connect to its host. Scope is fixed read-only inspection;
do not add host metrics, Docker socket mounts or lab lifecycle commands.

Default compose.yml now runs independently of containerlab, with Linux host
networking, UI port 8081, fixed project name and a /srv/containerlab-node-manager/data
bind mount. Image UID/GID are both 10001. Read STANDALONE-SETUP.md for setup,
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

See FRESH-IMAGE.md before replacing the worker: the supplied YAML has no /data mount.
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
