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
host helpers, refreshes the browser Wireshark stack, builds the manager
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
actions — **Start lab** (or *Start stopped devices*), **Stop devices**, **Restart all
devices…**, **Redeploy lab…**, **Destroy lab…** — and **All lab operations…** opens the
complete list in three groups: *Deployment*, *Lab tools* and *Danger*. **Advanced options**
at the bottom of the menu unfolds in place (click, Enter or ArrowRight) and holds **Import map…**,
**Edit map**, **Operation history…** and, only while the lab still records configuration lines the
retired telemetry feature added, **Retired telemetry configuration…** (see [TELEMETRY.md](TELEMETRY.md)). A disabled item
says why underneath it (the VM is not connected, the lab is not running, another
operation is running, the lab has no topology file on the VM). The **Manager ▾** menu in
the top bar holds the actions that are not about one lab: **Deploy a new lab…**,
**Running labs on the VM…** and **Operation history…**.

| Action | Behaviour |
|---|---|
| Start lab / Deploy lab, Redeploy lab, Destroy lab | Operate on the original VM topology. Destroy runs `containerlab destroy --cleanup` (whenever the installed containerlab offers `--cleanup`; there is no variant without it), so the containers and the generated lab folder (`clab-<name>`) go together and the next deploy starts clean; the review names the folder under *Technical details* before you confirm. Redeploy keeps that folder unless you choose *Redeploy and clear the lab folder…* (*Redeploy lab and clear the lab folder…* under All lab operations…), and falls back to destroy then deploy when necessary. |
| Apply topology changes | Applies the original VM YAML to the running lab when the installed containerlab supports it. |
| Start / Stop / Restart all devices | Every device of the lab. Stop keeps the containers; Destroy removes them. *Restart all devices…* is containerlab's lab-wide restart (every container stops and starts with its links kept); one device is *Restart device…* below. |
| Restart device… (one device: right-click it on the map, or *Details* in the Devices view) | containerlab's node-scoped restart of that one device (`containerlab restart --node <device>`, the operation the Containerlab VS Code extension's *Restart node* runs): the container stops and starts again with its links kept, so neighbours keep their wiring; a stopped device takes the start/restore path. The review names the device and the lab, warns that its CLI sessions and traffic through it drop and that neighbours lose their adjacencies to it, and lists that one device as affected. Nothing is saved, backed up, reset or reapplied; the device reads *Restarting*, then *Starting* until it accepts a login again (a login refused in the fifteen minutes after a restart, start or deploy the manager performed still reads *Starting*: IOS XR answers SSH before it accepts logins). A device stopped with `docker stop` outside containerlab has already lost its links; the job says how many links were restored. When a neighbour's container is not running, the review names it and says what follows: a neighbour stopped by the manager, the extension or `containerlab stop` keeps its link ends parked and the link comes back; one that exited on its own or was stopped with `docker stop` took the link with it, the job then reports *n of m links restored* with the neighbour named, and the device waits for all its interfaces before it boots (containerlab tells the image how many to expect: cEOS gives up waiting after five minutes, a VM-based image waits for good). Start the neighbour first, or redeploy the lab. Known limits, each named in the review before the student confirms: a vJunos-switch container cannot be started a second time (its launcher fails without the `init.conf` it renamed on the first start), so its restart is reported as failed by the job, with *Redeploy lab* as the way out; an XRv9k container's launcher picks the VM disk by file name at every start, and after the first start a second copy of the pristine image sorts first, so the first restart after a deploy boots the device from a fresh disk: it comes back Ready with its factory configuration and everything configured since the deploy is gone (back up first, then *Replace running configuration*). |
| Show running devices, Running labs on the VM | A readable table (topology, lab, device, type/image, state/health, IPv4/IPv6) in the operation window. Failed or incomplete output stays visible for diagnosis. |
| Save device configurations | containerlab's kind-dependent save command. The manager's own backups (Tools › Configuration backups) and the header's **Save** are separate. |
| Open all CLIs ↗ | A launcher page with one row per device (state pill, Open CLI ↗) and *Open all ready CLIs*. Allow pop-ups; at most 32 CLIs at once. |
| Add to / Remove from favourites | Sorts the lab first under *All labs* on Home; *Recent labs* is ordered by the last successful deploy or redeploy this manager ran, and nothing else (visits, saves and favourites do not reorder it). |
| Hide from Home / Show on Home | Takes the lab's card off Home (both tabs) and nothing else: the lab stays in My labs with its devices, backups, backup history, saved progress and Git binding; nothing on the VM changes, a running lab keeps running, and the background discovery never puts the card back by itself. Home says how many labs are hidden. Two ways back: **Choose a file on the lab VM…** › the lab's topology › *Add to My labs without starting* or *Deploy lab* (the same lab, not a second workspace), or **Manager ▾ › Labs found on the VM…** › *Hidden from Home* › **Show on Home**. This is not *Remove from this manager* (Advanced › Danger zone), which forgets the workspace. |
| Edit map | Move devices and notes, add text, boxes, circles, lines and groups, style, undo and redo, save and export the map as JSON or draw.io; never changes devices, links or the topology file (see *The map and its editor*). |
| Delete the topology file from the VM… | Deletes an undeployed topology file after keeping a recovery copy; refused while the file is deployed, also when it is deployed under another lab name (found by its topology path). |
| Deploy a new lab… / Lab topologies on the VM | The topology browser: expand the trusted lab folders and pick a `.clab.yaml`/`.clab.yml`. Existing files are read-only; the same browser opens in place from Home. |
| Lab files (Lab actions ▾, and the Advanced tab) | The same dialog opened for one lab, titled *Lab files · <lab>*. On a VM whose helper reports `diagnostics` it is in *files mode*: every listing it makes (the first, a folder you expand, **Up one folder**, **All lab folders**) also shows the text and configuration files the manager can read (`.yaml`, `.yml`, `.json`, `.drawio`, `.txt`, `.cfg`, `.conf`, `.set`, `.md`, and the containerlab files named `startup-config` and `juniper.conf`) with their sizes, topology files first, so a device's startup configuration under `clab-<lab>/<device>/` is reachable. A topology file opens as before; any other file opens a read-only *File on the VM* viewer that hides lines with passwords, secrets or SNMP communities, says so, and shows at most the last 512 KiB of a longer file (**Copy** when the browser can copy). Keys, certificates, `.env` files and binaries are never listed. Without the flag (an older helper) the dialog is the topology browser above. |
| Upload a file from this computer… (Home › Deploy, and the link in the topology browser) | For a topology file that is on your computer: the browser reads it, the manager checks that it is a topology it can read, you see the text and where it will be written, **Create file on the VM…** runs as a reviewed operation, and **Deploy or add this lab…** continues as for any file on the VM. Only that one file is uploaded (up to 1 MiB); files it refers to must be on the VM. A copied lab's saved map (`<topology>.annotations.json`, up to 1 MiB) can be added at the same time so devices keep their positions; it travels through the same review and is written beside the topology under its own name regardless of what the file on your computer was called, with a notice when that name differs and, if a map file is already there, a "Replaces the existing map file" notice in the review. |
| Build a lab visually… / Open in Lab Builder… | Opens the [lab builder](LAB-BUILDER.md): draw devices and links, then save the lab folder to the VM through a review. *Open in Lab Builder…* opens an existing topology file; saving again is only possible while the lab is not deployed and keeps a copy of the previous version. Opened from the topology file dialog, the builder's **← My labs** link and the browser Back button return to that same dialog (read fresh from the VM); opening it directly from the Build card returns to My labs as usual. |
| Write a new topology… | Creates a new topology file on the VM after a structure preview and confirmation; never replaces an existing file. |
| Add to My labs without starting / Deploy lab | Read an existing file and add the lab to My labs without deploying, or deploy it: *Deploy lab* saves the workspace (devices, map, VM source path) first and then reviews the containerlab command, so the lab is in My labs at once and nothing needs importing afterwards. |
| Preview topology (in the topology file dialog) | Draws the file as the Topology tab will: devices where the map file beside it (or the map file uploaded with it) puts them, with their icons and label positions, links with their interface names kept clear of the device labels. A preview is a file, not a lab: no device is a button and none is called *Not in this lab*; a device the map file names but the topology does not is captioned *Not in the topology file*. |
| Download a lab from GitHub… / Browse popular labs… | Optional HTTPS download into the VM's lab folder, followed by a review of the files and a separate deployment. |

Removed in earlier releases: editing existing VM YAML as text (the lab builder's reviewed *Save changes to the VM…* is the only way the manager replaces a topology file, and only for a lab that is not deployed), copy topology path, manual
Select/link VM project shortcut, Open VM folder lab shortcut, separate Edit
layout, horizontal/vertical diagram exports, SSHX/GoTTY and SR Linux fcli. These
commands are rejected by the current manager and installed helper (`layout=horizontal` and `layout=vertical`
of the draw.io route stay refused; the manager's own **Rows** and **Columns** arrangements in *Export to
draw.io…* are a different feature and are not that removed helper-run graph). Upgrade the
host helper as well as the image. Previously created sharing containers are not
automatically stopped or deleted by an upgrade; manage those on the VM if present.

## Every operation is reviewed first

A review that deploys or writes a topology (*Start lab*, *Redeploy lab*, the lab builder's *Save to the
VM…* and *Save changes to the VM…*, *Create file on the VM…*) also lists the topology's **images** and
asks the VM about each while the review is on the screen: *on the VM*, *not on the VM yet, the deploy
pulls it from its registry*, *not on the VM and not found in a registry* (called out above the list:
the devices using it stay down after the deploy; choose an image the VM has, or load it on the VM
first), or that the registry did not answer. The question is read-only on the VM (the operations
helper runs `docker image inspect` and `docker manifest inspect`, never a pull) and never delays the
review; the manager keeps each answer for a few minutes.

A lab operation never runs from a single click. The review names the action in plain
words (*Destroy BGP_TheoryToPractice?*, *Stop devices?*), says what happens to the
devices, warns that **configuration changes you have not saved are lost** for the
disruptive ones, shows when the lab was last saved (`Last saved 3 min ago.`, or `Never saved.`; in red
when it never was, when a lab operation ran after the last save, or when a saved state was loaded since;
`1 save is not uploaded yet.` follows when a save waits) and offers **Save first** when the
lab has a save location. The affected devices and the cleanup folder are under *Technical
details* together with the exact containerlab command; the *Start lab* review shows that
command directly, under **Command run on the VM**, since a fresh deploy has nothing else
to disclose. Confirming a lifecycle action on the open lab closes the review and reports
in the lab banner (*Stopping devices…* with **View output**); confirming *Start lab*
instead opens its live output immediately, with no second click — closing that window on
purpose does not bring it back on its own, and **View output** or a new *Start lab* still
open it again. The result window otherwise opens on its own only for actions that produce
something to read, such as *Show running devices*. The same banner also carries standing
notices that are not tied to one operation, such as configuration lines the retired
telemetry feature left on a device, with a **Review and remove…** action (see
[TELEMETRY.md](TELEMETRY.md)).

## Diagnostics: logs, interfaces, inspect and images

Everything here is read-only. None of it starts, stops, writes, pulls or runs anything inside a device; the manager
asks the VM's operations helper (new modes `logs`, `interfaces`, `netem-show`, an extended `browse`, `images`) and
shows the answer. The sections need a helper that reports `diagnostics: true` in `/api/operations/capabilities`;
after upgrading the manager, refresh the helper (`sudo bash deploy/start-manager.sh --enable-operations`) or the
device drawer shows neither section. The browser sends only the lab id and the device name; the manager derives the
container from the lab's deployment name and refuses a container that is not labelled for that lab and device.

- **Device drawer › Interfaces** (closed until opened). Name, Port (the device's own name, for example `ge-0/0/0`),
  State, RX and TX, with MAC, MTU and type as a second line. Data interfaces come first and carry **Capture**, which
  opens the capture dialog on that container interface (**Capture all connected** in the table header ticks every data
  interface); the management interface (`eth0`) is labelled; internal
  ones (cEOS `cpu`/`fabric`, cJunosEvolved `eth1`–`eth3`) sit under *Other interfaces*. RX and TX show bytes and,
  from the second sample of the same container run, a rate. Impairments set on an interface show as a line under it.
  A stopped container says so (*Interfaces exist only while it runs; Logs shows its last output.*); a device with no
  container yet says *No container for this device yet (deploy the lab, or wait for the deploy to create it).*
- **Device drawer › Logs.** The container's output: **Tail** (200, 1000, 2000), **Refresh**, **Follow**, **Find**
  and **Export**. Lines show `HH:MM:SS` with the full stamp on hover. Lines with passwords, passphrases, private
  keys, community strings or secrets are replaced before they reach the browser, terminal escape codes are removed,
  and nothing is stored, logged or written to an event; **Export** saves what is shown as
  `<lab>-<device>-logs-<UTC stamp>.txt` from the browser. **Follow** adds new lines every few seconds and scrolls
  only while you are at the bottom.
- **How the sections poll.** One request at a time, the next only after the answer; every 5 s, backing off to 30 s
  while the manager is busy (it serves three diagnostics calls at once) with the last data kept under *Updating
  paused, retrying…*; three errors in a row stop it with **Retry**; after 30 minutes it pauses with **Resume**; a
  hidden browser tab stops asking and fetches once on return. Closing the drawer or moving to another device
  collapses both sections and clears their state.
- **Device drawer › Container.** What the manager already knows about the device's container, from the latest VM
  discovery (opening the drawer asks the VM for nothing): Container (name), ID (first 12 characters), Container kind,
  Image (with *topology names …* when the running image differs), Addresses (IPv4 and IPv6), Console, and State (the
  VM's last report, for example *running · Up 2 hours (healthy)*, or *Not on the VM*), most with a **Copy** button. While
  Interfaces or Logs is open and refreshing, the section also shows the process id, health, start time and published
  ports those calls return. For a lab that is not linked to a running lab it is one sentence (*Container facts come from
  the VM. This lab is not linked to a running lab…*) with the kind and image the topology names. The Console row reads
  *Serial, port 5000* for vJunos-switch, vJunos-router and XRv9k, *None for this kind* for the other kinds, and *Not
  known* when the manager has no topology kind for the device.
- **Running labs on the VM…** (Manager ▾) keeps its six columns (Topology, Lab, Device, Type / image, State /
  health, IPv4 / IPv6) and adds **ID** (the first 12 characters of the container id) and **Owner**. Each header
  sorts; **Filter devices** hides rows whose text lacks what you typed (a case-insensitive substring, any column);
  the caption reads *n of m running devices* while a filter is set.
- **Images on this VM…** (Manager ▾) lists the Docker images with size and age and the labs whose topologies name
  each one; **Used by my labs** and **Missing** (a reference a lab names that the VM does not have) filter the
  list. Nothing is pulled or removed. Without the updated helper only the references appear.
- **containerlab version.** The Manager menu's footer and the Diagnostics page's *VM commands* row name the
  containerlab release when the manager has asked the VM for its capabilities.

## Device readiness after deployment

A running container is not a network OS that accepts a login: cEOS, vJunos and XRv9k
boot for one to several minutes. For every linked lab the manager logs in to each
running device over SSH and asks for `show version` every 20 seconds (with its
credential profile, the inventory login, or containerlab's documented default for the
kind) until the network OS answers. The lab header shows *Starting* and *n of m devices
ready*; each device carries a state pill (*Starting*, *Ready*, *Needs credentials*,
*Needs attention*, *Unavailable*) with a sentence that says what to do, on the Devices
tab, in the device panel and on the map. **Open CLI** and **Open all CLIs** enable as
devices answer (vJunos-switch, vJunos-router and XRv9k devices also offer **Console ↗**, a serial console that opens
once the container reports healthy and is the way in when SSH does not answer or the management configuration is
broken; see [NODE-FEATURES.md](../clab-backup-ui/NODE-FEATURES.md#serial-console)), and a login check runs once by itself when every device has answered,
so its `show version` result is under Tools › Configuration backups › *Login checks*
without a click. A device that stops or restarts must answer again. A failed automatic
check sends its devices back to *Starting* and is retried up to three times per boot. A
login refused three times in a row reads *Needs attention* with the remedy (add or fix
the credentials); **Test login now** in the device panel stays available for a manual
retry. Every backup or login check runs with its own empty `known_hosts`, so a
redeployed lab (new SSH host keys) never fails with *host key mismatch*.

## The map and its editor

Choose **Edit map** (Topology tab, Tools tab or Lab actions ▾ › Advanced options). For a lab whose
topology file the manager has, it opens the same editor as the [lab builder](LAB-BUILDER.md), on the
lab's own map and for the drawing only: drag devices, use a generated layout, add and style text,
rectangles, circles, lines and groups (drag devices into a group), copy and paste annotations, set link
label offsets, the link label mode and the grid. A device's look (its icon and corner radius, the icon
colour, the label's position, text direction and background) is edited as in the builder: right-click the
device and choose **Device look**, which opens the editor's own node editor with just those sections; a
label position, text direction, icon or the Transparent box applies the moment it is chosen (one Undo step
each), the colour pickers and the corner radius with the panel's *Apply*. The label positions include the
four corners (top left, top right, bottom left, bottom right), where a name sits diagonally off the icon
so no link covers it; the Topology tab, the preview and the draw.io export draw them the same way, and
the VS Code extension opens a map that uses a corner and draws that label below the icon. The bar
above the editor adds **Undo** / **Redo** (Ctrl+Z, Ctrl+Shift+Z; map changes only) and **Link labels…**
(how far a link's interface names sit from its devices). Devices and links cannot be added, changed or
removed there, nothing is deployed and the running lab is not touched; the editor cannot send anything
but the map to the manager (the node editor's change is turned into a change of the map document before
the editing engine sees it). **Save map** stores it and the Topology tab follows; **Back to the lab** asks when
something is unsaved. *Download map file* gives the full annotations document, *Export to draw.io* uses
the saved map, and *Import map file…* replaces the map with a file from your computer. A map that was
changed elsewhere since it was opened is not overwritten: reopen it. A lab without a topology file in the
manager (imported from an inventory) opens a simpler dialog with text, boxes, circles, lines and Undo.
The Topology tab draws what the editor stores: line arrows, rounded note backgrounds and nested group
levels, and a map saved by the VS Code extension in the boxed node style or with elbow links is drawn in that
style (the per-device box colours of that newer editor are not drawn yet). Devices and links of a lab whose map
was never placed sit on a grid; **More ▾ › Arrange devices…** lays them out in rows, columns or a ring and
saves the map, with **Undo arrange** offered once (it puts the map back exactly as it was); Edit map's own
layouts stay. The dialog says plainly that every device moves and the map is saved; notes, boxes and groups
stay where they are, so a group no longer surrounds its devices (the dialog counts those groups). *Rows* and
*Columns* lay the devices out by their links, one layer of neighbours at a time; *Ring* puts them on a circle;
a device with no link goes below the rest. They are disabled, with the reason *This map has no links to arrange
by*, when the map has no links, and a map with one device cannot be arranged. Arranging changes only the
stored map, never the topology, the devices or the running lab. **Undo arrange** appears under the map after
an arrangement and is kept only while the map is as the arrangement left it: if the map was changed by anyone
else, or the manager restarted, it is removed and the map is reloaded. A lab whose map still sits on the
default grid (two devices or more) says *Devices sit on the default grid.* under the map, with a button that
opens the same dialog.

**Link state on the map.** On a VM whose helper reports `link_state` (containerlab 0.64 or later), the Topology tab asks the VM every ten
seconds which container links are up, while the lab is *Running* or *Partially running*, the Topology tab is
shown, the browser tab is visible and the device panel is closed (opening the panel stops it; closing the panel
asks once at once and carries on; returning to a hidden browser tab does the same). A link whose container
interface is not up on either end (it went with a stopped neighbour, or the device set it down or dormant: a
cEOS `shutdown` shows this way on the neighbour as well) is drawn **red and dotted**, so the colour is not the
only sign; a working link keeps its normal stroke, and a link that is both down and impaired is drawn as down.
The line at the bottom left of the map counts the links (`Links: 4 up · 1 down`, and `· 1 not checked` for links
the manager cannot check, for example a device it cannot name a container for) and a legend line explains the
dotted red stroke while the colours are on. Hover or focus a link and the line at the bottom right gives its
words, for example `vrt:ge-0/0/1 — cjunos:et-0/0/0 · down: vrt ge-0/0/1 is dormant`, and the same words are the
link's tooltip and accessible name. When both ends report the same state the line says
`down at both ends (dormant: one side may be shut down)` without blaming a device. For a device that runs as a
virtual machine inside its container (vJunos-switch, vJunosEvolved, vJunos-router, vQFX, XRv9k) the state is the
container's link to the virtual machine, not the port inside it: a port shut down inside the device may still read
connected, and the count says *connected* instead of *up* (`dotted red = down (container link)`) for such labs.
Nothing of this is stored. When the answer is not available the links are drawn from the topology file, the
colours are cleared and the line says why, once: `Link state off: …` for a VM helper that needs the update, a
containerlab older than 0.64 (the VM's version is named), or a lab not linked to a lab on the VM; `Links are drawn
from the topology file; the lab is not running.` for a lab that is not running (nothing is asked). If the manager
gets no answer (the VM is busy or does not reply), the last colours stay under `Link state paused, retrying…`; after three failures the line reads
`Link state stopped (as of 14:02).` with **Retry**, and after thirty minutes `Link state paused (as of 14:02).` with
**Resume**, and the hover words of a kept colour carry the same time.

**Find** above the map filters the devices as you type by name, address, platform or the label drawn on the map,
dims the devices that do not match and the links between two of them, says `2 of 5 devices match` or `No device
matches "…"` under the map and, on Enter, fits the view to the matches; Escape clears the field first and only
then closes an expanded map. The filter is not stored and does not touch the Devices tab's search. Hovering or
focusing a link also outlines its two devices.

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

The map's **More ▾** menu (also in the expanded map) offers **Import map…**, **Download picture…**,
**Export to draw.io…**, **Arrange devices…**, **Open all CLIs ↗** and **Back up all configurations**; the three
new items are disabled with the reason *No map yet* while a lab has no map. Back up all covers every device that can be backed up
now, including devices not selected for scheduled backups. When every device is ready it
starts at once; when some cannot be backed up, or a job is already running, it first lists
the devices it will skip and why, and you confirm with **Back up N devices**. Right-click a device on the map for Open CLI, Console ↗ (the three kinds above; disabled with the reason while
the console cannot open), Capture traffic, Back
up configuration, Restart device… and Device details. Right-click a link for Capture both ends or one end
(a click on the link opens the capture dialog with both ends ticked, one Wireshark each); the Tools tab's
Packet capture card says how many Wireshark sessions run from this browser and offers End all my sessions
([CAPTURE.md](CAPTURE.md)).

**Download picture…** saves the map as SVG or PNG: the whole map or what is shown now, with or without the
background colour, and with or without the devices' state and link colours (left out unless ticked, so a picture
for a report does not carry one moment's colours). It is made in the browser and nothing is sent to the manager;
the file is `<lab>-map.svg` or `<lab>-map.png`, and it holds the drawn map only: no hover, dimming, tooltips or
capture hit areas. A PNG is drawn at up to twice the size; a map over 8192 px on its longest side, or a browser
that cannot encode a PNG, says so in the dialog and the SVG stays available. **Export to draw.io…** offers the
arrangement (*As on the map*, *Rows*, *Columns*) and a theme (*Manager colours*, or *Print (black and white)* for
paper). *Rows* and *Columns* arrange the devices in the file only, your map is not changed, and notes, boxes and
groups are left out of those two because they were placed for the saved positions; if the manager refuses, its
sentence appears in the dialog instead of a downloaded error file. The editor's own *Export to draw.io* keeps the
map's positions and the manager colours.

## Review and persistence

Every submitted host command requires a preview and confirmation. Review tokens
expire after five minutes and bind the VM connection, original file digest and
relevant deployment state. A change requires another preview. Output and outcome
persist in **Operation history…** (Manager ▾ or Lab actions ▾ › Advanced options); interrupted jobs require
inspection before retrying. A running command can be stopped with `POST /api/operations/{id}/cancel` when it is one of the eleven stoppable actions (every lifecycle command: deploy, redeploy, destroy, apply, start, stop, restart, plus Restart device, Save device configurations, Download lab and Running labs on the VM); the five that finish on their own (create, delete, publish, revise, inspect) answer 409: the manager closes its SSH channel, the helper ends containerlab's process group, the job stays busy until the helper's host lock is free (about 20 seconds, since the last check may run past the deadline), and it then reads `cancelled` with the repair for that action (for example Redeploy lab after a stopped deploy); a stopped deploy never records a deployment time. Lifecycle commands can interrupt CLI sessions. Manager
backups/import changes are blocked during an active lab operation.

Before it plans a command on an existing topology file (the lifecycle commands, *Restart
device*, delete and save again), the helper asks containerlab what is deployed
(`containerlab inspect --all`) so the review names the right containers. It waits for that
answer up to 25 seconds and reads at most 4 MiB. The same inspection runs again when you
confirm, so either step can stop. If containerlab does not answer in time (or fails) it stops
with *Could not inspect deployed labs before the operation*; an answer over 4 MiB, or one the
helper cannot read, stops it with that helper's own error instead. Nothing is changed, and
the command can be reviewed again.

A lab that already runs on the VM but is not in My labs is listed under **Manager ▾ › Labs
found on the VM…** (Home itself carries no such list, except the short *Already running on the
VM* list of the first-run page while My labs is empty). **Add to My labs** reads the lab's
files, shows them for review and imports only when you confirm with **Add lab**; discovery
never imports a lab by itself. A lab removed with the hide option stays listed there as
hidden until **Import again** or **Stop hiding**; a lab hidden from Home (*Hide from Home* in
the lab's ⋯ dialog, which keeps everything) is listed under *Hidden from Home* with **Show on
Home**, and adding its topology again from the topology browser shows it too.

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

Saving lives in the lab header, on every tab: a chip that says where the lab's saved work
stands, **Save** and **Load**. For capture, commit and push into an existing owner-scoped
repository, follow [GIT-SETUP.md](GIT-SETUP.md); the daily use is in
[GIT-PROGRESS.md](GIT-PROGRESS.md). This is separate from Containerlab’s kind-dependent
Save configurations command. Use the existing VM account, and try again after
authentication or export errors. No extra Linux user is required.

**Save** saves at once, without a label: the lab's topology file, its map and the
configuration of every included device go into one folder of the repository as one commit on the
lab VM. Then one sentence says what changed, with **Upload**, **Not now** and **See
changes**. Nothing is uploaded without **Upload**. A save is named automatically (for example
`ceos and xrv9k changed`); the name can be changed afterwards, and **Keep as a checkpoint**
keeps a save under a name. A lab can save into any folder of its repository, inside, above or
beside other labs' folders, and the folder can be created on the spot; the manager asks one
question, with buttons only, when two labs want the very same folder, when the folder
already holds a saved state of another lab or a course, or when a save of the lab still waits
for upload. **Save as a lab state…** writes the lab's current state into another folder (for
example `BGP/start`) without changing where the lab normally saves; it is how a course author
makes Start, Broken and Final ([course states](COURSE-STATES.md)). **All versions** and **Save
settings** open from the chip panel, and **See changes** under a save's sentence opens the drawer
`What changed`.

## Apply a saved configuration to a running node

A student who has saved a Junos, EOS or IOS XR configuration can put it back onto the
running node without destroying the lab, editing startup files, redeploying containerlab
or rebooting the router. **Load** in the lab header, on any tab, lists the lab's own saves and
checkpoints and the **Lab states** of the repository: every saved folder that holds a
manager-written `manifest.json` and that no connected lab saves into, whatever its name or depth, such
as a course's `Start`, `Broken` and `Final` (they are also in **All versions**, with
**Load this state…** on each). The lab does not have to change its save location first, and
loading never changes where it saves or the topology. A state can be a view-only version: one
saved without the restore files, listed with the reason and never offered for loading. Choose
a state and the review lists the saved state, the devices, and for each
whether it already matches the saved state, how many differences there are, or why it is
skipped — including a device whose platform cannot be restored yet, whose saved version
predates its platform's restore support, or an IOS XR device whose saved configuration
defines a `banner` (pasting one back in safely is not supported yet). The red **Load** is the confirmation. The manager backs
up the current configuration of every target first, loads the saved configuration as a
complete replacement inside the device's own transaction (Junos `load override`; EOS a
configuration session reset first; IOS XR `commit replace`, which replaces the whole
configuration natively), and activates it with a timed recovery that the device undoes on
its own if management is lost. **Undo this load** loads that backup again, through the same review. The manager then reconnects for the whole undo window to
confirm the change; on IOS XR only the CLI session that armed the change can confirm it,
so the manager keeps that session open and confirms on it once the reconnect has proved
management survived. EOS also saves the confirmed change to startup, since it does not do
that on commit; IOS XR persists a confirmed change immediately. The manager then captures
the node again and compares it to the saved state. If the manager restarts during a restore,
it reads back every device that was being changed and never applies the change again. Until it
has, the lab reads *Checking devices* and the manager refuses (409, or 400 for backups and login
checks; nothing is queued, so start it again afterwards) backups, restores, design applies, device,
credential and topology-file edits and *Remove lab* on that lab, and lab operations, map and
lab-setting saves, Git saves and adding a lab on every lab. A restore of another lab is accepted but
starts only once the read-back has finished (the exact list is in
[the restore notes](multi-platform-restore/README.md#outcomes-the-manager-reports-per-node)).
The read-back of a network-design apply after a restart holds only its own lab: backups, restores,
design applies, lab operations (Restart device included), map and lab-setting saves of that lab are
refused, other labs stay free, and
*Start fresh* and a change of the VM connection wait for it
([network design](NETWORK-DESIGN.md#applying-a-plan-to-devices)).
Live restore is supported for Junos
(`juniper_cjunosevolved`, `juniper_vjunosswitch`), Arista EOS (`arista_ceos`) and Cisco
IOS XR (`cisco_xrv9k`). This uses the manager's direct SSH path to the node and is
separate from Containerlab's Save configurations command. See
[GIT-PROGRESS.md](GIT-PROGRESS.md#apply-a-saved-configuration-to-a-running-node).
