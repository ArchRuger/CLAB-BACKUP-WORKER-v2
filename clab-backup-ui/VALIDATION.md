# Student-centred UI redesign, live-lab release validation and two fixes — 1.29.0

Prepared on `claude/1.29-release-validation` from `main` `66864c8` (PR #35, the merged redesign) on
2026-09-17. The redesign itself was validated on the fixture manager (below, "What was run"); this
release adds the live-lab acceptance pass on a real containerlab VM, the two defects it found and
their fixes, and the release bookkeeping. Release decision: **PASS — 1.29.0**.

## What was run

- `node --test tests/*.js`: 133 tests, all pass (the four redesign suites plus every existing
  browser suite with its pinned labels rewritten, behavioural claims kept).
- Python `unittest discover -s tests -t tests`: OK (one skipped: the opt-in SSH fixture). No
  backend file changed in the redesign; the run proves the helpers, routes and services
  are untouched.
- `node --check` on every `app/static/*.js`; `git diff --check` clean;
  `python3 deploy/verify-release.py` passes (1.28.0, documentation names only 1.28.0).
- Id audit: every element id the scripts look up exists in the page markup or in the
  dialogs the scripts inject; the remaining names are query-string keys.
- Browser validation with Playwright Chromium against `docs/redesign/tools/fixture_manager.py`
  (the real application on a scratch data directory; seeded labs; the readiness probe, the
  discovery refresh, backup jobs, the Git helper, the restore probe and the lab-operations
  helper answered in-process) with `docs/redesign/tools/verify_after.py` at 1920×1080,
  1440×900 and 1366×768: Home, every tab, the topology map (fits the viewport at 1366×768),
  the context menu, the device panel, the Progress flows (saved versions, compare, apply
  review, first save, checkpoint name, save location browser), Tools (capture dialog,
  telemetry settings), the lab-operation reviews and the banner-first confirm, All lab
  operations, Running labs on the VM, operation history and output, Advanced, Remove lab,
  polling stability with the device panel and a menu open across two polls, the CLI
  launcher, the deploy page with the topology browser and editor, Diagnostics, the network
  dashboard page, the terminal page and the guides. Zero console errors and zero page
  errors; the one non-2xx response Chromium logs is the optional `.annotations.json` read
  beside a topology, which the page expects to fail. Screenshots: `docs/redesign/shots/`.
- Functional-parity review: four independent read-only reviews of the code against
  `docs/redesign/inventory/*.md` and `docs/redesign/parity/*.md` (shell + topology,
  Git progress + restore, operations + management, capture + pages). Every inventory row
  is present; the findings (destroy copy when cleanup is unavailable, the clone review
  title, busy-disabled controls without a reason, the dropped *Lab:* line of the restore
  review, a fetch failure reading as "not saved yet", lab-scoped operation history, the VM
  file details of imported labs, unexplained disabled buttons on Advanced, logs refreshed
  while off screen, device row id collisions, the deploy flow bypassing the router, capture
  and Diagnostics copy details) were fixed in the same branch. Intentionally removed: none.

## Live-lab validation on the dev VM `clab-llm-dev2` (2026-09-17)

The host was installed with `docs/QUICK-INSTALL.md` during this pass (Ubuntu 24.04.4, Docker
29.8.1, Docker Compose 5.5.1, containerlab 0.79.0, manager container
`containerlab-node-manager-backup-ui-1`, the browser Wireshark and Grafana stacks, the discovery
password and helpers, the Git helper). Lab `clab-llm-dev2` (`/etc/containerlab/clab-llm-dev2/`):
PTX1 `n24l/cjunosevolved:26.2R1.7-EVO` (`juniper_cjunosevolved`, 172.20.20.2) and SW1
`n24l/vjunos-switch:23.2R1.14` (`juniper_vjunosswitch`, 172.20.20.3), containerlab default login,
two links `PTX1:et-0/0/0—SW1:eth1`, `PTX1:et-0/0/1—SW1:eth2`. Git: checkout
`~/labs/CLAB-MNGR-DEV-LLM` of `github.com/pruger-dev/CLAB-MNGR-DEV-LLM` (owner `clabllm`, `gh`
login `pruger-dev`), lab folder `clab-llm-dev2/work`, reference states
`clab-llm-dev2/reference/{start,solution,broken-01}` made with `deploy/scaffold-lab.py`, a nested
folder `Week-01/BGP/Final-State` created from the UI. Every gate below was driven through the
real UI with Playwright Chromium against `http://127.0.0.1:8081` (screenshots and JSON reports
kept in the session scratchpad; console and page errors were collected for every run: **0 console
errors, 0 page errors** in all of them, one handled HTTP non-2xx per run where noted).

| Test | Result |
|---|---|
| manager rebuild against existing persistent state | `docker compose -f clab-backup-ui/compose.yml up -d --build` twice mid-session (after the helper fix and after the UI fix) and once more at 1.29.0: the lab, its Git binding, backups, credentials and layout loaded; no traceback |
| Home / existing labs | lab card with the *Running* pill, *2 of 2 devices ready*, last save; Manager ▾ with VM connection, Deploy, Running labs, Operation history, Diagnostics and the VM status / version footer; menu survives a poll, Escape returns focus |
| deploy / redeploy Starting → Running | Deploy through *Deploy a new lab* → topology browser → *Deploy lab* → review "Start clab-llm-dev2?" (command under Technical details) → confirm at 10:22:21 UTC; UI went Stopped → *Starting — 0 of 2* (10:22:38) → *1 of 2* (10:33:08, PTX1's Open CLI enabled alone) → *Running, 2 of 2* (10:43:53), banner cleared, no reload. Redeploy through Lab actions ▾ at 11:08:16: *Redeploying lab…* banner with View output → Starting 0 of 2 → 1 of 2 (+510 s) → Running 2 of 2 (+1321 s); rows and map dots changed per device; containers recreated (StartedAt changed) |
| topology state updates | both devices drawn with state dots, `state-starting` → `state-ready` per device during boot; header pill/readiness agree; map fits at 1440×900, 1920×1080 and 1366×768; context menu (Open CLI first, Capture, Back up, Details; state in the header; survives a poll; Escape/Shift+F10); Expand/Escape; Edit lab map; Import map dialog; a map link activated from the keyboard opens *Capture traffic* on that endpoint |
| Open CLI | device panel of PTX1 (Ready, Open CLI first) → terminal page "clab-clab-llm-dev2-PTX1 · clab-llm-dev2", *Connected*; `show version`, `show interfaces terse`, `show configuration \| display set` typed and answered by Junos; resize changed the columns; Disconnect → *Disconnected*; Reconnect → *Connected*; the panel stayed open afterwards |
| Save Progress | unbound lab: *Connect a save location…* → first-save dialog; the suggested folder `clab-llm-dev2` was refused ("Lab folders in one repository cannot overlap: clab-llm-dev2/work is already a lab folder") → `clab-llm-dev2/work` → *Saving…* → *Saved to Git just now*; recent save row *Progress saved to Git*; checkout clean, nothing staged; commit `babef21` with `latest/{PTX1,SW1}.{set,jcfg}` + `manifest.json` |
| Git push | after every save `git rev-list origin/main..main` = 0 and GitHub's `main` SHA equalled the local HEAD (checked over the API) |
| checkpoint | *Create checkpoint…* with `release-1.29-live-validation` → live preview *Saved as: release-129-live-validation* → **failed on the 1.28.0 helper** (defect 1 below) → after the fix, *Retry save and upload* from the save window completed it; listed under Saved versions with its own time; `work/checkpoints/release-129-live-validation/` holds manifest, `.set` and `.jcfg`; pushed |
| Saved versions | Latest (View, Apply), Checkpoints, *Instructor and reference versions* (after defect 2's fix: `reference/start`, `reference/solution` with Apply; *Final state (instructor)* naming), Full history dialog; View → files + *Download (ZIP)* (real download: `.set`, `.jcfg`, `manifest.json`) |
| compare | *Compare with my latest save* on the checkpoint → "Compared with your latest save", diff rendered, no HTML interpreted, no "running configuration" wording |
| Apply to running lab | see the Junos restore evidence below: job `cd592c1c…` succeeded on **both** nodes from `clab-llm-dev2/reference/solution` (Saved versions → Apply, and the same from Browse the repository…), review with Lab / Source / Devices / three safety bullets / acknowledgement (running without it is refused with a sentence) |
| pre/post restore backups | `restore-pre` `4bdaefb0…` and `restore-post` `8d14040e…`, both succeeded for PTX1 and SW1, both in the backup history |
| stale config removed | PTX1 had `lo0 10.77.77.77/32`, host-name `PTX1-BROKEN-BY-STUDENT` and a deleted description committed by "the student"; after the restore the address is gone, the host-name is `PTX1`, the description is back, root-authentication present |
| no node reboot/recreate | PTX1 `StartedAt` `2026-09-17T11:08:16.395411838Z` before and after |
| packet capture | Tools → *Capture traffic…* (device picker first when no device is chosen); from PTX1's panel: device context, wired interfaces first, *Other interfaces on this device (12)*; *Start capture* → "Wireshark session started on the VM", session row *clab-clab-llm-dev2-PTX1 · eth1* with End session |
| browser Wireshark | *Open Wireshark ↗* → viewer page "Wireshark · Containerlab Node Manager", *Connected to Wireshark on the VM.*, remote screen drawn; a labelled container `clab-capture-clab-manager-capture-v1-…` existed for the session; ICMP generated on the link (5/5 answered). *End session* asks with `window.confirm`, which the headless run auto-dismissed, so the session was left to the 15-minute idle cleanup |
| telemetry/Grafana | *Telemetry settings…* in student sentences with a *Dashboard:* line; *Open lab map ↗* started Grafana on demand and opened the generated lab-map dashboard (`/d/clab-map-…/lab-map-…-clab-llm-dev2`); Grafana healthy, no plugin/dashboard errors in its log; Prometheus target `up`. No interface samples: this cJunosEvolved image rejects the gNMI subscription ("path or encoding not supported by this image") and vJunos-switch has no adapter. **Not a release gate — the maintainer is deprecating telemetry.** |
| Lab Actions reviews | Start disabled on the running lab with a reason; Stop / Restart / Redeploy reviews with the unsaved-work line, last save, *Save progress first*, command under Technical details, all cancelled; *All lab operations…* (Deployment / Lab tools / Danger); *Save device configurations* run from its review → banner with View output → output window; *Running labs on the VM…* → table with both devices; operation history (deploy, redeploy, save, inspect) and output |
| destroy review cancelled | "Destroy clab-llm-dev2?" with *Configuration changes you have not saved are lost*, the last-save line, *Save progress first*, danger confirm, `containerlab destroy … --cleanup` under Technical details → **Cancel**; lab still running |
| polling stability | device panel open with the same device and focus across three live polls; Lab actions menu keeps its focused item across three polls; focus on a row's Open CLI kept across two polls; the CLI session did not close the panel |
| 1366×768 live check | map bottom 668.9 < 768, no horizontal scroll, tabs and the header's Save progress within the viewport, destroy review confirm button not clipped (same at 1920×1080 and 1440×900) |
| Diagnostics | *This manager* / *VM connection* / *Saved in this manager* cards; probes against the real VM pass (*Folder listing*, *VM commands*); neither the discovery password nor the device password appears in the page |
| Advanced / operator | deployment details, VM file details of the lab, *Sync topology from VM* (no error), Add credentials dialog (platform / user / masked password), action logs (521 rows once the section is scrolled into view — it loads only while on screen, by design), Git technical details (branch, verified push destination), *Remove lab* dialog (danger submit, cancelled), the *Open CLIs* launcher page with two Ready rows |
| repository browser / nested folders | *Change folder…* shows the checkout with crumbs and *This lab*; `latest/` cannot be chosen (reason shown); `Week-01/BGP/Final-State` created in one step and registered on the VM (`setup-git.sh --list`); *New folder…* refuses `../etc` and `clab-llm-dev2/work` with a sentence; a non-Junos folder (`ARISTA-LAB-TEST`) offers no Apply |
| destination moves | *New folder… › Save this lab here* moved the lab from `clab-llm-dev2/work` to `clab-llm-dev2` (commit `3ee3f1b` "Move clab-llm-dev2 progress to clab-llm-dev2/", 10 files moved, pushed) and back into `work` with latest and the checkpoint travelling in one commit; the move dialog names the file count and consequences |
| failure paths | device not ready: Open CLI disabled with "still starting" in the context menu and the panel; save while devices boot: "Save failed · A device could not be read, so nothing was saved" in the status card, the row and the banner, `latest/` unchanged; busy: Stop / Restart / Redeploy / Destroy disabled with *Wait for the current operation to finish* while a save runs; the restore refuses to run without the acknowledgement; management-loss rollback observed for real (below) |
| security-boundary sanity | manager container: only `/srv/containerlab-node-manager/data` mounted, no Docker socket, user `worker`, not privileged; sudoers exactly the three helpers with empty argument lists; gateway accepts only the three commands; CSP unchanged; no secrets in Diagnostics or job records; restore job records carry no candidate |

### Junos restore evidence

Source `clab-llm-dev2/reference/solution/latest` (captured at 12:33:52 UTC from the running nodes,
schema 2, `restore_capable_nodes 2`). Deliberate stale state on PTX1 (direct SSH, committed with
the root-authentication the image requires): `lo0 10.77.77.77/32`, host-name `PTX1-BROKEN-BY-STUDENT`,
`et-0/0/0` description deleted. Job `cd592c1c48364704a5b94422e9114ce5`, 12:34:50 → 12:36:17 UTC:
`succeeded`, "All 2 node(s) restored and verified against the saved state."; PTX1 `verified`
(replaced, root-authentication present), SW1 `verified` (`no_op`: it already matched);
pre-backup `4bdaefb061b14a51b48be82ad78e7407` (`restore-pre`), post-backup
`8d14040e58304d74a6a990ffbbdbdfa0` (`restore-post`); the stale address and host-name gone from
`show configuration | display set`; PTX1 container `StartedAt` unchanged; the lab still saves to
`clab-llm-dev2/work`; *Last configuration change* on the Progress tab points at the job. This is
the first manager-orchestrated two-node restore and the first manager-orchestrated vJunos-switch
restore (both were "not verified" in 1.28.0).

A first attempt at 11:43 UTC, made with a solution state captured **before** the redeploy, showed
the safety net for real: containerlab had handed PTX1 a different management address after the
redeploy (172.20.20.3 → 172.20.20.2), the saved candidate carried the old one, the confirmed commit
moved PTX1 off its address, the manager could not reconnect (`NoValidConnectionsError`) and PTX1
rolled back by itself at 11:48:13 (`show system commit`: "commit confirmed, rollback in 5mins" then
the automatic rollback); the job ended `rollback_expected` / *Rolled back — unchanged* and SW1 was
left untouched (its session had landed on the node that briefly held its address). Nothing was
lost. The topology now pins `mgmt-ipv4` for both nodes, and `docs/GIT-PROGRESS.md` says so.

### Defects found during the live pass

1. **Release blocker, fixed.** `app/host_git.py` (the VM Git helper): the destination check of a
   save listed only each manifest entry's `path`, so the `.jcfg` restore artifacts written by the
   previous save of a Junos folder (schema 2, `restore_artifact`) looked like foreign files and every
   second *Save progress* or checkpoint into that folder was refused with "The destination contains
   files outside its manager manifest; preserve or move them first." (job `9b7ffb32…`,
   `export_pending`). Fix: the artifacts count as manifest-owned files, the "removes previously saved
   devices" guard looks at device files only, and an artifact the new manifest no longer references
   leaves the folder. Regression test
   `test_schema2_second_save_and_checkpoint_accept_the_folder_s_own_restore_artifacts` (fails on the
   old helper, passes on the fixed one). Retested live: the stuck checkpoint completed through *Retry
   save and upload*, a second latest save and repeated `scaffold-lab.py snapshot` saves into an existing
   reference folder succeeded. Refresh the helper with `setup-git.sh --refresh`.
2. **Medium, fixed.** Saved versions listed only the lab folder's direct siblings that hold a
   `latest/`, so the course layout the project's own scaffold creates (`<slug>/reference/<state>/latest`)
   never appeared under *Instructor and reference versions* (it stayed reachable through *Browse the
   repository…* and *Full history…*). `gitVersionGroups` now also lists the saved folders one level
   below a sibling that has no `latest/` of its own; test *saved versions list the course layout
   reference states one level below the lab folder*. Retested live: *Final state (instructor)* with
   Apply.

Observed and documented, not changed: a saved state captured before a redeploy that changed a
containerlab-assigned management address rolls back on apply (above; pin `mgmt-ipv4`); *Sync topology
from VM* keeps the manager's drawing (positions and links) when the VM has no annotations file, so a
link renamed in the YAML shows its old name on the map until the map is re-imported; *End session* in
the capture dialog uses a browser `confirm()`; the action logs fill only while the section is on
screen; Playwright cannot click a thin SVG link with the pointer (keyboard activation works). This
cJunosEvolved image names its data ports from `eth4` (the topology uses `et-0/0/0` aliases).

### Automated suites after the fixes

`node --test tests/*.js` 134/134; Python `unittest discover -s tests -t tests` 693 OK, 1 skipped
(the opt-in EOS SSH fixture); `node --check` on every static script; `bash -n` on every deploy
script; `git diff --check`; `deploy/verify-release.py` → `Source release verified: 1.29.0`;
`docs/redesign/tools/verify_after.py` against the fixture manager at 1920×1080, 1440×900 and
1366×768 rerun after the Saved-versions change: 93/93 checks at each viewport, 0 console errors, 0 page
errors, one handled HTTP 409 per viewport; GitHub Actions
*Release consistency* green on the branch and on PR #37, with `tests/test_topology_menu_ui.js` in
the browser step.

# Live Junos configuration restore and nested Git folders — 1.28.0

Prepared on `claude/junos-live-restore-and-git-destinations` from main `c1d22f3` (1.27.0) on
2026-09-16, after the user asked for a WebUI workflow that applies a saved Junos configuration to
a running node without a reboot or a containerlab redeploy (a complete desired-state replacement,
proven to remove stale statements), and for a more novice-friendly, flexible Git save location.

## The restore mechanism, established on the live lab first

Before writing product code, the whole-device replace was proven directly against the two Junos
lab nodes on the dev VM. The findings shaped the design:

- `show configuration | display set` is merge-only (`load set`) and cannot remove a statement a
  student added; the hierarchical form loaded with `load override terminal` does. Every Junos
  backup now also captures `show configuration` as a restore-grade artifact.
- On `archtop/cjunosevolved:26.2R1.7-EVO` the running config has **no `root-authentication`**, and
  any real commit — `load override` or `load update` — fails with *Missing mandatory statement:
  'root-authentication'*. The empty-diff commits that first looked like success proved nothing.
  The restore therefore ensures the candidate carries root-authentication, synthesising it from
  the candidate's own superuser login password when absent. `n24l/vjunos-switch:23.2R1.14` already
  has it and commits directly.
- A fresh SSH session's plain `commit` confirms a pending `commit confirmed` (verified with
  `show configuration | compare rollback 1`), so the manager can reconnect to prove management is
  alive and only then confirm; otherwise the node rolls back on its own.
- `junipernetworks.junos` 11.1.1 is a deprecation shim over `juniper.device`, and PyEZ / ncclient
  / lxml are not in the image, so NETCONF / `junos_config` are unavailable. The CLI path is the
  only option and is what shipped.

## Local checks (Ubuntu 24.04 dev VM; Python 3.12 venv from requirements.txt + httpx; Node)

| Check | Result |
|---|---|
| `test_restore_junos.py` — driver against a scripted fake channel (load override + Ctrl-D, root-auth present/synthesised/refused, load error, commit-check and commit-confirmed failure, no-op, confirm, capture) | 11 tests OK |
| `test_restore.py` — service with a fake connector and Runner: source resolution, node mapping, preflight reachability/match, guards (busy/acknowledge/idempotent), mandatory pre-backup, apply/verify, verify mismatch, redaction, restart reconciliation, and a node that stops after submit not aborting the healthy node | 17 tests OK |
| `test_git_progress.py` — new restore-artifact snapshot tests (schema 2 include + round-trip, legacy capture stays not-restore-capable, the version route reports restore capability) plus the existing suite | 29 tests OK |
| `test_git_places_ui.js` (new nested-folder path + destination preview) and `test_restore_ui.js` (badge/source/request-id, escaping) | 14 + 4 tests OK |
| Full Python suite `python -m unittest discover -s tests -t tests -p "test_*.py"` | 681 tests, 1 skip (the opt-in EOS SSH fixture), 0 failures |
| Full Node UI suites (`node --test tests/*.js` CI list incl. the two new files) | 0 failures |
| `node --check` on `restore.js`, `git-progress.js`, `git-places.js`; `git diff --check` | clean |
| `python deploy/verify-release.py` | `Source release verified: 1.28.0`; documentation names only 1.28.0 |

## Live validation on the dev VM (manager 1.28.0, VM Git helper 1.28.0, containerlab 0.79.0)

The lab `clabllm-dev` was redeployed clean (`containerlab redeploy`) to two factory Junos nodes:
`clab-clabllm-dev-PTX1` (`juniper_cjunosevolved`, 172.20.20.2) and `clab-clabllm-dev-SW1`
(`juniper_vjunosswitch`, 172.20.20.3), login admin / admin@123. The image was rebuilt
(`docker compose build backup-ui`) and recreated; `/api/state` reported 1.28.0. The Git helper was
refreshed with `setup-git.sh --refresh` (it now accepts the schema-2 snapshot). The end-to-end run
below used the manager's own API, driving the same routes the browser does; a mid-session
adversarial review (a workflow of 22 agents) surfaced seven real defects that were fixed and
re-tested before this run.

The whole flow was validated on **PTX1 (cJunosEvolved)** — the harder platform, because it
exercises the root-authentication synthesis path. SW1's vJunos-switch VM restarted itself during
this session and would not hold an SSH session, so the manager-orchestrated run was completed on
PTX1 only; the restore *mechanism* itself was proven on both platforms (see below).

| Step | Result |
|---|---|
| `New folder…` with a nested path `CCNP-SP/Labs/Week-04/BGP/Final-State` | Registered in one step (`POST /git/repositories/{id}/folders`) and listed in the tree; no click-through per level |
| Establish a final state and `Save progress` (latest) | Backup captured PTX1 and stored the restore-grade candidate (`restore.capture … clab-clabllm-dev-PTX1-…​.jcfg, 841 bytes`); committed and **pushed** to github.com/pruger-dev/CLAB-MNGR-DEV-LLM; `changed_files` included `labs/clabllm-dev/latest/PTX1.jcfg` |
| Read the saved version (`POST /git/version`) | `restore_supported true`, `restore_nodes [PTX1]`, files `PTX1.set` + `PTX1.jcfg`, manifest `schema 2`, `restore_capable_nodes 1` |
| Student breaks the running config (direct SSH): add `interfaces lo0 … 10.77.77.77/32`, change host-name to `PTX1-BROKEN-BY-STUDENT`, commit | Committed on the device |
| `Apply to running lab…` review (`POST …/restore/preflight`) | PTX1 `eligible`, `reachable`, `matches_saved false`, `pending_changes 3`; source `restore_capable_nodes 1` |
| `Replace configuration` (`POST …/restore`, confirm 3 min) | Job **succeeded**: *All 1 node(s) restored and verified against the saved state.* PTX1 → `verified`, `root_authentication synthesized`, `missing 0`, `extra 0`; `pre_backup_job_id` and `post_backup_job_id` recorded |
| Device after restore (direct SSH) | **Stale `lo0 10.77.77.77` removed**, host-name back to `HOSTNAME`, `root-authentication` present (synthesised, so the node stays loginable), mgmt address `172.20.20.2/24` intact |
| No reboot / no recreate | Container `StartedAt` identical before and after (`2026-09-16T11:45:37.183502085Z`); the restore never restarted, rebooted or redeployed the node |
| Pre-restore backup | `source restore-pre`, `succeeded`, captured the broken state with its own restore artifact — the operator can inspect or roll back to it |
| Failure path — a legacy backup with no restore artifact | Preflight `eligible_count 0`, `targets []`, `restore_capable_nodes 0`; `POST …/restore` → 400 *Select at least one saved node to restore.* The device was not touched |
| Failure path — an out-of-history commit | Preflight → 409 *The selected commit is outside this repository branch history.* |

## Apply from the folder browser, without rebinding (added after review feedback)

The first walkthrough tied *Apply to running lab* to the connected folder's history, so a
student had to re-point the lab at a folder before applying it. That is poor UX for a
repository of named states. **Apply to running lab…** now also appears on any folder in
*Where this lab lives* whose `latest/` holds a restore-grade candidate, and applies it
directly (`resolve_source` type `folder`; the helper's `allowed_repo_version` lets
`read-version` reach any snapshot folder of the checkout). Live-validated on the dev VM
against `pruger-dev/CLAB-MNGR-DEV-LLM`, which holds `labs/BGP-LAB/{Base, working, Final,
Broken}` as distinct saved BGP states: with the lab bound to **Broken**, applying **Final**
straight from its folder succeeded and verified, the running node converged to the Final
config (`peer-as 65002`, the export policy), the lab's binding was **unchanged** (no
rebinding), and the container did not restart.

## Load version labels every folder, and the lab scaffold

Two follow-ups after the same feedback. **Load version / History** used to show a bare "latest";
it now lists every saved folder in the checkout, each labelled by its path
(`labs/BGP-LAB/Broken · latest`, the connected one tagged *this lab*), and the version and Apply
actions read any of them by their full path (`host_git.allowed_repo_version` broadened
`read-version`; `git_progress.resolve_version_path` accepts a full or connected-relative path).
Live-verified on the dev VM: the history listed `labs/BGP-LAB/{Base, working, Final, Broken}` each
as its own labelled version, and loading `labs/BGP-LAB/Final/latest` by path returned the Final
config with `restore_supported`.

`deploy/scaffold-lab.py` plus `deploy/lab-template/` and `docs/NAMING.md` standardise a course:
`init <slug>` registers `<slug>/reference/{start,solution,broken-01}` and `<slug>/work` and binds
saves to `work`; `snapshot <slug> <state>` captures the running config into
`<slug>/reference/<state>` and rebinds to `work`. Live-run on the dev VM: `init demo-lab` created
the structure and bound the lab to `demo-lab/work`, and `snapshot demo-lab start` captured and
pushed the running config into `demo-lab/reference/start`; the demo folder was then removed. The
scaffold's orchestration is unit-tested (`test_scaffold_lab.py`).

## The restore mechanism proven on both Junos platforms (direct, pre-product)

The load-override + confirmed-commit sequence was proven end-to-end against **both**
`juniper_cjunosevolved` (PTX1) and `juniper_vjunosswitch` (SW1) before the product code existed:
a distinctive final state was committed, a student then added a stale `lo0`, changed the host-name
and deleted a desired `snmp contact`, and the final state was reloaded with `load override
terminal` + `commit confirmed 2` + `commit`. On both nodes the `show | compare` showed the stale
`lo0` removed, the deleted `snmp contact` re-added and the host-name reset; the check and confirmed
commit succeeded; and the container `StartedAt` was unchanged (no reboot). cJunosEvolved additionally
required the injected root-authentication (`configuration check succeeds` only with it).

## Not verified

- The **manager-orchestrated** restore on `juniper_vjunosswitch` (SW1) was not completed: SW1's
  VM restarted itself mid-session and would not hold an SSH session. The restore mechanism is
  proven on vJunos-switch directly (above); only the through-the-manager run is PTX1-only.
- A **two-node** restore in one job was exercised by unit tests, not live (only PTX1 was reachable).
- The **commit-confirmed automatic rollback** (losing management before confirm) was designed and
  unit-tested (`rollback_expected`), and the reconnect-then-confirm was proven live, but a real
  management-loss rollback was not forced on the live node.
- **IOS-XR and EOS** live restore is not implemented; those versions stay view/download only.
- Legacy (pre-1.28.0) snapshots were confirmed non-restorable live (the legacy-backup failure path
  above); an in-repo pre-1.28.0 Git version was not separately exercised beyond the schema check.

# Repository folder browser, folder moves and connect by URL — 1.27.0

Prepared on `claude/git-folder-browser` from main `609fd4b` (1.26.0) on 2026-09-14, after the
user asked for students to see where a lab's files land in the connected repository in a way
familiar from a Mac file browser, to change that folder and create folders from the manager,
and to recover from connecting the wrong repository without leaving the web UI.

## Local checks (Windows workstation; Python 3.12 venv for the app suites, Python 3.14 for the stdlib suites; Node 24)

| Check | Result |
|---|---|
| `test_host_git.py` with real Git in temporary repositories; new `HostGitPlacesTests`: clone-URL parsing, browse, `register()`, planning and overlap rules including retire, move with push, move refusals, connect (clone, adopt, wrong repository, occupied folder, missing identity), tools before the clone exists | 30 new tests OK; whole file 54 tests OK |
| `test_git_progress.py`; new `GitPlacesTests`: tree with lab tags, folder registration and validation, destination change with a move job and no recapture, pending-save guard and a recoverable move failure, connect by URL with acknowledgement and the cross-lab conflict | 26 tests OK |
| `test_git_transport.py`, `test_git_registrations.py`, `test_check_git.py`, `test_release_consistency.py` | 6 + 9 + 13 + 13 tests OK |
| `node --test tests/test_git_places_ui.js` (new: tree model, path chips, folder rules, folder names, sizes, escaping of the browser markup, connected card, move-job labels, choosing a folder in a repository the lab is not connected to) and `tests/test_git_progress_ui.js` | 9 + 14 tests OK |
| `node --test` of every UI suite (11 files) | 91 tests, 0 failures |
| `node --check` on `git-progress.js` and `git-places.js`; `git diff --check` | clean |
| `python deploy/verify-release.py` | `Source release verified: 1.27.0`; documentation names only 1.27.0 |

## Live validation on the dev VM (Ubuntu 24.04, manager 1.27.0, VM Git helper 1.27.0)

The working tree was staged into `~/projects/clab-manager` (the VM's `.env` kept), the helper
refreshed with `sudo bash deploy/setup-git.sh --refresh`, and the manager rebuilt and recreated
with `docker compose … build` and `up -d --force-recreate`. `/api/state` reported 1.27.0 and
`/api/git/repositories` listed the registered checkout through the refreshed helper. The lab
`clabllm-dev` (two Junos nodes) was connected to `~/labs/CLAB-MNGR-DEV-LLM`
(github.com/pruger-dev/CLAB-MNGR-DEV-LLM, branch `main`) at the folder `GIT-DEV-TEST`, with one
earlier save waiting for review. That save was pushed through the manager's own retry first:
pending saves block folder changes and reconnects by design, and an unpushed branch makes a
new registration refuse until it is synchronized, both of which the first run reported.

| Step | Result |
|---|---|
| `GET /api/git/repositories/{id}/tree` | The committed files of the checkout at HEAD, the lab's folder tagged with the lab, the last-save time, no truncation |
| `POST /api/labs/{id}/git/destination` with `labs/clabllm-dev` and `move_files` | Folder registered, lab reconnected with its two devices, previous registration retired; the *Folder move* job committed `Move clabllm-dev progress to labs/clabllm-dev/` (6 changed paths), pushed it, remote `main` equals the local head, old folder gone, `git status` clean |
| Status, tree, history and review after the move | Ready; the `latest` manifest names the lab; history lists the move commit; the review shows both configurations as added under the new folder |
| Same folder again; a folder nested inside a lab folder | Refused: "already saves to that folder" and "cannot overlap" |
| `POST /api/git/repositories/{id}/folders` with `courses/week1` | Registered; the tree lists it as a lab folder without a lab |
| Connect by URL to `ArchRuger/CLAB-BACKUP-WORKER-v2` (no push access) and to a repository that does not exist | Refused before cloning with "The GitHub account signed in on the VM cannot push to …"; no new checkout under `~/labs`. The first attempt reported a generic error because GitHub CLI was run inside the not-yet-existing checkout folder; fixed and re-run |
| Connect by URL with the page link `…/CLAB-MNGR-DEV-LLM/tree/main` into `labs/clabllm-dev` | Existing checkout adopted, registration reused, the lab stays connected with its devices |
| Full Python suite on the VM, `python -m unittest discover -s tests -t tests` | 645 tests, 1 platform skip, 0 failures |
| Browser (desktop app browser, 1440 × 960) → lab → More → Git repository | Connected card with the push URL, branch, VM account and the path `CLAB-MNGR-DEV-LLM › labs/clabllm-dev › latest/`; "Where this lab lives" with the folder path, the outline (`ARISTA-LAB-TEST`, `courses`, `labs › clabllm-dev` tagged *This lab*), the listing `latest · Most recent save · 2.4 KB`, the footer with the last save and commit, *Save this lab here* disabled with "This lab already saves here."; both registrations in the settings select; the move listed as *Folder move → labs/clabllm-dev* under Progress saves |

The VM ends with the lab saving to `labs/clabllm-dev` and the extra registered folder
`courses/week1`, both left in place as the working example of the feature.

## Not verified

- A fresh clone through *Connect by URL* was not exercised against GitHub: the dev account
  has one repository, which was already checked out. The clone path is covered by
  `test_host_git.py` against a local bare repository; the refusal path was exercised live and
  stops before cloning.
- Automatic commit identity from the GitHub account (`gh api user`) was not exercised live:
  the dev checkout already carries a local identity. Only the missing-identity refusal is unit
  tested.
- Moving `baseline/` and `checkpoints/` folders was covered by the real-Git unit test, not
  live; the dev lab only had `latest/`.
- No device capture was started by this validation; the saved files came from the user's
  earlier save. The move, new folder and connect dialogs were driven through their API routes
  and unit-tested render functions; they were not clicked through in a browser.
- The terminal wizard (`deploy/setup-git.sh`) is unchanged and was only used for `--refresh`.

# Map positions, destroy cleanup, Grafana on demand — 1.26.0

Prepared on `claude/map-positions-destroy-cleanup-grafana-on-demand` from main `478568a`
(1.25.0) on 2026-09-14, after the user reported the topology map showing nodes in a flat
line instead of the positions in the annotations file, and asked for destroy to use
`--cleanup`, for Grafana to run only on request, and for the telemetry history to be
capped at fifteen minutes everywhere.

## Root cause of the flat map, found on the dev VM

The `ceos-pair` workspace on the dev VM held ceos1 at (0,0) and ceos2 at (160,0), the
default grid, while `/etc/containerlab/ceos-pair/ceos-pair.clab.yaml.annotations.json`
placed them at (380,360) and (520,340) and discovery reported the file as found. The
workspace had been created by *Deploy lab* (source `ceos-pair.clab.yaml`, `synced_at`
null, status *Updates available*): that path registered the YAML alone, and only an
explicit *Sync from VM* would ever have applied the file.

## Local checks (Windows workstation, Python 3.12, Node)

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -t tests -p test_topology.py` (new `placed` / `unplaced` test) | 15 tests OK |
| `test_lab_operations.py` (parse-yaml with annotations, helper `grafana` mode argv) | 24 tests OK, 2 platform skips |
| `test_vm_files.py` (discovery places a grid-only drawing from the bundle's annotations, never a hand-placed one) | 26 tests OK, 1 skip |
| `test_diagram_editor.py` (a saved layout is `placed`) | 5 tests OK |
| `test_grafana_control.py` (new: activity parsing, idle stop, grace, retry back-off, API routes) | 8 tests OK |
| `test_telemetry_setup.py` (compose flags, container name, restart policy, setup order, quick ranges, idle key) | 9 tests OK, 1 skip |
| `test_check_install.py` (stopped Grafana passes read-only; a broken scrape still fails) | 37 tests OK, 1 skip |
| `test_telemetry_store.py`, `test_telemetry_map.py`, `test_telemetry_manager.py`, `test_install_manager.py`, `test_app.py` | OK |
| `node --test` operations, readiness and the new grafana page suites | 12 + 9 + 4 tests, 0 failures |
| `test_discovery.py` | Once green, twice one `PermissionError` on `os.replace(state.enc.tmp)`: the known Windows open-handle rename flake, a different test each time; rerun on the VM below |
| `node --test` of the whole CI list (9 suites) | 66 tests, 0 failures |
| `python deploy/verify-release.py` | `Source release verified: 1.26.0` and `Documentation names only release 1.26.0` |
| `bash -n` on every deploy script | clean |

## Live validation on the dev VM (Ubuntu 24.04, containerlab 0.79.0, Compose v5.5.1)

The working tree was staged into `~/projects/clab-manager` (the VM's `.env` kept) and upgraded
in place with `sudo bash deploy/start-manager.sh --enable-operations`, which reinstalled the
helpers, refreshed both stacks and rebuilt the manager. The session stopped at the user's
request before a from-commit re-stage: the VM runs that staged tree plus the identical
`compose.yml` line below; the committed tree differs from it only in the singular-minute
wording of the Grafana status texts. Not exercised live: the *Stop Grafana now* button in
Telemetry settings (unit-tested in `test_operations_ui.js`) and the CI smoke's Grafana
stop/start step (runs in CI on the push).

| Step | Result |
|---|---|
| Full Python suite on the VM (Linux venv from `requirements.txt` + httpx + pyyaml) | 611 tests, 610 pass, 1 skip; the one failure is `test_app.test_callback_and_archive_pipeline_offline`, whose `ansible-playbook` binary is not on that ad-hoc venv's PATH (unrelated to this change; the suites that flaked on Windows pass) |
| Launcher phase 5 (`setup-telemetry.sh`) | `.env` gained `TELEMETRY_GRAFANA_IDLE_MINUTES=15`; Prometheus and Grafana reported ready, scrape target `up`, Flow panel loaded, then `Grafana dashboards installed for TCP 3000 and stopped again: …`; `docker ps -a` shows `clab-manager-grafana Exited (0)` and Prometheus up |
| Prometheus `/api/v1/status/flags` | `storage.tsdb.retention.time=15m`, `min-block-duration=15m`, `max-block-duration=15m`, `retention.size=48MiB`: the hidden block flags are accepted by v3.14.0 |
| Installed helper | `/usr/local/lib/clab-manager/host_operations.py` is 1.26.0 with the `grafana` mode |
| `GET /api/telemetry/grafana` after the upgrade | `enabled true, running false, idle_minutes 15`, message *stopped; it starts when you open it from a lab* |
| The flat `ceos-pair` map (grid positions, never synced) | On the first discovery pass after the upgrade the drawing became ceos1 (380,360), ceos2 (520,340), `placed true`; event `topology.positions` logged at 13:03:03 UTC and the lab-map dashboard file rewritten five seconds later; `vm_source` still *Updates available* (logins and nodes wait for a sync, as designed); the manager's own map shows the two nodes at their drawn places |
| `check-install.sh` from `/tmp` | PASS 60 / FAIL 0 / WARN 2 (the exited lab nodes, the folder budget); **Grafana telemetry dashboards** PASS with *provisioned and stopped until someone opens it … stops it after 15 minutes … 1 lab map(s) are provisioned*; Network telemetry PASS |
| Lab header button | `href` = `/static/grafana.html#path=%2Fd%2Fclab-map-…%3Fvar-lab%3Dceos-pair%26refresh%3D10s&title=ceos-pair`, `target=_blank`, title ends with *Grafana starts on the VM when it is not running* (the desktop pane blocks new tabs, so the page was opened in place) |
| `/static/grafana.html` in the browser | Showed *Starting Grafana on the VM; this takes a few seconds…* and about twelve seconds later the tab was on `http://VM:3000/d/clab-map-…?var-lab=ceos-pair&refresh=10s` (*Lab map · ceos-pair*, Last 15 minutes, refresh 10s); the manager logged `grafana.start`, `started_at` set, `docker ps` shows the container up, `/api/health` ok, Flow panel loaded, `/metrics` counters for `/api/ds/query` and the dashboard routes growing while the tab was open |
| Automatic stop (idle set to 1 minute in `.env` for the test, manager reloaded) | With the dashboard tab open the monitor kept `last_activity` moving; after the tab was navigated away Grafana was stopped at 13:22:05 UTC, event `grafana.stop … after 1 minutes without an open dashboard`, `running false`, container `Exited (0)`; idle restored to 15 |
| Finding fixed during this run | `recreate-manager.sh` did not pick the idle value up at first: the manager's `compose.yml` passes named variables only and the new key was not listed, so the container kept the default. Added `TELEMETRY_GRAFANA_IDLE_MINUTES: ${TELEMETRY_GRAFANA_IDLE_MINUTES:-15}` to `clab-backup-ui/compose.yml`, pinned by `test_telemetry_setup`, patched identically on the VM; a recreate then changed the container (the script's ps line showed the new container) and the status read `idle_minutes 1` |
| Time picker in Grafana 13.0.2 | Quick ranges list *Last 5 minutes* and *Last 15 minutes* only (`quick_ranges` is honoured); the lab map's SVG is in the page with its eight cells and no panel error |
| Lab actions menu | *Destroy deployment* plus *Redeploy + cleanup*; no separate *Destroy + cleanup*; help text names `containerlab destroy --cleanup` |
| Destroy from the menu | Review showed *Cleanup removes generated lab artifacts. Expected lab directory: /etc/containerlab/ceos-pair/clab-ceos-pair* and the command `"/usr/bin/containerlab" "destroy" "-t" "…/ceos-pair.clab.yaml" "--name" "ceos-pair" "--cleanup"`; `Destroy deployment succeeded · Exit 0`; afterwards the folder holds only the YAML and the annotations file, `clab-ceos-pair` is gone and no lab container remains |
| Deploy-first path (workspace removed, *Deploy a new lab* → `/etc/containerlab` → `ceos-pair` → `ceos-pair.clab.yaml`) | *Validate / preview topology* drew ceos1 lower left and ceos2 upper right with the note *Wiring from the YAML, node positions from the annotations file beside it*; *Deploy lab* registered a new workspace whose drawing was `placed true`, ceos1 (380,360), ceos2 (520,340) before the deploy even ran; `deploy succeeded · Exit 0`, both cEOS containers up, `clab-ceos-pair` recreated, the new lab's map dashboard published; opening Grafana for the new lab started it again in about ten seconds |

# Documentation and installation audit — 1.25.0

Prepared on `claude/docs-install-audit` from main `a4cb89f` (1.24.0) on 2026-09-14, after the
user asked for a top-to-bottom documentation and install audit: the Wireshark and Grafana stacks
as part of the installation, version numbers tracked instead of left in the guides, every command
runnable from any directory, the link-hover bug, and telemetry moved out of the manager UI into
Grafana with the topology map back to its earlier state.

## Environment

- Dev VM `clab-dev-llm` (Ubuntu 24.04.4, Docker 29.8, Compose v5.5.1, containerlab 0.79.0, no
  KVM), running 1.24.0 from `~/projects/v1.24.0` with the capture and telemetry stacks and the
  `ceos-pair` lab (two cEOS 4.35.0F nodes) streaming telemetry when the session started.
- Windows workstation for the unit and browser tests (Python 3.12, Node); the desktop app's
  browser pane for the UI checks.

## The guided installer, end to end, on the documented route

| Step | Result |
|---|---|
| Working tree staged at `~/projects/clab-manager` (the folder every guide now uses), `.env` copied from the 1.24.0 folder | `verify-release.py --runtime` reports 1.25.0; `bash -n` passes on every deploy script |
| `bash ~/projects/clab-manager/deploy/install.sh` started from `/tmp` through a pty driver that answers the prompts like a person (menu 1, bind/port retained, operations 1, VS Code 2, media repair n, plan y, next step 2, menu 6) | First attempt stopped in phase 3 with the recovery menu: `start-manager.sh` ran the release check without `--runtime`, so the not-yet-written validation section blocked a VM install. Fixed (`--runtime` in the launcher, pinned by `test_release_consistency`), re-staged, re-run: phases 1/6 to 6/6 all `Completed`, no recovery menu, closing line `Manager 1.25.0: running; HTTP and version checks passed.` |
| Phase 4, browser Wireshark | pinned Wireshark image pulled, `clab-capture-service:1.25.0` built, Edgeshark and the session service recreated, `Manager recreated with the current clab-backup-ui/.env` |
| Phase 5, Grafana | Flow panel reported `present` (no download), `Prometheus on 127.0.0.1:9090 and Grafana on TCP 3000 are ready`, scrape target `unknown (first scrape pending)` at that moment, `Flow panel … loaded`, manager recreated again |
| Phase 1, `sudo -v` | Prompted for a password on this VM even with `clabllm ALL=(ALL) NOPASSWD: ALL`, because the account is also in the `sudo` group and sudo's `verifypw` default needs every entry to be NOPASSWD. For the unattended run `Defaults:clabllm verifypw = any` was added on the VM; a person at the console types the sudo password there, as the guides say |

## After the install

- `docker ps`: `clab-backup:1.25.0`, `clab-capture-service:1.25.0`, gostwire, packetflix,
  prometheus and grafana all up; the two cEOS nodes untouched.
- `/api/state`: version 1.25.0; `ceos-pair` reports `telemetry.status = streaming` and
  `telemetry.grafana = {enabled: true, port: 3000, map_uid: clab-map-35159c1aca7c447da2998e00}`;
  `/api/telemetry/health` reports one provisioned map and plugin 1.20.1; `/api/capture/status`
  enabled; the Prometheus target is `up`; Grafana answers 200 for the map dashboard uid;
  `/api/labs/x/telemetry/series` and `/static/telemetry.js` answer 404.
- `bash ~/projects/clab-manager/deploy/check-install.sh` run from `/tmp`: **PASS 61 / FAIL 0 /
  WARN 1** (the folder-coverage budget), including `[PASS] Browser Wireshark capture`,
  `[PASS] Network telemetry`, `[PASS] Grafana telemetry dashboards`, `[PASS] Engineer access` and
  the Git registry checks.

## In the browser (desktop app browser pane, fresh tab)

- Header tabs are Topology, Nodes, Backup history and More; no Telemetry tab and no
  `#telemetry-view`; every asset carries `?v=1.25.0`; footer v1.25.0; no console errors.
- **Lab map in Grafana ↗** links to
  `http://192.168.233.131:3000/d/clab-map-35159c1aca7c447da2998e00?var-lab=ceos-pair&refresh=10s`;
  opened in a second tab, `Lab map · ceos-pair` renders the two routers with green node and port
  dots and `↑ 0.0 b/s` labels (no traffic at the time).
- Map: legend reads "Links show imported wiring, not live status"; zero `data-link-index`
  attributes and zero `.tele-dot` elements; the hit path's computed style is transparent,
  16 px wide and `stroke-dasharray: none`; `elementFromPoint` along the link centre and at
  6, 12, 18 and 23 px above and below returns `path.capture-hit`, the background at 26 px (the
  SVG is scaled 3.01×, so the 16-unit band is ±24 px on screen); hovering paints the wire coral.
- Right-click on ceos1: Capture packets, SSH, Back up configuration, Node details; no *View
  telemetry*.
- Lab actions → Telemetry settings…: "Automatic telemetry is on: 2 supported nodes · 2
  streaming. Read the data in Grafana.", the checkbox on, the gNMI login select, *Remove
  manager-added lines…* disabled while automatic telemetry is on, no retry button because no
  node has failed. Saving, removal and retry are exercised by the browser test only.

## Tests

- Node: **76** tests pass (`tests/*.js`), including the new Telemetry settings dialog test and
  the Grafana link test; `test_telemetry_ui.js` is deleted with the feature.
- Python: **599** tests, 12 skipped. The full run on Windows reports the known `state.enc`
  rename flake (`WinError 5`) in a varying handful of tests (different ones in two runs); every
  affected file passes when run alone (`test_git_progress`, `test_capture`, `test_diagram_editor`,
  `test_telemetry_manager`, `test_nodes`, `test_node_readiness`, `test_downloads`,
  `test_vm_password`, `test_capture_proxy` re-run individually). New or changed:
  `test_release_consistency` (documentation check, `set-release.py`, launcher order and
  `--runtime`), `test_install_manager` (stack phases and menu 4), `test_check_install` (WARN and
  absolute advice), `test_capture_sessions` (`--remove`), `test_telemetry_manager` (chart routes
  gone, `grafana` in the view), `test_telemetry_metrics` (`grafana` in `/api/state`).
- `python3 deploy/verify-release.py`: the runtime set and the documentation both name 1.25.0;
  `set-release.py 1.25.0` was what moved the 19 runtime and documentation markers.

## Not covered

- `setup-capture.sh --remove`, `setup-telemetry.sh --remove` and a launcher run without
  `--manager-only` (the refresh-both-stacks path) were not run on the VM: the user tests on this
  VM and its stacks were left up. Unit tests cover the `.env` handling, the script contents and
  the launcher's order of steps.
- No fresh Ubuntu VM run: this VM already had every prerequisite, so phase 2 only reported them
  present. The Git wizard was not re-run (next step 2).
- The hover was verified geometrically and visually with telemetry streaming; the dotted
  "no telemetry" link that flickered cannot occur any more because no overlay class is added.
- XRv9k and cJunosEvolved are unchanged and were not touched.

# Grafana lab map — 1.24.0

Prepared on `claude/grafana-lab-map` from main `70f30c9` (1.23.1) on 2026-09-13, after the
user asked for a Grafana map "like srl-labs/srl-telemetry-lab". That lab uses the Flow panel
plugin with an SVG and a YAML drawn per lab; this release generates both from the manager's
drawing. Validated live on the dev VM (`clab-dev-llm`, cEOS 4.35.0F pair, Grafana OSS 13.0.2,
Prometheus v3.14.0, Flow panel 1.20.1).

## Setup and provisioning (documented scripts, re-staged from the final commit)

| Step | Result |
|---|---|
| `setup-telemetry.sh` (first run) | settings saved with `TELEMETRY_MAPS_DIR`, `Flow panel andrewbmchugh-flow-panel 1.20.1 installed in /srv/containerlab-node-manager/telemetry/plugins` (owner 472), map folder created for uid 10001, stack recreated, readiness `Prometheus … and Grafana … are ready`, `Flow panel … loaded` |
| `setup-telemetry.sh` (rerun) | `Flow panel … present` (no download), scrape target `up`, exit 0 |
| Manager recreated | `/api/telemetry/health` → `maps: {enabled, folder /data/telemetry/dashboards, dashboards 1, error ''}`; the file `clab-map-35159c1aca7c447da2998e00.json` (0644, uid 10001) appeared within 5 s of start |
| Grafana | `/api/search` lists `Lab map · ceos-pair` in folder *Lab maps* next to the three fixed dashboards; `/api/frontend/settings` lists the Flow panel; the bundled-app background installer no longer logs errors (`GF_PLUGINS_PREINSTALL_DISABLED`), the empty `provisioning/plugins` and `provisioning/alerting` files silence the two remaining start-up errors, Grafana Live is off |
| `check-install.sh` | **PASS 61 / FAIL 0 / WARN 1** (folder budget); `[PASS] Grafana telemetry dashboards — … the Flow panel is loaded and 1 lab map(s) are provisioned.` |
| Telemetry tab | button reads **Open lab map in Grafana ↗** and opens `/d/clab-map-35159c1aca7c447da2998e00` |

## The map in the browser (desktop app browser pane, fresh tab)

| Check | Result |
|---|---|
| First render | the panel needs about a minute to load the plugin bundle in this browser; then the two routers, `eth1` labels, node labels, port dots and rate labels render on the manager's cream canvas; no page error, no console error apart from Grafana Live's WebSocket (now disabled) |
| Traffic (Linux `ping -i 0.05 -s 1400` between the cEOS nodes, ≈230 kb/s each way) | both link halves green with moving dashes, rate labels `↑ 232.3 kb/s` / `↑ 232.8 kb/s`, port and node dots green |
| `shutdown` on ceos2 Ethernet1 | read from the DOM 40 s later: both port dots `rgba(255,49,84)` (red), both halves `rgba(190,200,210)` (grey), rate `↑ 0.0 b/s`, node dots green; `no shutdown` returned everything to green within the next refreshes |
| Defects found and fixed live | (1) link halves stayed grey under traffic: the SVG stylesheet coloured `.link`, and a CSS rule beats the `stroke` attribute the plugin sets — colours the plugin drives are attributes only now; (2) on a short link the two rate labels met in the middle — they now sit beside the wire near their own node; (3) port dots were drawn under the icons; (4) a discrete value on a threshold level is ambiguous — every level now sits between the values it separates |
| Learned about the plugin | it sets only `animation-duration`/`animation-direction` (the dash keyframes live in the SVG), replaces the text of a leaf holding one text node, `getColorFromNumber` compares `value < level`, and tool calls in one message run sequentially, so a flap test needs shutdown, inspection and restore as separate calls |

## Tests

- New `test_telemetry_map.py` (8: SVG structure, cells and NOS names, dashboard, signature,
  publisher, manager routes and stack-off behaviour); `test_telemetry_setup.py` 9 (plugin
  install with a fake runner, folders, compose binds and the second provider);
  `test_check_install.py` 37 (plugin missing and folder error cases); `test_telemetry_metrics.py`
  (state code); `test_telemetry_ui.js` (map link and button text); every telemetry module green
  on Windows apart from the known `state.enc` rename flake; 69 JS tests green; release
  consistency 1.24.0.
- CI smoke (`deploy/telemetry/smoke.py`) now installs the plugin with the real Grafana image,
  provisions a generated map for a fixture lab and checks that every series its cells bind to is
  answered; its result is on the pull request.

## Not covered

- XRv9k and cJunosEvolved maps: interface-name mapping is unit-tested, no such node runs here.
- Labs with more than two nodes and with annotations (groups, notes) render in unit tests only.

# Telemetry live fixes — 1.23.1

Prepared on `claude/v1.23.0-validation` from main `c8a2e26` (1.23.0) on 2026-09-13.
Scope: the first live run of the 1.23.0 telemetry release and the fixes it needed.
The user reported "the Grafana dashboard says there was an error"; the task was to
deploy the latest main on the dev VM and validate the whole setup and deployment.

## Environment

- Dev VM `clab-dev-llm` (Ubuntu 24.04.4, Docker 29.8, Compose v5.5.1, containerlab
  0.79.0, no KVM), manager 1.23.0 staged from main `c8a2e26` with
  `deploy/start-manager.sh --enable-operations` (image rebuilt, pygnmi installed),
  capture stack on `clab-capture-service:1.22.0` images, `sudo bash
  deploy/setup-telemetry.sh` (Prometheus v3.14.0 and Grafana OSS 13.0.2 pulled by
  digest), manager recreated with the new `.env`.
- Lab `ceos-pair` (two `arista_ceos` nodes, `n24l/ceos:4.35.0F`, `eth1`–`eth1`),
  saved by 1.22.0 (no telemetry setting yet), deployed through the manager's
  operations API; Ethernet1 addressed 10.0.0.1/24 and 10.0.0.2/24 by hand for link
  traffic. NOS login: containerlab default `admin`/`admin`.
- Browser checks in the desktop app's browser pane at 1280x900, console watched for
  errors; API checks with curl and stdlib Python on the VM.

## What 1.23.0 did on the VM before any fix

| Check | Result |
|---|---|
| `deploy/verify-release.py` on the staged tree | `Source release verified: 1.23.0` |
| `start-manager.sh` rebuild + helpers | exit 0; `/api/telemetry/health` enabled, pygnmi present, states `disabled: 2` (pre-1.23.0 lab) |
| `setup-telemetry.sh` | exit 0 and "Grafana dashboards installed", although `docker ps` showed `clab-manager-telemetry-prometheus-1 Restarting (1)`; its log: `Error parsing command line arguments: unexpected false` / `prometheus: error: unexpected false` |
| Grafana `/api/health` | `{"database":"ok","version":"13.0.2"}`; data source `clab-prometheus` and the three dashboards provisioned in folder *Containerlab Node Manager*; anonymous read of a dashboard 200 with `canEdit:false` |
| Grafana in the browser | every panel of *Lab overview* showed a red triangle, **"An error occurred within the plugin"** and *No data* (the user's report reproduced) |
| `check-install.sh` | PASS 60 / FAIL 1 / WARN 1: `[FAIL] Grafana telemetry dashboards — Grafana answers, but Prometheus on 127.0.0.1:9090 is not scraping the manager`; its *Next* step (rerun the setup) would not have fixed a rejected flag |
| Telemetry tab (pre-1.23.0 lab) | banner *Automatic telemetry is not enabled for this lab yet* with the **Enable** button, *Open Grafana ↗* offered, nodes *Off*; no console errors |
| **Enable automatic telemetry** on the live cEOS pair | both nodes went Waiting → Configuring → Connecting → Streaming within seconds; `applied=0` (containerlab's default `management api gnmi` / `transport grpc default` found, nothing written, no `telemetry.configure` event); endpoint `172.20.20.x:6030` plain text, JSON_IETF |
| Store after two minutes of streaming | `samples=116 dropped=60` and `samples=124 dropped=52`; Ethernet1 `rx_bps=None`, admin/oper empty on every interface; map link *unknown* |
| Raw pygnmi probe from the manager container | one 10 s cycle of `Ethernet1 counters` arrived as four notifications with timestamp ages 718 s (idle counters), 2 s (`in-octets`, `in-pkts`), 247 s (`in-unicast-pkts`) and 0.1 s (`last-update`): cEOS stamps each notification with the last change time of its leaves; a plain on-change subscription for `oper-status`/`admin-status` returned the sync marker and nothing else in 14 s, on-change with a 5 s heartbeat and sample mode both delivered the value every interval |
| After two quiet minutes | both nodes' BGP group `failed` ("No notifications for two minutes; resubscribing.") on a lab without BGP; the pill was red in the Telemetry tab |
| `docker restart clab-ceos-pair-ceos2` | the node reported *failed: The gNMI port did not answer* and the retry delay grew 15, 30, 60, 120, 240 s (`attempts=5` after eight minutes) |

## Fixes and their live verification (hot-loaded into the running container, then re-staged)

| Fix | Verification |
|---|---|
| `compose.telemetry.yml` without `--web.enable-remote-write-receiver=false` | Prometheus ready 2 s after `up -d --force-recreate`; target `http://127.0.0.1:8081/api/telemetry/metrics` `up`; Grafana data-source health `Successfully queried the Prometheus API`; *Lab overview* rendered with no error (find "error" on the page: none), Lab variable resolved to `ceos-pair`, *Nodes with telemetry* 2 |
| `setup-telemetry.sh` waits (`setup_telemetry.py --wait`) | unit-tested against stub servers (ready path, Prometheus down path, Grafana down path); exercised on the final re-stage (see below) |
| `deploy/telemetry/smoke.py` in CI | stdlib script; runs in the release-check workflow on push (result recorded in the PR checks) |
| Store: per-leaf ordering, receive-time rates and points, `POINT_MERGE`, per-field newest rate | after the hot-load: `dropped=0` on both nodes, Management0 rates present, Ethernet1 `rx_bps` follows traffic; with 10 pps × 1400 B ping between the nodes both ends showed ≈111 kb/s RX (`111244` / `111242` b/s), chart in the Telemetry tab drew the ramp; `tx_bps` 0 because the cEOS container reports 0 `out-octets` on data ports (`show interfaces Ethernet1 counters`: OutOctets 0 while InOctets grew by exactly the ping bytes) |
| EOS on-change state with heartbeat | admin/oper `UP/UP` on every interface within 10 s; map link *up* from both ends, green wire, green node dots, live legend |
| Flap | `shutdown` on ceos2 Ethernet1: link *down*, both ends `DOWN`, within 3 s; `no shutdown`: *up* within 3 s; rates resumed; Grafana *Interfaces* operational-state timeline showed the red gap |
| Idle groups | after the hot-load the BGP group reads `idle` ("nothing to report on this path"), interfaces `streaming`; in-process gNMI server test drives the same transition and the return to streaming when a neighbour appears |
| Retry cap for a port that does not answer | after `docker restart` the node retried every 30 s (`connecting` every fourth 10 s poll) instead of backing off to minutes; note that a bare `docker restart` also removes containerlab's veth links (Ethernet1 disappeared on the restarted cEOS and its gNMI server stayed "not yet running"), so the lab was recovered with a manager redeploy — see below |
| check-install hints | unit tests cover the "Prometheus does not answer" and "target down with classified error" cases; the FAIL text no longer echoes scrape errors |

## Final run on the re-staged 1.23.1 tree (commit `f8f4f9a`, 21:01–21:08 UTC)

`git archive` of the commit to `~/projects/v1.23.1`, `.env` carried over, then the
documented scripts in order:

| Step | Result |
|---|---|
| `deploy/verify-release.py` | `Source release verified: 1.23.1` |
| `start-manager.sh --enable-operations` | exit 0 (image rebuilt, helpers verified, engineer access refreshed) |
| `setup-capture.sh` | exit 0 (`clab-capture-service:1.23.1`, stack recreated) |
| `setup-telemetry.sh` | settings kept (existing admin password retained), stack recreated, then the new gate: `Prometheus on 127.0.0.1:9090 and Grafana on TCP 3000 are ready.`; exit 0 |
| manager recreated with the `.env` | `/api/state` version 1.23.1; `/api/telemetry/health` enabled, `grafana {enabled: true, port: 3000, prometheus_port: 9090}` |
| `check-install.sh` | **PASS 61 / FAIL 0 / WARN 1** (folder coverage budget) / INFO 5, with `[PASS] Network telemetry` and `[PASS] Grafana telemetry dashboards` |
| Lab redeployed through the manager (`containerlab redeploy`, 45 s) | `telemetry.clear: lab operation redeploy submitted`; after boot both nodes streaming with a fresh generation (`first_sample 21:06:02`, `samples=94 dropped=0`), Ethernet1 `UP/UP`, link *up* from both ends, `applied=0` |
| `PUT /telemetry/settings {auto:false}` | summary `disabled`, both nodes *Automatic telemetry is off for this lab*, `telemetry.clear: automatic telemetry disabled`, buffers empty |
| `POST /telemetry/remove-config` | `started: []`, both nodes skipped (no manager-owned lines on cEOS), message states that only recorded lines are removed |
| `PUT /telemetry/settings {auto:true}` | streaming again after 5 s with a new generation (`first_sample 21:06:52`), `dropped=0` |
| `POST /jobs {operation: backup}` while streaming | job succeeded on both nodes in 5 s; telemetry kept streaming |
| Capture, Grafana, Prometheus | `/api/capture/health ready`, Grafana `/api/health` ok (13.0.2), Prometheus target `up` with no error |
| Browser (fresh tab) | *Lab overview*: Nodes streaming 2, Nodes with telemetry 2, Links up 1, node and link tables filled; no page error, no console error |

## Tests

- Windows: `test_telemetry_store` 8, `test_telemetry_collector` 7, `test_telemetry_gnmi` 6
  (new idle-group test against the in-process server), `test_telemetry_adapters` 12,
  `test_telemetry_setup` 8 (new readiness-wait tests; one symlink test skips on Windows),
  `test_telemetry_metrics` 4, `test_check_install` 37, release consistency 7: all green.
  `test_telemetry_manager` 13 passes apart from the known Windows `state.enc` rename
  flake. Full suite: 581 tests, the only failures are that flake and the `test_git_progress`
  timing flakes that vary run to run on Windows; Linux CI is authoritative.
- Browser: 85 JS tests green (`node --test tests/*.js`).
- CI adds `deploy/telemetry/smoke.py` (real Prometheus and Grafana against a fixture
  manager); its result is on the pull request.

## Not covered

- XRv9k and cJunosEvolved adapters: no KVM on the dev VM; still fixture-only.
- The Wireshark browser session was not opened again in this session (targets and the
  service health were checked); the capture stack is the 1.21.1 design, unchanged.

# Automatic network telemetry — 1.23.0

Prepared on `claude/keen-dirac-qk9zzi` from main `36dfdf6` (1.22.0). Scope: the
telemetry feature described in docs/TELEMETRY.md (automatic gNMI provisioning over
SSH, an in-process pygnmi dial-in collector, a bounded in-memory session store, the
Telemetry tab, charts and the live link overlay on the map). No live lab VM or NOS
image was available in this session; everything below is local evidence.

**Round two (same branch): XR gRPC in plain text (`no-tls` ensured, recorded as
manager-owned) at the operator's request, and the optional Grafana stack.** Added
`app/telemetry_metrics.py` (Prometheus exposition at `/api/telemetry/metrics`),
`deploy/compose.telemetry.yml` (Prometheus v3.14.0 and Grafana OSS 13.0.2 pinned by
digest, host network, tmpfs volumes, memory and PID limits), `deploy/setup-telemetry.sh`
with `setup_telemetry.py`, the provisioned data source and three dashboards, the
*Grafana telemetry dashboards* health check and the **Open Grafana ↗** links. Evidence:
`test_telemetry_metrics.py` (4), `test_telemetry_setup.py` (5: env preservation and
refusals, Compose pinning/bounds, provisioning, dashboard JSON referencing only
exported metrics and the provisioned data source), one more `test_check_install.py`
case and one more browser test; `docker compose -f deploy/compose.telemetry.yml config`
accepts the file; the browser smoke with the stack announced shows both links with
the expected `var-lab`, `var-node` and `var-interface` parameters and a 73-line
metrics document. Grafana and Prometheus were **not started** in the development
session (no Docker daemon); their first run is part of the live acceptance.

**Local checks (Linux container, Python 3.11.15, Node 22.22.2).**

- `python3 deploy/verify-release.py`: `Source release verified: 1.23.0`;
  `test_release_consistency.py` passes on the bumped tree.
- Full Python suite, `.venv/bin/python -m unittest discover -s tests -t tests`:
  577 tests, OK, 1 skipped (the opt-in EOS SSH fixture, as before). The 74 new
  tests are `test_telemetry_names.py` (5), `test_telemetry_store.py` (7),
  `test_telemetry_adapters.py` (12), `test_telemetry_provision.py` (12: scripted
  EOS, IOS XR and Junos Evolved shells including enable password, privilege 15,
  rejected lines and aborts, output and prompt time limits, repeat runs that write
  nothing, removal of recorded lines only), `test_telemetry_collector.py` (7:
  normalisation of the six vendor-shaped fixtures in `tests/fixtures/telemetry/`,
  timestamp policy, failure classification without echoing details),
  `test_telemetry_manager.py` (13: readiness-triggered provisioning on the running
  app, repeat safety and backoff, credential failures and secret redaction in
  state, logs and telemetry responses, unsupported and partially supported nodes,
  stale detection and recovery, runtime change, lab operation, removal and reset
  clearing the session, address reuse across generations, settings gating, series
  API validation and bounds, explicit removal, link statuses from both ends,
  environment disable), `test_telemetry_gnmi.py` (5: the real pygnmi client against
  an in-process gRPC gNMI server that answers like EOS, XR and Junos, including
  origins, encodings, on-change fallback, login refusal and stream loss, TLS-first
  targets), `test_telemetry_metrics.py` (4), `test_telemetry_setup.py` (5) and two
  telemetry cases in `test_check_install.py`. Earlier suites
  (`test_app.py`, `test_node_readiness.py`, capture, operations, Git) are unchanged
  and green.
- Browser tests, `node --test tests/*.js`: 85 pass, 0 fail (new
  `test_telemetry_ui.js`: charts, link classes and titles, view states, settings
  save, overlay application, polling scope, Grafana links, link menu, renderer
  attributes, node menu, details drawer and tab wiring, capture context-menu
  delegation).
- Real browser smoke (not committed; Playwright with the session's Chromium against
  the app started with a seeded lab of one cEOS, one XRv9k and one cJunosEvolved
  node and 60 minutes of fake samples): the Telemetry tab, node cards, interface
  table, three charts, BGP table, settings dialog, the topology overlay (red
  mismatched link, dotted unknown links, node dots, live legend), the right-click
  link menu and *Telemetry r1:eth1* opening the tab preselected all rendered with
  no console errors and no CSP violations. Screenshots were reviewed for the
  legend/axis collision and the alias spacing, both fixed before delivery.
- Linux build path: no Docker daemon in the session, so no image build. `pip
  download --only-binary=:all: --python-version 3.12 --platform
  manylinux2014_x86_64` resolves pygnmi 0.8.15, grpcio 1.83.1, protobuf 7.36.1,
  dictdiffer and cryptography as wheels, so `pip install -r requirements.txt` in
  the python:3.12-slim image needs no compiler. `docker compose -f
  clab-backup-ui/compose.yml config --quiet` accepts the new
  `TELEMETRY_COLLECTOR` variable. `git diff --check` and `bash -n` on the deploy
  scripts are clean.

**Per-NOS support and validation matrix.**

| | cEOS | XRv9k | cJunosEvolved |
|---|---|---|---|
| Provisioning lines, prompts, scoped commit | fixture (scripted shell) | fixture (scripted shell) | fixture (scripted shell) |
| gNMI subscribe, encodings, paths | in-process gNMI server through pygnmi | in-process gNMI server through pygnmi | in-process gNMI server through pygnmi |
| Notification normalisation | fixture (`eos_*.json`) | fixture (`xr_*.json`) | fixture (`junos_*.json`) |
| Interface name mapping | unit tests | unit tests | unit tests |
| Live device: configuration, samples, traffic, link state, BGP, restart/redeploy, removal | **not verified** | **not verified** | **not verified** |

**Unverified on real images and to be confirmed with docs/TELEMETRY.md "Live
acceptance procedure":** that the containerlab defaults still enable gNMI on cEOS
and XRv9k as documented; that adding `no-tls` under an existing XRv9k `grpc` block
commits cleanly and the plain-text gRPC session accepts the password login; that
the Grafana and Prometheus containers start on the VM with the host-network,
tmpfs and dropped-capability settings; that cJunosEvolved 26.x accepts
`configure private` from the admin user and streams OpenConfig interface counters
with JSON_IETF or PROTO; which BGP paths each image serves (the BGP group reports
*unsupported* with the NOS reason when none does); the exact prompt strings of the
three CLIs (the drivers match generic prompt shapes and report a controlled
"did not return to its prompt" failure otherwise); and the real sample cadence,
which decides how quickly link colours follow an interface shutdown.

# Deploy-first UI and automatic NOS login — 1.22.0

Prepared on `claude/deploy-first-ui` from main `873366f` (1.21.1) for eight UI requests
(landing page, VM connection defaults, operation output, automatic NOS login, capture
interface list, capture target, viewer banner, `.pcapng` guidance). Everything below was
run on the Ubuntu 24.04 dev VM (Docker 29.8, Compose v5.5.1, containerlab 0.79.0, two
`arista_ceos` nodes, no KVM) against the staged 1.22.0 source (`git archive` of the
release commit), with the manager image and `clab-capture-service:1.22.0` rebuilt.

**Local checks (Windows workstation).** `python deploy/verify-release.py` reports
1.22.0. `node --test` over the ten browser test files: 74 pass, 0 fail (new
`test_readiness_ui.js`; extended `test_capture_ui.js`, `test_operations_ui.js`,
`test_vm_password_ui.js`, `test_capture_session_ui.js`). Python:
`test_node_readiness.py` (10 tests, new), `test_app.py`, `test_nodes.py`,
`test_junos_kinds.py`, `test_vm_files.py` (+1), `test_discovery.py`,
`test_import_confirmation.py`, `test_capture_sessions.py`, `test_capture_proxy.py`,
`test_runner_resilience.py`, `test_logging.py`, `test_topology.py`, `test_remove_lab.py`
and `test_manager_reset.py` pass in isolation; the full 500-test run shows only the
known Windows `os.replace` flake on random tests, each green on rerun. Linux CI is
authoritative.

**Verified on the VM, first staging (12:41 UTC):**

- Health: `check-install` PASS 59 / FAIL 0 / WARN 1 (folder coverage) with
  `[PASS] Running application version` and `[PASS] Optional packet capture`; helper
  1.22.0 connected; `/api/capture/health` ready.
- Readiness on the pair that was already running: within 6 s of the manager restart
  both nodes were probed with the saved profile, answered, the automatic NOS login
  test ran (`2/2 NOS sessions completed successfully`), the deployment bar read *NOS
  ready · 2/2 nodes accept SSH login* and the Nodes table showed *reachable* with the
  automatic-check timestamps.
- VM connection dialog: *Enable automatic discovery* and *Trust a replacement SSH
  host key on the next connection* both checked on open.
- Capture from the ceos1 row: *Topology interfaces* listed eth1 ticked, *All live
  Linux interfaces (14)* and *Advanced: other capture targets* collapsed, Start
  enabled. The session started; the viewer showed the one-row toolbar with the status
  inline and live STP/LLDP frames on eth1; *Download saved captures* answered in
  place with *No saved captures yet … type the full file name ending in .pcapng
  (Wireshark on the VM does not add the extension)*; *How to save a capture* opened
  with the same steps; the session was ended.
- Destroy lab from the deployment bar: Operation output opened with the green banner
  *✓ Destroy deployment succeeded · ceos-pair · Exit 0 · Operation completed*; the
  destroyed lab then reported *Not deployed* with both nodes *unavailable* and lab
  readiness idle.
- With the saved workspace removed, the landing page showed *Deploy a new lab*
  enabled, no VM note, no *Already running on the VM* list (nothing deployed), the
  two import links, and no *Lab actions* button.
- Deploy a new lab → Lab Topologies (in place) → /etc/containerlab → ceos-pair →
  ceos-pair.clab.yaml → Deploy lab: the workspace existed before containerlab ran
  (`lab.register` 13:04:26, deploy operation 13:04:42, VM path linked, both nodes on
  the containerlab default login, status booting); the banner read *Deploy lab
  running…* and then *✓ Deploy lab succeeded · Exit 0*; the monitor reported both
  nodes booting at 13:05:33 and answering at 13:05:53.

**Found and fixed during that run.** The automatic login test at 13:05:53 failed
`0/2` with `host key mismatch for 172.20.20.3`: the redeployed containers had new SSH
host keys (and swapped management addresses), and Ansible's paramiko transport had
recorded the old keys in the manager container's `~/.ssh/known_hosts` at 12:41 (the
inventory's `ansible_host_key_checking: False` does not reach the paramiko
sub-connection that ansible.netcommon opens, which loads and records known_hosts when
its own option is on). Before 1.22.0 every backup and login test after a redeploy
therefore failed until the manager container was recreated. Fixed by giving each job
HOME in its temporary directory plus `ANSIBLE_HOST_KEY_CHECKING=False`
(`runner.job_environment`), by making the readiness probe require a `show version`
answer over an SSH exec channel (checked against both live nodes: 0.5 s, exit 0,
`Arista cEOSLab …`) so SSH accepting a login while the CLI still starts no longer
counts, and by sending the nodes of a failed automatic test back to booting with up to
three automatic tests per boot. The shared not-ready pattern now also matches cEOS's
`% System is not yet ready` reply, which the backup path had accepted as output.

**Verified after the second staging (13:15 UTC, same manager container throughout).**
Right after the restart both running nodes answered `show version` and the automatic
test succeeded `2/2`. Then, through the API (the same preview/confirm path the UI
uses): destroy succeeded in 2 s; deploy succeeded in 46 s; 48 s after the deploy
started both nodes were *booting* (SSH not answering yet, addresses ceos1 172.20.20.3
and ceos2 172.20.20.2 reconciled by discovery); at 73 s both answered *NOS accepted SSH
login and answered show version*, the deployment bar state went to *ready*, `ssh_ready`
turned true for both, and the automatic NOS login test ran and succeeded `2/2` at
13:18:03 with the containers' new host keys. A manual backup on the redeployed lab
then succeeded `2/2` (13:18:15), and the manager container has no `~/.ssh` directory
at all afterwards: the jobs' known_hosts lived and died with their temporary
directories. `check-install` after the second staging: PASS 59 / FAIL 0 / WARN 1.
One API-only quirk seen while scripting this: a preview issued within about two
seconds of an operation finishing gets 409 *Wait for the current lab operation to
finish* while the manager runs its post-operation discovery refresh; the UI cannot
click that fast and the retry succeeds.

**Not run here.** vJunos, vQFX and XRv9k nodes cannot boot on this VM (no KVM): their
default logins are taken from containerlab.dev and their `show version` exec answers
were not exercised. `deploy/capture/smoke.py` is left to CI (`release-check`). The
Wireshark Save As dialog was not driven through noVNC.

# Browser Wireshark fixes — 1.21.1

Prepared on `claude/browser-capture-fixes` from main `7032daa` (1.21.0) after live
bug testing of 1.21.0 on the Ubuntu 24.04 dev VM (Docker 29.8, Compose v5.5.1,
containerlab 0.79.0, two `arista_ceos` nodes, no KVM). Everything below was run on
that VM against the staged 1.21.1 source (`git archive` of the release commit), with
the manager image and the `clab-capture-service:1.21.1` image both rebuilt from it.

**What 1.21.0 did on the VM before the fixes.** Every browser viewer failed with
*Viewer disconnected* (WebSocket close 1006): the pinned `wireshark-vnc-docker`
image's websockify answers HTTP 400 to a handshake without the `binary`
subprotocol, the session service closed before accept (403 in its log), and the
manager relayed the 403. CI's smoke step failed on `main` for the same reason. A
file written inside the container's `/pcaps` (what File → Save As does) was absent
from **Download saved captures** because the Docker archive API reads the container
filesystem through the daemon and never sees a tmpfs mounted inside the container.
`sudo bash deploy/setup-capture.sh` on a VM running the 1.20.1 stack ended with
`could not find a network matching network mode clab-manager-capture_default`
twice in a row and left Edgeshark stopped.

**Verified on the VM with 1.21.1:**

- **Migration.** The 1.20.1 capture stack was recreated on its original
  `clab-manager-capture_default` network, then the 1.21.1 `setup-capture.sh` ran:
  it rebuilt the service image, recreated gostwire and packetflix, created
  `sessions`, removed the old network and exited 0. `/api/capture/status` enabled,
  `/api/capture/health` `{"ready": true}`; `check-install` PASS 59 / FAIL 0 / WARN 1
  (folder coverage) with `[PASS] Optional packet capture`.
- **Viewer.** Through the manager relay from a stdlib-free `websockets` client:
  `RFB 003.008` greeting, version echo and security-type list `[1, 1]` both with no
  subprotocol offered (what the served noVNC does) and with `binary` offered
  (negotiated `binary`). In the desktop-app browser, **Start browser capture →
  Open Wireshark in browser** on `clab-ceos-pair-ceos1 eth1` rendered the real
  Wireshark desktop with *live capture in progress* and listed ICMP echo
  request/reply pairs from `ping 10.0.0.1` on ceos2 plus LLDP; Reconnect viewer
  reloaded into the same session. Cross-origin and foreign-cookie WebSocket
  attempts still return 403.
- **Downloads.** The Wireshark container now carries a labelled tmpfs-backed
  anonymous volume on `/pcaps` (256 MiB, uid/gid 1000, mode 0700, nosuid/nodev/noexec)
  and container tmpfs only for `/tmp` and `/config`. With nothing saved, the API
  answers 409 *No saved captures yet…* and the viewer shows that sentence in place
  instead of opening JSON. After copying the live capture file into `/pcaps` as
  uid 1000 inside the container, the download returned a tar with
  `pcaps/<name>.pcapng` whose bytes matched the file inside the container (pcapng
  magic, interface block present), and the viewer's Download button reported
  *Downloading saved captures*. A foreign cookie gets 404.
- **Cleanup.** End session removed the container and its volume; a dangling volume
  created by hand with the capture label was swept when the session service
  restarted; sessions survive a manager container restart.
- **Unchanged behaviour rechecked:** owner cookie flags, idempotent retry,
  409/422/404/429 paths, asset allow-list, no token in any manager response,
  service 403 without a bearer, backup job 2/2 cEOS nodes with ZIP download,
  inspect operation through the gateway.

**Not run here:** `deploy/capture/smoke.py` refuses a host with an existing capture
stack and the maintainer was using the VM's stack during this session, so its
run is left to CI (`release-check` executes it on push); it now reads `/tmp` and
saves into `/pcaps` with `docker exec`, never `docker cp`, and asserts the
empty-folder 409. Wireshark's own Save As dialog was not driven through noVNC
(keyboard modifiers do not reach the remote desktop from the desktop-app browser
pane); the file was written inside the container as the desktop user instead.

**Windows:** `python -m unittest discover -s tests -t tests -p "test_capture*.py"`
40 tests OK (with `websockets` and `uvicorn` installed), `test_release_consistency.py`
and `test_check_install.py` OK, `node --test` on the five UI suites 33 passed
including the new `tests/test_capture_session_ui.js`, `bash -n` on every deploy
script, `python deploy/verify-release.py` = 1.21.1, `git diff --check` clean.

# Browser Wireshark — 1.21.0

Prepared on `codex/browser-wireshark` from latest main `1d7e0f9` (1.20.1).
A final fetch found no additional main commits. This is source delivery, not a
published image, pushed commit or VM deployment.

- **490 Python tests completed across all 41 test files: 479 passed, 11 platform
  skips.** Tests ran per file in isolated processes on Windows. The first combined
  run was stopped while the Git integration suite was still running; a subsequent
  100-second per-file budget also timed out that suite. Its independent rerun
  completed all **24 Git tests in 248 seconds**, with no failures. The final **38
  capture tests** include discovery, stale selection, fixed Docker policy,
  ownership/authentication, retry idempotency, capacity, idle/hard expiry, partial
  creation cleanup, token rotation, saved-file transport and configuration migration.
- The manager's HTTP and binary WebSocket proxy was exercised over **real loopback
  connections to a synthetic session service**. Tests cover browser-cookie
  isolation, cross-origin rejection, upstream credential separation, JavaScript
  asset restrictions, binary round trip, download bytes and scoped CSP.
- **29 JavaScript regressions passed**, including 12 capture UI tests. Capture UI
  tests were rerun after the final launch-key/reset wording change.
- **Headless Chrome** exercised actual HTML/JS: live-interface selection against
  a synthetic API, launch, the browser popup, loading the noVNC adapter contract,
  viewer layout and ending a session. No browser script errors. Screenshots were
  visually reviewed; fixture screenshots/logs remain ignored under `.build/`.
  The displayed desktop was synthetic, not a real Wireshark GUI.
- Release metadata verifies as **1.21.0**, including the new viewer page and
  optional session-service image version. `bash -n deploy/setup-capture.sh`, Python
  compilation, parsing the four affected YAML files, and `git diff --check` passed.
- The public Wireshark image manifest was resolved and pinned to
  `sha256:682c8bd42282c44f991e0d6015ce3303e5a3aa08a1e2c2b6937fd554ddb31186`
  (Linux amd64 and arm64). Upstream Dockerfile/startup code and noVNC service paths
  were inspected. Setup's image pin is checked against the service constant.

**Still requires Linux/Docker acceptance:** no local Docker daemon was available.
The new `deploy/capture/smoke.py` and CI step have been authored but not executed
here. They start an isolated optional stack, check the real noVNC RFB greeting,
find actual captured loopback packet bytes, download saved capture data and end
its session. The smoke test refuses an existing capture stack/session and never
operates a training lab. CI also validates Compose configuration and builds the
session-service image. Do not equate local mocks, YAML parsing or this CI
configuration with a successful Docker build or live capture.

On the real VM also exercise a topology link, Wireshark filters, Stop / File →
Save As under `/pcaps`, archive download, reconnect, timeout and explicit End.
Confirm existing backup/SSH/lab operations continue. See docs/CAPTURE.md for setup,
limits, trust boundary, migration and cleanup. Historical validation below applies
to the releases named there, not to the new browser runtime.

# Capture vetting fixes — 1.20.1

- Prepared on branch `claude/capture-vetting-fixes` from main `71fb0e5` (1.20.0).
  Source delivery; no Docker image is published. Lockstep metadata verifies as
  **1.20.1** including `capture-setup.html`.
- **Live vetting of 1.20.0 on the dev VM (Ubuntu 24.04.4, no KVM)** that produced the
  findings: Edgeshark started from `deploy/compose.capture.yml` (packetflix 0.9.7,
  `127.0.0.1:5001`; `/` serves the UI, `/version` answers); the real
  `/discover/mobyshark` payload (15 rows over 5 namespaces) passes `normalize_targets`;
  the manager-built `packetflix:ws://…/capture?container=…&nif=eth0%2Feth1` URI, read
  with a stdlib WebSocket client on the VM while pinging between the cEOS nodes,
  delivered valid pcapng (one SHB, two IDBs, dozens of EPBs), so multi-interface and
  the percent-encoded `nif` work; 409 for unknown, duplicate and forged selections and
  after a disposable container restart; 403 cross-origin; 502 with a safe message when
  packetflix was stopped while the operations probe kept passing. Against packetflix
  0.9.7 a wrong PID, wrong start time, another live namespace identifier and a
  netns-only request **all captured**, which is why docs/CAPTURE.md no longer describes the
  `container=` identity as a stale-namespace check. A host-namespace launch returned
  200, then **409 after an unrelated container started** (a new veth), then 200 after
  it stopped: the identity hashed the whole interface list.
- Windows unit tests with the CI-style discover invocation: `test_capture` (22; four
  new: skipped rows, namespace merge preferring init, unrelated interface changes keep
  a selection valid, shared namespace listed once and launchable without aliases in the
  URL, unreadable rows counted), `test_check_install` (35; new capture check for
  disabled/enabled/failed/no-manager), `test_release_consistency`; all 58 JavaScript
  tests pass (three new capture-dialog tests plus the alias/loopback label test). The
  known Windows `state.enc` rename flake appeared once in `setUp` and passes on rerun.
- **Live verification of 1.20.1 on the same VM** after `start-manager.sh` rebuilt the
  manager: version 1.20.1 with the provider enabled; the host view lists the host
  namespace once as `systemd(1)` with `containerlab-node-manager-backup-ui-1` as its
  alias and merges the cEOS `CliShell(pid)` process rows into their node rows (the raw
  15 rows have exactly 5 distinct netns); a host launch returned **200, 200, 200**
  across an unrelated container start and stop; lab/node views are unchanged; forged
  and missing-interface selections still return 409; `check-install` reports
  **PASS 59 / FAIL 0 / WARN 1** with `[PASS] Optional packet capture` and its manual
  Wireshark item. In a real browser: the toolbar dialog shows "Choose a capture target
  above." with Prepare disabled, the host scope shows the alias labels, selecting
  `systemd(1)` keeps Prepare disabled until `ens33` is ticked, and Prepare then yields
  the `packetflix:` link with no console errors. The alias-label truncation ("+N more")
  landed after that browser run and is covered by the JavaScript test only.
- Found while redeploying: `setup-git.sh --list` (run as root by guided Git setup)
  imported `host_git.py` from the owner's source checkout and left a root-owned
  `__pycache__` there, so `rm -rf ~/projects/v1.20.1` failed as the owner.
  `git-registrations.py` and `check_install.module()` now set
  `sys.dont_write_bytecode`; the VM was cleaned with sudo once and the final commit
  redeployed from a fresh extract.
- Not exercised: the workstation cshargextcap plugin and SSH tunnel (Wireshark 4.6.8 is
  installed on the workstation but the plugin is not), VM-based NOS kinds, HTTPS/proxy
  Edgeshark deployments, and the `.env` copy path of `install.sh`.

# 1.20.0 — optional Wireshark capture (2026-09-12)

Prepared in the active workspace on `codex/wireshark-capture`, based on fetched
`origin/main` at `822cb33`, then synchronized with main `2b36478` (1.19.4)
after PRs #16 and #17 merged. Engineer access setup, topology file permissions,
installer/health checks and upstream live-validation records are retained.
The feature remains staged, with no source commit, push, image build or live
Wireshark deployment performed here.

## Verified locally

- After synchronizing with main `2b36478` (PRs #16 and #17), the full Python
  suite ran **469 tests, OK, 11 skipped**, in 239 seconds on Windows. No failures.
  This includes all **18 capture tests**, the engineer-access health and installer
  regressions, and the existing operations/backup/Git tests. The additional
  POSIX topology-permission regression is among the Windows skips.
- All upstream-only files were verified byte-for-byte against main. Host helpers
  match main exactly apart from their 1.20.0 release metadata. Feature-only files
  match the preserved pre-sync feature, and upstream validation history is retained.
- All **55 JavaScript tests passed** again after main synchronization, including
  nine capture UI regressions. Desktop/mobile browser checks below were also rerun.
- All seven release-consistency tests passed with the new setup page included.
  `deploy/verify-release.py` reports **1.20.0**.
- JavaScript syntax and `git diff --check` passed.
- Headless desktop Chrome used the real application UI and FastAPI server, with
  isolated temporary lab data and a synthetic Edgeshark provider. Checked a node,
  both link endpoint selection and interface preselection, two interfaces in one
  namespace, host-interface capture preparation, native URI generation, and the
  in-app setup page. No browser JavaScript errors.
- Inspected desktop and 390px mobile screenshots; verified dialog and page have
  no horizontal overflow, including the capture and topology action rows.
- Checked Siemens' discovery schema, Packetflix API and native launch code.
  Resolved and pinned public multi-architecture image manifest digests; both
  contain Linux amd64 and arm64 images. Provider response time/size bounds,
  redirect rejection, exact node matching, process restart/interface changes,
  malformed payloads, cross-origin requests and concurrent discovery limits are
  covered by the regression tests.

## Deployment checks still required

There is no Docker executable or installed WSL/Linux environment on this machine.
No manager image or optional-service containers were built/run locally. YAML
parsing is checked locally; actual `docker compose config` is added to Linux CI,
with no claim that the new CI job has run. No desktop Wireshark plugin was installed
or invoked, and no live packets, router NOS, host capture capabilities, SSH tunnel,
TLS proxy or Linux namespace lifecycle were tested. Browser checks prove capture
selection and handoff generation, not packet streaming.

Follow [docs/CAPTURE.md](../docs/CAPTURE.md) for installation, research sources, known
Linux/VM visibility limits, and the disposable-lab live acceptance procedure.
Prepared URLs include Packetflix namespace/process identity checks; processless
namespaces retain the upstream namespace-reuse limitation. The provider is
optional, has no manager socket/capability changes, and is disabled by default.

---

# Engineer access for VS Code and the Containerlab extension — 1.19.4

- Prepared on branch `claude/engineer-access` from the 1.19.3 branch tip `3d10cb4`
  (main `822cb33`). Source delivery; no Docker image is published.
- Adds `deploy/setup-engineer-access.sh`, the `start-manager.sh --refresh` re-apply,
  the installer question/phase 5/menu option 3, the `check_host._engineer` health
  check, and the `host_operations.py` create mode (0664 in a setgid parent, else
  0644). Lockstep metadata verifies as **1.19.4**; the new script is in the CI
  `bash -n` list.
- Windows unit tests with the CI-style discover invocation: `test_check_host` (16,
  four new: unconfigured INFO, configured PASS, each missing piece FAIL, unprivileged
  runs no commands), `test_install_manager` (16, one new: the engineer phase runs
  after manager verification only when chosen, with `--owner USER`),
  `test_lab_operations` (22; the POSIX file-mode test skips on Windows and runs in
  Linux CI), `test_check_install` (34), `test_release_consistency`,
  `test_helper_preflight`, `test_gateway_preflight` and `test_git_onboard` all pass.
- **Live dev-VM validation (Ubuntu 24.04.4, no `/dev/kvm`), applied by the author with
  the maintainer's passwordless sudo and read back afterwards:** before the change the
  VM reproduced both reported errors (no `clab_admins` group, `clabllm` in neither
  `docker` nor `clab_admins`, `/etc/containerlab` root:root 0755, containerlab 0755;
  `mkdir /etc/containerlab/vscode-test` denied). After
  `setup-engineer-access.sh --owner clabllm`, a fresh login showed both groups; the
  roots became `clab_admins 2775` and the existing lab file 664; `mkdir` and a new
  topology under `/etc/containerlab/vscode-test` succeeded as `clabllm`, inheriting
  `clab_admins 664`; `containerlab inspect --all` and `docker ps` worked without
  sudo (SUID `-rwsr-xr-x root root`). The still-running 1.19.3 manager browsed and
  read that engineer-created folder through the gateway. `start-manager.sh
  --enable-operations` then upgraded the VM to **1.19.4** (gateway verified for
  discovery, operations and Git at 1.19.4; container `clab-backup:1.19.4`), and its
  `--refresh` call restored `clab_admins 2775` on the projects root that
  `setup-operations.sh` had reset plus the SUID bit. Afterwards: Debug probe
  **browse PASS, capabilities PASS (1.19.4)**; `check-install` **PASS 58 / FAIL 0 /
  WARN 1 / INFO 5** including `[PASS] Engineer access for VS Code / Containerlab
  extension`; a topology **created by the manager** through the operations gateway
  (`preview` + `confirm`, job succeeded) landed as `root:clab_admins 664` and the
  engineer could edit it. Negative path: with the projects folder and SUID
  deliberately reset, `check-install` reported `[FAIL] Engineer access` naming both
  pieces with the `--refresh` fix, `--refresh` repaired them, and the report returned
  to PASS 58 / FAIL 0. The VS Code extension's own activation after killing its
  server was left to the maintainer and not observed by the author.

# V1.19.2 bug-fix report follow-up — 1.19.3

- Prepared from published main `0faae0b` (1.19.2) on branch
  `claude/v1.19.2-bug-fix-report`. Source delivery; no Docker image is published.
- **Live dev-VM validation (Ubuntu 24.04.4, x86_64, no `/dev/kvm`):** the branch was
  staged with `git archive`, `deploy/install-prerequisites.sh --docker --containerlab`
  installed Docker 29.8 / Compose v5.5.1 / containerlab 0.79.0, and the maintainer ran
  the interactive steps (`start-manager.sh --enable-operations` with the clab-discovery
  password, the browser VM connection, and `setup-git.sh` choosing a subfolder). The
  resulting state, read back without changing it: manager container `clab-backup:1.19.3`
  running; `/api/state` reports version 1.19.3, discovery configured and connected as
  `clab-discovery`, helper 1.19.3; the Debug probe reports **browse PASS and
  capabilities PASS** through the real SSH gateway (the path that returned 409 in the
  1.19.2 report); a two-node `arista_ceos` lab (`n24l/ceos:4.35.0F`, container-only)
  was **deployed through the operations gateway** (`deploy` succeeded, exit 0, then
  `inspect-all`), imported as Running with both nodes Ready; a NOS login test and a
  backup **succeeded on both nodes**; one Git registration carries the new
  subfolder prompt (label `CLAB-MNGR-DEV-LLM / ARISTA-LAB-TEST`, prefix
  `ARISTA-LAB-TEST`) and one Save progress is `synced` with a verified pushed commit;
  `bash deploy/check-install.sh` reports **PASS 57 / FAIL 0 / WARN 1 / INFO 5** on
  source 1.19.3, the WARN being the default 20-folder browse budget. The first-run VM
  connection dialog and the green setup banner were exercised by the maintainer and
  not directly observed by the author.
- Fixes: `diagnostics.failure_hint` now orders the gateway/account phrases before a
  tightened password rule, so the Debug panel no longer reports a reachable-account
  operations-gateway failure as an authentication/password problem;
  `lab_operations.operation_connection_error` and `check_install`'s topology-browser
  next step were reworded to match, and `check_install` gives a gateway-specific step
  when discovery is connected. The manager prompts for the VM connection once on first
  load when none is configured. Guided Git setup prompts for a per-lab repository
  subfolder (one repository, many labs) and ends with a success banner.
- Release metadata verifies as **1.19.3** (`python deploy/verify-release.py`), including
  the `app.js` footer fallback and every `?v=` asset in the five static HTML pages.
- Focused suites run on the Windows workstation with FastAPI/httpx/paramiko installed:
  `test_diagnostics` (9), `test_operations_ssh` (14), `test_lab_operations` (21, 1 skip),
  `test_check_install` (34, 1 skip), `test_check_host`, `test_git_onboard` (42),
  `test_git_registrations`, `test_gateway_preflight`, `test_helper_preflight`,
  `test_install_manager`, `test_check_git`, `test_apt_sources`, `test_apt_update`,
  `test_junos_kinds` and `test_release_consistency` all pass. The new/changed test
  methods were also run individually and pass.
- JavaScript: **46 tests pass** (`node --test tests/*.js`), including three new
  first-run VM-prompt tests; `node --check` passes for `app.js` and `management.js`.
- The full Windows unittest run (445 tests) shows the known, nondeterministic
  `PermissionError: [WinError 5]` on `os.replace(state.enc.tmp -> state.enc)` in
  `Store.atomic` during `setUp`; each affected test passes when rerun in isolation.
  This is a Windows open-handle rename limitation, not a product defect. Judge the
  suite by isolated reruns or by Linux CI.
- `bash -n` passes for all deploy scripts. VM-based NOS kinds (vJunos, XRv9k) were
  not exercised because the dev VM lacks nested virtualization; only the container
  cEOS kind was deployed and backed up.

# Integrated audit recovery fixes — 1.19.2

- Integrated the unmerged audit commit `8d87ea8` with current main `2c10037`
  (1.19.1) on `codex/deployment-operation-audit`. The local merge is resolved
  and staged for review; no new commit, push or GitHub merge was performed.
- Full combined Python suite: **443 tests ran, 433 passed and 10 skipped**
  in 244 seconds. All **43 JavaScript tests pass**. Skips cover Linux
  Ansible control-node behavior, controlling-terminal/process groups,
  symlink/openat checks and the opt-in EOS SSH fixture. No remote CI result is
  available for the uncommitted integration.
- Before integration, 16 focused audit tests against current main produced
  three passes, five failures, seven errors and one Linux-only skip. The failure
  paths cover topology overwrite, storage recovery, stuck lab/Git guards, audit
  logging, bounded Git stderr and cleanup after the Git parent exits. The
  previously failing regressions now pass as part of the combined suite.
- Retained main's SSH EOF implementations and added audit bounds/recovery without
  shortening its 60-second discovery deadline, helper inspect/label budgets,
  refresh wait or 90-second debug probes. Its authentication hints, terminal Git
  clone behavior, dependency bounds and LF normalization remain present.
- Real localhost SSH regressions from both branches pass, including delayed and
  fragmented output after exit status. Helper-timeout tests and diagnostics
  tests confirm the newer budgets are retained. Host-service/package probes use
  mocks; localhost Paramiko is not an Ubuntu OpenSSH installation test.
- Release metadata, including the app.js footer fallback, verifies as 1.19.2.
  Workflow YAML, Bash syntax for all ten deployment scripts, and Git whitespace
  checks pass. CI includes both branches' relevant SSH, timeout, Git recovery,
  operation, logging and browser regressions.
- No Docker build, fresh Ubuntu install, live VM helper call, device action or
  remote Git push was performed. The real Linux Git inherited-stdout timeout
  regression is skipped locally and included in CI. Full deployment validation
  remains outstanding; see the [audit report](../docs/archive/DEPLOYMENT-AUDIT.md).

# Transport EOF, helper timeouts and hygiene — 1.19.1

- Prepared from published main `2d34415` (1.19.0) on
  `claude/transport-eof-and-helper-timeouts`. No image build, fresh-VM run,
  live VM helper call or device validation was performed on this Windows host.
- Real localhost Paramiko regressions now cover discovery as they did
  operations: exit status before a delayed tail, exit status before a 160 KiB
  multipart tail, and nonzero status before a tail (six discovery SSH tests).
  Git transport tests replace the old `recv_ready` mock with an EOF-terminated
  stream, add a fragmented tail with early exit status, and assert a truncated
  envelope is never parsed (six tests). Both loops copy `lab_operations.remote`.
- Four helper timeout tests verify the 25 s inspect / 8 s label budget fits the
  60 s manager deadline, that an expired watchdog raises `TimeoutError`, that a
  completed inspect parses, and that the helper's stderr names the timeout.
  Diagnostics tests cover the new `failure_hint` classification of Paramiko
  "Authentication failed." and the 90 s probe budget.
- Full Python suite on Windows with Git and Node on PATH: 427 tests ran,
  424 passed, nine skipped (Linux Ansible control node, controlling terminal,
  openat symlink, opt-in EOS fixture). Three errors were the known Windows
  `os.replace` PermissionError on `state.enc` and each passes when rerun alone.
  Twenty-two real-repository host Git tests ran that previous Windows runs
  skipped for lack of git. JavaScript: 42 tests pass; `node --check` passes.
- `deploy/verify-release.py` reports 1.19.1 including the new `app.js` footer
  check; `bash -n` passes for every deploy script. ShellCheck was unavailable.
- Vendor collection ranges were read from the Galaxy API on 2026-09-11
  (netcommon 8.6.2, junos 11.1.1, iosxr 12.4.2, eos 12.2.0); an unconstrained
  build that day would resolve the same majors. A Docker build with the pinned
  ranges has not been run here.
- Line-ending normalization was committed separately with
  `git add --renormalize`; the change is content-neutral for every parser the
  files feed and must be reviewed as such.
- The OpenSSH ordering (exit-status request emitted before the remaining pipe
  data is drained) is modelled by the fixtures; the effect on the user's VM
  still needs a live discovery and Git save after upgrading image and helpers.

# Development debug panel and folder browsing — 1.19.0

- Prepared from merged main `a7a016b` (1.18.1) on
  `codex/development-debug-panel`. No commit, push, image publication or VM
  deployment was performed.
- Full Python suite: 416 tests ran, 407 passed and nine skipped. Skips cover
  Linux Ansible control-node behavior, controlling-terminal/process groups,
  symlink/openat checks and the opt-in EOS SSH fixture. The seven focused debug
  tests also pass, including a server-error test added after the full run.
- All 42 JavaScript tests pass (39 existing/operations tests plus three debug
  UI tests). Browser regression proves a listing renders while capabilities
  are still pending, survives their failure and retries folder expansion.
- Debug tests cover availability before setup, metadata bounds, secret/path
  exclusion, safe exception classification, same-origin rejection, simultaneous
  probe rejection, settings changes during checks, version mismatch, failed
  checks, safe text rendering, retry and JSON report generation.
- An isolated localhost browser fixture verified the debug page, readable
  narrow layout, separate browse PASS / capabilities FAIL results, and topology
  folder expansion while capability checks fail. No real VM was contacted.
  Report Blob contents and download naming passed the UI harness; the in-app
  browser did not emit a download event, so a saved workstation file was not
  independently confirmed.
- Release metadata, workflow YAML and Git whitespace checks pass. CI now runs
  debug API and browser regressions; this branch's remote CI has not run yet.
- Existing 1.18.1 SSH EOF handling is retained and its real localhost Paramiko
  tests pass. The identified browser dependency is a separate failure path;
  confirmation of the user's actual VM error still requires a live debug report.

# Operations helper and installation diagnostics — 1.18.1

- Prepared from merged main `7331e9a` (1.18.0) on `codex/operations-helper-fix`.
  Commit, push, publication and VM deployment remain pending.
- Reproduced the exact generic operations-helper error in two real localhost SSH
  tests before changing the client: exit status arriving before the final JSON
  result, including a fragmented 160 KiB response. Both pass with EOF-based reads.
  This establishes a transport defect; it does not prove the cause on the user's VM.
- All 14 real SSH regressions pass, including streamed output, fingerprint pinning,
  late output, nonzero/missing exit status, incomplete JSON, bounded stderr and
  controlled diagnostic messages without leaked stderr secrets.
- The 133-test application/health/installer regression run passed with two skips:
  131 passed; the Linux controlling-terminal regression and symlink creation test
  could not run on this Windows host. Host services and permission probes are
  mocked; the localhost SSH tests use Paramiko, not Ubuntu OpenSSH.
- The checker now retains its terminal/session for sudo's authentication timestamp,
  and tests the actual query runner before reporting administrator access PASS.
  This corrects the false-failure pattern in the user's 1.18.0 report. The root-run
  workaround is documented; the corrected live VM report is still outstanding.
- The delegated gateway suite adds 12 passing tests and two Linux-only process
  regressions skipped here: 147 tests selected overall, 143 passed and four skipped.
  It covers sudo denial, missing capabilities, invalid versions, timeout/overflow
  cleanup, failed pipe reads and unfinished readers without exposing helper output.
- The launcher additionally checks the restricted gateway and core capabilities
  before rebuilding. These are read-only preflight queries, not a lab deployment.
- Source metadata verifies as 1.18.1. ShellCheck, Python syntax, workflow YAML,
  documentation links/fences and Git whitespace checks passed. CI includes the
  SSH, operations and delegated gateway suites; this branch's CI has not run yet.
- No Docker image build, real fresh Ubuntu install, live gateway/sudo check or lab
  deployment was performed. The saved VM account and live deployment outcome still
  need verification on the user's VM. No existing labs or credentials were changed.

# Juniper vQFX and vJunos-switch — 1.18.0

- Prepared from merged main `712662f` (1.17.0) on `codex/junos-switch-kinds`.
  Commit, push, publication and VM deployment remain pending.
- 118 focused tests selected: 114 passed and four Linux-only checks skipped on
  this Windows host. Coverage includes 14 new Junos-kind tests plus application,
  discovery, VM import, downloads, Git progress, topology, release consistency
  and helper-preflight regressions.
- The new tests exercise canonical/legacy kind imports, generic Junos driver
  precedence and conflicting groups, saved-node sync with retained selection,
  credentials and manual endpoints, distinct credential defaults, generated
  Junos commands, `.set` captures, immutable download naming, Git manifest/byte
  preservation and SuperPuTTY usernames. Device and Git processes are mocked;
  temporary captured fixtures do not demonstrate a live NOS backup or push.
- Source release verification reports 1.18.0. Python syntax, workflow YAML,
  documentation links/fences and Git whitespace checks passed. CI now includes
  the Junos-kind suite with application test dependencies; that workflow has
  not yet run on GitHub for this branch.
- No Docker image build, live SSH/backup against either new NOS, or VM deployment
  was performed. Existing cJunos behavior and historical capture metadata are
  retained. Manager support does not remove Containerlab's documented restriction
  on deploying vJunos-switch inside another VM; this is covered in the VM guides.

# Installation health report — 1.17.0

- Prepared from merged main `7c25648` (1.16.1), retaining the pending WinSCP
  instruction updates. Commit, push and VM deployment remain pending.
- 163 focused tests passed: health report 32, host checks 12, Git checks 13,
  installer 15, APT clock/update 17, Git wizard 40, registrations 9, APT sources
  14, release consistency 7 and helper preflight 4. Host/service commands and
  HTTP were mocked; this is not evidence that the user's VM is healthy.
- Covered root-only helper success with failed restricted access, unavailable
  operations, real-folder request failures, empty inventories/folders, bounded
  traversal, stale or unsafe helpers, missing persistent storage/key, invalid
  state, version drift, Git owner/identity/staging/remote-read failures, omitted
  secrets and independent continued reporting. Watchdog regressions cover
  descendants holding stdout, privileged timeout wrapping and one HTTP deadline
  across connection and body reads.
- ShellCheck passed for check-install.sh, install.sh, install-prerequisites.sh,
  setup-git.sh and start-manager.sh. Source consistency reports 1.17.0; Python
  syntax, Markdown links/fences and Git whitespace checks passed. CI includes
  the new tests and shell launcher, but has not run on GitHub for this change.
- No packages, clocks, services, Git checkouts or lab configurations were changed
  on a VM. No Docker build, live SSH/SFTP login, device backup or real GitHub
  authorization/push was performed. The report distinguishes these remaining
  manual workflow tests from automated checks.

# Installer clock recovery — 1.16.1

- Prepared from merged GitHub main `58a17bd` (1.16.0); commit/push is pending.
- 105 focused tests passed: APT clock/update handling 17, installer 14, Git
  wizard 40, registrations 9, APT sources 14, release consistency 7 and helper
  preflight 4. System/package commands were mocked; no clock was changed.
- Covered the reported future Release date error, expired/stale metadata,
  synchronized/manual/unavailable clocks, bounded active-NTP waits using
  monotonic time, strict APT checks, streamed output and original failure codes.
  Git package setup stops before installation after a failed update.
- ShellCheck passed for install.sh, install-prerequisites.sh, setup-git.sh and
  start-manager.sh. Source consistency reports 1.16.1. Documentation adds
  pre-bootstrap clock checks and recovery within the original paused run.
- No live Ubuntu package installation, NTP recovery, Docker build or VM
  deployment was performed. The new CI test entry is prepared locally.

# Consolidated terminal installer — 1.16.0

- Prepared from local 1.15.3 commit e64790a; latest fetched main was 0658562.
- 88 focused tests passed: installer 14, Git wizard 40, read-only registrations 9,
  APT source handling 14, release consistency 7 and helper preflight 4.
- Covered step retry/cancel, real-owner environment, retained .env bytes, custom
  ports/IPv6 and version failures, registered checkout selection, custom binding
  preservation/rechecks, URL correction, login recovery, identity repair and
  exact APT backups that preserve network sources, disabled Docker repositories,
  and explicit local Docker targeting. Package/sudo commands were mocked.
- ShellCheck passed for install.sh, install-prerequisites.sh, setup-git.sh and
  start-manager.sh. Source verification reports 1.16.0. Git whitespace checks passed.
- CI now includes these stdlib regression tests and installer shell syntax checks;
  the updated workflow has not yet run on GitHub.
- No fresh Ubuntu install, live GitHub authorization, package installation,
  Docker build or VM deployment was performed here. Validate the complete path
  on a disposable Ubuntu 24.04 VM before treating it as a verified VM install.

# Git owner and identity guidance — 1.15.3

- Based on merged main 0658562. Guided setup accepts an existing checkout directly,
  repairs invalid identity, and retains valid settings and the owner's environment.
- 19 onboarding tests passed, including existing-checkout resume without cloning,
  blank input retry, invalid identity repair and preservation of valid identity.
  Seven release-consistency and four helper-preflight tests passed (30 total).
- ShellCheck passed for setup-git.sh and start-manager.sh. Source verification
  reports 1.15.3; Git whitespace checks passed.
- Shell registration still runs Git only after dropping to the owner. Failure
  guidance retains custom registration settings and provides absolute paths.
- No live Ubuntu registration, package installation, Docker build or deployment
  was performed. Changes are prepared locally for user commit and push.

# Guided Git setup recovery — 1.15.2

- Based on GitHub main 698fabb, preserving the latest user wiki edits.
- Reject GitHub branch/file page URLs before choosing a directory or authenticating;
  retain HTTPS repository URLs and nested namespaces on other Git hosts.
- Package-update failures stop before installation, with source-repair instructions;
  package-install errors report their own recovery step. System sources are not edited.
- Focused validation passed: 15 onboarding tests, seven release-consistency tests
  and four helper-preflight tests (26 total). Source verification reports 1.15.2;
  the Git whitespace check passed. These are local tests with mocked package commands.
- No live Ubuntu package installation, Docker build, VM upgrade or push was performed.

# Repository consistency repair — 1.15.1

- Audited current GitHub main b0389ba and reproduced its source/helper version
  mismatch. Corrected VERSION to match the existing 1.15.1 runtime components.
- Seven release-consistency tests and four helper-preflight tests passed. Cases
  include the stale VERSION file, each runtime metadata location, empty lab
  inventory, malformed responses, and version errors without credential leakage.
- Source consistency check, launcher ShellCheck and Git whitespace checks passed.
- New GitHub Actions workflow is prepared but has not run on GitHub. Docker build
  and fresh-VM launch have not been executed here. No remote push was performed.
- Existing runtime code is retained; the historical full-suite results below
  describe their original runs, not a new full-suite run for this cleanup.

# Git progress validation — 1.15.0

- Baseline: GitHub main 160fe5e. This cumulative source release includes the prior
  VM password and UI/diagram changes documented below.
- Full Python suite: 204 tests run, 198 passed, 6 platform/opt-in skips.
  Includes 20 host Git tests (real disposable repositories/bare remotes and mocked
  production dispatch), 19 coordinator tests, four bounded SSH transport tests,
  and five worker logging/persistence recovery tests. Existing backup, password,
  topology, file-transfer and lab-operation regressions also passed.
- Real Git cases cover exact artifact bytes, unrelated/staged work, foreign
  outgoing commits, no-op saves, baseline-only changes, checkpoint uniqueness,
  changed remotes, fast-forward updates/divergence, failed pushes, ancestor-save
  reconciliation, interrupted writes/commits and retries after owner repairs.
  A no-change save compares as empty; long and reserved device names export safely.
- Coordinator tests cover exact selected scope, incomplete captures, provenance,
  idempotency, review preferences, retry-without-push, lost replies, capture-ID
  persistence failure, restart recovery, pending-save guards and version ZIPs.
- JavaScript: 38 tests passed, including 14 Git workflow tests for payloads,
  escaped output, destination acknowledgement, historical target selection,
  request-ID reuse, double-click prevention and modal/polling behavior.
- Browser QA used an isolated local manager, synthetic device captures and real
  local Git checkouts/remotes. Checked repository selection, one-click save,
  diff/version viewing, ZIP download, checkpoint capture, failed push and retry,
  and baseline from an older capture. Verified retry created no new capture and
  baseline left latest untouched. No real VM/device/remote account was accessed.
- ShellCheck passed for setup-git.sh, start-manager.sh and clab-manager-gateway.
  Deploy shell files remain LF; Python source/embedded setup code compile.
- The source ZIP and cumulative patch are verified against clean 160fe5e. The
  package excludes preview state, environments, real captures and credentials.
- Linux sudo/UID transitions, the owner's noninteractive HTTPS credential helper,
  Docker image build and real NOS captures still require deployment validation.
  Mocked privilege-order checks do not establish live Linux permission behavior.
  No GitHub push, registry publication or deployment was performed. Load version
  retrieves files; applying configurations to live devices remains unavailable.

# UI and diagram validation — 1.14.0

- Baseline: GitHub main 160fe5e; includes the 1.13.0 VM password changes below.
- Full Python suite: 156 tests run, 150 passed, six platform/opt-in skips.
  New tests cover saved annotation persistence/restart, unchanged wiring/no VM writes,
  unsaved export, XML escaping, JSON style round-trip, invalid input, stale-map
  conflicts and rollback after failed saves.
- JavaScript: 24 tests passed. New geometry/payload tests cover line movement,
  coordinate limits, node identity and revision retention.
- Browser checks used an isolated local 1.14.0 fixture without a VM connection:
  sidebar labels/order, release caption, default Topology view, Credentials dropdown,
  equal 12px tab text, Deploy New Lab wording, text/box editing, saved/reopened edits,
  Undo and discard confirmation. Input events update the canvas before Save.
- Inspection dialog checked at a 1280px viewport: width about 1242px; full long
  topology path wraps and no table cell truncates its text.
- Master wiki updated from the user-supplied document. Proxmox/Ubuntu sections
  retained; old VM client-key procedures replaced with setup, encrypted persistence,
  one-time migration and password recovery. Source builds are the default.
- Source ZIP and cumulative patch checked against clean 160fe5e; Linux scripts
  remain LF. Generated artifacts exclude preview data and email attachments.
- No Linux VM installation, Docker build, live-device test, registry publication,
  GitHub push or deployment was performed. Those deployment checks remain as
  described in the password validation below.

# VM password validation — 1.13.0

- Baseline: fresh clone of GitHub origin/main at 160fe5e (V1.12.1 bug fixs).
  Work is isolated in branch codex/vm-password; previous local checkouts preserved.
- Full Python suite: 151 tests run, 145 passed, six platform/opt-in skips. Includes
  synthetic local SSH transport for discovery, SFTP and structured operations.
- New tests cover key-to-password migration, fingerprint retention, encrypted
  persistence/restart, password rotation and blank preservation, rejection of key
  fields, no credential leakage, and effective SSH policy conflict detection.
- JavaScript: 22 tests passed, including new password form and migration behavior.
  Node syntax check passed for management.js.
- ShellCheck 0.11.0: no findings for setup-discovery.sh, setup-password.sh,
  setup-operations.sh, start-manager.sh and the shared gateway.
- Browser: inspected the real local 1.13.0 app with isolated data, confirmed the
  masked/required password field, default account, absence of client-key controls,
  dialog layout and rendered password setup/recovery guide.
- Whitespace check passed with cr-at-eol for the repository's tracked CRLF files;
  Linux scripts remain LF and are protected by .gitattributes.
- No Linux VM/systemd/passwd/sshd installation, Docker image build, live NOS test,
  registry publication or GitHub push was performed. Deployment validation should
  cover a fresh account, existing key migration, cancelled password prompt, restart,
  password reset, rejected client keys/shell/forwarding and unchanged admin login.

# UI refinement validation — 1.12.1

- Python regression run: 145 tests; six platform/environment skips. The only
  initial failure was the previous version assertion, updated to 1.12.1 and rerun.
- New coverage: topology filtering before the 500-entry limit, quick-action state
  guards and deploy/start selection, and no automatic topology dialog on entry.
- Browser fixture: same-tab Deploy New Lab landing page, explicit Lab Topologies
  opening, filtering old-helper mixed results, topology Deploy lab confirmation,
  cancellation, return navigation, and status-panel Destroy confirmation. No
  browser console errors were reported during the check.
- Synthetic SSH/operation fixtures only; no live NOS commands or Docker build.
- Git fetch was unavailable because the local Git remote-https helper is missing.
  Existing local source was preserved; no push or registry publication occurred.

# Validation — Containerlab Node Manager 1.12.0 (2026-09-10)

## Current release

- Python: 144 tests completed, 138 passed and 6 existing platform/opt-in skips.
  The suite includes discovery/import, persistence, backups, terminal tickets,
  scoped host operations, source deletion and current removed-action rejection.
- JavaScript: all 17 regression tests passed. All application scripts pass Node
  syntax checks. Inspection tests cover flat/grouped JSON, surrounding CLI logs,
  IPv4/IPv6, health/image fields, malformed output and escaped untrusted values.
- Start fresh tests verify explicit confirmation, busy backup/operation/SSH/
  discovery guards, retained VM credentials/fingerprint/encryption key, deletion
  of backup files/history/exclusions, cache invalidation and retention of unknown
  files. Interrupted state commits and staged cleanup failures resume correctly.
- Draw.io tests verify the supplied fixture's annotation text, node coordinates,
  containment-relative coordinates, unique cell IDs, endpoint labels, source/target
  references, escaped XML and unsupported-layout rejection. Exporting unsaved
  node positions leaves the saved layout unchanged. The full diagrams.net desktop
  editor was not launched; pixel-identical rendering is not claimed.
- Browser checks on isolated loopback SSH fixtures: automatic page load without
  login; retained VM settings and guide link; simplified lab action menu; interactive
  editor/full export; inspect review and 12-node result table; expanded topology
  bulk backup review; node right-click SSH/backup menu; exclusion clearing; lazy
  vertical project tree and read-only YAML. Start fresh cleared preview storage,
  preserved VM connection and returned the deployment to Ready to import with
  confirmation still required. No real VM or device commands were run.
- Fetched origin/main 7c5cef6 exactly matches the previous delivered 1.11.0 source.
  Release ZIP and patches are verified against that revision, the previous source
  ZIP and original baseline 06b8624. Shell files retain LF line endings.
- This Windows environment cannot build/run the Linux Docker image or install
  privileged helpers on a Containerlab VM. Actual image build, sudo/helper setup,
  Containerlab lifecycle commands and live NOS connectivity remain VM validation.
  Use the documented start-manager command to update helpers and image together.

## Historical release evidence

# Validation — Containerlab Node Manager 1.11.0 (2026-09-10)



## 1.11.0 evidence



- Full Python suite: 136 tests, 130 passed, 6 skipped for unavailable platform

  capabilities. Existing map, persistence, import confirmation, discovery, backup,

  SSH and removal checks remain included.

- All 14 JavaScript regression tests pass; new operations/workspace scripts pass

  Node syntax checks. Browser checks cover the new interactive flows.

- Host operation tests exercise exact scoped argv, feature detection, redeploy

  fallback order, unsupported flags/actions, path traversal, changed source/state/

  options, file creation, write/delete recovery, active-lab deletion refusal,

  optional cloning/sharing/fcli constraints, output bounds and secret redaction.

- Real subprocess tests verify stderr cannot corrupt inspection JSON and a

  disconnected streaming consumer terminates the child process.

- Real loopback Paramiko tests verify structured stdin, literal forced command,

  fragmented NDJSON output, failed exit/error handling and fingerprint mismatch.

- Authenticated API tests cover cancel, single-use/expired/revision-bound reviews,

  backup/operation conflicts, disk-save failure, output persistence and restart

  interruption, YAML diffs/name overrides, favorites/layouts and XML parsing.

  GoTTY JSON-port and HOST_IP output formats are covered; fcli reads the current

  VM management network and rejects incompatible saved labs.

- Browser fixture uses the supplied BGP topology with sanitized annotations and

  twelve nodes. Verified lab header and sidebar right-click menus, cleanup review

  cancellation, inspect confirmation/live output/success, YAML diff/cancel,

  drag-and-save layout, project browser, popular catalog selection, clone details,

  GoTTY port entry, and the new-tab SSH launcher with correct node-specific links.

  No browser console errors observed. No real VM/device commands were run.

  Screenshot: dist/lab-actions-1.11.0.png.

- Latest fetched origin/main b20468e matches delivered 1.10.0 source except the

  three ignore files. Source ZIP and patches target that commit, previous 1.10.0

  delivery and original baseline 06b8624; packaging checks reconstruct the source.

- Windows has no Docker/Containerlab/Linux host service here. Actual root helper

  installation, flock/process-group behavior, Docker image build, lifecycle

  operations and external SSHX/GoTTY/fcli services require a disposable Linux lab.

  These are not claimed as live deployment validation.



## Earlier release evidence



# Validation — Containerlab Node Manager 1.10.0 (2026-09-10)



## 1.10.0 evidence



- Full Python suite: **113 tests, 108 passed, 5 skipped**. Existing platform/opt-in

  skips remain. JavaScript regressions: **14 passed**; management script syntax checked.

- Eight confirmation tests cover background polling/preview without saving, cancel

  semantics, explicit token requirement, single save, changed files/VM, expiry,

  retained exclusions on cancel, old-client bypass rejection, disk-failure rollback

  and retry, offline/cross-name rejection, and authentication. Existing file-import

  regression fixtures now explicitly confirm before expecting a saved workspace.

- Two subprocess preflight tests exercise deploy/verify-helper.py with valid current

  envelopes (including zero labs), old helpers and malformed bundles. Only controlled

  version/status text is printed, never source contents or credentials.

- Browser on synthetic local SSH fixture: 12-node lab appeared Ready to import.

  Preview showed 12 nodes, 16 links and four exact source paths. Cancel followed by

  Refresh discovery left no saved workspace. Reopening and choosing Import lab saved

  the lab, inventory credentials and map; status was Running. No browser console errors.

  Screenshot: import-confirmation-1.10.0.png. No live device actions performed.

- New host-side start-manager.sh updates/installs the helper, verifies the expected

  version/file protocol before recreation, prepares persistent storage, builds and

  starts Compose. Existing key retained; existing account plus supplied key is

  rejected to prevent accidental rotation. Another running data-sharing manager is

  rejected. Scripts kept LF for Linux.

- Latest fetched origin/main 0c0182c matches the 1.9.1 source delivery except three

  ignore/attributes files restored here. ZIP and patches are verified against that

  revision, previous 1.9.1 delivery and original baseline 06b8624.

- No Linux shell, Docker engine or live VM was available here. Privileged setup,

  shell execution, actual image build/recreation and real deployment connectivity

  remain VM checks; preflight parser tests do not establish full installer success.

  No GitHub push or user-VM deployment was performed.



## Earlier 1.9.1 evidence (retained for context)



## 1.9.1 evidence



- Full Python suite: **103 tests, 98 passed, 5 skipped**. Existing platform/opt-in

  skips remain. New coverage includes missing Docker labels, standard generated

  folder lookup, grouped inspect output, absolute labPath, permission errors,

  sanitized diagnostics, automatic-import retry and old-helper upgrade feedback.

- Real local Paramiko server tests exercised direct inspection plus SFTP on the

  same authenticated connection: original YAML and generated inventory read,

  permission-denied definition, and unavailable SFTP. Discovery survives file

  failures and no unrelated files are opened.

- New imports retain valid YAML when optional exports/inventory are mismatched;

  tests verify foreign credentials are discarded. Existing explicit sync remains

  atomic and preserves the saved workspace on invalid optional files.

- JavaScript regressions: **14 passed**. Production script syntax checked.

- Browser: synthetic SSH helper using the production collector, with the screenshot's

  `/etc/containerlab/<name>/clab-<name>/` layout and a sanitized 12-node BGP fixture.

  Denied YAML access produced a detected lab; clicking it attempted automatic

  import and then opened the manual form with a retry button. File details showed

  the exact denied YAML path and three found companion files. Restoring fixture

  access and clicking retry imported 12 nodes, inventory credentials and 16 map

  links with zero unmatched nodes. No files were uploaded through the form.

  General Import a lab offered the detected name and automatic retry. Right-click

  PE1 showed SSH, backup and details. No browser console errors were observed.

  Screenshot: auto-import-1.9.1.png. No live NOS actions were invoked.

- GitHub origin/main at d84c76b matches delivered 1.9.0 except the three missing

  ignore/attributes files restored here. Source ZIP and patches are verified against

  that commit, the 1.9.0 delivery, and baseline 06b8624.

- This upgrade changes the installed VM helper; --update-helper retains the current

  account and authorized key. Docker image label and static asset versions are 1.9.1.

- Docker builds, privileged Linux provisioning, Linux openat protections and access

  to the user's actual VM remain untested here. No GitHub push or VM deployment.



## Earlier 1.9.0 evidence (retained for context)



## 1.9.0 evidence



- Full Python suite: 94 tests, 89 passed, 5 existing platform/integration skips.

  Eight new removal tests verify scoped state/history removal, retained backup

  files and other labs/host credentials, absence of remote command calls,

  persistent exclusions across restarts, explicit reimport, immediate rediscovery,

  removal during an in-flight poll, active-job and stale-name guards, failed-save

  rollback, authentication, and manual import clearing a matching exclusion.

- JavaScript regressions: 14 passed. All application JavaScript syntax checked.

- Browser with synthetic local data: Cancel retains the workspace; default removal

  leaves an excluded sidebar entry, and refreshing discovery does not recreate it.

  Import again creates a new 13-node Running workspace. Removing with exclusion

  unchecked and refreshing discovery also imports a fresh workspace successfully.

  No browser console errors were observed. Screenshot: remove-lab-1.9.0.png.

- Removal has no remote side effects and performs no filesystem deletion. Saved

  backup files and shared audit logs remain on disk; prior history entries and

  credential profiles are not restored when a new workspace is imported.

- Latest fetched GitHub commit 63ca6d6 contains the 1.8.0 delivery except for the

  three ignore/attributes files restored here. Source ZIP and patches verified

  against that commit, prior 1.8.0 delivery, and original 06b8624 baseline.

- No helper/key change is required from 1.8.0. Docker/Linux deployment remains

  untested here; no changes were pushed to GitHub or deployed to the user's VM.



## Earlier 1.8.0 validation (retained for context)



## 1.8.0 evidence



- Full Python suite: 86 tests, 81 passed, 5 skipped. Added 18 VM-file tests:

  automatic import; encrypted persistence and public/log secret exclusion;

  explicit sync preserving manual endpoints, credentials, profiles, identity,

  schedules and history; pending annotation changes; bad/mismatched/missing files;

  removed deployments; old helper compatibility; authentication/offline rejection;

  custom inventory ports; saved display-name map binding; real loopback SSH file

  transport; helper paths, custom generated directories, digests and size budgets.

- The additional skip is the helper's Linux openat/O_NOFOLLOW symlink test. The

  original four platform/integration skips remain as documented below.

- JavaScript regressions: 14 passed. Application JavaScript syntax checked.

- Browser: the production app received all four files over a local Paramiko SSH

  fixture, automatically created the 13-node BGP workspace, imported credentials

  and rendered 16 links with zero unmatched nodes. A changed annotation produced

  Updates available while retaining the map. Clicking Sync from VM changed the

  saved/rendered coordinate from x=320 to x=360 and returned Up to date. Restored

  original fixture geometry afterward. Right-click node actions remain available.

- Updated the restricted helper installation and added a key-preserving upgrade.

  Added docs/archive/FRESH-VM-GUIDE.md covering clean Ubuntu installation through deployment,

  connectivity, keys, persistence, first lab, backups and upgrades.

- Verified complete source archive and patches against Git baseline 06b8624 and

  the previously delivered 1.7.0 source archive, and GitHub commit 4742a90. The

  fetched GitHub 1.7.0 source matches that delivery except for three absent ignore/

  attributes files, restored here. No live state/keys included.



No Docker engine, Linux VM or WSL distribution is available in this workspace.

Docker image build, privileged installation, sudoers/SSH restrictions, Linux

openat protections and real vendor-node operations remain VM deployment checks.

The helper's portable file-collection branch was tested with temporary directories;

that is not evidence that Linux provisioning has run successfully.

No code was pushed to GitHub or deployed to the user's VM.



## Earlier 1.7.0 evidence (retained for context)



Repository: ArchRuger/CLAB-BACKUP-WORKER-v2. Git baseline: 06b8624 (1.6.0 upload).

This release includes the previously delivered 1.6.1 map corrections. No changes

were pushed to GitHub or deployed to the user's VM.



## Automated evidence



- Across the full suite and focused reruns: 68 Python tests covered, 64 passed,

  4 skipped. Discovery coverage includes 21 passing tests, three of which use

  real loopback SSH. Existing JavaScript behavior tests: 14 passed.

- All application JavaScript syntax checks passed.

- Compose YAML structure checked for host networking, persistent bind mount,

  create_host_path=false, and absence of Docker port publishing.

- CRLF-aware git diff whitespace check passed. Linux shell scripts retain LF endings.

- Full source ZIP and patches verified during packaging against the v2 baseline

  and the delivered 1.6.1 source ZIP, ignoring checkout line-ending differences.



Four existing skips: two Ansible control-node integrations require Linux; one

symlink check requires Windows privileges; one EOS fixture requires the opt-in

Ansible collections environment. No additional tests were skipped for discovery.



New coverage includes registration from YAML, default kinds and prefixes, exact

node matching, multiple active labs, discovery without registration, empty and

malformed inspect output, IPv6 addresses, partial/stopped/missing/stale conditions,

credential exclusion/encryption, restart invalidation, manual endpoint retention,

reimport identity/history preservation, renamed deployment linking, stale in-flight

result rejection, unavailable node-action blocking, and scheduled-backup resumption.



Three tests run a real Paramiko server on loopback: the fixed inspect command and

JSON response, rejection of a nonzero remote exit even with plausible JSON, and a

changed SSH fingerprint blocking command execution. Other tests simulate inspection

results. No live lab devices or actual host containerlab instance were contacted.



## Browser verification



Ran the production FastAPI app with disposable local state and a loopback SSH

server returning synthetic inspect JSON. The map uses sanitized copies of the

user's actual annotation/wiring geometry.



- Saved VM password credentials through the UI and tested discovery over SSH.

- Retested the same account with blank credential fields; retained credentials

  worked and the UI reported "VM connected. Lab discovery is active."

- Confirmed Running for the 13-node lab and Not deployed for a second saved lab.

- Confirmed a discovered but unregistered lab offers setup.

- Inspected the YAML/annotation import dialog and legacy inventory alternative;

  multipart YAML import/reimport behavior is covered through the real API tests.

- Saved a deployment link from the browser.

- Set PE1's address/port to a manual endpoint, refreshed discovery, and verified

  the override remained unchanged.

- Verified the existing topology view still shows 13 nodes, 16 links, zero unmatched.

- Adjusted sidebar scrolling so saved labs and discovery controls remain accessible.

- Captured the final standalone workspace screenshot in the release artifacts.



## Deployment limits



No Docker engine or Linux/WSL execution environment is available here. The image

was not built, host networking was not exercised on Linux, and privileged VM setup,

sudoers installation and migration scripts were not executed. Script contents and

Compose structure were reviewed; Linux provisioning is the remaining deployment

validation. No real NOS backup, SuperPuTTY import, or live host discovery was run.



Follow docs/STANDALONE-SETUP.md for a deployment test: preserve existing data, start one

standalone manager, configure the restricted account, import an edited lab YAML,

verify discovery through lab stop/redeploy, and test a real node SSH/backup. Verify

history and keys before removing the old worker. Discovery reports container state;

it does not prove that a virtual NOS has finished booting.



The source archive excludes raw uploads, preview state, tokens, private keys,

configuration captures, virtual environments and .build/. Only sanitized geometry

regression fixtures are included. Original uploaded YAML is encrypted at runtime

and omitted from public API responses.
