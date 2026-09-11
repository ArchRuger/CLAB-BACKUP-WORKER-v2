# Containerlab Node Manager — 1.12.0

A persistent workspace for network engineers using containerlab. Run one manager
per Linux VM as an independent Docker Compose service. Import lab definitions,
discover deployed labs over SSH, open node terminals, and retain configuration
backups as training labs are replaced.

**Already pulled the Docker image?** Follow [Docker Hub setup](../DOCKER-HUB-SETUP.md).
It covers host prerequisites, matching helper installation, persistent storage,
image-only Compose launch, VM connection, first import, everyday use and upgrades.
Use [deploy/compose.image.yml](../deploy/compose.image.yml) for this path; it has no build step.

**Building from source?** Follow the [Fresh VM installation guide](../FRESH-VM-GUIDE.md).
For an existing installation, see [VM connection and recovery](../VM-CONNECTION.md)
and [migration instructions](../STANDALONE-SETUP.md).

## Changes in 1.14.0

VM connections now use a user-created password. First host setup prompts securely
for the clab-discovery account password before launching the manager. Enter that
same password in VM connection; it is encrypted in persistent storage. Routine
upgrades retain it, and --reset-password supports recovery. SSH restrictions now
apply to the account independently of client keys. Existing key connections require
one-time migration; device credential options remain unchanged.

## Changes in 1.12.0

The workspace opens directly without an access-token login. VM and device SSH
credentials remain encrypted in persistent storage. Keep VM connection enabled
for discovery, automatic file import and reviewed lab commands.

- Retained: lifecycle commands, inspect/save, SSH all, favorites, VM projects,
  new project creation, optional repository downloads, backup history and SuperPuTTY.
- Removed: existing VM YAML editing, lab path/link/folder shortcuts, separate
  layout control, SSHX/GoTTY and fcli. VM project files open read-only.
- One interactive draw.io editor with full editable export: nodes, connections,
  interface labels, groups, notes, colors and positions. No online service needed.
- Inspect results appear as a table. VM projects use an expandable vertical tree.
- Topology header offers SSH all and Back up all configs, including expanded view.
- Right-click an excluded lab to clear its exclusion without importing it.
- Manager settings → Start fresh clears manager data and backup files after
  confirmation, retaining the VM connection and leaving VM labs/files untouched.

[VM connection setup and troubleshooting](../VM-CONNECTION.md) covers passwords, permissions,
helper repair and upgrades. [Lab commands](../LAB-OPERATIONS.md) documents retained actions.

## Setup and import improvements retained from 1.10.0

- **Source-build launch command:** `sudo bash deploy/start-manager.sh` updates the installed
  VM helper, verifies its file-transfer protocol and version, prepares storage,
  builds the image and recreates the Compose service. Existing passwords/data are retained.
  First setup prompts for the discovery account password. An old helper cannot silently
  survive a normal upgrade; verification failures stop before container recreation.
- **Import confirmation:** discovery reads files automatically and shows new labs as
  Ready to import. Clicking a lab previews its name, node/link counts, source files
  and warnings. Only **Import lab** saves the workspace and inventory credentials.
  Cancel saves no workspace. Import again also requires confirmation and retains
  the exclusion if cancelled. Existing saved workspaces remain available.
- Confirmation expires after five minutes and is rejected if files, VM connection or
  exclusion state change. Refreshes and older API clients cannot bypass confirmation.
- Outdated inspection-only helpers now show an actionable message in VM connection
  and the sidebar instead of appearing ready for automatic file import.

## Existing features

- **Remove lab** clears only that saved manager workspace and its history entries.
  It never stops containers or changes VM lab files. Backup files and audit logs
  remain on disk; other labs and the VM connection are retained.
- Removed labs are excluded from automatic import by default. Use **Import again**
  in the sidebar, or uncheck the exclusion in the removal dialog to test automatic
  discovery on its next check. Queued/running jobs must finish before removal.

- Automatic retrieval of deployed lab YAML, annotations, generated inventory and topology data, followed by import confirmation.
- File change detection and **Sync from VM**, preserving saved node settings, profiles and backup history.
- Helper upgrade with `deploy/setup-discovery.sh --update-helper` retains the password after first migration.
- Standalone Compose deployment with Linux host networking and automatic restart.
- Host directory `/srv/containerlab-node-manager/data` mounted at `/data`, using
  explicit UID/GID 10001 and a one-time setup script.
- Original `.clab.yaml` registration, optional annotation maps, and updates that
  preserve matching node identities, credentials, schedules and configuration history.
- Encrypted VM password settings, fixed read-only SSH discovery every 30 seconds,
  manual refresh, stored SSH fingerprint and changed-key rejection.
- Running, Partially running, Stopped, Not deployed, Unknown and Unlinked lab states.
- Automatic node management addresses with explicit manual endpoint overrides.
- Deployment-aware scheduling for linked labs; offline/unknown labs retain their
  data and wait until they are available. Existing inventory-only behavior remains.

The list and map both retain node details, per-node backups and browser SSH tabs.
SuperPuTTY XML exports use the lab name. Junos, IOS-XR and EOS backup adapters and
historical downloads remain. Host CPU/memory monitoring is not part of this release.

## Build from source or migrate

Read [Standalone setup and migration](../STANDALONE-SETUP.md) first. Existing workers
may contain all their data inside the container; copy it before removing them.
Remove the old Backup-Worker entry from training lab YAML once migration is verified.

After installing Docker, containerlab and SSH as described in the guide, run from
the repository root on the Linux VM. For first setup, create your password when prompted:

```bash
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
```

For upgrades with the existing discovery account/password:

```bash
cd ~/projects/v1.15.0
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
```

The script installs/updates and verifies the helper before starting the manager.
Keep your existing `.env` or custom UI port settings when changing source folders.
A manager launched with `docker run` must follow the migration guide first; the
script refuses to start a second manager against its active data directory.
Image-only `docker build` remains available but cannot update host-installed files.

Open `http://VM_ADDRESS:8081`, configure
**VM connection**. The guide includes the restricted discovery account setup and
existing-data migration. New deployed labs appear as Ready to import; review and confirm to save them. Existing workspaces offer Sync from VM;
manual YAML/annotation/inventory uploads remain available. Running container status does not prove NOS login/boot readiness.

The manager requires no Docker socket. Host networking provides reachability;
host SSH provides fixed discovery and explicitly enabled lab operations. Imported YAML
is stored as encrypted data. Deployment uses the reviewed original VM project
through the privileged host helper; treat project files and manager users as trusted.
Exactly one manager process/container may use a given data directory.

## Development

From `clab-backup-ui`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -v
node --test tests/test_download_ui.js tests/test_topology_ui.js
```

See [validation](VALIDATION.md) for actual test evidence and deployment
limits, and [node features](NODE-FEATURES.md) for SSH, backup, map and
export behavior. Source packages and patches are prepared locally; a package does
not imply that GitHub was updated or an image was built/deployed.
