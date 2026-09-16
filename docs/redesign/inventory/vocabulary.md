# Backend state vocabulary and route contract — clab-manager 1.28.0

Source of truth: `/home/clabllm/projects/clab-manager/clab-backup-ui/app/` — every file below was read completely. Nothing in this document is inferred from the UI; every value is quoted from the Python that sets or returns it. Line references are to the files as read on 2026‑09‑16.

Assigned files read in full: `main.py`, `discovery.py`, `node_readiness.py`, `lab_operations.py`, `node_services.py`, `git_progress.py`, `restore.py`, `telemetry.py`, `capture.py`, `runner.py`, `store.py`.
Supporting files read (in full or the exact result-building blocks) because the assigned routes return their output: `downloads.py`, `inventory.py`, `telemetry_settings.py`, `vm_files.py`, `topology.py`, `layout.py`, `diagnostics.py`, `grafana_control.py`, `capture_sessions.py`, `restore_junos.py` (supported kinds + result keys), `telemetry_store.py` (constants + snapshot keys), `telemetry_collector.py` (emit events, group statuses, failure reasons), `telemetry_adapters.py` (SUPPORTED, labels), `host_operations.py` (capabilities/browse/read/popular/grafana/plan/execute results), `host_git.py` (status/history/browse/update/result blocks), `ansible/callback_plugins/backup_events.py`, `__init__.py` (`__version__ = "1.28.0"`).

---

## 1. GET /api/state — complete document

`main.py:179-187`. Returned under `store.lock`. Top level:

| field | type | source |
|---|---|---|
| `labs` | list of **public lab** objects | `public_lab(l)` for each `store.state['labs']` |
| `jobs` | list of **job** objects (all, newest first, decorated) | `decorate_job(copy.deepcopy(j))` |
| `platforms` | object keyed by platform id | `inventory.PLATFORMS` |
| `version` | string `"1.28.0"` | `__version__` |
| `discovery` | **discovery** object | `discovery.public()` |
| `git_jobs` | last 200 **public git job** objects (oldest→newest order of the stored list) | `public_git_job(j)` over `store.state['git_jobs'][-200:]` |
| `restore_jobs` | last 200 **public restore job** objects | `public_restore_job(j)` over `store.state['restore_jobs'][-200:]` |
| `operations` | last 200 **operation** objects, with `output` and `result` stripped | `store.state['operations'][-200:]` |

### 1.1 `platforms`
`inventory.py:17-23`. Keys: `juniper_cjunosevolved`, `juniper_vqfx`, `juniper_vjunosswitch`, `cisco_xrv9k`, `arista_ceos`. Each value: `label` (`Junos`, `Junos (vQFX)`, `Junos (vJunos-switch)`, `IOS-XR`, `EOS`), `os`, `command`, `suffix` (`set` for Junos, `cfg` for XR/EOS); the three Junos entries also carry `restore`, `restore_format` = `junos-hierarchical`, `restore_suffix` = `jcfg`.
`DEFAULT_CREDENTIALS` (`inventory.py:28-34`) exist for all five platforms (admin/admin@123 for the Junos kinds, clab/clab@123 for XRv9k, admin/admin for cEOS) — this is why `credential_source` can be `default`.

### 1.2 Public lab object (`main.py:133-154`)
Every stored lab key **except** `nodes`, `profiles`, `monitor_host`, `drawing`, `definition_yaml`, `telemetry` is deep-copied through. Stored lab keys observed being set anywhere in the read code:

| key | set where | notes |
|---|---|---|
| `id` | uuid hex | |
| `name` | inventory upload / definition / import | |
| `defaults` | `{platform_or_'ssh': profile_id}` | set by POST profiles with `make_default` |
| `interval` | minutes, 0 = manual | PUT schedule |
| `next_run` | epoch seconds or `null` | runner/scheduler |
| `created`, `updated` | ISO timestamps | |
| `source` | filename of the imported inventory/YAML | |
| `deployment_name` | containerlab lab name; **absence/empty = "Unlinked" lab** | PUT deployment, POST lab-definitions, import, sync |
| `container_prefix` | default `clab`; `''` allowed | same |
| `vm_source` | see §1.7 | discovery `update_sources`, `prepare_lab`; removed by PUT deployment |
| `vm_project_path` | VM YAML path | PUT operations-settings |
| `favorite` | bool | PUT operations-settings |
| `git_binding` | see §1.8 | git connect/link/destination; removed by unlink |

Added/overridden by `public_lab`:

| key | value |
|---|---|
| `profiles[]` | `{id, label, platform, username, auth}` only (secrets stripped). `platform` may be any PLATFORMS key **or `'ssh'`**; `auth` ∈ `password`, `key` |
| `nodes[]` | public node rows, §1.3 |
| `deployment` | `lab_status(state, lab)`, §1.4 |
| `nos_readiness` | `summarize(node nos_login states)`, §1.5 |
| `telemetry` | `telemetry.lab_summary(lab)`, §1.6 |

### 1.3 Public node row (`main.py:138-150`)
Every stored node key except `username`, `password`, `enable_password`, `container_name` passes through. Stored node keys (from `inventory.parse_inventory`, `discovery.parse_definition`, `discovery.reconcile`, `main.edit_node`, `vm_files.prepare_lab`):

`name`, `short_name`, `definition_node` (definition-sourced labs only), `address`, `port`, `platform` (PLATFORMS key or `''`), `kind` (raw containerlab kind, definition-sourced only), `enabled` (bool; always forced to `enabled and bool(platform)`), `profile_id` (`''` = use lab default / inventory / containerlab default), `groups` (list), `endpoint_mode` (`'auto'` | `'manual'`), `discovered` (bool), `runtime_state` (string), `discovered_address` (string).

Added by `public_lab`:

| key | rule |
|---|---|
| `available` | `node_available(state, lab, n)` (§2.4) |
| `readiness` | `readiness(lab, n)` when available, else the literal string `'Lab unavailable'` (§2.5) |
| `inventory_credentials` | `bool(username and password)` on the stored node |
| `credential_source` | `'profile'` \| `'inventory'` \| `'default'` \| `''` (§2.6) |
| `login_configured` | `available and bool(effective_credentials(lab,n).username)` |
| `nos_login` | `{status, message, at?}` from `login_state` (§2.7) |
| `ssh_ready` | `login_configured and nos_login.status in ('ready','unmonitored')` — **this is the gate the UI must keep for SSH/terminal buttons** |
| `telemetry` | `{state, message, at?}` from `telemetry.node_status` (§2.12) |

### 1.4 `deployment` (`discovery.lab_status`, `discovery.py:146-159`)
`{status, message}` plus, for linked labs only, `last_success` and `checked_at` (copied from the discovery record). Statuses in §2.1.

### 1.5 `nos_readiness` (`node_readiness.summarize`, `node_readiness.py:74-82`)
`{status, total, ready, booting, failed}`. Only nodes whose `nos_login.status` ∈ `ready|booting|failed` are counted (`total`). Statuses in §2.8.

### 1.6 `telemetry` lab summary (`telemetry.lab_summary`, `telemetry.py:547-555`)
Unlinked lab → `{status: 'unmonitored', total: 0}`.
Linked lab → `summarize(states)` = `{status, total, disabled, waiting, configuring, connecting, streaming, stale, unsupported, failed}` (one count per name in `STATES`; `total` = count of counted, supported states) **plus** `settings_of(lab)` = `{auto, decided, profile_id}` **plus** `grafana = {enabled, port, map_uid}` (`map_uid` non-empty only when Grafana is enabled and the lab has a drawing). Statuses in §2.13.

### 1.7 `vm_source` (`vm_files.metadata` + `prepare_lab` + `discovery.update_sources`)
`digest`, `files` (`{kind: {path, sha256}}` for kinds present among `definition`, `annotations`, `inventory`, `topology`), `missing` (list of absent kinds), `message`, `synced_digest`, `synced_at`, `status` (§2.16), `can_sync` (bool), `warnings` (list of strings).

### 1.8 `git_binding` (`git_progress.py:497-498, 563-564`)
`binding_id`, `revision`, `repository` (helper descriptor: `id, label, owner, path, remote, push_url, branch, prefix, revision`), `host_identity` (sha256 digest of VM address/port/username/fingerprint), `node_names` (list), `review_before_push` (bool).

### 1.9 Job object (`runner.py:175-179, 223-224, 377-384` + `downloads.decorate_job`)
`id`, `lab_id`, `lab_name`, `operation` (§2.17), `source` (§2.18), `created`, `status` (§2.19), `message`, `started` (once running), `finished` (terminal), `nodes[]`, optional `progress_id` (the git job or restore job that owns this backup) and `progress_context` (`{node_names, excluded_nodes, topology_digest}` for git saves; `{node_names}` for restore pre/post backups). Decorated: `archive_name` (`<lab>_<YYYY-MM-DD_HH-MM>.zip`), `download_timezone` = `'UTC'`.

`nodes[]`: `name`, `status` (§2.20), `message`; on a successful backup outcome also `file`, `platform`, `short_name`, `captured_at`, `capture_time_source` (`'NOS command completed'` or, backfilled, `'legacy job time'`), `download_metadata_version` (`1`), and when a Junos restore candidate was stored `restore_file`, `restore_format` (`'junos-hierarchical'`); decorated `download_name` only for nodes with `status == 'succeeded'` and a `file`.

### 1.10 Public git job (`git_progress.PUBLIC_JOB`, line 35-36)
`id`, `lab_id`, `lab_name`, `created`, `finished`, `status` (§2.21), `message`, `backup_job_id`, `commit`, `pushed`, `target` (§2.22), `checkpoint`, `changed_files`, `snapshot_path`, `note`, `review_before_push`. (Internal, never public: `request_digest`, `binding_digest`, `request`, `want_push`, `node_names`, `capture_context`, `snapshot_digest`, `expected_head`, `retry`, `retry_push`.)

### 1.11 Public restore job (`restore.PUBLIC_JOB`, line 37-38)
`id`, `lab_id`, `lab_name`, `created`, `finished`, `status` (§2.23), `message`, `source` (`{type, commit?, path?, backup_job_id?, folder?, captured_at, lab_name, restore_capable_nodes, saved_nodes}`), `confirm_minutes`, `pre_backup_job_id`, `post_backup_job_id`, `targets[]`.
`targets[]`: `name`, `short_name`, `platform`, `status` (§2.24), `message`; after load: `diff_sample` (≤40 masked lines), `root_authentication`, `no_op`; after verify: `missing_statements`, `extra_statements`, and on mismatch `missing_sample`, `extra_sample` (≤20 masked lines each).

### 1.12 Operation record (`lab_operations.py:246-247, 377-386`)
In `/api/state` and `GET /api/operations`: `id`, `lab_id` (`''` for lab-less actions), `name`, `action` (§2.26), `path`, `created`, `status` (§2.25), `message`, `exit_code` (`null` until finished), `started`, `finished`. `GET /api/operations/{id}` additionally returns `output` (scrubbed, last 512 KiB) and `result` (`{exit_code, recovery_path?, project_path?}`).

### 1.13 `discovery` (`discovery.public`, `discovery.py:386-404`)
| field | meaning |
|---|---|
| `host` | `{address, port, username, auth, command_mode, enabled, fingerprint}` or `null` when never configured |
| `configured` | `bool(host)` |
| `connected` | `discovery_fresh(state)`: host enabled **and** last inspection ok **and** younger than `MAX_AGE = 90 s` |
| `checking` | discovery lock currently held (a refresh is running) |
| `checked_at`, `last_success` | ISO timestamps |
| `error` | controlled error string or `''` |
| `interval` | `30` (server poll interval, seconds) |
| `file_import_supported` | helper returned file bundles |
| `file_reader` | `'inspect-only'` \| `'helper'` \| `'sftp'` |
| `helper_version` | string or `null` |
| `helper_update_required` | connected, `command_mode == 'helper'`, but no file import support |
| `pending_imports` | `{deployed_name: {nodes, files[]}}` — only while connected, else `{}` |
| `file_reports` | `{deployed_name: {kind: {status, message, paths[]}}}`; `status` ∈ `found, missing, permission_denied, timeout, unreadable, path_unavailable, sftp_unavailable` (`vm_files.REPORT_MESSAGES`) |
| `file_errors` | `{deployed_name: message}` |
| `ignored_labs` | list of deployed names excluded from auto-import |
| `discovered` | `[{name, nodes, running, imported, excluded}]` per lab seen on the VM |

---

## 2. Enumerations (value → meaning → where set)

### 2.1 `labs[].deployment.status` (`discovery.lab_status`)
| value | meaning | rule |
|---|---|---|
| `Unlinked` | workspace has no `deployment_name`; message "Import a lab YAML or link this workspace to discovery." | `not lab.deployment_name` |
| `Unknown` | discovery not fresh; message = discovery error or "Configure the VM connection and refresh discovery." | `not discovery_fresh` |
| `Not deployed` | no containers for this deployment on the VM | no rows for `deployment_name` |
| `Running` | every discovered container `running` **and** every saved node `discovered` with `runtime_state == 'running'` | |
| `Partially running` | at least one container running but not all/not all saved nodes | |
| `Stopped` | containers exist, none running | |
Message for the last three: `"{running}/{rows} discovered containers running; {expected} saved nodes. Container state does not verify NOS readiness."`

### 2.2 `labs[].nodes[].runtime_state` (`discovery.reconcile`, `parse_definition`)
Free-form containerlab container `state` string (≤40 chars; `running` is the only value compared), or `'absent'` when the expected container is not in the inspection, or `'unknown'` for a freshly parsed definition before reconcile.

### 2.3 `labs[].nodes[].endpoint_mode`
`'auto'` (address/port follow discovery) or `'manual'`. Set: definitions default to `auto`; inventory uploads and legacy binds default to `manual`; `PUT node` accepts either or infers `manual` when the address changes; `prepare_lab` forces `manual` when the inventory port ≠ 22.

### 2.4 `labs[].nodes[].available` (`discovery.node_available`)
`true` when the lab is unlinked; otherwise requires `discovery_fresh` **and** `discovered` **and** `runtime_state == 'running'` **and** (`endpoint_mode == 'manual'` or a `discovered_address`).

### 2.5 `labs[].nodes[].readiness` (`runner.readiness` + `public_lab`)
| value | meaning |
|---|---|
| `Choose NOS` | `platform` not in PLATFORMS |
| `Needs credentials` | no effective username |
| `Ready` | platform supported and a login exists |
| `Lab unavailable` | substituted by `public_lab` when `available` is false |
Only `Ready` nodes can be backed up/tested/scheduled.

### 2.6 `labs[].nodes[].credential_source` (`runner.credential_source`)
`'profile'` (node or lab-default profile exists), `'inventory'` (node has username+password), `'default'` (platform has a containerlab documented default login), `''` (none; also when a referenced profile id no longer exists).

### 2.7 `labs[].nodes[].nos_login.status` (`node_readiness.login_state`)
| value | message | rule |
|---|---|---|
| `unmonitored` | "SSH readiness is only monitored for labs linked to a VM deployment." | lab unlinked |
| `unavailable` | "Node is not running or discovery is stale." | `available == false` |
| `needs_credentials` | "Assign NOS credentials to this node first." | no effective username |
| `ready` | check message (automatic: "NOS accepted SSH login and answered show version (automatic check)"; manual: "SSH authentication succeeded") | latest SSH check `status == 'reachable'` |
| `failed` | check message (automatic: "SSH login refused with the saved credentials. Assign a credential profile, then Test login."; manual: "SSH login failed. Check credentials, address, port, and NOS readiness.") | check `status == 'failed'` |
| `booting` | "Container is running; the NOS has not answered an SSH login and show version yet" | no check yet / probe pending |
`at` is present for ready/failed/booting (may be `null`). Underlying `services.checks` entry: `{status: 'reachable'|'failed', at, message, source?: 'automatic'}`; the automatic monitor only records `failed` after `REFUSALS_BEFORE_FAILED = 3` consecutive refusals, retries booting nodes every `BOOT_RETRY = 20 s` and failed ones every `AUTH_RETRY = 60 s`, and scans every `SCAN_INTERVAL = 5 s`.

### 2.8 `labs[].nos_readiness.status` (`node_readiness.summarize`)
`idle` (no monitored node), `ready` (all monitored ready), `booting` (any booting), `failed` (otherwise, i.e. only ready/failed with ≥1 failed).

### 2.9 `labs[].nodes[].ssh_ready`
Derived: `login_configured && nos_login.status ∈ {ready, unmonitored}`.

### 2.10 `discovery.file_reader`
`inspect-only`, `helper`, `sftp`.

### 2.11 `discovery.file_reports[..][kind].status`
`found`, `missing`, `permission_denied`, `timeout`, `unreadable`, `path_unavailable`, `sftp_unavailable` (messages in `vm_files.REPORT_MESSAGES`).

### 2.12 `labs[].nodes[].telemetry.state` (`telemetry.node_status`, `STATES`)
| value | meaning / typical message |
|---|---|
| `unmonitored` | lab unlinked: "Telemetry is only collected for labs linked to a VM deployment." |
| `disabled` | collector unavailable (`self.unavailable` message), or lab setting off ("Automatic telemetry is off for this lab." / "…has not been enabled for this lab yet."), or during/after a remove-config run |
| `waiting` | not running/stale discovery; waiting for the NOS login check; waiting for a lab operation/backup; collector limit; store node limit; "Retry requested."; "Waiting for the next telemetry check." |
| `configuring` | SSH provisioning of gNMI lines in progress |
| `connecting` | gNMI dial-in opening / subscribing |
| `streaming` | usable samples arriving |
| `stale` | session open but no sample for > `STALE_AFTER = 45 s` |
| `unsupported` | no adapter for this kind (supported: `arista_ceos`, `cisco_xrv9k`, `juniper_cjunosevolved`) |
| `failed` | credentials problem, provisioning failure, or collector failure; message ends "Next attempt in N s." (backoff 15 s → 300 s; `auth` reason always 300 s; `connect` reason capped at 30 s) |

### 2.13 `labs[].telemetry.status` (`telemetry.summarize`)
`unmonitored` (unlinked), `disabled` (all nodes disabled/none), `unsupported` (no supported node), `streaming` (all supported streaming), `failed` (any failed), `partial` (some streaming or stale), `waiting` (otherwise).

### 2.14 Telemetry per-group status (`GET /api/labs/{id}/telemetry` → `nodes[].groups[group].status`, from `telemetry_collector` emits)
`subscribed`, `idle`, `streaming`, `unsupported`, `failed`. Collector failure `reason` values: `auth`, `connect`, `unsupported`, `error`.

### 2.15 Link/end states in the telemetry lab view (`telemetry.end_status`, `link_status`)
End: `up`, `down`, `stale`, `unknown`, `unsupported`. Link: `up`, `up-partial`, `down` (with `mismatch` true when the other end is up), `stale`, `unknown`. `DOWN_STATES` = `DOWN, LOWER_LAYER_DOWN, NOT_PRESENT, TESTING, DORMANT`.

### 2.16 `labs[].vm_source.status`
| value | set where |
|---|---|
| `Up to date` | `prepare_lab` (no issues) or `update_sources` when `synced_digest == bundle digest` |
| `Updates available` | `update_sources` when digests differ |
| `Imported with warnings` | `prepare_lab` with optional-file issues (`can_sync` false) |
| `Files unavailable` | `update_sources` start (before re-evaluation) or bundle invalid |
| `VM unavailable` | discovery refresh failed |

### 2.17 `jobs[].operation`
`backup`, `test` (POST jobs accepts only these; automatic monitor submits `test`).

### 2.18 `jobs[].source`
`manual` (POST jobs), `scheduled` (interval scheduler), `automatic` (readiness monitor login test), `git-progress` (git save capture), `restore-pre`, `restore-post`.

### 2.19 `jobs[].status` (`runner.py`, `store.py`)
| value | meaning |
|---|---|
| `queued` | "Waiting for SSH worker" |
| `running` | "Opening NOS CLI sessions over SSH" |
| `succeeded` | all nodes succeeded, git commit ok, ansible exit 0 |
| `partial` | some nodes succeeded |
| `failed` | no node succeeded, or exception |
| `interrupted` | worker restarted / storage failure / pool shut down (messages: "Worker restarted during this job; run again.", "Worker stopped before the capture started.", "Job interrupted before its result could be finalized…") |
Only one job may be `queued`/`running` at a time across all labs.

### 2.20 `jobs[].nodes[].status`
`queued` → during run the Ansible callback statuses are passed through: `running` (from `ok` of an intermediate task or task start), `failed`, `unreachable` → final outcome `succeeded` or `failed`; `interrupted` when the job was interrupted. Callback statuses are exactly `running`, `ok`, `failed`, `unreachable` (`backup_events.py`).

### 2.21 `git_jobs[].status` (`git_progress.py`)
| value | meaning | busy? |
|---|---|---|
| `queued` | save/retry/move queued | yes (`GIT_BUSY`) |
| `capturing` | running the backup capture | yes |
| `exporting` | publishing to the VM repository / moving folders / (update marker) | yes |
| `pushing` | pushing the commit | yes |
| `synced` | pushed and verified in remote history; terminal | no |
| `committed` | saved on VM, not pushed (push not wanted) | pending* |
| `review_pending` | committed, waiting for the user to review before push (binding `review_before_push`) | pending* |
| `push_pending` | commit exists but push failed / helper `needs_attention` | pending* |
| `export_pending` | capture done but export failed / helper `needs_attention` without commit | pending* |
| `capture_incomplete` | capture unusable ("Capture incomplete…"); terminal, retry refused | no |
| `failed` | no capture, no commit; terminal, retry refused | no |
| `interrupted` | manager stopped mid-save; retry allowed | pending* |
| `dismissed` | user chose "Keep snapshot only", or an `update` marker finished; terminal, retry refused | no |
| `unchanged` | referenced by `pending_progress` (`status == 'unchanged' and pushed` is not pending) — not set by any code read | — |
\*`pending_progress` = any git job whose status is not in `synced, dismissed, capture_incomplete, failed` (and not `unchanged`+pushed). Pending saves block: lab removal, VM identity change, git connect/link/unlink/destination/update, and the storage reset.

### 2.22 `git_jobs[].target`
`latest`, `checkpoint`, `baseline` (saves), `move` (folder move), `update` (repository update marker; always ends `dismissed`).

### 2.23 `restore_jobs[].status` (`restore.py`)
| value | meaning |
|---|---|
| `queued` | "Restore queued." |
| `preflight` | "Checking the lab and target nodes." |
| `backing_up` | "Backing up the current configuration first." |
| `applying` | "Applying the saved configuration." |
| `verifying` | "Verifying the restored configuration." |
| `confirming` | listed in `RESTORE_BUSY` but never assigned at job level in the code read |
| `succeeded` | all targets verified |
| `partial` | some restored, none needing review, some bad |
| `needs_attention` | applied but verification needs review, or unexpected exception ("Restore interrupted: …") |
| `failed` | no node restored, or pre-restore backup failure |
| `preflight_failed` | lab removed / VM changed / discovery stale / no live node |
| `interrupted` | manager restart or pool shutdown |
| `dismissed` | in `DONE` but never assigned in the code read |
`RESTORE_BUSY = queued, preflight, backing_up, applying, confirming, verifying` — any restore in these states blocks **every** backup on every lab (`runner.submit`) and counts as `operation_busy` for its lab.

### 2.24 `restore_jobs[].targets[].status`
`pending` → `ineligible` (not running at execute time) | `backing_up` → `applying` → `confirming` → `applied` → `verified` | `applied_unverified` | `verify_mismatch`; failures: `failed` (nothing changed), `rollback_expected` (commit armed but not confirmed; auto-rollback), `interrupted` (restart). `ready` and `preflight` are named in the restart handler but never assigned.

### 2.25 `operations[].status` (`lab_operations.py`)
`queued` ("Queued"), `running` ("Executing on the VM"), `succeeded` ("Operation completed", exit 0), `failed` ("Host command returned an error" or controlled error), `interrupted` ("Manager restarted; inspect the VM before retrying." / "Manager is shutting down…"). `BUSY = queued, running`.

### 2.26 `operations[].action`
`deploy`, `redeploy`, `destroy`, `apply`, `start`, `stop`, `restart`, `save`, `inspect`, `inspect-all`, `create`, `delete`, `clone`. Telemetry clears a lab's session when an operation with action in `LIFECYCLE = deploy, redeploy, destroy, start, stop, restart, apply` is submitted for it.

### 2.27 `GET /api/operations/capabilities` → `actions[action]`
Per action in the helper `LIFECYCLE` (`deploy, redeploy, destroy, apply, start, stop, restart, save, inspect`): `{available, cleanup, graceful}`; `redeploy` may carry `fallback: true` (destroy+deploy); `clone: {available}`. Top level also `protocol` = `clab-manager-operations-v1`, `version`, `roots[]`, `network` (bool).

### 2.28 Git helper `repository_status` (`GET /api/labs/{id}/git` → `repository_status`)
`{repository, head, ready, problem, baseline_revision, latest_manifest}`; on helper error the manager substitutes `{ready: false, problem: <message>}`. Helper journal `status` values surfaced as `result.status` inside a save: `needs_attention`, `committed`, `synced`; `update` returns `{status: 'updated', head, message}`.

### 2.29 `GET /api/capture/status`
`enabled` (bool), `provider` ∈ `edgeshark`, `disabled`, `message`, `setup_url` = `/static/capture-setup.html`.

### 2.30 Grafana control (`GET /api/telemetry/grafana`)
`{enabled, port, running (true|false|null=unchecked), idle_minutes, started_at, last_activity, checked_at, error, message}`.

### 2.31 Diagnostics probe check status (`POST /api/debug/probe` → `checks[].status`)
`pass`, `warning`, `fail`; on fail `code` ∈ `host-trust, vm-disabled, gateway-permission, gateway-account, untrusted-folder, missing-folder, not-directory, symlink-folder, timeout, authentication, helper-unavailable`.

### 2.32 Host settings (`discovery.host`)
`auth` must be `password`; `command_mode` ∈ `helper`, `direct`.

### 2.33 Event log levels and actions (`GET /api/logs` → `events[].level`, `events[].action`)
Levels: `info`, `warning`, `error`. Actions emitted by the read code: `worker.start`, `api.request`, `lab.remove`, `inventory.import`, `node.edit`, `credentials.create`, `schedule.update`, `schedule.deferred`, `download.device`, `download.archive`, `download.metadata.unavailable`, `job.queued`, `job.start`, `node.prepare`, `ssh.task.<status>`, `ansible.start`, `ansible.exit`, `ansible.diagnostic`, `node.validate`, `backup.write`, `restore.capture`, `restore.capture.skip`, `node.succeeded`, `node.failed`, `git.start`, `git.commit`, `git.unchanged`, `git.diagnostic`, `git.failed`, `job.finish`, `job.failed`, `nos.ready`, `ssh.check`, `terminal.open`, `terminal.close`, `sessions.export`, `topology.import`, `topology.layout`, `topology.positions`, `discovery.files`, `discovery.status`, `discovery.configure`, `lab.auto_import`, `lab.sync`, `lab.register`, `lab.operation`, `git.progress`, `git.connect`, `git.folder`, `git.destination`, `restore.queued`, `restore.prebackup`, `restore.node`, `restore.failed`, `restore.finish`, `telemetry.<state>`, `telemetry.clear`, `telemetry.configure`, `telemetry.remove`, `telemetry.unsupported`, `telemetry.settings`, `capture.launch`, `capture.end`, `grafana.start`, `grafana.stop`. Each event: `{time, action, message, level, lab_id, job_id, node}`.

---

## 3. Shared guards (the rules every button must respect)

| guard | definition | HTTP result |
|---|---|---|
| **CSRF/origin** (`main.py:90-95`) | any `/api/*` request with `Sec-Fetch-Site: cross-site` or an `Origin` ≠ base URL | 403 "Use this manager from its own browser page." |
| **reset pending** (`main.py:96-97`) | `.reset-pending` exists; every `/api/*` except `POST /api/manager/reset` | 503 "A storage reset needs completion. Retry Start fresh or restart the manager." |
| **body size** (`main.py:98-102`) | POST/PUT/PATCH/DELETE must send `Content-Length` 1..2 500 000 | 413 "Upload limit is 2.5 MB per request; content length is required." (400 on non-numeric) |
| **validation** | pydantic failure | 422 `{"detail":"Check the request fields and upload sizes."}` |
| `operation_busy(state, lab_id, progress_id)` (`lab_operations.py:29-37`) | any operation in `BUSY`, any git job in `GIT_BUSY`, or any restore in `RESTORE_BUSY` that belongs to this lab **or has no lab_id** (lab-less operations block everyone) | callers raise 409 "Wait for the lab operation to finish." |
| `get_lab` (`main.py:128-132`) | `operation_busy` then 404 "Lab not found" | 409 / 404 |
| `LabOperations.guard(lab_id)` | any active operation (memory `active` set or `operation_busy` on any lab) → 409 "Wait for the current lab operation to finish."; any backup/test job `queued|running` for this lab (or any lab when no id) → 409 "Wait for the lab backup or login job to finish." | 409 |
| `GitProgress.idle()` | `operation_busy` (any lab) or any job `queued|running` → 409 "Wait for the active backup, Git save or lab operation to finish."; reset pending → 409 "Finish the storage reset first." | 409 |
| `GitProgress.guard_pending(lab_id)` | `pending_progress` → 409 "Finish pending Git saves, or choose Keep snapshot only in Git history before continuing." | 409 |
| `RestoreService.guard_idle(lab_id)` | `operation_busy` or any job queued/running → 409 "Wait for the active backup, Git save, restore or lab operation to finish."; reset pending → 409 | 409 |
| `Discovery.idle(lab_id)` | `operation_busy` → 409 "Wait for the lab operation to finish." | 409 |
| `Runner.submit` (ValueError → 400 via POST jobs) | messages: "Wait for the lab operation to finish.", "A configuration restore is in progress. Wait for it to finish.", "Finish the manager reset before starting a job.", "A job is already running. Wait for it to finish.", "Lab not found", "Scheduled backup paused: lab discovery is unavailable or the lab is not fully running", "Select existing, distinct nodes", "Enable at least one supported node", "Selected nodes are not currently available. Refresh VM discovery before connecting.", "Complete NOS and credentials for: a, b, …" (first 8) | 400 |
| `NodeServices.node()` | 404 lab/node; `not node_available` → 409 "Node is unavailable; refresh VM discovery before connecting." | |
| `NodeServices.reserve()` | >32 open SSH clients → 429 "SSH session limit reached; close a session and retry." | 429 |

Server-side timers the UI polls against: discovery refresh every `INTERVAL = 30 s`, stale after `MAX_AGE = 90 s`, refresh-wait `75 s`; readiness scan 5 s; telemetry scan 5 s, sample interval 10 s, stale after 45 s; scheduler tick 2 s (deferred scheduled runs retry in 60 s); Grafana monitor 30 s, start timeout 75 s; preview tokens expire 300 s (operations and imports); terminal ticket 30 s; terminal idle 900 s / max 14 400 s; capture discovery timeout 8 s (+12 s read).

---

## 4. Routes — request, response, guards

Notation: `→` response; **G:** guards/conflicts; errors quoted verbatim.

### 4.1 Manager / state / logs (`main.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /` | — | `static/index.html` | |
| `GET /vm-connection-guide` | — | `static/vm-connection.html` | |
| `GET /api/state` | — | §1 document | none (not logged as an api.request) |
| `POST /api/manager/reset` | `{confirmation: "RESET"}` (extra fields forbidden) | `{reset: true, vm_connection_retained: true}` | 400 "Type RESET to confirm."; 409 "Discovery is checking the VM. Retry after it finishes."; `operations.guard()`; `git_progress.guard_pending()`; 409 "Close SSH sessions and wait for connection checks before resetting." (open terminals or a running ssh-check); 500 "Storage reset could not finish…". Keeps `host` (new revision) and nothing else. |
| `DELETE /api/labs/{lab_id}` | `{name (1-120, must equal current lab name), prevent_reimport: bool = true}` | `{removed: lab_id, name, prevent_reimport}` | `get_lab`; `guard_pending(lab_id)`; 409 "The lab name changed. Reopen Remove lab and try again."; 409 "Wait for this lab backup or login job to finish before removing it."; 500 "Could not save the removal. The workspace was retained." Removes the lab's jobs, git_jobs, restore_jobs; adds/removes the deployed name in `ignored_labs`. |
| `GET /api/logs` | query `lab_id, job_id, level, node (substring, case-insens.), limit (1-2000, default 500)` | `{events: [...]}` newest first across 4 rotated files | |

### 4.2 Labs, nodes, profiles, schedule, jobs, downloads (`main.py`)
| method path | request | response | guards |
|---|---|---|---|
| `POST /api/inventory` | multipart: `name` (≤120), `inventory` file (≤1 MiB), optional `lab_id`, optional `topology` file | public lab | 400 with parser messages ("Enter a lab name", "Upload no more than 2000 nodes per lab", "No hosts found in the inventory", …); with `lab_id`: `get_lab`, keeps `profile_id/short_name/platform/enabled` of nodes with the same name; all nodes get `endpoint_mode='manual'`; a schedule is cleared to 0 when any enabled node is not `Ready`. |
| `PUT /api/labs/{lab_id}/node` | `{name, address, port=22, platform='', profile_id='', enabled=true, short_name?: str, endpoint_mode?: 'auto'|'manual'}` (extra forbidden) | public lab | `get_lab`; 404 "Node not found"; 400 "Unsupported NOS"; 400 "Credential profile not found"; 400 address/port messages; 400 "Choose automatic or manual addressing"; 400 "Link a deployed lab before using automatic addresses"; `enabled` is forced false without a platform; `auto` triggers `reconcile`. |
| `POST /api/labs/{lab_id}/profiles` | multipart: `label` (≤120), `platform` (PLATFORMS key or `ssh`), `username` (≤128), `auth` (`password`|`key`), `password`, `passphrase`, `enable_password`, `make_default` (default true), `private_key` file (≤64 KiB, RSA/ECDSA/Ed25519) | public lab | 400 "Choose a supported NOS and authentication method", "Profile name and username are required", "Upload the SSH private key", "SSH key must be smaller than 64 KiB", "Cannot read the private key; verify its format and passphrase"; `get_lab`. No profile edit/delete route exists. |
| `PUT /api/labs/{lab_id}/schedule` | `{interval: 0..10080}` minutes | public lab | `get_lab`; 400 "Complete credentials for enabled nodes before scheduling" when interval>0 and (no enabled node or any not `Ready`). |
| `POST /api/labs/{lab_id}/jobs` | `{operation: 'backup'|'test' = 'backup', node_names?: [..] (≤2000)}` | job object (undecorated) | 400 "Invalid operation"; `runner.submit` messages (§3). `node_names` omitted = all enabled nodes and resets `next_run`; given = exact selection. |
| `GET /api/jobs/{job_id}/nodes/{node_index}/download` | — | file (`application/octet-stream`, filename = `download_name`) | 404 "Backup not found" (missing or not a backup); 409 "Wait for the backup to finish"; 404 "Device backup not found"; 404 "This device has no successful configuration backup"; 404 "Configuration file is unavailable" |
| `GET /api/jobs/{job_id}/download` | — | zip (`archive_name`) with `manifest.json` | as above plus 404 "This job has no saved configurations"; 404 "A configuration file is unavailable; download available devices individually" |

### 4.3 Discovery / VM connection (`discovery.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/discovery` | — | discovery object §1.13 | |
| `PUT /api/host` | `{address (≤253), port=22, username (1-128), auth='password', password='' (≤4096), command_mode='helper', enabled=true, reset_fingerprint=false}` | discovery object | 400: "VM connections require password authentication", "Choose a valid inspection mode", "Enter a VM username", "Enter the VM password" (password may be omitted only when address/port/username/auth are unchanged), address messages; `idle()`; 409 "Finish pending Git saves or choose Keep snapshot only before changing the VM identity."; fingerprint kept only when address+port unchanged and not `reset_fingerprint`. Wakes the discovery loop. |
| `POST /api/discovery/refresh` | — | discovery object with `checking: false` (or the current public object if the lock could not be taken within 75 s) | no-op when host not enabled |
| `POST /api/discovery/import-preview` | `{name}` | `{name, token, nodes, links, files (manifest), missing[], warnings[], excluded}` | refreshes first; 409 "A fresh VM connection is required…", "This deployment already has a saved workspace…", "A saved workspace has this name…", file error / "The VM helper needs updating…" / "The deployed files are unavailable…", bundle errors. Token valid 300 s. |
| `POST /api/discovery/import` | `{name, token (32)}` | public lab | refreshes; `idle()`; 409 "Import confirmation expired. Preview the lab again."; 409 "The VM, lab files or import setting changed. Preview the lab again before confirming."; 500 "Could not save the imported lab…". Clears the name from `ignored_labs`. |
| `POST /api/discovery/forget-exclusion` | `{name}` | `{cleared: name}` | 500 "Could not save the change. Exclusion retained." |
| `POST /api/discovery/allow-import` | `{name}` | always 409 "Import again now requires a preview and confirmation. Refresh the browser and choose Import again." | legacy |
| `POST /api/labs/{lab_id}/sync` | — | public lab | refreshes; `idle(lab_id)`; 404; 409 "Fresh VM files are unavailable. Refresh discovery, upgrade the helper, or import manually."; 400 "VM files are invalid or inconsistent; the saved workspace was retained." Replaces the lab from VM files, keeping saved node settings/history. |
| `PUT /api/labs/{lab_id}/deployment` | `{deployed_name='' (≤120), prefix='clab' (≤120)}` — empty name unlinks | public lab | 400 identifier messages; `idle(lab_id)`; 404; 409 "That deployment is already linked to another workspace". Drops `vm_source`, defaults node `endpoint_mode` to `manual`, reconciles. |
| `POST /api/lab-definitions` | multipart: `definition` (≤1 MiB YAML), `lab_id=''`, `deployed_name=''`, optional `annotations` | public lab | 400 parser messages; `idle(lab_id)`; 404 "Lab not found"; 409 "Several saved workspaces match this name…", "Deployment already linked to another workspace". Creates or updates (matching by `lab_id`, else `deployment_name`, else a unique legacy inventory lab with that name); keeps node identity/settings by `definition_node`. |

### 4.4 Node services (`node_services.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/labs/{lab_id}/health` | — | `{nodes: [{name, ssh: check or null, backup: {job_id, status, at} or null}]}` (latest backup job outcome per node) | 404 |
| `POST /api/labs/{lab_id}/ssh-check` | `{name (1-200)}` | `{status: 'reachable'|'failed', at, message}` | `node()` (404/409); 400 "Assign SSH credentials to this node first."; 409 "A login check is already running for this node."; 429 session limit |
| `POST /api/labs/{lab_id}/terminal-ticket` | `{name}` | `{ticket, expires_in: 30, endpoint: "addr:port"}` | as above; 429 "Too many pending terminal sessions" (>32) |
| `WS /api/terminal` | first text frame within 5 s: `{"ticket": ...}` (≤512 B); then `{"type":"input","data":str≤16 KiB}` or `{"type":"resize","cols":20-400,"rows":5-150}` | server sends `{type:'status', message:'Connected'}`, raw bytes, `{type:'status', message:'Session timeout. Reconnect to continue.'}`, `{type:'error', message:'Session ended. Check credentials, endpoint, and session limits.'}` | origin must match (close 1008); bad/expired ticket → close 1008; idle 900 s, max 14 400 s |

### 4.5 Lab operations (`lab_operations.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/operations/capabilities` | — | §2.27 (cached 60 s per host revision) | `invoke` errors → 409 with helper/connection message ("Configure and enable the VM connection first.", "Refresh discovery to establish the VM fingerprint first.", "Cannot reach the VM operations helper. Check setup and SSH settings.", gateway messages) |
| `POST /api/operations/browse` | `{path=''}` | `{path, parent, entries: [{name, path, directory}]}` (roots when path empty; only dirs and `*.clab.yaml|yml`, ≤500) | 409 helper errors |
| `POST /api/operations/read` | `{path}` | `{path, text, sha256}` (≤1 MiB; only .yaml .yml .json .drawio .txt .cfg .conf .set) | 409 |
| `GET /api/operations/popular` | — | `{items: [{name, url, description}]}` (srl-labs GitHub catalog, needs `network`) | 409 |
| `POST /api/operations/parse-yaml` | `{options: {text, annotations?}}` | `{name, drawing, annotations_used}` | 400 "Enter a valid literal Containerlab topology." |
| `POST /api/operations/preview` | `{action, lab_id='', path='', name='', options={}}`; options ⊆ `cleanup, graceful, url, project, text` | helper plan `{action, name, source_name, path, source_hash, affected: [{name,id,state}], argv, steps, digest, warnings[]}` + `token` (options stripped) | 400 "This lab operation has been removed or is unsupported." (action not in the 13); `guard(lab_id)`; 404 "Lab not found."; 400 "The VM file must contain a valid literal Containerlab topology." / "Use valid literal Containerlab YAML for the new project."; 409 "Source changed during review; retry."; 409 "VM connection changed. Preview again."; helper 409s. Token 300 s, ≤50 kept. |
| `POST /api/operations/confirm` | `{token (32)}` | operation record (§1.12, with `output: ''`) | 409 "Review expired; preview the operation again."; 409 "VM changed. Preview again."; 409 "Saved lab was removed. Preview again."; `guard`; 500 "Could not save the operation; nothing was submitted."; 409 "Manager is shutting down. Preview again after restart." After execution discovery is refreshed. |
| `GET /api/operations` | — | list newest first, without `output` (keeps `result`) | |
| `GET /api/operations/{job_id}` | — | full record incl. `output`, `result` | 404 "Operation not found." |
| `PUT /api/labs/{lab_id}/operations-settings` | `{favorite?: bool, path?: str}` | `{saved: true}` | 404; `guard(lab_id)`; 400 "The selected VM YAML does not match this lab name."; 409 "VM connection changed. Select the project again."; 404 "Lab was removed." |
| `GET /api/labs/{lab_id}/drawio?layout=interactive` | — | `.drawio` XML attachment | 400 "Choose a supported layout."; 404 |
| `PUT /api/labs/{lab_id}/layout` | `{positions: {nodeId: [x,y]}, decorations?: [...], revision?: str}` | `{saved: true}` | `guard`; 404 "Import a topology map first."; 409 "The map changed. Reopen the editor before saving or exporting."; 400 "Unknown map nodes." / "Invalid node coordinates." / decoration messages; 500 "Could not save the layout. Try again." Sets `drawing.placed = true`. |
| `POST /api/labs/{lab_id}/annotations` | same Layout body | `.clab.yaml.annotations.json` attachment | as `positioned` |
| `POST /api/labs/{lab_id}/drawio` | same Layout body | `.drawio` attachment of the posted layout | as `positioned` |

### 4.6 Topology (`topology.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/labs/{lab_id}/topology` | — | bound drawing (`{schema:3, nodes[{id, alias, label, x, y, icon, iconColor, labelPosition, labelBackgroundColor, iconCornerRadius, interfacePattern, direction, inventory_name}], links[[{node, interface, label_offset?},{...}]], decorations[], has_links_source, skipped_links, placed, settings{background, gridColor, labelMode, endpointOffset}, revision}`) or `null` | 404 |
| `POST /api/labs/{lab_id}/topology` | multipart `annotations` (required), optional `topology` | bound drawing | 400 "Invalid drawing: …"; 409 "Wait for the lab operation to finish." |
| `POST /api/labs/{lab_id}/superputty` | `{include_passwords=false}` | `sessions.xml` attachment | 400 "Duplicate session short names; edit node names before exporting" etc. |

### 4.7 Git progress (`git_progress.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/git/repositories` | — | `{protocol: 'clab-manager-git-v1', version, repositories: [descriptor]}` | 409 "Update the VM Git helper to match manager 1.28.0 using setup-git.sh --refresh." / "Invalid repository list." / connection messages |
| `GET /api/labs/{lab_id}/git` | — | `{binding, repository_status, jobs (lab's git jobs newest first), supported_nodes: [{name, short_name, platform}], unsupported_nodes: [names]}` | 404 |
| `PUT /api/labs/{lab_id}/git` | `{binding_id, node_names (1-500), review_before_push=false}` | `{saved: true, binding}` | `idle`; `guard_pending`; 404; 400 "Choose a repository registered by the VM administrator."; 409 "VM connection changed. Connect again."; 400 "Select distinct supported devices from this lab."; 409 "This registered destination is already connected to another lab. Register a separate prefix."; 500 |
| `GET /api/git/repositories/{binding_id}/tree` | — | `{repository, head, files: [{path, size}], truncated, saved: {latest, baseline, checkpoints: epoch|null}, folders: [{id, label, prefix, lab: {id,name}|null}]}` | 404 "This repository is not registered on the VM. Refresh the list."; 409 helper |
| `POST /api/git/repositories/{binding_id}/folders` | `{prefix=''}` | `{repository: descriptor}` | 400 folder-name rule; 409 "The VM did not return the new folder registration." |
| `POST /api/labs/{lab_id}/git/destination` | `{prefix='', move_files=false}` | `{saved: true, binding, job: public git job|null}` | `idle`; `guard_pending`; binding required (409 "Connect this lab to a Git repository first."); 409 "Reconnect the original VM before changing the folder."; 409 "This lab already saves to that folder."; 409 "This folder is already connected to another lab (<name>). Choose a different folder."; move job has `target: 'move'`, push wanted |
| `POST /api/labs/{lab_id}/git/connect` | `{url (1-2048), prefix='', node_names=[], review_before_push=false, acknowledge=false}` | `{saved: true, binding}` | **400 "Acknowledge that full device configurations will be committed and pushed to this repository."** when `acknowledge` false; `idle`; `guard_pending`; 404; 409 "The VM did not return the repository registration."; bind_lab errors |
| `POST /api/labs/{lab_id}/git/unlink` | — | `{unlinked: true}` | `idle`; `guard_pending`; 404; 500 "Could not disconnect the repository." |
| `POST /api/labs/{lab_id}/git/save` | `{request_id (32 hex), target='latest'|'checkpoint'|'baseline', checkpoint='' (≤100, `[A-Za-z0-9][A-Za-z0-9_-]{0,99}`), push=true, note='' (≤500, single line), backup_job_id='', replace_baseline=false, expected_baseline='', allow_removed=false}` | public git job (idempotent on `request_id`) | 400 "Choose latest, checkpoint or baseline.", "Use a checkpoint name containing…", "Select a complete saved capture for the baseline." (baseline needs `backup_job_id`), "Use a single-line save note."; 409 "Request ID already belongs to a different save."; `idle`; binding 409; 409 "Reconnect the original VM before saving progress."; 409 "Configured devices changed. Review the Git repository device selection."; 404 "Capture not found in this lab."; 400 capture errors; 400 "Capture must contain exactly the configured devices."; 500. `review_before_push && push` → job ends `review_pending`. |
| `GET /api/git/jobs/{job_id}` | — | public git job | 404 "Git save not found." |
| `POST /api/git/jobs/{job_id}/retry` | `{push=true}` | public git job | `idle`; 409 "Start a new save for this capture outcome." for `dismissed|capture_incomplete|failed`; `synced` returns unchanged; 409 "Repository settings changed. Reconnect the original destination." |
| `POST /api/git/jobs/{job_id}/dismiss` | `{acknowledge=false}` | public git job | **400 "Confirm keeping the snapshot without tracking its pending Git save."**; `idle` |
| `POST /api/labs/{lab_id}/git/update` | — | helper `{status: 'updated', head, message}` | `idle`; `guard_pending`; binding; creates a marker git job (`target: 'update'`, status `exporting`) that always ends `dismissed`; 409 helper ("Local and remote history diverged…", "The checkout changed…") |
| `GET /api/labs/{lab_id}/git/history` | — | `{commits: [{commit, time, message}] (≤50), versions: [{name, path, commit, connected, label}]}` — `label` = `"<folder> · latest|baseline|checkpoint · <name>"` | binding; 409 helper |
| `POST /api/labs/{lab_id}/git/version` | `{commit (40-64 hex), path (1-250)}` | `{manifest, files: [{name, text}], restore_supported, restore_nodes[]}` | 400 "Choose a saved version." / "Choose a safe saved version path." / "Choose latest, baseline or a named checkpoint version."; 409 decode errors ("Version integrity check failed." …) |
| `POST /api/labs/{lab_id}/git/version/download` | same | zip `<lab>-<commit12>.zip` | same |
| `POST /api/labs/{lab_id}/git/compare` | `{job_id=''}` **or** `{commit, path}` | `{files: [{name, status: 'added'|'removed'|'changed', before, after}]}` | job form: 404 "Git save not found in this lab."; 409 "Reconnect the original repository to review this save."; commit form: 400 "Choose a saved commit."; compares the version with HEAD's connected `latest` |

### 4.8 Restore (`restore.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/labs/{lab_id}/restore/sources` | — | `{backups: [{backup_job_id, created, finished, nodes[]}], supported_nodes[], unsupported_nodes[], restore_supported_platforms: ['juniper_cjunosevolved','juniper_vjunosswitch']}` | 404 |
| `POST /api/labs/{lab_id}/restore/preflight` | `{source: {type: 'git'|'backup'|'folder', commit='', path='', backup_job_id=''}, node_names?: [..]}` | `{source, targets: [{name, short_name, platform, running_platform, eligible, reason, requested, reachable?, matches_saved?, pending_changes?}], eligible_count}` | 404; `guard_idle`; source errors (409 git/folder, 404 "Saved capture not found in this lab.", 400 capture errors, 400 "Choose a saved folder to apply.", 400 "Choose a saved Git version, a saved folder or a saved capture as the restore source."); ineligibility reasons: "No running node in this lab matches this saved node.", "Live restore is not supported for this platform yet.", "The saved platform does not match the running node.", "The node is not currently running or discovery is stale.", "Assign NOS credentials to this node first.", "Refresh VM discovery before restoring.", "SSH probe failed: <Exception>" |
| `POST /api/labs/{lab_id}/restore` | `{request_id (32 hex), source, node_names (1-500), confirm_minutes=5 (2-60), acknowledge=false}` | public restore job (idempotent on `request_id`) | **400 "Acknowledge that the running configuration will be replaced."**; 404; `guard_idle`; 400 "Select at least one saved node to restore."; 409 "Some selected nodes cannot be restored: name: reason; …"; 409 "VM connection changed. Reconnect and try again."; 500 |
| `GET /api/restore/jobs/{job_id}` | — | public restore job | 404 "Restore job not found." |

### 4.9 Telemetry (`telemetry.py`, `grafana_control.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/telemetry/health` | — | `{enabled, collector: 'gnmi'|'disabled', message, library: 'pygnmi'|'missing', method, sample_interval: 10, sessions, states: {state: count}, queue, queue_dropped, bounds{collectors:64, provisioning:4, queue:5000}, store, supported_kinds, grafana{enabled,port,prometheus_port}, maps, metrics_path}` | |
| `GET /api/telemetry/metrics` | — | Prometheus text | |
| `GET /api/labs/{lab_id}/telemetry` | — | lab view: `{lab_id, lab_name, generated_at, enabled, unavailable, grafana{enabled, port, prometheus_port, map_uid}, settings{auto, decided, profile_id, profile_label}, method, sample_interval, stale_after: 45, summary, nodes: [{name, short_name, platform, label, supported, state, message, at?, endpoint, transport, groups, attempts, applied, first_sample, method, last_sample, fresh, samples, dropped, overflow, interfaces: [{name, role, wired, peer, peer_interface, drawn, …rates}], peers[]}], links: [{index, status, mismatch, ends: [{node, label, interface, nos_interface, state, rx_bps, tx_bps, oper, at}]}], linked, password_profiles: [{id,label,platform}]}` | 404 |
| `GET /api/labs/{lab_id}/telemetry/map.svg` / `map.yml` / `map.json` | — | generated Grafana map SVG / panel YAML / dashboard JSON | 404 "This lab has no drawing yet. Import its topology first." |
| `PUT /api/labs/{lab_id}/telemetry/settings` | `{auto: bool, profile_id='' (≤64)}` | lab view | 404; 400 "Credential profile not found"; 400 "gNMI needs a password profile; SSH keys cannot be used." Sets `decided=true`; `auto=false` clears the lab session. |
| `POST /api/labs/{lab_id}/telemetry/retry` | `{node=''}` | `{retried: [names]}` | 404 "Node not found"; only nodes in `failed|stale|unsupported` are reset to `waiting` "Retry requested." |
| `POST /api/labs/{lab_id}/telemetry/remove-config` | `{node=''}` | `{started[], skipped[], message}` | 409 "Disable automatic telemetry first; otherwise the lines would be added again."; 404 when a named node matched nothing; a node is skipped when it has no owned lines/adapter, is not running/reachable, has no login, or is in flight |
| `GET /api/telemetry/grafana` | — | §2.30 | |
| `POST /api/telemetry/grafana/start` | — | status | 409 "The Grafana stack is not installed on this manager. Run sudo bash deploy/setup-telemetry.sh on the VM."; 409 "The Grafana container does not exist on the VM…"; 409 "Grafana was started but did not answer within 75 s…"; helper 409 (incl. "The VM operations helper predates on-demand Grafana…") |
| `POST /api/telemetry/grafana/stop` | — | status | 409 not installed; helper 409 |

### 4.10 Packet capture (`capture.py`, `capture_sessions.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/capture/status` | — | §2.29 | |
| `GET /api/capture/targets` | query `lab_id='' (≤100)`, `node='' (≤200)` | `{targets: [{id (64 hex), name, kind, prefix, interfaces[], aliases[]}], message}` | 404 lab/node; 400 "A node filter requires a lab."; 503 disabled ("Packet capture is disabled. Follow Capture setup to enable Edgeshark." or config error); 429 "Capture discovery is busy. Retry shortly."; 502 provider errors |
| `POST /api/capture/launch` | `{target_id (64 hex), interfaces (1-128), request_id? (64 hex)}` | `{id, url: '/static/capture-session.html#<id>', message}` | 503 "Browser capture is disabled. Follow Capture setup."; 409 "Capture target changed or disappeared. Refresh interfaces and select it again."; 409 "Select interfaces from the refreshed live list."; 502 "Browser capture service returned an invalid session."; session-service 404/409/429/503/502 messages |
| `GET /api/capture/health` | — | session service health | 503 when disabled |
| `GET /api/capture/sessions` | — | owner's sessions (sets `clab_capture_owner` cookie) | |
| `GET /api/capture/sessions/{sid}` | — | session | 404 "Capture session not found." / "…not owned by this browser." |
| `POST /api/capture/sessions/{sid}/end` | — | service result | |
| `GET /api/capture/sessions/{sid}/assets/{path}` | — | JS asset (≤2 MiB) | 404/502 |
| `GET /api/capture/sessions/{sid}/download` | — | `wireshark-captures.tar` | 404; 409 service detail or "Capture files unavailable. Check the session and save files in /pcaps first."; 502 |
| `WS /api/capture/sessions/{sid}/websockify` | binary noVNC frames (≤4 MiB) | relay | origin check → close 1008 |

### 4.11 Diagnostics (`diagnostics.py`)
| method path | request | response | guards |
|---|---|---|---|
| `GET /api/debug` | — | `{schema: 1, generated_at, manager_version, python_version, packages, uptime_seconds, vm{configured, enabled, password_saved, fingerprint_saved, connected, checking, file_import_supported, discovery_helper_version}, audit_log_available, saved_counts{labs,jobs,operations,git_jobs}, requests: [{time, id, method, route, status, duration_ms}] (≤200), scope}` | |
| `POST /api/debug/probe` | `{path=''}` | `{generated_at, checks: [{check: 'browse'|'capabilities', status, entry_count?, helper_version?, message?, code?, duration_ms}]}` | 409 "A diagnostic check is already running. Wait for it to finish."; 409 "VM settings changed during the check. Run it again." |
Every `/api/*` response carries `X-Request-ID`. Static pages present: `index.html`, `workspace.html`, `terminal.html`, `capture-session.html`, `capture-setup.html`, `debug.html`, `grafana.html`, `vm-connection.html`.

---

## 5. Cross-cutting facts a redesign must preserve

1. `available` false ⇒ `readiness` is the string `Lab unavailable`, `login_configured` false, `ssh_ready` false, `nos_login.status` = `unavailable`.
2. Only **one** backup/test job may run at a time across all labs; a restore in progress blocks all backups; a git save's own capture and a restore's own pre/post backups are exempt via `progress_id`.
3. Lab-less operations (`inspect-all`, `create`, `clone`, and any preview without `lab_id`) block every lab (`operation_busy` treats empty `lab_id` as global).
4. Discovery "connected" decays after 90 s without a successful inspection; after a manager restart the previous snapshot is marked `ok=false, error='Waiting for a fresh VM inspection.'` until the first refresh.
5. Scheduled backups are deferred (retry in 60 s, event `schedule.deferred`) unless the lab is unlinked or `deployment.status == 'Running'`.
6. The automatic readiness monitor runs one `test` job with `source: 'automatic'` per boot cycle once every running node with a login is `reachable`; a failed automatic test resets those nodes to `booting` up to 3 attempts, then logs "Automatic NOS login test failed repeatedly; check the credentials and run Test NOS login by hand".
7. Telemetry never runs while its lab is `operation_busy` or has a queued/running job; submitting a lifecycle operation clears the lab's telemetry session.
8. Confirmations the backend enforces (the UI must still send them): reset `confirmation: "RESET"`; remove lab `name` must match; git connect `acknowledge`; git dismiss `acknowledge`; restore `acknowledge`; preview→confirm `token` (300 s); import-preview→import `token` (300 s); layout `revision` conflict.
9. Idempotency keys the UI generates: git save `request_id` (32 hex), restore `request_id` (32 hex), capture launch `request_id` (64 hex, optional).
