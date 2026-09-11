# Containerlab Node Manager 1.15.2 — a fresh VM to a working lab

> This 1.15.2 source release requires building the new image. Previously published
> images do not contain this release's Git progress workflow.

If package setup fails with `file:/cdrom ... Release`, follow
[package installation recovery](GIT-SETUP.md#package-installation-recovery) to
disable the obsolete installer source, then rerun the failed package command.


This guide starts with a fresh **Ubuntu Server 24.04 LTS VM**, a normal user with
`sudo` access, and an internet connection for installation. Run one manager per
engineer's VM. Allow enough CPU, RAM, disk and virtualization support for your
chosen network images; those requirements come from the lab devices.

Commands marked **VM** run in the VM's terminal. **Workstation** means the computer
where you open the manager in a browser. Replace `YOUR_VM_USER` and `VM_IP` with
your VM login and address. Do not type those placeholders literally.

The manager runs independently of containerlab, listens on TCP **8081**, and saves
its data under `/srv/containerlab-node-manager/data`. You do not add the manager
to a lab YAML or recreate it when switching labs.

## 1. Install the basic tools and clone the repository

**VM:**

```bash
sudo apt update
sudo apt install -y ca-certificates curl git openssh-server python3 sudo
sudo systemctl enable --now ssh
mkdir -p "$HOME/projects"
cd "$HOME/projects"
git clone https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2.git v1.15.2
cd v1.15.2
cat clab-backup-ui/VERSION
```

This guide requires **1.15.2** source, including `clab-backup-ui/app/host_files.py`.
If the clone reports an older version, obtain the 1.15.2 source package or the
matching release commit before proceeding. Local source delivery does not mean
the GitHub repository has already been updated. For a delivered ZIP, extract it
and place its contents in `~/projects/v1.15.2` so that `clab-backup-ui/` and
`deploy/` are directly inside that folder. This is the version-folder convention
used throughout this guide.
All later relative paths start at the directory containing `deploy/` and
`clab-backup-ui/`.

## 2. Install Docker Engine and Compose

**VM:** these commands use Docker's official Ubuntu APT repository. They assume
the fresh VM has no previous Docker installation. If it does, follow the
[official Docker installation instructions](https://docs.docker.com/engine/install/ubuntu/)
to resolve conflicting packages first.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

This guide uses `sudo docker` consistently; adding your user to the Docker group
is unnecessary. Use normal rootful Docker Engine; rootless Docker or user
namespace remapping requires different persistent-directory ownership.

## 3. Install containerlab on the VM

**VM:** download the official installer, inspect it with `less` (press `q` to exit),
then run it. These commands do not deploy a lab.

```bash
curl -fsSL https://get.containerlab.dev -o /tmp/install-containerlab.sh
less /tmp/install-containerlab.sh
sudo bash /tmp/install-containerlab.sh
containerlab version
sudo containerlab inspect --all --format json
```

An empty inspection is expected before deploying any labs. Containerlab must be
installed as a root-owned executable in `/usr/bin` or `/usr/local/bin`. The
helper setup checks this. See [Containerlab installation](https://containerlab.dev/install/)
for other distributions or offline packages.

## 4. Prepare persistent storage

**VM, repository root:**

```bash
sudo bash deploy/setup-vm.sh
sudo stat -c '%u:%g %a %n' /srv/containerlab-node-manager/data
```

Expected ownership/mode: `10001:10001 700`. The image runs with this UID/GID, and
Compose mounts this directory at `/data`. You do not need `chmod 777`, matching
host usernames, or per-lab permission changes. Compose refuses to silently create
a missing directory with the wrong ownership.

Persistent contents include imported labs and maps, VM/device credentials,
credential profiles, schedules, backup history/files, action logs. State and credentials are encrypted in `state.enc`; **retain
`state.key` alongside it**. Configuration backup files are separate files under
`backups/`. Copy the entire data directory when backing up or moving the manager.

If this is actually an upgrade from a worker that kept data inside its container,
stop here and follow [the migration procedure](STANDALONE-SETUP.md#2-migrate-an-existing-worker-if-present)
before starting the new manager. A genuinely fresh VM has nothing to migrate.

## 5. Create the restricted VM account password

**VM, repository root, interactive terminal:**

```bash
sudo bash deploy/setup-discovery.sh
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Setup creates clab-discovery and prompts twice for your chosen password with hidden
input. It installs the restricted SSH gateway and stores the account's password hash
in /etc/shadow. Enter this same password in VM connection after launch. No client
key generation, transfer or upload is needed. The SSH host fingerprint still identifies
the VM. The account is not added to the Docker group; it has no interactive SSH shell,
PTY or forwarding access. The manager container needs no Docker socket.

It reads deployment state and **only** these files from verified metadata:

| File | Location and purpose |
|---|---|
| Original YAML | Exact topology path reported by containerlab; node names/kinds and wiring |
| `<original-yaml-filename>.annotations.json` | Beside the original YAML; VS Code layout, groups and notes |
| `ansible-inventory.yml` | Generated lab directory; connection data and available device credentials |
| `topology-data.json` | Generated lab directory; exported node identities/kinds |

The generated directory normally sits beside the YAML as `clab-<lab-name>`.
Verified container labels can identify custom lab directories; absent labels
do not prevent the standard lookup. There is no recursive disk search. Files must be regular files with
no symlink components, at most 1 MiB each. The helper caps file content at 8 MiB
per inspection and examines at most 100 labs. This discovery helper never executes YAML, Ansible
inventory scripts, deploy/destroy commands, or device configuration commands.
Some nonstandard or unresolved template-based definitions need manual import.

## 6. Build a fresh image and launch the manager

First run `python3 deploy/verify-release.py` from the repository root. The launcher
also checks that VERSION, app, helpers and image metadata match before changing
the host. If the source reports 1.15.0 but helpers report 1.15.1, follow the
[repair for the affected GitHub checkout](REPOSITORY-MAINTENANCE.md#repair-the-affected-fresh-vm).

**VM, repository root:**

```bash
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
sudo docker compose -f clab-backup-ui/compose.yml exec backup-ui \
  python -c 'from app import __version__; print(__version__)'
sudo docker compose -f clab-backup-ui/compose.yml logs --tail=30 backup-ui
```

The launch script refreshes the helper and validates its version before building
and recreating the manager. If step 5 was skipped, it prompts for the password here.
An existing password is retained. --enable-operations adds reviewed lab commands.
Only trusted VM
projects under approved roots can be managed. Read [LAB-OPERATIONS.md](LAB-OPERATIONS.md)
for command coverage, optional downloads and recovery. Without this flag,
a fresh setup provides discovery/import only. Already enabled helpers are upgraded
automatically on subsequent launches.

Expect **1.15.2**. Open **`http://VM_IP:8081`** on your workstation. There is no
UI access-token login. VM connection and device SSH authentication are separate.
See [VM connection setup and recovery](VM-CONNECTION.md) for detailed help.


Compose uses **Linux host networking**. The UI listens directly on the VM's port
8081; do not add `-p` or `ports:`. Device SSH uses the reachable management
addresses on the VM. The browser does not need direct routing to those addresses.
Ensure your VM network permits workstation-to-VM TCP 8081 and SSH TCP 22. For NAT
VM networking, configure those two forwards in your hypervisor, or use a reachable
bridged VM address. `127.0.0.1` in your workstation browser means your workstation,
not the VM.

If UFW is already enabled, allow access from your actual workstation IP (replace
`WORKSTATION_IP`):

```bash
sudo ufw status
sudo ufw allow from WORKSTATION_IP to any port 8081 proto tcp
sudo ufw allow from WORKSTATION_IP to any port 22 proto tcp
```

If port 8081 is occupied, for example use 8082 consistently for Compose commands:

```bash
sudo env UI_PORT=8082 docker compose -f clab-backup-ui/compose.yml up -d
```

To remember this choice, put `UI_PORT=8082` in `clab-backup-ui/.env`. Open port 8082
and use it in the browser. Default access is HTTP for the isolated lab network.

An equivalent **image-only build** from the repository root is:

```bash
sudo docker build --pull --no-cache -t clab-backup:1.15.2 ./clab-backup-ui
```

If already inside `clab-backup-ui`, use `.` as the last argument instead. That
last argument is required: it is the Docker build context. Compose above handles
both the correct context and persistent launch settings for you.

## 7. Connect the manager to this VM

In the UI, open **VM connection** and enter:

| Setting | Value |
|---|---|
| VM address | `127.0.0.1` because the container shares this VM's network |
| SSH port | `22`, or the actual port configured for the VM SSH service |
| VM username | `clab-discovery` |
| VM password | The password you created for clab-discovery |
| Inspection method | Installed discovery and file helper |
| Automatic discovery | Enabled |

Click **Save and test connection**. The UI should report that the VM is connected.
The first successful connection trusts and saves its SSH fingerprint. Reopen the
dialog to compare it to the host key fingerprint from step 5 (the negotiated key
may instead be RSA/ECDSA; inspect that corresponding host public key). Later
unexpected fingerprint changes block discovery until you verify/reset it.

These credentials access the VM helper. Device SSH/backup credentials are separate;
they come from generated inventory when available or from your saved profiles.
Leaving credential fields blank when saving the same VM account retains its password.

## 8. Deploy a lab and let it appear automatically

Store your labs in a lasting directory, for example `~/labs`. Keep each original
YAML and its VS Code annotations together. The manager must be absent from those
topologies. Deploy your intended lab using its required network images:

```bash
sudo containerlab deploy -t /absolute/path/to/your-lab.clab.yaml
```

For an optional, small **discovery smoke test** without network-vendor images,
create two Linux containers:

```bash
mkdir -p "$HOME/labs/manager-smoke"
cat > "$HOME/labs/manager-smoke/manager-smoke.clab.yaml" <<'YAML'
name: manager-smoke
topology:
  nodes:
    host1:
      kind: linux
      image: alpine:3
      cmd: sleep infinity
    host2:
      kind: linux
      image: alpine:3
      cmd: sleep infinity
  links:
    - endpoints: ["host1:eth1", "host2:eth1"]
YAML
sudo containerlab deploy -t "$HOME/labs/manager-smoke/manager-smoke.clab.yaml"
```

The manager uses JSON output from `containerlab inspect --all --format json`,
which contains the same topology path shown in the table. It reads these four
files without shell navigation or uploading them manually:

| File | Lookup |
|---|---|
| Original lab YAML | Absolute `absLabPath` from inspect, or an absolute `labPath` |
| Annotations | `<original-yaml-path>.annotations.json` |
| Inventory | `<yaml-directory>/clab-<lab-name>/ansible-inventory.yml` |
| Topology export | `<yaml-directory>/clab-<lab-name>/topology-data.json` |

Verified Docker labels can supply a custom generated directory; missing labels
fall back to the standard folder. `authorized_keys`, node filesystem directories
and Nornir inventory are not read. Only supported lab data is saved in encrypted
manager state; this is not a mirror of the whole deployment directory.

For example, a topology at `/etc/containerlab/BGP_TheoryToPractice/BGP_TheoryToPractice.clab.yaml`
leads to generated files under `/etc/containerlab/BGP_TheoryToPractice/clab-BGP_TheoryToPractice/`.

If a detected lab has not imported, click its sidebar entry to retry automatically.
A successful read opens the import confirmation. Only after a failed attempt does
the manual upload form open, with a retry button.
Expand **Discovery file details** to see found, missing or permission-denied paths.
The general **Import a lab** dialog also offers automatic import when an unimported
lab has been detected. Never-deployed labs can still be uploaded manually.

Within approximately 30 seconds, or after **Refresh discovery**:

1. The detected lab appears as **Ready to import** without uploading files.
2. Click it to preview the lab name, node/link counts, source paths and warnings.
   Choose **Import lab** to save the workspace and credentials, or **Cancel** to
   leave it unsaved. Discovery keeps running while confirmation is pending.
3. After confirmation, the list shows addresses/status and Topology shows the
   annotation layout if available, otherwise a simple generated map.
4. The list and map retain node actions; right-click a map node for SSH, backup
   and details. Unsupported device kinds have no NOS backup adapter.

The Alpine smoke test has **no SSH server or NOS backup support**; use it to check
discovery, persistence and wiring only. With Junos, IOS-XR or EOS devices, check
the imported credentials or assign a profile, wait for the NOS to finish booting,
then use **Test NOS login**, SSH and a single-node backup. A Running container
does not establish that its NOS is ready. Your licensed vendor images and their
requirements are separate from the manager installation.

## 9. Change files, switch labs, and keep your work

- **New deployment:** files are retrieved automatically, then the lab waits for
  confirmation. Schedules start in Manual when imported. Nothing automatically
  backs up or changes the devices. Preview confirmations expire after five minutes;
  changed files, VM settings or exclusions require a new preview.
- **Existing workspace:** file/path changes show **Updates available**. Choose
  **Sync from VM** to apply the current definition/layout and add/remove nodes.
  Saved matching-node identity, credentials, profiles, driver choice, backup
  selection, manual endpoints, schedules and backup history remain intact.
- **Automatic endpoints:** continue following discovered management IPs. Explicit
  nonstandard ports from inventory are treated as manual endpoints.
- **Missing annotations:** an existing map is retained. To update that map,
  restore the annotations on the VM or import the map manually. A new lab gets a
  generated map. Missing inventory does not erase existing credentials.
- **Invalid/inconsistent files:** existing workspaces stay intact and sync is
  blocked. For a new workspace, valid original YAML still imports if an optional
  file is invalid; the UI reports the skipped file. Credentials from a mismatched
  inventory are not applied. Correct the file and Sync from VM later.
- **Remove lab in the manager:** open the lab and select **Remove lab**. Confirm
  the named workspace. Imported nodes, map, credentials, schedule and history
  entries are removed from manager state. Backup files under `/data/backups/<old-id>`
  and audit logs remain on disk. Other labs, VM credentials and running containers
  are unaffected. Wait for active jobs and resolve or explicitly dismiss pending
  Git saves before removing the lab.
- **Test automatic import again:** uncheck **Keep this lab excluded from automatic
  import** in that dialog, remove it, and click Refresh discovery. Or leave the
  default exclusion enabled and later click **Import again** under its name in
  the sidebar. Either path requires a new import confirmation. Cancelling Import
  again keeps the exclusion. Confirming creates a new workspace with a new ID;
  old custom settings and history are not restored. Exclusions survive restarts.
- **Deleted/stopped lab:** its workspace, credentials and history remain. Discovery
  only finds deployed containers; it does not scan for never-deployed YAML files.
  Import those manually if you want to prepare a workspace before deployment.
- **Existing inventory workspace:** use **Link deployment** with the matching lab
  name, then **Sync from VM**. A matching unlinked workspace prevents a duplicate
  automatic import; it is not silently replaced.
- **Manager restart:** saved state survives; linked node actions/schedules wait
  for fresh discovery. Linked schedules require the lab to be fully Running.

For the disposable smoke test, destroy only that named test lab:

```bash
sudo containerlab destroy -t "$HOME/labs/manager-smoke/manager-smoke.clab.yaml"
```

Refresh discovery: its workspace should remain and say **Not deployed**. Redeploy
using the previous deploy command: the same workspace should return to Running.
Imported workspaces are snapshots, not copies of device filesystems or running
configurations. Back up NOS configurations separately using the manager.

## 9a. Connect a repository for Save progress

Complete a manual device backup before setting up Git publishing. Use your existing
ordinary VM account; no extra Linux user is needed on a standalone installation.
Create the destination repository on GitHub with a README, then from this source
directory run **without sudo**:

```bash
bash deploy/setup-git.sh
```

The wizard handles clone/reuse, GitHub login, commit identity and registration
checks. On a headless VM, authorize its device code in your workstation browser
and leave the terminal waiting. A missing VM browser is normal.
Follow [GIT-SETUP.md](GIT-SETUP.md) for the short walkthrough and error recovery.

In the lab, choose **Git repository settings**, select the registered checkout,
review the included devices and save the binding. **Save progress** now captures,
exports to `latest/`, commits and pushes. **Save locally** keeps the commit on the
VM; **Push saved progress** retries it later. Checkpoints and baseline preserve
milestones, and **Load version** downloads saved configurations without applying
commands to devices.

Git runs as the registered VM owner with that account’s authentication. The `clab-discovery` VM password
remains separate. The UI has no user login: everyone given access shares the
registered repositories' authority. Read [GIT-PROGRESS.md](GIT-PROGRESS.md) for
service-context credentials, review, conflicts, recovery and persistence.

Back up the owner's working checkout and the helper's registration/journal as well as
the manager data. A manager-only archive does not include his repository or Git
login. Resolve pending saves or explicitly **Keep snapshot only** before removing
that workspace or resetting the manager.

## 10. Back up persistent data and upgrade

### Back up the manager

**VM, repository root:** stop it briefly for a consistent directory copy. This
stops only the manager, not your labs. If your existing manager was launched with
`docker run`, use `sudo docker stop containerlab-node-manager` and
`sudo docker start containerlab-node-manager` in place of the two Compose commands.
The root-only archive contains credentials
and the encryption key as well as configuration backups.

```bash
sudo docker compose -f clab-backup-ui/compose.yml stop backup-ui
sudo install -d -m 0700 /srv/containerlab-node-manager-snapshots
sudo tar -C /srv/containerlab-node-manager -czf \
  /srv/containerlab-node-manager-snapshots/data-$(date +%Y%m%d-%H%M%S).tar.gz data
sudo docker compose -f clab-backup-ui/compose.yml start backup-ui
```

Keep another copy outside the VM. To restore on a new VM, stop its manager, retain
any current data as a separate recovery copy, extract the archive under
`/srv/containerlab-node-manager`, ensure the restored directory/files belong to
`10001:10001`, and start the manager. Restore `state.key` along with
the data. Reconfigure the discovery password/account for the new VM; a different VM
SSH host key needs verification before trusting it in the UI.

### Upgrade an existing installation to 1.15.2

Keep the original data directory and back it up first. Put the new source in
`~/projects/v1.15.2` with `clab-backup-ui/` and `deploy/` directly inside it.
Carry forward your previous `.env` or custom UI bind/port settings. For an existing
Compose installation, use the same entry point as a fresh launch:

```bash
cd "$HOME/projects/v1.15.2"
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
```

This updates and verifies the VM helper, retains the existing password/account,
prepares the persistent data directory, builds `clab-backup:1.15.2`, and recreates
the Compose service. It verifies the helper version/protocol even when no labs
are deployed. It prints no file contents or credentials during that check.
If Git progress was enabled, refresh its helper with `sudo bash deploy/setup-git.sh --refresh` from
this same source; keep the existing registrations and repository checkouts.

The browser must show v1.15.2. Refresh discovery; existing labs stay saved and new
labs wait for import confirmation. Existing workspaces still use Sync from VM.

If you only run `docker build`, host files cannot be updated from that image build.
Use the launch script for helper-based setup/upgrades. Advanced direct-SFTP users
can continue building and running Compose manually; their existing VM account
must have inspection and SFTP file-read permission. The restricted clab-discovery
account must use helper mode.

If a running docker-run manager uses the same data, the launch script stops after
building and asks you to complete the following migration. It does not remove it.

**If you launched the old standalone container with `docker run`**, it is not
owned by Compose. After building the new image, stop/remove just that manager
container (verify its `/data` bind mount first), then start Compose:

```bash
sudo docker inspect containerlab-node-manager --format '{{json .Mounts}}'
sudo docker stop containerlab-node-manager
sudo docker rm containerlab-node-manager
sudo docker compose -f clab-backup-ui/compose.yml up -d --no-build
```

Only do this when the inspected `/data` mount points to your persistent
`/srv/containerlab-node-manager/data`. Removing a container does not remove that
host directory. Do not run two manager processes against the same data directory.

## Troubleshooting

| Symptom | Check |
|---|---|
| `docker build` requires one argument | Use `./clab-backup-ui` from the repository root, or `.` inside that directory |
| Build downloads fail | VM DNS/internet or internal mirrors; source alone does not contain image/package dependencies |
| UI unreachable | VM IP, TCP 8081, hypervisor NAT/bridge, firewall, Compose `ps` and `logs` |
| Address already in use | Old manager is still running or another service occupies 8081; inspect `sudo ss -ltnp` |
| Permission denied for `/data` | `stat` should show `10001:10001 700`; use the provided setup script for a fresh directory |
| VM authentication fails | Username `clab-discovery`, its password, SSH service and setup script; see VM-CONNECTION.md for reset |
| Helper upgrade required | Run `sudo bash deploy/start-manager.sh` from current source on the VM; select helper mode and refresh |
| Connected but file import fails | Expand Discovery file details for each attempted path and result; update the helper, verify original YAML still exists, avoid symlinks, each file <=1 MiB |
| File locations unclear | `sudo containerlab inspect --all --format json` shows original `absLabPath`; generated files normally live in the adjacent `clab-<lab-name>` folder; verified labels can identify a custom folder |
| Saved map did not change | Save the correct `.annotations.json` beside the original YAML, refresh, then Sync from VM |
| Running but SSH/backup fails | NOS still booting, credentials/driver, network routing, or wrong SSH port; edit the node connection |
| YAML uses anchors/variables | Provide a resolved, literal definition manually; manager imports data without executing templates |
| A removed workspace reappears | Keep the exclusion checkbox enabled when removing it; unchecked allows it to appear for a new import confirmation |

Do not paste raw helper JSON into support logs: it carries base64-encoded file
contents, which can include inventory credentials. The UI reports controlled
errors without logging that payload.

## Airgapped installations

Perform dependency/image downloads on an approved connected machine with the
same architecture. Transfer the source and required Ubuntu/Docker/containerlab
packages or use your internal package mirrors. Build the manager there and export:

```bash
sudo docker save clab-backup:1.15.2 -o clab-backup-1.15.2.tar
```

On the prepared offline VM, after completing storage and discovery-password setup
above, update both host helpers from the transferred source before starting:

```bash
sudo docker load -i clab-backup-1.15.2.tar
sudo bash deploy/setup-discovery.sh --update-helper
sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
sudo docker compose -f clab-backup-ui/compose.yml up -d --no-build
```

Transfer required lab images separately. The UI assets are bundled; no CDN is
needed at runtime. SSH discovery and file import stay on the VM.
Use these explicit helper commands for offline upgrades too; the normal
`start-manager.sh` command intentionally builds with `--pull --no-cache` and
requires package/image access. Retained lab command prerequisites are in
[LAB-OPERATIONS.md](LAB-OPERATIONS.md); leave downloads disabled for offline VMs.

## Validation boundary

The release includes automated parser/API, persistence and SSH transport tests.
Docker builds, root-owned helper installation, Linux filesystem protections and
live vendor-node operations still require verification on your Linux VM. See
[VALIDATION.md](clab-backup-ui/VALIDATION.md) for the exact evidence.
