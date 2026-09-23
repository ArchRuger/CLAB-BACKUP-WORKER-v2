# VM connection — password setup and recovery

The manager connects to the Containerlab VM over SSH as the restricted account
`clab-discovery`, with a password you create **on the VM during host setup, before
the manager starts**. The image build contains no user password. Each VM has its own
user-created password, retained across reboots and manager upgrades. Device SSH and
backup credentials are configured separately and retain their existing options.

## First launch

The guided installer (`bash "$HOME/projects/clab-manager/deploy/install.sh"`)
creates the account and asks for the password during its third phase. The launcher
it runs does the same on its own, from any directory, in an interactive terminal as
your normal VM administrator account:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/start-manager.sh" --enable-operations --lab-root /etc/containerlab
```

Setup prompts twice (`New password:`, `Retype new password:`) for the new
`clab-discovery` password without displaying it; the two entries must match and must
not be empty. This is separate from sudo's prompt for your administrator password. Use
a unique password. There is no default or generated password, command-line password
argument or environment variable. Setup then runs `retire-telemetry.sh --no-recreate`
to tear down any leftover telemetry stack, verifies helpers, refreshes the capture
stack, builds the image and recreates the manager with its existing persistent data.
Omit `--enable-operations` for discovery/import only.

### The prefilled VM connection

Right after it sets the password, setup hands the connection to the manager once, so
nothing has to be typed again in the browser. It writes a one-time seed,
`/srv/containerlab-node-manager/data/host-bootstrap.json` (mode `0600`, owner
`10001:10001`, readable only by root and the manager), holding the address, SSH port,
account, password, inspection method, the automatic-check choice and the fingerprint of
the VM's own SSH host key. Setup confirms with *VM connection prefilled for the manager:
open VM connection and choose Save and test connection once.* On its next check (at start
and every 30 seconds) the manager moves the seed into its encrypted settings and deletes
the file.

Open `http://VM_IP:8081`. The **VM connection** dialog opens by itself, already filled
in, with the notice *Prepared by VM setup* and the key setup recorded. These entries are
**no longer typed**:

| Entry | Filled in by setup |
|---|---|
| VM address | `127.0.0.1` (the supplied Linux host-network deployment) |
| SSH port | The SSH server's configured port (`22` unless changed) |
| VM username | `clab-discovery` |
| VM password | The password just created; the field shows *Saved by VM setup on …, leave blank to keep it* |
| Inspection method | Installed discovery and file helper |
| Check the VM automatically for running labs | Checked |

**The one remaining step is the confirmation.** Choose **Save and test connection**
once. Until then the manager does not connect to the VM at all: a prepared connection
never trusts a host key in the background. The confirmed first connection must present
the key setup recorded; the manager then saves (pins) that fingerprint as usual. If the
VM presents a different key, the connection is refused with *VM SSH host key does not
match the key recorded by VM setup* and nothing is trusted: verify the VM, then run the
setup again (for example with `--reset-password`), or deliberately tick *Trust a
replacement SSH host key on the next connection*. That checkbox is left unticked in the
prepared dialog.

A seed never replaces trust: when a fingerprint is already saved (a password reset on a
connected VM) it stays in force, the new password is taken over, and the dialog warns if
the key setup recorded differs from the saved one. A seed that is not valid is ignored,
deleted and noted in the action log; its content is never logged. Only whether a password
is saved, when setup prepared the connection and the fingerprint it recorded reach the
browser, never the password. Changing the address or port in the dialog drops what setup
recorded, and the password must then be typed.

If setup prints that the manager data directory does not exist yet, or when the password
was already set and not reset (nothing to hand over), no seed is written. Enter the
connection by hand:

| Setting | Value |
|---|---|
| VM address | `127.0.0.1` for the supplied Linux host-network deployment |
| SSH port | `22`, or your configured SSH port |
| VM username | `clab-discovery` |
| VM password | The password you just created in the VM terminal |
| Inspection method | Installed discovery and file helper |
| Check the VM automatically for running labs | Checked |

Then choose **Save and test connection**. The manager saves the password encrypted and
never returns it to the browser. Reopening the dialog shows an empty password field;
leave it blank to retain the saved password for the same address, port and account.
Changing any of those requires entering the password again. Saving here updates the
manager's credential; it does not change the Linux account password.

On first connection, compare the saved host fingerprint against the VM's host key:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

The negotiated key may instead be RSA/ECDSA. Later fingerprint changes block
connection until independently verified and explicitly accepted in the UI (the
dialog's *Trust a replacement SSH host key on the next connection* checkbox).

## Persistent storage

| Location on VM | Contents |
|---|---|
| `/etc/shadow` | Linux account password hash, set by setup through `chpasswd` |
| `/srv/containerlab-node-manager/data/host-bootstrap.json` | One-time seed from setup (plain JSON including the password, mode `0600`, `10001:10001`); the manager deletes it after moving it into `state.enc` |
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
ownership/mode is `10001:10001 700`; the launcher prepares it (or run
`sudo bash "$HOME/projects/clab-manager/deploy/setup-vm.sh"`). No password is baked
into a Docker image. A rebuilt VM requires account setup again; copying manager data
alone does not recreate a Linux account.

The SSH policy forces the gateway and disables public-key authentication, interactive
SSH shells, PTYs, forwarding and user RC scripts for this account. Setup validates
syntax and effective policy before reload and restores the previous SSH configuration
on failure or a cancelled password prompt. Earlier conflicting Match rules cause
setup to fail with a review message. Its directives follow
[OpenSSH's SSH server configuration reference](https://man.openbsd.org/sshd_config).

## Upgrades and password changes

Routine upgrades use the installer or the launcher above. Once an account password
exists, setup retains it without prompting. It also preserves manager data and
previously enabled operations. A Docker build alone cannot install host helpers.

To create the account or repair helpers without building:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-discovery.sh"
sudo bash "$HOME/projects/clab-manager/deploy/setup-operations.sh" --lab-root /etc/containerlab
```

`--update-helper` remains an accepted alias for the discovery setup. To change or
recover a forgotten password, use your normal VM administrator account:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-discovery.sh" --reset-password
```

The reset hands the new password to the manager through the same one-time seed: open
**VM connection** and choose **Save and test connection** (the password field can stay
blank). Without a seed, enter the new password there. The previous manager credential
cannot reconnect until updated. `start-manager.sh --reset-password` also
resets the password before building and launching.

An installation that once used an SSH client key for this account is converted by
the same setup: the account becomes password-only, its old `authorized_keys` entries
are cleared, and saving the password in the dialog removes the obsolete key fields
while retaining the pinned VM host fingerprint. Other VM accounts and their SSH
settings are untouched.

## Troubleshooting

| Symptom | Check / fix |
|---|---|
| Password setup required | Run the discovery setup in the VM terminal, then save the password in VM connection. |
| VM connection says *Prepared by VM setup* | Expected after setup: choose Save and test connection once to connect and trust the VM's key. |
| Host key does not match the key recorded by VM setup | Nothing was trusted. Compare with `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`; if the VM is right, run the setup again or tick the replacement-key option deliberately. |
| `host-bootstrap.json` stays in the data directory | The manager could not delete it (ownership); it is not loaded twice by one manager process. Remove it as root after the connection works. |
| Authentication failed | Use the same password set for clab-discovery; reset it through the administrator command above if forgotten. |
| Setup needs an interactive terminal | Run directly from a VM console or interactive administrator SSH session. Passwords are not accepted from piped input. |
| Conflicting SSH account policy | Review earlier Match rules and global PermitUserEnvironment with your VM administrator. The installer requires user environment processing disabled. |
| Connection refused / timed out | Check address/port, `sudo systemctl status ssh`, firewall and VM networking. |
| Interactive SSH / SFTP denied | Expected for clab-discovery. Select the installed helper and use Save and test connection. Direct SFTP mode requires another existing account with ordinary file access. |
| Fingerprint changed | Verify the VM's host key independently before trusting a replacement in the UI. Password resets do not fix host identity changes. |
| Discovery connected, but folders and Git answer HTTP 409 | The session is not running the operations gateway; rerun the launcher with `--enable-operations` (see [the health report](HEALTH-CHECK.md#recover-the-operations-helper-error)). |
| Helper outdated / commands unavailable | Run the launcher from the current release source with the required lab roots and operations enabled. |
| Save failed | Check free disk space and data ownership; retain state.key and state.enc. |

**Manager settings → Start fresh** retains the VM connection, password, fingerprint
and state.key. **Remove from this manager…** affects only the selected saved workspace. Neither
operation changes the VM account password. New labs still require import confirmation.
