# Documentation

Start with the [project README](../README.md) for the overview, the quick start and
the system diagram. The guides below go deeper; each one says which release it was
last written for in its first heading.

## Install

| Guide | Use it when |
|---|---|
| [Quick install](QUICK-INSTALL.md) | You want the shortest route from a fresh Ubuntu VM to a saved lab: only what to paste, type or click. |
| [Fresh VM guide, version 2](FRESH-VM-GUIDE-V2.md) | You are building the VM yourself: Proxmox settings, Ubuntu, the installer, WinSCP and VS Code checks, the first Git save, and recovery for each step. |
| [Guided VM installation](INSTALL.md) | You want to know what the terminal installer's menu, phases and options do. |
| [VM connection](VM-CONNECTION.md) | You are creating or repairing the `clab-discovery` account and its password, or the manager cannot reach the VM. |
| [Docker Hub setup](DOCKER-HUB-SETUP.md) | You run a pulled image instead of building from source. |
| [Standalone setup and migration](STANDALONE-SETUP.md) | You are moving from the older in-lab worker container to the standalone manager, or starting it by hand with `deploy/start-manager.sh`. |

## Operate

| Guide | Use it when |
|---|---|
| [Lab operations](LAB-OPERATIONS.md) | You deploy, destroy or inspect labs, browse VM topologies, edit the diagram, or want to know how NOS readiness is judged. |
| [Git setup](GIT-SETUP.md) | You register a VM checkout so *Save progress* can commit and push with the owner's login. |
| [Save lab progress](GIT-PROGRESS.md) | You use saves, checkpoints, baselines, history and loads. |
| [Browser Wireshark](CAPTURE.md) | You install the capture stack, start sessions, download captures, or need the security boundary of the capture services. |
| [Health check](HEALTH-CHECK.md) | You read `deploy/check-install.sh` output and fix FAIL or WARN lines. |
| [Debug panel](DEBUG-PANEL.md) | You use the development diagnostics page to probe VM helpers and file browsing. |

## Reference

| Document | Contents |
|---|---|
| [Architecture](ARCHITECTURE.md) | Diagrams of the system, the VM access boundary, the deploy-to-ready sequence, the capture stack and persistence, plus a module map and the VM paths. |
| [Changelog](CHANGELOG.md) | Release notes for every version since 1.10, newest first. |
| [Repository maintenance](REPOSITORY-MAINTENANCE.md) | Release consistency checks, packaging rules and the CI workflow. |
| [Wiki master guide](WIKI-MASTER-GUIDE.md) | The long-form build and operations guide formatted for Wiki.js. |
| [Node features](../clab-backup-ui/NODE-FEATURES.md) | Node-level behaviour: SSH terminals, backups, the map and exports. |
| [Validation evidence](../clab-backup-ui/VALIDATION.md) | What was actually tested for each release, on the dev VM and locally. |
| [Agent instructions](../agent%20instructions.md) | Handoff notes for coding agents, newest release first. |
| [Capture third-party notices](../deploy/CAPTURE-THIRD-PARTY-NOTICES.md) | Licences of the Edgeshark and Wireshark components. |

## Archive

Superseded documents kept for history: the
[original fresh VM guide](archive/FRESH-VM-GUIDE.md) (manual installation before
the terminal installer), [fresh image and worker upgrade, 1.6.1](archive/FRESH-IMAGE.md),
[UI refinement 1.12.1](archive/UI-UPDATE-1.12.1.md), the
[deployment and operation audit for 1.19.2](archive/DEPLOYMENT-AUDIT.md) and the
[Git lab progress proposal](archive/GIT-LAB-PROGRESS-PROPOSAL.md) that became
*Save progress*.
