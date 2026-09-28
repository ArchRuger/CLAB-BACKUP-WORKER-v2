# Acceptance pass 6 — Opus (self-reported)

The second of two independent clean-pass gates on release 1.30.50 of the containerlab manager: the netlab UI/UX
campaign and Restart device. I was asked to run as the Opus model. That identity is self-reported: nothing inside
the session can verify it. This pass only verified. It fixed nothing, edited no tracked file and wrote nothing
outside `docs/netlab-ui-qa/acceptance/pass-6/` (`PASS_DIR`), this report and `mktemp -d` scratch directories.
My own scripts are under `PASS_DIR/tools/`. Every time below is UTC on 2026-09-28.

## Build, tree and environment

| Check | Command | Result |
|---|---|---|
| Commit | `git rev-parse --short HEAD` (00:22:07) | `9aa25c3` |
| Release | `cat clab-backup-ui/VERSION` | `1.30.50` |
| Tree at start | `git status --short` | only the expected untracked files: three `CLAB_*.md`, `acceptance/PASS-5-sonnet.md` and `pass-5/` |
| Tree during the run | `git status --short` (00:35) | the lead's expected edits `M docs/netlab-ui-qa/DEFECTS.md`, `EVIDENCE.md` and `FINAL-REPORT.md`, plus `pass-6/`. After every restore step the tool evidence folders read clean |
| `git diff --check` | at 00:22:14 and again at the end | clean, exit 0 |
| Host tools | `node --version`, `nproc` | Node v18.19.1 on this host, 28 CPUs. Chromium 153.0.8010.12 (Playwright) |

Manager container (`docker ps`, 00:35:13, `PASS_DIR/environment.txt`):

```
ea4604b1f576   clab-backup:1.30.50   2026-09-27 23:18:08 +0000 UTC   Up About an hour   containerlab-node-manager-backup-ui-1
```

The capture session service still runs `clab-capture-service:1.30.49`, which the charter says is intentional.
`sudo containerlab inspect --all --format json` (read-only) listed the five `restore-square` containers as
`running`, on containerlab 0.79.0.

Pre-flight `/api/state` at 00:22:57 (`PASS_DIR/preflight.txt`) read manager 1.30.50 and lab id
`174386ec12ee496190c585c5796b2662`. All five devices had `nos_login.status == "ready"`: ceos, cjunosevolved,
vjunos-switch and xrv9k read *Ready*, and host1 read *Choose NOS*. The post-flight at 00:36 read the same
(`PASS_DIR/postflight.txt`).

## Steps

Each fixture tool ran on its own fresh `mktemp -d` data directory. Chain A (8170–8172) and chain B (8173, 8174)
ran in parallel through `PASS_DIR/tools/run_fixture_chain.sh`. That script refuses to run `coverage_run.py` if
`coverage.json` or `COVERAGE.md` are already modified, so it cannot throw away a lead edit.

| # | Step | Command | UTC start–end | Result | Evidence | Verdict |
|---|---|---|---|---|---|---|
| 1 | Release check | `python3 deploy/verify-release.py` | 00:22:14 | "Source release verified: 1.30.50" / "Documentation names only release 1.30.50." | `static.txt` | PASS |
| 1 | Diff check | `git diff --check` | 00:22:14 | no output, exit 0 | `static.txt` | PASS |
| 1 | JS syntax | `node --check` on each of the 22 `app/static/*.js` | 00:22:14 | 0 failures | `static.txt` | PASS |
| 1 | Links | `check_links.py` | 00:22:15 | "173 files, 0 problems" | `static.txt` | PASS |
| 2 | Python unit suite | `unittest discover -s tests -t tests` | 00:22:11–00:26:15 | Ran 1704 tests in 241.450s, OK (skipped=1) | `unit-python-tail.txt` | PASS |
| 2 | Browser suite | `node --test tests/*.js` | 00:22:19–00:22:20 | tests 379, pass 379, fail 0 | `unit-browser-tail.txt` | PASS |
| 3 | Design tab walk | `check_design_ui.py --port 8170 --shots <tmp> --report PASS_DIR/…` | 00:22:53–00:23:02 | 29 of 29, 0 console and 0 page errors | `check_design_ui-report.md`, `.log` | PASS |
| 3 | QA-009 poll retry | `check_design_poll_retry.py --port 8171 --out PASS_DIR` | 00:23:02–00:24:02 | 9 checks, 0 failed | `poll-retry.json`, `check_design_poll_retry.log`, `poll-retry-*.png` | PASS |
| 3 | Stress race | `stress_design.py race --port 8172` | 00:24:02–00:30:39 | 80 checks, 0 failed. race-a leaks 0/20, race-b stale-wins 0/20 | `stress/race-results.json`, `stress_race.log` | PASS |
| 3 | Stress bulk | `stress_design.py bulk --port 8172` | 00:30:39–00:31:36 | 43 of 43 | `stress/bulk-results.json`, `stress_bulk.log` | PASS |
| 3 | Stress restore | `git checkout -- docs/netlab-ui-qa/evidence/stress`, then status | 00:31:37 | clean | `stress-restore-status.txt` | PASS |
| 3 | Coverage run | `coverage_run.py --port 8173 --data <tmp>` | 00:22:53–00:24:07 | 123 rows: 112 PASS, 8 BLOCKED, 3 NOT RUN, 0 FAIL. **0 rows differ** from the committed `coverage.json` | `coverage-results.json`, `coverage-compare.txt`, `coverage_run.log` | PASS |
| 3 | Coverage restore | `git checkout -- evidence/coverage coverage.json COVERAGE.md`, then status | 00:24:07 | clean. The tool had left `coverage.json` and `COVERAGE.md` unchanged (empty diff) | `coverage-restore-status.txt`, `coverage-diffstat.txt` | PASS |
| 3 | Design probes | `design_probes.py --port 8174 --data <tmp>` | 00:24:07–00:25:23 | 55 checks, 34 pass and 21 FAIL. The 21 are exactly the expected ones: all **19 of 19 CONFIRMED-target checks FAIL**, plus P1 "the loss is permanent" and P3 "Generate was not blocked". No other check failed | `design_probes.log` | PASS |
| 3 | Probes restore | `git checkout -- docs/netlab-ui-qa/evidence/probes`, then status | 00:25:23 | clean | `probes-restore-status.txt` | PASS |
| 3 | Own adversarial check | `PASS_DIR/tools/adversarial_design.py --port 8175` | 00:33:16–00:33:36 | 15 of 15 | `adversarial-design.json`, `.log`, `adv-S*.png` | PASS |
| 4 | Traffic probe | `traffic_probe.py --from cjunosevolved --crossing 10.255.0.1 --other 10.255.0.3 --minutes 8` | 00:23:08–00:31:01 | 71 rounds, 0 SSH failures, 0 loss on the other path. The outages on the crossing path match the cEOS jobs (see below) | `ceos-traffic.jsonl`, `traffic-windows.txt` | PASS |
| 4 | cEOS full run | `check_restart_device.py --device ceos --ready-budget 300 --devices --stopped --terminal --capture --links 3` | 00:23:12–00:26:06 | 81 checks, 0 failed | `ceos-2026-09-28T002313+0000.json`, `restart-ceos.log`, `ceos-0023-*.png` | PASS |
| 4 | Two tabs, run 1 | `check_restart_two_tabs.py --device host1` | 00:26:32–00:26:57 | **crashed**: an unhandled Playwright `TimeoutError` in step 1 (tab B's review never opened), no JSON record written. See F-1 | `two-tabs-run1-crashed.log`, `external-operations.txt` | FAIL (tool) |
| 4 | Two tabs, run 2 | same | 00:27:32–00:27:50 | 13 checks, 0 failed. The stale review was refused with "Another lab operation ran after this review. Review the restart again." Idle waits 0.0 s and 0.0 s | `two-tabs-host1-2026-09-28T002732+0000.json`, `two-tabs.log` | PASS |
| 4 | Neighbour, containerlab mode | `check_restart_neighbour.py --device ceos --neighbour host1 --links 3 --neighbour-links 2 --stop-mode containerlab` | 00:28:11–00:29:08 | 20 checks, 0 failed | `neighbour-ceos-containerlab-20260928T002811+0000.json`, `neighbour.log` | PASS |
| 4 | Previews and refusals | `PASS_DIR/tools/previews_refusals.py` | 00:29:41–00:29:43 | 14 rows, 0 failed. Operation jobs 160 before and 160 after | `previews-refusals.json` | PASS |
| 4 | XRv9k read-back before | `nodecli.py xrv9k "show running-config interface Loopback0" "show ospf neighbor"` | 00:29:59 | Loopback0 `10.255.0.4 255.255.255.255`. OSPF FULL with 10.255.0.3 and 10.255.0.1 | `xrv9k-readback-before.txt` | PASS |
| 4 | XRv9k restart (the only one) | `check_restart_device.py --device xrv9k --links 2 --ready-budget 1200` | 00:30:05–00:35:17 | 28 checks, 0 failed. Readiness went `booting` (00:30:25) straight to `ready` (00:35:12), with no `failed` | `xrv9k-2026-09-28T003005+0000.json`, `restart-xrv9k.log` | PASS |
| 4 | XRv9k read-back after | `nodecli.py` ×3 | 00:35:23, 00:35:30, 00:35:4x | Configuration A survived: Loopback0 unchanged, Gi0/0/0/0 `10.0.34.1` and Gi0/0/0/1 `10.0.41.0` up, OSPF back to 2 × FULL | `xrv9k-readback-after-{1,2,3}.txt` | PASS |
| 5 | Ledger regression tests, run singly | see the ledger section | 00:33:52–00:34:00 | 12 of 12 selections pass | `ledger-tests.txt` | PASS |
| 5 | Mutation checks in a scratch copy | `PASS_DIR/tools/mutation_checks.py /tmp/tmp.DODLvBu25y` | 00:31:25–00:31:40 | 9 of 9 mutants killed. The TOOL-002 assertions hold, 8 of 8 synthetic cases | `mutation-checks.json` | PASS |

## Detail of the live runs

**cEOS** (`ceos-2026-09-28T002313+0000.json`, 81 of 81). The container id `0e70068d3675` was kept in all three
runs, and the other four containers kept their ids, start times and PIDs.

| Run | Job | Job times | Message | Links after | Readiness |
|---|---|---|---|---|---|
| Map, running | `7837e4c4` | 00:23:22–00:23:27 | `Operation completed · 3 links restored` | eth1, eth2, eth3 | booting 00:23:28, ready 00:23:49 |
| Devices panel by keyboard | `4a740772` | 00:24:01–00:24:05 | 3 links restored | eth1, eth2, eth3 | booting 00:24:06, ready 00:24:27 |
| Stopped with `containerlab stop --node` (00:24:32), then the map | `47edf234` | 00:25:35–00:25:39 | 3 links restored | eth1, eth2, eth3 | booting 00:25:40, ready 00:26:01 |

The terminal reconnect and the capture checks passed. Every review, the cancel path and the `--node` argv check
passed.

**Two tabs** (run 2). The double click created exactly one job (`442e4feb`, 00:27:37–00:27:40, `2 links restored`,
same container `8f8dbe30cad0`). Tab B's older review was refused with the QA-020 wording and nothing restarted a
second time. In the simultaneous race exactly one new job ran (`de9ec0ba`, 00:27:45–00:27:48), and the loser read
"Another lab operation ran after this review. Review the restart again."

**Neighbour** (containerlab mode). host1 was stopped with `containerlab stop --node` (00:28:13). The cEOS review and
the API preview both named host1 and both cases. The cEOS job `4c425331` (00:28:33–00:28:37) read `3 links
restored` and kept the container id. host1 started again through the product: job `22fbd748`, 00:28:59–00:29:02,
`2 links restored`.

**Previews and refusals** (`previews-refusals.json`). All requests used `Origin: http://127.0.0.1:8081` unless the
row says otherwise.

| Request | Status | Token | Check |
|---|---|---|---|
| Preview vjunos-switch | 200 | yes | carries `RESTART_KNOWN_LIMITS['juniper_vjunosswitch']` verbatim |
| Preview xrv9k | 200 | yes | carries `RESTART_KNOWN_LIMITS['cisco_xrv9k']` verbatim |
| Preview ceos | 200 | yes | carries no known-limit text |
| Node of another lab (`netlab-test`) | 404 | no | "This device is not in the lab." |
| restore-square node under another lab's id | 404 | no | same |
| Unknown node | 404 | no | same |
| Foreign `Origin: http://evil.example.com` | 403 | no | "Use this manager from its own browser page." |
| `Sec-Fetch-Site: cross-site` | 403 | no | same |
| Node `--all` | 404 | no | refused |
| Node `ceos,host1` | 404 | no | refused |
| Empty body | 413 | no | refused (see O-4) |
| Unknown lab id | 404 | no | "Lab not found." |
| `/api/operations/confirm` with a forged 32-hex token | 409 | no | "Review expired; preview the operation again." |

No preview was ever confirmed. The operation job count was 160 before and 160 after.

**XRv9k** (`xrv9k-2026-09-28T003005+0000.json`, 28 of 28). This was the device's third restart since the 22:00
redeploy. The review named the XRv9k known limit ("…the first restart after a deploy boots the device from a fresh
disk…"). Cancel started nothing. Job `0fd2ab68` ran 00:30:11–00:30:24 and read `2 links restored`. The container
kept its id `5706950aa8de` and got a new start at 00:30:22, and the other four containers were untouched.
Readiness was `[00:30:25 booting, 00:35:12 ready]`, with no `failed` between them (QA-019). The design, its plans,
the Git binding and the deployment time were untouched. At 00:35:23, 12 s after *Ready*, OSPF still listed no
neighbours. By 00:35:30 there was one FULL and one EXSTART, and by the third read both were FULL. Configuration A
survived the later restart, so nothing was reapplied.

## Traffic-probe loss windows (`traffic-windows.txt`)

The probe ran from cjunosevolved. The crossing target is 10.255.0.1 (cEOS). The other target is 10.255.0.3
(vJunos-switch), and it lost nothing in any of the 71 rounds.

| Outage on the crossing path | Rounds | Matching events |
|---|---|---|
| 00:23:22–00:23:38, clean again at 00:23:46 | 3 | Job `7837e4c4` 00:23:22–27, then cEOS booting until 00:23:49 |
| 00:24:00–00:26:00, clean again at 00:26:06 | 18 | Job `4a740772` 00:24:01–05. Ready at 00:24:27, then cEOS stopped at 00:24:32. Job `47edf234` 00:25:35–39, Ready at 00:26:01 |
| 00:28:37–00:28:44, clean again at 00:28:52 | 2 | Neighbour-check job `4c425331` 00:28:33–37 |

The 9 rounds from 00:25:12 to 00:26:00 were logged with `crossing_loss: null`, meaning ping gave no parsable answer
while cEOS was stopped. Counted as clean, they would shorten the second window (see O-3). No outage falls outside a
cEOS job or cEOS's stopped period. The XRv9k restart (00:30:11) is not on either probed path, and the probe saw
nothing there.

## Defect ledger spot check

Each named regression test was run alone from `clab-backup-ui/` (`ledger-tests.txt`). Each fix was also undone in a
scratch copy under `mktemp -d` (`/tmp/tmp.DODLvBu25y/clab-backup-ui`), never in the worktree, using the worktree's
`.venv` through `PATH`. The same test was then run pristine (it must pass) and mutated (it must fail), per
`mutation-checks.json`.

| Entry | Test run singly | Mutation (fix undone) | Mutant result | Observed live or in the fixture in this pass |
|---|---|---|---|---|
| **QA-020** | `test_a_stale_restart_review_hears_the_stale_reason_while_the_previous_job_still_refreshes`: OK | `self.guard()` moved back in front of the consent checks in `confirm()` | **FAILED**: killed | Two-tabs run 2: the stale review heard "Another lab operation ran after this review…" |
| **QA-019** | `test_a_refused_login_right_after_a_manager_restart_reads_booting_until_the_grace_window_closes` and `test_a_lab_wide_lifecycle_job_drops_every_device_login_proof_for_the_grace_window`: OK | grace-window condition replaced by `if False:` | **FAILED**: killed | XRv9k `booting → ready` with no `failed`. cEOS ×4 the same |
| **QA-017** | `test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note`: OK | `cisco_xrv9k` key removed from `RESTART_KNOWN_LIMITS` | **FAILED**: killed | The XRv9k review and preview carry the limit, and cEOS's carries none. The later restart kept configuration A, as the entry says |
| **QA-018** | `test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links`: OK | `restart_links()` never lists a neighbour that is down | **FAILED**: killed | Neighbour check 20 of 20: the review named host1 and both cases, and `3 links restored` |
| **TOOL-002** | no unit test. The tool's own assertions were fed synthetic inputs | `check_argv` given an exact argv, two `--node`, the wrong node, no `--node` and `destroy`. The failed-between expression given `booting, failed, booting, ready` | 8 of 8 behave as claimed | The cEOS and XRv9k records contain the argv and failed-between checks, and both passed on real data |
| QA-014 | `test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason`: OK | `settled_after_restart()` skipped | **FAILED**: killed | Not exercised live (vjunos-switch preview only, by rule). Its preview carries the limit |
| RD-001 | `test_a_restart_device_review_is_stale_when_a_lifecycle_job_lands_during_its_own_helper_calls`: OK | preview-time lifecycle refusal replaced by `pass` | **FAILED**: killed | Not directly observable live |
| QA-016 | `test_engine_identifiers_follow_netlabs_16_character_rule`: OK | `NAME` widened back to 64 characters | **FAILED**: killed | Stress bulk: a 17-character VRF was refused at save with the 16-character words, and a 16-character one generated |
| QA-012 | `test_bgp_as_must_be_present_and_in_range`: OK | `_check_bgp_as()` call removed | **FAILED**: killed | Probe P10's CONFIRMED-target checks (AS 0 coerced, blank prefix coerced) FAIL, meaning the bug is gone |
| QA-015 | `node --test --test-name-pattern="QA-015" tests/test_network_design_ui.js`: 2 pass | sequence guard removed from `designViewFresh` | **1 of 2 FAILS**: killed | Stress race-b: stale-wins 0/20 |
| U-01 and QA-001 (extra, not mutated) | "U-01…" 1 pass, "designStateOf: a saved design…" 1 pass | — | — | My adversarial S1 and S2 (below) |

No mutant survived.

### Own adversarial check (`PASS_DIR/tools/adversarial_design.py`, fixture on 8175, 15 of 15)

The check runs warm and returned sessions in an order the tools do not use:

- **S1 (U-01 class).** Lab B is saved first (OSPF area 0.0.0.7), then lab A with BGP AS 65123. With focus left in
  A's pool field, the browser goes Back to B. B's form shows B's values, not A's AS. An edit and Save in B stored
  area 0.0.0.8 and no BGP, and A was untouched.
- **S2 (abandoned draft, QA-010 and QA-001 class).** An unsaved AS 65124 in A was abandoned by switching to
  Topology and closing the page. A new page in the same browser context offered it as *Unsaved changes* with 65124,
  and it had never been saved. *Discard changes* restored 65123. After a reload the state read "Design saved, no
  plan yet", never "No design yet".
- **S3 (stale write across tabs).** Tab 1 held an unsaved AS 65111 while tab 2 saved 65200. Tab 1's Save was
  refused with a 409. The page said "Your unsaved changes were older than the saved design and were discarded.",
  and 65200 stayed.

The only console error was that handled 409.

## Findings

**F-1 (tooling). `check_restart_two_tabs.py` can still abort with no record, despite TOOL-004's "fixed".**
TOOL-004's disposition says "a stuck control is a failed check with the record kept". Only the steps after the
stale-review step are inside the `try`. Step 1 (`open_map_menu(b…).click(); review_open(b)`, tool line 85) is not.

In run 1 (00:26:32–00:26:57) tab B's review did not open within 20 s. The tool exited with an unhandled
`playwright._impl._errors.TimeoutError` and wrote no `two-tabs-*.json` (`two-tabs-run1-crashed.log`). At that
moment another client was destroying and deleting a different lab, `Quick-Test`, on the same manager: job
`7dc83b8f` 00:26:36–00:26:38, then job `2f29059b` 00:26:52–00:26:53 (`external-operations.txt`). The busy guard is
manager-wide: `guard()` in `lab_operations.py` line 280 checks `self.active or operation_busy(state)` without a lab
id. So the likely cause is that host1's preview was refused as busy while that operation ran. That is an inference:
the crashed run left no screenshot. No host1 job was created in run 1 (`traffic-windows.txt`, jobs list).

**Reproduction:** start the tool while any other lab operation on the manager is running or finishing its
follow-up refresh. The tool crashes in step 1 with no record. Run 2 (00:27:32), started when the manager was idle,
passed 13 of 13.

This is a tooling finding. The product refused correctly: nothing was restarted and no job was created.

## Observations

- **O-1 (environment).** The charter says the lead touches neither the lab nor the manager during the pass, but
  someone else operated the deployed manager during it. `Quick-Test` was published at 00:22:38, deployed
  00:22:44–00:23:09, destroyed 00:26:36–00:26:38 and deleted 00:26:52–00:26:53 (`external-operations.txt`). None of
  this pass's tools or commands did it. It overlapped the start of the cEOS run, which still passed 81 of 81, and it
  caused F-1. `restore-square` was not affected.
- **O-2 (known, OBS-005).** `design_probes.py` exited 0 with 21 FAIL lines, confirming OBS-005. Its only console
  error was the injected 500 of the fault injection.
- **O-3 (tooling).** While a target is unreachable (cEOS stopped), `traffic_probe.py` logs `crossing_loss: null`
  (`loss()` returns `None` when ping prints no statistics). A summary that treats `null` as clean under-reports the
  outage: here it would split one 00:24:00–00:26:00 outage into a window ending at 00:25:04.
- **O-4.** A zero-length POST to `/api/operations/preview` is refused with 413 and "Upload limit is 2.5 MB per
  request; content length is required." The refusal is by design (CLAUDE.md), but the wording is about upload size,
  not a missing body.
- **O-5 (tool output hygiene).** Every JSON record these tools wrote lacked a final newline, and
  `design_probes.py` and `coverage_run.py` print lines with trailing whitespace. This pass's copies in `PASS_DIR`
  were normalised: LF, no trailing whitespace, one final newline. The JSON still parses.
- **O-6.** The charter says `coverage_run.py` rewrites `coverage.json` and `COVERAGE.md`. This run left both
  unchanged (empty `git diff --stat`) and rewrote only `evidence/coverage/`. The restore was still run.
- **O-7.** The host has Node v18.19.1, and the browser suite passed 379 of 379 on it. The Node 24 requirement
  applies only to the lab-builder build, which this pass did not run.
- **O-8.** The manager reported XRv9k *Ready* (00:35:12) before OSPF re-converged (FULL by about 00:35:40). That
  matches the documented meaning of readiness (an SSH login proof) and is recorded only for the student-facing
  expectation.

## Not run or blocked

- The coverage run's own 8 BLOCKED and 3 NOT RUN rows are the same as the committed `coverage.json` (the apply
  rows need real devices behind the fixture).
- By rule: no restart of vjunos-switch or cjunosevolved, no `--stop-mode docker`, no confirmation of the vJunos or
  XRv9k previews beyond the one allowed XRv9k restart.
- QA-014 and RD-001 were checked by unit test and mutation only, not live.
- No reapply of configuration A: none was needed.

## Verdict: NOT CLEAN

There is one finding, F-1: a tooling defect in `check_restart_two_tabs.py`, whose step 1 is not covered by the
TOOL-004 guard. Every product check in this pass passed. Static and unit suites were green, the fixture tools
matched the reference figures exactly, cEOS was 81 of 81, two-tabs 13 of 13 on the rerun, neighbour 20 of 20,
previews and refusals 14 of 14, XRv9k 28 of 28 with `booting → ready` and configuration A surviving, and all
9 mutants were killed.
