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
- **Research**: done (`RESEARCH.md`, `PARITY.md`); the plan with the chunk order is `README.md`.
- **VM**: 72 GB RAM, 24 CPUs, 98 GB free disk, KVM present; the five images are pulled; two labs from the Git
  redesign stream exist with their containers exited (`git-redesign`, `git-redesign-b`); the manager and the capture
  stack run (release image 1.31.0 at the time of writing).
- **Chunk in progress**: C02 built (checkpoint `d00ccf1`, not released) and under verification; C03 helper slice in build; see the log.

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
- 2026-10-23 02:05 UTC: research landed (99-row matrix, critic). The manager on the VM is 1.31.1 from this branch
  (`sudo bash deploy/start-manager.sh`), the `parity` lab is imported (lab id `d7e3a4686c084f9f88e344b5064aa162`), five
  nodes Ready with inventory logins. vJunos-router: the container is up but its VM relaunches every five seconds
  (291 launches); triage is C00.
- 2026-10-23 02:05 UTC, **C00 result**: `n24l/juniper_vjunos-router:26.2R1.7` does not boot on this VM. The container's
  launcher starts the outer qemu with `-cpu host`; the Junos "VM-VMX" architecture then starts an inner qemu 2.7.0,
  which aborts with `kvm_put_msrs: Assertion 'ret == cpu->kvm_msr_buf->nmsrs' failed` (two levels of nesting under a
  VM host; the vJunos-switch launcher uses a fixed IvyBridge model with `vmx=on` and boots here). A test-only local
  image `local/juniper_vjunos-router:26.2R1.7-nested` (Dockerfile: one `sed` on `/launch.py` applying the switch's
  CPU model; never pushed) replaces the node's image in `parity.clab.yaml`; `containerlab deploy` reconciled the
  lab, recreating `vrt` and its link neighbours `vsw` and `cjunos` (02:04 UTC). The manager's catalog keeps the
  published tag: on a bare-metal host the published image is expected to boot; the owner should know that the
  nested case needs the CPU-model fix (upstream vrnetlab issue material).
- 2026-10-23 02:30 UTC, **C01 live pass (partial, four of five nodes)**: with `vrt` on the nested-virtualization image,
  vJunos-router boots (`show version`: Model vmx, Junos 26.2R1.7) and the manager's jobs through the real pipeline
  succeeded on `vrt`, `vsw`, `xrv9k`, `ceos`: test logins 4/4 (job `a2c78ce6…`), backup 4/4 "Configuration saved" (job
  `e20f18a2…`, archive `parity_2026-10-23_02-30.zip`); the router's download name is
  `vJunos-router_vrt_2026-10-23_02-30UTC.cfg` and its node carries no `restore_format` (restore off by design). The
  node record still shows the originally imported image tag; a Sync from VM would pick up the local tag. `cjunos`,
  recreated at 02:04 with the others, had not opened SSH by 02:30 (first boot took nine minutes); being looked at.
- 2026-10-23 02:44 UTC: `cjunos` finished booting (Model ptx10001-36mr, 02:40); test login 1/1 (job `0d4b97c6…`) and
  backup 1/1 (job `273ded5b…`), so the C01 live pass covers all five nodes through the manager. C02 is in build (four
  slices), the C03 helper slice is in build; the C03 manager and UI slices wait for C02's files to settle.
- 2026-10-23 03:00 UTC: C02 built in four slices and committed as a checkpoint (`d00ccf1`); the manager on the VM was
  rebuilt from the tree (3 s loop) so the cancel route exists live. Running: `/clab-slice-verify` (tests, attack, fixture
  at 1440 and 760 plus read-only live checks of the terminal and Copy on the parity lab), `/clab-review-changes` (base
  `408a2fd`), and a `clab-devops-engineer` live stop pass on a disposable two-cEOS lab `stoptest` (evidence to
  `evidence/c02-live-stop.md`). The C03 helper slice (`host_operations.py`, new `test_host_diagnostics.py`) is
  uncommitted in the tree and breaks one images test until its contract is settled.
