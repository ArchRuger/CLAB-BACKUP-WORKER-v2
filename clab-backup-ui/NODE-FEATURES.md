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

- **Capture traffic…** opens the browser Wireshark dialog on that node with its wired ports
  listed first ([CAPTURE.md](../docs/CAPTURE.md)).
- **Open CLI ↗** opens an independent interactive terminal in a new browser tab. It
  connects to the saved management address/port, not the container wrapper, with
  the assigned profile, the containerlab default login or the imported credentials.
  For linked labs it opens once the readiness monitor has seen the NOS answer.
- **Back up configuration** queues only this node using the NOS backup engine. This works even
  when the node is excluded from scheduled backups, and does not reset the lab
  schedule. The single backup queue still allows one job at a time.
- **Details** offers latest and historical successful configuration downloads,
  **Test login** (authenticates over SSH and asks for `show version`; its
  timestamped result is a last check, not a continuous reachability guarantee) and
  **Edit connection…** (short name used in backup file names, address, port, NOS,
  profile, *Include in backups*).

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

## Backup download names

A device's configuration downloads as `<type>_<device>_<YYYY-MM-DD>_<HH-mm>UTC.<ext>`,
for example `cjunosevo_GTW-2_2026-09-10_01-04UTC.cfg`: the type and extension come from
the platform (`cjunosevo`, `vJunos-switch` and `vQFX` → `.cfg`, `IOS-XR` → `.txt`,
`CEOS` → `.conf`; an unknown platform reads `Device` and keeps the stored extension), the
device is the short name frozen with that backup, and the time is when the device was
captured, in UTC, never the download time. **Download all (ZIP)** is
`<lab>_<YYYY-MM-DD>_<HH-mm>.zip` (the job's start, UTC) and holds the same file names and a
manifest. Characters Windows cannot store are replaced, and two names that differ only by
case get a number. The files kept on the VM use different, stable internal names.

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

Only session open/close and login-check results enter action logs. Keystrokes,
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

## Deployment checks

After an upgrade, verify on a lab:

1. Existing backup history and profiles remain available.
2. Login and one backup on each supported NOS work; the files download.
3. SSH opens, `show version` answers, resize, disconnect and reconnect work.
4. A Linux node connects with a generic profile if present.
5. A node drawer shows its connection settings and saved backup downloads.
6. Right-click on the map offers Open CLI, Capture traffic, Back up configuration and
   Device details; a link opens the
   capture dialog on either endpoint.

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
configuration** and **Device details**; click a link to capture either end. The menu
header shows the device's state, and an action that is not available says why under
its label. Keyboard users can focus a device and press Shift+F10, navigate with arrow
keys, and press Escape to close the menu. Actions have the same credential/readiness
requirements as the Devices tab. Each device carries a state dot (ready, starting,
needs attention, unavailable) taken from the same readiness check as the Devices tab.
Links show the imported wiring, never live connectivity.

This is an operational map, not a complete VS Code topology editor: custom icons,
HTML/Markdown text styling, geographic layouts, nested relative geometry, traffic
annotations and link editing are not reproduced. Line arrows, rounded text
backgrounds and nested group levels made in **Edit map** are kept in the lab's map
document and shown by that editor, but are not drawn on the Topology tab or in the
draw.io export. Unsupported/one-ended links are
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
Saved profile/inventory usernames take precedence; fallback usernames are `clab` for
IOS-XR and `admin` for cJunosEvolved and cEOS. Unknown kinds prompt for a username.
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
