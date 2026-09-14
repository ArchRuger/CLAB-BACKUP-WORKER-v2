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

## Retained commands

Open **Lab actions** or right-click a saved lab (keyboard: Shift+F10).

| Action | Behavior |
|---|---|
| Deploy / redeploy / destroy | Operates on the original VM topology; compatible cleanup variants are offered separately. Redeploy falls back to destroy then deploy when necessary. |
| Apply | Applies the original VM YAML when supported by installed Containerlab. |
| Start / stop / restart | Applies to every node in the selected lab. Stop retains containers; destroy removes them. |
| Inspect lab / View running lab details | Readable table of topology, lab, node, kind/image, state/health and IPv4/IPv6. Failed or incomplete output remains visible for diagnosis. |
| Save configurations | Containerlab's kind-dependent save command. Manager backups are separate. |
| SSH all nodes | Opens a launcher tab with individual links and Open all ready sessions. Allow browser popups; at most 32 concurrent terminals/checks. |
| Favorite | Sorts this saved lab above other labs. |
| Edit topology diagram | Move nodes and annotations, add text/boxes/circles/lines, style, undo, save and export JSON/draw.io. |
| Telemetry settings… | Automatic telemetry on/off for this lab, the gNMI login profile, the reason a node is not streaming, retry, removal of manager-added lines. |
| Delete undeployed VM YAML | Separate source deletion; refused while its deployment exists. Keeps a VM recovery copy. |
| Deploy New Lab → Lab Topologies | Same-tab landing page with an explicit browser button; the workspace landing page and its header button open the same browser in place when no lab is saved yet. Expand folders to select .clab.yaml/.clab.yml files; existing files are read-only. |
| New topology | Creates a new VM YAML after structure preview and confirmation; never replaces an existing file. |
| Save to manager / Deploy lab | Read an existing file and save a manager workspace without deploying, or deploy: Deploy lab saves the workspace (nodes, map, VM source path) first and then reviews the containerlab command, so the lab is in the manager at once and nothing needs importing afterwards. |
| Clone repository / popular labs | Optional HTTPS project acquisition, followed by review of files and separate deployment. |

Removed in earlier releases: existing VM YAML editing, copy topology path, manual
Select/link VM project shortcut, Open VM folder lab shortcut, separate Edit
layout, horizontal/vertical diagram exports, SSHX/GoTTY and SR Linux fcli. These
commands are rejected by the current manager and installed helper. Upgrade the
host helper as well as the image. Previously created sharing containers are not
automatically stopped or deleted by an upgrade; manage those on the VM if present.

## NOS readiness after deployment

A running container is not a network OS that accepts a login: cEOS, vJunos and
XRv9k boot for one to several minutes. For every linked lab the manager logs in to
each running node over SSH and asks for `show version` every 20 seconds (with its
credential profile, the inventory login, or containerlab's documented default for the
kind) until the NOS answers.
The deployment bar shows *NOS booting 1/2 nodes accept SSH login so far* and then
*NOS ready 2/2*; each answer is recorded in the Nodes table's *Last SSH check*
column as an automatic check. SSH actions, the map's SSH menu entry and **SSH all
nodes** open as nodes answer, and **Test NOS login** runs once by itself when every
node has answered, so the show version result is in Backup history without a click.
A node that stops or restarts must answer again. A failed automatic test sends its
nodes back to booting and is retried up to three times per boot. A login refused three
times in a row is shown as failed with the remedy (assign a credential profile) and is
retried each minute; **Test login** in the node details stays available for a manual
retry. Every backup or login test runs with its own empty `known_hosts`, so a
redeployed lab (new SSH host keys) never fails with *host key mismatch*.

## Telemetry after readiness

With *Automatic telemetry* on (the default for labs created since 1.23.0; earlier
labs turn it on once under **Lab actions → Telemetry settings…**), every node that
has answered `show version` is checked over SSH for its gNMI service, missing lines
are added with the NOS's scoped commit, and a gNMI subscription streams interface
rates, link state and BGP neighbours into memory for Prometheus to scrape. The
**Grafana ↗** button in the lab header opens the lab's dashboards and its generated
map. A stop, destroy, redeploy or removal clears the session. Details, per-NOS
support and the acceptance procedure are in [TELEMETRY.md](TELEMETRY.md).

## Interactive diagram and topology actions

Choose **Edit diagram** in the topology toolbar to move nodes, add text, boxes, circles and lines, or edit appearance. Undo reverses edits; closing offers to discard unsaved changes. Save persists the manager map. Download annotations JSON or Export draw.io includes unsaved edits without writing VM files. Concurrent edits are rejected if the saved map changed; reopen it before editing again.

The editor changes node positions; connections
follow the nodes. Full export contains editable nodes, connections, interface
labels, groups/shapes, notes, colors and positions. Contained nodes are grouped
with their surrounding annotation so they move together in draw.io. Router,
switch and server symbols use native editable diagram elements. Imported custom
icon artwork is represented by a generic network symbol.

The exported `.drawio` is uncompressed editable XML, following the
[draw.io document format](https://www.drawio.com/docs/reference/diagram-generation/).
Open it in diagrams.net or its desktop application. No external service is used
for export. Live SSH/backup actions stay in Node Manager and are not embedded in
the exported file. This is the manager's layout editor, not an embedded copy of
the full diagrams.net application. Structural topology changes are made in the
original VM YAML and imported/synced separately.

The topology header provides **SSH all nodes** and **Back up all configs**, also
in expanded view. Backup all reviews all ready nodes, including unchecked ones,
and lists unavailable/unsupported nodes it will skip. Per-node right-click SSH,
backup and details remain available. Inventory actions remain unchanged.

## Review and persistence

Every submitted host command requires a preview and confirmation. Review tokens
expire after five minutes and bind the VM connection, original file digest and
relevant deployment state. A change requires another preview. Output and outcome
persist in operation history; interrupted jobs require inspection before retrying.
Lifecycle commands can interrupt node sessions. Manager backups/import changes
are blocked during an active lab operation.

Discovery matches imported lab names to the original VM topology path. Open **Deploy New Lab → Lab Topologies** to add an undeployed project. Sync from VM refreshes imported data
without overwriting saved connection settings. Saving a manager layout never
rewrites the original annotations file; a later topology import can replace it.

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
manually on the VM if needed. **Remove lab** and **Start fresh** have different,
manager-only scope; neither deletes original VM sources or deployment containers.

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
