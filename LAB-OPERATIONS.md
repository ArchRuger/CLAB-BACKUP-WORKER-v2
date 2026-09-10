# Lab commands — Containerlab Node Manager 1.11.0

## Upgrade from your existing installation

Put this release's contents directly in `~/projects/v1.11.0`, with `deploy/`
and `clab-backup-ui/` inside it. Keep the persistent data directory and existing
SSH key. If you customized `clab-backup-ui/.env`, copy that file from your previous
version folder before starting.

```bash
cd "$HOME/projects/v1.11.0"
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
sudo docker compose -f clab-backup-ui/compose.yml logs --tail=30 backup-ui
```

This updates and verifies both host helpers, retains the authorized SSH public
keys, builds `clab-backup:1.11.0` without cache, and recreates the independent
manager. UI port remains **8081**, using Linux host networking; do not add `-p`.
Persistent data remains `/srv/containerlab-node-manager/data`, UID/GID 10001,
mode 0700. Refresh the browser and discovery, then use **Lab actions**.
Subsequent upgrades can run plain `sudo bash deploy/start-manager.sh`: an already
enabled operations helper is updated automatically.

An image build alone cannot update host permissions or helper files. To build
only the image from the repository root:

```bash
sudo docker build --pull --no-cache -t clab-backup:1.11.0 ./clab-backup-ui
```

For a fresh VM, follow [FRESH-VM-GUIDE.md](FRESH-VM-GUIDE.md). If the discovery
account does not exist yet, the launch command also accepts your public key:

```bash
sudo bash deploy/start-manager.sh "$HOME/clab-manager-discovery.pub" \
  --enable-operations --lab-root /etc/containerlab
```

The UI must use the installed **clab-discovery** account/key in helper mode.
Existing direct-inspection accounts can continue discovery but are not
automatically granted the new operations protocol. Configure the dedicated
account to use lab commands.

## Where the commands live

Open **Lab actions** in a saved lab, or right-click its sidebar entry (keyboard:
Shift+F10). The menu contains the lab-level equivalents of the extension commands:

| Extension area | Manager behavior |
|---|---|
| Deploy / redeploy / destroy, including cleanup | Reviewed commands on the original VM topology; cleanup variants only when the installed command supports that flag |
| Apply | Apply current VM YAML when supported by the installed Containerlab version |
| Start / stop / restart | Operate on the entire selected lab's nodes; stop retains containers, destroy removes them |
| Inspect | Selected lab or all labs (also in the sidebar), with saved output |
| Save | Containerlab's kind-dependent configuration save; manager versioned backups remain separate |
| SSH all | A new launcher tab lists every node and opens ready sessions individually or together; allow popups for Open all; maximum 32 concurrent terminals/checks |
| Edit / create topology | VM YAML editor, syntax/structure preview, save review and diff; edits to existing sources preserve a recovery copy |
| Favorite / copy path / open workspace | Favorite sorting, copy original VM path, project browser in a new tab |
| Import / link workspace | Browse a VM project, review its YAML, then confirm Add project / Link project; files remain on the VM |
| Delete lab source | Separate Delete undeployed VM YAML action, refused while deployment containers exist; preserves a recovery copy |
| Graph / editor / draw.io | Existing map plus draggable layout editor and coordinate fields; horizontal, vertical and current-layout `.drawio` downloads |
| Clone repository / popular lab | Clone an HTTPS project into the VM project directory, browse its files, select a topology and separately review deployment |
| SSHX / GoTTY | Attach, detach, reattach, and open/copy URLs from the operation's saved output; optional host enablement required |
| SR Linux fcli | bgp-peers, bgp-rib, ipv4-rib, lldp, mac, ni, subif, sys-info and custom fcli subcommand/options |

Reference: [Containerlab VS Code extension](https://github.com/srl-labs/vscode-containerlab),
command inventory checked against 0.26.3. Editor commands use browser equivalents;
the manager does not launch VS Code or embed its extension. Draw.io files are
generated locally without an external diagram service. The layout editor changes
node positions and wiring follows; edit YAML for structural node/link changes.
It is not the complete VS Code visual topology authoring interface.

## Operation review and history

Host commands require review/confirmation showing the lab, absolute source path,
argv and deployed containers. Cleanup identifies the expected generated lab
directory and warns about artifact removal. Source and deployment changes invalidate
the review; tokens expire after five minutes and are single-use.

Only one host operation runs through this manager/helper at a time. Conflicting
manager backups, imports, sync and lab changes are blocked. Operations use the
original YAML's parent directory so relative binds/configs/scripts resolve.
Existing labs whose source cannot be found must **Select / link VM project**.
An uploaded YAML snapshot does not reconstruct its dependencies.

**Operation history** stores the latest 200 records with status, timestamps,
exit code and up to 512 KiB of scrubbed output each, in encrypted persistent
state. Output streams while a command runs. Secrets from saved credentials and
common sensitive output patterns are redacted; avoid printing other secrets in
custom topology scripts. Records survive a manager restart. An unfinished record
becomes Interrupted: inspect actual VM state before retrying. There is no automatic
retry of a lifecycle command. Commands have a 20-minute execution timeout.

Discovery refreshes after completion. Destroying a deployment keeps its manager
workspace and backups. **Remove lab** still removes only manager records; it never
destroys a VM deployment or deletes its source. Delete VM YAML is distinct and
does not remove the saved workspace or any adjacent project files.

Saving YAML updates the VM source; it does not silently apply/redeploy or replace
the manager map. Use **Sync from VM** after deployment to refresh imported data.
For undeployed labs, update the manager definition with the edited YAML when you
want to refresh its inventory before deploying. Saving a manager layout does not
overwrite the original `.annotations.json`; a later topology import can replace it.

## Trusted project roots and permissions

Enabling operations expands the discovery key's authority to privileged lab
management within approved roots. Containerlab topologies can execute hooks and
mount host paths. Treat these files and everyone using the manager as trusted
VM administrators; the action registry is not a sandbox for untrusted YAML.

The root-owned `/etc/clab-manager/operations.json` lists allowed project roots,
resolved binaries and optional features. Defaults are `/etc/containerlab` and
`/srv/containerlab-node-manager/projects`. Add actual project roots as needed:

```bash
sudo bash deploy/setup-operations.sh --lab-root /home/YOUR_VM_USER/labs
```

The directory must be an absolute non-symlink path; traversal, symlink components
and paths outside these roots are rejected. No recursive directory deletion is
provided. The setup script preserves previous roots and feature enablement.
To revoke optional features or remove a root, edit the root-owned configuration
using `sudoedit /etc/clab-manager/operations.json`; set `network` or `sharing` to
false as needed. Wait up to a minute for capability caching to refresh.

The SSH key uses a forced gateway that accepts only the fixed discovery request
or `clab-manager-operations`. Structured JSON travels over stdin; command arguments
are never passed to a shell. The account has no interactive SSH/PTY/tunnel access,
and the manager container has no Docker socket. Automatic file discovery continues
through its existing read-only helper. Bounded project browsing/editing is available
only through the newly enabled operations helper.

## Optional features for connected or airgapped VMs

Cloning and the live popular-lab catalog are disabled until explicitly enabled.
The catalog queries GitHub for SRL Labs repositories tagged `clab-topo`; it needs
outbound HTTPS. Offline users can transfer complete project folders into a trusted
root and browse them normally.

```bash
sudo bash deploy/setup-operations.sh --allow-downloads
```

Sharing is independently disabled by default:

```bash
sudo bash deploy/setup-operations.sh --allow-sharing
```

SSHX depends on its relay/network and compatible `containerlab tools sshx`.
GoTTY depends on `containerlab tools gotty`; its default manager form uses VM
port **8082**, separate from UI port 8081. Open firewall access only for intended
recipients. Containerlab may need to pull the tools' images; preload them for an
airgapped VM. Links are available in attach/reattach operation output, not in the
UI access-token URL. Sharing defaults and reachability remain Containerlab's
responsibility. An unsupported command is disabled based on actual host help.

fcli requires SR Linux nodes, the management Docker network, and a preloaded
`ghcr.io/srl-labs/nornir-srl:latest` image (override `fcli_image` in the root config
to an approved pinned tag). For a connected staging VM:

```bash
sudo docker pull ghcr.io/srl-labs/nornir-srl:latest
sudo docker save ghcr.io/srl-labs/nornir-srl:latest -o nornir-srl.tar
```

Transfer that archive to the airgapped VM and run `sudo docker load -i nornir-srl.tar`.
The manager runs fcli with `--pull never`, a read-only topology mount and the lab's
management network. Custom queries supply only fcli arguments, not Docker options
or a shell. Credentials and device prerequisites follow the
[nornir-srl tool](https://github.com/srl-labs/nornir-srl).
Containerlab deploy itself retains normal image-pull behavior: preload every
device image and review hooks for an airgapped deployment.

## Recovering an edited/deleted source

An operation result reports a recovery path under the source directory's
`.clab-manager-history/`. Recovery files are root-readable and are not displayed
in ordinary folder browsing. Use the exact path from the operation result:

```bash
sudo cp -- /absolute/project/.clab-manager-history/FILE.UUID /absolute/project/FILE.clab.yaml
```

Review destination ownership/mode after recovery. Restoring source files does not
recreate containers. This is separate from the manager's device configuration
backup history.

## Validation limits

Automated checks cover operation arguments, reviews, encrypted persistence,
conflicts, file recovery, bounds, draw.io parsing and real loopback SSH transport.
Browser checks use synthetic host replies. This Windows workspace cannot execute
Linux Containerlab/Docker lifecycle commands, sudo installation or external sharing
services. Start with Inspect, then a disposable small lab, before exercising
destroy/cleanup against training deployments.
