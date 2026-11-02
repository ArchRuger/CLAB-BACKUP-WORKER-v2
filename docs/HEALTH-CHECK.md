# Check an installed VM

`deploy/check-install.sh` inspects a VM after installation and browser setup and
prints a **PASS / FAIL / WARN / SKIP / INFO** report with the next action for each
problem. It checks the current installation and does not repair it. For a running
manager, the [Diagnostics page](DEBUG-PANEL.md) (administrators only, after signing in)
also checks folder browsing and helper versions and exports API request metadata; use
this terminal report when the manager is unavailable, nobody can sign in or host setup
needs checking. The report needs no manager account: it never signs in.

## Run the report

From any directory **inside Ubuntu**, as your normal VM account:

```bash
bash "$HOME/projects/clab-manager/deploy/check-install.sh"
```

Approve the sudo prompt for host inspection. Run without a leading `sudo` so
the checker detects the ordinary account used for WinSCP. A leading `sudo` is
also supported: the checker uses `SUDO_USER`, or an explicit `--owner archtop`.
You can also select **5. Check running installation** in the installer menu.

Before this final check, complete **Manager ▾ › VM connection… → Save and test
connection**, verify its saved host fingerprint, and connect the intended registered
checkout by pressing **Save** in the lab header (the first save offers a place to save; **Save settings** in
the chip panel changes it later). You can run the report earlier for diagnostics;
missing setup will be reported instead of assumed successful. The full install
still performs its shorter container/version/HTTPS check before browser setup.

For the standard Git workflow plus the administrative WinSCP setup:

```bash
bash "$HOME/projects/clab-manager/deploy/check-install.sh" --require-git --require-admin-sftp
```

Use `--require-admin-sftp` when you deliberately configured root file access in
WinSCP. Ordinary SFTP uploads to your own folders do not need that permission.
See [the working WinSCP setup](FRESH-VM-GUIDE-V2.md#winscp-admin-sftp).

## Read the result

| Result | Meaning |
|---|---|
| `PASS` | That automated check succeeded at the time of the report |
| `FAIL` | A required component failed or could not be verified; follow its `Next:` instruction |
| `WARN` | Attention is needed, or the result has incomplete coverage |
| `SKIP` | A prerequisite prevented a check from running; it is not a pass |
| `INFO` | A deliberate check boundary or a remaining manual test |

The heading, counts and final line summarize the same result:

| Overall result | Exit code | Meaning |
|---|---|---|
| `AUTOMATED CHECKS PASSED` | `0` | No failed, warned or skipped automated checks; informational/manual limits remain |
| `FAILURES FOUND` | `1` | At least one failed check |
| `NEEDS ATTENTION` | `2` | No failed checks, but warnings or skipped checks remain |

Run `echo "$?"` immediately after the command if you need its exit code.
An unsynchronized clock, an intentionally stopped lab, incomplete folder coverage,
an unconfigured optional Git workflow or a deliberately removed stack can produce
a warning. Review the reason; do not start devices or alter settings solely to
make a report green. Every `Next:` line is a command that works from any directory.

This is an **illustrative excerpt**, not output from your VM:

```text
Containerlab Node Manager - installation health report
==============================================================
FAILURES FOUND
PASS: 2 | FAIL: 2 | WARN: 1 | SKIP: 0 | INFO: 1
Source: 1.31.9

[PASS] Manager container
  The backup-ui container is running.
[FAIL] Operations helper through restricted account
  Helper responds as root but not correctly through clab-discovery; check gateway/sudoers.
  Next: sudo bash /home/archtop/projects/clab-manager/deploy/setup-operations.sh
[FAIL] Topology browser over saved SSH connection
  The uncached browser request failed: HTTP 409
[WARN] Retired telemetry stack
  Still present: container(s) clab-manager-grafana, clab-manager-telemetry-prometheus-1; volume(s) clab-manager-telemetry_grafana-data, clab-manager-telemetry_prometheus-data; .env key(s) TELEMETRY_STACK; folder /srv/containerlab-node-manager/telemetry.
  Next: sudo bash /home/archtop/projects/clab-manager/deploy/retire-telemetry.sh
[INFO] Git repository 1: push permission
  Not exercised. Remote read access does not prove write permission or acceptance by branch rules.

MANUAL VERIFICATION STILL REQUIRED
  - Test WinSCP from the workstation, a real device backup, and a deliberate Git save/push.

FAILURES FOUND (exit 1)
```

## What it checks

| Area | Automated evidence |
|---|---|
| Source | Complete matching release metadata, compared with the running application and host helper responses |
| Network design engine | The pinned netlab engine inside the running image answers `/api/design/engine`: PASS with its version, WARN with the manager's own diagnostic when it is unavailable (every other feature keeps working; rebuild the image to restore planning) |
| Ubuntu and clock | Installer target platform, reported NTP synchronization and filesystem free space; no external clock comparison |
| SSH | Server configuration syntax, a local TCP listener, dedicated `clab-discovery` account/password status and effective restricted gateway policy |
| Normal SFTP | Effective ordinary-account SFTP subsystem and password policy; no password is requested or tested by this check |
| Administrative SFTP | Whether effective sudoers permission permits the ordinary account to launch the root SFTP server without a password |
| Proxmox additions | Optional QEMU guest-agent state and `/dev/kvm` presence for VM-based NOS images |
| Engineer access | When `setup-engineer-access.sh` recorded an account: its `docker` and `clab_admins` membership, group-writable `clab_admins` setgid trusted lab roots, and the root-owned SUID containerlab binary that VS Code's Containerlab extension needs; informational when never configured |
| Docker and manager | Local rootful daemon, Compose, running manager container, restart policy, host networking, version and the actual configured HTTPS address and port; readiness is `GET /api/health` over TLS with the installed certificate as the only trusted one |
| Persistent storage | Persistent writable mount, container UID, saved key/state presence and successful decryption without printing contents |
| Containerlab | CLI response and deployed-node inspection; no deployed labs is valid before the first deployment |
| Helper files | Root ownership, modes, regular files and content of the installed inspect, operate and Git helpers compared with this source, and sudoers syntax; a stale or missing operate helper fails here and skips the SSH checks that need it |
| Restricted helpers | Actual discovery/operations gateway and sudo execution as `clab-discovery`, matching protocols/versions and core command availability |
| Manager-to-VM path | An uncached topology-browser request using the manager's saved SSH connection and pinned host fingerprint, run read-only by a probe inside the manager container |
| Lab folders | Real folder browsing through that connection, including subfolders within the configured coverage limit |
| Git | Registry access through the manager, local registered owners/checkouts, initial commit, commit identity, registered branch/destination, and staged/managed-folder changes |
| Optional Git remote read | With `--git-remote`, a bounded `ls-remote` as each registered owner; no fetch, commit or push |
| Browser Wireshark capture | Whether the provider is enabled (a WARN with the setup command when it is not, since the stack is part of every installation), Edgeshark lists targets, and the browser session service and pinned image are ready. Live packets, viewer interaction and saved-capture download remain acceptance checks |
| TLS, firewall and exposure | The group below: the certificate and its files, the HTTPS listener, the plain-HTTP redirect, HSTS, the host firewall, listening ports, published container ports, a waiting setup or recovery code and SSH hardening |
| Retired telemetry stack | PASS when no container or volume labelled with the old telemetry Compose project remains, no `TELEMETRY_*` key remains in `clab-backup-ui/.env` and neither retired feature folder remains on disk; otherwise WARN listing what is left, with the remedy |

Disabled online lab downloads are informational and do not explain a failed
folder browse. Existing empty folders are valid. A missing folder, symlinked
project path, unavailable helper or failed SSH request gets a separate result.

Local host checks describe the VM where you run the script. Manager SSH checks
describe the host saved in **VM connection**. For this standalone workflow those
should be the same VM; check the saved address if they disagree.

## How the report asks the manager

The manager has a sign-in, and the report has no account, so it asks the running manager
**one** HTTP question: `GET /api/health` over TLS, with the installed
`/srv/containerlab-node-manager/tls/cert.pem` as the only certificate it trusts (the host
name is not compared; whether the certificate carries the right names is the separate
`tls.names` check). It makes two more requests that read no page: a plain-HTTP `GET /` on the redirect port,
which must answer `301`, and a plain-HTTP `GET /` on the TLS port, which must fail. The TLS
listener and HSTS checks read the same pinned HTTPS answer (below). Every other fact about the
manager (the design engine, the capture provider, the saved VM connection, the topology
browser and the Git registry) comes from a read-only probe, `docker exec … python -m
app.probe NAME`, run inside the manager container. A probe reads its environment, a loopback
service or the manager's saved state read-only, never writes and never prints a value.

You may meet these **SKIP** results (the reasons below are the common ones; each is worded as the report prints it), none of which is a pass:

| SKIP reason | What it means and what to do |
|---|---|
| *The running manager predates this check's probe; rebuild it.* | The container runs an older image than this checkout. Run the `start-manager.sh` command the `Next:` line shows. |
| *The saved state could not be read without the manager (…); the manager's own page runs this check.* | The probe could not open the saved state. Open **Manager ▾ › Diagnostics** after signing in as an administrator, which runs the same check. |
| *… a lab's save drawer lists the registry.* | The same, for the Git registry: open a lab's **Save ▾** drawer, whose folder chooser lists the repositories through the same request. |
| *The installed certificate could not be read, so the manager was not asked over HTTPS.* | `cert.pem` is missing or unreadable; run the `setup-tls.sh` command shown. |
| *Docker access is required for this check.* | Docker or the manager container is not available (the *Docker daemon*, *Docker Compose* and *Manager container* rows say which); follow their `Next:` line. The report already asks Docker through `sudo`. |
| *The manager start command could not be read.* / *The manager has no usable HTTPS address, so the TLS listener was not probed.* / *The TLS listener did not answer, so the header was not read.* | The manager container is missing or not serving; run the `start-manager.sh` command shown. |
| *The certificate names could not be read…* / *The certificate rule of setup-tls.sh could not be loaded…* | The names in the certificate were not compared; run the `setup-tls.sh` command shown. |
| *The listening sockets could not be listed.* / *The running containers could not be listed.* | The exposure check could not read the host's sockets or the container list; nothing was concluded. |
| *The setup-code file could not be checked…* | Whether a setup or recovery code waits is unknown; rerun the report with administrator access, as its `Next:` line says. |
| *The effective SSH configuration could not be read.* | Run the `setup-ssh-hardening.sh` command shown. |
| *Manager container unavailable…* | The probe-based facts were not read; start the manager and run the report again. |

## TLS, firewall and exposure

These checks never change anything, never read a private key and never print the setup
code, a key or a hash. Their ids appear in `--json`:

| Id | What it checks | Result you may see |
|---|---|---|
| `tls.files` | The tls folder: directory, `cert.pem`, `key.pem` and `mode` exist with the owners and modes in [TLS and the certificate](INSTALL.md#tls-and-the-certificate), and the mode word is valid | PASS; FAIL names what differs |
| `tls.cert` | The installed certificate parses; its expiry and SHA-256 fingerprint are printed | PASS; WARN within 30 days of expiry; FAIL expired or unreadable |
| `tls.hsts-scope` | Only with a provided certificate | INFO: HSTS applies to every port of the name for 180 days |
| `tls.names` | Every certificate address, listed `UI_ALLOWED_HOSTS` name and `--name` entry is in the certificate | PASS; WARN lists the missing names (`setup-tls.sh` regenerates a self-signed certificate and recreates the manager itself; or install a new provided certificate) |
| `tls.bind` | The manager's start command carries the TLS arguments and `--no-proxy-headers` | PASS; WARN if `--no-proxy-headers` is missing (an older compose file); FAIL if it would serve plain HTTP |
| `tls.listener` | The manager answers over TLS with the installed certificate pinned | PASS; FAIL names the reason |
| `http.redirect` | The redirect port answers `301` to the HTTPS address, and the TLS port refuses plain HTTP | PASS; INFO when `UI_HTTP_PORT=0`; WARN if the redirect is down; FAIL when plain HTTP serves a page |
| `http.hsts` | `Strict-Transport-Security: max-age=15552000` is sent | PASS; WARN absent (an older image) |
| `firewall` | `ufw` is active, denies incoming traffic by default and allows SSH, the TLS port and the redirect port | PASS; WARN inactive, too narrow, a deny rule covering a manager port, or a rule that allows every port or more than 1000 ports from anywhere; FAIL not installed. A cloud security group is an accepted reason to ignore the warning |
| `exposure.listeners` | Only SSH, the TLS port and the redirect port listen beyond loopback | PASS; WARN lists others; FAIL if the capture stack is not loopback-only |
| `exposure.ports` | No running container publishes a port beyond loopback (a lab topology with `ports:` can) | PASS; WARN lists them |
| `signon.bootstrap` | Whether a setup or recovery code is waiting; the file is never opened beyond its first line | PASS none waiting; WARN *Setup not completed: no administrator exists* (open the setup page and enter the code from `sudo cat /srv/containerlab-node-manager/data/setup-code`), or a recovery is open or expired ([lost password](INSTALL.md#lost-administrator-password)) |
| `ssh.hardening` | `PermitRootLogin`, `LoginGraceTime` and `PerSourceMaxStartups` as `setup-ssh-hardening.sh` sets them | PASS; INFO when `PermitRootLogin` stays at the OpenSSH default because root may log in with a key; WARN otherwise |
| `ssh.bruteforce` | `fail2ban` is active | PASS; WARN while it is not ([recommended](INSTALL.md#recommended-fail2ban)) |

The `Next:` line of each names the exact command. See [Firewall and SSH](INSTALL.md#firewall-and-ssh)
for the installer steps behind the firewall and SSH rows.

## Check the folder that failed in the UI

Give `--lab-path` an **absolute folder**, not the topology YAML filename:

```bash
bash "$HOME/projects/clab-manager/deploy/check-install.sh" --lab-path /etc/containerlab/vJunOS-SW
```

The script checks specified folders first, then configured roots and discovered
subfolders. Repeat `--lab-path` for more than one priority folder. The default
coverage is **20 folders**. Larger trees report a warning when more folders
remain unchecked. A folder listing that reaches the helper's 500-entry limit
also reports incomplete coverage.

For a larger tree and an optional Git remote-read check:

```bash
bash "$HOME/projects/clab-manager/deploy/check-install.sh" --require-git --git-remote \
  --lab-path /etc/containerlab/vJunOS-SW --max-folders 80 --deadline 600
```

The default run budget is 300 seconds, with bounded individual commands and
responses. If coverage times out, fix the reported prerequisite or rerun with a
specific folder and a larger budget. A timed-out check is never counted as passed.

## Recover the operations-helper error

**If discovery is connected but "Topology browser over saved SSH connection" fails
with HTTP 409 (and Git registry also fails)**, the saved VM password is not the
cause: connected discovery uses the same `clab-discovery` account and password.
The clab-discovery SSH session is reaching the account but not running the
operations gateway, so its `clab-manager-operations` command is reported as not
found. Rerun the launcher from the source folder:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/start-manager.sh" --enable-operations
```

This reinstalls the gateway, operations helper and sudoers, verifies them through
the restricted account, refreshes the capture stack and recreates the
manager container so the running image matches. Then reconnect in **Manager ▾ › VM
connection…** and reopen the folder. The Diagnostics page labels this a gateway/enablement problem
(`did not run the operations gateway`) rather than an authentication failure, and
the report gives the same gateway-specific next step. If the local "Operations
helper through restricted account" check itself fails, refresh only the operations
installation first:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-operations.sh"
```

This refreshes the operations helper, gateway and sudoers entry while retaining
custom trusted roots and any existing download permission. It does not rebuild
the image or reset the VM password. Close and reopen the failed folder, then run
the report again. If the discovery account itself is missing, complete the
installer first. Use the installed release's source for a helper-only repair; a
release upgrade should update the manager and helpers together.

If local helper execution passes but browser SSH fails, review **VM connection**
address, username, installed-helper mode, password and fingerprint. If only one
folder fails, verify its existence and that its path is within a trusted root
without symlink components. The checker does not create folders, change their
ownership, or broaden trusted roots. `clab_admins` is not required for manager
operations: the installer keeps new containerlab installations without SUID/group
elevation unless you choose VS Code access, and the helper runs containerlab
through its restricted sudo rule.

## Options

| Option | Use |
|---|---|
| `--json` | Print the structured report to standard output; progress and sudo messages use standard error |
| `--owner archtop` | Select the ordinary VM account for account-specific SSH/SFTP checks, especially when running from a root session |
| `--lab-path /absolute/folder` | Prioritize this folder; repeat as needed |
| `--max-folders 80` | Folder coverage limit, from 1 through 500; default 20 |
| `--deadline 600` | Run budget in seconds, from 30 through 1800; default 300 |
| `--require-git` | Treat missing Git setup as a failure instead of a warning |
| `--git-remote` | Also test remote branch reads as each registered repository owner |
| `--require-admin-sftp` | Require the optional passwordless root SFTP permission |
| `--require-kvm` | Require `/dev/kvm` for VM-based network images |
| `--discovery-only` | Indicate that lab operations were intentionally not enabled; do not use this to conceal a broken deployment workflow |

The local Git check inspects at most 20 registrations and reports any remaining
ones as unverified. `--owner` does not replace repository owners: each checkout
is checked under its own registered Linux account and HOME.

## Save a support report

To keep the structured result in your home directory:

```bash
bash "$HOME/projects/clab-manager/deploy/check-install.sh" --json --require-git > "$HOME/clab-health.json"
check_status=$?
printf 'Health report exit code: %s\n' "$check_status"
```

The JSON contains the overall result, exit code, status counts, individual check
IDs/details/recovery guidance and remaining manual checks. Reports may include
source and lab-folder paths, account-specific recovery commands and the local
manager address. They omit passwords, tokens, device configuration contents,
decrypted state and raw Git/SSH error output. Review paths and filenames before
sharing. No report is uploaded automatically.

The checker does not install packages, alter configuration or credentials,
restart services, deploy/stop labs, create backups, or fetch/commit/push Git
changes. Normal service/SSH request audit logs can be written; an existing
credential helper may update its own cache during an optional remote-read check.

## Complete the real workflow

Even when automated checks pass, verify these actions yourself:

1. Open `https://VM_ADDRESS:8443` (or your configured port) from the workstation using
   the VM LAN address, accept the self-signed certificate after comparing its
   fingerprint with the one the report prints for `tls.cert`
   ([TLS and the certificate](INSTALL.md#tls-and-the-certificate)), and sign in. A local
   HTTPS success does not test the workstation firewall or network route: if the page
   does not load, check the firewall and any cloud security group for the TLS port.
   A DNS name other than a single-label or `.local` name is refused until it is
   listed in `UI_ALLOWED_HOSTS` ([Opening the manager by a name](INSTALL.md#opening-the-manager-by-a-name)).
2. Log in through WinSCP as the normal Ubuntu account, upload a small file and
   download it again. For administrative SFTP, test the intended root-owned
   destination. Configuration checks do not prove a real password login.
3. Test an intended device login and capture/download its configuration. A
   running Docker container or `/dev/kvm` device does not prove NOS readiness.
4. Start a capture (**Capture traffic…**) on a deployed lab and confirm packets
   arrive in Wireshark.
5. Press **Save** in the lab header deliberately, press **Upload** when it offers it, wait for the chip to
   report the save as uploaded, and inspect the expected remote files. A public remote can be readable anonymously;
   `ls-remote` does not prove GitHub write permission or branch-rule acceptance.

Continue with [the fresh-VM walkthrough](FRESH-VM-GUIDE-V2.md),
[Git recovery](GIT-SETUP.md#fix-a-failed-save) or the
[master operations wiki](WIKI-MASTER-GUIDE.md) for the relevant next step.
