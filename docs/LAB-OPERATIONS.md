# Lab operations

## Enabling and upgrading

Lab operations (deploy, destroy, inspect and the rest of this page) are enabled by
the guided installer's *Lab operation access* question and refreshed by every
upgrade (`bash "$HOME/projects/clab-manager/deploy/install.sh"`, menu 1). The
launcher it runs can also be used on its own, from any directory:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/start-manager.sh" --enable-operations --lab-root /etc/containerlab
sudo docker compose -f "$HOME/projects/clab-manager/clab-backup-ui/compose.yml" logs --tail=30 backup-ui
```

The launcher first checks source release consistency, refreshes and verifies the
host helpers, refreshes the browser Wireshark and Grafana stacks, builds the manager
image without cache and recreates the manager. Open `http://VM_IP:8081`; no UI login
is required. Linux host networking uses this port directly, without `-p` forwarding.
Data stays in `/srv/containerlab-node-manager/data` (UID/GID 10001, mode 700).

See [VM connection setup and recovery](VM-CONNECTION.md) and the
[installation guide](INSTALL.md). Lab commands require the dedicated
clab-discovery account, its password and the installed helper mode. Direct
inspection accounts do not automatically gain the operations protocol.

## Where the commands are

Everything containerlab can do with a lab is under **Lab actions ▾** in the lab header
(or right-click a lab card on Home; keyboard: Shift+F10). The menu carries the everyday
actions — **Start lab** (or *Start stopped devices*), **Stop devices**, **Restart
devices**, **Redeploy lab…**, **Destroy lab…** — and **All lab operations…** opens the
complete list in three groups: *Deployment*, *Lab tools* and *Danger*. A disabled item
says why underneath it (the VM is not connected, the lab is not running, another
operation is running, the lab has no topology file on the VM). The **Manager ▾** menu in
the top bar holds the actions that are not about one lab: **Deploy a new lab…**,
**Running labs on the VM…** and **Operation history…**.

| Action | Behaviour |
|---|---|
| Start lab / Deploy lab, Redeploy lab, Destroy lab | Operate on the original VM topology. Destroy always runs `containerlab destroy --cleanup`, so the containers and the generated lab folder (`clab-<name>`) go together and the next deploy starts clean; the review names the folder under *Technical details* before you confirm. Redeploy keeps that folder unless you choose *Redeploy lab and clear the lab folder…*, and falls back to destroy then deploy when necessary. |
| Apply topology changes | Applies the original VM YAML to the running lab when the installed containerlab supports it. |
| Start / Stop / Restart devices | Every device of the lab. Stop keeps the containers; Destroy removes them. |
| Show running devices, Running labs on the VM | A readable table (topology, lab, device, type/image, state/health, IPv4/IPv6) in the operation window. Failed or incomplete output stays visible for diagnosis. |
| Save device configurations | containerlab's kind-dependent save command. The manager's own backups (Tools › Configuration backups) and *Save progress* are separate. |
| Open all CLIs ↗ | A launcher page with one row per device (state pill, Open CLI ↗) and *Open all ready CLIs*. Allow pop-ups; at most 32 CLIs at once. |
| Add to / Remove from favourites | Sorts the lab first on Home. |
| Edit map | Move devices and notes, add text, boxes, circles and lines, style, undo, save and export the map as JSON or draw.io. |
| Telemetry settings… | Telemetry on or off for this lab, the login used for gNMI, why a device is not streaming, retry, removal of the lines the manager added, and the network dashboard's state. |
| Delete the topology file from the VM… | Deletes an undeployed topology file after keeping a recovery copy; refused while the lab is running. |
| Deploy a new lab… / Lab topologies on the VM | The topology browser: expand the trusted lab folders and pick a `.clab.yaml`/`.clab.yml`. Existing files are read-only; the same browser opens in place from Home. |
| Write a new topology… | Creates a new topology file on the VM after a structure preview and confirmation; never replaces an existing file. |
| Add to My labs without starting / Deploy lab | Read an existing file and add the lab to My labs without deploying, or deploy it: *Deploy lab* saves the workspace (devices, map, VM source path) first and then reviews the containerlab command, so the lab is in My labs at once and nothing needs importing afterwards. |
| Download a lab from GitHub… / Browse popular labs… | Optional HTTPS download into the VM's lab folder, followed by a review of the files and a separate deployment. |

Removed in earlier releases: existing VM YAML editing, copy topology path, manual
Select/link VM project shortcut, Open VM folder lab shortcut, separate Edit
layout, horizontal/vertical diagram exports, SSHX/GoTTY and SR Linux fcli. These
commands are rejected by the current manager and installed helper. Upgrade the
host helper as well as the image. Previously created sharing containers are not
automatically stopped or deleted by an upgrade; manage those on the VM if present.

## Every operation is reviewed first

A lab operation never runs from a single click. The review names the action in plain
words (*Destroy BGP_TheoryToPractice?*, *Stop devices?*), says what happens to the
devices, warns that **configuration changes you have not saved are lost** for the
disruptive ones, shows when progress was last saved to Git (in red when it never was, or
when a lab operation ran after the last save) and offers **Save progress first** when the
lab has a save location. The exact containerlab command, the affected devices and the
cleanup folder are under *Technical details*. Confirming a lifecycle action on the open
lab closes the review and reports in the lab banner (*Stopping devices…* with **View
output**); the result window opens on its own only for actions that produce something to
read, such as *Show running devices*.

## Device readiness after deployment

A running container is not a network OS that accepts a login: cEOS, vJunos and XRv9k
boot for one to several minutes. For every linked lab the manager logs in to each
running device over SSH and asks for `show version` every 20 seconds (with its
credential profile, the inventory login, or containerlab's documented default for the
kind) until the network OS answers. The lab header shows *Starting* and *n of m devices
ready*; each device carries a state pill (*Starting*, *Ready*, *Needs credentials*,
*Needs attention*, *Unavailable*) with a sentence that says what to do, on the Devices
tab, in the device panel and on the map. **Open CLI** and **Open all CLIs** enable as
devices answer, and a login check runs once by itself when every device has answered,
so its `show version` result is under Tools › Configuration backups › *Login checks*
without a click. A device that stops or restarts must answer again. A failed automatic
check sends its devices back to *Starting* and is retried up to three times per boot. A
login refused three times in a row reads *Needs attention* with the remedy (add or fix
the credentials); **Test login now** in the device panel stays available for a manual
retry. Every backup or login check runs with its own empty `known_hosts`, so a
redeployed lab (new SSH host keys) never fails with *host key mismatch*.

## Telemetry after readiness

With telemetry on (the default for labs created since 1.23.0; earlier labs turn it on
once under **Lab actions ▾ › Telemetry settings…**), every device that has answered
`show version` is checked over SSH for its gNMI service, missing lines are added with
the NOS's scoped commit, and a gNMI subscription streams interface rates, link state and
BGP neighbours into memory for Prometheus to scrape. **Open lab map ↗** (or **Open
network dashboard ↗**) on the Tools tab opens the lab's Grafana map or dashboards,
starting Grafana on the VM first when it is stopped (it stops itself after 15 minutes
without a viewer; *Telemetry settings…* shows its state and can stop it now). A stop,
destroy, redeploy or removal clears the session. Details, per-NOS support and the
acceptance procedure are in [TELEMETRY.md](TELEMETRY.md).

## The map and its editor

Choose **Edit map** (Topology tab, Tools tab or Lab actions ▾) to move devices, add
text, boxes, circles and lines, or edit their appearance. Undo reverses edits; closing
offers to discard unsaved changes. Save persists the manager map. *Download map file*
(annotations JSON) and *Export draw.io* include unsaved edits without writing VM files.
Concurrent edits are rejected if the saved map changed; reopen it before editing again.

The editor changes device positions; connections follow the devices. The full export
contains editable devices, connections, interface labels, groups/shapes, notes, colours
and positions. Contained devices are grouped with their surrounding annotation so they
move together in draw.io. Router, switch and server symbols use native editable diagram
elements. Imported custom icon artwork is represented by a generic network symbol.

The exported `.drawio` is uncompressed editable XML, following the
[draw.io document format](https://www.drawio.com/docs/reference/diagram-generation/).
Open it in diagrams.net or its desktop application. No external service is used
for export. Live CLI and backup actions stay in Node Manager and are not embedded in
the exported file. This is the manager's layout editor, not an embedded copy of
the full diagrams.net application. Structural topology changes are made in the
original VM YAML and imported/synced separately.

The map's **More ▾** menu (also in the expanded map) offers **Open all CLIs ↗** and
**Back up all configurations…**. Back up all reviews every device that can be backed up
now, including devices not selected for scheduled backups, and lists the devices it
will skip and why. Right-click a device on the map for Open CLI, Capture traffic, Back
up configuration and Device details.

## Review and persistence

Every submitted host command requires a preview and confirmation. Review tokens
expire after five minutes and bind the VM connection, original file digest and
relevant deployment state. A change requires another preview. Output and outcome
persist in **Operation history…** (Manager ▾ or Lab actions ▾); interrupted jobs require
inspection before retrying. Lifecycle commands can interrupt CLI sessions. Manager
backups/import changes are blocked during an active lab operation.

Discovery matches imported lab names to the original VM topology path. Open
**Manager ▾ › Deploy a new lab…** to add an undeployed topology. **Sync topology from VM**
(Lab actions ▾ or Advanced › Deployment details) refreshes imported data without
overwriting saved connection settings. Saving a manager layout never rewrites the
original annotations file; a later topology import can replace it.

## Trusted project roots and optional downloads

The root-owned `/etc/clab-manager/operations.json` records trusted roots, fixed
binaries and optional network permission. Defaults include `/etc/containerlab`
and `/srv/containerlab-node-manager/projects`. Add a real directory with:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-operations.sh" --lab-root /your/lab/projects
```

Browse is limited to these roots, rejects symlink paths and caps each folder at
500 entries. File reads are capped at 1 MiB. Topologies are trusted VM code:
Containerlab can execute hooks, mount files and pull images. Everyone who can
reach this manager's port has access to its enabled lab operations.

Optional cloning/catalog downloads require Git and network access on the VM:

```bash
sudo apt install -y git
sudo bash "$HOME/projects/clab-manager/deploy/setup-operations.sh" --allow-downloads
```

They are disabled by default. To revoke downloads or remove a trusted root, use
`sudoedit /etc/clab-manager/operations.json`; set `network` to false or remove the
root. Setup preserves existing roots and network permission unless you edit them.
Offline users can copy complete lab projects into a trusted root and browse them.

## Recovery

Delete undeployed VM YAML preserves a copy in `.clab-manager-history` next to the
original file. Its operation result records the exact recovery path. Restore it
manually on the VM if needed. **Remove from this manager** (Advanced › Danger zone) and
**Start fresh** (Manager ▾ › Manager settings…) have different, manager-only scope;
neither deletes original VM sources or deployment containers.

If discovery works but commands fail, repair the operations gateway and permissions
using [VM-CONNECTION.md](VM-CONNECTION.md). A stale image-only upgrade does not
refresh host scripts. Updating both through start-manager is the normal workflow.
The launcher checks the restricted gateway before building. For the older checker's
false sudo failures and the operations SSH response fix, follow
[the health report recovery procedure](HEALTH-CHECK.md#recover-the-operations-helper-error).

## Save lab progress to Git

For capture, commit and push into an existing owner-scoped repository, follow
[GIT-SETUP.md](GIT-SETUP.md). This is separate from Containerlab’s kind-dependent
Save configurations command. Use the existing VM account, and retry the original
manager save after authentication or export errors. No extra Linux user is required.

## Apply a saved configuration to a running node

A student who has saved a Junos configuration can put it back onto the running node
without destroying the lab, editing startup files, redeploying containerlab or
rebooting the router. On the **Progress** tab, every saved version — the lab's own
*Latest*, *Checkpoints* and *Baseline*, and the *Instructor and reference versions* kept
in other folders of the same repository — offers **Apply to running lab…** when it holds
a restore-grade Junos state; the lab does not have to change its save location first.
The review lists the source version, the devices, and for each whether it already
matches the saved state, how many differences there are, or why it is skipped. The manager backs up the current configuration of every target first, loads the
saved configuration as a complete replacement (`load override`), checks it, and activates
it with a commit that rolls back on its own if management is lost; it then captures the
node again and compares it to the saved state. Live restore is supported for
`juniper_cjunosevolved` and `juniper_vjunosswitch`; IOS-XR and EOS versions remain
view/download only. This uses the manager's direct SSH path to the node and is separate
from Containerlab's Save configurations command. See
[GIT-PROGRESS.md](GIT-PROGRESS.md#apply-a-saved-configuration-to-a-running-node).
