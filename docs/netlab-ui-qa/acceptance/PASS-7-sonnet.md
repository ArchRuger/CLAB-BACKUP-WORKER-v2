# Acceptance pass 7 — Sonnet (self-reported)

Independent, fresh-state acceptance pass on release 1.30.50 of the containerlab manager (netlab UI/UX
campaign + Restart device), test-suite revision `02fd181`. Model: Sonnet 5, self-reported by the model
itself (no external verification of the model identity was performed or is possible from inside the
session). Verification only: nothing was fixed, no tracked file was edited, and every finding below is
reported as found, not repaired.

Evidence, logs and this report's own working files are under `docs/netlab-ui-qa/acceptance/pass-7/`
(`PASS_DIR`); scripts under `PASS_DIR/tools/`.

## Build, tree and environment

| Check | Command | Result |
|---|---|---|
| Commit | `git rev-parse --short HEAD` | `02fd181` (confirmed) |
| Version | `cat clab-backup-ui/VERSION` | `1.30.50` (confirmed) |
| Tree | `git status --short` | three untracked `CLAB_*.md` root files, this pass's own untracked `docs/netlab-ui-qa/acceptance/pass-7/`; **no** tracked file modified before, during or after this pass (`docs/netlab-ui-qa/PICKUP.md` was not being edited during this run; `pass-3/` was not present in this checkout's listing at pass time either) |
| `git diff --check` | (working tree) | clean, no output, exit 0 |

Manager container (`docker ps`, checked 2026-09-28T01:09:05Z):

```
CONTAINER ID   IMAGE                 STATUS       NAMES
ea4604b1f576   clab-backup:1.30.50   Up 2 hours   containerlab-node-manager-backup-ui-1
```

Capture stack: `clab-manager-capture-sessions-1` runs `clab-capture-service:1.30.49` (unchanged code, per
the charter — not a finding); `clab-manager-capture-packetflix-1` and `clab-manager-capture-gostwire-1` up.
containerlab 0.79.0.

Pre-flight `/api/state` (`PASS_DIR/preflight-state.json`, 2026-09-28T01:09:13Z): lab id
`174386ec12ee496190c585c5796b2662`; all five devices of `restore-square` (ceos, cjunosevolved,
vjunos-switch, xrv9k, host1) read `nos_login.status == "ready"`; host1's `readiness` reads *Choose NOS* as
expected. No lab-operation was `running` in `/api/operations` at pre-flight or at any point this pass
polled it (checked again mid-run at 01:26 UTC: `running ops: []`).

## Steps

| # | Step | Command | UTC start | UTC end | Result | Evidence | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | verify-release | `python3 deploy/verify-release.py` | 01:09:16 | 01:09:16 | "Source release verified: 1.30.50" / "Documentation names only release 1.30.50." | `verify-release.log` | PASS |
| 1 | diff check | `git diff --check` | 01:09:20 | 01:09:20 | no output | `git-diff-check.log` | PASS |
| 1 | node --check | every `app/static/*.js` (22 files) | 01:09:25 | 01:09:26 | 0 failures | `node-check.log` | PASS |
| 1 | link check | `check_links.py` | 01:09:30 | 01:09:30 | "177 files, 0 problems" | `check_links.log` | PASS |
| 2 | Python unit suite | `unittest discover` (`clab-backup-ui/`) | 01:09:37 | 01:13:06 | Ran 1704 tests in 209.857s, OK (skipped=1) | `unittest-full.log` | PASS |
| 2 | Browser suite | `node --test tests/*.js` | 01:09:36 | 01:09:41 | tests 379, pass 379, fail 0 | `node-test-full.log` | PASS |
| 3 | Design tab browser walk | `check_design_ui.py --port 8180` | 01:10:16 | 01:10:24 | 29 of 29 checks passed; 0 console/page errors | `check_design_ui-report.md`, `check_design_ui.log` | PASS |
| 3 | QA-009 poll retry | `check_design_poll_retry.py --port 8181` | 01:10:30 | 01:11:24 | 9 checks, 0 failed | `check_design_poll_retry.log`, `poll-retry.json` | PASS |
| 3 | Stress race | `stress_design.py race --port 8182` | 01:11:41 | 01:17:35 | 80 checks: race-a leaks 0/20, race-b stale-wins 0/20, 0 unhandled console errors | `stress_race.log`, `race-results.json` | PASS |
| 3 | Stress bulk | `stress_design.py bulk --port 8182` | 01:17:55 | 01:18:43 | 43/43 checks, 24 generations run | `stress_bulk.log`, `bulk-results.json` | PASS |
| 3 | Coverage run | `coverage_run.py --port 8183` | 01:18:0x | 01:18:58 | 123 rows: 112 PASS, 8 BLOCKED, 3 NOT RUN, 0 FAIL; 0 rows differ from committed `coverage.json` (diffed programmatically, all 123 ids match) | `coverage_run.log`, `coverage-results.json` | PASS |
| 3 | Design probes | `design_probes.py --port 8184` | 01:19:5x | 01:20:59 | 55 checks; all 19 CONFIRMED-target checks FAIL (none PASS); the two named bug-describing checks (P1 "the loss is permanent", P3 "Generate was not blocked") also FAIL; total 21 FAIL, 34 PASS, no other unexpected failure | `design_probes.log` | PASS |
| 3 | Adversarial (own) — QA-002 More menu reasons | `PASS_DIR/tools/check_more_menu_reasons.py --port 8185` | 01:22:25 | 01:22:29 | 17/17 checks | `check_more_menu_reasons.log` | PASS |
| 4 | Traffic probe (background) | `traffic_probe.py --from cjunosevolved --crossing 10.255.0.1 --other 10.255.0.3 --minutes 8` | 01:22:35 | 01:30:38 | 73 samples; 4 loss windows, all attributable to the four ceos restarts below; 0 loss on the non-crossing path; 0 SSH failures | `ceos-traffic.jsonl` | PASS |
| 4 | cEOS restart (map/devices/stopped) | `check_restart_device.py --device ceos --devices --stopped --terminal --capture --links 3 --ready-budget 300` | 01:22:41 | 01:24:38 | 81 checks, 0 failed | `check_restart_device_ceos.log`, `ceos-2026-09-28T012241+0000.json` | PASS |
| 4 | Two tabs (host1) | `check_restart_two_tabs.py --device host1` | 01:24:53 | 01:25:10 | 13 checks, 0 failed | `check_restart_two_tabs.log`, `two-tabs-host1-2026-09-28T012453+0000.json` | PASS |
| 4 | Neighbour (ceos/host1, containerlab mode) | `check_restart_neighbour.py --stop-mode containerlab` | 01:25:17 | 01:26:12 | 20 checks, 0 failed | `check_restart_neighbour.log`, `neighbour-ceos-containerlab-20260928T012518+0000.json` | PASS |
| 4 | API previews + refusals | `curl` × 6 | 01:26:2x | 01:26:3x | see detail below | `api-previews.log` | PASS |
| 4 | XRv9k read-back (pre) | `nodecli.py xrv9k ...` | 01:27:05 | 01:27:09 | Loopback0 10.255.0.4/32; OSPF 2 neighbours FULL, up 51 min and 1 min (configuration A) | `xrv9k-readback-before.log` | PASS |
| 4 | XRv9k restart | `check_restart_device.py --device xrv9k --links 2 --ready-budget 1200` | 01:27:23 | 01:32:37 | 28 checks, 0 failed; readiness `booting` (01:28:03) → `ready` (01:32:32), no `failed` state | `check_restart_device_xrv9k.log`, `xrv9k-2026-09-28T012723+0000.json` | PASS |
| 4 | XRv9k read-back (post) | `nodecli.py xrv9k ...` | 01:32:46 | 01:33:27 | Loopback0 unchanged (10.255.0.4/32); OSPF 2 neighbours FULL, freshly up (~27–29 s), confirming reconvergence, not a config change | `xrv9k-readback-after.log` | PASS |
| 5 | Defect ledger spot check (10 entries) | see below | 01:18:05 | 01:18:09 (unit) + live steps above | all 10 confirmed | `ledger-tests.log` | PASS |

## Detail of the live runs

**cEOS full cycle** (`ceos-2026-09-28T012241+0000.json`, started 01:22:41, finished 01:24:38): three runs —
`map-running` (Restart device… from the map, Cancel proven inert, then confirmed; job succeeded, "3 links
restored", container kept its id with a new start time, other four containers' ids/start times untouched,
readiness went `Starting` → `Ready` with no false credentials failure, browser CLI showed the disconnect
and a clean reconnect with nothing replayed, a fresh capture resolved interfaces); `devices-running` (same
walk from the Devices tab/device panel, keyboard-reachable, panel stays open and returns focus); then
`map-stopped` (device stopped first with containerlab's own `stop --node`, review named the start/restore
path and the exited state, job restored all links, device came back Ready). 81 of 81 checks passed.

**Two tabs** (`two-tabs-host1-2026-09-28T012453+0000.json`): tab A's double-click created exactly one job
(`f00afc5429d747079405c4a8ddd52474`, "2 links restored", 01:24:57.96–01:25:01.00); tab B's older review
was refused with "Another lab operation ran after this review. Review the restart again." (not "Wait for
the current lab operation to finish."), dialog stayed open, no second job, no second restart; a fresh
review then worked; the simultaneous-confirm race also produced exactly one new job. `idle_before_start`
and `idle_waits` are both `[0.0, 0.0]` — the manager was already idle, so TOOL-004/TOOL-005's guarded waits
never had to wait, but the fields are present and recorded as the fix requires. 13 of 13 checks passed.

**Neighbour** (`neighbour-ceos-containerlab-20260928T012518+0000.json`, started 01:25:18, finished
01:26:12): host1 stopped with `containerlab stop --node` (parked links); the review named host1 as not
running and described both the parked and destroyed cases; the API preview carried the same warning;
ceos's restart job restored all 3 links (the parked one came back); ceos reached Ready; host1 was then
restarted through the product itself (start/restore path), got its own links back, and ceos's link count
was confirmed whole again. 20 of 20 checks passed.

**API previews and refusals** (`api-previews.log`):

| Target | Result |
|---|---|
| `clab-restore-square-vjunos-switch` preview | 200, `warnings` = the exact `RESTART_KNOWN_LIMITS['juniper_vjunosswitch']` string (byte-for-byte compared against `clab-backup-ui/app/lab_operations.py:130`) |
| `clab-restore-square-xrv9k` preview | 200, `warnings` = the exact `RESTART_KNOWN_LIMITS['cisco_xrv9k']` string |
| `clab-restore-square-ceos` preview | 200, `warnings: []` (no known-limit note) |
| Node of another lab (`clab-netlab-test-somenode` under the `restore-square` lab id) | 404 `{"detail":"This device is not in the lab."}` |
| Unknown node (`clab-restore-square-doesnotexist`) | 404 `{"detail":"This device is not in the lab."}` |
| Foreign `Origin: http://evil.example.com` | 403 `{"detail":"Use this manager from its own browser page."}` |

Operation-job count before and after the six requests: 170 → 170 (unchanged; no job was created by any
preview or refusal). No preview or refusal response carried a `token` field except the two accepted
previews, which is what a preview is for.

**XRv9k, the mandatory single restart** (`xrv9k-2026-09-28T012723+0000.json`, confirmed 01:27:29, job
`c3667a9a13ba410f88da9d4d20e8de67` succeeded 01:27:29–01:28:02, "2 links restored", same container id with
a new start time): readiness states recorded were exactly `[["2026-09-28T01:28:03+00:00","booting"],
["2026-09-28T01:32:32+00:00","ready"]]` — booting straight to ready, **no `failed` state** in between
(QA-19 confirmed; a separate live poll of `/api/state` independently observed
`nos_login.status` go `booting` at 01:32:20 → `ready` at 01:32:40, corroborating the tool's own record).
28 of 28 checks passed, matching this pass's expected "about 28 checks" figure.

Per this pass's stated expectation, this restart is a **later** restart of XRv9k since the 22:00 UTC
redeploy (the lab has been restarted three times before this run). Read-back before
(`xrv9k-readback-before.log`, 01:27:05): `interface Loopback0 … ipv4 address 10.255.0.4 255.255.255.255`,
`show ospf neighbor` FULL with 10.255.0.3 (up 51 min) and 10.255.0.1 (up 1 min). Read-back after
(`xrv9k-readback-after.log`): an immediate OSPF read at 01:32:51 (9 s after the job finished) showed no
neighbours yet (adjacencies had not reformed); a retry 36 s later at 01:33:27 showed `interface Loopback0 …
10.255.0.4 255.255.255.255` **unchanged** and both neighbours FULL again, freshly up (27–29 s), which is
consistent with reconvergence after the restart, not a configuration loss. **Configuration A survived this
later restart, as this pass's brief required; nothing was reapplied.** The XRv9k known limit (the product
cannot tell the first restart from later ones, so every restart's review carries the same fresh-disk
warning regardless of whether the disk is actually still fresh) is named in the review text captured in
the restart JSON's `reviews` field and in `RESTART_KNOWN_LIMITS['cisco_xrv9k']`.

One transient observed twice, both times self-recovering and outside any product code path under test: a
direct `nodecli.py xrv9k "show ospf neighbor"` call (independent SSH tool, not the manager) hit
`paramiko.ssh_exception.SSHException: Error reading SSH protocol banner` on its first connection attempt
before and after the restart, then the same process's next line of output shows a normal command result —
`nodecli.py` evidently retries internally. Recorded as an observation (see below), not a finding, since it
never affected a checked outcome.

## Traffic-probe loss windows

`ceos-traffic.jsonl`, 73 samples, 01:22:36–01:30:31 UTC. Crossing target 10.255.0.1 (through ceos); other
target 10.255.0.3 (via vjunos-switch, not crossing ceos).

| Window | Duration | Attributable to |
|---|---|---|
| 01:22:55–01:23:10 | ~15 s | cEOS restart, map entry point (confirmed 01:22:xx, job in `ceos-2026-09-28T012241+0000.json` `map-running`) |
| 01:23:29–01:23:44 | ~15 s | cEOS restart, Devices entry point (`devices-running`) |
| 01:23:57–01:24:27 | ~30 s (longer: includes the `stop --node` before the restart) | cEOS restart, stopped-device cycle (`map-stopped`) |
| 01:25:39–01:26:01 | ~22 s | cEOS restart inside the neighbour check (`neighbour-ceos-containerlab-...json`) |

`other_loss` was 0 in every one of the 73 samples (the non-crossing path was never affected, as expected);
`ssh_ok` was `true` in every sample (no probe-side SSH failure). All four windows align with a ceos restart
this pass itself ran; no unexplained loss window was observed.

## Defect ledger spot check

| ID | Regression test | Result | Live corroboration this pass |
|---|---|---|---|
| QA-017 | `test_lab_operations.py::test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note` | ok | XRv9k preview and restart review both carried the known-limit text; configuration A survived the (later) restart as expected |
| QA-018 | `test_lab_operations.py::test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links` | ok | `check_restart_neighbour.py` 20/20: review named host1, job reported the correct link counts in both directions |
| QA-019 | `test_node_readiness.py::test_a_refused_login_right_after_a_manager_restart_reads_booting_until_the_grace_window_closes`; `test_lab_operations.py::test_a_lab_wide_lifecycle_job_drops_every_device_login_proof_for_the_grace_window` | ok, ok | Both ceos (4×) and xrv9k (1×) restarts showed readiness go straight `Starting/booting` → `Ready/ready` with no false credentials failure |
| QA-020 | `test_lab_operations.py::test_a_stale_restart_review_hears_the_stale_reason_while_the_previous_job_still_refreshes` | ok | Two-tabs: stale review refused with "Another lab operation ran after this review. Review the restart again." (not the old "Wait…" wording) |
| TOOL-002 | (tool-side fix, no dedicated unit test) | — | Both restart runs' "exactly one `--node`" and "no false credentials failure / no `failed` between Starting and Ready" checks passed cleanly, which is exactly what TOOL-002 repaired |
| QA-014 | `test_lab_operations.py::test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason` | ok | Not exercised live this pass (vJunos-switch restart is forbidden by the hard rules; only a preview was taken, which correctly carried the known-limit warning) |
| QA-016 | `test_design_intent.py::test_engine_identifiers_follow_netlabs_16_character_rule` | ok | Exercised indirectly by `stress_design.py bulk`'s boundary checks (43/43) |
| U-08 | `test_shell_ui.js` "U-08: a menu that would open past the left edge anchors to its button instead, measured each time it opens" | ok (1 pass, 21 skipped by pattern filter, as expected) | Not separately re-driven live; the fixture-level `check_more_menu_reasons.py` adversarial check exercised the same More-menu machinery (a different item, QA-002) end to end without incident |
| RD-001 | `test_lab_operations.py::test_restart_device_binds_every_container_naming_shape_exactly`; `test_a_restart_device_review_is_stale_when_a_lifecycle_job_lands_during_its_own_helper_calls` | ok, ok | Not separately re-driven live; QA-020's live proof exercises the same staleness family |
| TOOL-004 | (tool-side fix, no dedicated unit test) | — | Two-tabs JSON carries `idle_before_start` and `idle_waits` fields (both `0.0` since the manager was already idle), confirming the tool records its idle waits and writes its JSON as the fix requires |

## Findings

None.

## Observations

1. `nodecli.py xrv9k "show ospf neighbor"` hit a transient `paramiko.ssh_exception.SSHException: Error
   reading SSH protocol banner` on its first connection both before (01:27:09) and after (01:32:51) the
   XRv9k restart, in both cases followed immediately by a normal, correct command result from the same
   invocation. This is the independent SSH tool retrying, not the manager; it never affected a checked
   outcome and is unrelated to any product code path under test. Worth the maintainer's eye only if it
   recurs more disruptively elsewhere.
2. No lab operation belonging to another lab was seen running in `/api/operations` at any point this pass
   polled it (pre-flight and again mid-run) — the maintainer's request to stay off the manager during this
   pass appears to have held.
3. host1's `runtime_status` read "Up 3 minutes" at this pass's pre-flight check (01:09:13), before this
   pass had restarted anything — evidence of a prior pass's or the lead's own use of host1 shortly before
   this run started. Not a breach by this pass and not a finding (host1 is explicitly a free-use device
   under the hard rules), recorded only because it was outside this pass's own actions.

## Not run or blocked

- vJunos-switch and cJunosEvolved were not restarted (forbidden by the hard rules); vJunos-switch got an
  API preview only, which is all the charter and hard rules permit.
- QA-014's fix was not independently re-driven live this pass beyond the vJunos-switch preview (a live
  restart of that device is forbidden), consistent with the hard rules; the unit regression test was run
  and passed.
- U-08 and RD-001 were not separately re-driven live this pass; their unit/browser regression tests were
  run and passed, and closely related live machinery (More-menu clicks for QA-002, the stale-review family
  for QA-020) was exercised without incident.

## Verdict: CLEAN

No finding contradicts a record or a criterion in this pass. Model: **Sonnet 5**, self-reported.
