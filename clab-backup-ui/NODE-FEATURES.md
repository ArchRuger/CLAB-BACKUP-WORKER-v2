# Node features

Node-level behaviour of the manager: what a node row and the topology map offer,
how the browser terminal works, and the map import and session export formats.
Lab-level lifecycle, project and drawing controls are in
[LAB-OPERATIONS.md](../docs/LAB-OPERATIONS.md); installation is in
[INSTALL.md](../docs/INSTALL.md).

Click a lab to open its workspace. Every imported node is shown, including Linux
and unmapped kinds. The device panel (**Details** on the Devices tab, or a click on
the device) contains the last SSH check, the connection
settings and the node's saved configuration history; checks are on demand, with
timestamps. The manager collects no host CPU or memory metrics; the retired network
telemetry feature is described in [TELEMETRY.md](../docs/TELEMETRY.md).

## Node actions

- **Interfaces** and **Logs** in the device drawer (closed until opened; they need a VM helper that reports
  `diagnostics`) show the container's interfaces with one traffic counter sample per poll, and its redacted output.
  Each data interface has **Capture**, which opens the capture dialog on that container interface; **Capture all
  connected** in the table opens it with every data interface ticked (shown from two data interfaces), and the
  dialog's *Open as* chooses one Wireshark for them or one per interface. Both sections are read-only
  and use the VM's operations helper, never the device's own session (see *Diagnostics* in
  [LAB-OPERATIONS.md](../docs/LAB-OPERATIONS.md)).
- **Container facts** (device drawer, section *Container*) list what the manager already knows about the
  device's container: its name, the first 12 characters of its id, the container kind, the image (with a line *topology
  names …* when the running image differs from the one the topology names), the management IPv4 and IPv6 address, and
  whether the device has a serial console, each with a **Copy** button; the *State* row shows the VM's last report
  (for example *running · Up 2 hours (healthy)*, or *Not on the VM*). The section is built from the latest VM discovery
  and never calls the VM when the drawer opens; process, health, start time and published ports appear in it only
  while the Interfaces or Logs section is open and refreshing. A lab that is not linked to a running lab gets one sentence
  instead (*Container facts come from the VM…*) plus the kind and image the topology names, and no stale values.
- **Capture traffic…** opens the browser Wireshark dialog on that node with its wired ports
  listed first ([CAPTURE.md](../docs/CAPTURE.md)).
- **Open CLI ↗** opens an independent interactive terminal in a new browser tab. It
  connects to the saved management address/port, not the container wrapper, with
  the assigned profile, the containerlab default login or the imported credentials.
  For linked labs it opens once the readiness monitor has seen the NOS answer.
- **Console ↗** opens the device's serial console in a new tab (see *Serial console* below). It is offered only for
  vJunos-switch, vJunos-router and XRv9k devices, in the device panel, the Devices view and the map's right-click menu.
  It opens once the container reports healthy (the launcher uses the console during the first boot; if the device panel
  has a Logs section, it shows that boot) and is the way in when SSH does not answer or the management configuration is
  broken. The button appears once the lab is linked to a running lab with this device in its topology; from then on it
  stays visible and, where the console cannot open, disabled with the reason.
- **Restart device…** (also in the device panel and the Devices technical view) restarts only this
  device through containerlab's own node-scoped restart on the VM (`containerlab restart --node`,
  what the VS Code extension's *Restart node* runs): the container stops and starts with its links
  kept; a stopped device is started and its links restored. It goes through the reviewed operation
  dialog like every lab command, names the device and the lab, and saves, backs up, resets or
  reapplies nothing. The device reads *Restarting*, then *Starting* until it answers a login again
  (its earlier login proof is dropped, so an old *Ready* never survives a restart). For fifteen minutes
  after a restart, start or deploy the manager itself performed, a refused login still reads *Starting*
  ("SSH answers but the saved login is not accepted yet"): IOS XR answers SSH minutes before it accepts
  logins, and that is a boot, not wrong credentials.
- **Back up configuration** queues only this node using the NOS backup engine. This works even
  when the node is excluded from scheduled backups, and does not reset the lab
  schedule. The single backup queue still allows one job at a time.
- **Details** offers latest and historical successful configuration downloads,
  **Test login** (authenticates over SSH and asks for `show version`, or a harmless shell
  command for a device with no NOS platform; its timestamped result is a last check, not a
  continuous reachability guarantee. A device with a NOS platform must really answer `show version`.
  A device without one (a Linux host, or a network OS of a kind the manager does not back up) counts as
  answering when its CLI says anything but a not-ready reply, even an error for the shell command it does
  not know. The CLI must have answered completely within 25 seconds of being asked, or the check ends
  there and counts as no answer; the readiness monitor's own check follows the same rules. A login
  that is accepted while the CLI is still starting
  shows the *Starting* login-result badge with its own message, never *Login OK*. In a lab
  linked to a VM deployment the device reads *Starting* too, the readiness monitor keeps asking
  and replaces the result with the real answer. A lab with no VM deployment (an inventory
  import) is not monitored: only the login result reads *Starting* and it stays until the next
  **Test login** (its message says so), while the device itself stays available for SSH
  whenever a login is configured) and
  **Edit connection…** (short name used in backup file names, address, port, NOS,
  profile, *Include in backups*). Every field is checked before anything changes or is
  logged, so a rejected edit leaves the device as it was; if the manager's state file cannot
  be written the edit answers an error (HTTP 500), nothing was changed, and it can be
  repeated once storage is healthy.

**Test logins**, beside the Devices heading on both the topology rail and the Devices
tab, repeats **Test login** for every device of the lab at once instead of one at a
time (bounded to 4 SSH sessions together, so it never opens more than that). A device
is skipped, not attempted, when it has no saved address (*no address*) or no login to
try (*needs credentials*); being excluded from backups (a Linux host such as the
multitool, which has no NOS platform) does not exclude it from the login test; the notification
after starting says how many devices were skipped. While it runs the button reads
*Testing…* and is disabled, and so is the other copy of it; each device being tested
reads *Testing login…* until it answers. A refresh only ever reports what the device
actually did: it never marks a device ready by itself and never opens a terminal, and
it does not touch backups. While a device is starting or missing credentials, its
disabled **Open CLI ↗** explains why and points back at **Test logins** (or that
device's own **Test login**) to check again once it is ready.

For Linux or unmapped nodes, add credentials (Advanced › Credentials › **Add
credentials**) with the type **Linux host (CLI only, no backups)** and assign the
profile under Edit connection…. A generic default applies to unmapped
nodes. Generic SSH does not enable configuration backups for unsupported platforms.
Changing backup selection does not disable terminal access.

A `ghcr.io/srl-labs/network-multitool` node (any tag, no NOS platform) needs no
credential profile: the manager applies its documented login from the
[network-multitool README](https://github.com/srl-labs/network-multitool), the
same way a NOS kind gets its containerlab default. SSH readiness and **Open
CLI ↗** work the same as for any other login; configuration backups stay
unavailable, since this image has no backup driver.

## Device kinds

What the manager does for each containerlab kind (the code is `app/inventory.py`, `downloads.py`,
`topology.py` and `restore_drivers.py`; `GET /api/catalog` returns the same facts as one read-only list for the
lab builder and the Topology editor: kind, label, aliases, whether a default login exists, the interface rule
and the backup, restore, design and console capabilities):

| Kind (label) | Aliases | Default login | Backup | Download name | Data port in the topology | Restore | Console |
|---|---|---|---|---|---|---|---|
| `arista_ceos` (EOS) | `ceos`, `eos` | admin / admin | `show running-config` | `CEOS` `.conf` | `ethN` = `EthernetN` | yes | no |
| `cisco_xrv9k` (IOS-XR) | `vr-xrv9k`, `iosxr` | clab / clab@123 | `show running-config` | `IOS-XR` `.txt` | `eth(N+1)` = `Gi0/0/0/N` | yes | yes |
| `juniper_cjunosevolved` (Junos) | `cjunosevolved`, `junos` | admin / admin@123 | display set | `cjunosevo` `.cfg` | `eth(N+4)` = `et-0/0/N` | yes | no |
| `juniper_vjunosswitch` (Junos (vJunos-switch)) | `vr-vjunosswitch`, `vjunosswitch` | admin / admin@123 | display set | `vJunos-switch` `.cfg` | `eth(N+1)` = `ge-0/0/N` | yes | yes |
| `juniper_vjunosrouter` (Junos (vJunos-router)) | `vr-vjunosrouter`, `vjunosrouter` | admin / admin@123 | display set | `vJunos-router` `.cfg` | `eth(N+1)` = `ge-0/0/N` | yes (see below) | yes |
| `juniper_vsrx` (Junos (vSRX)) | `vr-vsrx`, `vsrx` | admin / admin@123 | display set | `vSRX` `.cfg` | `eth(N+1)`; `ge-`, `xe-` and `et-0/0/N` all name it | yes | no |
| `juniper_vqfx` (Junos (vQFX)) | `vr-vqfx`, `vqfx` | admin / admin@123 | display set | `vQFX` `.cfg` | `eth(N+1)` = `xe-0/0/N` | no | no |

The Junos kinds back up as `show configuration | display set | no-more`, the human and diff form, and also keep the
hierarchical configuration as the restore artifact (`.jcfg`) that the Junos restore driver replaces the whole
configuration with. Login order is unchanged: credential profile, then the inventory login, then the kind default
above, then (for `linux` nodes only) the documented image default. The vSRX default is the one containerlab.dev
publishes for `vr-vsrx` (checked 2026-10-27). Notes on the two newest Junos kinds:

- **vSRX** is a Junos firewall; the Load driver was proven live on the exact image
  (Junos 23.2R2.21). The manager offers no serial console for it: a kind joins the console list only after the console has been verified
  live through the manager's own console path, and that has not been done for vSRX.
- **vJunos-router**: the Load driver was proven live on a nested derivative of the published image. The
  published image does not boot on a VM host (an official containerlab limitation), so the kind needs a
  bare-metal KVM host; on a virtual machine host its virtual router aborts at boot. See
  [DEVICES.md](../docs/parity-campaign/DEVICES.md) and the supported-platform matrix in
  [the restore guide](../docs/multi-platform-restore/README.md).
- vQFX is backed up and downloaded but has no restore driver and no console yet.

## Backup download names

A device's configuration downloads as `<type>_<device>_<YYYY-MM-DD>_<HH-mm>UTC.<ext>`,
for example `cjunosevo_GTW-2_2026-09-10_01-04UTC.cfg`: the type and extension come from
the platform (`cjunosevo`, `vJunos-switch`, `vJunos-router`, `vSRX` and `vQFX` → `.cfg`, `IOS-XR` → `.txt`,
`CEOS` → `.conf`; an unknown platform reads `Device` and keeps the stored extension), the
device is the short name frozen with that backup, and the time is when the device was
captured, in UTC, never the download time. **Download all (ZIP)** is
`<lab>_<YYYY-MM-DD>_<HH-mm>.zip` (the job's start, UTC) and holds the same file names, a
manifest, and the topology and map the backup embedded as `<lab>.clab.yml` and
`<lab>.clab.yml.annotations.json` (see *The topology travels with every backup* below).
Characters Windows cannot store are replaced, and two names that differ only by
case get a number. The files kept on the VM use different, stable internal names. The manager
keeps only the newest 300 backup and login-test job records per lab (a busy one, or one a
pending Git save or restore still needs, survives longer); once a record is dropped it can no
longer be downloaded, chosen as a Git save's capture or a restore source, used as a lab's
starting point, or shown as a node's last backup. Its configuration files are not deleted: they stay
under the manager's own data directory (`backups/<lab>/latest` and `backups/<lab>/history/<job>`).

## The topology travels with every backup

Every backup that saved at least one configuration (on demand, scheduled, or the capture behind a
**Save**) also stores the lab's topology and map beside the configurations, so a configuration
is never divorced from the topology it was taken under: the containerlab file and its
`.annotations.json` as they were on the VM beside the deployed topology at the last discovery pass
(within the thirty-second discovery interval), or, when the VM's copy is not known, the manager's own
copy from the last sync. The map follows its own rule (`topology_capture` and `map_changed_in_manager`
in `app/runner.py`): a map that a person changed in the manager since the VM's map file was last synced
into it (moving a device on the Topology tab, *Edit map*, an uploaded map) is the map that travels,
because it is the map the person sees; otherwise the VM's map file travels, also when that file has
changed on the VM since the last sync; and when the VM has no map file, the manager's own map travels,
and the record says so. When both the person and the VM changed the map, the person's map wins; the
VM's newer file stays on the VM and *Sync topology from VM* still offers it. The backup record says which (*the files beside the
deployed topology on the VM* or *the manager's copy*), the file's path and when it was read, with the
digests of both files. A backup after which the manager holds no topology text clears the two files
from the lab's `latest/` folder, so its local Git history never pairs new configurations with an old
topology; every earlier backup keeps its own copy.
A backup whose topology or map could not be stored with it carries a `topology_missing` mark, a
controlled value and never an error text, and the backup itself is not failed by it: `no-text` means
the manager holds no topology text for the lab (for example a lab imported from an inventory), so its saves hold
device configurations only; `error` means the topology file could not be written and `map-error`
that the topology was written but the map the lab has was not. A **Save** whose capture carries
`error` or `map-error` stops and commits nothing (*The topology could not be saved with this
capture. Try again.*), so a save never reaches the repository without a file the lab has and never
deletes one from `latest`. Such a capture is not offered for **Keep as a checkpoint** or **Use as
starting point…** either (*This capture does not include the topology. Save again first.*).
They are kept under stable internal names in the backup folder and in its local Git history, download
in the ZIP under the lab's own names, and travel into every Git save (your latest save, a checkpoint, the starting point, a lab state) as
`<lab>.clab.yml` and `<lab>.clab.yml.annotations.json` next to the device files, listed in the save's
manifest as files of their kind rather than as devices: **Load** ignores them (loading never changes the topology), **See changes** and **See what’s different**
show their changes, and a save without them never counts as a removed device.
Backups and saves made before this feature carry none and keep working as before. The manager cannot
see a topology file edited on the VM after the lab was deployed without a redeploy; what travels is
the file as it was at capture time.

## Browser terminal behaviour

The terminal is a normal interactive session: configuration commands are available
if the saved device account permits them. EOS enable entry and passwords are
interactive; the terminal does not run the backup driver's automatic enable step.
Use **Disconnect** or close the tab to end it; **Reconnect** starts a new session.
Disconnected shells are not resumed. Resize and standard terminal keys are supported.

The terminal opens directly, without a UI login. The server still requires a
short-lived, single-use terminal ticket and checks the WebSocket origin. Device
SSH credentials are looked up in encrypted manager storage. Closing the terminal
tab or restarting the manager ends the connection.

Only session open/close and login-check results enter action logs (a close is logged only
for a session whose open was logged; a ticket that is refused or a login that fails before
the shell starts leaves neither). Keystrokes,
terminal output, and credentials are not recorded there. SSH host keys retain the
existing trusted-lab policy (unknown keys are accepted). Use this on your trusted
lab network. Use HTTPS/WSS when accessed over an untrusted network; a proxy must
forward WebSocket Upgrade, preserve Host, and correctly convey the external scheme
from a trusted proxy address. The shipped Compose setup serves HTTP.

The frontend vendors xterm.js and its fit addon with their licences under
`app/static/vendor/`; there is no runtime CDN or frontend build step. Only the
terminal document permits inline styles in its Content Security Policy, as required
by xterm's generated character-width, font and ANSI-colour rules. Scripts remain
restricted to this origin; the dashboard retains its original CSP.

## Serial console

**Which devices.** Three kinds offer a serial console: `juniper_vjunosswitch`, `juniper_vjunosrouter` and
`cisco_xrv9k` (their vrnetlab-based images expose the emulator's serial port on TCP port 5000 of the container). A
kind joins only when its image's own project documents the console and it was verified live; the Junos (vSRX) kind
(`juniper_vsrx`) is therefore **not** offered one. The
manager decides by the topology kind of the device, not by the network OS chosen under *Edit connection*. A device
whose kind is not in that list (cEOS, cJunosEvolved, vQFX, vSRX and the rest) shows no **Console** button, and the drawer's
Container section says *None for this kind*; a device the manager has no topology kind for (it came from an inventory
file) says *Not known* there, and *Lab actions ▾ › Sync topology from VM* supplies the kind.

**When the button is enabled.** The manager answers this itself, and the button, the Devices rows and the map menu all
show the same answer; the button appears once the lab is linked to a running lab with this device in its topology, and
from then on it stays visible and is disabled, with the reason as its hover text and a note in the device panel, while
the device is not running or the VM's status
is out of date, the VM reported no management address, a *Restart device…* job is running for it, its health check
reads starting or unhealthy, or its container has run for less than two minutes. The reason is that a device's launcher
holds the console while it boots, and a second client would disturb it. Open CLI and the SSH readiness states are not
affected.

**What the student sees.** The same terminal page as Open CLI, in console mode: the title and the header read *Serial
console*, and the notice says that this is the same as a cable in the device's console port, that the device shows its
own login prompt when it is ready (Enter is only for a prompt that is already there), that a console login stays open
on the device until you log out, and that the session closes after 15 minutes without typing. A console login left in
configuration mode keeps holding the device's configuration: a later Load refuses that device until you leave
configuration mode or log out of the console. The toolbar (font size,
Copy, Clear, Save) is the one of the SSH page; saved files carry `console` in their names. The manager connects to the
container's discovered management address and the kind's port; the browser sends only the lab, the device and the word
`console`. It uses the same single-use ticket and WebSocket origin rules as SSH, but not Paramiko or a saved login:
**no credentials are sent**, the device prompts for its own. A serial console has no window size, so a resize is
ignored, and the device pages long output as on a real console (Junos shows `---(more)---`: press Enter or the space bar,
or set `set cli screen-length 0` for the session; the manager never types that for you).

**One console per device.** A second console for the same device from this manager is refused at once, and the sentence
names when the first one opened (in UTC); at most 8 consoles are open at a time, counted apart from the 32 SSH
sessions. A console that nothing in the browser types into closes after 15 minutes (output arriving does not keep it
open), and no console lasts longer than 4 hours; a device that stops or restarts closes it with *The console closed: the
device stopped or restarted.* **Reconnect** asks for a new ticket and meets the same checks as the first open. *Start
fresh* (Manager settings) is refused while a console is open, as it is for open SSH sessions.

**Refusals, and what each means.**

- *… has no serial console* / *The manager has no topology kind for …*: the kind is not one of the three, or the
  manager does not know it (see above).
- *… is not running on the VM…*, *The VM has not reported a management address…*, *The console needs a lab linked to
  the VM…*: the device, its address or the link to the running lab is missing; start or link the lab, or refresh.
- *… is restarting*, *… is still starting*, *… has not finished booting*, *… started less than two minutes ago*: the
  launcher still has the console. Try again once the device reports healthy; for a boot that never finishes, the Logs
  section of the device panel (where it exists) shows why.
- *Could not reach the console of …* and *The console of … is in use by its launcher … or by a client outside this
  manager*: the connection failed, or it succeeded but the console stayed silent, which means another client holds it.
- *The console of … is already open from this manager* and *Too many consoles are open*: the one-console and
  eight-console rules above.

**What is recorded.** Only `console.open` and `console.close` events with the lab and the device. Console output and
keystrokes are not stored, logged or put in an event, and a refused ticket leaves nothing. The manager answers the
telnet negotiation the emulator's port sends and removes the telnet control bytes from the output; the text you see is
the device's.

## Deployment checks

After an upgrade, verify on a lab:

1. Existing backup history and profiles remain available.
2. Login and one backup on each supported NOS work; the files download.
3. SSH opens, `show version` answers, resize, disconnect and reconnect work.
4. A Linux node connects with a generic profile if present.
5. A node drawer shows its connection settings and saved backup downloads.
6. Right-click on the map offers Open CLI, Capture traffic, Back up configuration, Restart
   device… and Device details; a link opens the
   capture dialog with both ends ticked, and right-click on a link offers Capture both ends or one end.

See `VALIDATION.md` for what was actually tested for each release.

Implementation reference: [xterm.js API](https://xtermjs.org/docs/api/terminal/classes/terminal/).

## Topology map and session export

Deployed and imported labs get their map from the topology file and, when present,
the containerlab `.annotations.json`; **Import map…** (the map's **More ▾** menu, or
Lab actions ▾ › Advanced options) uploads them by hand. Annotations alone show positions; the topology supplies wiring and interface
names. Supported drawing features are positioned nodes, groups, rectangle/circle/line
shapes, and plain text notes. Imported font sizes, weights, colours, text alignment,
rotations, node label placement, group backgrounds, opacity, borders and viewer
background colours are preserved where supported. Built-in router, switch and
server symbols replace the corresponding icon categories. Pan by dragging the
background; use **+**, **−**, **Fit** or **Expand**. Fit uses the rendered bounds rather
than guessed text extents.

Saved node coordinates are the top-left of the 40 px icon, matching the source
canvas. Legacy unsized text notes retain paragraph spacing; explicit fill opacity
replaces an embedded RGBA alpha. Endpoint labels use the saved offset. For generated
topology-data exports, Cisco XRv9k data ports map from `eth2` to `Gi0/0/0/1`, and so
on; other kinds retain their exported names. Native YAML interface names are
preserved. YAML is preferred when it contains custom NOS aliases that cannot be
reconstructed from an export. Schema 3 records the corrected drawing metadata; a
map imported by an older importer shows a reminder to reimport the original files.

Right-click a matched device for **Open CLI ↗**, **Capture traffic…**, **Back up
configuration**, **Restart device…** and **Device details**; click a link to capture both of its ends, or right-click it for both ends or one. The menu
header shows the device's state, and an action that is not available says why under
its label. Keyboard users can focus a device and press Shift+F10, navigate with arrow
keys, and press Escape to close the menu. Actions have the same credential/readiness
requirements as the Devices tab. Each device carries a state dot (ready, starting,
needs attention, unavailable) taken from the same readiness check as the Devices tab.
Links show the imported wiring; while the lab runs on a VM whose helper reports `link_state`, a link whose
container interface is not up on either end is also drawn red and dotted (the container links from the VM's
interface listing, not from the devices; see *Link state on the map* in
[`docs/LAB-OPERATIONS.md`](../docs/LAB-OPERATIONS.md)), and for a device that runs as a virtual machine inside its
container the state is the container's link to it, not the port inside it.

This is an operational map, not a complete VS Code topology editor: custom icons,
HTML/Markdown text styling, geographic layouts, nested relative geometry, traffic
annotations and link editing are not reproduced. Line arrows, rounded text
backgrounds and nested group levels made in **Edit map** are kept in the lab's map
document and drawn by the editor, the Topology tab and the draw.io export, as are the boxed
node style and elbow links of a map saved by the VS Code extension (its per-device box colours
are not). Unsupported/one-ended links are
counted in the map status. Mapping uses unique inventory names, stored short names,
or the exact `clab-<lab name>-` prefix. Ambiguous or unknown nodes have no actions;
correct the node's short name in Edit connection (or reimport inventory with
topology-data.json) to resolve a mismatch. Imports do not change endpoints,
credentials, schedules or existing backups. Drawing data is saved in encrypted
state. Only whitelisted drawing fields are retained.

**Export SuperPuTTY sessions…** (Advanced tab › Lab operations) downloads `<lab-name>.xml` with
`Lab name/Node short name` session IDs. All inventory nodes are included, even if
excluded from backups. Short names come from inventory's topology-data.json import,
then the explicit node name override, then removal of an exact lab prefix. Duplicate
session names are rejected. Invalid filename characters are replaced with
underscores; slashes in folder/session names become underscores. Sessions use saved
SSH addresses/ports, which must be reachable from the workstation; container
management addresses are not automatically translated to host-published ports.
Saved profile/inventory usernames take precedence; fallback usernames are the kind defaults above:
`clab` for IOS-XR and `admin` for cEOS and every Junos kind (cJunosEvolved, vQFX, vJunos-switch,
vJunos-router, vSRX). Unknown kinds prompt for a username.
Custom lab credentials always take priority over vendor defaults.

Passwords are omitted by default. Checking **Include saved passwords in the file (stored as plain text)**
exports available password-profile/inventory passwords via PuTTY `-pw` arguments.
No default passwords are invented; key material/passphrases and enable passwords are
never exported. SuperPuTTY/PuTTY configuration and version must permit this argument.
Import using SuperPuTTY's session import feature, selecting the downloaded XML.
The export was checked against upstream serialisation source, not a live SuperPuTTY
installation. A password prompt is the fallback when no password was saved.

Format references: [VS Code annotations](https://github.com/srl-labs/vscode-containerlab/blob/v0.24.0/src/reactTopoViewer/shared/types/topology.ts),
[containerlab export](https://github.com/srl-labs/containerlab/blob/main/core/export_templates/auto.tmpl),
[SuperPuTTY SessionData](https://github.com/jimradford/superputty/blob/master/SuperPutty/Data/SessionData.cs).
