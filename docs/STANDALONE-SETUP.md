# Manual setup and migration

The guided installer (`bash "$HOME/projects/clab-manager/deploy/install.sh"`, see
[INSTALL.md](INSTALL.md)) runs everything on this page for you. Read it when you
want the pieces one by one on an already prepared Linux host, when you are moving
data out of the older in-lab worker container, or when you want to launch a
prebuilt image instead of building one. Every command works from any directory;
the source folder is `~/projects/clab-manager`.

Run one manager per engineer's Linux VM. It is a separate Docker Compose service,
outside every containerlab topology. Lab deployment/destruction does not manage
its lifecycle. The manager uses host networking for reachability and SSH for a
fixed discovery and explicitly enabled privileged lab commands. It does not mount
the Docker socket. See [LAB-OPERATIONS.md](LAB-OPERATIONS.md) to enable commands
and configure trusted project roots while retaining the current password.

For Git publishing, use the VM account you already have. Once the manager and a
device backup work, run `bash "$HOME/projects/clab-manager/deploy/setup-git.sh"`
without sudo. Follow [GIT-SETUP.md](GIT-SETUP.md); no additional Linux user is needed.

## 1. Prepare permanent storage

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-vm.sh"
```

This creates `/srv/containerlab-node-manager/data`, owned by UID/GID 10001 with
mode 0700. The image explicitly uses UID/GID 10001. The Compose bind mount maps
this directory to `/data` and refuses to create a missing host directory silently.
These instructions target normal rootful Docker Engine on Linux; rootless Docker
or user-namespace remapping needs the equivalent mapped host ownership.

The directory contains encrypted state (`state.enc`), its encryption key
(`state.key`), action logs and `backups/`.
Imported lab YAML and host/device credentials are kept in encrypted state. API
state responses exclude raw YAML and credentials. The VM project file viewer
can explicitly read original source files within trusted project roots.
The key lives beside the encrypted state, so access to this directory permits
recovery of secrets. Keep the directory private and back it up as a unit.

## 2. Migrate an existing worker, if present

Do this **before starting the new manager**, while the destination is empty.
For the previously supplied BGP lab:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/migrate-worker-data.sh" clab-BGP_TheoryToPractice-Backup-Worker
```

Use your actual old container name. The script stops only that container, copies
all of `/data` including hidden files and keys, checks the required state/key,
sets ownership, and retains a recovery copy outside generated lab folders.
It refuses to overwrite a nonempty destination. On copy/validation failure it
restarts the old worker if it was running. A successful migration leaves the old
worker stopped; do not run two managers against the same data directory.

The previous YAML had no persistent data mount, so removing that worker before
copying its data would lose its saved work. An existing named-volume deployment
can also be migrated using this script with its old container name.

After verifying the new manager and history:

1. Remove the `Backup-Worker` node from each training lab's YAML so it is not
   recreated with the lab. Preserve your network nodes and their configuration.
2. Remove the stopped old worker container when ready, for example:
   `docker rm clab-BGP_TheoryToPractice-Backup-Worker`.
3. In the saved workspace, use **Advanced › Deployment details › Update topology file…** with the edited topology.
   This removes the old worker from the saved node list while retaining history.

Old inventory-only workspaces remain usable with their manual addresses and
existing schedules. Link/update them to enable deployment-aware scheduling;
set their schedules to manual during the transition if you do not want them
running before discovery is configured. No migration automatically resets schedules.

## 3. Build and start the independent manager

After configuring the discovery account in section 4, run the launcher. It also
installs the browser Wireshark stack and the Grafana dashboards (skip them with
`--manager-only`):

```bash
sudo bash "$HOME/projects/clab-manager/deploy/start-manager.sh"
sudo docker compose -f "$HOME/projects/clab-manager/clab-backup-ui/compose.yml" exec backup-ui \
  python -c "from app import __version__; print(__version__)"
sudo docker compose -f "$HOME/projects/clab-manager/clab-backup-ui/compose.yml" logs backup-ui
```

Expect the release in `clab-backup-ui/VERSION`. Open `http://VM_ADDRESS:8081`; no UI
login is required. See [VM connection setup and troubleshooting](VM-CONNECTION.md).
Docker must start at VM boot; `restart: unless-stopped` restarts the manager with
Docker unless you explicitly stopped it.

Equivalent image-only build, tagged with the release:

```bash
sudo docker build --pull --no-cache -t "clab-backup:$(cat "$HOME/projects/clab-manager/clab-backup-ui/VERSION")" "$HOME/projects/clab-manager/clab-backup-ui"
```

The final path is the required build context. Builds require the base image and
Debian/Python/Ansible dependencies or internal mirrors. In an airgapped environment,
build on a connected build host, then transfer the image with `docker save`/`docker load`.
After loading it, launch it with `deploy/compose.image.yml` as described in the
[master guide's airgapped section](WIKI-MASTER-GUIDE.md#part-20).

Host networking shares the VM's network namespace. The UI binds directly to port
8081, and the manager can reach node addresses that are reachable from the VM.
There is no `ports:` mapping and no dependency on a lab Docker network's lifecycle.
If needed, set `UI_BIND`/`UI_PORT` in `clab-backup-ui/.env` before the launcher runs (`sudo` does not pass shell variables on, and the Grafana setup reads `UI_PORT` from that file). Do not run
another application on the same listening address/port. Node routing, firewall and
SSH readiness still apply; deployment status is not proof of a successful NOS login.

## 4. Install the restricted discovery account

On the VM, in an interactive administrator terminal, create the account password:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-discovery.sh"
```

Setup prompts twice without echo. The Linux account hash persists in /etc/shadow;
the manager saves an encrypted copy of the entered password in its persistent data.
The gateway restricts SSH to discovery and approved operations. See
[VM connection setup and recovery](VM-CONNECTION.md) for migration and password reset.

The helper accepts no caller arguments. It inspects deployments using:

```bash
containerlab inspect --all --format json
```

It also reads Docker container labels using fixed `docker inspect` arguments and reads
only the original YAML, adjacent annotations, generated inventory and topology export.
It uses fixed binaries, a clean environment, and `/` as its working directory.
The application cannot submit arbitrary shell commands through discovery.

In **VM connection**:

- VM address: `127.0.0.1` (the manager shares this VM's networking).
- SSH port: the VM's SSH port, normally 22.
- VM username: `clab-discovery`.
- VM password: the password created during host setup.
- Inspection method: **Installed discovery and file helper**.
- Save and test connection.

The first successful SSH connection trusts and stores the VM fingerprint. Later
changes block discovery. Verify an unexpected change before using the explicit
replacement-key checkbox. Reopen VM connection to see the saved fingerprint.

Alternatively, an existing VM account can use password authentication with
**Direct inspection + SFTP (existing VM account)** if it already has permission
to inspect Docker without an interactive sudo prompt and read the deployment
files through SFTP. Direct mode does not elevate file-read permissions. The dedicated helper is preferred.
Host credentials and NOS credentials are separate.

## 5. Register and use persistent labs

Use **Remove from this manager…** (**Lab actions ▾** or **Advanced › Danger zone**) to
remove only a saved manager workspace, credentials, schedule and history entries.
Backup files and audit logs stay on disk. No running container or VM lab file is
modified. The default exclusion prevents automatic reimport; use **Stop hiding**
under **Manager ▾ › Labs found on the VM…** later, or uncheck the exclusion when
removing if you want to test immediate rediscovery. Both paths require confirmation
before a new workspace is saved; cancelling the import retains its exclusion. Other
labs and the VM connection remain.


The installed helper reads deployed lab files automatically. New labs wait for
confirmation: under **Manager ▾ › Labs found on the VM…** click the lab (*Ready to import*), review files, and choose **Add lab** or **Cancel**. Existing
workspaces show Updates available and offer **Sync topology from VM**, preserving matching
node settings, credentials, profiles, schedules and history. Missing files never
delete a saved workspace. Optional files must be valid and match the YAML; invalid
files block sync without partial changes. A missing annotation retains an existing
map. Original YAML is required. New labs can import the YAML while reporting an
invalid optional file; credentials from a mismatched inventory are skipped.
Old inspection-only helpers discover nodes only; the launcher installs the matching
helper. The standard generated folder beside the YAML is tried even without Docker
labels. **File check details** in that dialog shows paths and results; clicking a detected lab
retries automatic import before offering manual upload.

Normal setup/upgrades use the installer or the launcher, which update and verify
the helper before building/recreating the manager. They preserve existing
passwords/data. First launch prompts for a password when needed.
For a helper-only repair (including password migration when needed):

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-discovery.sh" --update-helper
```

See the [master guide](WIKI-MASTER-GUIDE.md) for file locations, limits,
Docker-run-to-Compose upgrades and troubleshooting. Manual import remains available:


Choose **Manager ▾ › Import lab files…** and upload the original `.clab.yaml`. Optionally include
its `.annotations.json`. The YAML supplies the lab name, node identities/kinds,
prefix and links; annotations supply layout and styling. The importer handles
literal node/default/kind settings and both normal and empty container prefixes.
It does not execute YAML, deployment commands, startup configuration or bindings.
YAML anchors and unresolved variable-based identity/address fields are rejected;
provide a resolved literal definition for those topologies.

Set **Lab name on the VM** when containerlab was launched with a name override.
An existing workspace can use **Link to a running lab…** (**Advanced › Deployment details**) without replacing its inventory.
Only one saved workspace can be linked to each deployment name on this VM.
Reimporting that definition updates its workspace instead of making a duplicate.
A unique unlinked legacy workspace with the same lab name is reused; ambiguous
matches require opening the intended workspace and using **Update topology file…**.

The manager polls every 30 seconds and also offers **Manager ▾ › Refresh lab list**:

| State | Meaning |
|---|---|
| Running | All saved nodes matched running containers and all discovered containers are running |
| Partially running | Some containers are running, but the deployment does not fully match a running saved lab |
| Stopped | Matching containers exist but none are running |
| Not deployed | A successful inspection found no containers for this lab |
| Unknown | No fresh successful inspection; includes disabled/unreachable discovery |
| Unlinked | Legacy inventory workspace not associated with deployment discovery |

Snapshots expire after 90 seconds and are invalidated on manager restart. Failure
retains saved labs, configuration history and last successful inspection time.
Discovered but unregistered labs offer a setup button. Multiple labs can be active.
The UI does not forcibly switch the workspace you are viewing as labs change.

New YAML nodes use automatic management addresses (SSH port 22). **Edit connection**
can pin a manual IP/hostname and port, including a published NOS SSH port. Inventory
imports and existing legacy endpoints stay manual. Automatic addresses refresh after
redeployment; explicit manual endpoints do not. Host network mode handles the same
standard Docker bridge reachability as the VM; unusual macvlan/remote networks
still require host routing or reachable published SSH endpoints.

For linked labs, scheduled backups pause unless discovery is fresh and the entire
lab is Running. The interval is retained and the schedule retries automatically.
Manual node actions require a currently discovered running node; unknown/missing
nodes cannot accidentally use stale automatic addresses. Credentials and NOS boot
readiness are additional requirements. Other running nodes in a partial lab can
still be accessed individually. Legacy unlinked inventory behavior is retained.

## Backup, restore, and updates

For a consistent full backup, briefly stop the manager (lab nodes keep running):

```bash
sudo docker compose -f "$HOME/projects/clab-manager/clab-backup-ui/compose.yml" stop backup-ui
sudo tar -C /srv/containerlab-node-manager -czf \
  /root/node-manager-data-$(date +%Y%m%d-%H%M%S).tgz data
sudo docker compose -f "$HOME/projects/clab-manager/clab-backup-ui/compose.yml" start backup-ui
```

Restore into an empty data directory with the manager stopped. Restore the complete
`data/` tree, including `state.key`; set ownership to UID/GID 10001 and keep the
directory mode 0700. Start one manager and verify its labs/history. Persistence
survives container changes, not destruction of the VM disk without a backup.

To update the manager, retain the same host directory and run the installer or the
launcher again; for a prebuilt image, load it and recreate the container with the
image Compose file. Stop or remove the old lab worker first to avoid duplicate
schedules or a port conflict. Imported workspaces and backups remain. No router
configuration is automatically restored by this feature.

For golden VM templates, provision the empty directory and software, then initialize
each engineer's manager and VM password separately. Cloning initialized data also clones
its credentials and encryption key.

References: [Docker host networking](https://docs.docker.com/engine/network/drivers/host/),
[bind mounts](https://docs.docker.com/engine/storage/bind-mounts/),
[containerlab inspect](https://containerlab.dev/cmd/inspect/).
