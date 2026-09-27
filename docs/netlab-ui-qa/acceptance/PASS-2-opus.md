# Acceptance pass 2 (Opus): netlab UI/UX campaign and Restart device, release 1.30.48

The second of two independent clean acceptance passes on the final build. This pass checks the records. It fixes
nothing. I did not read the first pass's report or its folder. All evidence is in [`pass-2/`](pass-2/).

## Build, tree and environment

- **Tree.** The worktree is `~/projects/clab-manager-1.30.42`, branch `claude/netlab-integration`, HEAD `b4329d3`
  (release 1.30.48).
  - `git diff HEAD -- clab-backup-ui/app clab-backup-ui/tests deploy` has 0 lines, so the application, the tests and
    the deploy scripts are exactly the release commit.
  - The tree also carries uncommitted edits that someone else made to records and tooling while this pass ran:
    `DEFECTS.md`, `EVIDENCE.md`, `PICKUP.md`, `RESTART-PARITY.md`, `VALIDATION.md`, `probes-report.md`, 12
    `evidence/probes/*.png` and `tools/probes/design_probes.py`. I left them as they were.
- **Deployed product.**
  - Manager: `clab-backup:1.30.48` at `http://127.0.0.1:8081`. `/api/state` reports `version: 1.30.48`. I did not
    rebuild or restart it.
  - containerlab 0.79.0. Chromium 153.0.8010.12 (Playwright). System Node v18.19.1.
- **Lab `restore-square`.** It was deployed at 18:45 UTC. At the start of this pass (20:24:49 UTC) all five containers
  were running and every device read *Ready*.
  - XRv9k had been restarted once since the deploy, at 19:58:03.
  - Configuration A was present on every device. It was proven by an XRv9k read-back and by a clean traffic baseline.
- **Fixtures.**
  - Ports 8145–8149 only.
  - Every fixture had a fresh data directory under `<scratch>/acceptance-opus/`: `--data` where the tool takes it,
    and `TMPDIR` pointing into that folder for the tools that call `tempfile.mkdtemp()`.
  - Every fixture was stopped. At 20:43:12 ports 8145–8149 were free and no tool process was left.
- **Concurrency.**
  - The two fixture chains (A: design UI, poll retry, probes; B: stress race, stress bulk, coverage) ran in parallel.
    They also overlapped the live cEOS run.
  - The live steps ran strictly one after another, and no other `check_restart_*` process was running at any time.
  - The race pass still scored 80/80 under that load.
- **Files outside `pass-2/`.** Tool runs overwrote some records, and I put them back:
  - `evidence/probes/` from a byte-identical backup: the sha256 of the listing was `3992570d…` before and after.
  - `evidence/stress/`, `evidence/coverage/`, `coverage.json` and `COVERAGE.md` with `git checkout --`. They had no
    uncommitted edits before the runs.
  - No new untracked file was left anywhere outside `acceptance/`.

## Steps

All times are UTC on 2026-09-27. "Evidence" paths are relative to `docs/netlab-ui-qa/acceptance/pass-2/`, except
where marked.

| # | Command (from the worktree root unless noted) | When | Result | Evidence | Verdict |
|---|---|---|---|---|---|
| 1.1 | `python3 deploy/verify-release.py` | 20:22:42 | exit 0: "Source release verified: 1.30.48", "Documentation names only release 1.30.48." | `static-unit-regression.txt` | PASS |
| 1.2 | `git diff --check` | 20:22:42 | **exit 2**: `docs/netlab-ui-qa/probes-report.md:400: new blank line at EOF` (an uncommitted edit, mtime 20:17:40). Checked further: `git diff --check b4329d3~1 b4329d3` also exits 2 (`COVERAGE.md:296` blank line at EOF; `evidence/restart/ceos-1727-waits-for-interfaces.txt` lines 2–9 trailing whitespace) | `static-unit-regression.txt` | **FAIL** (F-1) |
| 1.3 | `node --check` on each `clab-backup-ui/app/static/*.js` | 20:22:42 | 22 files, 0 failures | `static-unit-regression.txt` | PASS |
| 1.4 | `python3 docs/maintenance-audit/tools/check_links.py` | 20:22:42 | "165 files, 0 problems", exit 0 | `static-unit-regression.txt` | PASS |
| 2.1 | (`clab-backup-ui/`) `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests` | 20:22:39–20:26:12 | **Ran 1701 tests in 211.9 s, OK (skipped=1)**, as expected | `static-unit-regression.txt` | PASS |
| 2.2 | (`clab-backup-ui/`) `node --test tests/*.js` | 20:26:30–20:26:31 | **tests 379, pass 379, fail 0** (22 files), as expected | `static-unit-regression.txt` | PASS |
| 3.1 | `docs/netlab-integration/tools/check_design_ui.py --port 8145 --shots <scratch> --report pass-2/check_design_ui-report.md` | 20:24:41–20:24:49 | 29/29; 0 console errors, 0 page errors. Includes the QA-001 word *Design saved, no plan yet* after Save | `check_design_ui-report.md` | PASS |
| 3.2 | `docs/netlab-ui-qa/tools/check_design_poll_retry.py --port 8146 --out …/pass-2` | 20:24:49–20:25:44 | 9/9. One injected 500 gave "(attempt 1 of 5) … Trying again…" and the plan still completed. Six failed polls gave *Plan progress unknown*, and the poll count stayed 7 → 7 for 15 s. Generate again reloads | `poll-retry.json`, `poll-retry-*.png` | PASS |
| 3.3 | `docs/netlab-ui-qa/tools/stress_design.py race --port 8147` | 20:24:43–20:31:08 | 80/80 checks; race-a leaks **0/20**, race-b stale-wins **0/20**, 0 unhandled console errors | `stress-race-results.json` | PASS |
| 3.4 | `docs/netlab-ui-qa/tools/stress_design.py bulk --port 8147` | 20:31:08–20:32:06 | 43/43; 24 generations, median 2.136 s, p95 2.158 s. A 17-character VRF name is refused at Save (400, "16 characters"); a 16-character one saves and generates | `stress-bulk-results.json` | PASS |
| 3.5 | `docs/netlab-ui-qa/tools/coverage_run.py --port 8148 --data <fresh>` | 20:32:06–20:33:13 (67 s, inside the 30 min limit) | 123 rows: **112 PASS, 8 BLOCKED, 3 NOT RUN, 0 FAIL**. The per-row results are identical to the committed record: no row differs, same ids | `coverage-results.json`, `coverage-ND-ERROR-006.png` | PASS |
| 3.6 | `docs/netlab-ui-qa/tools/probes/design_probes.py --port 8149 --data <fresh>` (the working-tree script) | 20:25:44–20:26:58 | 55 checks; **0 of 19 CONFIRMED-target checks passed** (all 19 fail as required). The 2 other failures are bug-describing checks that the fix makes false (P1 "the loss is permanent", P3 "Generate was not blocked"). Console: 1 error, the injected 500 | `probes-run-worktree-script.txt` | PASS |
| 3.6b | Extra: the same probes with the script as committed in `b4329d3` (`git show b4329d3:…/design_probes.py`, scratch root, port 8149) | 20:27:48–20:29:15 | 54 checks; **3 of 19 CONFIRMED-target checks PASS on the fixed build**: P7 "poll dies silently … still Generating 3 s after a 500", P8 "the edit is gone after reload", P8 "no message at all tells the student". The released probe tool cannot tell fixed from unfixed for QA-009 and QA-010 | `probes-run-committed-script.txt` | **FAIL** (F-3) |
| 3.7 | Own adversarial fixture check against QA-016 and QA-012: `pass-2/tools/adversarial_names.py 8145 <fresh> pass-2/adversarial-names.json` (API only, real engine) | 20:30:05–20:30:10 | 16/16, detailed below | `adversarial-names.json`, `tools/adversarial_names.py` | PASS |
| 4.1 | `docs/netlab-ui-qa/tools/traffic_probe.py --from cjunosevolved --crossing 10.255.0.1 --other 10.255.0.3 --minutes 8 --out …/pass-2/ceos-traffic.jsonl` (background) | 20:24:55–20:32:57 | 73 rows. Loss windows are in "Traffic probes" below | `ceos-traffic.jsonl` | PASS |
| 4.2 | `docs/netlab-ui-qa/tools/check_restart_device.py --url http://127.0.0.1:8081 --lab restore-square --device ceos --ready-budget 300 --devices --stopped --terminal --capture --links 3 --out …/pass-2` | 20:25:10–20:27:40 | **78/78**, detailed below | `ceos-2026-09-27T202511+0000.json`, `ceos-2025-*.png` | PASS |
| 4.3 | `docs/netlab-ui-qa/tools/check_restart_two_tabs.py --url http://127.0.0.1:8081 --lab restore-square --device host1 --out …/pass-2` | 20:28:16–20:28:34 | **13/13**, detailed below | `two-tabs-host1-2026-09-27T202816+0000.json`, `two-tabs-stale-review.png` | PASS |
| 4.4 | `docs/netlab-ui-qa/tools/check_restart_neighbour.py --url http://127.0.0.1:8081 --lab restore-square --device ceos --neighbour host1 --links 3 --neighbour-links 2 --ready-budget 300 --stop-mode containerlab --out …/pass-2` | 20:33:08–20:34:20 | **20/20**, detailed below | `neighbour-ceos-containerlab-20260927T203308+0000.json`, `neighbour-containerlab-ceos-2033-*.png` | PASS |
| 4.5 | API previews: `POST /api/operations/preview` `{"action":"restart-node","lab_id":"174386ec…","node":"clab-restore-square-vjunos-switch"}` and the same for `…-xrv9k` (headers `Content-Type: application/json`, `Origin: http://127.0.0.1:8081`), via `pass-2/tools/api_previews.py` | 20:35:41–20:35:44 | Both 200, each with its known-limit warning (texts below). A cEOS control preview carries neither note. The previews run the helper's preview mode only; no job was created (the count of operation jobs was the same before and after) | `api-previews-refusals.json` | PASS |
| 4.6 | API refusals, same route (11 cases plus a foreign Origin) | 20:35:41–20:35:44 | Every case gave 4xx and no token. The three required cases are among them. Full list below | `api-previews-refusals.json` | PASS |
| 4.7 | Extra: QA-013 read-only. *Capture traffic…* opened from the map on cjunosevolved, vjunos-switch and xrv9k, then closed without preparing (`pass-2/tools/capture_dialog_ports.py`) | 20:43:55–20:44:02 | 8/8. All three read "Connected interfaces" with no "not found on the VM": cjunosevolved `eth4 et-0/0/0`, `eth5 et-0/0/1`; vjunos-switch `eth1…eth3` = `ge-0/0/0…2`; xrv9k `eth1 Gi0/0/0/0`, `eth2 Gi0/0/0/1`. No job and no capture session were created | `capture-dialog-ports.json`, `capture-dialog-xrv9k.png` | PASS |
| 4.8a | XRv9k read-back before the restart: `clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/nodecli.py xrv9k "show running-config interface Loopback0" "show ospf neighbor"` | 20:36:01 | `interface Loopback0 / ipv4 address 10.255.0.4 255.255.255.255`; OSPF FULL with 10.255.0.3 (Gi0/0/0/0) and 10.255.0.1 (Gi0/0/0/1) | `xrv9k-readback.json` (sanitised; the raw transcript stays outside Git) | PASS |
| 4.8b | `docs/netlab-ui-qa/tools/check_restart_device.py --url http://127.0.0.1:8081 --lab restore-square --device xrv9k --links 2 --ready-budget 1200 --out …/pass-2` (map, the last live step) | 20:36:26–20:41:51 | **27/27**, detailed below. The review names the XRv9k known limit. See also F-2 | `xrv9k-2026-09-27T203626+0000.json`, `xrv9k-2036-*.png` | PASS (F-2 found in this run's own record) |
| 4.8c | XRv9k read-back after the restart (same command, then `"show ospf neighbor" "show ipv4 interface brief"`) | 20:41:59, 20:42:16 | **The configuration survived.** Loopback0 `10.255.0.4` is present. At 20:41:59 OSPF was EXSTART/INIT; at 20:42:16 it was FULL with both neighbours, and Loopback0, Gi0/0/0/0 `10.0.34.1` and Gi0/0/0/1 `10.0.41.0` were Up/Up. The configuration was not restored, because it did not need to be | `xrv9k-readback.json` | PASS |
| 4.8d | Extra: an independent traffic probe across XRv9k: `traffic_probe.py --from ceos --crossing 10.255.0.4 --other 10.255.0.2 --minutes 20 --out …/pass-2/xrv9k-traffic-from-ceos.jsonl`, stopped by hand after recovery | 20:36:15–20:43:01 | 79 rows. The crossing path was lost 20:36:33 → back 20:42:12. The other path had 0 % loss on all 79 rows | `xrv9k-traffic-from-ceos.jsonl` | PASS |
| 5.1 | Named regression tests on their own: `-k <name>` for five Python tests; `node --test --test-name-pattern=<name> tests/test_network_design_ui.js` for three patterns (list below) | 20:25:33–20:25:41 | 5 Python tests OK; 4 node tests pass (QA-001 #2, QA-006 #72, QA-015 #84–#85) | `static-unit-regression.txt` | PASS |
| 5.2 | Extra: mutation checks. Each fix was undone in a scratch copy of `app/` and `tests/`, and its test rerun | 20:26:03–20:26:18 | All 5 tests FAIL on the mutated copy (QA-014, QA-015, QA-016, QA-017, QA-018), so they guard the fixed behaviour | `static-unit-regression.txt` | PASS |
| 5.3 | `RESTART-PARITY.md` per-image claims against the JSON records it cites | 20:37–20:38 | The numbers of four claims match the records (below). The XRv9k row's state description is contradicted by the same record | this report | PASS for the figures; see F-2 |

## Detail of the live runs

**Scope of the proof.** These runs show that the checks pass on 1.30.48. They are independent evidence, not a replay
of the campaign's records:

- The container identity comes from `sudo docker inspect`.
- The configuration comes from `nodecli.py`, an independent SSH session.
- The traffic comes from `traffic_probe.py`.
- The review text comes from the page.

**cEOS (4.2), 78/78.** The container id `1f5d55773644` was kept through all three runs. The other four containers
kept their id, StartedAt and pid in every run.

| Run | Job | Message | StartedAt | Ready (fresh check) |
|---|---|---|---|---|
| Map | 20:25:19.9–20:25:24.0 | `Operation completed · 3 links restored` (3 `Restored link` lines) | 19:52:59 → 20:25:21 | 20:25:44 |
| Devices, keyboard | 20:25:56.9–20:26:03.7 | `3 links restored` | → 20:26:00 | 20:26:24 |
| After `containerlab stop --node ceos` | 20:27:11.5–20:27:14.5 | `3 links restored` | pid 0 → 3403082 | 20:27:34.8 |

- The same links came back every time (`eth1@if374 eth3@if380 eth2@if384`).
- The design (revision `c80a6c72…`, 9 generations), the Git binding and `last_deployed` were unchanged.
- The browser CLI showed *Disconnected*, offered Reconnect and replayed nothing.
- A capture resolved the interfaces after the restart.
- The review of the stopped device named the start/restore path and `exited`. No review carried a known-limit note.

**Two tabs (4.3), 13/13.**

- A double click created exactly **one** job (`b7c87512…`, `2 links restored`) and one restart: StartedAt
  19:53:26 → 20:28:21, same id.
- The older review in the other tab was refused with "Another lab operation ran after this review. Review the restart
  again." and kept its dialog open. No second job and no second restart followed.
- Two confirmations at the same moment gave **1** new job. The loser read "Wait for the current lab operation to
  finish.", and the winner's dialog closed.

**Neighbour down, parked case (4.4), 20/20.**

- host1 was stopped with `containerlab stop --node` and read `exited`.
- The review of ceos read: "host1 is not running. If it was stopped by the manager, the VS Code extension or
  containerlab stop, its link to ceos is parked and comes back with this restart. If it exited on its own or was
  stopped with docker stop, that link is gone: containerlab restores only 2 of 3 links and the job says so, and the
  device then waits for all its interfaces before it boots (cEOS gives up waiting after five minutes, a VM-based image
  waits for good) and stays at Starting until host1 runs again. Start host1 first …, or redeploy the lab." The API
  preview carried the same text.
- The job read `Operation completed · 3 links restored` (`links_expected` 3, `neighbours_down` `["host1"]`). ceos was
  *Ready* at 20:34:11.
- host1 was restarted through the product with `2 links restored`, and every link was present afterwards.

**Known-limit warnings (4.5), as the API returned them on 1.30.48 with every device running.**

- vJunos-switch: "Known limit of the vJunos-switch image: its container cannot be started a second time (the launcher
  renames its init.conf on the first start and fails without it), so this restart leaves the device stopped until you
  redeploy the lab. Proven on vjunos-switch 23.2R1.14 with containerlab 0.79.0."
- XRv9k: "Known limit of the XRv9k image: its launcher picks the VM disk by file name at every start, and after the
  first start a second copy of the pristine image sorts first, so the first restart after a deploy boots the device
  from a fresh disk: it comes back Ready with its factory configuration and everything configured since the deploy is
  gone (proven on cisco_xrv9k 24.3.1 with containerlab 0.79.0). Back up the configuration first and use Replace running
  configuration afterwards."
- The command the helper would run is exactly one `--node` with the topology name:
  `["/usr/bin/containerlab","restart","-t","/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml","--name","restore-square","--node","xrv9k"]`.
  The vjunos-switch and ceos previews differ only in the node name.

**Refusals (4.6).** Each case below returned no token.

| Case | Status | Message |
|---|---|---|
| Another lab's device `clab-netlab-test-ptx1` | 404 | "This device is not in the lab." |
| Made-up `clab-restore-square-nosuchdevice` | 404 | the same |
| The short name `ceos` | 404 | the same |
| `a,b` list | 404 | the same |
| `options: {"node":"ceos"}`, with or without a top-level node | 400 | "The device selector is resolved by the manager, not sent by the page." |
| `options: {"container":…}` | 400 | the same |
| Other options | 400 | "Restart device takes no options." |
| **`path` set** | 400 | "Restart device uses the lab's own topology file." |
| No node | 400 | "Choose the device to restart." |
| `node` on the lab-wide `restart` | 400 | "Only Restart device names a single device." |
| Foreign `Origin` | 403 | "Use this manager from its own browser page." |

**XRv9k (4.8), 27/27.**

- The review named the known limit, and Cancel changed nothing.
- The job ran 20:36:31.8–20:36:38.0 with `Operation completed · 2 links restored`. The id `520eaf6e1cff` was kept;
  StartedAt went 19:58:03 → 20:36:35 and the pid 3304739 → 3429890.
- The other four containers were untouched, and the links were the same (`eth1@if375`, `eth2@if383`).
- *Ready* came with a fresh check at 20:41:44.9, 5.1 min after the job ended.
- The design, its plans, the Git binding and the deployment time were untouched.
- The readiness timeline recorded by the tool (from `/api/state`, 3 s poll) was **booting 20:36:39 → failed 20:38:18 →
  booting 20:39:49 → ready 20:41:47**. See F-2.
- The disk listing in the container shows why the configuration survived. Before the restart the running boot used
  `clab-24.3.1-overlay.qcow2`, still being written at 20:36:07. The first deploy's overlay
  `xrv9k-fullk9-24.3.1-overlay.qcow2` had been abandoned since 19:57:58. After the restart the launcher chained a new
  `clab-24.3.1-overlay-overlay.qcow2` (being written, 20:42:04) on the previous boot's overlay. That matches QA-017's
  mechanism: only the first restart after a deploy boots a fresh disk.

**Final state (20:44:16).**

- Every device reads Ready.
- OSPF is FULL on all four edges of the square: cEOS sees 10.255.0.2 and 10.255.0.4; vJunos-switch sees 10.255.0.2 and
  10.255.0.4.
- XRv9k is still Up.

## Traffic probes

- **Across cEOS (4.1).** The probe ran from cJunosEvolved: the crossing path goes to cEOS lo `10.255.0.1`, the other
  path to vJunos-switch lo `10.255.0.3`. It sent 2 pings per round, with a round every 6–8 s.
  - Crossing path, map restart (job 20:25:19.9–20:25:24.0): 100 % loss from 20:25:21 to 20:25:36, 50 % at 20:25:44,
    0 % from 20:25:50. The loss window is about 23–29 s against *Ready* at 20:25:44.
  - Crossing path, Devices restart (job 20:25:56.9–20:26:03.7): 100 % from 20:25:57 to 20:26:19, 0 % at 20:26:27.
    The window is about 22–30 s.
  - Crossing path, stop and then restart: 100 % from 20:26:33 (the `containerlab stop` at about 20:26:30) to 20:27:03.
    The 4 rounds from 20:27:11 to 20:27:27 had no ping statistics, which I count as "not up". The path was at 0 % from
    20:27:33, with *Ready* at 20:27:34.8. The window is about 60 s, including the time the device was stopped.
  - From 20:27:33 to the end (20:32:51) the crossing path was at 0 %.
  - **The other path lost nothing: 0 % in all 73 rounds.** So only traffic through the restarted device was
    interrupted, and it recovered after each restart.
- **Across XRv9k (4.8d).** The probe ran from cEOS: the crossing path goes to XRv9k lo `10.255.0.4`, the other path to
  cJunosEvolved lo `10.255.0.2`. The crossing path was lost from 20:36:33 and recovered at 20:42:12, 27 s after
  *Ready*. The other path was at 0 % in all 79 rounds.

## Step 5 in detail

**Regression tests for seven entries** (QA-001, QA-006, QA-012, QA-014, QA-015, QA-016, QA-017, QA-018). Each named
test exists and passes on its own. Where a fix could be undone cheaply, the test fails without it, which is step 5.2.

| Entry | Test | What this pass saw of the behaviour itself |
|---|---|---|
| QA-001 | `designStateOf: a saved design with no plan yet is not "No design yet"` | *Design saved, no plan yet* after Save (3.1) |
| QA-006 | `P4: Generate with unsaved changes saves them first and says so; …` | Probe P4's CONFIRMED-target checks all fail (3.6). The generated plan used the unsaved AS, and the export did not use the old AS |
| QA-012 | `test_bgp_as_must_be_present_and_in_range` | AS 0, 4294967296, "65000" and true are all refused at the API naming `bgp.as`; 4294967295 is accepted and generates (3.7). The wording is in O-1 |
| QA-014 | `test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason` | The vJunos-switch review warning on 1.30.48 (4.5). The failed-job path itself is NOT RUN live here: restarting vJunos-switch is forbidden |
| QA-015 | `QA-015: two overlapping loads of one lab …` and `… lab-switch guard still holds …` | race-b stale-wins 0/20 (3.3) |
| QA-016 | `test_engine_identifiers_follow_netlabs_16_character_rule` | 17-character names refused at Save in five positions the unit test does not cover (3.7), and 16-character ones generate |
| QA-017 | `test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note` | The note in the page review and the API preview. The configuration survives a restart that is not the first one after a deploy (4.8) |
| QA-018 | `test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links` | The parked case live (4.4). The destroyed case is NOT RUN here: docker-stop mode is forbidden |

**`RESTART-PARITY.md` against the JSON records it cites.** I checked four claims. All figures match within the 3 s
poll granularity.

1. **cEOS row** (`ceos-2026-09-27T134146+0000.json`, manager 1.30.47): 66 checks, 0 failed.
   - Map job 13:41:52–13:41:53, `3 links restored`, id `e0c7880e10fb` kept, StartedAt 13:10:08 → 13:41:53, ready_at
     13:42:14.
   - Devices: StartedAt → 13:42:22, ready_at 13:42:42.99. The table says *Ready* 13:42:44, which is the poll time.
   - Stopped: pid 0 → 2179680, StartedAt → 13:43:24, ready_at 13:43:50.
   - The others were unchanged in all three runs. **Matches.**
2. **XRv9k row** (`xrv9k-2026-09-27T152910+0000.json`): 75 checks, 0 failed.
   - Map job 15:29:19–15:29:28 (9 s), `2 links restored`, id `423cb69b2f23`, pid 2553491 → 2609157, ready_at
     15:40:37 (11.2 min).
   - Devices job 15:40:52–15:40:58, ready 15:45:59.
   - Stopped job 15:46:44–15:46:47, ready 15:51:54.
   - **The figures match.** The row's "*Restarting*, then *Starting* from 15:29:29, *Ready* 15:40:37" omits the `failed`
     state from 15:34:31 to 15:39:00 that the same record holds (F-2).
3. **vJunos-switch rerun** (`vjunos-switch-2026-09-27T155300+0000.json`): 26 checks, 7 failed.
   - The job was `failed` 15:53:06–15:53:17 (11 s) with "containerlab restarted the device, but its container is exited
     (Exited (1) 2 seconds ago) right after starting. Known limit of the vJunos-switch image …".
   - The others were untouched, and the device ended *Unavailable*. **Matches.**
   - The claim that "the review carried the known limit" rests on `preview-warnings-1553.json`, an API preview taken
     when the device was already `exited`. The run record itself keeps no review text.
   - Both the record and the preview are from the 1.30.47 working tree. On 1.30.48 only the preview (4.5) is proven.
     The failed-job path was not run on the final build.
4. **XRv9k persistence proof** (`xrv9k-2026-09-27T171848+0000.json`, 1.30.48): 27/27.
   - Job 17:18:53–17:19:26, `2 links restored`, ready_at 17:24:27. **Matches.**
   - It holds a `failed` state from 17:21:07 to 17:23:38 as well (F-2).

## The adversarial fixture check (3.7), in detail

**The claim.** `NETWORK-DESIGN.md` and QA-016 say that every name the engine types as an identifier follows netlab's
16-character rule and is refused at Save, "so that a name the manager accepts never fails the plan later". QA-012 says
AS 0, a blank AS or an out-of-range AS is refused with the field named.

**Refused at Save (400).**

- 17-character names in five positions the unit test does not cover:
  - `routing.policy.<name>`
  - `routing.prefix.<name>`
  - `routing.static.<name>`
  - `nodes.r1.vlans.<name>`
  - an id-typed *value*: a static route's `vrf`
- Edge cases of the name rule itself:
  - a trailing newline, `"red\n"`. Python's `$` would match before it, and the key guard refuses it ("unreadable key").
  - a leading digit.
  - a hyphen.
- AS values `0`, `4294967296`, `"65000"` and `true`, each naming `bgp.as`.

**Positive control.** 16-character VRF, policy, prefix-list and static names, together with AS `4294967295`, saved
**and** generated ("Plan generated") with the real engine.

**Result.** 16/16. The claim holds. The wording of some refusals is in O-1.

## Findings

These are things that contradict the records or the pass's own criteria. Each one has a reproduction.

**F-1: `git diff --check` fails on the tree, and on the release commit itself. P3, repository hygiene; step 1.2.**

- Reproduce:
  - `git diff --check` gives `docs/netlab-ui-qa/probes-report.md:400: new blank line at EOF`. This is an uncommitted
    edit made at 20:17 UTC.
  - `git diff --check b4329d3~1 b4329d3` gives `docs/netlab-ui-qa/COVERAGE.md:296: new blank line at EOF`, and
    trailing whitespace on lines 2–9 of `docs/netlab-ui-qa/evidence/restart/ceos-1727-waits-for-interfaces.txt`.
- Why it matters: `CLAUDE.md` lists `git diff --check` among the static checks run before every handoff. The release
  commit was cut without passing it.

**F-2: XRv9k reads *Needs attention*, "SSH login failed with the saved credentials", in the middle of every restart.
P2 proposed: a misleading state that points to the wrong action during a recovery. Not recorded anywhere.**

- **What happens.** After a Restart device of XRv9k, `nodes[…xrv9k].nos_login.status` in `/api/state` goes
  `booting → failed → booting → ready`, not `booting → ready`.
- **In this pass.** The `failed` state lasted from 20:38:18 to 20:39:49 (`xrv9k-2026-09-27T203626+0000.json`,
  `runs.map-running.readiness.states`).
- **In the campaign's own records.** Every XRv9k restart shows the same pattern, eight runs in all:

  | Record | Run | `failed` window |
  |---|---|---|
  | `xrv9k-2026-09-27T152910+0000.json` | map | 15:34:31–15:39:00 |
  | same | devices | 15:42:38–15:45:10 |
  | same | stopped | 15:48:30–15:50:58 |
  | `xrv9k-2026-09-27T165016+0000.json` | map | 16:55:32–17:00:01 |
  | `xrv9k-2026-09-27T170416+0000.json` | map | 17:06:11–17:07:38 |
  | same | devices | 17:11:14–17:13:45 |
  | `xrv9k-2026-09-27T171848+0000.json` | map | 17:21:07–17:23:38 |

  No cEOS or cJunosEvolved record shows it.
- **What the student sees.** The UI maps this state in `status.js:102` to red *Needs attention*: "xrv9k is running, but
  SSH login failed with the saved credentials.", with *Check credentials*. The readiness message is "SSH login refused
  with the saved credentials. Assign a credential profile, then Test login." (`node_readiness.py:46`). So for 1.5–4.5
  minutes of every XRv9k restart the product tells the student that their credentials are wrong and to change them,
  while the device is simply still booting.
- **Where this comes from.** `node_readiness.py:297` maps `paramiko.AuthenticationException` to `failed`. XR's SSH
  server answers before its login works.
- **What it contradicts.**
  - `docs/LAB-OPERATIONS.md` (Restart device row): "the device reads *Restarting*, then *Starting* until it accepts a
    login again".
  - `clab-backup-ui/NODE-FEATURES.md:29`: the same words.
  - `RESTART-PARITY.md`, deliberate-differences table: "*Restarting*, then *Starting*, and *Ready* only when it answers
    `show version`".
  - `RESTART-PARITY.md`, the XRv9k per-image row.
- **Why the tools missed it.** The check "went back through Starting" passes once `booting` appears, whatever follows.
- **Scope of the evidence.** The UI text above is derived from the recorded API state and `status.js`. No screenshot was
  taken in that window. Whether the same happens after a deploy or redeploy was not tested; by the code path it would.

**F-3: the probe script committed in the release cannot tell the fixed build from the broken one for QA-009 and
QA-010. P3, evidence tooling; step 3.6b.**

- Reproduce: run `git show b4329d3:docs/netlab-ui-qa/tools/probes/design_probes.py` against a fresh fixture. Three
  CONFIRMED-target checks PASS on 1.30.48:
  - P7: the state label reads "Generating" 3 s after a 500. It always does; the retry notice is in `#design-detail`.
  - P8: "the edit is gone after reload". This is inherent.
  - P8: "no message at all tells the student".
- The working tree carries an uncommitted rewrite of exactly those checks (20:16 UTC). With it all 19 checks fail as
  required (3.6).
- The product is fixed: 3.2 (9/9) and the working-tree probe prove it. But the probe tool in `b4329d3`, and any record
  that cites a run of it, does not meet the rule that CONFIRMED-target checks must fail on the fixed build.

**F-4: two checks in the live tools cannot fail as written. P3, tooling.** I proved both claims another way, so no
product result depends on them.

- `check_restart_device.py`, "the command names exactly one --node". The code is `A and B or C` with
  `C = text.count('--node') >= 1`. In every review of this pass `A` was false, because the review's innerText has no
  `"--node"`: the argv is folded under *Technical details*. The check therefore passed on the prose
  "containerlab restart --node" alone, and it would pass with two `--node`. This pass proved the claim from the API
  preview's `argv` instead (4.5): exactly one `--node <topology node>`.
- The same tool's "went back through Starting" check does not look at what comes between `booting` and `ready` (F-2).

## Observations

These do not contradict a record, but they are worth the maintainer's eye.

- **O-1: wording of two refusals.** An id-typed *value* over 16 characters is refused with the generic "The value has
  the wrong type (expected id)", not the 16-character words that keys get. AS refusals read "The value has the wrong
  type (expected asn)": they name the field but not the 1–4294967295 range.
- **O-2: a dangling prefix-list reference is not caught.** A routing policy whose `match.prefix` names a prefix list
  that does not exist saves and generates ("Plan generated"). The documented reference checks cover devices, links,
  pools, VLANs and VRFs, so this is outside the claims.
- **O-3: hyphens are refused.** Hyphenated names are refused, although netlab's `must_be_id` accepts `[A-Za-z0-9_-]`.
  The manager is stricter than the engine, which is consistent with the documented rule.
- **O-4: U-06 keeps the exception name.** The apply review with no reachable device now has the summary line, the plain
  words, the reason under Apply and Cancel (`coverage-ND-ERROR-006.png`). The exception name ("Connectivity:
  NoValidConnectionsError") is still appended, by design (`designApplyReasonText`). The acknowledgement is still
  offered when nothing can be applied.
- **O-5: XRv9k Docker health.** 10 minutes after its restart, XRv9k's Docker health was `unhealthy` (healthcheck output
  "starting"), and the manager's discovery shows `runtime_status: 'unhealthy'` for a device it proves *Ready*. Before
  this pass's restart, 25 minutes after the previous one, it read `healthy`. This is image-level and was not followed
  up.
- **O-6: misleading probe check names.** In the working-tree probe script some non-target checks have names that
  describe the old bug, and they pass on the fixed build. For example P7 "no error/retry indication was ever shown",
  which looks only at `#design-state`. They are not product failures, but anyone reading the log may be misled.

## Not run or blocked

| Item | Status | Reason |
|---|---|---|
| vJunos-switch restart (QA-014's failed job on the final build 1.30.48) | NOT RUN | Forbidden by the pass's rules. The image cannot start twice. The warning is proven through the API preview (4.5), and the job logic by its unit test plus mutation (5.1, 5.2). The only live proof of the failed job is from the 1.30.47 working tree (15:53) |
| XRv9k first restart after a deploy (QA-017's configuration loss) on 1.30.48 | NOT RUN | It needs a redeploy, which is forbidden. This pass proved the note and the survival on a later restart |
| Neighbour destroyed-link case (`--stop-mode docker`, QA-018) | NOT RUN | Forbidden (`docker stop`) |
| XRv9k Devices entry point and stopped path in this pass | NOT RUN | The pass allows one XRv9k restart only |
| cJunosEvolved restart | NOT RUN | Not part of this pass. Its capture mapping was checked read-only (4.7) |
| Coverage rows ND-APPLY-007, -008, -012, -013, -014, -017, ND-ERROR-007, ND-PLAN-009 | BLOCKED (tool's classification) | They need a reachable device behind an apply review, and the fixture has no SSH endpoint |
| Coverage rows ND-APPLY-016, ND-GENERATE-005, ND-PLAN-004 | NOT RUN (tool's classification) | A concurrent manager job, or an allocation collision or renumbering that the fixture edits do not trigger |
| Firefox and WebKit | NOT RUN | Chromium only in this pass |

## Verdict: NOT CLEAN

- Step 1.2 `git diff --check` **FAILED** (F-1). It fails on the working tree and on the release commit `b4329d3`.
- Step 3.6b: the committed probe script has CONFIRMED-target checks that pass on the fixed build (F-3).
- F-2 contradicts `LAB-OPERATIONS.md`, `NODE-FEATURES.md` and `RESTART-PARITY.md`. Every XRv9k restart shows
  *Needs attention* / "SSH login failed with the saved credentials" for 1.5–4.5 minutes before *Ready*.
- F-4: two live-tool checks are vacuous. I proved their claims by other means.

Everything else passed:

- Unit suites: Python 1701 OK with 1 skipped; node 379/379.
- Fixture and browser runs: design UI 29/29, poll retry 9/9, race 80/80, bulk 43/43, coverage 112/8/3/0, probes 0 of 19
  targets passing, own adversarial check 16/16.
- Live runs: cEOS 78/78, two tabs 13/13, neighbour parked case 20/20, previews and refusals 20/20, capture mapping
  8/8, XRv9k 27/27 with the configuration surviving.
- Traffic: only paths through the restarted device lost packets, and they recovered each time.
- Every step that was not executed is listed above with its reason.
