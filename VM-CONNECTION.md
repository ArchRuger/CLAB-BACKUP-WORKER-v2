# VM connection — setup and recovery, 1.12.0

The manager runs independently of your labs. Its VM connection is an SSH connection
to the Linux machine running Containerlab. It discovers deployed labs and reads
their files. With operations enabled, the same connection runs reviewed lab commands.
Node SSH uses the device credentials from inventory or credential profiles.

For a completely empty Ubuntu VM, start with [FRESH-VM-GUIDE.md](FRESH-VM-GUIDE.md)
to install Docker, Compose, Containerlab and OpenSSH. Commands below run on that
VM unless explicitly marked Workstation. Versioned source lives in
`~/projects/v1.12.0`, with `deploy/` and `clab-backup-ui/` directly inside it.
Persistent data lives outside every version folder at
`/srv/containerlab-node-manager/data`.

## First connection

1. On your workstation, generate a dedicated key pair with OpenSSH. Choose a
   passphrase if desired. Copy only the public key to your VM using its normal login:

```text
ssh-keygen -t ed25519 -f clab-manager-discovery
scp clab-manager-discovery.pub YOUR_VM_USER@VM_IP:clab-manager-discovery.pub
```

2. On the VM, install the helper, build the image and launch the manager:

```bash
cd "$HOME/projects/v1.12.0"
sudo bash deploy/start-manager.sh "$HOME/clab-manager-discovery.pub" --enable-operations --lab-root /etc/containerlab
```

This first-launch command refuses to replace an existing account's key. For an
already configured VM, use the upgrade command below without a public key.
The `.pub` file is public. The file without `.pub` is private; keep it on your
workstation and select it in the manager. If you generated the pair on the VM,
transfer the private file to your workstation using your normal file transfer.

3. Open `http://VM_IP:8081`. No workspace login is required. Open **VM connection**:

| Setting | Recommended value |
|---|---|
| VM address | `127.0.0.1` when using supplied Linux host-network Compose on the same VM |
| SSH port | `22`, or the VM SSH server's configured port |
| VM username | `clab-discovery` |
| Authentication | SSH private key |
| SSH private key | Select `clab-manager-discovery`, without `.pub` |
| Key passphrase | The passphrase chosen during generation, if any |
| Inspection method | Installed discovery and file helper |
| Enable automatic discovery | Checked |

Choose **Save and test connection**. The first connection saves the VM SSH host
fingerprint. On the VM, compare it with `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`
(the negotiated host key may instead be RSA/ECDSA). Subsequent fingerprint changes
block connection until explicitly accepted in the UI.

The manager checks every 30 seconds. A detected lab appears as Ready to import.
Click it, review the files and counts, then choose **Import lab**. Cancelling
does not save a workspace. Use manual file upload if source files are unavailable.

## What is stored where

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

## Upgrading without changing keys

Extract the new source into the new version folder. Then:

```bash
cd "$HOME/projects/v1.12.0"
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
sudo docker compose -f clab-backup-ui/compose.yml exec backup-ui python -c 'from app import __version__; print(__version__)'
sudo docker compose -f clab-backup-ui/compose.yml logs --tail=50 backup-ui
```

The script refreshes both helpers, verifies versions, prepares storage, performs
a fresh no-cache build and recreates the Compose service. It retains installed
public keys and the manager's private key/settings. A Docker build alone cannot
update a helper installed on the VM. No new key pair is needed for upgrades.
Refresh your browser after upgrading. The expected version is **1.12.0**.

To repair only the host helpers, without building an image:

```bash
cd "$HOME/projects/v1.12.0"
sudo bash deploy/setup-discovery.sh --update-helper
sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
sudo /usr/local/sbin/clab-manager-inspect | python3 deploy/verify-helper.py 1.12.0
printf '%s\n' '{"mode":"capabilities"}' | sudo /usr/local/sbin/clab-manager-operate | python3 deploy/verify-operations.py 1.12.0
```

The verifiers display only compatibility information. Raw discovery output can
contain inventory passwords; do not paste it into public logs or support messages.

## Replacing a lost private key and revoking old keys

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

## Troubleshooting

| Symptom | Check / fix |
|---|---|
| Cannot reach the UI | Check Compose status and logs. Browse VM_IP:8081, and check VM firewall/NAT forwarding for TCP 8081. |
| VM connection refused or timed out | Verify the address and SSH port; run `sudo systemctl status ssh` and `sudo ss -lntp`. Supplied host-network Compose can use 127.0.0.1; bridge containers cannot use that address to reach the VM. |
| Authentication failed | Use username clab-discovery, the private file without .pub and its correct passphrase. Compare its public fingerprint with installed authorized_keys using ssh-keygen -lf. Replace lost keys using the procedure above. |
| An interactive SSH test refuses a shell | Expected for the helper account. It only accepts fixed discovery/operation requests; use Save and test connection. |
| Fingerprint mismatch | Verify the VM's host key independently. If the VM was rebuilt and the new key is expected, check Trust a replacement SSH host key in VM connection, then save and test. Do not rotate the client key to solve this. |
| Lab discovered but automatic import asks for helper update | Run the normal start-manager command from the current source folder, or repair both helpers above. Refresh discovery and retry the lab. |
| Read/import permission error | Use Installed discovery and file helper; it can read root-owned lab artifacts. Direct mode uses the selected account's ordinary SFTP permissions and cannot read files that account cannot access. |
| Commands unavailable or operations helper error | Enable/repair setup-operations and include the lab's trusted root. The helper tests the installed Containerlab command support. Older Containerlab versions may lack some commands. |
| Path outside trusted roots | Run setup-operations with `--lab-root /actual/project/root`. Use the parent directory containing your lab projects, not filesystem root. |
| Cannot browse a symlink path | Use a real directory path. Helpers deliberately refuse symlink components. |
| Save fails / Start fresh cannot finish | Check free disk space and data ownership. Repair permissions, then retry Start fresh or restart; its journal resumes the reset. |
| Deployed lab missing | Run `sudo containerlab inspect --all --format json` on the same VM and check VM connection is enabled. Refresh discovery; clear any matching exclusion. |

File discovery starts from the topology path reported by inspect. For example,
`/etc/containerlab/BGP_TheoryToPractice/BGP_TheoryToPractice.clab.yaml` leads to the
adjacent `.annotations.json` and generated
`clab-BGP_TheoryToPractice/ansible-inventory.yml` and `topology-data.json`.
These files must exist on the VM; manual uploads remain available if they do not.

For a credential-preserving edit to the same VM account, leave credential fields
blank. Switching accounts or replacing a passphrase requires supplying the matching
credential again. The UI never displays saved private keys or passwords.

## Start fresh versus Remove lab

**Remove lab** removes one saved workspace and its history entries. Its saved
backup files and audit logs remain on disk. A default exclusion prevents immediate
rediscovery; right-click that excluded lab and choose **Clear exclusion** to forget it.

**Manager settings → Start fresh** requires typing RESET. It clears all imported
labs, device credentials, schedules, backup files, job/operation history, logs and
exclusions. It retains the VM connection, its authentication and trusted fingerprint,
and state.key. It never destroys a deployment, deletes a VM project, or removes
the helper account. Close terminals and wait for jobs first. Deployed labs will
be offered for import again and still require confirmation. New audit entries
can appear immediately after the reset as the manager resumes work.
