# Acceptance pass 8 — Opus (self-reported)

The second of two independent clean-pass gates on release 1.30.50 of the containerlab manager (test-suite
revision `02fd181`): the netlab UI/UX campaign and Restart device. I was asked to run as the Opus model; that
identity is self-reported and nothing inside the session can verify it. This pass only verified: it fixed nothing,
edited no tracked file and wrote nothing outside `docs/netlab-ui-qa/acceptance/pass-8/` (`PASS_DIR`), this report and
`mktemp -d` scratch directories. My own scripts are under `PASS_DIR/tools/`. Every time below is UTC on 2026-09-28.

**Verdict: NOT CLEAN** — one product finding (F-1, a wrong-lab *Remove design*), every other check passed.

## Build, tree and environment

| Check | Command | Result |
|---|---|---|
| Commit | `git rev-parse --short HEAD` (01:36:44) | `02fd181` |
| Release | `cat clab-backup-ui/VERSION` | `1.30.50` |
| Tree at start | `git status --short` | only the expected untracked files: three `CLAB_*.md`, `acceptance/PASS-7-sonnet.md`, `pass-7/` |
| Tree during and after the run | `git status --short` (01:51) | the lead's expected edits `M docs/netlab-ui-qa/EVIDENCE.md` and `FINAL-REPORT.md`, plus `pass-8/`. The tool evidence folders read clean after every restore |
| `git diff --check` | 01:36:48 and 01:51 | clean, exit 0 |
| Host tools | `node --version`, `nproc` | Node v18.19.1, 28 CPUs, Chromium 153.0.8010.12 (Playwright), containerlab 0.79.0 |

Manager container (`docker ps`, 01:37:28, `PASS_DIR/environment.txt`):

```
ea4604b1f576   clab-backup:1.30.50   2026-09-27 23:18:08 +0000 UTC   Up 2 hours   containerlab-node-manager-backup-ui-1
```

The capture session service runs `clab-capture-service:1.30.49` (intentional per the charter). `sudo containerlab
inspect --all --format json` listed the five `restore-square` containers as `running`.

Pre-flight `/api/state` at 01:37:18 (`preflight.txt`): manager 1.30.50, lab id `174386ec12ee496190c585c5796b2662`,
all five devices `nos_login.status == "ready"` (host1 reads *Choose NOS*), no queued or running operation. Post-flight
at 01:51:53 (`postflight.txt`): the same, and the 12 operation jobs created during the pass are all mine and all on
`restore-square` (see the live detail); **no operation ran on another lab** during the pass.

## Steps

Fixture tools ran in two parallel chains through `PASS_DIR/tools/run_fixture_chain.sh`, each tool on its own fresh
`mktemp -d` data directory (chain A: 8190–8192; chain B: 8193, 8194). The chain refuses to run `coverage_run.py` if
`coverage.json` or `COVERAGE.md` are already modified, so it cannot discard a lead edit. My own checks used 8195, 8196.

| # | Step | Command | UTC start–end | Result | Evidence | Verdict |
|---|---|---|---|---|---|---|
| 1 | Release check | `python3 deploy/verify-release.py` | 01:36:48 | "Source release verified: 1.30.50" / "Documentation names only release 1.30.50." | `static.txt` | PASS |
| 1 | Diff check | `git diff --check` | 01:36:48 | no output, exit 0 | `static.txt` | PASS |
| 1 | JS syntax | `node --check` on each of the 22 `app/static/*.js` | 01:36:49 | 0 failures | `static.txt` | PASS |
| 1 | Links | `check_links.py` | 01:36:50 | "177 files, 0 problems" | `static.txt` | PASS |
| 2 | Python unit suite | `unittest discover -s tests -t tests` | 01:36:53–01:40:29 | Ran 1704 tests in 214.880s, OK (skipped=1) | `unit-python-tail.txt` | PASS |
| 2 | Browser suite | `node --test tests/*.js` | 01:36:56 | tests 379, pass 379, fail 0 | `unit-browser-tail.txt` | PASS |
| 3 | Design tab walk | `check_design_ui.py --port 8190 --shots <tmp> --report PASS_DIR/…` | 01:37:15–01:37:23 | 29 of 29, 0 console and 0 page errors | `check_design_ui-report.md`, `.log` | PASS |
| 3 | QA-009 poll retry | `check_design_poll_retry.py --port 8191 --out PASS_DIR` | 01:37:23–01:38:20 | 9 checks, 0 failed | `poll-retry.json`, `check_design_poll_retry.log`, `poll-retry-*.png` | PASS |
| 3 | Stress race | `stress_design.py race --port 8192` | 01:38:20–01:44:25 | 80 checks, 0 failed; race-a leaks 0/20, race-b stale-wins 0/20 | `stress/race-results.json`, `stress_race.log` | PASS |
| 3 | Stress bulk | `stress_design.py bulk --port 8192` | 01:44:25–01:45:23 | 43 of 43, 24 generations | `stress/bulk-results.json`, `stress_bulk.log` | PASS |
| 3 | Stress restore | `git checkout -- docs/netlab-ui-qa/evidence/stress`, status | 01:45:23 | clean | `stress-restore-status.txt` | PASS |
| 3 | Coverage run | `coverage_run.py --port 8193 --data <tmp>` | 01:37:16–01:38:23 | 123 rows: 112 PASS, 8 BLOCKED, 3 NOT RUN, 0 FAIL; **0 rows differ** from the committed `coverage.json` | `coverage-results.json`, `coverage-compare.txt`, `coverage_run.log` | PASS |
| 3 | Coverage restore | `git checkout -- evidence/coverage coverage.json COVERAGE.md`, status | 01:38:23 | clean; the tool had left `coverage.json` and `COVERAGE.md` unchanged | `coverage-restore-status.txt`, `coverage-diffstat.txt` | PASS |
| 3 | Design probes | `design_probes.py --port 8194 --data <tmp>` | 01:38:23–01:39:36 | 55 checks, 34 PASS, 21 FAIL: **all 19 CONFIRMED-target checks FAIL** (none passes), plus P1 "the loss is permanent" and P3 "Generate was not blocked"; no other check failed | `design_probes.log` | PASS |
| 3 | Probes restore | `git checkout -- docs/netlab-ui-qa/evidence/probes`, status | 01:39:36 | clean | `probes-restore-status.txt` | PASS |
| 3 | Own adversarial check | `PASS_DIR/tools/adversarial_transitions.py --port 8196` (trial run on 8195 at 01:39:56 gave the same result) | 01:48:07–01:48:32 | 13 checks, **2 failed: F-1** | `adversarial-transitions.json`, `.log`, `adv8-*.png` | **FAIL (F-1)** |
| 4 | Traffic probe | `traffic_probe.py --from cjunosevolved --crossing 10.255.0.1 --other 10.255.0.3 --minutes 8` | 01:37:31–01:45:36 | 73 rounds, 0 SSH failures, 0 loss on the other path; four outage windows on the crossing path, each on a cEOS event | `ceos-traffic.jsonl`, `traffic-windows.txt` | PASS |
| 4 | cEOS full run | `check_restart_device.py --device ceos --ready-budget 300 --devices --stopped --terminal --capture --links 3` | 01:37:54–01:40:55 | 81 checks, 0 failed | `ceos-2026-09-28T013754+0000.json`, `restart-ceos.log`, `ceos-summary.txt`, `ceos-0137-*.png` | PASS |
| 4 | Two tabs | `check_restart_two_tabs.py --device host1` | 01:41:16–01:41:34 | 13 checks, 0 failed; idle waits 0.0 s before the start and 0.0/0.0 s later | `two-tabs-host1-2026-09-28T014116+0000.json`, `two-tabs.log` | PASS |
| 4 | Neighbour, containerlab mode | `check_restart_neighbour.py --device ceos --neighbour host1 --links 3 --neighbour-links 2 --stop-mode containerlab` | 01:41:38–01:42:29 | 20 checks, 0 failed | `neighbour-ceos-containerlab-20260928T014138+0000.json`, `neighbour.log` | PASS |
| 4 | Previews and refusals | `PASS_DIR/tools/previews_refusals.py` | 01:42:52–01:42:55 | 18 checks, 0 failed; operation jobs 178 before and 178 after | `previews-refusals.json`, `.log` | PASS |
| 4 | Own live adversarial check | `PASS_DIR/tools/live_transitions.py` | 01:44:14–01:44:38 | 11 checks, 0 failed (a first run at 01:43:40 had a bug in my script, see O-6) | `live-transitions.json`, `.log`, `live-L1-*.png` | PASS |
| 4 | XRv9k read-back before | `nodecli.py xrv9k "show running-config interface Loopback0" "show ospf neighbor"` | 01:44:45 | Loopback0 `10.255.0.4 255.255.255.255`; OSPF FULL with 10.255.0.3 and 10.255.0.1 | `xrv9k-readback-before.txt` | PASS |
| 4 | XRv9k restart (the only one) | `check_restart_device.py --device xrv9k --links 2 --ready-budget 1200` | 01:45:44–01:50:48 | 28 checks, 0 failed; readiness `booting` 01:46:02 → `ready` 01:50:43, no `failed` | `xrv9k-2026-09-28T014545+0000.json`, `restart-xrv9k.log`, `xrv9k-summary.txt` | PASS |
| 4 | XRv9k read-back after | `nodecli.py` ×2 | 01:50:53, 01:51:40 | configuration A survived: Loopback0 unchanged; `router ospf 1` intact; OSPF back to 2 × FULL at 01:51:40 (none yet at 01:50:54, O-4) | `xrv9k-readback-after.txt`, `xrv9k-readback-after-2.txt` | PASS |
| 5 | Ledger regression tests, run singly | see the ledger section | 01:47:42–01:48 | 12 of 12 selections pass | `ledger-tests.txt` | PASS |
| 5 | Mutation checks in a scratch copy | `PASS_DIR/tools/mutation_checks.py /tmp/tmp.FZ2hgQ6TP4 …` | 01:47:20–01:47:32 | 10 of 10 mutants killed, each test passing again once restored; TOOL-002 assertions 10 of 10 synthetic cases as expected | `mutation-checks.json`, `.log` | PASS |

## Detail of the live runs

**cEOS** (`ceos-2026-09-28T013754+0000.json`, 81 of 81). The container id `0e70068d3675` was kept in all three runs,
and the other four containers kept their ids, start times and PIDs in each.

| Run | Job | Job times | Message | Links after | Readiness |
|---|---|---|---|---|---|
| Map, running | `64a7b222` | 01:38:03–01:38:07 | `Operation completed · 3 links restored` | eth1, eth2, eth3 | booting 01:38:08, ready 01:38:29 |
| Devices panel by keyboard | `99775c34` | 01:38:40–01:39:03 | 3 links restored (containerlab spent 21 s before restoring the links, O-2) | eth1, eth2, eth3 | booting 01:39:03, ready 01:39:24 |
| Stopped with `containerlab stop --node` (01:39:29), then the map | `4203d3d9` | 01:40:26–01:40:29 | 3 links restored | eth1, eth2, eth3 | booting 01:40:29, ready 01:40:51 |

Every review named the lab (`restore-square`), the topology file and "Only ceos in restore-square restarts"; the
stopped case named the start/restore path. The terminal reconnect and capture checks passed; no cEOS review carried
a known-limit note.

**Two tabs.** The double click created exactly one job (`68876799`, 01:41:21–01:41:24, `2 links restored`, container
`8f8dbe30cad0` kept). Tab B's older review was refused with "Another lab operation ran after this review. Review the
restart again." (the QA-020 wording), with no second job and no second restart. In the simultaneous race exactly one
job ran (`ad126e5d`, 01:41:30–01:41:33); the loser read the stale-review refusal and kept its dialog open.

**Neighbour** (containerlab mode). host1 stopped with `containerlab stop --node` (01:41:40). The review and the API
preview named host1 and both cases; the cEOS job `f90b88a6` (01:41:54–01:41:58, `links_expected 3`,
`neighbours_down ["host1"]`) read `3 links restored`, container kept, all three links present. host1 started again
through the product: job `b0232da9`, 01:42:21–01:42:24, `2 links restored`.

**Previews and refusals** (`previews-refusals.json`; every request with `Origin: http://127.0.0.1:8081` unless noted).
The known-limit texts were compared verbatim with `RESTART_KNOWN_LIMITS` parsed (ast) from the worktree's
`lab_operations.py`.

| Request | Status | Token | Check |
|---|---|---|---|
| Preview vjunos-switch | 200 | yes | carries `RESTART_KNOWN_LIMITS['juniper_vjunosswitch']` verbatim |
| Preview xrv9k | 200 | yes | carries `RESTART_KNOWN_LIMITS['cisco_xrv9k']` verbatim |
| Preview ceos, preview host1 | 200 | yes | no known-limit text |
| Node of another lab (`clab-netlab-test-host1`) | 404 | no | "This device is not in the lab." |
| restore-square host1 under netlab-test's id | 404 | no | same |
| Unknown node | 404 | no | same |
| Foreign `Origin: http://evil.example.com` | 403 | no | "Use this manager from its own browser page." |
| `Sec-Fetch-Site: cross-site` | 403 | no | same |
| Node with a trailing space; node `../clab-restore-square-host1` | 404 | no | refused |
| `options: {node: cjunosevolved}` smuggled in | 400 | no | "The device selector is resolved by the manager, not sent by the page." |
| `path` given | 400 | no | "Restart device uses the lab's own topology file." |
| No node | 400 | no | "Choose the device to restart." |
| `/api/operations/confirm` with a forged 32-hex token | 409 | no | "Review expired; preview the operation again." |

No preview of vjunos-switch, xrv9k or ceos was ever confirmed. Operation jobs: 178 before, 178 after.

**My live adversarial transitions** (`live_transitions.py`, 11 of 11; only host1 was restarted):

- L1: a Restart review for host1 of `restore-square`, then browser Back to `Quick-Test` (which also has a host1). The
  review **stays open over the other lab** (O-1), but it names `restore-square`, its topology path and "Only host1 in
  restore-square restarts"; confirmed, exactly `restore-square`'s host1 restarted (job `c0867408`, 01:44:21–01:44:24),
  no other container changed.
- L4: a review closed together with its tab starts nothing.
- L2: an API review of ceos, then a host1 restart of the same lab through the API (job `c6c9be78`, 01:44:31–01:44:34):
  the older ceos review is refused 409 "Another lab operation ran after this review. Review the restart again." and
  ceos kept its start time (cross-device staleness holds).
- L3: the used host1 token confirmed again: refused (4xx), no second job.

**XRv9k** (`xrv9k-2026-09-28T014545+0000.json`, 28 of 28). A later restart (the fifth since the 22:00 redeploy). The
review named the XRv9k known limit ("…the first restart after a deploy boots the device from a fresh disk…"; check
"the review names the known limit of this image before the student confirms" passed). Cancel started nothing and left
the container untouched. Job `f6bb4236` ran 01:45:51–01:46:01, `2 links restored`; container `5706950aa8de` kept, new
start 01:45:59, the other four containers untouched; links eth1, eth2 back. Readiness `[01:46:02 booting, 01:50:43
ready]`, no `failed` between them (QA-019; the tool's "no false credentials failure between Starting and Ready"
passed). The design, plans, Git binding and deployment time were untouched. Configuration A survived (read-back
above): **no loss, nothing reapplied**.

## Traffic probe loss windows

`traffic-windows.txt`. From cJunosEvolved, 73 rounds 01:37:31–01:45:30, 0 SSH failures; the other path (10.255.0.3)
never lost a packet. A round counts as an outage when loss > 0 or the ping printed no loss line (no route).

| Outage on 10.255.0.1 (via cEOS) | cEOS event |
|---|---|
| 01:38:04–01:38:19 | map restart `64a7b222` 01:38:03–01:38:07, Ready 01:38:29 |
| 01:38:39–01:39:17 | Devices-panel restart `99775c34` 01:38:40–01:39:03, Ready 01:39:24 |
| 01:39:31–01:40:48 (no route 01:40:16–01:40:43) | `containerlab stop --node` 01:39:29; restart `4203d3d9` 01:40:26–01:40:29, Ready 01:40:51 |
| 01:41:54–01:42:09 | neighbour-check restart `f90b88a6` 01:41:54–01:41:58 |

No outage outside these windows; the host1 restarts did not touch either path.

## Ledger spot check

Each regression test run singly from `clab-backup-ui/` (`ledger-tests.txt`, 01:47:42–01:48), then mutation-checked in
a scratch copy (`mutation-checks.json`: the fix undone, the named test run against the copy and required to FAIL,
then the file restored and the test required to PASS again; bytecode caching disabled, see O-6).

| Entry | Regression test (singly) | Mutation (fix undone in the copy) | Mutant | Observed in steps 3–4 |
|---|---|---|---|---|
| **QA-017** | `test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note` OK | `cisco_xrv9k` key removed from `RESTART_KNOWN_LIMITS` | killed | the XRv9k review and API preview carry the limit verbatim, cEOS and host1 carry none |
| **QA-018** | `test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links` OK | `restart_links` never reports a neighbour down | killed | neighbour check 20/20: host1 named with both cases, `3 links restored` |
| **QA-019** | `test_a_refused_login_right_after_a_manager_restart_reads_booting_until_the_grace_window_closes` OK; `test_a_lab_wide_lifecycle_job_drops_every_device_login_proof_for_the_grace_window` OK | `LOGIN_GRACE = 0`; lab-wide jobs forget no device | both killed | XRv9k `booting → ready` with no `failed`; every cEOS/host1 run the same |
| **QA-020** | `test_a_stale_restart_review_hears_the_stale_reason_while_the_previous_job_still_refreshes` OK | `self.guard()` moved back before the stale checks in `confirm()` | killed | two-tabs 13/13 with the QA-020 wording; my L2 the same across devices |
| **TOOL-002** | (tool assertions) | the tool's own expression text evaluated on synthetic inputs | 10/10 as expected: a `booting, failed, booting, ready` timeline fails; two `--node`, another device after `--node`, no `--node`, `deploy`, a 409 preview all fail the argv check | both checks passed on the live runs |
| QA-014 | `test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason` OK | `settled_after_restart` always returns '' | killed | (vJunos-switch not restarted, by rule) |
| QA-016 | `test_engine_identifiers_follow_netlabs_16_character_rule` OK | `NAME` widened to 64 characters | killed | stress bulk's boundary check (17 characters refused, 16 accepted by the engine) passed |
| QA-015 | `node --test --test-name-pattern=QA-015 tests/test_network_design_ui.js` 2/2 | `designViewFresh` ignores the sequence | killed | stress race-b stale-wins 0/20 |
| RD-001 | `test_a_restart_device_review_is_stale_when_a_lifecycle_job_lands_during_its_own_helper_calls` OK | the preview-time stale refusal removed | killed | (not reachable live without a concurrent job) |
| RD-003 | `test_restart_device_binds_every_container_naming_shape_exactly` OK | selector reduced to a bare suffix match | killed | node-of-another-lab / path / trailing-space refusals |
| QA-003 | `node --test --test-name-pattern='^P1: an unrelated guided edit' …` 1/1 (a `QA-003` pattern matches no title) | — | — | probe P1's three CONFIRMED-target checks fail as required |

## Findings

**F-1 (product, P0 class by the ledger's own scale: a wrong-lab mutation with data loss; U-01's class, not covered by
its fix). *Remove design* opened in one lab stays open after the browser goes Back to another lab, and confirming it
silently removes the first lab's design while the second lab is shown.**

- Reproduction (fixture, real app and engine, `adversarial_transitions.py` T1, reproduced twice: 01:40 on 8195 and
  01:48 on 8196): both labs carry the same saved design (same content, so the same content-hash revision
  `48ad14b7b28b4110a7e6b893`; a class of identical starter designs makes this realistic). Open `BGP_TheoryToPractice`'s
  Design tab, then `ospf-basics`'s; More › *Remove design…*; press the browser's Back. The page switches to
  `BGP_TheoryToPractice` (header, hash, `designState.labId`), but `#design-clear-dialog` stays open over it, still
  reading "The saved network design for this lab is removed" (`adv8-T1-2-after-back.png`). Click *Remove design*: the
  dialog closes, **`ospf-basics`'s design is removed** (API: `a_present false`), `BGP_TheoryToPractice` keeps its
  design and still reads "Design saved, no plan yet", and no message is shown (`adv8-T1-3-after-confirm.png`,
  `adversarial-transitions.json` `t1_after_confirm`).
- Cause (read in the source): `selectLab()` (`app.js`) and `applyRoute()` (`shell.js`) close only `details-dialog` on a
  lab change; `designClearDesign()` (`network-design.js`) captures `lab` when the dialog opens but reads the revision
  from `designState.view` (the lab now shown) when it is confirmed, and after the write
  `if(!designViewWritten(labId))return;` returns before the notice, so the removal is silent.
- With different revisions (T1b, Renumber) the same stale dialog is refused with "The design changed since this page
  loaded. Reload it first." and nothing changes — safe, but the reason is wrong (nothing changed; the dialog belongs to
  another lab). The same code shape makes *Forget allocations* act on the hidden lab when the revisions are equal
  (inferred from the source, not run).

## Observations

- O-1: the Restart review also stays open over another lab after Back (L1); unlike F-1 it names its lab, topology path
  and device, and confirming restarted exactly that device, so it contradicts nothing. The shared cause (dialogs not
  closed on a lab change) is worth fixing together with F-1.
- O-2: the cEOS Devices-panel job took 23 s (01:38:40–01:39:03) against 3–4 s for the other cEOS jobs; the job output
  shows containerlab waiting 21 s between parsing the topology and restoring the links (the host was also running the
  fixture chains and the unit suite). Well within the budget.
- O-3: `docker ps` showed the XRv9k container `(unhealthy)` at 01:37 (the image's own healthcheck) while the manager
  read it *Ready* and the device answered SSH; the manager's readiness is SSH-proven by design.
- O-4: right after *Ready* (01:50:43) XRv9k's `show ospf neighbor` listed none at 01:50:54; both adjacencies were FULL
  at 01:51:40. The configuration itself was intact at the first read-back.
- O-5: the tools write their JSON records without a final newline, and `design_probes.log` / `coverage_run.log` carry
  whitespace-only lines; I normalised my copies in `PASS_DIR` (the charter's hygiene rule). The probe driver still
  exits 0 with 21 FAIL lines (OBS-005, already recorded).
- O-6 (my harness, not the product): `live_transitions.py` run 1 (01:43:40) picked the wrong job because I sliced the
  capped, unordered `/api/operations` list by length (kept as `live-transitions-run1-scriptbug.*`; its restarts were two
  host1 jobs, `0e5e3ade` and `8eb23496`); `mutation_checks.py` run 1 reported two survivors because a same-size mutant
  written in the same second was served from a stale `.pyc` to the "restored" run (kept as
  `mutation-checks-run1-stale-pyc.*`); the rerun without bytecode caching killed all ten.

## Not run or blocked

Nothing of the charter was skipped. By rule, vjunos-switch and cjunosevolved were never restarted (previews only for
vjunos-switch), `--stop-mode docker` was not used, and XRv9k was restarted exactly once.

## Scripts of this pass (`PASS_DIR/tools/`)

- `run_fixture_chain.sh` — the two fixture chains with fresh data directories and the tracked-evidence restores.
- `adversarial_transitions.py` — T1 dialog kept across a Back navigation (F-1), T1b the same with different revisions,
  T2 reload mid-generation, T3 lab switched under a running generation and back.
- `live_transitions.py` — L1–L4 against the deployed manager (host1 restarts only).
- `previews_refusals.py` — the previews and refusals, verbatim comparison with `RESTART_KNOWN_LIMITS`.
- `mutation_checks.py` — the ten mutations in a scratch copy and the TOOL-002 synthetic cases.
- `summarise_restart.py` — per-run summary of a `check_restart_device.py` record.

**Verdict: NOT CLEAN** (F-1). Model: Opus, as asked (self-reported).
