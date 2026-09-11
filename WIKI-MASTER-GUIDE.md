> Historical guide for earlier releases. For 1.13.0, use [VM-CONNECTION.md](VM-CONNECTION.md)
> and [FRESH-VM-GUIDE.md](FRESH-VM-GUIDE.md). Their password setup replaces the SSH client key steps below.
> Build 1.13.0 from source; no new registry image is claimed by this delivery.

# Containerlab Node Manager — Master Build & Operations Guide

Build an engineer's training VM, install **Containerlab Node Manager 1.12.0**, and keep labs, credentials and configuration history across container upgrades.

This page combines the Ubuntu/Proxmox build notes, the installation walkthrough and the current manager documentation. Follow it from the beginning for a fresh VM. If Docker and Containerlab already work, start at **Part 6**, after checking the reference paths below.

> **Release baseline:** `archtop/clab-backup:1.12.0`. The default installation runs the downloaded image. Matching repository files supply the VM helpers and Compose configuration. One engineer gets one VM and one persistent manager.
{.is-info}

> **UI update — 1.12.1:** the updated source uses **Deploy New Lab → Lab Topologies**, an explicit browser button and same-tab return navigation. Start/Destroy are on the lab status panel. The Docker Hub installation examples below remain pinned to the previously supplied `1.12.0` image; use the repository’s `UI-UPDATE-1.12.1.md` for the new source build.
{.is-info}

## Reference environment

| Setting | Example / standard |
|---|---|
| Hypervisor | Proxmox VE |
| Guest OS | Ubuntu Server 24.04 LTS |
| Current example hostname | `clab-3` |
| Current example VM address | `10.150.2.213` |
| Subnet / gateway | `10.150.2.0/24` / `10.150.2.1` |
| Example DNS | `8.8.8.8`, or your internal resolver |
| VM administrator | `archtop` |
| Proxmox VM ID | Look up with `qm list`; do not infer it from the hostname |
| Earlier reference hosts | `clab-1`: `10.150.2.211`; `clab-2`: `10.150.2.212` |
| Manager UI | `http://10.150.2.213:8081` |
| Release files | `/home/archtop/projects/v1.12.0/` |
| Persistent manager data | `/srv/containerlab-node-manager/data/` |
| Lab projects | `/etc/containerlab/<project>/` |
| VM helper account | `clab-discovery` |

Replace these example addresses and usernames for each engineer. The old build's VM ID `101` belongs to that example; it is not a universal value. This guide assumes a normal rootful Docker Engine installation without user-namespace remapping.

## Where commands run

| Label | Terminal |
|---|---|
| **Proxmox host** | Proxmox node shell; `qm` commands run here |
| **Ubuntu VM** | Console or SSH session logged in as your normal administrator |
| **Workstation** | Your Windows/Linux/macOS computer, where the browser and key files live |
| **Manager UI** | The web application at the VM address |

All manager installation and maintenance commands run in the **Ubuntu VM** unless stated otherwise. Do not run `qm` inside Ubuntu, or Linux `sudo` commands in Windows PowerShell. Code blocks contain commands without shell prompt prefixes.

## How the pieces connect

```text
Engineer workstation
  Browser -------- TCP 8081 --------> Node Manager container
                                        | /data bind mount
                                        +--> /srv/containerlab-node-manager/data
                                        |
                                        +-- SSH --> VM helper (clab-discovery)
                                        |          discovery, files, lab commands
                                        |
                                        +-- SSH --> network nodes

Proxmox --> Ubuntu VM --> Docker / Containerlab --> training devices
                         independent manager       lab deployments
```

The manager keeps running when a lab is stopped or destroyed. Deployed labs remain on the VM; importing a lab creates a saved manager workspace. The two have different lifecycles.

> **Access model:** 1.12.0 opens directly without a UI login. Give access to TCP 8081 only to the intended engineers. VM discovery authentication and device SSH credentials are still required and are stored in the persistent manager data.
{.is-warning}

## Page contents

| Part | Topic |
|---|---|
| [1](#part-1) | Build the Ubuntu VM |
| [2](#part-2) | Enable nested virtualization when required |
| [3](#part-3) | Make the intended disk space available |
| [4](#part-4) | Install Docker, Compose and Containerlab |
| [5](#part-5) | Engineer access, WinSCP and VS Code |
| [6](#part-6) | Get the release image and matching host files |
| [7](#part-7) | Prepare persistent storage |
| [8](#part-8) | Create the VM connection key |
| [9](#part-9) | Install discovery, file-transfer and operations helpers |
| [10](#part-10) | Launch Containerlab Node Manager |
| [11](#part-11) | Connect the UI to the VM |
| [12](#part-12) | Deploy, discover and import labs |
| [13](#part-13) | Node inventory, maps, SSH and backups |
| [14](#part-14) | Lab commands, VM projects and interactive draw.io |
| [15](#part-15) | Everyday container management |
| [16](#part-16) | Upgrade without losing data |
| [17](#part-17) | Backups, recovery and manager-only removal |
| [18](#part-18) | VM connection repair, lost keys and multiple keys |
| [19](#part-19) | Troubleshooting and lessons from the first install |
| [20](#part-20) | Airgapped installation and handoff checklist |

---

# Part 1 — Build the Ubuntu VM {#part-1}

## Step 1.1 — Create and install the guest

On Proxmox, create a VM using the Ubuntu Server 24.04 LTS ISO. Allocate CPU, memory and disk for the **whole training lab**, particularly VM-based network images. There is no single sizing value that fits every topology. Attach its network interface to the bridge/VLAN reachable by your workstation.

During Ubuntu installation:

1. Select the normal server installation and your keyboard settings.
2. Configure the network interface, commonly `ens18`, with **Manual IPv4**.
3. Enter your assigned subnet, address, gateway and DNS from the reference table.
4. Leave the proxy empty unless your environment requires one.
5. Select the intended virtual disk; use LVM if following Part 3.
6. Set the hostname and normal administrator account. Use your chosen password.
7. Enable **Install OpenSSH server**. Extra server snaps and Ubuntu Pro enrollment are optional.
8. Complete installation, detach the ISO if needed and boot from the installed disk.

> Confirm the IP allocation in your network records before assigning it. A successful ping indicates the address is in use; no ping response does not prove it is free.
{.is-info}

## Step 1.2 — Verify connectivity

**Ubuntu VM:**

```bash
hostnamectl
ip -br address
ip route
getent hosts download.docker.com
sudo systemctl status ssh --no-pager
```

**Workstation:**

```text
ssh archtop@10.150.2.213
```

Verify the new VM's SSH fingerprint through its console before accepting it. Continue installation in this SSH session if preferred.

**Ubuntu VM:**

```bash
sudo apt update
sudo apt install -y ca-certificates curl git openssh-server python3 sudo
sudo systemctl enable --now ssh
```

> **Checkpoint:** you can log in from the workstation using the normal VM account, resolve package hosts and run `sudo`.
{.is-success}

---

# Part 2 — Enable nested virtualization when required {#part-2}

VM-based NOS images, including cJunosEvolved, need virtualization support inside the Ubuntu guest. Containerlab and Node Manager themselves do not require nested KVM merely to run ordinary containers.

```text
Physical CPU -> Proxmox/KVM (L0) -> Ubuntu VM (L1)
                                  -> device container -> internal QEMU/KVM VM (L2)
```

## Step 2.1 — Check the Proxmox host

**Proxmox host:**

```bash
qm list
lscpu
```

Identify the correct VM and CPU vendor. Check the relevant module:

## CPU vendor {.tabset}

### Intel

```bash
cat /sys/module/kvm_intel/parameters/nested
```

Expected: `Y` or `1`. If disabled, review existing module settings and configure `options kvm_intel nested=1` in the host's modprobe configuration. Apply during planned host maintenance; do not unload an in-use KVM module.

### AMD

```bash
cat /sys/module/kvm_amd/parameters/nested
```

Expected: `Y` or `1`. If disabled, review existing module settings and configure `options kvm_amd nested=1` in the host's modprobe configuration. Apply during planned host maintenance.

## Step 2.2 — Expose the host CPU to the guest

**Proxmox host:** read the ID from `qm list`, then select it explicitly:

```bash
read -r -p "Ubuntu VM ID from qm list: " LAB_VMID
qm config "$LAB_VMID"
```

Confirm this is the intended guest. Shut it down cleanly, then check its state:

```bash
qm shutdown "$LAB_VMID" --timeout 60
qm status "$LAB_VMID"
```

Only after the status is **stopped**, change the CPU type and start it:

```bash
qm set "$LAB_VMID" --cpu host
qm start "$LAB_VMID"
```

The change requires a full guest stop/start. This is not an instruction to reboot the entire Proxmox host. Nested KVM behavior is described in the [Linux KVM documentation](https://docs.kernel.org/virt/kvm/x86/running-nested-guests.html).

## Step 2.3 — Verify inside Ubuntu

**Ubuntu VM:**

```bash
lscpu
ls -l /dev/kvm
lsmod | grep kvm
```

If `/dev/kvm` is missing, revisit host nesting and the guest CPU type. Device boot logs reporting KVM failures are a direct clue; `tap0`/`tap1` or EVO startup waits alone are not proof of a KVM problem. Check the device image's own boot requirements as well.

---

# Part 3 — Make the intended disk space available {#part-3}

The example build had a large virtual disk but a 100 GiB root logical volume. A large disk in Proxmox does not automatically mean the Ubuntu filesystem uses all of it.

## Step 3.1 — Inspect before resizing

**Ubuntu VM:**

```bash
lsblk -f
sudo pvs
sudo vgs
sudo lvs
findmnt -no SOURCE,FSTYPE /
df -h /
```

Confirm the root LV name, filesystem type and **VFree** in its volume group. The commands below apply only when the root is `/dev/ubuntu-vg/ubuntu-lv` and that volume group already has free extents.

## Step 3.2 — Extend the logical volume

If this training VM should allocate all remaining VG space to its root LV:

```bash
sudo lvextend -l +100%FREE /dev/ubuntu-vg/ubuntu-lv
```

This consumes the VG's unallocated space. Leave space unallocated instead if you plan other logical volumes. The allocation syntax is documented in [Ubuntu's lvextend manual](https://manpages.ubuntu.com/manpages/noble/man8/lvextend.8.html).

## Root filesystem {.tabset}

### ext4

```bash
sudo resize2fs /dev/ubuntu-vg/ubuntu-lv
df -h /
```

### XFS

```bash
sudo xfs_growfs /
df -h /
```

## Step 3.3 — Confirm the result

Compare `df -h /` with your intended allocation. The old build reached approximately 982 GiB usable filesystem capacity; your result depends on disk size and filesystem overhead.

If **VFree is zero**, these commands cannot create additional space. Determine whether the virtual disk, partition or physical volume needs expansion first. Do not guess a partition name or apply a partition-resize command from another host. Non-LVM installations need their filesystem's own expansion procedure.

---

# Part 4 — Install Docker, Compose and Containerlab {#part-4}

## Step 4.1 — Install Docker on a fresh Ubuntu VM

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

Manager administration uses `sudo docker` consistently. Part 5 adds engineer groups for VS Code when needed. Use normal rootful Docker Engine; rootless Docker or user
namespace remapping requires different persistent-directory ownership.

## Step 4.2 — Install Containerlab

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

> Press <kbd>q</kbd> to exit `less`. <kbd>Ctrl</kbd>+<kbd>Z</kbd> suspends it instead. If you see `[1]+ Stopped less ...`, use `fg` to return to that job, then press <kbd>q</kbd>.
{.is-info}

If Docker already works, verify it and skip its installation block. Do not run Containerlab's separate “install everything” setup over this sequence; Docker is already installed here.

---

# Part 5 — Engineer access, WinSCP and VS Code {#part-5}

## Step 5.1 — Allow the engineer to use Docker and Containerlab

**Ubuntu VM:** the optional VS Code workflow needs the normal engineer account in both groups:

```bash
getent group docker
getent group clab_admins
sudo usermod -aG docker,clab_admins archtop
```

If `clab_admins` is absent, check the Containerlab installation before continuing. Log out and establish a fresh SSH session, then verify:

```bash
id
docker ps
containerlab inspect --all
```

These groups grant elevated host capabilities. Add the normal training administrator, **not** the restricted `clab-discovery` account. The [Containerlab VS Code setup guide](https://containerlab.dev/manual/gui/vsc-extension/) describes the required access.

## Step 5.2 — Create a writable lab workspace

On a fresh VM:

```bash
sudo install -d -o archtop -g archtop -m 0755 /etc/containerlab
mkdir -p /etc/containerlab/BGP_TheoryToPractice
```

Copy the complete project into that folder, including referenced startup configurations. Existing root-owned project folders need ownership corrections scoped to the intended project. Group membership alone does not grant write access to every directory.

> Lab source folders and manager storage have different owners. The engineer can own their lab project. `/srv/containerlab-node-manager/data` stays `10001:10001`, mode `700`.
{.is-warning}

## File transfer {.tabset}

### Normal WinSCP session

Connect using SFTP, host `10.150.2.213`, port `22`, user `archtop`, and your normal VM login. Upload projects to the engineer-owned directory above. Use the normal account for key transfers as well.

### Optional administrative SFTP

Only if you need root-level file administration, first verify the server binary on Ubuntu:

```bash
ls -l /usr/lib/openssh/sftp-server
sudo visudo -f /etc/sudoers.d/archtop-sftp
```

Add the following rule, adjusting the username if needed:

```text
archtop ALL=(root) NOPASSWD: /usr/lib/openssh/sftp-server
```

Validate with `sudo visudo -c`. In WinSCP, open **Advanced → Environment → SFTP** and set the server to:

```text
sudo /usr/lib/openssh/sftp-server
```

This session can modify root-owned files. It is optional and not needed for the normal project upload workflow. Do not add the old example's blanket `NOPASSWD: ALL` rule just to transfer files. See [WinSCP's sudo/SFTP guidance](https://winscp.net/eng/docs/faq_su).

## Step 5.3 — Connect VS Code to the VM

Install **Remote - SSH** on the workstation, connect to `archtop@10.150.2.213`, and open the VM project folder. Install the Containerlab extension in that **remote VM context**. Check `id`, `docker ps` and `containerlab inspect --all` in the integrated remote terminal.

If an old VS Code server process retains the previous groups, close the connection and restart that remote server/session. A VM reboot is a fallback after saving work; a Proxmox host reboot is not required for group changes.

## Step 5.4 — Obtain required device images

Node Manager's image does not contain the router/switch images. Read the topology's `image:` entries and pull or load each required image. Log in to Docker Hub only when needed for private access or authenticated pulls:

```bash
sudo docker login -u archtop
sudo docker image ls
```

Use the same account context for login and image pulls: `sudo docker login` stores credentials for root, while `docker login` uses your normal user's configuration. Enter a registry token/password at the prompt. Registry credentials, the VM login and device credentials are separate.

---

# Part 6 — Get the release image and matching host files {#part-6}

## Step 6.1 — Identify the image

Use **`archtop/clab-backup:1.12.0`** for this release. Confirm the local image
and application version before installing its matching host helpers.

```bash
sudo docker image ls
MANAGER_IMAGE='archtop/clab-backup:1.12.0'
sudo docker image inspect "$MANAGER_IMAGE" --format 'User={{.Config.User}} Image={{.Id}}'
sudo docker run --rm --pull never --network none --entrypoint python "$MANAGER_IMAGE" \
  -c 'from app import __version__; print(__version__)'
sudo docker compose version
```

The version check should print **1.12.0** for this guide. It starts only a temporary
Python version check, without mounting data or starting the manager. An image-not-found
error means the name/tag differs from the image you downloaded. Select a release tag
or digest rather than a moving `latest` tag so image and helper versions can be matched. If the image
is not present yet, run `sudo docker pull archtop/clab-backup:1.12.0` first.

If Compose is missing, install the Docker Compose plugin for your Docker Engine
installation using [Docker's Ubuntu installation guide](https://docs.docker.com/engine/install/ubuntu/).
For an entirely unconfigured machine, [Part 4](#part-4) covers Docker installation.

## Step 6.2 — Download the host setup files

```bash
mkdir -p "$HOME/projects"
cd "$HOME/projects"
git clone https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2.git v1.12.0
cd v1.12.0
cat clab-backup-ui/VERSION
```

The folder name does not select a Git release. Confirm that the version printed
by the repository **matches the image version from Step 6.1**. If GitHub still has
an older release, use the matching delivered source ZIP or published release ref.
Do not install mismatched helpers. For a ZIP, place `deploy/` and `clab-backup-ui/`
directly inside `~/projects/v1.12.0`, rather than inside another nested folder.

Verify the required files are present:

```bash
ls deploy/compose.image.yml deploy/setup-vm.sh deploy/setup-discovery.sh \
  deploy/setup-operations.sh deploy/verify-helper.py deploy/verify-operations.py \
  clab-backup-ui/app/host_files.py clab-backup-ui/app/host_operations.py
```

Keep this directory for helper updates and management commands. Cloning it does
not build or start anything. The existing `deploy/start-manager.sh` is a **source
build workflow**; use the commands in this guide when consuming a prebuilt image.

The final layout should be:

```text
/home/archtop/projects/v1.12.0/
  deploy/
    compose.image.yml
    setup-vm.sh
    setup-discovery.sh
    setup-operations.sh
  clab-backup-ui/
    VERSION
    Dockerfile
    app/

/etc/containerlab/BGP_TheoryToPractice/       lab sources and deployment artifacts
/srv/containerlab-node-manager/data/         created in Part 7; survives upgrades
```

---

# Part 7 — Prepare persistent storage {#part-7}

From `~/projects/v1.12.0`:

```bash
sudo bash deploy/setup-vm.sh
sudo stat -c '%u:%g %a %n' /srv/containerlab-node-manager/data
```

Expected output starts with **`10001:10001 700`**. The container's worker user has
UID/GID 10001. You do not need to create a matching host login or use `chmod 777`.

This directory will hold imported labs, encrypted credentials/settings, schedules,
operation history, logs and configuration backup files. Keep `state.key` with
`state.enc`; restoring the encrypted state without its key will not work.
Removing or replacing the container does not remove this bind-mounted directory.

On an existing machine, migrate any old container-only data using
[the migration subsection](#part-7) before starting a new manager. Run only
one manager process/container against a data directory.

## Existing lab-embedded worker only

Skip this subsection on a fresh VM. If an old worker kept its only copy of `/data` inside its container, migrate it **before** removing that container or starting the new manager:

```bash
# Replace this example with the actual old worker container name.
sudo bash deploy/migrate-worker-data.sh clab-BGP_TheoryToPractice-Backup-Worker
```

The script stops that worker, copies its data and keys, checks the copy and retains a recovery copy. It refuses a nonempty destination. After validating the new manager, remove the worker definition from the lab YAML so a later deployment does not recreate it. Keep the old stopped container until its history and backups are verified in the new manager.

---

# Part 8 — Create the VM connection key {#part-8}

Choose **one** key-generation method. Generating it on the workstation avoids an extra private-key transfer. Never overwrite an existing key pair during a routine upgrade.

## Step 8.1 — Key-generation location {.tabset}

### Workstation — recommended

Open a terminal in a private folder where you can retain the key. These commands work with OpenSSH, including Windows PowerShell:

```text
ssh-keygen -t ed25519 -f clab-manager-discovery
scp clab-manager-discovery.pub archtop@10.150.2.213:clab-manager-discovery.pub
```

Choose a passphrase when prompted, or press Enter for no passphrase. If the files already exist, use a new filename instead of agreeing to overwrite them.

On the **Ubuntu VM**, set and check the public-key path:

```bash
KEY_PUB="$HOME/clab-manager-discovery.pub"
test -r "$KEY_PUB" && ssh-keygen -lf "$KEY_PUB"
```

### Ubuntu VM — alternative

**Ubuntu VM**, normal administrator account:

```bash
install -d -m 0700 "$HOME/.ssh"
ssh-keygen -t ed25519 -f "$HOME/.ssh/clab-manager-discovery"
KEY_PUB="$HOME/.ssh/clab-manager-discovery.pub"
test -r "$KEY_PUB" && ssh-keygen -lf "$KEY_PUB"
```

Transfer the private file to a private folder on your workstation, for example from a workstation terminal:

```text
scp archtop@10.150.2.213:/home/archtop/.ssh/clab-manager-discovery .
```

The manager UI will need that private file. Retain the key pair in your chosen private storage location, outside the source repository.

## Step 8.2 — Understand which file goes where

| File | Purpose |
|---|---|
| `clab-manager-discovery.pub` | Public key installed on the Ubuntu VM |
| `clab-manager-discovery` | Private key selected in the manager's VM connection form |
| Passphrase, if chosen | Unlocks that private key; enter it in the form |

`KEY_PUB` exists only in the current Ubuntu shell. If you reconnect, set it again to the path you actually used before Part 9.

> **Fix from the installation walkthrough:** `ssh-keygen -f clab-manager-discovery` creates files in the current folder. If that folder is `~/projects/v1.12.0`, the public key is there; `$HOME/clab-manager-discovery.pub` points somewhere else. Use the actual path. The error does not mean you need to generate another pair.
{.is-warning}

To locate a pair created in the release folder:

```bash
cd "$HOME/projects/v1.12.0"
pwd
ls -l ./clab-manager-discovery.pub
```

If this is your public key, use `KEY_PUB="$HOME/projects/v1.12.0/clab-manager-discovery.pub"` for installation. Move retained private keys out of version folders before sharing or replacing source files.

---

# Part 9 — Install discovery, file-transfer and operations helpers {#part-9}

**VM** — this key-install command is for the fresh account described by this guide:

```bash
cd "$HOME/projects/v1.12.0"
if [ -n "${KEY_PUB:-}" ] && [ -r "$KEY_PUB" ]; then
  sudo bash deploy/setup-discovery.sh "$KEY_PUB" &&
    sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
else
  printf 'Public key not found. Set KEY_PUB to its actual absolute path before continuing.\n'
fi
```

If the public-key check fails, correct `KEY_PUB` before proceeding.

This creates the restricted `clab-discovery` account and installs the discovery,
file-transfer and lab-operation helpers. Setup with a public key replaces that
account's existing authorized keys; use `--update-helper` for upgrades instead.
The account does not provide a general interactive SSH shell.

Verify the installed helpers match this release:

```bash
sudo /usr/local/sbin/clab-manager-inspect | python3 deploy/verify-helper.py 1.12.0
printf '%s\n' '{"mode":"capabilities"}' | sudo /usr/local/sbin/clab-manager-operate \
  | python3 deploy/verify-operations.py 1.12.0
```

Both commands must report version **1.12.0** successfully. The verifiers avoid
printing imported file contents, which may contain device passwords. If a check
fails, repair the helper before continuing; see [VM connection repair](#part-18).

If projects live elsewhere, add their actual parent directory with
`sudo bash deploy/setup-operations.sh --lab-root /your/project/directory`.
Use real directories without symlink components. The manager needs no Docker
socket mount and no mount of the host lab directories; helpers access them over SSH.

---

# Part 10 — Launch Containerlab Node Manager {#part-10}

From `~/projects/v1.12.0`, create the local image settings. This file retains the
image selection across terminal sessions:

```bash
cat > deploy/image.env <<'EOF'
MANAGER_IMAGE=archtop/clab-backup:1.12.0
UI_BIND=0.0.0.0
UI_PORT=8081
EOF

sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml config
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml \
  up -d --no-build --pull never
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml ps
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml \
  logs --tail=50 backup-ui
```

The supplied `compose.image.yml` has **no build section** and uses the local image.
It mounts the persistent directory at `/data`, runs one worker, and restarts the
manager automatically after a VM reboot or unexpected exit. `--pull never` also
makes a missing/wrong image name fail immediately rather than fetching another image.
The image and pull policy are standard [Compose service settings](https://docs.docker.com/reference/compose-file/services/).

Do not launch this alongside an older manager using the same data. The standard
Compose project/service names are shared with the source-build installation to
support replacement; a separately named `docker run` installation must be stopped
and migrated first.

Check the running release and local HTTP endpoint:

```bash
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml \
  exec backup-ui python -c 'from app import __version__; print(__version__)'
curl -fsS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8081/
```

Expect **1.12.0** and **HTTP 200**. Use the customized port if you changed UI_PORT.

## Reference — the image-based Compose configuration

The matching repository supplies this file at `deploy/compose.image.yml`:

```yaml
# Runs an already downloaded release image. There is deliberately no build section.
# Usage from the repository root:
# docker compose --env-file deploy/image.env -f deploy/compose.image.yml up -d --no-build --pull never
name: containerlab-node-manager
services:
  backup-ui:
    image: ${MANAGER_IMAGE:?Set MANAGER_IMAGE in deploy/image.env to your downloaded release image}
    pull_policy: never
    restart: unless-stopped
    network_mode: host
    command: ["uvicorn", "app.main:create_app", "--factory", "--host", "${UI_BIND:-0.0.0.0}", "--port", "${UI_PORT:-8081}", "--workers", "1"]
    environment:
      DATA_DIR: /data
    volumes:
      - type: bind
        source: /srv/containerlab-node-manager/data
        target: /data
        bind:
          create_host_path: false
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
```


## Alternative — build from source

Use this only when intentionally building locally. Complete Parts 7–9 first, then from the repository root:

```bash
cd "$HOME/projects/v1.12.0"
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
sudo docker compose -f clab-backup-ui/compose.yml ps
sudo docker compose -f clab-backup-ui/compose.yml logs --tail=50 backup-ui
```

This refreshes the installed helpers, builds `clab-backup:1.12.0` without cache and recreates the manager. For this installation method, use `-f clab-backup-ui/compose.yml` in maintenance commands instead of the Hub guide's `--env-file deploy/image.env -f deploy/compose.image.yml`.

For an image build alone, the build context is required:

```bash
# From the repository root:
sudo docker build --pull --no-cache -t clab-backup:1.12.0 ./clab-backup-ui
```

If already inside `clab-backup-ui`, use `.` as the final argument. Building alone neither starts a container nor updates host helpers. Run only one manager against the persistent directory.

---

# Part 11 — Connect the UI to the VM {#part-11}

On your workstation, open **`http://VM_IP:8081`**. There is no access-token login.
Choose **VM connection** and enter:

| Field | Value for this deployment |
|---|---|
| VM address | `127.0.0.1` |
| SSH port | `22`, unless your VM SSH server uses another port |
| VM username | `clab-discovery` |
| Authentication | SSH private key |
| SSH private key | Workstation file `clab-manager-discovery`, without `.pub` |
| Key passphrase | Your key passphrase, if set |
| Inspection method | Installed discovery and file helper |
| Enable automatic discovery | Checked |

Click **Save and test connection**. The first successful connection records the
VM's SSH host fingerprint. The sidebar should report **VM connected**.
Later host-key changes need explicit verification and acceptance in the UI.

## Why there is no Docker port mapping

This deployment uses Linux **host networking**. The manager listens directly on
the VM's TCP port 8081 and can reach the lab management addresses on that VM.
`127.0.0.1` in VM connection therefore reaches the VM's SSH service.
Do not add `-p 8081:8081`: Docker ignores published ports in host mode.
[Docker host networking documentation](https://docs.docker.com/engine/network/drivers/host/).

Your workstation's `127.0.0.1` is your workstation, so use the **VM's reachable
IP** in the browser. If the VM sits behind hypervisor NAT, configure a hypervisor
forward from your chosen workstation/host port to **VM port 8081**, or use a
reachable bridged VM address. This is separate from Docker port publishing.

If a VM firewall is active, permit TCP 8081 from the intended workstation/network.
For example, after substituting the actual workstation address on an existing UFW setup:

```bash
sudo ufw allow from WORKSTATION_IP to any port 8081 proto tcp
```

A browser SSH session uses the same UI port via WebSocket; it needs no extra
published port. Exported SuperPuTTY sessions connect directly from the workstation
to the exported device addresses, so those addresses need workstation reachability.

## Three separate connections

| Connection | Account / credential |
|---|---|
| Workstation → Ubuntu administration | Normal VM login, such as `archtop` |
| Manager → VM discovery and commands | `clab-discovery` + dedicated private key |
| Manager → lab device | Device username/password or assigned SSH profile |

The browser uses `http://10.150.2.213:8081` in this example; the VM connection form uses `127.0.0.1`. A working VM connection does not prove a router's password is correct.

---

# Part 12 — Deploy, discover and import labs {#part-12}

Copy a complete training project onto the VM, including its original `.clab.yaml`,
referenced startup configs and optional `.clab.yaml.annotations.json`. Put it under
your configured trusted root and load its required device images. Deploy from the
VM terminal using the actual topology filename, for example:

```bash
cd /etc/containerlab/YOUR_PROJECT
sudo containerlab deploy -t YOUR_LAB.clab.yaml
sudo containerlab inspect --all
```

The command deploys the training devices; the manager stays running independently.
Alternatively, use **Deploy New Lab → Lab Topologies** to browse an undeployed project and review its
deployment through the UI once the VM connection works.

In the manager:

1. Click **Refresh discovery**, or wait for the next 30-second check.
2. Click the discovered lab labelled **Ready to import**.
3. Review its name, node counts, files and warnings, then click **Import lab**.
4. Confirm the lab appears in the sidebar and its nodes have management addresses.
5. Review device credentials. Use the imported inventory accounts or add a NOS
   credential profile. Test one device after it finishes booting.
6. Open its SSH tab and run a configuration backup. Confirm the result appears
   in **Backup history**, then download a configuration to verify the workflow.

Discovery starts with the original YAML path returned by Containerlab inspect.
It also reads the adjacent annotations and the generated lab directory's
`ansible-inventory.yml` and `topology-data.json`. No running labs means there is
nothing to discover yet. Manual file upload is the fallback for missing/unreadable
files. Device running state alone does not mean the network OS is ready for SSH.

## Expected files for the example BGP lab

```text
/etc/containerlab/BGP_TheoryToPractice/
  BGP_TheoryToPractice.clab.yaml
  BGP_TheoryToPractice.clab.yaml.annotations.json
  clab-BGP_TheoryToPractice/
    ansible-inventory.yml
    topology-data.json
    ...device folders...
```

The original YAML path is the **Topology** column in `clab inspect --all`. The helper uses JSON inspection to find that path, then reads the corresponding original and generated files. It does not scrape the visual table or recursively search the whole disk.

| Input | What it provides |
|---|---|
| Original `.clab.yaml` | Lab definition, node kinds and links |
| Adjacent `.clab.yaml.annotations.json` | Saved map positions, shapes, notes and styling |
| Generated `ansible-inventory.yml` | Device endpoints and available inventory credentials |
| Generated `topology-data.json` | Deployed identities, short names and topology metadata |

Automatic import is preferred. Review the preview before saving; cancelling leaves the new lab unsaved. For existing saved labs, review **Sync from VM** when imported files change. Saved connection settings and history are retained, but a topology reimport can replace a manager-edited layout.

## Manual fallback

If automatic file reading fails, check **Discovery file details** for attempted paths and errors. Upload the original YAML, inventory and topology/annotations files through the relevant import forms. Annotations alone describe a drawing; supply YAML or topology data for wiring. Missing files, symlinks, oversized files and unusual unresolved definitions can require correction or manual import.

The helper accepts regular files without symlink components, with limits of 1 MiB per file, 8 MiB of file content per inspection and 100 labs. A root-owned generated inventory should work with the installed helper; do not make the lab tree world-writable to fix it.

---

# Part 13 — Node inventory, maps, SSH and backups {#part-13}

## Node inventory

Select a saved lab to see its nodes. Open **Node details** for the endpoint, credential/profile settings, latest SSH check and saved configuration history. Test a node after its NOS completes booting. Configure the correct backup driver for supported devices; generic SSH access does not imply configuration-backup support.

The list remains available even when a topology map is imported. The current MVP has no host CPU/memory utilization collector to configure.

## Map and right-click actions

Open **Topology** and import the corresponding annotations and topology if automatic import did not already supply them. Pan by dragging the background; use **Fit map**, zoom and expanded view.

Right-click a matched node for **SSH**, **Back up configuration** and **Node details**. Keyboard users can focus a node and press <kbd>Shift</kbd>+<kbd>F10</kbd>. Use <kbd>Esc</kbd> to dismiss the menu.

Map actions use the same node connection as the inventory. Unknown or ambiguous node names cannot receive live actions; correct the short-name mapping or reimport the matching topology data. Links show imported wiring, not measured live connectivity. Custom artwork and unsupported annotation types may differ from VS Code.

For older stored maps, reimport the original files to recover metadata that earlier importers did not retain. Refresh the browser after an image upgrade before diagnosing a stale right-click menu.

## Browser SSH

**SSH** opens a terminal in a new browser tab. **SSH all nodes** opens a launcher with individual links and an option to open ready sessions. Allow browser popups; the manager permits at most 32 concurrent terminals/checks. Closing the terminal or restarting the manager disconnects the session.

Browser SSH runs from the manager to the device. Test the saved management address, port and credentials from that network perspective. Action logs record session events, not a full transcript of typed commands and terminal output.

## Configuration backups

| Action | Scope |
|---|---|
| Per-node backup | The named node, regardless of its scheduled-selection checkbox |
| Regular lab backup / schedule | Nodes selected for the normal backup workflow |
| Back up all configs | Reviews all ready nodes, including unchecked ones; lists skipped nodes |
| Backup history download | Saved configuration snapshot from the selected job |
| Containerlab Save configurations | Separate host operation; behavior depends on the device kind |

Review readiness, choose a backup, then inspect its outcome in **Backup history** and download a configuration. Configure a schedule only after a manual backup works. Linked discovery pauses automatic work when its lab is unavailable; a running container alone is not proof of SSH readiness.

## SuperPuTTY session export

Choose **Export sessions** in the lab toolbar. The file is named `<lab-name>.xml` and organizes sessions as **Lab name → node short name**. Import it through SuperPuTTY's session import feature.

Saved profile/inventory usernames take priority. Known-kind fallbacks include `clab` for IOS-XR and `admin` for cJunosEvolved/cEOS. Check custom usernames before exporting. All inventory nodes are included, even when excluded from scheduled backups.

Passwords are omitted by default. **Include saved passwords as plain text** optionally adds available saved login passwords through PuTTY `-pw` arguments; it does not invent passwords or export private keys, passphrases or enable passwords. If the receiving SuperPuTTY/PuTTY setup does not accept the argument, enter the password interactively.

Exported sessions connect from the **workstation** to device addresses. Browser SSH working does not guarantee direct workstation routing to those addresses.

---

# Part 14 — Lab commands, VM projects and interactive draw.io {#part-14}

Open **Lab actions** or right-click a saved lab (keyboard: Shift+F10).

| Action | Behavior |
|---|---|
| Deploy / redeploy / destroy | Operates on the original VM topology; compatible cleanup variants are offered separately. Redeploy falls back to destroy then deploy when necessary. |
| Apply | Applies the original VM YAML when supported by installed Containerlab. |
| Start / stop / restart | Applies to every node in the selected lab. Stop retains containers; destroy removes them. |
| Inspect lab / inspect all | Readable table of topology, lab, node, kind/image, state/health and IPv4/IPv6. Failed or incomplete output remains visible for diagnosis. |
| Save configurations | Containerlab's kind-dependent save command. Manager backups are separate. |
| SSH all nodes | Opens a launcher tab with individual links and Open all ready sessions. Allow browser popups; at most 32 concurrent terminals/checks. |
| Favorite | Sorts this saved lab above other labs. |
| Interactive draw.io editor | Drag nodes or edit coordinates. Save layout updates the manager; Export full diagram downloads current positions without saving. |
| Delete undeployed VM YAML | Separate source deletion; refused while its deployment exists. Keeps a VM recovery copy. |
| Deploy New Lab → Lab Topologies | Same-tab landing page; choose Lab Topologies to browse .clab.yaml/.clab.yml files. Existing files are read-only. |
| New topology | Creates a new VM YAML after structure preview and confirmation; never replaces an existing file. |
| Add project / deploy project | Read an existing file, add a saved manager workspace, or separately review deployment. |
| Clone repository / popular labs | Optional HTTPS project acquisition, followed by review of files and separate deployment. |

## Interactive diagram and full export

There is one interactive diagram editor. It changes node positions; connections
follow the nodes. Full export contains editable nodes, connections, interface
labels, groups/shapes, notes, colors and positions. Contained nodes are grouped
with their surrounding annotation so they move together in draw.io. Router,
switch and server symbols use native editable diagram elements. Imported custom
icon artwork is represented by a generic network symbol.

The exported `.drawio` is uncompressed editable XML, following the
[draw.io document format](https://www.drawio.com/docs/reference/diagram-generation/).
Open it in diagrams.net or its desktop application. No external service is used
for export. Live SSH/backup actions stay in Node Manager and are not embedded in
the exported file. This is the manager's layout editor, not an embedded copy of
the full diagrams.net application. Structural topology changes are made in the
original VM YAML and imported/synced separately.

The topology header provides **SSH all nodes** and **Back up all configs**, also
in expanded view. Backup all reviews all ready nodes, including unchecked ones,
and lists unavailable/unsupported nodes it will skip. Per-node right-click SSH,
backup and details remain available. Inventory actions remain unchanged.

## Review commands before execution

Every submitted host command requires a preview and confirmation. Review tokens
expire after five minutes and bind the VM connection, original file digest and
relevant deployment state. A change requires another preview. Output and outcome
persist in operation history; interrupted jobs require inspection before retrying.
Lifecycle commands can interrupt node sessions. Manager backups/import changes
are blocked during an active lab operation.

Discovery matches imported lab names to the original VM topology path. Open **Deploy New Lab → Lab Topologies** to add an undeployed project. Sync from VM refreshes imported data
without overwriting saved connection settings. Saving a manager layout never
rewrites the original annotations file; a later topology import can replace it.

## Project roots and optional downloads

The root-owned `/etc/clab-manager/operations.json` records trusted roots, fixed
binaries and optional network permission. Defaults include `/etc/containerlab`
and `/srv/containerlab-node-manager/projects`. Add a real directory with:

```bash
sudo bash deploy/setup-operations.sh --lab-root /your/lab/projects
```

Browse is limited to these roots, rejects symlink paths and caps each folder at
500 entries. File reads are capped at 1 MiB. Topologies are trusted VM code:
Containerlab can execute hooks, mount files and pull images. Everyone who can
reach this manager's port has access to its enabled lab operations.

Optional cloning/catalog downloads require Git and network access on the VM:

```bash
sudo apt install -y git
sudo bash deploy/setup-operations.sh --allow-downloads
```

They are disabled by default. To revoke downloads or remove a trusted root, use
`sudoedit /etc/clab-manager/operations.json`; set `network` to false or remove the
root. Setup preserves existing roots and network permission unless you edit them.
Offline users can copy complete lab projects into a trusted root and browse them.

## Recovery after deleting an undeployed YAML

The operation result records a recovery copy under `.clab-manager-history` beside the source. Restore that file manually on the VM if needed. This is different from **Remove lab**, which affects manager storage only.

---

# Part 15 — Everyday container management {#part-15}

Run these from your installation directory. Restarting/stopping the manager does
not stop the training lab containers. It does disconnect active browser SSH sessions.

```bash
cd "$HOME/projects/v1.12.0"

# View status and recent logs
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml ps
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml logs --tail=100 backup-ui

# Restart only the manager
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml restart backup-ui

# Stop it deliberately; start it again when ready
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml stop backup-ui
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml start backup-ui
```

After an intentional stop, use `start`/`up` to resume it; `unless-stopped` does not
undo an intentional stop on reboot. [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/). Keep `deploy/image.env` when changing version
folders. It contains the selected image and listening settings, not SSH credentials.

---

# Part 16 — Upgrade without losing data {#part-16}

1. Back up the persistent directory using [Part 17](#part-17).
2. Pull the exact new release image while the old manager is still running.
3. Place the matching source/helper package in its new version folder. Check its
   VERSION against the image as in [Step 6.1](#part-6).
4. Copy `deploy/image.env` from the previous folder and change MANAGER_IMAGE to the
   new image. Retain any custom bind/port values.
5. Update helpers, keeping the existing authorized keys:

```bash
# Run from the NEW release's repository root.
sudo bash deploy/setup-discovery.sh --update-helper
sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
```

6. Repeat both helper verification commands with the **new version**, then run:

```bash
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml \
  up -d --no-build --pull never --force-recreate
```

Check the running version and refresh the browser. The fixed data path, Compose
project name and service name retain your workspace across version folders. Do not
generate a new SSH key for an ordinary upgrade. A plain `docker restart` does not
replace an existing container with a newly pulled image.

## Source-build upgrades

For a source-build installation, put the new release in its own version folder, retain any customized `clab-backup-ui/.env`, and run that release's `deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab`. Use its source Compose file for status checks. Do not substitute the Hub image Compose command without intentionally switching installation methods.

## Release checks

Confirm the image version, both installed helper versions, retained labs/credentials, one browser SSH session and one backup download. Refresh the browser to load the release's frontend assets. Keep the prior image and a pre-upgrade data archive until these checks pass; a downgrade may require restoring the matching earlier data snapshot.

---

# Part 17 — Backups, recovery and manager-only removal {#part-17}

Close terminals and let jobs finish, then stop the manager for a consistent copy.
From the installation directory:

```bash
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml stop backup-ui
sudo install -d -m 0700 /srv/containerlab-node-manager/archive
sudo sh -c 'umask 077; tar -czf "/srv/containerlab-node-manager/archive/manager-$(date -u +%Y%m%dT%H%M%SZ).tgz" -C /srv/containerlab-node-manager data'
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml start backup-ui
```

Copy the archive off the VM and retain the image reference and install settings.
The archive contains the encryption key and credentials, so keep it private.
It covers manager data, not the original VM projects or device images; back those
up separately if you need to recreate the entire training VM.

To recover, stop the manager, preserve the existing data directory separately,
and extract the saved archive under `/srv/containerlab-node-manager` so it restores
`data/` with its original numeric ownership. Keep `state.key` and `state.enc`
together, verify UID/GID 10001 and directory mode 700, then start the matching
manager image. A replacement VM also needs the helper/account/key installation.

**Remove lab** removes one saved workspace. **Start fresh** deletes all manager
workspaces and backup files after confirmation while retaining VM connection
settings. Neither is required for an image upgrade. Neither destroys live labs.

## Choose the correct removal action

| Action | Manager data | VM lab/source files |
|---|---|---|
| Stop/recreate manager container | Retained in the bind mount | Unchanged |
| Remove lab | Removes one saved workspace/history entries; backup files and audit logs remain | Unchanged |
| Clear exclusion | Allows discovery to offer that lab again; does not import it | Unchanged |
| Start fresh, type `RESET` | Clears workspaces, device credentials, schedules, backups, jobs/logs and exclusions; retains VM connection and `state.key` | Unchanged |
| Lab Stop | Workspace retained | Stops the selected lab's nodes; containers remain |
| Lab Destroy | Workspace retained | Removes the selected deployment; cleanup variants have additional reviewed effects |
| Delete undeployed VM YAML | Separate operation | Removes original source only when undeployed; saves a recovery copy |

After **Remove lab**, the default exclusion prevents immediate reappearance. Right-click the excluded lab and choose **Clear exclusion** to test discovery again. The next import still needs confirmation.

Close active terminals and wait for jobs before **Start fresh**. It is not part of a normal upgrade. If interrupted by disk/permission problems, fix the cause and retry or restart; the reset journal resumes the operation.

## Rebuilding an entire VM

A manager data archive is only one part of recovery. Retain the complete VM projects, referenced startup configs, device images, manager image/version, helper source package and required SSH public keys. Reinstall the host helpers on the replacement VM and verify its new host fingerprint. Restoring only `state.enc` without `state.key` cannot recover saved credentials.

---

# Part 18 — VM connection repair, lost keys and multiple keys {#part-18}

## Repair helpers without rebuilding the image

```bash
cd "$HOME/projects/v1.12.0"
sudo bash deploy/setup-discovery.sh --update-helper
sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
sudo /usr/local/sbin/clab-manager-inspect | python3 deploy/verify-helper.py 1.12.0
printf '%s\n' '{"mode":"capabilities"}' | sudo /usr/local/sbin/clab-manager-operate | python3 deploy/verify-operations.py 1.12.0
```

The verifiers display only compatibility information. Raw discovery output can
contain inventory passwords; do not paste it into public logs or support messages.

## Replace a lost private key and revoke old keys

Use your normal VM administrator login. Generate a new pair on the workstation
and copy its `.pub` file as in first setup, using a new filename. On the VM:

```bash
cd "$HOME/projects/v1.12.0"
sudo bash deploy/setup-discovery.sh "$HOME/clab-manager-replacement.pub"
sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
```

Passing a public key to setup-discovery **replaces all existing key entries for
the dedicated clab-discovery account**. It does not alter your normal VM user's
keys. The second command restores the operations gateway and sudo permissions.
In **VM connection**, select the new matching private key and passphrase, then
save and test. This changes client authentication; it does not require trusting
a new VM host fingerprint. Existing authenticated SSH connections must be closed
if you need revocation to take effect immediately.

## Multiple keys

One manager has one configured VM connection and one active credential. Multiple
public keys on the VM allow different clients to authenticate to the same helper
account; they do not make the manager rotate between keys.

For this multi-engineer design, each isolated VM should have its own pair. If you
need two keys on one VM, install operations first and use:

```bash
sudoedit /home/clab-discovery/.ssh/authorized_keys
```

Retain the existing entry and append one line for each additional public key,
using exactly this prefix followed by the entire `.pub` file content:

```text
restrict,command="/usr/local/sbin/clab-manager-gateway" ssh-ed25519 AAAA... engineer-name
```

Replace `AAAA...` with the actual public key, not a private key. Each entry must
be one line. Keep the file root-owned with mode 644 and `.ssh` mode 755, as set by
the installer. Future normal upgrades retain these entries. To revoke one key,
remove its line; to revoke all old keys, use the replacement procedure above.

## VM host fingerprint changes

Client keys authenticate the manager. Host keys identify the VM; they are different keys. On the VM console, inspect the relevant SSH host public key:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

If SSH negotiated RSA/ECDSA, inspect that host public key instead. After confirming an expected change, use **Trust a replacement SSH host key** in VM connection and save/test. Replacing the manager's client key does not fix a VM host-fingerprint mismatch.

## Where connection files live

| Location | Contents |
|---|---|
| Workstation private key file | Original private key you generated |
| `/home/clab-discovery/.ssh/authorized_keys` | Restricted public key entries accepted by the VM |
| `/usr/local/sbin/clab-manager-gateway` | Routes SSH requests to discovery or structured operations |
| `/usr/local/sbin/clab-manager-inspect` | Discovery and file-reading helper |
| `/usr/local/lib/clab-manager/` | Installed Python helpers |
| `/etc/sudoers.d/clab-manager-discovery` | Exact helper commands allowed through sudo |
| `/etc/clab-manager/operations.json` | Trusted project roots and optional download permission |
| `/srv/containerlab-node-manager/data/state.enc` | Encrypted lab and VM settings, including uploaded private key |
| `/srv/containerlab-node-manager/data/state.key` | Encryption key; retain alongside state.enc |
| `/srv/containerlab-node-manager/data/backups/` | Saved configuration files and history |

The container uses UID/GID `10001:10001`; its data directory should have mode
`700`. Run `sudo bash deploy/setup-vm.sh` to create/repair this directory, then
check `sudo stat -c '%u:%g %a %n' /srv/containerlab-node-manager/data`.
Do not use chmod 777. Keep the entire data directory when upgrading or backing up.

---

# Part 19 — Troubleshooting and lessons from the first install {#part-19}

| Symptom | Next step |
|---|---|
| MANAGER_IMAGE is required / image not found | Set the exact local repository:tag in deploy/image.env; confirm with docker image ls. |
| Bind source path does not exist | Run setup-vm.sh; verify the exact persistent path. |
| Permission denied writing /data | Verify 10001:10001 ownership and mode 700. For migrated data, check ownership of existing files too; setup-vm repairs the directory, not every old file. |
| Address already in use | Check `sudo ss -lntp` for port 8081 and stop a duplicate manager, or change UI_PORT and recreate the service. |
| Local HTTP 200 but workstation cannot open UI | Check VM IP, UI_BIND, firewall and hypervisor NAT forwarding. Docker -p is not used with host networking. |
| UI opens but discovery cannot connect | Check SSH service/port, clab-discovery username, private key and passphrase. |
| Shell denied during manual SSH testing | Expected for the restricted account. Use the manager's connection test. |
| Lab detected but files will not import | Run helper verifiers; ensure image/helpers match and original/generated lab files exist. |
| Discovery works but lab commands fail | Install setup-operations.sh, use helper mode and add the actual project root. |
| No discovered labs | Deploy a lab on this VM, check inspect --all, refresh discovery and clear any matching exclusion. |
| Nodes discovered but SSH/backup fails | Wait for NOS boot, verify credentials/driver and management address/port. |

For fingerprint changes, lost-key replacement, multiple keys and detailed helper
repair, use [VM connection repair](#part-18).

## VM connection diagnostics

| Symptom | Check / fix |
|---|---|
| Cannot reach the UI | Check Compose status and logs. Browse VM_IP:8081, and check VM firewall/NAT forwarding for TCP 8081. |
| VM connection refused or timed out | Verify the address and SSH port; run `sudo systemctl status ssh` and `sudo ss -lntp`. Supplied host-network Compose can use 127.0.0.1; bridge containers cannot use that address to reach the VM. |
| Authentication failed | Use username clab-discovery, the private file without .pub and its correct passphrase. Compare its public fingerprint with installed authorized_keys using ssh-keygen -lf. Replace lost keys using the procedure above. |
| An interactive SSH test refuses a shell | Expected for the helper account. It only accepts fixed discovery/operation requests; use Save and test connection. |
| Fingerprint mismatch | Verify the VM's host key independently. If the VM was rebuilt and the new key is expected, check Trust a replacement SSH host key in VM connection, then save and test. Do not rotate the client key to solve this. |
| Lab discovered but automatic import asks for helper update | Repair both helpers using Part 18; a Hub image installation does not need a source rebuild. Refresh discovery and retry the lab. |
| Read/import permission error | Use Installed discovery and file helper; it can read root-owned lab artifacts. Direct mode uses the selected account's ordinary SFTP permissions and cannot read files that account cannot access. |
| Commands unavailable or operations helper error | Enable/repair setup-operations and include the lab's trusted root. The helper tests the installed Containerlab command support. Older Containerlab versions may lack some commands. |
| Path outside trusted roots | Run setup-operations with `--lab-root /actual/project/root`. Use the parent directory containing your lab projects, not filesystem root. |
| Cannot browse a symlink path | Use a real directory path. Helpers deliberately refuse symlink components. |
| Save fails / Start fresh cannot finish | Check free disk space and data ownership. Repair permissions, then retry Start fresh or restart; its journal resumes the reset. |
| Deployed lab missing | Run `sudo containerlab inspect --all --format json` on the same VM and check VM connection is enabled. Refresh discovery; clear any matching exclusion. |



## Errors seen in the installation walkthrough

| Message / symptom | Cause and correction |
|---|---|
| Cannot find the Proxmox VM ID | Run `qm list` in the Proxmox host shell; match the VM name. |
| Public key does not exist at `$HOME/clab-manager-discovery.pub` | Key generation happened in another directory. Set `KEY_PUB` to the actual `.pub` path, then install it. |
| First launch requires a public key | The restricted helper account was not initialized. Complete Part 8 and Part 9; the keyless source launcher is for an already configured account. |
| Compose says service is not running during `exec` | The earlier launch failed. Read that failure, fix it, run `up`, then verify `ps` before `exec`. |
| `docker build` requires an argument | Include the build context: `./clab-backup-ui` from the repo root or `.` from its Dockerfile folder. |
| `[1]+ Stopped less ...` | Ctrl+Z suspended the viewer. Run `fg`, then press `q`. |
| Lab discovered but upload is still manual | Verify both installed helpers match the image; image replacement alone does not update host file-transfer support. |
| Old instructions request a UI access token | That login was removed in 1.12.0. Check the actual running version instead of searching for a new token. |
| Map layout or right-click behavior looks like the old version | Verify the running image, refresh browser assets and reimport original map files if earlier imports discarded metadata. |
| VS Code extension sees permission errors | Check both groups in a fresh remote session and write permissions on the exact project directory. |
| Junos/EVO remains in startup waits | Check device logs, `/dev/kvm`, guest CPU exposure and the image's resource/boot requirements. |
| Disk still appears around 100 GiB | Compare `vgs`, `lvs` and `df`; the LV and filesystem are separate expansion steps. |

## A useful support report

Include the manager version, Containerlab version, Compose status, helper verification results, the specific UI error and whether ordinary node SSH works. Avoid sending private keys, raw inventories or full discovery JSON: they can contain credentials. Use the provided verifiers to report helper compatibility without dumping file contents.

The supplied terminal log demonstrates an earlier 1.10.0 installation and its key-path correction. It is not evidence that every 1.12.0 step was run on a fresh Linux VM.

---

# Part 20 — Airgapped installation and handoff checklist {#part-20}

Bring the manager image, matching repository/source package, required VM packages
and network device images onto the VM before starting. On a connected staging
machine, `docker image save` exports the manager image; `docker image load` imports
it on the VM. This guide's Compose launch uses only the local image and performs
no build. OS installation, Containerlab installation and training-image acquisition
still need offline packages or approved internal mirrors. Clone/catalog downloads
are optional and disabled by default.

## Transfer the prebuilt manager image

**Connected staging machine:**

```bash
docker pull archtop/clab-backup:1.12.0
docker image save -o clab-backup-1.12.0.tar archtop/clab-backup:1.12.0
```

Transfer the archive, matching repository files and other offline prerequisites. **Ubuntu VM**, from the transfer directory:

```bash
sudo docker image load -i clab-backup-1.12.0.tar
```

Continue with Part 6's version check. Image-based Compose uses `--pull never` and has no build step. Optional online project downloads remain disabled unless explicitly enabled.

## Engineer handoff record

| Record | Value to fill in |
|---|---|
| Engineer / VM owner | |
| Proxmox node and VM ID | |
| Ubuntu hostname / address | |
| Manager URL | |
| Manager image tag / digest | |
| Matching host-helper version | |
| Installation method and source folder | |
| Trusted lab project roots | |
| VM connection public-key fingerprint | |
| Private-key storage location — do not paste the key | |
| Data archive location / last successful restore check | |

## Completion checklist

- [ ] Workstation reaches Ubuntu over SSH and the manager at TCP 8081.
- [ ] Nested KVM works if required by the training devices.
- [ ] Root filesystem has the intended capacity.
- [ ] Docker, Compose and Containerlab work on the VM.
- [ ] Required network device images are available locally.
- [ ] Source package, image and both installed helpers match.
- [ ] Manager data is outside version/lab folders, owned by `10001:10001`, mode `700`.
- [ ] VM connection reports connected using the installed helper.
- [ ] A deployed lab is discovered; its automatic import preview has been confirmed.
- [ ] Node inventory and topology names map correctly.
- [ ] One node opens through inventory SSH and map right-click SSH.
- [ ] A configuration backup succeeds and its saved file downloads.
- [ ] SuperPuTTY and full editable draw.io export have been checked where used.
- [ ] Manager restart retains the workspace and credentials.
- [ ] A complete manager data archive has been copied off the VM.

## Documentation baseline

Prepared for 1.12.0 using the existing Wiki.js host-build page, the supplied HTML installation walkthrough and the repository's setup, VM connection, lab operations and node-feature guides. Historical failures were turned into corrections rather than copied as steps to repeat. Application procedures were checked against the local release documentation and deployment configuration; a complete fresh Linux VM installation was not performed in the Windows authoring workspace.

## Related references

- [Project repository](https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2)
- [Wiki.js Markdown editor](https://docs.requarks.io/en/editors/markdown)
- [Docker Ubuntu installation](https://docs.docker.com/engine/install/ubuntu/)
- [Containerlab installation](https://containerlab.dev/install/)
- [Containerlab VS Code extension](https://containerlab.dev/manual/gui/vsc-extension/)
- [Linux nested KVM](https://docs.kernel.org/virt/kvm/x86/running-nested-guests.html)
- [WinSCP administrative SFTP](https://winscp.net/eng/docs/faq_su)
{.links-list}
