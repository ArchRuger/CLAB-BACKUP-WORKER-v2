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
complete list in three groups: *Deployment*, *Lab tools* and *Danger*. **Advanced options**
at the bottom of the menu unfolds in place (click, Enter or ArrowRight) and holds **Import map…**,
**Edit map**, **Telemetry settings…** and **Operation history…**. A disabled item
says why underneath it (the VM is not connected, the lab is not running, another
operation is running, the lab has no topology file on the VM). The **Manager ▾** menu in
the top bar holds the actions that are not about one lab: **Deploy a new lab…**,
**Running labs on the VM…** and **Operation history…**.

| Action | Behaviour |
|---|---|
| Start lab / Deploy lab, Redeploy lab, Destroy lab | Operate on the original VM topology. Destroy runs `containerlab destroy --cleanup` (whenever the installed containerlab offers `--cleanup`; there is no variant without it), so the containers and the generated lab folder (`clab-<name>`) go together and the next deploy starts clean; the review names the folder under *Technical details* before you confirm. Redeploy keeps that folder unless you choose *Redeploy and clear the lab folder…* (*Redeploy lab and clear the lab folder…* under All lab operations…), and falls back to destroy then deploy when necessary. |
| Apply topology changes | Applies the original VM YAML to the running lab when the installed containerlab supports it. |
| Start / Stop / Restart devices | Every device of the lab. Stop keeps the containers; Destroy removes them. |
| Show running devices, Running labs on the VM | A readable table (topology, lab, device, type/image, state/health, IPv4/IPv6) in the operation window. Failed or incomplete output stays visible for diagnosis. |
| Save device configurations | containerlab's kind-dependent save command. The manager's own backups (Tools › Configuration backups) and *Save progress* are separate. |
| Open all CLIs ↗ | A launcher page with one row per device (state pill, Open CLI ↗) and *Open all ready CLIs*. Allow pop-ups; at most 32 CLIs at once. |
| Add to / Remove from favourites | Sorts the lab first under *All labs* on Home; *Recent labs* is ordered by the last successful deploy or redeploy this manager ran, and nothing else (visits, saves and favourites do not reorder it). |
| Edit map | Move devices and notes, add text, boxes, circles, lines and groups, style, undo and redo, save and export the map as JSON or draw.io; never changes devices, links or the topology file (see *The map and its editor*). |
| Telemetry settings… | Telemetry on or off for this lab, the login used for gNMI, why a device is not streaming, retry, removal of the lines the manager added, and the network dashboard's state. |
| Delete the topology file from the VM… | Deletes an undeployed topology file after keeping a recovery copy; refused while the lab is running. |
| Deploy a new lab… / Lab topologies on the VM | The topology browser: expand the trusted lab folders and pick a `.clab.yaml`/`.clab.yml`. Existing files are read-only; the same browser opens in place from Home. |
| Upload a file from this computer… (Home › Deploy, and the link in the topology browser) | For a topology file that is on your computer: the browser reads it, the manager checks that it is a topology it can read, you see the text and where it will be written, **Create file on the VM…** runs as a reviewed operation, and **Deploy or add this lab…** continues as for any file on the VM. Only that one file is uploaded (up to 1 MiB); files it refers to must be on the VM. |
| Build a lab visually… / Edit visually… | Opens the [lab builder](LAB-BUILDER.md): draw devices and links, then save the lab folder to the VM through a review. *Edit visually…* opens an existing topology file; saving again is only possible while the lab is not deployed and keeps a copy of the previous version. |
| Write a new topology… | Creates a new topology file on the VM after a structure preview and confirmation; never replaces an existing file. |
| Add to My labs without starting / Deploy lab | Read an existing file and add the lab to My labs without deploying, or deploy it: *Deploy lab* saves the workspace (devices, map, VM source path) first and then reviews the containerlab command, so the lab is in My labs at once and nothing needs importing afterwards. |
| Download a lab from GitHub… / Browse popular labs… | Optional HTTPS download into the VM's lab folder, followed by a review of the files and a separate deployment. |

Removed in earlier releases: editing existing VM YAML as text (the lab builder's reviewed *Save changes to the VM…* is the only way the manager replaces a topology file, and only for a lab that is not deployed), copy topology path, manual
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
once under **Lab actions ▾ › Advanced options › Telemetry settings…**), every device that has answered
`show version` is checked over SSH for its gNMI service, missing lines are added with
the NOS's scoped commit, and a gNMI subscription streams interface rates, link state and
BGP neighbours into memory for Prometheus to scrape. **Open lab map ↗** (or **Open
network dashboard ↗**) on the Tools tab opens the lab's Grafana map or dashboards,
starting Grafana on the VM first when it is stopped (it stops itself after 15 minutes
without a viewer; *Telemetry settings…* shows its state and can stop it now). A stop,
destroy, redeploy or removal clears the session. Details, per-NOS support and the
acceptance procedure are in [TELEMETRY.md](TELEMETRY.md).

## The map and its editor

Choose **Edit map** (Topology tab, Tools tab or Lab actions ▾ › Advanced options). For a lab whose
topology file the manager has, it opens the same editor as the [lab builder](LAB-BUILDER.md), on the
lab's own map and for the drawing only: drag devices, use a generated layout, add and style text,
rectangles, circles, lines and groups (drag devices into a group), copy and paste annotations, set link
label offsets, the link label mode and the grid. The bar above the editor adds **Undo** / **Redo**
(Ctrl+Z, Ctrl+Shift+Z; map changes only), **Device look…** (a device's icon, colours and label) and
**Link labels…** (how far a link's interface names sit from its devices). Devices and links cannot be added, changed or removed
there, nothing is deployed and the running lab is not touched; the editor cannot send anything but the
map to the manager. **Save map** stores it and the Topology tab follows; **Back to the lab** asks when
something is unsaved. *Download map file* gives the full annotations document, *Export to draw.io* uses
the saved map, and *Import map file…* replaces the map with a file from your computer. A map that was
changed elsewhere since it was opened is not overwritten: reopen it. A lab without a topology file in the
manager (imported from an inventory) opens a simpler dialog with text, boxes, circles, lines and Undo.
The Topology tab draws less than the editor can store: line arrows, rounded text backgrounds and nested
group levels are kept in the map document and shown by the editor, but are not drawn on the Topology tab
(rotation, colours, borders, corner radius, label offsets and the label mode are).

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
**Back up all configurations**. Back up all covers every device that can be backed up
now, including devices not selected for scheduled backups. When every device is ready it
starts at once; when some cannot be backed up, or a job is already running, it first lists
the devices it will skip and why, and you confirm with **Back up N devices**. Right-click a device on the map for Open CLI, Capture traffic, Back
up configuration and Device details.

## Review and persistence

Every submitted host command requires a preview and confirmation. Review tokens
expire after five minutes and bind the VM connection, original file digest and
relevant deployment state. A change requires another preview. Output and outcome
persist in **Operation history…** (Manager ▾ or Lab actions ▾ › Advanced options); interrupted jobs require
inspection before retrying. Lifecycle commands can interrupt CLI sessions. Manager
backups/import changes are blocked during an active lab operation.

A lab that already runs on the VM but is not in My labs is listed under **Manager ▾ › Labs
found on the VM…** (Home itself carries no such list, except the short *Already running on the
VM* list of the first-run page while My labs is empty). **Add to My labs** reads the lab's
files, shows them for review and imports only when you confirm with **Add lab**; discovery
never imports a lab by itself. A lab removed with the hide option stays listed there as
hidden until **Import again** or **Stop hiding**.

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

A student who has saved a Junos, EOS or IOS XR configuration can put it back onto the
running node without destroying the lab, editing startup files, redeploying containerlab
or rebooting the router. On the **Progress** tab, every saved version — the lab's own
*Latest*, *Checkpoints* and *Baseline*, and the *Instructor and reference versions* kept
in other folders of the same repository — offers **Apply to running lab…** when it holds
a restore-grade state for at least one supported device; the lab does not have to change
its save location first. The review lists the source version, the devices, and for each
whether it already matches the saved state, how many differences there are, or why it is
skipped — including a device whose platform cannot be restored yet, whose saved version
predates its platform's restore support, or an IOS XR device whose saved configuration
defines a `banner` (pasting one back in safely is not supported yet). The manager backs
up the current configuration of every target first, loads the saved configuration as a
complete replacement inside the device's own transaction (Junos `load override`; EOS a
configuration session reset first; IOS XR `commit replace`, which replaces the whole
configuration natively), and activates it with a timed recovery that the device undoes on
its own if management is lost. The manager then reconnects for the whole undo window to
confirm the change; on IOS XR only the CLI session that armed the change can confirm it,
so the manager keeps that session open and confirms on it once the reconnect has proved
management survived. EOS also saves the confirmed change to startup, since it does not do
that on commit; IOS XR persists a confirmed change immediately. The manager then captures
the node again and compares it to the saved state. Live restore is supported for Junos
(`juniper_cjunosevolved`, `juniper_vjunosswitch`), Arista EOS (`arista_ceos`) and Cisco
IOS XR (`cisco_xrv9k`). This uses the manager's direct SSH path to the node and is
separate from Containerlab's Save configurations command. See
[GIT-PROGRESS.md](GIT-PROGRESS.md#apply-a-saved-configuration-to-a-running-node).
