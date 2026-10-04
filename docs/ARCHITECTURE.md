# Architecture

The manager is one container on the lab VM. It talks to the VM through a single
restricted SSH account, to the lab nodes through SSH and Ansible, and to the
browser capture stack through localhost. This page shows those relationships, the
sequence that turns a topology file into a usable lab, and which module owns what.

## System overview

```mermaid
flowchart LR
    B["Browser on your workstation"]
    subgraph VM["Lab VM · Ubuntu 24.04"]
        M["Node Manager container<br/>FastAPI + vanilla JS · port 8081<br/>host network · UID 10001 · no Docker socket"]
        D[("Persistent data<br/>/srv/containerlab-node-manager/data<br/>state.enc · state.key · backups/ · events.jsonl")]
        G["sshd · Match User clab-discovery<br/>ForceCommand clab-manager-gateway"]
        H["Root helpers via sudoers<br/>clab-manager-inspect · -operate · -git"]
        C["containerlab + Docker Engine"]
        N[("Lab nodes<br/>cEOS · Junos · XRv9k · Linux")]
        W["Browser capture stack<br/>gostwire · packetflix · session service<br/>Wireshark containers"]
        K[("Registered Git checkout<br/>owned by a VM account")]
    end
    R[("Git remote<br/>GitHub over HTTPS")]
    B -- "HTTP + WebSocket" --> M
    M --- D
    M -- "SSH, password, pinned host key" --> G --> H
    H --> C --> N
    H --> K -- "push with the owner's login" --> R
    M -- "SSH terminals · readiness probes · Ansible network_cli" --> N
    M -- "127.0.0.1:5001 discovery<br/>127.0.0.1:5801 sessions" --> W
    W -. "captures inside the node namespaces" .-> N
```

## The VM access boundary

Everything the manager does on the host passes through one SSH account. Its only
shell command is a gateway that recognises three exact commands and starts the
matching helper through `sudo -n`; `/etc/sudoers.d` lists those helpers by full
path with an empty argument list, so nothing else can be run.

```mermaid
flowchart TB
    M["Manager container"]
    S["sshd on the VM<br/>Match User clab-discovery · password auth · ForceCommand"]
    GW{"clab-manager-gateway<br/>switch on SSH_ORIGINAL_COMMAND"}
    I["clab-manager-inspect<br/>host_files.py · read-only<br/>containerlab inspect + lab file bundle"]
    O["clab-manager-operate<br/>host_operations.py · deploy, destroy, start, stop, restart (lab or one node),<br/>inspect, save, create, publish, revise, clone · trusted roots only"]
    Gt["clab-manager-git<br/>host_git.py · export, commit, push, browse, move<br/>as the checkout owner; register as root"]
    X["anything else → exit 64"]
    T[("/etc/clab-manager<br/>operations.json · git.json · engineer.json")]
    M -- "SSH" --> S --> GW
    GW -- "clab-manager-inspect" --> I
    GW -- "clab-manager-operations" --> O
    GW -- "clab-manager-git" --> Gt
    GW --> X
    O --- T
    Gt --- T
```

What each side can and cannot do:

| Party | Can | Cannot |
|---|---|---|
| Manager container | Serve the UI, keep encrypted state, open SSH to nodes and to `clab-discovery`, run Ansible against nodes | Reach the Docker socket, run arbitrary VM commands, read lab files outside the helper bundle |
| `clab-discovery` account | Start the three helpers through the gateway | Open a shell, run other commands, use SFTP in helper mode |
| Operations helper | Run containerlab on topology files under the trusted roots in `operations.json`, with every command reviewed and confirmed in the UI first | Touch files outside those roots, run commands the manager did not preview |
| Git helper | Export the workspace into a registered checkout and commit, push, list or move folders as its owner; as root, register another folder of an already registered checkout, or clone and register a repository for the VM account that owns the registered ones | Run Git as root, accept command text or credentials, read other owners' repositories |
| Capture session service | Create and remove labelled Wireshark containers from one pinned image | Accept images, commands, mounts or URLs from a client; it is never exposed to browsers |

## From topology file to usable lab

```mermaid
sequenceDiagram
    participant U as Browser
    participant M as Manager
    participant H as VM helpers
    participant N as Lab nodes
    U->>M: Deploy lab (topology chosen on the VM)
    M->>M: Save the workspace: nodes, map, VM source path
    M->>H: preview, then confirm the containerlab command
    H-->>M: streamed output, exit code
    M-->>U: The lab banner reports the operation (View output opens the window)
    loop discovery, every 30 s
        M->>H: clab-manager-inspect
        H-->>M: containers, states, management addresses
    end
    loop readiness, every 20 s per node until it answers
        M->>N: SSH login (profile, inventory or containerlab default) + show version
        N-->>M: answer, refusal or no answer yet
    end
    M-->>U: n of m devices ready · Open CLI enables per device
    M->>N: Test NOS login (Ansible show version), once per boot
    N-->>M: results under Tools › Configuration backups › Login checks
```

A node that stops or is redeployed goes back to *booting* and has to answer
again. Every Ansible run gets its own empty `known_hosts`, because lab containers
generate new SSH host keys on each deploy.

## Browser packet capture

```mermaid
flowchart LR
    B["Browser tab<br/>noVNC served from the pinned image"]
    M["Manager relay<br/>owner cookie · allow-listed assets<br/>HTTP + WebSocket, same origin"]
    S["Session service container<br/>bearer token · Docker socket<br/>labelled containers and volumes"]
    E["Edgeshark<br/>gostwire discovery · packetflix pcapng streams"]
    W["Wireshark container<br/>wireshark-vnc-docker · no host mounts<br/>/pcaps tmpfs-backed volume"]
    N[("Lab node interfaces")]
    B -- "/api/capture/..." --> M
    M -- "127.0.0.1:5801" --> S
    M -- "127.0.0.1:5001" --> E
    S -- "create · remove · archive /pcaps" --> W
    W -- "packetflix:// stream" --> E
    E -. "capture in the node's network namespace" .-> N
```

Sessions are limited to four at a time, 15 minutes idle and two hours in total;
ending a session removes its container and files. Details, coverage and the
security notes are in [CAPTURE.md](CAPTURE.md).

## Where data lives

| Location | Owner | Contents |
|---|---|---|
| `/srv/containerlab-node-manager/data` | UID 10001 | `state.enc` (Fernet-encrypted workspaces, credentials, jobs), `state.key`, `backups/<lab>/latest` and `history/`, `events.jsonl` audit log |
| `/srv/containerlab-node-manager/projects` | root, group `clab_admins` | Trusted root for cloned or created topologies |
| `/etc/containerlab` | root, group `clab_admins` | Default trusted lab root; containerlab writes each lab's folder here |
| `/etc/clab-manager/` | root | `operations.json` (trusted roots, download permission), `git.json` (registered checkouts), `engineer.json` (VS Code account) |
| `/usr/local/lib/clab-manager/`, `/usr/local/sbin/clab-manager-*` | root | Installed helper copies and launchers |
| `/etc/ssh/clab-manager-password.conf`, `/etc/sudoers.d/clab-manager-*` | root | The `clab-discovery` SSH policy and the exact helper permissions |
| A registered checkout, for example `~/labs/<repo>` | the VM account that owns it | Saved lab progress; pushed with that account's own Git login |
| `clab-backup-ui/.env` in the source folder | the installing account | Capture settings (`CAPTURE_*`) written by the setup script, read when the manager is created or recreated |

Credentials never leave the encrypted state; API responses and logs scrub
passwords, keys and passphrases, and helper output is published only in complete
lines.

## Module map

| Module | Responsibility |
|---|---|
| `app/main.py` | Application factory, security headers and CSP, inventory, credential profiles, jobs and downloads, the public view of a lab |
| `app/allowed_hosts.py` | The outermost ASGI layer against DNS rebinding: refuses every HTTP request and WebSocket handshake whose `Host` is missing, repeated, malformed or a name outside DNS could control (IP literals, `localhost`, single-label and `.local` names pass; other names only when listed in `UI_ALLOWED_HOSTS`; `X-Forwarded-Host` is never read), before the same-origin guard in `main.py` and the WebSocket Origin checks, which all derive the manager's own origin from `Host` |
| `app/downloads.py` | Download names, short device names, UTC timestamps, safe lookup of a job's snapshot files, ZIP and manifest assembly, legacy metadata backfill ([download names](../clab-backup-ui/NODE-FEATURES.md#backup-download-names)) |
| `app/store.py` | Encrypted state file, atomic saves, bounded audit log, reset journal |
| `app/discovery.py`, `app/vm_files.py`, `app/host_files.py` | VM connection, 30-second inspection loop, address reconciliation (the one container-name formula covers the default, custom, empty and `__lab-name` prefixes; a container with only an IPv6 address is matched too), lab file bundles and import; `host_files.py` is the helper installed on the VM |
| `app/lab_operations.py`, `app/host_operations.py` | Reviewed containerlab commands with preview tokens and persistent output (including *Restart device*, the node-scoped `restart-node` action: the manager resolves one device to its topology node and container, the helper binds that one container into the review), topology browser and editor, diagram layout API; `host_operations.py` runs on the VM |
| `app/static/lab-builder.html`, `lab-builder-page.js`, `lab-builder.css`, `app/static/lab-builder/`, `lab-builder/` | The [lab builder](LAB-BUILDER.md): the page and its plain-JavaScript logic (browser drafts, starters, templates, reviewed save), the committed editor assets (SR Labs clab-ui, its licence, notices and hash manifest), and the build-time TypeScript project that produces them (never built on a VM). Saving uses the `publish` and `revise` actions of `host_operations.py` |
| `app/git_progress.py`, `app/host_git.py` | *Save progress*: capture, export, commit, push and history through the owner-scoped VM helper; the repository folder browser, folder moves and connecting a repository by URL. Snapshots of restore-capable platforms (Junos, EOS, IOS XR) also carry a restore-grade artifact (hashed and sized) in the manifest |
| `app/restore.py`, `app/restore_drivers.py`, `app/restore_shell.py`, `app/restore_compare.py`, `app/restore_junos.py`, `app/restore_eos.py`, `app/restore_iosxr.py` | *Apply to running lab*: a managed restore job that backs up each target first, then replaces its whole configuration inside the device's own transaction with a timed recovery (Junos `load override` + `commit confirmed`; EOS a configuration session + `commit timer`; IOS XR `commit replace confirmed`, confirmed only from the CLI session that armed it), reconnects to confirm and verifies the result. `restore_drivers` is the per-platform contract and registry (Junos, EOS and IOS XR). It runs over the manager's direct node-SSH path — no host helper — and serialises with backups, Git saves and lab operations |
| `app/runner.py` | Ansible `network_cli` backups and login tests, per-job environment and `known_hosts`, output validation, Git history of backups; backups of restore-capable platforms (Junos, EOS, IOS XR) also capture a restore-grade candidate (Junos hierarchical, EOS/IOS XR running-config) |
| `app/node_services.py` | SSH login checks (*Login OK* only when the CLI also answers a real command; when the login is accepted but the CLI is still silent the device reads *Starting*, which the readiness monitor replaces with a real answer only for a lab linked to a VM deployment (for an inventory import the result stays until the next *Test login*); a refused login reads *Needs attention*) and browser terminals over WebSocket (`terminal.close` is logged only for a session whose `terminal.open` was) |
| `app/node_readiness.py` | Readiness monitor: login and `show version` probes, SSH gating, the automatic login test |
| `app/network_design.py`, `app/design_intent.py`, `app/design_adapter.py`, `app/design_engine.py`, `app/design_capabilities.py`, `app/design_capability_data.json`, `app/static/network-design.js` | *Network design* ([NETWORK-DESIGN.md](NETWORK-DESIGN.md)): the intent document a lab keeps (schema, validation, allocation ledger), the adapter that joins the containerlab topology and the intent into a netlab topology with explicit profiles and endpoint mapping, the runner of the pinned `netlab create` engine in a private per-job directory, the shared capability model (engine support read from the pinned engine, image limits, validation levels) with its generated data file, the service with the routes, generation jobs and immutable per-plan artifacts under `network-design/` in the data directory, and the Design tab's script. Planning touches no device, VM or Docker |
| `app/design_apply.py`, `app/design_provision.py`, `app/design_ownership.py`, `app/design_eos.py`, `app/design_junos.py`, `app/design_iosxr.py` | *Apply to devices* of the network design ([NETWORK-DESIGN.md](NETWORK-DESIGN.md), contract in `docs/netlab-integration/PROVISIONING.md`): `design_provision` decides what of a generated fragment may reach a device (identity, management, logins and hostname never do); `design_ownership` is the pure ownership algebra (statement sets, created ancestors, stale/conflicts/expected, removal planning, read-back verification); the three drivers stage removals and the candidate inside the NOS's own merge transaction (EOS configuration session with `commit timer`, Junos exclusive candidate with `commit confirmed`, IOS XR exclusive session kept open for `commit confirmed minutes`), render the desired set on the device, and confirm only their own pending change from a fresh connection; `design_apply` owns the review token, the apply job (mandatory pre-change backup through the Runner, per-device settle with `rolled_back`/`uncertain`, post-change backup), the per-lab ownership ledger `network_ownership` and the routes. Device access is direct node SSH only |
| `app/telemetry_retirement.py` | Startup migration of a lab's stored telemetry setting: keeps a non-empty ledger of configuration lines the retired feature added to a device as a private `telemetry_retired` record, and the *Remove from devices* action that deletes exactly those lines on the running device, reads it back, and reports `removed`, `absent`, `failed` or `skipped` |
| `app/capture.py`, `app/capture_sessions.py`, `app/capture_service.py` | Edgeshark discovery and identity checks, the manager-side relay, and the separate session service that owns the Docker socket |
| `app/topology.py`, `app/layout.py`, `app/drawio_export.py` | Maps from annotations and YAML, layout persistence, draw.io and SuperPuTTY exports |
| `app/diagnostics.py` | The debug panel and its VM probes |
| `app/inventory.py` | Ansible inventory parsing, supported kinds and their documented default logins |
| `app/static/` | The manager UI, plain scripts loaded by `index.html` in a fixed order with no build step: `status.js` (student status vocabulary), `shell.js` (hash router, menus, browser storage), `app.js` (state, rendering), `topology-render.js` and `topology.js` (the map and its menu), `home.js` (Home: the Deploy and Build cards, Recent labs), `management.js` (VM connection, labs found on the VM, import), `operations.js` (lab commands, topology browser, upload), `diagram-editor.js` (the basic map editor for a lab without a topology text), `git-progress.js` and `git-places.js` (the Progress tab and the repository folder browser), `restore.js` (*Apply to running lab*), `capture.js` (Wireshark). Standalone pages with their own scripts: `terminal`, `workspace` (CLI launcher), `debug` (Diagnostics), `vm-connection`, `capture-setup`, `capture-session`, and `map-editor.html` with `map-editor-page.js` (*Edit map*: the lab builder's editor restricted to the map, saving through the map-document API) |
| `deploy/` | `install.sh` and `install-manager.py` (guided installer), `start-manager.sh` (runs `retire-telemetry.sh --no-recreate` before building the manager) and `recreate-manager.sh`, the `setup-*.sh` VM scripts (discovery, operations, engineer access, Git, capture), `retire-telemetry.sh` (one-time teardown of a leftover telemetry stack), `check-install.sh` with `check_*.py`, the capture stack Compose file with `capture/smoke.py`, `verify-release.py` and `set-release.py` |
