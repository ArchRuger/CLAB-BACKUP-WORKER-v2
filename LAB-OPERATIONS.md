# Lab operations — Containerlab Node Manager 1.12.1

## Upgrade

Place the source directly in `~/projects/v1.12.1`, containing `deploy/` and
`clab-backup-ui/`. Copy any customized `clab-backup-ui/.env` from the older folder.
Keep the persistent directory and existing VM password.

```bash
cd "$HOME/projects/v1.12.1"
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
sudo docker compose -f clab-backup-ui/compose.yml logs --tail=30 backup-ui
```

The script refreshes and verifies both host helpers, builds `clab-backup:1.12.1`
without cache and recreates the manager. Open `http://VM_IP:8081`; no UI login is
required. Linux host networking uses this port directly, without `-p` forwarding.
Data stays in `/srv/containerlab-node-manager/data` (UID/GID 10001, mode 700).

See [VM connection setup and recovery](VM-CONNECTION.md) and the
[fresh VM installation guide](FRESH-VM-GUIDE.md). Lab commands require the dedicated
clab-discovery account, its password and the installed helper mode. Direct
inspection accounts do not automatically gain the operations protocol.

## Retained commands

Open **Lab actions** or right-click a saved lab (keyboard: Shift+F10).

| Action | Behavior |
|---|---|
| Deploy / redeploy / destroy | Operates on the original VM topology; compatible cleanup variants are offered separately. Redeploy falls back to destroy then deploy when necessary. |
| Apply | Applies the original VM YAML when supported by installed Containerlab. |
| Start / stop / restart | Applies to every node in the selected lab. Stop retains containers; destroy removes them. |
| Inspect lab / inspect all | Readable table of topology, lab, node, kind/image, state/health and IPv4/IPv6. Failed or incomplete output remains visible for diagnosis. |
| Save configurations | Containerlab's kind-dependent save command. Manager backups are separate. |
| SSH all nodes | Opens a launcher tab with individual links and Open all ready sessions. Allow browser popups; at most 32 concurrent terminals/checks. |
| Favorite | Sorts this saved lab above other labs. |
| Interactive draw.io editor | Drag nodes or edit coordinates. Save layout updates the manager; Export full diagram downloads current positions without saving. |
| Delete undeployed VM YAML | Separate source deletion; refused while its deployment exists. Keeps a VM recovery copy. |
| Deploy New Lab → Lab Topologies | Same-tab landing page with an explicit browser button. Expand folders to select .clab.yaml/.clab.yml files; existing files are read-only. |
| New topology | Creates a new VM YAML after structure preview and confirmation; never replaces an existing file. |
| Add project / deploy project | Read an existing file, add a saved manager workspace, or separately review deployment. |
| Clone repository / popular labs | Optional HTTPS project acquisition, followed by review of files and separate deployment. |

Removed in this release: existing VM YAML editing, copy topology path, manual
Select/link VM project shortcut, Open VM folder lab shortcut, separate Edit
layout, horizontal/vertical diagram exports, SSHX/GoTTY and SR Linux fcli. These
commands are rejected by the current manager and installed helper. Upgrade the
host helper as well as the image. Previously created sharing containers are not
automatically stopped or deleted by an upgrade; manage those on the VM if present.

## Interactive diagram and topology actions

There is one interactive diagram editor. It changes node positions; connections
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
sudo bash deploy/setup-operations.sh --lab-root /your/lab/projects
```

Browse is limited to these roots, rejects symlink paths and caps each folder at
500 entries. File reads are capped at 1 MiB. Topologies are trusted VM code:
Containerlab can execute hooks, mount files and pull images. Everyone who can
reach this manager's port has access to its enabled lab operations.

Optional cloning/catalog downloads require Git and network access on the VM:

```bash
sudo apt install -y git
sudo bash deploy/setup-operations.sh --allow-downloads
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
