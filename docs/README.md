# Documentation

Start with the [project README](../README.md) for the overview, the quick start and
the system diagram. The guides below go deeper.

Three conventions hold across every guide:

- **Every command works from any directory.** The scripts find the source checkout
  themselves. The guides keep the source in `~/projects/clab-manager` and write
  commands as `bash "$HOME/projects/clab-manager/deploy/<script>"`; replace that path
  if you cloned elsewhere.
- **The guides describe the current release** and name no version of their own. What
  changed in each release is in the [changelog](CHANGELOG.md); the release check
  (`python3 deploy/verify-release.py`) refuses a guide that names an older release or a
  versioned source folder, so a guide that mentions a release is either the current one
  or says "since x.y.z".
- **Browser Wireshark and the Grafana dashboards are part of every installation**, not
  add-ons: the installer sets both up, an upgrade refreshes both, and the health check
  reports either one missing.

## Install

| Guide | Use it when |
|---|---|
| [Quick install](QUICK-INSTALL.md) | You want the shortest route from a fresh Ubuntu VM to a saved lab: only what to paste, type or click. |
| [Fresh VM guide, version 2](FRESH-VM-GUIDE-V2.md) | You are building the VM yourself: Proxmox settings, Ubuntu, the installer, WinSCP and VS Code checks, the first Git save, and recovery for each step. |
| [Guided VM installation](INSTALL.md) | You want to know what the terminal installer's menu, phases and options do, how upgrades work, and how the Wireshark and Grafana stacks are managed. |
| [VM connection](VM-CONNECTION.md) | You are creating or repairing the `clab-discovery` account and its password, or the manager cannot reach the VM. |
| [Manual setup and migration](STANDALONE-SETUP.md) | You want the pieces the installer runs, one by one, or you are moving data from the older in-lab worker container. |

## Operate

| Guide | Use it when |
|---|---|
| [Lab operations](LAB-OPERATIONS.md) | You deploy, destroy or inspect labs, browse VM topologies, edit the diagram, or want to know how NOS readiness is judged. |
| [Git setup](GIT-SETUP.md) | You register a VM checkout so *Save progress* can commit and push with the owner's login. |
| [Save lab progress](GIT-PROGRESS.md) | You use saves, checkpoints, baselines, history and loads. |
| [Browser Wireshark](CAPTURE.md) | You start capture sessions, download captures, repair or remove the capture stack, or need the security boundary of the capture services. |
| [Network telemetry](TELEMETRY.md) | You want to know what the manager collects from a deployed lab and how, what the Grafana dashboards show, the per-lab setting, per-NOS support, bounds, security notes and the live acceptance procedure. |
| [Grafana lab map](GRAFANA-MAP.md) | You want the srl-telemetry-lab style weathermap in Grafana: how the manager generates one per lab, what a new lab needs, what you still craft, and how to build a hand-tuned variant from the generated SVG and configuration. |
| [Health check](HEALTH-CHECK.md) | You read `deploy/check-install.sh` output and fix FAIL or WARN lines. |
| [Debug panel](DEBUG-PANEL.md) | You use the development diagnostics page to probe VM helpers and file browsing. |

## Reference

| Document | Contents |
|---|---|
| [Tour](TOUR.md) | Screenshots of the UI: the deploy-to-ready sequence, node actions, SSH, backups, Git and Wireshark in the browser. |
| [Architecture](ARCHITECTURE.md) | Diagrams of the system, the VM access boundary, the deploy-to-ready sequence, the telemetry path, the capture stack and persistence, plus a module map and the VM paths. |
| [Changelog](CHANGELOG.md) | Release notes for every version since 1.10, newest first. |
| [Repository maintenance](REPOSITORY-MAINTENANCE.md) | The release rules: the lockstep version set, the documentation conventions, the bump procedure, packaging limits and the CI workflow. |
| [Wiki master guide](WIKI-MASTER-GUIDE.md) | The long-form build and operations guide formatted for Wiki.js. |
| [Node features](../clab-backup-ui/NODE-FEATURES.md) | Node-level behaviour: SSH terminals, backups, the map and exports. |
| [Validation evidence](../clab-backup-ui/VALIDATION.md) | What was actually tested for each release, on the dev VM and locally. |
| [Agent instructions](../agent%20instructions.md) | Handoff notes for coding agents, newest release first. |
| [Capture third-party notices](../deploy/CAPTURE-THIRD-PARTY-NOTICES.md) and [telemetry third-party notices](../deploy/TELEMETRY-THIRD-PARTY-NOTICES.md) | Licences of the Edgeshark, Wireshark, Prometheus, Grafana and Flow panel components. |

## Archive

Superseded documents kept for history: the
[original fresh VM guide](archive/FRESH-VM-GUIDE.md) (manual installation before
the terminal installer), the [Docker Hub image guide](archive/DOCKER-HUB-SETUP.md)
(a pulled image with SSH-key VM authentication, before passwords and the installer),
the [fresh image and worker upgrade](archive/FRESH-IMAGE.md) of the in-lab worker
era, a [UI refinement note](archive/UI-UPDATE-1.12.1.md), the
[repository audit](archive/REPOSITORY-AUDIT-1.15.1.md) that introduced the release
checks, the [deployment and operation audit](archive/DEPLOYMENT-AUDIT.md) and the
[Git lab progress proposal](archive/GIT-LAB-PROGRESS-PROPOSAL.md) that became
*Save progress*.
