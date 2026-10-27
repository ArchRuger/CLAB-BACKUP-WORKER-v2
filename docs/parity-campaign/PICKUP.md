# Parity campaign: pickup file

The owner's instruction (2026-10-23): reach feature parity between this manager and
[`srl-labs/containerlab-app`](https://github.com/srl-labs/containerlab-app) (web, desktop and VS Code apps sharing
one topology editor) and the VS Code Containerlab extension, as UI/UX improvements, within the memory and storage of
the development VM, tested on the Juniper images first: `n24l/vjunos-switch:23.2R1.14`,
`n24l/juniper_vjunos-router:26.2R1.7`, `n24l/cjunosevolved:26.2R1.7-EVO`, with `n24l/cisco_xrv9k:24.3.1` and
`n24l/ceos:4.35.0F`. The owner is away; the work runs unattended in checkpointed chunks, each committed and pushed on
this branch, each a release of its own with its CHANGELOG, VALIDATION and handoff sections.

## State

- **Branch**: `claude/parity-campaign`, pull request 73 against `main` (the routing release, pull request 71, and the
  campaign up to the C05 checkpoint, pull request 72, were merged into `main` on 2026-10-23; the owner merges 73 when
  the lead says it is ready; worker and integration branches are never merged on their own).
- **Research**: done (`RESEARCH.md`, `PARITY.md`); the plan with the chunk order is `README.md`.
- **VM**: 72 GB RAM, 24 CPUs, KVM present; the five images are pulled; the `parity` lab (vsw, vrt, cjunos, xrv9k, ceos)
  runs; the manager and the capture stack run the release named in the last log entry.
- **Chunk in progress**: see the last log entry.
- **Campaign 2 (2026-10-27)**: the owner's four-objective extension; its chunk ledger, routing record and
  decisions are [CAMPAIGN-2.md](CAMPAIGN-2.md); the acceptance matrix is [ACCEPTANCE.md](ACCEPTANCE.md) and the
  per-image matrix [DEVICES.md](DEVICES.md) (both written during the campaign).

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
- 2026-10-23 07:40 UTC, **release 1.31.3** (the C03 drawer sections and the rest of its UI, C04 serial console and
  container facts, the C05 helper): the `/clab-review-changes` on `d303f38..cd91e2d` (17 confirmed, 1 must-fix already
  fixed) answered in C03-DESIGN §12, C04-DESIGN §10, C05-DESIGN §10 and every finding applied (`c741320`); the C03 UI
  verified and passed live, the console passed live on `vrt`. In flight, not in this release: the C05 manager slice on
  branch `claude/c05-manager` (`0cd4225`) with its drawer (S3) and map/reviews (S4) UI slices in the worktrees
  `c05-s3` and `c05-s4`; C07 S1 and S2 in agent worktrees; the C06, C07, C08 (amendment in progress) and C09 designs
  answered. Next: merge `claude/c05-manager` with S3 and S4 onto the branch, `/clab-slice-verify` and
  `/clab-review-changes` for C05, the live pass (delay on `vsw`–`vrt` seen in a ping, Reset, Clear all, a filtered
  destroy and Apply of `ceos`, Stop and Start device), release 1.31.4; C07 likewise; then C06, C08, C09 builds; C10 when
  the VM is quiet.
- 2026-10-23 08:30 UTC (usage limit reached mid-flight; durable checkpoint): C05 is integrated on the branch (`3b36667`,
  the merge of `claude/c05-manager`: manager, drawer and map/reviews slices; node 934 pass, Python 2807 OK) and the
  live manager runs it; `/clab-slice-verify`, `/clab-review-changes` (base `ce74255`) and the live pass on the parity
  lab were running when the session stopped: read their results from the next session's `/workflows` or rerun them;
  the 1.31.4 records are drafted in the session scratchpad (not in the repo: redraft from C05-DESIGN if lost). Built
  and committed in worktrees, not yet integrated (branches pushed to origin): C07 S1 `worktree-agent-a87dbddcbea4e9020`
  (`1682abe`, capture sets, sessions list, End all), C07 S3 `wt-c07-s3` (`6f424b4`, smoke and fixture capture stack),
  C08 S1 `worktree-agent-af2508aa01d396b7d` (`50bfbf5`, `locateYaml` and the rebuilt bundle), C09 S3
  `worktree-agent-af1a2ef97ccdf799f` (`d198b02`, `preferences.js`). Still in build when the session stopped: C07 S2
  (UI), C08 S2 (validator and schema), C06 S0+S1b, S1a, S2 (agent worktrees under `.claude/worktrees/`). Next: finish
  C05 (verification fixes, review answers in C05-DESIGN, release 1.31.4 with `test_impairments.py` and
  `test_device_impairments_ui.js` already in CI), integrate C07 (S2 then S4 docs, review, live pass), C08 (S3 after S2),
  C06 (S3 after S2, S4, S5), C09 (S1, S2 after C07 frees `index.html` and `shell.js`); C10 when the VM is quiet.
- 2026-10-23 11:30 UTC, **release 1.31.4** (C05: impairments, Stop and Start device, the apply plan and pending
  changes, Run with options, per-device save; the helper half shipped in 1.31.3): `/clab-slice-verify` (9 of 11 held,
  seven breaks), `/clab-review-changes` (23 confirmed, one must-fix: Confirm live during a re-preview) and the live
  pass on the parity lab (two breaks: vJunos rows printed as `eth1 (ge-0/0/0)`, the map not re-read after a drawer
  change) all answered in C05-DESIGN §11 and §12 and every finding applied (`2d8afde`, `698c63e`, `28a7afa`). Built,
  verified and waiting their turn on integration branches (all pushed): C07 `claude/c07-int` (slices, fixes from its
  verification, C07-DESIGN §10; the live capture pass running against a manager rebuilt from that tree), C06
  `claude/c06-int` (four slices and docs; its fixture slice `wt-c06-s4` in build, then `/clab-slice-verify`), C08
  `wt-c08-s3` (three slices, docs, fixes, C08-DESIGN §10; CI needs `test_lab_builder_check_ui.js` and
  `test_clab_schema.py`), C09 `claude/c09-int` (three slices and docs; `/clab-slice-verify` running). Next, in
  order: merge C07 onto the branch, `/clab-review-changes`, release 1.31.5 (records drafted in the session
  scratchpad); then C06 (verification, review, live pass), C08 and C09 (reviews), each a release; C10 last.
- 2026-10-23 15:40 UTC, **release 1.31.5** (C07: capture parity; built on `claude/c07-int`, fast-forwarded onto the
  branch, then `/clab-review-changes` with base `6c3f5d5`: 10 confirmed, 2 refuted, the fixes in `f2e6e1e` and the
  answers in C07-DESIGN §12; the verification §10 and the live pass §11 were done on the integration branch).
  `main` was merged back into the branch (`541e3ac`, merge commits only) after pull requests 71 and 72 landed.
  Waiting their turn (all pushed, each with the campaign head `61ccce5` merged in): C06 `claude/c06-int` (`c733849`:
  the four slices, the S4 fixture slice and `check_c06.py`, the docs, the lead's fix for the script-load race;
  `/clab-slice-verify` running on the fixture; then merge onto the branch, `/clab-review-changes`, the live pass with
  the A1 `vm`-wording check, release 1.31.6 with the draft in the session scratchpad), C08 `wt-c08-s3` (`2bdc9cf`:
  verified, CI entries added, bundle check clean; review, release), C09 `claude/c09-int` (`72334f5`: verified,
  shortcut rows repointed after the merge; review, release); C10 last; C11 blocked on upstream 0.4.0.
- 2026-10-23 17:30 UTC, **release 1.31.6** (C06 Topology tab parity, C08 builder YAML checks, C09 Help, shortcuts,
  Home filter and browser preferences, in one release for budget: the owner reported 75 % of the week's usage spent).
  C06: `/clab-slice-verify` on `claude/c06-int` (every acceptance check held, eight breaks: one high, a merge that put
  C05's tests in the wrong class; four medium; three low), a single `risk-reviewer` pass on the backend diff (three
  should-fix) and the compact live pass on the parity lab (link state 5 of 5, cEOS `shutdown` → `dormant` in 12 s,
  the A1 vJunos check left both ends `up` so the `connected` wording ships, arrange and Undo exact, a stale Undo 412,
  the draw.io export), all answered in C06-DESIGN §10 to §12. C08 and C09: verified earlier on their branches
  (§10 of each design), then one `clab-ui-reviewer` pass each instead of the full branch-review workflow (C08:
  `bridge` is not a special endpoint, proven with `containerlab validate` on this VM; limits of the check are no
  longer errors; the caption only when a check ran; C09: the Reset confirmation names Needs attention again, the
  shortcut pin hardened, Space on Help links), fixed on their branches and merged (`cec09c1`, `6cf477e`); the
  cross-chunk integration fixes (shortcut cites, the builder note as a preference family) in the following commit.
  **Dropped or deferred by the revised plan**: the full `/clab-review-changes` workflow on C06, C08 and C09; C10
  (the vJunos-router Load proof) and C11 (editor 0.4.0, blocked upstream) are not started; the low findings listed
  in each design's answers stand as open points. Pull request 73 (`claude/parity-campaign` → `main`) carries
  1.31.2 to 1.31.6; the owner merges it. The worktrees under `.claude/worktrees/` and the side branches are history
  after this release and may be removed.
- 2026-10-27 01:20 UTC, **campaign 2 started** (D00): baseline recorded in `CAMPAIGN-2.md` (branch at `e709f3d` = 1.31.6,
  `main` merged pull request 77, the VM rebooted at about 00:35 UTC and every lab container exited; manager and capture
  stack back at 1.31.6). Routing verified from the agent transcripts (Haiku scout, Sonnet devops; Opus reviewers in
  flight). Official kind defaults rechecked for the six images (table in `CAMPAIGN-2.md`); containerlab.dev states
  vJunos-router "cannot be used in any deployments that launch it from within a VM", which makes the C00 blocker an
  official host limitation. npm still lists only `@containerlab/clab-ui` 0.3.2: C11 stays blocked. Running: A01
  (`ACCEPTANCE.md` by `docs-auditor`), A02 (the deferred C06/C08/C09 reviews by `risk-reviewer` and `clab-ui-reviewer`
  on the 1.31.5→1.31.6 diff), B03a (`clab-devops-engineer`: vSRX pull and solo boot in `camp-vsrx`, the `parity` lab
  redeployed). Next: the topology-editing design (T01) from the editor's integrator documentation, B02 (vSRX registry)
  once B03a reports the image's console and interface facts.
