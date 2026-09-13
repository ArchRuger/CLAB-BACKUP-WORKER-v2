# Changelog

Release notes for every published version, newest first. Links point to the
guides in this folder; validation evidence for recent releases is in
[clab-backup-ui/VALIDATION.md](../clab-backup-ui/VALIDATION.md).

## Changes in 1.22.0

The manager leads with deployment instead of import, and a freshly deployed lab is
usable without any manual setup.

- **Deploy-first landing page.** With no saved lab, the workspace offers **Deploy a
  new lab** (the VM topology browser, in place), lists labs already running on the VM
  with a one-click **Import**, and asks for the VM connection first when none exists.
  Importing a lab definition or an Ansible inventory stays available as links.
- **Deploy lab saves the workspace.** **Deploy lab** in the topology browser registers
  the workspace (nodes, map and VM source path) before containerlab runs, so the lab is
  in the sidebar at once and nothing has to be imported afterwards. **Save to
  manager** still saves without deploying.
- **Automatic NOS login.** Nodes of supported kinds use containerlab's documented
  default login when no credential profile or inventory login exists: cEOS
  `admin`/`admin`, vJunos-switch, vQFX and cJunosEvolved `admin`/`admin@123`, XRv9k
  `clab`/`clab@123`. A profile or an inventory login always wins; the Nodes table shows
  *Containerlab default login* when the default is in use. A readiness monitor logs in
  to every running node of a linked lab over SSH and asks for `show version` every
  20 seconds until the NOS answers, shows *NOS booting 0/2* and then *NOS ready 2/2*
  in the deployment bar, records each answer in the *Last SSH check* column, and runs
  **Test NOS login** once when every node has answered after a deployment. SSH, the
  SSH menu entry and **SSH all nodes** open as nodes answer; a node that stops or
  restarts must answer again, and a failed automatic test sends its nodes back to
  booting and is retried up to three times per boot. A login refused three times in
  a row is reported as failed with the fix (assign a profile) and keeps being retried
  each minute. **Sync from VM** fills a blank saved login from the generated inventory.
- **Backups and login tests survive a redeploy.** Lab containers generate new SSH host
  keys on every deploy, and the Ansible transport used to record the old keys in the
  manager's `known_hosts` and then refuse the node with *host key mismatch* until the
  manager was recreated. Every job now runs with its own empty `known_hosts`.
- **Operation output** starts with a large green banner such as *✔ Deploy lab
  succeeded · Exit 0 · Operation completed*; failures are red, running jobs blue.
- **VM connection** opens with *Enable automatic discovery* and *Trust a replacement
  SSH host key on the next connection* both checked.
- **Capture dialog.** Opened from a node or a link, it lists that node's topology
  interfaces first (a single one is already ticked, and a link opens on its first
  endpoint). The remaining live Linux interfaces sit under *All live Linux
  interfaces*; scope, search and the capture-target selector sit under *Advanced* and
  unfold only when no target could be resolved.
- **Wireshark viewer.** One toolbar row with the status inline and the instructions
  under *How to save a capture*, which say to type the full file name ending in
  `.pcapng` because Wireshark on the VM does not add the extension; the *No saved
  captures yet* message says the same.

## Changes in 1.21.1 (historical)

Fixes from vetting the 1.21.0 browser Wireshark on a live Ubuntu VM. The viewer now
connects: the pinned Wireshark image's websockify only completes a handshake that
offers the `binary` WebSocket subprotocol, so the session service and the manager
relay offer it (and answer it only to a browser that asked). **Download saved
captures** returns what Wireshark saved under `/pcaps`: that folder is now a
tmpfs-backed Docker volume the daemon can read instead of a container tmpfs that the
archive API never sees; the same size, ownership and cleanup limits apply, and an
empty folder answers "No saved captures yet" instead of an empty archive. The viewer
checks a download before handing it to the browser so that message is shown in
place. `setup-capture.sh` recreates the capture services, so upgrading a 1.20.x
stack no longer stops on the renamed project network. The CI smoke test reads the
container's temporary and saved files from inside the container, where tmpfs
contents live, and checks the empty-folder response. See
[Browser capture setup](CAPTURE.md) and [validation evidence](../clab-backup-ui/VALIDATION.md).

## Changes in 1.21.0 (historical)

Wireshark now runs on the lab VM and opens in the browser. The workstation plugin,
external-app launcher and public Edgeshark URL setting are removed. A separate
session service creates isolated, pinned Wireshark containers; the manager keeps
its existing permissions. Sessions support reconnect, saved-capture downloads,
explicit removal, browser ownership and idle/lifetime/resource limits.

Run `sudo bash deploy/setup-capture.sh` on the VM, then upgrade/recreate the
manager. Existing 1.20.x local capture settings are migrated while unrelated
settings are retained. No workstation capture tunnel is needed. See
[Browser capture setup](CAPTURE.md) and [validation evidence](../clab-backup-ui/VALIDATION.md).

## Changes in 1.20.1 (historical)

Fixes from vetting the 1.20.0 Wireshark capture on a live Ubuntu VM with Edgeshark.
A selected host-namespace target no longer fails with "target changed" whenever any
container starts or stops: the target identity now covers the namespace, root
process, name and engine prefix, and only the interfaces you selected are checked
against fresh discovery. **All host targets** lists a namespace shared by a
host-networked container (the manager itself) once, naming the other as an alias,
and marks loopback-only namespaces. A namespace Edgeshark reports in an unreadable
form is skipped and counted instead of hiding every other target. Prepare capture
stays disabled until an interface is ticked, and node/menu Capture actions are
disabled when the manager reports capture disabled. `check-install` gains an
**Optional packet capture** check. [CAPTURE.md](CAPTURE.md) now states what was
observed: Packetflix 0.9.7 does not reject a mismatched PID, start time or
namespace, so the manager's re-discovery and link expiry are the real stale-target
guards. Root-run helpers (`setup-git.sh --list`, a privileged `check-install`) no
longer leave root-owned Python bytecode in the ordinary owner's source folder, which
blocked removing or re-staging that folder without sudo.

## Changes in 1.20.0 (historical; desktop launch replaced in 1.21.0)

Optional Wireshark capture is available from node actions, either endpoint of a
map link, and a searchable live interface browser. All host targets includes
bridges, physical NICs and other namespaces. Multiple interfaces in one namespace
can be selected together. The manager rechecks selections before preparing a
native Wireshark handoff; packets stream directly from Edgeshark to the workstation.

The workstation handoff introduced in this release was replaced by VM-hosted
browser sessions in 1.21.0. Use the current [capture setup](CAPTURE.md).

## Changes in 1.19.4

Engineer access for VS Code Remote - SSH and the Containerlab extension is now a
setup step instead of a paste-in block. The two errors it removes are
`Extension activation failed. Insufficient permissions. Ensure USER is in the
clab_admins and docker group(s)` and `EACCES: permission denied, mkdir
'/etc/containerlab/...'` from the VS Code file explorer. The new
`deploy/setup-engineer-access.sh` adds one ordinary account to `docker` and
`clab_admins`, makes every trusted lab root a group-writable `clab_admins`
folder with the setgid bit so new files inherit the group, restores the
containerlab SUID mode, and records the account so `start-manager.sh` reapplies
it after operations setup or a containerlab upgrade resets those. The installer
offers it in the standard flow and as menu option 3; `check-install` gains an
**Engineer access** check that names the exact missing piece. Topologies the
manager creates in such a folder are group-editable (0664; 0644 elsewhere)
instead of root-only 0600, so the same lab can be edited in VS Code. The manager
itself is unchanged and still uses sudo through its restricted gateway.

## Changes in 1.19.3

Fixes for the 1.19.2 bug-fix report. The Debug panel and the operations error now
name the real cause when the browser reaches a connected VM but folder browsing and
Git return HTTP 409: previously both said "Check the saved VM password", even though
connected discovery already proves the password. The operations "command not found"
case is now reported as "the clab-discovery SSH session did not run the operations
gateway" with the enable-operations remedy, and the Debug panel classifies it as a
gateway problem instead of an authentication failure. `check-install` gives the same
gateway-specific next step when discovery is connected.

When the web page opens and no VM connection is configured yet, the manager now
prompts for it once, since the VM connection is what makes discovery, operations and
Git work. A configured connection, or one dismissed this session, is not re-prompted.

Guided Git setup (`bash deploy/setup-git.sh`) now asks which repository subfolder
holds each lab, so one repository can hold many labs (for example `bgp`, `eth`, `ip`),
each pushed to its own subfolder, and an already-registered repository can gain a new
subfolder for another lab. Successful setup ends with a clear success banner. See
[GIT-SETUP.md](GIT-SETUP.md) and [GIT-PROGRESS.md](GIT-PROGRESS.md).

This is a source delivery; no Docker image is published. It was installed on a fresh
Ubuntu 24.04 dev VM, where folder browsing, a lab deploy through the operations
gateway, NOS login and backup on two cEOS nodes, a subfolder Git registration and a
pushed Save progress all succeeded, and `check-install` reported no failures. See
[VALIDATION.md](../clab-backup-ui/VALIDATION.md) for the exact evidence and limits.

## Changes in 1.19.2

Integrates the remaining [deployment audit fixes](archive/DEPLOYMENT-AUDIT.md)
with 1.19.1. Topology creation now preserves files created concurrently.
Discovery, scheduled backups and lab/Git operation guards recover from storage
write failures. Failed audit writes no longer fail completed actions, and Debug
panel reports the last audit-write result. Missed events are not replayed.
Git response limits include stderr, and Linux Git timeouts stop descendants
even after the parent exits.

Retains 1.19.1's SSH EOF handling, longer helper/discovery/debug timeouts,
dependency bounds and LF normalization. Install matching manager and helpers
with `bash deploy/install.sh`, keeping existing persistent data, then confirm
Release 1.19.2. See the audit for test evidence and live deployment limits.

Documentation added after publication: the installation guides gain three
paste-in fixes for the VM clock after a Proxmox snapshot rollback, passwordless
root SFTP for WinSCP, and VS Code Remote - SSH with the Containerlab extension.
The installer itself is unchanged and still leaves those choices to you.

## Changes in 1.19.1

Applies the 1.18.1 operations-transport fix to the two remaining SSH readers.
Discovery and Git transfers now wait for stream end-of-file before accepting
the helper's exit status; OpenSSH can report that status while the helper's
final stdout bytes are still queued, which truncated large inspection or Git
envelopes and produced misleading "Invalid containerlab inspection response"
or "Install or refresh the matching Git helper" errors.

The installed discovery helper allows `containerlab inspect --all` 25 seconds
instead of 8 (per-container label lookups stay at 8 seconds), the manager
waits 60 seconds for the helper, the health checker matches that budget, and
a timeout is reported as a timeout rather than a permissions failure. Update
both the image and the host helpers with `sudo bash deploy/start-manager.sh`.

Also: the Git wizard keeps `git clone` attached to the terminal with no
120-second limit; the Debug panel classifies a rejected VM password as an
authentication failure and gives the capabilities probe 90 seconds;
`setup-discovery.sh` explains a missing containerlab or Docker binary instead
of exiting silently; the browser footer fallback version is release-checked;
vendor Ansible collections are pinned to their current major versions; and
`.gitattributes` normalizes every text file to LF.

Prepared from published main `2d34415` (1.19.0) on
`claude/transport-eof-and-helper-timeouts`. Source delivery only; no image
publication, fresh-VM run or live device validation is implied.

## Changes in 1.19.0

Adds a [development debug panel](DEBUG-PANEL.md) available before any lab is imported.
Inspect runtime versions, VM readiness, recent API failures and independent
read-only folder/helper checks, then download a metadata-only JSON report.
Credentials, paths, request payloads and raw logs are excluded.

Fixes a remaining file-browser failure: a successful folder listing no longer
waits for command-capability checks. Files render immediately; failed command
checks disable only optional online controls and show a diagnostic hint.
The existing 1.18.1 SSH stream and gateway fixes are retained.

Run `bash deploy/install.sh` from the complete source root on the VM to update,
then verify the release in Debug panel. Source delivery only; no image
publication or VM deployment is implied.

## Changes in 1.18.1

Fixes operations SSH reads that could stop at the exit-status packet before the
helper's final response arrived. The manager now waits for stream EOF, retains
bounded diagnostics, and distinguishes missing gateway and sudo-permission errors.
The launcher also checks helpers through `clab-discovery` before building the image.

The health checker retains its terminal session for sudo authentication. Earlier
1.17.0/1.18.0 checkers could report administrator access PASS followed by false
failures for every privileged check. On those releases, rerun the same report
with `sudo bash deploy/check-install.sh --owner archtop` (use your ordinary account).
See [the health report guide](HEALTH-CHECK.md) for the complete recovery procedure.

## Changes in 1.18.0

Adds Juniper vQFX and vJunos-switch to node import, NOS credential profiles,
SSH checks, configuration backups and Git progress saves. They use the existing
Junos SSH driver to capture `show configuration | display set | no-more`.

| Device | Containerlab kind | Also recognized by the manager |
|---|---|---|
| Juniper vQFX | `juniper_vqfx` | `vr-vqfx`, `vqfx` |
| Juniper vJunos-switch | `juniper_vjunosswitch` | `vr-vjunosswitch`, `vjunosswitch` |

Use the canonical kind in new Containerlab YAML. Select the matching NOS in
**Credentials** and enter that device's actual login. Passwords are not filled in
automatically. Previously saved unknown nodes can use **Sync from VM**, or choose
the NOS in **Node details → Edit connection**. Check **Include in backups** for
each intended node; sync preserves existing selection and credential choices.
Captured files use `.set` internally and `junos-display-set` in Git manifests;
individual downloads are named `vQFX_*.cfg` or `vJunos-switch_*.cfg`.

Build the matching manager and update its host helpers using the source launcher
before testing a device login and backup. Live configuration restore remains
unavailable. Containerlab documents vJunos-switch as unsupported inside a VM
because of its nested architecture; adding this manager adapter does not change
that deployment requirement. See the [vQFX](https://containerlab.dev/manual/kinds/vr-vqfx/)
and [vJunos-switch](https://containerlab.dev/manual/kinds/vr-vjunosswitch/) kind guides.

The Junos support was merged in main `7331e9a` (1.18.0). Live SSH/backup
validation of these two NOS images remains pending. The 1.18.1 fixes are prepared
from that baseline; publication and a complete fresh-VM validation remain pending.

## Changes in 1.17.0

Adds a separate installation checker and connects installer menu **3** to the
full report. It verifies services, persistent state, SSH/SFTP policy, helper
execution through `clab-discovery`, actual topology folders over saved SSH,
and owner-scoped Git checkout readiness. Optional checks cover administrative
WinSCP, KVM and remote Git reads. It gives recovery commands and text/JSON
results without automatically repairing setup or running lab/push operations.

Prepared locally from published main `7c25648` (1.16.1); publication and a full
fresh-VM validation of 1.17.0 remain pending. The initial installation's short
HTTP/version check remains separate from this final report after browser setup.

## Changes in 1.16.1

Package setup now shows VM UTC time and NTP status before APT updates, with a
bounded wait for an already-active time service. It identifies future-dated or
expired repository metadata and gives clock/mirror recovery steps while keeping
APT validation enabled. The same checks cover Git/GitHub CLI package setup.
See [clock recovery](FRESH-VM-GUIDE-V2.md#recovery-c) to resume a paused install.
These changes are on published main `7c25648`; a complete fresh-VM run of 1.16.1
has not been verified. For WinSCP access to root-owned files, complete the
[manual administrative SFTP setup](FRESH-VM-GUIDE-V2.md#winscp-admin-sftp).

## Changes in 1.16.0

Run `bash deploy/install.sh` as your ordinary VM account for a consolidated
terminal installer: prerequisites, optional APT media repair, password/helpers,
image build/start, HTTP/version checks, then Git setup. Separate menu entries
reopen Git setup or check a running manager without rebuilding it.

The Git terminal wizard has numbered steps, retry/cancel recovery, owner and
identity checks, and preserves existing registration settings. Start with the
[guided installation guide](INSTALL.md); detailed manual instructions remain available.

## Changes in 1.15.3

Guided setup can resume an existing checkout with `--guided --repo PATH`, repair
missing/invalid commit identity, and show the exact source-script path after a
failed registration. Setup guidance distinguishes Linux owner, GitHub login,
commit identity and the two project directories. See [Git setup](GIT-SETUP.md).

## Changes in 1.15.2

Guided Git setup rejects GitHub page URLs before cloning, explains the local
checkout directory and reports package failures with recovery instructions.
See [package installation recovery](GIT-SETUP.md#package-installation-recovery)
for the Ubuntu `file:/cdrom` error. This source is prepared locally for publication.

## Changes in 1.15.1

Repository repair: VERSION now matches the 1.15.1 app/helpers. Run
`python3 deploy/verify-release.py` to check the complete source before publishing
or installing. The launcher runs this check automatically. See
[repository audit and maintenance](REPOSITORY-MAINTENANCE.md) for the cleanup and
repair of affected fresh installations.

Guided Git onboarding now uses the existing VM account, prepares HTTPS login and
commit identity, and checks repository readiness before registration. Run
`bash deploy/setup-git.sh` without sudo. Start with [GIT-SETUP.md](GIT-SETUP.md).
Missing identity is caught before an export writes or stages files. Helper-only
upgrades retain existing registrations; unchanged re-registration retains revisions.

## Git progress introduced in 1.15.0

- **Save progress** captures the chosen devices, exports a complete snapshot to
  the registered VM repository, commits exact changed files and pushes. Capture,
  commit and push outcomes remain separate, with retry from the saved artifacts.
- **Save locally**, named checkpoints and an explicitly selected baseline support
  offline work and milestones. History, comparison and version ZIP downloads
  let the engineer retrieve an earlier configuration set.
- A restricted host Git helper runs Git as the registered Linux owner using the
  owner's external HTTPS authentication. It does not copy tokens into the manager.
- Repository changes, unexpected staged work and remote conflicts require
  attention; no force push, automatic stash or destructive reset is offered.
- Pending saves retain their context across restarts and block destructive manager
  cleanup until resolved or explicitly dismissed while keeping the snapshot.
- Version retrieval downloads files. Applying configurations to running devices
  is unavailable until the NOS restore adapters are validated.

Read [Save lab progress to Git](GIT-PROGRESS.md) for setup, buttons, architecture,
recovery and account boundaries. This remains a trusted-operator UI without
browser sign-in; a registered owner is a Linux execution identity.

## Changes in 1.14.0

- Sidebar order and labels follow the revised workflow; supported device types show
  the active release. View running lab details opens a wider inspection table.
- Topology opens first, followed by Nodes and Backup history; Credentials and
  Action logs are available from the More dropdown.
- Edit diagram adds movable text, boxes, circles and lines with appearance controls,
  Undo and unsaved-change protection. Save persists annotations in manager storage.
  Export current edits as annotations JSON or editable draw.io without changing VM files.
- Concurrent map edits fail with a clear conflict instead of overwriting a newer map.
- The master wiki now documents password setup, persistence, migration and recovery,
  and the updated UI. The VM password behavior from 1.13.0 is included.

## Changes in 1.13.0

VM connections now use a user-created password. First host setup prompts securely
for the clab-discovery account password before launching the manager. Enter that
same password in VM connection; it is encrypted in persistent storage. Routine
upgrades retain it, and --reset-password supports recovery. SSH restrictions now
apply to the account independently of client keys. Existing key connections require
one-time migration; device credential options remain unchanged.

## Changes in 1.12.1

- **Deploy New Lab** opens in the same tab. Choose the large **Lab Topologies**
  button to browse; no dialog opens automatically. **Back to lab manager** returns
  to the saved workspace.
- Only `.clab.yaml` / `.clab.yml` files and navigation folders appear in the browser.
- **Deploy lab** opens a concise confirmation, with the command in expandable details.
- **Start lab** and **Destroy lab** appear beside deployment status. Start deploys
  an absent lab or starts stopped containers. Destroy is separate from Remove lab.

See [1.12.1 update and build instructions](archive/UI-UPDATE-1.12.1.md). This is a source
release; the previously supplied Hub image `archtop/clab-backup:1.12.0` does not
include these changes. No new Hub image has been published by this workspace.

## Changes in 1.12.0

The workspace opens directly without an access-token login. VM and device SSH
credentials remain encrypted in persistent storage. Keep VM connection enabled
for discovery, automatic file import and reviewed lab commands.

- Retained: lifecycle commands, inspect/save, SSH all, favorites, VM projects,
  new project creation, optional repository downloads, backup history and SuperPuTTY.
- Removed: existing VM YAML editing, lab path/link/folder shortcuts, separate
  layout control, SSHX/GoTTY and fcli. VM project files open read-only.
- One interactive draw.io editor with full editable export: nodes, connections,
  interface labels, groups, notes, colors and positions. No online service needed.
- Inspect results appear as a table. VM projects use an expandable vertical tree.
- Topology header offers SSH all and Back up all configs, including expanded view.
- Right-click an excluded lab to clear its exclusion without importing it.
- Manager settings → Start fresh clears manager data and backup files after
  confirmation, retaining the VM connection and leaving VM labs/files untouched.

[VM connection setup and troubleshooting](VM-CONNECTION.md) covers passwords, permissions,
helper repair and upgrades. [Lab commands](LAB-OPERATIONS.md) documents retained actions.

## Setup and import improvements retained from 1.10.0

- **Source-build launch command:** `sudo bash deploy/start-manager.sh` updates the installed
  VM helper, verifies its file-transfer protocol and version, prepares storage,
  builds the image and recreates the Compose service. Existing passwords/data are retained.
  First setup prompts for the discovery account password. An old helper cannot silently
  survive a normal upgrade; verification failures stop before container recreation.
- **Import confirmation:** discovery reads files automatically and shows new labs as
  Ready to import. Clicking a lab previews its name, node/link counts, source files
  and warnings. Only **Import lab** saves the workspace and inventory credentials.
  Cancel saves no workspace. Import again also requires confirmation and retains
  the exclusion if cancelled. Existing saved workspaces remain available.
- Confirmation expires after five minutes and is rejected if files, VM connection or
  exclusion state change. Refreshes and older API clients cannot bypass confirmation.
- Outdated inspection-only helpers now show an actionable message in VM connection
  and the sidebar instead of appearing ready for automatic file import.

## Feature baseline retained from earlier releases

- **Remove lab** clears only that saved manager workspace and its history entries.
  It never stops containers or changes VM lab files. Backup files and audit logs
  remain on disk; other labs and the VM connection are retained.
- Removed labs are excluded from automatic import by default. Use **Import again**
  in the sidebar, or uncheck the exclusion in the removal dialog to test automatic
  discovery on its next check. Queued/running jobs must finish before removal.

- Automatic retrieval of deployed lab YAML, annotations, generated inventory and topology data, followed by import confirmation.
- File change detection and **Sync from VM**, preserving saved node settings, profiles and backup history.
- Helper upgrade with `deploy/setup-discovery.sh --update-helper` retains the password after first migration.
- Standalone Compose deployment with Linux host networking and automatic restart.
- Host directory `/srv/containerlab-node-manager/data` mounted at `/data`, using
  explicit UID/GID 10001 and a one-time setup script.
- Original `.clab.yaml` registration, optional annotation maps, and updates that
  preserve matching node identities, credentials, schedules and configuration history.
- Encrypted VM password settings, fixed read-only SSH discovery every 30 seconds,
  manual refresh, stored SSH fingerprint and changed-key rejection.
- Running, Partially running, Stopped, Not deployed, Unknown and Unlinked lab states.
- Automatic node management addresses with explicit manual endpoint overrides.
- Deployment-aware scheduling for linked labs; offline/unknown labs retain their
  data and wait until they are available. Existing inventory-only behavior remains.

The list and map both retain node details, per-node backups and browser SSH tabs.
SuperPuTTY XML exports use the lab name. Junos, IOS-XR and EOS backup adapters and
historical downloads remain. Host CPU/memory monitoring is not part of this release.
