# Check an installed VM — 1.18.1

Run the second script after installation and browser setup to get a clear
**PASS / FAIL / WARN / SKIP / INFO** report with the next action for each problem.
It checks the current installation and does not repair it automatically.

This guide targets **1.18.1**, prepared from published main `7331e9a` (**1.18.0**).
It fixes the checker's sudo session handling. Obtain complete matching source after publication;
copying only the launcher omits the Python check modules it needs. An earlier
installed manager will be reported as a version mismatch until upgraded.

## Run the report

From the manager source checkout **inside Ubuntu**, use your normal VM account:

```bash
bash deploy/check-install.sh
```

Approve the sudo prompt for host inspection. Run without a leading `sudo` so
the checker detects the ordinary account used for WinSCP. A leading `sudo` is
also supported: the checker uses `SUDO_USER`, or an explicit `--owner archtop`. You can also select
**3. Check running installation** in `bash deploy/install.sh`.

Before this final check, complete **VM connection → Save and test connection**,
verify its saved host fingerprint, and connect the intended registered checkout
under **More → Git repository**. You can run the report earlier for diagnostics;
missing setup will be reported instead of assumed successful. The full install
still performs its shorter container/version/HTTP check before browser setup.
It does not automatically complete all of this second script's checks.

For the standard Git workflow plus the administrative WinSCP setup:

```bash
bash deploy/check-install.sh --require-git --require-admin-sftp
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
| `INFO` | Optional functionality, a deliberate check boundary, or a remaining manual test |

The heading, counts and final line summarize the same result:

| Overall result | Exit code | Meaning |
|---|---|---|
| `AUTOMATED CHECKS PASSED` | `0` | No failed, warned or skipped automated checks; informational/manual limits remain |
| `FAILURES FOUND` | `1` | At least one failed check |
| `NEEDS ATTENTION` | `2` | No failed checks, but warnings or skipped checks remain |

Run `echo "$?"` immediately after the command if you need its exit code.
An unsynchronized clock, an intentionally stopped lab, incomplete folder coverage
or an unconfigured optional Git workflow can produce a warning. Review the reason;
do not start devices or alter settings solely to make a report green.

This is an **illustrative excerpt**, not output from your VM:

```text
Containerlab Node Manager - installation health report
==============================================================
FAILURES FOUND

[PASS] Manager container
  The backup-ui container is running.
[FAIL] Operations helper through restricted account
  Helper responds as root but not correctly through clab-discovery; check gateway/sudoers.
  Next: sudo bash /home/archtop/projects/v1.18.1/deploy/setup-operations.sh
[FAIL] Topology browser over saved SSH connection
  The uncached browser request failed: HTTP 409
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
| Ubuntu and clock | Installer target platform, reported NTP synchronization and filesystem free space; no external clock comparison |
| SSH | Server configuration syntax, a local TCP listener, dedicated `clab-discovery` account/password status and effective restricted gateway policy |
| Normal SFTP | Effective ordinary-account SFTP subsystem and password policy; no password is requested or tested by this check |
| Administrative SFTP | Whether effective sudoers permission permits the ordinary account to launch the root SFTP server without a password |
| Proxmox additions | Optional QEMU guest-agent state and `/dev/kvm` presence for VM-based NOS images |
| Docker and manager | Local rootful daemon, Compose, running manager container, restart policy, host networking, version and actual configured HTTP address/port |
| Persistent storage | Persistent writable mount, container UID, saved key/state presence and successful decryption without printing contents |
| Containerlab | CLI response and deployed-node inspection; no deployed labs is valid before the first deployment |
| Restricted helpers | Actual discovery/operations gateway and sudo execution as `clab-discovery`, matching protocols/versions and core command availability |
| Manager-to-VM path | An uncached topology-browser request using the manager's saved SSH connection and pinned host fingerprint |
| Lab folders | Real folder browsing through that connection, including subfolders within the configured coverage limit |
| Git | Registry access through the manager, local registered owners/checkouts, initial commit, commit identity, registered branch/destination, and staged/managed-folder changes |
| Optional Git remote read | With `--git-remote`, a bounded `ls-remote` as each registered owner; no fetch, commit or push |

Disabled online lab downloads are informational and do not explain a failed
folder browse. Existing empty folders are valid. A missing folder, symlinked
project path, unavailable helper or failed SSH request gets a separate result.

Local host checks describe the VM where you run the script. Manager SSH checks
describe the host saved in **VM connection**. For this standalone workflow those
should be the same VM; check the saved address if they disagree.

## Check the folder that failed in the UI

Give `--lab-path` an **absolute folder**, not the topology YAML filename:

```bash
bash deploy/check-install.sh --lab-path /etc/containerlab/vJunOS-SW
```

The script checks specified folders first, then configured roots and discovered
subfolders. Repeat `--lab-path` for more than one priority folder. The default
coverage is **20 folders**. Larger trees report a warning when more folders
remain unchecked. A folder listing that reaches the helper's 500-entry limit
also reports incomplete coverage.

For a larger tree and an optional Git remote-read check:

```bash
bash deploy/check-install.sh --require-git --git-remote \
  --lab-path /etc/containerlab/vJunOS-SW --max-folders 80 --deadline 600
```

The default run budget is 300 seconds, with bounded individual commands and
responses. If coverage times out, fix the reported prerequisite or rerun with a
specific folder and a larger budget. A timed-out check is never counted as passed.

## Recover the operations-helper error

**If 1.17.0/1.18.0 reports administrator access PASS but Docker, SSH and every
helper fail together**, first rerun the report as root. Those checker versions
start commands in detached sessions which cannot reuse Ubuntu's terminal-scoped
sudo authentication. Do not treat that pattern alone as a broken VM:

```bash
sudo bash deploy/check-install.sh --owner archtop --lab-path /etc/containerlab/vJunOS-SW
```

Substitute your ordinary account and actual folder. This workaround works on the
existing source. Version 1.18.1 preserves the session while keeping command
process groups and timeouts, and verifies privilege using the same command runner.

The 1.18.1 launcher checks the restricted account's gateway and sudo permissions
before building. The browser's saved SSH connection and actual folders still
need the report after browser setup. Use **clab-discovery** as the saved VM
username with **installed helper** mode; `archtop` is the ordinary Git/SFTP owner.
An ordinary SSH shell does not implement the `clab-manager-operations` command.

The manager's SSH reader also used to stop at exit status before the stream
ended. A delayed final result reproduced the exact generic helper error in a
local SSH test. Upgrading both image and helpers to 1.18.1 fixes that reader;
a helper-only refresh cannot update code inside the running image:

```bash
sudo bash deploy/start-manager.sh --enable-operations
```

Run this from complete 1.18.1 source after publication, retaining any customized
`.env` settings when moving to a new source folder. No automatic lab deployment
or retry is performed. If a lifecycle command was interrupted, inspect current
lab state before approving another operation.

`clab_admins` is not required for manager operations. The installer deliberately
keeps new Containerlab installations without SUID/group elevation; the fixed
helper runs Containerlab through its restricted sudo rule.

For an existing VM whose discovery account is already set up, refresh only the
operations installation from its **matching source checkout**:

```bash
sudo bash deploy/setup-operations.sh
```

This refreshes the operations helper, gateway and sudoers entry while retaining
custom trusted roots and any existing download permission. It does not rebuild
the image or reset the VM password. Close and reopen the failed folder, then run
the report again. If the discovery account itself is missing, complete the
installer first. Use the existing installed release's source for a helper-only
repair; a release upgrade should update the manager and helpers together.

If local helper execution passes but browser SSH fails, review **VM connection**
address, username, installed-helper mode, password and fingerprint. If only one folder fails, verify its existence
and that its path is within a trusted root without symlink components. The checker
does not create folders, change their ownership, or broaden trusted roots.

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
bash deploy/check-install.sh --json --require-git > "$HOME/clab-health.json"
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

1. Open the manager from the workstation using the VM LAN address and configured
   port. Local HTTP success does not test the workstation firewall/network route.
2. Log in through WinSCP as the normal Ubuntu account, upload a small file and
   download it again. For administrative SFTP, test the intended root-owned
   destination. Configuration checks do not prove a real password login.
3. Test an intended device login and capture/download its configuration. A
   running Docker container or `/dev/kvm` device does not prove NOS readiness.
4. Use **Save progress** deliberately, wait for **Pushed**, and inspect the
   expected remote files. A public remote can be readable anonymously;
   `ls-remote` does not prove GitHub write permission or branch-rule acceptance.

Continue with [the fresh-VM walkthrough](FRESH-VM-GUIDE-V2.md),
[Git recovery](GIT-SETUP.md#fix-a-failed-save) or the
[master operations wiki](WIKI-MASTER-GUIDE.md) for the relevant next step.
