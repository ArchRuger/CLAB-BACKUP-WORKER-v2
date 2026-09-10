# Containerlab Node Manager — 1.6.1

Version 1.6.1 fixes topology imports using the supplied 13-node/16-link lab: node coordinates, legacy note spacing, shape opacity, and IOS-XR interface labels. The right-click SSH/backup menu is verified with the actual drawing and local test endpoints. See [fresh image and worker upgrade](../FRESH-IMAGE.md) before replacing an existing worker; the supplied lab YAML has no persistent `/data` mount.

A self-contained Docker application for backing up Junos, IOS-XR, and Arista EOS
configuration over SSH. The image starts empty. Upload containerlab's generated
Ansible inventory in the browser, review the nodes, add NOS credentials, test the
login, and run or schedule backups.

The worker never needs a Docker socket, host directory bind, host VM login, or
access to containerlab's files on the VM. It treats the targets as network
appliances, connects to their NOS management SSH service, and runs vendor CLI
commands. No Docker exec or container filesystem access is used.

## Start the application

Extract this project into a fresh build directory. Use the Docker network that can
reach your NOS management addresses. For same-host containerlab this is normally
the lab management bridge; its actual name must match your deployment.

```bash
cd clab-backup-ui
export CLAB_NETWORK=clab   # replace if your management network has another name
docker compose up -d --build
docker compose logs backup-ui
```

Open `http://<containerlab-host-IP>:8080` in your browser. The worker startup log
prints `NOS Backup UI access token: ...`. Enter that token in the UI. It is generated
at first boot and retained in the worker's volume, not baked into the image.

UI_PORT can change the published port and UI_BIND can limit the listening host
address. The default Compose mapping is 0.0.0.0:8080. The application uses HTTP by
default for an isolated lab; use your HTTPS reverse proxy for access over an
untrusted network because inventory uploads may contain credentials.

Stop the previous backup workers before switching to this UI. Do not run the old
backup worker and the UI's schedule against the same lab unintentionally. No router
restart or topology redeployment is needed for this Compose sidecar.

For targets with routable management addresses on another host, the image can run
on an ordinary Docker bridge instead of the existing management network:

```bash
docker run -d --name nos-backup-ui --restart unless-stopped \
  -p 8080:8080 \
  --mount type=volume,src=nos-backup-ui-data,dst=/data \
  clab-backup:webui
```

Uploading an inventory does not create network reachability. Private Docker bridge
addresses require attachment to that network or appropriate routing. If using
published SSH ports, edit each node's NOS endpoint and port in the UI. The endpoint
must forward to the NOS SSH service, not to the host VM's SSH service.

## Browser workflow

1. **Import a lab:** choose a display name and upload `ansible-inventory.yml` from
   containerlab. Obtain the generated file using your existing file transfer or
   editor workflow and upload it from your browser. The worker does not locate or
   read its original host path.
2. **Review inventory:** supported kind groups identify NOS types automatically.
   Unknown or unsupported kinds are disabled. Edit a row to map its NOS, address,
   SSH port, credential profile, or inclusion in backups.
3. **Add credentials:** credentials included in the inventory are imported. Add
   password or private-key profiles through the UI when needed. Profiles can be
   defaults per NOS or assigned to individual nodes. Encrypted SSH keys accept a
   passphrase. Credentials are entered for the NOS, not Docker or the host VM.
4. **Test NOS login:** connects over SSH and runs `show version` on enabled nodes.
   This proves a NOS command succeeded, not just that TCP/22 is open.
5. **Back up now:** retrieves active configuration and shows per-node results.
6. **Backup history:** download configuration ZIPs and inspect failures. Set a
   backup interval in minutes; 0 disables scheduling. A schedule first runs after
   its interval. A manual run also resets that lab's next scheduled time.
7. **Replace inventory:** upload a fresh inventory after lab changes. Matching
   node names retain their profile assignment and enabled state. Uploaded addresses
   and ports replace previous values; per-node endpoint overrides must be reviewed
   again. New nodes are parsed automatically. Stored profiles remain available.

The image is reusable for any lab with these supported kinds. Multiple labs may
be imported into one worker. Inventory discovery happens on upload, not by polling
an inaccessible host file. No lab name, address, topology, inventory, NOS account,
or private key is packaged in the application image.

## Supported NOS commands

| Containerlab kind | NOS SSH driver | Backup command |
|---|---|---|
| `juniper_cjunosevolved` | `junipernetworks.junos.junos` | `show configuration \| display set \| no-more` |
| `cisco_xrv9k` | `cisco.iosxr.iosxr` | `show running-config` |
| `arista_ceos` | `arista.eos.eos` | `show running-config` |

Kind groups or recognized ansible_network_os values identify the platform. An
optional `topology-data.json` upload supplies kind metadata when custom groups
omit it. Unmapped nodes can be classified in the UI. Other kinds remain disabled.
The application does not upload/run arbitrary Ansible playbooks, inventory scripts,
connection plugins, or shell arguments from the uploaded file. Those settings are
not necessary to retrieve configuration using the supported NOS adapters.

## Inventory handling

Accepts static YAML/JSON inventories with nested groups and host variables, plus
JSON in Ansible's dynamic-script output format as data. Output is always rebuilt
as a valid static inventory for the Ansible subprocess, avoiding the previous
script-JSON/static-file mismatch. Executable inventory scripts are not accepted.

Recognized input fields are ansible_host, ansible_port, ansible_user,
ansible_password (or ansible_ssh_pass), ansible_network_os, clab_kind, and ansible_become_password (EOS enable password). Kind group
names also identify platforms. A missing ansible_host falls back to the inventory
hostname, which must resolve from inside the worker.

The import is bounded to 1 MiB per inventory/topology file and 2000 hosts per lab.
YAML anchors, aliases, executable tags, and Jinja template expressions are rejected.
Conflicting inherited connection values across multiple groups are rejected for
review. Unsupported execution-related Ansible variables are ignored. Upload a
separate private key through Credentials instead of referencing a host key path.

Credential precedence: explicit node profile, then lab default for its NOS, then
credentials imported for that host. A profile with an empty password is allowed
for lab accounts configured that way. Imported username-only hosts require an
explicit profile. To rotate credentials, add a new profile and make it the NOS
default or assign it to nodes. Old profiles are retained in this initial release.

## Persistence and job behavior

Docker-managed volume `nos-backup-ui-data` is mounted at /data. The non-root image
initializes its ownership; no VM directory chmod/chown is required. The volume
contains:

- Encrypted application state: labs, normalized inventories, credential profiles,
  schedules, and job results.
- A locally generated state encryption key and UI access token.
- `/data/backups/<lab-id>/latest/`: latest successful configuration files and Git
  history for that lab.
- `/data/backups/<lab-id>/history/<job-id>/`: per-run configuration snapshots.

The key and encrypted state live on the same volume; encryption prevents accidental
plaintext state exposure but does not protect against someone who controls that
volume. The API never returns passwords, passphrases, or private keys. Configuration
archives may naturally contain NOS secrets and should be handled as device backups.
The token is held in browser session storage and submitted as a Bearer token.

One process manages jobs, with one active job and up to five concurrent SSH
sessions. Use exactly one Uvicorn worker and one container per data volume. There
is no shared-volume multi-instance coordination. Application restart marks any
unfinished job interrupted and retains earlier successful files. Schedules retry
when ready; a due schedule blocked by missing credentials or another job is checked
again after a minute. Inventory replacement disables a schedule if enabled nodes
are missing credentials.

Failed or empty retrievals do not overwrite a node's previous configuration.
Successful nodes in a partial job can still be archived and committed. Unchanged
configurations do not create additional Git commits. Removed/excluded nodes' old
latest files are retained. There is no automatic retention pruning in this version.
Downloads contain successful configurations from that job and a manifest of node
results, not a promise that all nodes succeeded. Internal storage filenames include a short hash to prevent collisions. Downloaded
filenames use the readable device/type/time naming described below.

The automated backup engine does not restore configurations, write startup
configuration, or back up qcow2 images. Interactive terminal users can run commands
permitted by their device account. SSH host-key verification is disabled for this initial ephemeral
lab workflow; controlled known_hosts management is not implemented in this release.
Private RSA, ECDSA and Ed25519 keys are accepted when readable by Paramiko.

Persistent named volumes remain on the Docker host. They survive container
replacement, not loss of the host disk or explicit volume deletion. Avoid
`docker compose down -v` when retaining settings and backups.

## Operational notes

- An operator still needs Docker permission to build/start the container. The
  running application requires no host file or Docker API permission.
- A running container is not proof its virtual NOS finished booting. Use the
  NOS login test once the lab has booted.
- Passwords and key passphrases are suppressed from job error text where known;
  raw device configuration is never printed by the worker callback.
- The UI refreshes task progress and action logs every four seconds. File results
  finalize after the Ansible pass finishes. There is no raw-terminal stream or
  cancellation control.
- Dependencies have version ranges. The built image records the installed packages
  at /opt/python-packages.txt and /opt/ansible-collections.txt. Keep a validated
  image digest for reproducible deployments.
- UI access token recovery: `docker compose logs backup-ui`. It is printed again
  on restart. Treat access to that log like access to this backup workspace.

## Local development and tests

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -v
```

The Ansible CLI must be available on PATH for backup execution. Install the
collections from collections.yml for live NOS runs. The tests use local simulated
NOS output for the callback/archive check, not a live network device.

## Sources

- [Containerlab-generated inventory and kind groups](https://containerlab.dev/manual/inventory/)
- [Ansible static inventory schema](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/yaml_inventory.html)
- [Ansible network_cli](https://docs.ansible.com/projects/ansible/latest/collections/ansible/netcommon/network_cli_connection.html)
- [Docker-managed volumes](https://docs.docker.com/engine/storage/volumes/)

## EOS fix and action logs (September 2026)

This update explicitly requests `ansible_become: true` and
`ansible_become_method: enable` for `arista_ceos`. The EOS terminal driver handles
both an initial `>` prompt and a session already at `#`. If your EOS account needs
an enable password, create an EOS credential profile with the optional **EOS enable
password** field and make it the default, or assign it to the switch. Leave this
field empty when enable does not require a password. It is separate from the SSH
login password. Existing profiles continue to work without migration.

Missing enable-mode handling was found in the original implementation. It is a
plausible failure path, not a confirmed diagnosis of your specific switch without
its failure output. Authentication, SSH reachability, terminal initialization,
image readiness, or command authorization failures now retain diagnostics.

The exact adapters are:

- `arista_ceos`: EOS network_cli with enable mode and driver-managed paging;
  `show running-config` retrieves the active configuration.
- `cisco_xrv9k`: IOS-XR network_cli to the NOS SSH endpoint (not the container's
  Linux shell); `show running-config`. XR configuration/timestamp headers are
  normalized. XRv9k can take a long time to finish booting.
- `juniper_cjunosevolved`: Junos network_cli, whose terminal plugin enters the
  Junos CLI from a `%` shell prompt and disables paging;
  `show configuration | display set | no-more`. This stores committed configuration
  as set commands, not uncommitted candidate changes.

Use the container management address and port 22, or a reachable host address and
its explicitly published NOS SSH port. The worker does not add port forwarding.
Custom startup configurations can change management reachability and credentials.

Open **Action logs**, or **Backup history → View action logs** for a selected job.
Logs show UTC timestamps, severity, node/job IDs, driver/endpoint/command selection,
Ansible task start/result, sanitized failure diagnostics, output validation,
configuration writes, Git commit/no-change/failure, job lifecycle, schedule deferral,
inventory changes, profile creation, node edits, and API action status. A task start
means SSH/terminal setup is beginning; success means the command returned. Individual
SSH packets, password exchanges, and raw configuration contents are not logged.

Filter by node, job, or severity. Choose **All worker actions** to see startup and
requests not associated with a lab. Download exports the currently displayed,
filtered events as JSON Lines (up to 1,000); the authenticated `/api/logs` endpoint
allows up to 2,000. The UI reports refresh failures instead of silently displaying
stale logs as current.

Operational logs persist at `/data/events.jsonl`, rotating at approximately 5 MiB
with three older files retained. This is separate from backup retention, which
remains unchanged. Logs contain metadata and sanitized diagnostics; known login,
enable, and key secrets are suppressed. Full SSH transcripts/configurations are
not intentionally included. Temporary Ansible output remains private to the job
and is removed afterward.

### Upgrade an existing installation

1. Replace the application source with this release. Preserve your current Compose
   environment and `/data` volume; do not delete the volume.
2. For a Compose deployment, rebuild and recreate the application:

   ```bash
   cd clab-backup-ui
   docker compose up -d --build
   ```

   For a worker managed by containerlab, rebuild its existing image tag:

   ```bash
   docker build -t clab-backup:1.6.1 -t clab-backup:webui ./clab-backup-ui
   ```

   Then recreate the worker container through your existing deployment procedure,
   preserving its `/data` mount. A container restart alone does not use a rebuilt
   image. Rebuilding the tag does not change running containers.

3. Refresh the browser. Add an EOS profile with an enable password only if required.
4. Run **Test NOS login**, then **Back up now**. Open the job's action logs and check
   the exported EOS configuration before re-enabling the schedule.
5. If EOS still fails, export its filtered job logs; the error should now distinguish
   driver/setup, SSH, privilege, command, and storage failure stages.

Official references:
- https://containerlab.dev/manual/kinds/ceos/
- https://containerlab.dev/manual/kinds/vr-xrv9k/
- https://containerlab.dev/manual/kinds/cjunosevolved/
- https://github.com/ansible-collections/arista.eos/blob/main/plugins/terminal/eos.py

## 1.2.0 — Individual downloads and readable names (retained in 1.6.1)

In **Backup history**, expand a completed job and click **Download config** beside
any successful device, or **Download all (ZIP)** for all successful configurations
in that job. Partial jobs support both options for the devices that succeeded.
Login tests and failed devices do not offer configuration downloads. Each successful
download request appears in Action logs, with the device name for individual files.

| Kind | Download filename example |
|---|---|
| `juniper_cjunosevolved` | `cjunosevo_GTW-2_2026-09-10_01-04UTC.cfg` |
| `cisco_xrv9k` | `IOS-XR_PE1_2026-09-10_01-04UTC.txt` |
| `arista_ceos` | `CEOS_IXP-L2-Switch_2026-09-10_01-04UTC.conf` |

ZIP name: `BGP_TheoryToPractice_2026-09-10_01-02.zip`.
The ZIP timestamp is the job's start time; each configuration timestamp is the
completion time of that device's retrieval. All times are UTC and are shown as UTC
in the UI. Filenames use minutes; downloading different runs from the same minute
can cause your browser to append a number locally. Renaming never changes the
configuration bytes: Junos still contains set commands, now delivered with `.cfg`.

The same config names appear in individual downloads, ZIP contents, and the ZIP's
manifest. Filenames use underscores instead of Windows-invalid `|` or `:` characters.
Unsafe characters are normalized. If names would collide within a job (including
Windows case-insensitive collisions), a numeric suffix is added to the device name.

For device names, the worker uses a saved short name from topology metadata or the
optional **Edit node → Download device name** field. Otherwise it removes the exact
`clab-<lab name>-` prefix, or uses the configured NOS hostname when it matches the
container name's suffix. It preserves an ambiguous full name instead of guessing
where a hyphenated lab name ends. Set Download device name to resolve that case.
The choice is frozen for each new backup.

Existing backups remain downloadable. On first startup, this release records naming
metadata for historical files using known file formats, identifiable NOS headers,
and existing inventory platform assignments. Historical timestamps use job finish
(start/create as fallback), because the prior version did not record per-device
capture times. The UI labels these as historical job timestamps. If no job time
exists, the stored file modification time is used. If the device type cannot be
recovered, it remains downloadable as `Device_<name>_<time>UTC.<original-extension>`
until its historical metadata can be identified; no type is guessed.

This upgrade updates metadata only; it does not rename or rewrite stored snapshots,
latest files, or Git history. Keeping internal filenames stable preserves unchanged
configuration detection. Later inventory edits do not change saved snapshot names.

### Build the versioned image

From the repository root:

```bash
docker build -t clab-backup:1.6.1 -t clab-backup:webui ./clab-backup-ui
```

For containerlab, set the worker image to `clab-backup:1.6.1`, then recreate the
worker using your deployment procedure while preserving its existing `/data` mount.
For Compose, run `docker compose up -d --build` from `clab-backup-ui`; Compose now
uses `clab-backup:1.6.1`. Refresh the browser after recreating the worker. The footer
and `/api/state` report `1.6.1`, and the image carries the OCI version label.

Extra validation commands, from `clab-backup-ui`:

```bash
python -m unittest discover -s tests -v
node --test tests/test_download_ui.js
```

Topology maps and SuperPuTTY session export are available in 1.6.1. See NODE-FEATURES.md in the application directory for inputs, mapping, export credentials, and compatibility limits.
