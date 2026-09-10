# Containerlab Node Manager — 1.9.1

A persistent workspace for network engineers using containerlab. Run one manager
per Linux VM as an independent Docker Compose service. Import lab definitions,
discover deployed labs over SSH, open node terminals, and retain configuration
backups as training labs are replaced.

**Start here:** [Fresh VM installation guide](FRESH-VM-GUIDE.md) — Ubuntu, Docker, containerlab,
persistent storage, SSH keys, first launch, automatic imports, upgrades and backups.

## What changed in 1.9.1

- Discovery follows the original YAML path from `containerlab inspect`, then checks
  the adjacent `clab-<lab-name>` directory for generated inventory and topology data.
  Missing Docker labels no longer prevent file import; verified labels still locate
  custom generated directories.
- Clicking a detected lab tries VM import before showing manual uploads. The general
  import dialog also offers a VM retry for an unimported detected lab.
- **Discovery file details** lists attempted paths and per-file results, including
  missing files and permission failures.
- Direct inspection now reads the same files through SFTP using the existing SSH
  account. The restricted helper remains preferred for root-owned files.
- Update the installed helper with `sudo bash deploy/setup-discovery.sh --update-helper`
  when upgrading from 1.9.0 or earlier. This retains the installed SSH key.

## Existing features

- **Remove lab** clears only that saved manager workspace and its history entries.
  It never stops containers or changes VM lab files. Backup files and audit logs
  remain on disk; other labs and the VM connection are retained.
- Removed labs are excluded from automatic import by default. Use **Import again**
  in the sidebar, or uncheck the exclusion in the removal dialog to test automatic
  discovery on its next check. Queued/running jobs must finish before removal.

- Automatic imports of deployed lab YAML, annotations, generated inventory and topology data through the restricted VM helper.
- File change detection and **Sync from VM**, preserving saved node settings, profiles and backup history.
- Helper upgrade with `deploy/setup-discovery.sh --update-helper` retains the existing SSH key.
- Standalone Compose deployment with Linux host networking and automatic restart.
- Host directory `/srv/containerlab-node-manager/data` mounted at `/data`, using
  explicit UID/GID 10001 and a one-time setup script.
- Original `.clab.yaml` registration, optional annotation maps, and updates that
  preserve matching node identities, credentials, schedules and configuration history.
- Encrypted VM password/key settings, fixed read-only SSH discovery every 30 seconds,
  manual refresh, stored SSH fingerprint and changed-key rejection.
- Running, Partially running, Stopped, Not deployed, Unknown and Unlinked lab states.
- Automatic node management addresses with explicit manual endpoint overrides.
- Deployment-aware scheduling for linked labs; offline/unknown labs retain their
  data and wait until they are available. Existing inventory-only behavior remains.

The list and map both retain node details, per-node backups and browser SSH tabs.
SuperPuTTY XML exports use the lab name. Junos, IOS-XR and EOS backup adapters and
historical downloads remain. Host CPU/memory monitoring is not part of this release.

## Install or migrate

Read [Standalone setup and migration](STANDALONE-SETUP.md) first. Existing workers
may contain all their data inside the container; copy it before removing them.
Remove the old Backup-Worker entry from training lab YAML once migration is verified.

For a fresh installation, from this repository root on the Linux VM:

```bash
sudo bash deploy/setup-vm.sh
sudo docker compose -f clab-backup-ui/compose.yml build --pull --no-cache
sudo docker compose -f clab-backup-ui/compose.yml up -d
sudo docker compose -f clab-backup-ui/compose.yml logs backup-ui
```

Open `http://VM_ADDRESS:8081`, enter the token printed in the logs, and configure
**VM connection**. The guide includes the restricted discovery account setup and
existing-data migration. New deployed labs import automatically. Existing workspaces offer Sync from VM;
manual YAML/annotation/inventory uploads remain available. Running container status does not prove NOS login/boot readiness.

The manager requires no Docker socket. Host networking provides reachability;
host SSH provides fixed inspection and bounded reads of deployment files. Uploaded lab YAML is
stored as encrypted data and never executed or deployed by this application.
Exactly one manager process/container may use a given data directory.

## Development

From `clab-backup-ui`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -v
node --test tests/test_download_ui.js tests/test_topology_ui.js
```

See [validation](clab-backup-ui/VALIDATION.md) for actual test evidence and deployment
limits, and [node features](clab-backup-ui/NODE-FEATURES.md) for SSH, backup, map and
export behavior. Source packages and patches are prepared locally; a package does
not imply that GitHub was updated or an image was built/deployed.
