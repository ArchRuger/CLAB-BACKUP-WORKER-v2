# Architecture

The manager is one container on the lab VM. It talks to the VM through a single
restricted SSH account, to the lab nodes through SSH and Ansible, and to an optional
capture stack through localhost. This page shows those relationships, the sequence
that turns a topology file into a usable lab, and which module owns what.

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
        W["Browser capture stack (optional)<br/>gostwire · packetflix · session service<br/>Wireshark containers"]
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
    O["clab-manager-operate<br/>host_operations.py · deploy, destroy, start, stop,<br/>inspect, save, create, clone · trusted roots only"]
    Gt["clab-manager-git<br/>host_git.py · export, commit, push<br/>as the checkout owner"]
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
| Git helper | Export the workspace into a registered checkout and commit or push as its owner | Register checkouts (only root or the guided setup can), read other owners' repositories |
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
    M-->>U: Operation output with the green banner
    loop discovery, every 30 s
        M->>H: clab-manager-inspect
        H-->>M: containers, states, management addresses
    end
    loop readiness, every 20 s per node until it answers
        M->>N: SSH login (profile, inventory or containerlab default) + show version
        N-->>M: answer, refusal or no answer yet
    end
    M-->>U: NOS ready · SSH opens per node
    M->>N: Test NOS login (Ansible show version), once per boot
    N-->>M: results in Backup history
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
| `clab-backup-ui/.env` in the source folder | the installing account | Capture settings (`CAPTURE_*`), read by `start-manager.sh` |

Credentials never leave the encrypted state; API responses and logs scrub
passwords, keys and passphrases, and helper output is published only in complete
lines.

## Module map

| Module | Responsibility |
|---|---|
| `app/main.py` | Application factory, security headers and CSP, inventory, credential profiles, jobs and downloads, the public view of a lab |
| `app/store.py` | Encrypted state file, atomic saves, bounded audit log, reset journal |
| `app/discovery.py`, `app/vm_files.py`, `app/host_files.py` | VM connection, 30-second inspection loop, address reconciliation, lab file bundles and import; `host_files.py` is the helper installed on the VM |
| `app/lab_operations.py`, `app/host_operations.py` | Reviewed containerlab commands with preview tokens and persistent output, topology browser and editor, diagram layout API; `host_operations.py` runs on the VM |
| `app/git_progress.py`, `app/host_git.py` | *Save progress*: capture, export, commit, push and history through the owner-scoped VM helper |
| `app/runner.py` | Ansible `network_cli` backups and login tests, per-job environment and `known_hosts`, output validation, Git history of backups |
| `app/node_services.py` | SSH login checks and browser terminals over WebSocket |
| `app/node_readiness.py` | Readiness monitor: login and `show version` probes, SSH gating, the automatic login test |
| `app/capture.py`, `app/capture_sessions.py`, `app/capture_service.py` | Edgeshark discovery and identity checks, the manager-side relay, and the separate session service that owns the Docker socket |
| `app/topology.py`, `app/layout.py`, `app/drawio_export.py` | Maps from annotations and YAML, layout persistence, draw.io and SuperPuTTY exports |
| `app/diagnostics.py` | The debug panel and its VM probes |
| `app/inventory.py` | Ansible inventory parsing, supported kinds and their documented default logins |
| `app/static/` | The UI: `app.js` (workspace), `management.js` (VM connection, landing page, import), `operations.js` (lab commands, topology browser), `topology*.js` and `diagram-editor.js` (map), `capture*.js` (Wireshark), `git-progress.js`, `terminal.js`, `debug.js` |
| `deploy/` | `install.sh` and `install-manager.py` (guided installer), `start-manager.sh`, the `setup-*.sh` VM scripts, `check-install.sh` with `check_*.py`, the capture Compose file and `capture/smoke.py`, `verify-release.py` |
