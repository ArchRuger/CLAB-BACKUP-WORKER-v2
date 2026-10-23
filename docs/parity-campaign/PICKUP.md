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
- 2026-10-23 03:25 UTC: C03 helper (`3c982c1`) and manager side (`device_diagnostics.py`, routes GET logs/interfaces/netem,
  GET images with details/used_by/missing, POST browse with files mode, POST view; installed before `LabOperations` so it
  owns `browse` and `images`, whose old handlers were removed) committed as checkpoints; `fixture_manager.py` answers the
  new modes. The C03 UI slice (`device-diagnostics.js` and hooks) starts when the C02 verification finishes, because the
  fixture serves the tree. C02 live stop pass done (`evidence/c02-live-stop.md`).
- 2026-10-23 03:50 UTC: C02 verified (`/clab-slice-verify`: all nine acceptance checks held in Chromium and Firefox over
  plain http; five breaks, one medium) and code-reviewed (22 confirmed, none must-fix); every finding fixed and
  committed (`fcde544` Python, `dd3a3b5` UI; answers in C02-DESIGN §8). Running: a second `/clab-review-changes`
  (base `d00ccf1`, covering the fixes and the C03 helper and manager checkpoints), a QA re-check of the fixes, the
  full Python suite. Next: release 1.31.2 (C01, C02, the C03 helper and API; records drafted in the session), rebuild
  with `sudo bash deploy/start-manager.sh` because the helper changed, then the C03 UI slice.
- 2026-10-23 04:45 UTC, **release 1.31.2** (C01, C02, the C03 helper and API): the second `/clab-review-changes`
  (`d00ccf1..c3f3d94`, 21 confirmed, none must-fix) was answered in C02-DESIGN §8a and C03-DESIGN §10 and every
  should-fix applied (log and viewer redaction across window cuts, the raw `/read` route kept to its old file types,
  `container_prefix`, images, the terminal status row and Save session after Clear); the manager and helpers were
  rebuilt from the tree and the diagnostics routes exercised live on `vrt` (VALIDATION). Built in parallel and NOT in
  this release: the C03 UI slice (worktree `agent-a47614a36aae4bd74`, commit `ac73779`; `/clab-slice-verify` running),
  `C04-DESIGN.md` (reviewed: 22 confirmed, 2 must-fix on the console-before-launcher race; the designer is answering
  them in §9) and `C05-DESIGN.md` (lead's amendment §1.2: netem modes under a non-blocking flock with a request
  digest; `/clab-design-review` running). Next: integrate the C03 UI slice onto this release (its `?v=` tag moves to
  1.31.2, `test_device_diagnostics_ui.js` joins the CI node line, the deferred Try again mapping for start, apply and
  restart lands with it), `/clab-review-changes`, a live pass on the parity lab, release 1.31.3; then C04 and C05
  builds from their answered designs.
- 2026-10-23 05:50 UTC: after 1.31.2 (pull request 72, stacked on 71): the C03 UI slice is integrated on the branch
  (`9d35cc1` cherry-picked from the worktree, assets at 1.31.2, `test_device_diagnostics_ui.js` in CI, the deferred Try
  again mapping applied, `f2fd2ae`); the live manager was rebuilt with it (image only; helper unchanged). Running: its
  `/clab-slice-verify` (from the worktree) and a read-only live pass on the parity lab. `C04-DESIGN.md` answered its
  review (22 rows) and S1a is committed (`fd8da7f`: `console_gate`, the telnet codec, one console per device,
  `test_node_console.py` in CI); S1b (discovery fields, the public row, the Start fresh guard) is in build.
  `C05-DESIGN.md` answered its review (30 rows, `cc8d5ca`); S1 (the helper's lifecycle modes) is in build by
  `clab-fable-specialist`. Next: C03 fixes from the verification and `/clab-review-changes` on `d303f38..`, release
  1.31.3 with the C03 UI; then C04 S2 UI and S3 docs, `/clab-review-changes` with `risk-reviewer` and
  `clab-network-specialist` on the console diff, the live console pass on `vrt`; C05 S2 manager after C04 S1b frees
  `discovery.py` and `main.py`.
- 2026-10-23 06:20 UTC: towards 1.31.3 (all on the branch, pushed): the C03 UI slice verified (`/clab-slice-verify`,
  12 of 16 held; answers C03-DESIGN §11) and passed live on `vrt`, `vsw`, `xrv9k`; its two medium and eleven low
  findings fixed (`766558c`, `314dff7`); the live break on `ceos` and `cjunos` (Docker refused the inspect format for a
  container without a HEALTHCHECK) fixed in the helper with the C05 S1 slice (`524fba4`) and re-checked live after
  `start-manager.sh`. C04 built in three slices (`fd8da7f` console service, `08e7336` discovery and public row, `21a1b41`
  UI, `2e082c2` docs) and passed its live console pass on `vrt` (login, `show version`, one console per device, the
  held-console refusal, events only); one break (the container id read under `id`, containerlab writes `container_id`)
  is being fixed with the C05 S2 manager slice, in build. Designs C06 (`04391ea`) and C07 (`50a6549`) answered the
  lead's questions and are under `/clab-design-review`; C08 and C09 designs in writing. Running: `/clab-review-changes`
  on `d303f38..` (the whole 1.31.3 scope). Next: its fixes, the Python suite, release 1.31.3 (records drafted in the
  session's scratchpad), `start-manager.sh`; then C05 S3/S4 UI from the manager slice's route report, the C06/C07
  builds from their answered designs.
