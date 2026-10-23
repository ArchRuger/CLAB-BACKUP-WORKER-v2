# Parity campaign: pickup file

The owner's instruction (2026-10-23): reach feature parity between this manager and
[`srl-labs/containerlab-app`](https://github.com/srl-labs/containerlab-app) (web, desktop and VS Code apps sharing
one topology editor) and the VS Code Containerlab extension, as UI/UX improvements, within the memory and storage of
the development VM, tested on the Juniper images first: `n24l/vjunos-switch:23.2R1.14`,
`n24l/juniper_vjunos-router:26.2R1.7`, `n24l/cjunosevolved:26.2R1.7-EVO`, with `n24l/cisco_xrv9k:24.3.1` and
`n24l/ceos:4.35.0F`. The owner is away; the work runs unattended in checkpointed chunks, each committed and pushed on
this branch, each a release of its own with its CHANGELOG, VALIDATION and handoff sections.

## State

- **Branch**: `claude/parity-campaign`, stacked on `claude/agent-routing-embed` (pull request 71, release 1.31.1,
  the agent routing in `.claude/`). Merge 71 first; this branch's pull request will be opened against `main` and
  carries 71's commits until then.
- **Research**: running (a dynamic workflow: eight inventories, the gap matrix, a critic). Its result becomes
  `RESEARCH.md` (inventories) and `PARITY.md` (the matrix with dispositions: present, partial, absent, not pursued
  with the invariant that rules it out) in this folder.
- **VM**: 72 GB RAM, 24 CPUs, 98 GB free disk, KVM present; the five images are pulled; two labs from the Git
  redesign stream exist with their containers exited (`git-redesign`, `git-redesign-b`); the manager and the capture
  stack run (release image 1.31.0 at the time of writing).
- **Chunks**: not yet decided; the matrix proposes them, the lead orders them (most valuable and least risky first,
  live-lab chunks explicit).

## How to continue after an interruption

1. `git status`, `git log --oneline -5`, this file, then `PARITY.md` for the chunk in progress and its checklist.
2. Every chunk follows `.claude/rules/clab-ui-routing.md`: design under this folder, `/clab-design-review`, build in
   slices with the named agents, `/clab-slice-verify` and `/clab-review-changes`, a live pass on the Juniper labs
   where the chunk touches devices, then the release step (`clab-release` skill) and a push.
3. Memory before a lab: `free -g`; vJunos-switch and vJunos-router boot as VMs (5 GB each, 4 vCPU), XRv9k wants
   16 GB; stagger the boots and keep one operator per lab.

## Log

- 2026-10-23 01:40 UTC: branch created; research workflow started at 01:21 UTC.
- 2026-10-23 01:50 UTC: the `parity` lab deployed from `/srv/containerlab-node-manager/projects/parity/parity.clab.yaml`
  (five nodes, management 172.20.20.111 to .115, published default logins); cJunosEvolved, cEOS, vJunos-switch and
  XRv9k answer on SSH with their versions, vJunos-router still booting. Memory with all five up: about 29 GB used.
- 2026-10-23 01:50 UTC: first slice committed: the kind `juniper_vjunosrouter` is known to the manager for backups,
  downloads, saves, the lab-builder catalog and the labels; restore and network design stay off for it until the
  live proof on `vrt` (then: `restore_junos.SUPPORTED_KINDS`, the `restore*` keys in `inventory.PLATFORMS`, and the
  two tests that pin the absence). `docs/parity-campaign/` is history-exempt in `verify-release.py`.
