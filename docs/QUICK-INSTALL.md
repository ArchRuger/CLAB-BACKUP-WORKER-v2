# Quick install — paste and go

The whole route from a fresh Ubuntu VM to a saved lab, as ordered steps with
only what to paste, type or click. Explanations, alternatives and recovery are
in the [full fresh VM guide](FRESH-VM-GUIDE-V2.md).

Run every block in the **Ubuntu VM terminal as your normal account**, not as
root and not as `clab-discovery`, unless the step says **Proxmox**, **Windows**,
**WinSCP**, **VS Code** or **browser**. Every command works from any directory.
Replace these placeholders:

| Placeholder | Replace with |
|---|---|
| `archtop` | Your Ubuntu account name, if different |
| `VM_IP` | The VM's LAN address, for example `10.150.2.213` |
| `LAB_NAME` | Your lab folder and topology name, for example `practice-lab` |
| `GITHUB_URL` | Your repository's **Code → HTTPS** URL, ending in `.git` |

## 1. Start the VM

1. **Proxmox:** roll back to the snapshot taken after the Ubuntu install, then start the VM.
2. Open its console, or from **Windows** run `ssh archtop@VM_IP`, and log in.

## 2. Fix the clock

```bash
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
sleep 10
date -u
timedatectl status
```

`date -u` must show the current UTC time. If it does not, put the current UTC
date and time into the `set-time` line, then paste:

```bash
sudo timedatectl set-ntp false
sudo timedatectl set-time "2026-09-12 15:20:00 UTC"
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
date -u
```

## 3. Get the source and start the installer

```bash
(
  set -e
  if ! command -v git >/dev/null 2>&1; then
    sudo apt-get update --error-on=any
    sudo apt-get install -y git
  fi
  mkdir -p "$HOME/projects"
  git clone https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2.git "$HOME/projects/clab-manager"
  bash "$HOME/projects/clab-manager/deploy/install.sh"
)
```

## 4. Answer the installer

| Prompt | Type |
|---|---|
| `Setup menu` | `1` |
| `Manager bind/port settings` | `1` |
| `Lab operation access` | `1` |
| `VS Code / Containerlab extension access for archtop` | `1` |
| `Back up and disable obsolete installation-media APT entries if present? (y/N)` | `y` |
| `Proceed with this plan? (y/N)` | `y` |
| `[sudo] password for archtop:` | Your Ubuntu password |
| `New password:` then `Retype new password:` (after `Create the clab-discovery password`) | A new password for the manager's VM login. **Write it down**; step 9 needs it |
| `Next step` | `1` if your GitHub repository already exists, otherwise `2` and skip step 5 |

The browser Wireshark and Grafana phases run without questions. Wait for
`Manager 1.26.0: running; HTTP and version checks passed.` The image build and the
two stacks take several minutes. If a step fails, read the error, fix it in a second
terminal, then type `1` to retry. A `not valid yet` APT error is the clock:
redo step 2 in the second terminal, then retry.

## 5. Git wizard

Create the GitHub repository first, with **Add a README** selected. Then:

| Prompt | Type |
|---|---|
| `Where are your lab configurations going?` | `1` |
| `HTTPS clone URL (Code > HTTPS on GitHub)` | `GITHUB_URL` |
| `Checkout directory [/home/archtop/labs/...]` | Enter |
| `Install GitHub CLI with sudo apt-get? (y/N)` | `y` |
| One-time code, then `Press Enter to open ...` | Copy the code, press Enter. On **Windows** open https://github.com/login/device, paste the code, authorize |
| `Commit author name` | Your name |
| `Commit author email (GitHub noreply email is also valid)` | Your email |
| `Register this checkout with the manager? (y/N)` | `y` |

Wait for `Registered ...` and `Ready.` To reopen the wizard later:

```bash
bash "$HOME/projects/clab-manager/deploy/install.sh" --git
```

## 6. WinSCP

Paste in the VM:

```bash
sudo -v
me="$(id -un)"
printf '%s ALL=(root) NOPASSWD: /usr/lib/openssh/sftp-server\n' "$me" | sudo tee "/etc/sudoers.d/${me}-sftp" >/dev/null
sudo chmod 0440 "/etc/sudoers.d/${me}-sftp"
sudo visudo -cf "/etc/sudoers.d/${me}-sftp"
sudo -k
sudo -n /usr/lib/openssh/sftp-server </dev/null >/dev/null && echo "Root SFTP is ready for $me"
```

Expect `parsed OK` and `Root SFTP is ready`. Then in **WinSCP**, create a site:

| Setting | Value |
|---|---|
| File protocol | SFTP |
| Host name | `VM_IP` |
| Port number | `22` |
| User name | `archtop` |
| Password | Your Ubuntu password |
| Advanced → Environment → SFTP → SFTP server | `sudo -n /usr/lib/openssh/sftp-server` |

Save, connect, accept the host key, and check that you can create a folder
under `/etc/containerlab`.

## 7. VS Code

If you answered **1** to the installer's *VS Code / Containerlab extension
access* question, skip the command. Otherwise paste in the VM:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-engineer-access.sh" --owner "$(id -un)"
```

Then in **VS Code** on Windows:

1. Install the **Remote - SSH** extension.
2. If VS Code was already connected to this VM: Command Palette → **Remote-SSH: Kill VS Code Server on Host...** → pick the VM.
3. Connect to `archtop@VM_IP` and install the **Containerlab** extension in that remote window.
4. Open a terminal there; `id -nG` must list `docker` and `clab_admins`, and creating a folder under `/etc/containerlab` in the explorer must work.

## 8. Upload the lab and images

1. **WinSCP:** open `/etc/containerlab`, create `LAB_NAME`, and upload the whole
   project into it: the `.clab.yaml`, startup configs and annotations file.
2. In the VM, pull each image named in the topology:

```bash
sudo docker pull IMAGE:TAG
```

For an image archive uploaded with WinSCP to `/home/archtop/uploads` instead:

```bash
sudo docker load -i "$HOME/uploads/IMAGE.tar"
```

## 9. Connect the manager to the VM

**Browser** on Windows: open `http://VM_IP:8081`. The **VM connection** dialog
opens by itself the first time:

| Field | Value |
|---|---|
| VM address | `127.0.0.1` |
| SSH port | `22` |
| Username | `clab-discovery` |
| Password | The password created in step 4 |
| Inspection method | Installed discovery and file helper |
| Automatic discovery | Enabled |

Click **Save and test connection**.

## 10. Deploy the lab

In the **browser**:

1. **Deploy a new lab** → expand `/etc/containerlab` → `LAB_NAME` → click the
   `.clab.yaml` → **Deploy lab** → confirm the reviewed command.
2. Wait for the green banner, then for **NOS ready** in the deployment bar. The
   login test runs by itself and appears in **Backup history**.
3. Devices with their own logins: **More → Credentials → Add credential** for each
   device type, then open a node → **Test login**. Nodes with containerlab's default
   login need nothing.
4. **Back up all configs** in the topology header.

Deployed from the VM terminal instead (`sudo containerlab deploy -t
/etc/containerlab/LAB_NAME/LAB_NAME.clab.yaml`)? The lab appears on the landing
page as **Already running on the VM**; click **Import**.

## 11. Watch it and capture

1. **Grafana ↗** in the lab header starts Grafana on the VM when it is stopped (a few
   seconds) and opens the lab map. Links colour as traffic flows; the Interfaces
   dashboard shows rates. Grafana stops itself after 15 minutes without an open
   dashboard; the button brings it back.
2. Right-click a node on the map → **Capture packets** → tick a port → **Start
   browser capture** → **Open Wireshark in browser**.

## 12. Save to Git

1. **More → Git repository** → select the registered checkout and the devices → save.
2. **Save progress** → wait for **Pushed** → check the files on GitHub.

## 13. Check everything

```bash
bash "$HOME/projects/clab-manager/deploy/check-install.sh" --require-git --require-admin-sftp
```

Fix any **FAIL** or **WARN** using its `Next:` line, then rerun. Done.

## Later

- Clock wrong again after a rollback: step 2.
- WinSCP says `sudo: a password is required`: step 6.
- VS Code says `Insufficient permissions`: step 7.
- Upgrade: `git -C "$HOME/projects/clab-manager" pull --ff-only`, then step 3's
  last line and step 4 again (existing passwords and settings are kept).
- Reopen the installer menu: `bash "$HOME/projects/clab-manager/deploy/install.sh"`.
