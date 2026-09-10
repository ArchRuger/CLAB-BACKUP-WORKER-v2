# Containerlab Node Manager 1.8.0 — a fresh VM to a working lab

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
git clone https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2.git
cd CLAB-BACKUP-WORKER-v2
cat clab-backup-ui/VERSION
```

This guide requires **1.8.0** source, including `deploy/clab_manager_files.py`.
If the clone reports an older version, obtain the 1.8.0 source package or the
matching release commit before proceeding. Local source delivery does not mean
the GitHub repository has already been updated. For a delivered ZIP, extract it
and use its `CLAB-BACKUP-WORKER-v2-1.8.0` directory as the repository root instead.
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
credential profiles, schedules, backup history/files, action logs and the UI
access token. State and credentials are encrypted in `state.enc`; **retain
`state.key` alongside it**. Configuration backup files are separate files under
`backups/`. Copy the entire data directory when backing up or moving the manager.

If this is actually an upgrade from a worker that kept data inside its container,
stop here and follow [the migration procedure](STANDALONE-SETUP.md#2-migrate-an-existing-worker-if-present)
before starting the new manager. A genuinely fresh VM has nothing to migrate.

## 5. Set up the restricted VM discovery key

**Workstation:** generate a dedicated key pair. These commands work in a terminal
with OpenSSH, including Windows PowerShell. Run in a folder where you can find
the resulting files; choose a passphrase when prompted, or press Enter for none.

```text
ssh-keygen -t ed25519 -f clab-manager-discovery
scp clab-manager-discovery.pub YOUR_VM_USER@VM_IP:clab-manager-discovery.pub
```

Two files are created:

| File | Use |
|---|---|
| `clab-manager-discovery.pub` | Public key: copied to the VM for the setup script |
| `clab-manager-discovery` | Private key: retain on your workstation; select this file in the manager UI |

**VM, repository root:**

```bash
sudo bash deploy/setup-discovery.sh "$HOME/clab-manager-discovery.pub"
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

The script creates the `clab-discovery` account, a root-owned helper and a validated
sudoers rule. Its SSH key can invoke only the fixed helper; it cannot open a shell,
PTY or tunnel. The account is not added to the Docker group. The helper uses the
host's Docker CLI to read deployment labels; the manager container receives no
Docker socket and needs no mount of your lab directories.

It reads deployment state and **only** these files from verified metadata:

| File | Location and purpose |
|---|---|
| Original YAML | Exact topology path reported by containerlab; node names/kinds and wiring |
| `<original-yaml-filename>.annotations.json` | Beside the original YAML; VS Code layout, groups and notes |
| `ansible-inventory.yml` | Generated lab directory; connection data and available device credentials |
| `topology-data.json` | Generated lab directory; exported node identities/kinds |

The generated directory comes from container labels, including custom lab
directories. There is no recursive disk search. Files must be regular files with
no symlink components, at most 1 MiB each. The helper caps file content at 8 MiB
per inspection and examines at most 100 labs. It never executes YAML, Ansible
inventory scripts, deploy/destroy commands, or device configuration commands.
Some nonstandard or unresolved template-based definitions need manual import.

If your existing key is already installed, **do not generate another key**: use
the upgrade section below. If you generated it on the VM instead, copy the
private file to your workstation using your normal file transfer and keep its
permissions private; the setup script still takes the `.pub` file.

## 6. Build a fresh image and launch the manager

**VM, repository root:**

```bash
sudo docker compose -f clab-backup-ui/compose.yml build --pull --no-cache
sudo docker compose -f clab-backup-ui/compose.yml up -d
sudo docker compose -f clab-backup-ui/compose.yml ps
sudo docker compose -f clab-backup-ui/compose.yml exec backup-ui \
  python -c 'from app import __version__; print(__version__)'
sudo docker compose -f clab-backup-ui/compose.yml logs --tail=30 backup-ui
```

Expect **1.8.0**. The startup log prints the UI access token. To retrieve the
persisted token directly:

```bash
sudo cat /srv/containerlab-node-manager/data/ui.token
```

Open **`http://VM_IP:8081`** on your workstation and enter the token.

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
sudo docker build --pull --no-cache -t clab-backup:1.8.0 ./clab-backup-ui
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
| Authentication | SSH private key |
| Private key | Select `clab-manager-discovery`, without `.pub` |
| Passphrase | The key passphrase, if you chose one |
| Inspection method | Installed discovery and file helper |
| Automatic discovery | Enabled |

Click **Save and test connection**. The UI should report that the VM is connected.
The first successful connection trusts and saves its SSH fingerprint. Reopen the
dialog to compare it to the host key fingerprint from step 5 (the negotiated key
may instead be RSA/ECDSA; inspect that corresponding host public key). Later
unexpected fingerprint changes block discovery until you verify/reset it.

These credentials access the VM helper. Device SSH/backup credentials are separate;
they come from generated inventory when available or from your saved profiles.
Leaving credential fields blank when saving the same VM account retains its key.

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

Within approximately 30 seconds, or after **Refresh discovery**:

1. A new workspace appears for the deployed lab without uploading files.
2. The node list shows detected addresses and deployment status.
3. Topology shows the saved layout if annotations exist, otherwise a simple map.
4. The list and map retain node actions; right-click a map node for SSH, backup
   and details. Unsupported device kinds have no NOS backup adapter.

The Alpine smoke test has **no SSH server or NOS backup support**; use it to check
discovery, persistence and wiring only. With Junos, IOS-XR or EOS devices, check
the imported credentials or assign a profile, wait for the NOS to finish booting,
then use **Test NOS login**, SSH and a single-node backup. A Running container
does not establish that its NOS is ready. Your licensed vendor images and their
requirements are separate from the manager installation.

## 9. Change files, switch labs, and keep your work

- **New deployment:** a valid new lab imports automatically. Schedules start in
  Manual. Nothing automatically backs up or changes the devices.
- **Existing workspace:** file/path changes show **Updates available**. Choose
  **Sync from VM** to apply the current definition/layout and add/remove nodes.
  Saved matching-node identity, credentials, profiles, driver choice, backup
  selection, manual endpoints, schedules and backup history remain intact.
- **Automatic endpoints:** continue following discovered management IPs. Explicit
  nonstandard ports from inventory are treated as manual endpoints.
- **Missing annotations:** an existing map is retained. To update that map,
  restore the annotations on the VM or import the map manually. A new lab gets a
  generated map. Missing inventory does not erase existing credentials.
- **Invalid/inconsistent files:** the workspace stays intact and sync is blocked.
  The UI identifies the lab needing manual import/file correction. Original YAML
  is required; optional inventory and topology export must match its nodes.
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
`10001:10001`, and start the manager. Restore `state.key` and `ui.token` along with
the data. Reconfigure the discovery key/account for the new VM; a different VM
SSH host key needs verification before trusting it in the UI.

### Upgrade an existing 1.7.0 installation to 1.8.0

Obtain the new source, keep the original data directory, and back it up first.
From the updated repository root:

```bash
sudo bash deploy/setup-discovery.sh --update-helper
sudo docker compose -f clab-backup-ui/compose.yml build --pull --no-cache
```

If the existing manager is already managed by this Compose file, recreate it:

```bash
sudo docker compose -f clab-backup-ui/compose.yml up -d --force-recreate
```

If it was launched with `docker run`, skip that command and follow the separate
container replacement instructions immediately below before starting Compose.

`--update-helper` preserves your existing discovery account and authorized key.
No new SSH key or data initialization is needed. In the UI select the installed
helper, refresh discovery, then **Sync from VM** for existing lab workspaces.
An older helper/direct mode continues to discover nodes but cannot import files.

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
| VM authentication fails | Username `clab-discovery`, private key without `.pub`, correct passphrase, SSH service and setup script |
| Helper upgrade required | Run `setup-discovery.sh --update-helper` from new source, select helper mode, refresh |
| Connected but file import fails | Original YAML still exists, labels reference it, optional files match nodes, no symlinks, each file <=1 MiB |
| File locations unclear | `sudo containerlab inspect --all --format json` shows original `absLabPath`; generated directory comes from `clab-node-lab-dir` |
| Saved map did not change | Save the correct `.annotations.json` beside the original YAML, refresh, then Sync from VM |
| Running but SSH/backup fails | NOS still booting, credentials/driver, network routing, or wrong SSH port; edit the node connection |
| YAML uses anchors/variables | Provide a resolved, literal definition manually; manager imports data without executing templates |
| A removed workspace reappears | It is still deployed on the VM, so automatic import recreates it |

Do not paste raw helper JSON into support logs: it carries base64-encoded file
contents, which can include inventory credentials. The UI reports controlled
errors without logging that payload.

## Airgapped installations

Perform dependency/image downloads on an approved connected machine with the
same architecture. Transfer the source and required Ubuntu/Docker/containerlab
packages or use your internal package mirrors. Build the manager there and export:

```bash
sudo docker save clab-backup:1.8.0 -o clab-backup-1.8.0.tar
```

On the prepared offline VM:

```bash
sudo docker load -i clab-backup-1.8.0.tar
sudo docker compose -f clab-backup-ui/compose.yml up -d --no-build
```

Transfer required lab images separately. The UI assets are bundled; no CDN is
needed at runtime. SSH discovery and file import stay on the VM.

## Validation boundary

The release includes automated parser/API, persistence and SSH transport tests.
Docker builds, root-owned helper installation, Linux filesystem protections and
live vendor-node operations still require verification on your Linux VM. See
[VALIDATION.md](clab-backup-ui/VALIDATION.md) for the exact evidence.
