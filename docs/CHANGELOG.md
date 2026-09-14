# Changelog

Release notes for every published version, newest first. Links point to the
guides in this folder; validation evidence for recent releases is in
[clab-backup-ui/VALIDATION.md](../clab-backup-ui/VALIDATION.md).

## Changes in 1.26.0

The map takes its node positions from the annotations file, destroy cleans up, and
Grafana runs only while someone reads it, with fifteen minutes of history everywhere.
See [LAB-OPERATIONS.md](LAB-OPERATIONS.md), [TELEMETRY.md](TELEMETRY.md) and
[GRAFANA-MAP.md](GRAFANA-MAP.md).

- **Map positions come from the annotations file.** *Deploy lab* and *Save to manager*
  registered the workspace from the topology YAML alone, so every node landed on the
  default grid (a flat row) and the `.annotations.json` beside the topology was never
  read; nothing applied it afterwards either, because discovery leaves a saved drawing
  to an explicit *Sync from VM*. Now the browser reads the file with the topology
  through the VM helper and sends it along, so the preview, the saved workspace and the
  Grafana map start from the drawn layout (`/api/operations/parse-yaml` takes
  `options.annotations` and reports `annotations_used`; a broken file falls back to the
  grid without failing the topology). A drawing records whether its nodes were placed
  (`placed`); discovery places a grid-only drawing from the annotations file beside the
  deployed topology on its next pass, without a sync and without touching logins or
  nodes, and never replaces a layout somebody saved in the editor. Drawings saved before
  this release are recognised by their coordinates, so an existing flat lab is placed
  as soon as its files are seen.
- **Destroy cleans up.** *Destroy deployment* and the quick destroy button run
  `containerlab destroy --cleanup`, so the containers go together with the generated
  lab folder (`clab-<name>`) and the next deploy starts clean; the review names the
  folder. The flag is sent unless the installed containerlab is known to lack it (the
  helper refuses an unsupported flag itself). Redeploy keeps the folder unless its
  cleanup variant is chosen; the separate *Destroy + cleanup* entry is gone.
- **Grafana on demand.** Grafana idles at a few hundred MiB, so the telemetry stack
  leaves it stopped: `deploy/compose.telemetry.yml` names the container
  `clab-manager-grafana` with the restart policy `no`, and `setup-telemetry.sh` checks
  the stack and then stops Grafana. The lab header's **Grafana ↗** button opens
  `/static/grafana.html`, which asks the manager to start Grafana on the VM when it is
  stopped (`docker start` of that one container through the reviewed operations helper,
  new mode `grafana` with `status`, `start` and `stop`) and then moves the tab to the
  dashboard on the manager's own host name; only a dashboard path travels in the link.
  The manager (`app/grafana_control.py`, `GET /api/telemetry/grafana`,
  `POST …/start`, `POST …/stop`) watches Grafana's request counters over the loopback
  and stops it after `TELEMETRY_GRAFANA_IDLE_MINUTES` (default 15, written into `.env`
  by the setup; 0 keeps it running once started) without a dashboard request; an open
  dashboard refreshes every ten seconds and keeps it alive. **Lab actions → Telemetry
  settings…** shows the state and has **Stop Grafana now**. Prometheus keeps running.
  `check-install.sh` treats a stopped Grafana as the normal state (PASS, read-only,
  never starts it) and checks its health and the Flow panel only while it runs; the CI
  smoke stops and starts the container by name and expects everything re-provisioned.
- **Fifteen minutes of history everywhere.** Prometheus keeps 15-minute blocks with a
  15-minute retention (the block size matters: retention alone would keep the default
  two-hour head block in memory), on a smaller tmpfs; the manager's session store keeps
  15 minutes per series (130 points) instead of an hour; the dashboards and the
  generated lab maps open on the last 15 minutes with 5- and 15-minute quick ranges.
- **Operational notes.** The VM helper must be reinstalled for the new `grafana` mode
  (`start-manager.sh` does it; an old helper answers with a message that says so).
  Upgrading recreates both telemetry containers; Grafana's data volume is tmpfs and
  everything in it is provisioned from files, so a stop loses nothing.

## Changes in 1.25.0

A documentation and installation audit. Grafana is the one place where telemetry is
shown, the browser Wireshark and Grafana stacks are part of every installation, every
documented command works from any directory, and the release check now refuses a guide
that names another release. See [INSTALL.md](INSTALL.md), [TELEMETRY.md](TELEMETRY.md)
and [REPOSITORY-MAINTENANCE.md](REPOSITORY-MAINTENANCE.md).

- **Telemetry lives in Grafana.** The Telemetry tab, its charts, the live link colours
  and status dots on the topology map, the *View telemetry* entries in the node menu,
  the node details and the link menu, and the per-series chart routes
  (`/telemetry/series`, `/telemetry/bgp-series`) are gone. The lab header shows
  **Grafana ↗** (or **Lab map in Grafana ↗** when the lab has a generated map), opening
  the lab's dashboards on the manager's own host name; `/api/state` announces
  `telemetry.grafana` (`enabled`, `port`, `map_uid`) per lab. **Lab actions →
  Telemetry settings…** keeps the per-lab switch, the gNMI login profile, the removal
  of manager-added lines, the reason a node is not streaming and a retry for failed
  nodes. The collector, the Prometheus exposition and the lab-map publisher are
  unchanged.
- **Link hover on the map is fixed.** The telemetry overlay applied `stroke-dasharray`
  to every path of a link group, including the invisible 16 px hit path that makes a
  link clickable, so a link without telemetry (dotted) reacted to the pointer only where
  a 1 px dash happened to lie under it and the highlight flickered along the wire. The
  map renderer and stylesheet are back to their pre-telemetry state; capture from a
  link, the right-click menus, pan, zoom and the diagram editor are as before.
- **Browser Wireshark and Grafana are standard.** The installer runs both as their own
  retryable phases after the manager (phases 4 and 5 of 6, or 7 with VS Code access);
  the launcher (`start-manager.sh`) refreshes both on every upgrade before it creates
  the manager, unless `.env` says `CAPTURE_PROVIDER=disabled` or
  `TELEMETRY_STACK=disabled` or `--manager-only` is given; menu **4** reinstalls both
  without a rebuild (Check is now 5, Exit 6). `setup-capture.sh` and
  `setup-telemetry.sh` recreate the manager themselves so their settings take effect
  (`--no-recreate` is what the launcher passes), both take `--remove` (capture keeps its
  token, telemetry its admin password), and the new `recreate-manager.sh` reloads
  `clab-backup-ui/.env` into the manager without a rebuild. The telemetry setup creates
  the manager data directory when it is missing, so a fresh VM works in any order. The
  health check reports a missing stack as **WARN** with the setup command (capture is
  now titled *Browser Wireshark capture*), and every `Next:` line is an absolute command.
- **Every command works from any directory.** The guides keep the source in
  `~/projects/clab-manager`, write every command with its absolute path and upgrade by
  pulling into the same folder; the health check's advice prints absolute paths.
- **Release numbers are tracked.** `deploy/verify-release.py` now also checks the
  documentation: the living guides may name only the current release (history is
  written as "since x.y.z" or "x.y.z or later"), versioned source folders and image tags
  are refused, and the README, changelog, validation record and handoff notes must lead
  with the current release. `deploy/set-release.py NEW` moves every runtime and
  documentation marker in one go. CI and `test_release_consistency.py` run both checks.
  Every guide was rewritten to the convention; the Docker Hub image guide and the
  repository audit narrative moved to `docs/archive/`, and
  `REPOSITORY-MAINTENANCE.md` now states the release rules.

## Changes in 1.24.0

A Grafana weathermap for every lab, generated by the manager. See
[GRAFANA-MAP.md](GRAFANA-MAP.md).

- **Lab map dashboards.** For each lab with a drawing the manager renders an SVG of the
  topology (positions, icons, labels, groups and notes as on its own map) and a Flow
  panel configuration that binds every link half, port and node to the series it
  exports, and writes one provisioned dashboard `Lab map · <name>` into the Grafana
  folder *Lab maps*. Links are coloured and dash-animated by the far end's receive rate
  (grey, green, yellow, orange, red from 10 kbit/s to 5 Mbit/s), each link end shows its
  rate, port dots follow oper-status, the node dot the telemetry state. Maps follow
  renames, redraws and removals within 30 seconds. `app/telemetry_map.py`, previews at
  `/api/labs/{id}/telemetry/map.svg`, `map.yml` and `map.json` for hand-tuned variants.
- **Flow panel plugin.** `setup-telemetry.sh` installs `andrewbmchugh-flow-panel`
  1.20.1 (Apache-2.0, community-signed) once, pinned, with the pinned Grafana image's
  CLI into `TELEMETRY_CONFIG_DIR/plugins`, mounted read-only so restarts work offline;
  it creates `TELEMETRY_MAPS_DIR` (default
  `/srv/containerlab-node-manager/data/telemetry/dashboards`) for the manager's user
  and mounts it read-only into Grafana; the readiness wait reports whether the plugin
  loaded. `--remove` deletes the plugin folder again.
- **Telemetry tab** opens the lab's map with **Open lab map in Grafana ↗** when one
  exists. New metric `clab_telemetry_node_state_code` (-1 failed … 3 streaming) for
  value-driven colours. `/api/telemetry/health` reports `maps`.
- **check-install** warns when the Flow panel is not loaded or the map folder is not
  writable. CI's telemetry smoke installs the plugin, provisions a generated map and
  verifies that every series its cells bind to is answered.

## Changes in 1.23.1

The first live run of 1.23.0 on the dev VM (cEOS 4.35.0F, Prometheus v3.14.0, Grafana
13.0.2) found six defects in the telemetry release; all are fixed and re-validated live.
See [TELEMETRY.md](TELEMETRY.md).

- **Grafana showed "An error occurred within the plugin" on every panel.** Prometheus
  v3.14.0 refuses `--web.enable-remote-write-receiver=false` ("unexpected false"), so the
  container crash-looped and the provisioned data source had nothing to answer with,
  while `setup-telemetry.sh` still reported success. The flag is gone (the receiver is off
  by default), the setup script now waits for Prometheus `/-/ready` and Grafana
  `/api/health` and fails with the container status and logs when they do not come up,
  and CI starts the real stack against a fixture manager (`deploy/telemetry/smoke.py`),
  checks the data source, the three provisioned dashboards and every panel and variable
  query.
- **cEOS samples were dropped, no receive rate, no link state.** cEOS stamps each
  notification with the last change time of the leaves it carries, so one 10 s cycle
  arrives as several notifications whose timestamps differ by minutes; the store ordered
  all leaves of an interface on one clock and discarded whichever group came "earlier"
  (half of all samples live). Samples are now ordered per leaf by the device clock while
  rates, chart points and freshness use the manager's receive time; a cycle that arrives
  in several notifications a second apart shares one chart point and each direction keeps
  its own newest rate.
- **Interface state stayed unknown on cEOS.** A plain on-change subscription is answered
  with the sync marker only (no initial value), so oper/admin state and the map link
  colour waited for the first flap. The EOS state subscription now carries a heartbeat of
  one sample interval. Verified live: shutdown turns the link red within 3 s from both
  ends, no shutdown turns it green again.
- **"BGP: failed" on every lab without BGP.** EOS sends nothing for a sampled path with
  nothing behind it; after two quiet minutes the group was closed as failed. A quiet group
  now reports *idle*, stays subscribed and turns streaming when data appears.
- **Slow recovery after `docker restart` of a node.** The address and running state do
  not change, so nothing reset the node and the retry backoff grew to minutes. A port that
  does not answer now retries every 30 s at most; the node streams again shortly after the
  NOS boots.
- **check-install** names a Prometheus that does not answer (with the Compose commands to
  inspect it) separately from a target that is not scraped, and classifies scrape errors
  instead of echoing them. Group pills keep their encoding; the telemetry setup tests run
  on Windows as well.

## Changes in 1.23.0

Live network telemetry for disposable labs, automatic from deploy to chart, kept in
memory only. See [TELEMETRY.md](TELEMETRY.md).

- **Automatic provisioning.** Once the readiness monitor has a `show version` answer
  from a node of a lab with *Automatic telemetry* on, the manager opens an SSH shell
  with the node's saved login, reads the gRPC/gNMI service configuration and adds only
  the missing lines with the NOS's own scoped commit: cEOS `management api gnmi` /
  `transport grpc default` (running-config only, never `write`), IOS XR `grpc` +
  `port 57400` + `no-tls` with `commit`, Junos Evolved `set system services extension-service
  request-response grpc clear-text port 32767` in `configure private`. Containerlab's
  cEOS and XRv9k defaults already enable gNMI, so those usually need no change.
  Every added line is logged and recorded per node; repeat checks write nothing.
- **gNMI dial-in collector** in the manager process (pygnmi, BSD-3; grpcio) using the
  host-network path the manager already uses for SSH: interface counters every 10 s,
  oper/admin state (on change on EOS), BGP neighbour session state and prefix counts
  where the model is advertised. Plain-text gRPC on all three kinds (TLS with the
  device certificate where an EOS or Junos node already has it); encodings follow the
  node's capabilities; rejected subscriptions fall back to broader paths; a login
  refusal never probes further.
- **Session-only store.** Bounded rings (60 minutes, 400 points per series, 96
  interfaces and 64 neighbours per node, 512 nodes), rates from counter deltas with
  reset, gap and out-of-order handling, generation tags so a previous deployment with
  the same name and address never feeds a new one. Cleared on stop, destroy, redeploy
  (operations submitted through the manager), removal, manager reset and restart.
  Nothing is written to the encrypted state, backups, Git or the data directory.
- **Telemetry tab**: lab verdict, node cards with state and reason, interface table
  (wired peer, admin/oper, RX/TX bit and packet rates, errors, discards, last sample),
  SVG charts for 5/15/60 minutes, BGP neighbour table and prefix chart, settings
  dialog (automatic on/off, gNMI password profile, removal of manager-added lines),
  clear empty, off, waiting, stale, partial and failed states. Unsupported metrics
  show `n/a`, never zero; no utilisation percentages.
- **Topology overlay**: links coloured from both ends (up, up on one observed end,
  down with a mismatch marker, stale, no telemetry), hover text with rates, a status
  dot per node, a right-click link menu with *Capture packets* and *Telemetry* per
  end, *View telemetry* in the node menu and details drawer. Pan, zoom, annotations
  and the existing SSH, backup and capture actions are unchanged. Interface names are
  mapped per kind (`eth1` → `Ethernet1`, `eth1` → `GigabitEthernet0/0/0/0`, `eth4` →
  `et-0/0/0`), never guessed across kinds.
- **Node states**: Off, Waiting, Configuring, Connecting, Streaming, Stale,
  Unsupported, Failed with an actionable reason; streaming means usable samples
  arrived. Telemetry defers while a lab operation or backup job runs and never blocks
  terminals, captures, backups or deployments.
- **Settings and safety**: automatic telemetry is on for labs created from 1.23.0;
  earlier labs show an explicit *Enable automatic telemetry* step before any device
  write. gNMI uses the saved password login (SSH keys cannot be used; a password
  profile can be chosen). `TELEMETRY_COLLECTOR=disabled` turns the collector off.
  Secrets never enter responses or logs; failures are classified, not echoed.
- **Grafana dashboards in another tab (optional).** `sudo bash
  deploy/setup-telemetry.sh` starts Prometheus (v3.14.0) and Grafana OSS (13.0.2),
  digest-pinned, host-networked like the manager, with dropped capabilities, memory
  and PID limits and tmpfs data (two-hour retention). Prometheus scrapes the new
  `/api/telemetry/metrics` endpoint (Prometheus text format: node states, interface
  rates and counters, link states, BGP neighbours; names only) every 10 s; Grafana
  serves three provisioned read-only dashboards (Lab overview, Interfaces, BGP
  neighbours) to anonymous Viewers, with a generated admin password kept in `.env`.
  The Telemetry tab shows **Open Grafana ↗** and a per-node **Grafana ↗** link once
  the manager is recreated with `TELEMETRY_STACK=grafana`. `--remove` takes the stack
  down again. Licences are listed in `deploy/TELEMETRY-THIRD-PARTY-NOTICES.md`.
- **Health check** gains *Network telemetry* and *Grafana telemetry dashboards*;
  `check-install` reports the collector, each linked lab's verdict, Grafana's health
  and Prometheus scraping, plus manual traffic and dashboard checks.
- **Tests**: 74 new Python tests (names, store, adapters, scripted SSH sessions for the
  three NOS families, notification fixtures, the state machine on the app, an
  in-process gRPC gNMI server driven through the real pygnmi client, the metrics
  endpoint, the Grafana stack definition and setup script, the health checks) and a
  browser test file for charts, view states, overlay, Grafana links and menus. No live
  device validation was possible for this release; the acceptance procedure is in
  TELEMETRY.md.

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
