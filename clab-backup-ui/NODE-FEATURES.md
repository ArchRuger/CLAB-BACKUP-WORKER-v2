# Containerlab Node Manager — 1.12.1

Lab-level lifecycle, project and drawing controls are documented in
[LAB-OPERATIONS.md](../LAB-OPERATIONS.md). Enable the host operations helper for
these features. Existing node SSH/backup actions remain available.

The default deployment is now a standalone persistent manager. Follow
[standalone setup and migration](../STANDALONE-SETUP.md); the older build/worker
upgrade section below is historical. Linked lab discovery gates SSH and backups
on fresh running nodes. Manual endpoints remain available as explicit overrides.

New labs require a preview and Import lab confirmation before saving. Cancel
leaves them unsaved, including across background checks. The normal
`deploy/start-manager.sh` launch updates/verifies the helper while retaining the
existing SSH key.

The updated restricted helper reads new deployments from the topology path in
inspect and the adjacent generated lab folder, with missing Docker labels allowed.
Direct mode also reads files over SFTP with the same account. Discovery file details
shows attempted paths and errors; detected lab clicks try automatic import before
offering manual uploads. Upgrade the helper for 1.12.0 without changing its key. Existing labs
show file changes and offer Sync from VM without resetting saved node connections
or history. Follow [the fresh VM guide](../FRESH-VM-GUIDE.md) for setup and upgrades.

Click a lab to open its node dashboard. Every imported node is shown, including
Linux and unmapped kinds. Details contains the last SSH authentication check,
connection settings and the node's saved configuration history.
The details drawer shows configured settings separately from the last SSH check.
Checks are on demand, with timestamps; no host metrics or collector are used.

## Node actions

- **Test login** in the details drawer authenticates to SSH without issuing a command. Its timestamped
  result is a last check, not a continuous reachability guarantee.
- **Back up** queues only this node using the existing NOS backup engine. This
  works even when the node is excluded from scheduled backups, and does not reset
  the lab schedule. The single backup queue still allows one job at a time.
- **Details** offers latest and historical successful configuration downloads.
  Existing lab-wide jobs, individual downloads, and ZIP downloads are retained.
- **Open SSH** opens an independent interactive terminal in a new browser tab.
  It connects to the saved management address/port, not the container wrapper.
  It uses the assigned profile, platform default, or imported credentials.
- **Edit connection** is available in the node details drawer.

For Linux or unmapped nodes, create a **Generic SSH / Linux (terminal only)**
credential profile and assign it under Edit. A generic default applies to unmapped
nodes. Generic SSH does not enable configuration backups for unsupported platforms.
Changing backup selection does not disable terminal access.

## Browser terminal behavior

The terminal is a normal interactive session: configuration commands are available
if the saved device account permits them. EOS enable entry and passwords are
interactive; the terminal does not run the backup driver's automatic enable step.
Use Disconnect or close the tab to end it; Connect / reconnect starts a new session.
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
from a trusted proxy address. The shipped Compose setup still serves HTTP.

The frontend vendors xterm.js 5.5.0 and addon-fit 0.10.0 with their licenses under
`app/static/vendor/`; there is no runtime CDN or frontend build step.
Only the terminal document permits inline styles in its Content Security Policy,
as required by xterm's generated character-width, font and ANSI-color rules.
Scripts remain restricted to this origin; the dashboard retains its original CSP.

## Interface and upgrade from 1.3.0

Containerlab Node Manager uses a slate navigation rail, coral selection and primary actions,
cyan terminal accents, light working surfaces, and an original fiber-line mark.
It contains no company or vendor logo. Selecting a node opens a right-side details
drawer with connection settings, its last SSH check, and configuration history.
SSH and per-node backups remain directly accessible in the node table.

Host resource monitoring has been removed: no CPU/memory columns, collector,
host mapping, container-name mapping, monitoring endpoints, or collector token
configuration is required. Existing `monitor_host` / `container_name` values in
encrypted state are ignored and omitted from public state; no destructive data
migration runs. Profiles, backups, schedules, and the existing data key are retained.

If you installed the optional 1.3.0 systemd collector, stop it on that host:

```bash
sudo systemctl disable --now clab-monitor
```

If you ran it in a terminal, stop that process with Ctrl+C. You may remove the old
MONITOR_TOKEN entry from your deployment environment. The 1.6.1 source archive
does not contain `monitor/`; old copies left by an overlay extraction are not used
by the worker. The archive's source folder is the complete current build context.

## Build and upgrade

See [fresh image and worker upgrade](../FRESH-IMAGE.md) for worker-only recreation
and data preservation. The supplied lab YAML has no `/data` mount; copy its data
before replacing that container.

From the repository root (the folder containing `clab-backup-ui/`):

```bash
docker build --pull --no-cache -t clab-backup:1.6.1 -t clab-backup:webui ./clab-backup-ui
```

If already inside `clab-backup-ui` beside its Dockerfile:

```bash
docker build --pull --no-cache -t clab-backup:1.6.1 -t clab-backup:webui .
```

For Compose, run `docker compose up -d --build` from that application directory.
For containerlab, update the worker image to `clab-backup:1.6.1` and recreate only
that worker using your existing deployment procedure. Keep the existing `/data`
mount and its key. Do not delete the volume or redeploy the router lab for this upgrade.
Refresh the browser and confirm v1.6.1 in the footer. The upgrade preserves existing device snapshots and stored credentials.

## Deployment checks

1. Verify existing backup history and profiles remain available.
2. Check login and run one backup on each supported NOS; download the files.
3. Open SSH, run `show version`, resize, disconnect, and reconnect on each NOS.
4. Connect a Linux node using a generic profile if present.
5. Open a node drawer and verify its connection settings and saved backup downloads.

See `VALIDATION.md` for local test evidence and remaining live-lab checks.

Implementation reference: [xterm.js API](https://xtermjs.org/docs/api/terminal/classes/terminal/).

## Topology and session export (1.6.1)

Choose **Topology > Import topology**. Upload `lab.clab.yaml.annotations.json`
and optionally the corresponding `.clab.yaml` or generated `topology-data.json`.
Annotations alone show positions; the topology supplies wiring and interface names.
Supported drawing features are positioned nodes, groups, rectangle/circle/line shapes,
and plain text notes. Imported font sizes, weights, colors, text alignment, rotations,
node label placement, group backgrounds, opacity, borders, and viewer background
colors are preserved where supported. Built-in router, switch and server symbols
replace the corresponding icon categories. Pan by dragging the background; use zoom,
Fit map, or Expand map. Fit uses the rendered bounds rather than guessed text extents.

Version 1.6.1 interprets saved node coordinates as the top-left of the 40px icon,
matching the source canvas. Legacy unsized text notes retain paragraph spacing;
explicit fill opacity replaces an embedded RGBA alpha. Endpoint labels use the
saved offset. For generated topology-data exports, Cisco XRv9k data ports map from
`eth2` to `Gi0/0/0/1`, and so on; other kinds retain their exported names. Native
YAML interface names are preserved. YAML is preferred when it contains custom NOS
aliases that cannot be reconstructed from an export. These paths produce identical
links for the supplied BGP lab. Schema 3 records the corrected drawing metadata.

Right-click a matched node for **SSH**, **Back up configuration**, and **Node details**.
SSH opens a new browser tab with the existing saved connection. Keyboard users can
focus a node and press Shift+F10, navigate with arrow keys, and press Escape to close
the menu. Actions have the same credential/readiness requirements as the node list.

**Upgrading from 1.5.0 or 1.6.0:** reimport the original annotations plus topology file.
Earlier importers discarded styling or did not retain corrected label metadata;
existing stored maps need a fresh import to apply all corrections. Old maps remain readable and display a reminder.
Reimporting drawing data does not replace inventory, credentials, or backups.
This is an operational map, not a complete VS Code topology editor: custom icons,
HTML/Markdown text styling, geographic layouts, nested relative geometry, traffic
annotations, and link editing are not reproduced. Unsupported/one-ended links are
counted in the map status. Imported links never imply live connectivity.

Click a matched node to open SSH in a new tab, run a backup, test login, or inspect
configuration history. Nodes remain the default list view. Mapping uses unique
inventory names, stored short names, or the exact `clab-<lab name>-` prefix. Ambiguous
or unknown nodes have no actions. Correct the node's short name in Edit connection
(or reimport inventory with topology-data.json) to resolve a mismatch. Imports do
not change endpoints, credentials, schedules, or existing backups. Drawing data is
saved in encrypted state. Only whitelisted drawing fields are retained.

**Export sessions** in the lab toolbar downloads `<lab-name>.xml` with
`Lab name/Node short name` session IDs. All inventory nodes are included, even if
excluded from backups. Short names come from inventory's topology-data.json import,
then the explicit node name override, then removal of an exact lab prefix. Duplicate
session names are rejected. Invalid filename characters are replaced with underscores. Slashes in folder/session names become underscores.
Sessions use saved SSH addresses/ports, which must be reachable from the workstation;
container management addresses are not automatically translated to host-published ports.
Saved profile/inventory usernames take precedence; fallback usernames are `clab` for
IOS-XR and `admin` for cJunosEvolved and cEOS. Unknown kinds prompt for a username.
Custom lab credentials always take priority over vendor defaults.

Passwords are omitted by default. Checking **Include saved passwords as plain text**
exports available password-profile/inventory passwords via PuTTY `-pw` arguments.
No default passwords are invented; key material/passphrases and enable passwords are
never exported. SuperPuTTY/PuTTY configuration and version must permit this argument.
Import using SuperPuTTY's session import feature, selecting the downloaded XML.
This release was checked against upstream serialization source, not a live SuperPuTTY
installation. A password prompt is the fallback when no password was saved.

Format references: [VS Code annotations](https://github.com/srl-labs/vscode-containerlab/blob/v0.24.0/src/reactTopoViewer/shared/types/topology.ts),
[containerlab export](https://github.com/srl-labs/containerlab/blob/main/core/export_templates/auto.tmpl),
[SuperPuTTY SessionData](https://github.com/jimradford/superputty/blob/master/SuperPutty/Data/SessionData.cs).
