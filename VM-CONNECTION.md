# VM connection — password setup and recovery, 1.14.0

Create the `clab-discovery` password **on the VM during host setup, before launching
the manager**. The image build contains no user password. Each VM has its own
user-created password, retained across reboots and manager upgrades.

The manager connects to the Containerlab VM over SSH using this password. Device
SSH and backup credentials are configured separately and retain their existing options.

## First launch or migration from an SSH key

Run these commands in an interactive terminal using your normal VM administrator
account. Start in the extracted source folder containing `deploy/` and `clab-backup-ui/`.
Docker, Compose, Containerlab, Python 3, sudo and a running OpenSSH service are required;
see [Fresh VM guide](FRESH-VM-GUIDE.md) for installation.

```bash
cd "$HOME/projects/v1.14.0"
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
```

Setup prompts twice for the new `clab-discovery` password without displaying it.
This is separate from sudo's prompt for your administrator password. Use a unique
password. There is no default or generated password, command-line password argument,
environment variable, or password file. Setup then verifies helpers, builds the image,
and recreates the manager with its existing persistent data. Omit `--enable-operations`
for discovery/import only on a new VM.

For an existing key-based installation, this converts the dedicated account to
password authentication and clears its old `authorized_keys` entries. The new manager
does not use saved client keys; saving the password removes the old private key and
passphrase from its encrypted host settings. Existing SSH sessions are not terminated
by the SSH reload. Other VM accounts and their SSH authentication settings are preserved.

Open `http://VM_IP:8081`, then **VM connection**:

| Setting | Value |
|---|---|
| VM address | `127.0.0.1` for the supplied Linux host-network deployment |
| SSH port | `22`, or your configured SSH port |
| VM username | `clab-discovery` |
| VM password | The password you just created in the VM terminal |
| Inspection method | Installed discovery and file helper |
| Automatic discovery | Enabled |

Choose **Save and test connection**. The manager saves the password encrypted and
never returns it to the browser. Reopening the dialog shows an empty password field;
leave it blank to retain the saved password for the same address, port and account.
Changing any of those requires entering the password again. Saving here updates the
manager's credential; it does not change the Linux account password.

On first connection, compare the saved host fingerprint against the VM's host key:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

The negotiated key may instead be RSA/ECDSA. SSH server identity keys remain required;
this change removes client authentication keys. Migrating the password on the same
VM preserves its trusted fingerprint. Later fingerprint changes block connection
until independently verified and explicitly accepted in the UI.

## Persistent storage

| Location on VM | Contents |
|---|---|
| `/etc/shadow` | Linux account password hash, managed by `passwd` |
| `/srv/containerlab-node-manager/data/state.enc` | Encrypted manager settings, including the saved VM password |
| `/srv/containerlab-node-manager/data/state.key` | Key needed to decrypt settings; retain alongside state.enc |
| `/srv/containerlab-node-manager/data/backups/` | Saved device configurations |
| `/etc/ssh/clab-manager-password.conf` | Password-only, restricted SSH policy for clab-discovery |
| `/etc/ssh/sshd_config` | Includes the account policy at its end |
| `/usr/local/sbin/clab-manager-gateway` | Allows only fixed discovery and structured operation requests |
| `/etc/sudoers.d/clab-manager-discovery` | Exact allowed helper commands |
| `/etc/clab-manager/operations.json` | Trusted lab roots and optional download permission |

Compose mounts the manager data directory at `/data`. Keep this entire directory,
including its encryption key, when recreating or upgrading the container. Expected
ownership/mode is `10001:10001 700`; `sudo bash deploy/setup-vm.sh` prepares it.
No password is baked into a Docker image. A rebuilt VM requires account setup again;
copying manager data alone does not recreate a Linux account.

The SSH policy forces the gateway and disables public-key authentication, interactive
SSH shells, PTYs, forwarding and user RC scripts for this account. The installer
validates syntax and effective policy before reload and restores the previous SSH
configuration on failure or a cancelled password prompt. Earlier conflicting Match
rules cause setup to fail with a review message. Its directives follow
[OpenSSH's SSH server configuration reference](https://man.openbsd.org/sshd_config).

## Upgrades and password changes

Routine upgrades use the same `start-manager.sh` command. Once an account password
exists, setup retains it without prompting. It also preserves manager data and
previously enabled operations. A Docker build alone cannot install host helpers.

To create/migrate the account or repair helpers without building:

```bash
sudo bash deploy/setup-discovery.sh
sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
```

`--update-helper` remains an alias for setup, including password migration if needed.
To change or recover a forgotten password, use your normal VM administrator account:

```bash
sudo bash deploy/setup-discovery.sh --reset-password
```

Then enter the new password in **VM connection** and save/test. The previous manager
credential cannot reconnect until updated. `start-manager.sh --reset-password` also
resets the password before building and launching. No SSH key generation or upload
is required.

## Troubleshooting

| Symptom | Check / fix |
|---|---|
| Password setup required | Run setup-discovery.sh in the VM terminal, then save the password in VM connection. |
| Authentication failed | Use the same password set for clab-discovery; reset it through the administrator command above if forgotten. |
| Setup needs an interactive terminal | Run directly from a VM console or interactive administrator SSH session. Passwords are not accepted from piped input. |
| Conflicting SSH account policy | Review earlier Match rules and global PermitUserEnvironment with your VM administrator. The installer requires user environment processing disabled. |
| Connection refused / timed out | Check address/port, `sudo systemctl status ssh`, firewall and VM networking. |
| Interactive SSH / SFTP denied | Expected for clab-discovery. Select the installed helper and use Save and test connection. Direct SFTP mode requires another existing account with ordinary file access. |
| Fingerprint changed | Verify the VM's host key independently before trusting a replacement in the UI. Password resets do not fix host identity changes. |
| Helper outdated / commands unavailable | Run start-manager.sh from the current release source with the required lab roots and operations enabled. |
| Save failed | Check free disk space and data ownership; retain state.key and state.enc. |

**Manager settings → Start fresh** retains the VM connection, password, fingerprint
and state.key. **Remove lab** affects only the selected saved workspace. Neither
operation changes the VM account password. New labs still require import confirmation.
