> Historical guide for earlier releases. For 1.14.0, use [VM-CONNECTION.md](VM-CONNECTION.md)
> and [FRESH-VM-GUIDE.md](FRESH-VM-GUIDE.md). Their password setup replaces the SSH client key steps below.
> Build 1.14.0 from source; no new registry image is claimed by this delivery.

# Pulled the Docker image? Start here

This guide takes a fresh **Ubuntu Server 24.04 LTS VM** from an already downloaded
Containerlab Node Manager image to a persistent manager with lab discovery,
browser SSH and configuration backups. The manager and Containerlab run on the
same VM, independently of each other. Each engineer gets their own VM.

Docker Engine is already installed and able to run the image. You need a normal
VM administrator account with `sudo`. Commands below run in **the VM terminal**
unless labelled **Workstation**. Use rootful Docker Engine with its normal UID
mapping; rootless Docker and user-namespace remapping need a different ownership setup.

**Release image:** `archtop/clab-backup:1.12.0`

**You do not build the application in this guide.** The pulled image supplies it.
The current image does not include the host installation scripts, so download
the matching repository/source package for those scripts and the Compose file.
The image does not install Docker, Containerlab, SSH or the helper account on your VM.

## What you will have when finished

| Component | Location / purpose |
|---|---|
| Browser UI | `http://VM_IP:8081` |
| Manager container | Standalone Compose service `backup-ui` |
| Saved manager data | `/srv/containerlab-node-manager/data`, outside all lab/version folders |
| Host helper account | `clab-discovery`, reached over SSH |
| Lab projects | For example, `/etc/containerlab/<project>/` |
| Install files for this release | `~/projects/v1.12.0/` |

No UI login is required in 1.12.0. Give access to this port only to the intended
engineers: users reaching the UI can access its enabled lab operations.

## 1. Identify and verify the image you pulled

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
For an entirely unconfigured machine, [FRESH-VM-GUIDE.md](FRESH-VM-GUIDE.md) covers
Docker installation; return here to run the pulled image instead of building one.

## 2. Prepare the VM's SSH server and Containerlab

```bash
sudo apt update
sudo apt install -y ca-certificates curl git openssh-server python3 sudo
sudo systemctl enable --now ssh
sudo systemctl enable --now docker
```

Check whether Containerlab is installed:

```bash
containerlab version
```

If it is missing, download and review the official installer, then run it:

```bash
curl -fsSL https://get.containerlab.dev -o /tmp/install-containerlab.sh
less /tmp/install-containerlab.sh
sudo bash /tmp/install-containerlab.sh
containerlab version
sudo containerlab inspect --all --format json
```

Press `q` to leave `less`. No running labs is a normal result on a new VM.
See [Containerlab installation](https://containerlab.dev/install/) for package or
offline installation. Network device images are separate from the manager image;
load the images required by your training lab before deploying it.

## 3. Get matching host setup files

```bash
mkdir -p "$HOME/projects"
cd "$HOME/projects"
git clone https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2.git v1.12.0
cd v1.12.0
cat clab-backup-ui/VERSION
```

The folder name does not select a Git release. Confirm that the version printed
by the repository **matches the image version from step 1**. If GitHub still has
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

## 4. Create persistent storage

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
[STANDALONE-SETUP.md](STANDALONE-SETUP.md) before starting a new manager. Run only
one manager process/container against a data directory.

## 5. Create the VM connection key

**Workstation** — in a folder where you can retain the key files:

```text
ssh-keygen -t ed25519 -f clab-manager-discovery
scp clab-manager-discovery.pub YOUR_VM_USER@VM_IP:clab-manager-discovery.pub
```

Replace `YOUR_VM_USER` and `VM_IP` with your normal administrator login and VM
address. Choose a key passphrase when prompted, or press Enter for no passphrase.

| File | Where it goes |
|---|---|
| `clab-manager-discovery.pub` | Public key copied to the VM for installation |
| `clab-manager-discovery` | Private key retained on your workstation and selected in the manager UI |

The key is for the manager's connection to the VM. Device usernames/passwords
are configured separately after importing a lab.

## 6. Install and verify the host helpers

**VM** — this key-install command is for the fresh account described by this guide:

```bash
cd "$HOME/projects/v1.12.0"
sudo bash deploy/setup-discovery.sh "$HOME/clab-manager-discovery.pub"
sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
```

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
fails, repair the helper before continuing; see [VM-CONNECTION.md](VM-CONNECTION.md).

If projects live elsewhere, add their actual parent directory with
`sudo bash deploy/setup-operations.sh --lab-root /your/project/directory`.
Use real directories without symlink components. The manager needs no Docker
socket mount and no mount of the host lab directories; helpers access them over SSH.

## 7. Launch the downloaded image with Compose

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

## 8. Open the UI and configure the VM connection

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

### Why there is no Docker port mapping

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

## 9. Deploy and import your first training lab

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
Alternatively, use **VM projects** to browse an undeployed project and review its
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

## Everyday commands

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

## Upgrading to another pulled image

1. Back up the persistent directory as described below.
2. Pull the exact new release image while the old manager is still running.
3. Place the matching source/helper package in its new version folder. Check its
   VERSION against the image as in step 1.
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

## Back up and recover your manager data

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

## Troubleshooting the first launch

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
repair, use [VM-CONNECTION.md](VM-CONNECTION.md).

## Airgapped VMs

Bring the manager image, matching repository/source package, required VM packages
and network device images onto the VM before starting. On a connected staging
machine, `docker image save` exports the manager image; `docker image load` imports
it on the VM. This guide's Compose launch uses only the local image and performs
no build. OS installation, Containerlab installation and training-image acquisition
still need offline packages or approved internal mirrors. Clone/catalog downloads
are optional and disabled by default.

## Documentation validation

This guide is checked against the 1.12.0 Dockerfile, helper installers and
application settings. The image-based Compose file deliberately omits build
configuration. The release image reference supplied for this guide is `archtop/clab-backup:1.12.0`. A complete fresh Linux VM install has not been executed
in the Windows development workspace.
