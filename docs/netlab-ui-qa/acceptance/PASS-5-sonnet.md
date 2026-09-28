# Acceptance pass 5 — Sonnet (self-reported)

Independent, fresh-state acceptance pass on release 1.30.50 of the containerlab manager (netlab UI/UX
campaign + Restart device). Model: Sonnet 5, self-reported by the model itself (no external
verification of the model identity was performed or is possible from inside the session). Verification
only: nothing was fixed, no tracked file was edited, and every finding below is reported as found, not
repaired.

Evidence, logs and this report's own working files are under
`docs/netlab-ui-qa/acceptance/pass-5/` (`PASS_DIR`), scripts under `PASS_DIR/tools/`.

## Build, tree and environment

| Check | Command | Result |
|---|---|---|
| Commit | `git rev-parse --short HEAD` | `9aa25c3` (confirmed) |
| Version | `cat clab-backup-ui/VERSION` | `1.30.50` (confirmed) |
| Tree | `git status --short` | three untracked `CLAB_*.md` root files, `docs/netlab-ui-qa/acceptance/pass-3/` (tracked, pre-existing), this pass's own untracked `docs/netlab-ui-qa/acceptance/pass-5/`; **no** tracked file modified during this pass (the charter's expected `M docs/netlab-ui-qa/PICKUP.md` did not appear — the lead had not edited it during this run) |
| `git diff --check` | (staged/working tree) | clean, no output, exit 0 |

Manager container (`docker ps`, 2026-09-28T00:09:23Z):

```
CONTAINER ID   IMAGE                 CREATED AT                      STATUS          NAMES                                   PORTS
ea4604b1f576   clab-backup:1.30.50   2026-09-27 23:18:08 +0000 UTC   Up 51 minutes   containerlab-node-manager-backup-ui-1
```

Capture session service: `clab-manager-capture-sessions-1` runs `clab-capture-service:1.30.49` (unchanged
code, as the charter states — not a finding). `containerlab inspect` (read-only, `sudo`) confirmed the five
`restore-square` containers (ceos, cjunosevolved, vjunos-switch, xrv9k, host1) all `running`/`(healthy)`,
containerlab 0.79.0.

Pre-flight `/api/state` (`PASS_DIR/preflight-api-state.json`, 2026-09-27T23:55:17Z): lab id
`174386ec12ee496190c585c5796b2662`; all five devices of `restore-square`, including host1, read
`nos_login.status == "ready"`.

## Steps

| # | Step | Command | UTC start | UTC end | Result | Evidence | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | verify-release | `python3 deploy/verify-release.py` | 23:48:43 | 23:48:43 | "Source release verified: 1.30.50" / "Documentation names only release 1.30.50." | `verify-release.log` | PASS |
| 1 | diff check | `git diff --check` | 23:48:45 | 23:48:45 | no output | `git-diff-check.log` (empty) | PASS |
| 1 | node --check | every `app/static/*.js` | 23:48:49 | 23:48:50 | 0 failures | `node-check.log` | PASS |
| 1 | link check | `check_links.py` | 23:48:53 | 23:48:54 | "173 files, 0 problems" | `check_links.log` | PASS |
| 2 | Python unit suite | `unittest discover` (`clab-backup-ui/`) | 23:48:57 | 23:52:35 | Ran 1704 tests in 212.880s, OK (skipped=1) | `pyunit-full.log` | PASS |
| 2 | Browser suite | `node --test tests/*.js` | 23:51:0x | 23:51:06 | tests 379, pass 379, fail 0 | `nodetest-full.log` | PASS |
| 3 | Design tab browser walk | `check_design_ui.py --port 8160` | 23:51:0x | 23:51:0x | 29 of 29 checks passed; 0 console/page errors | `check_design_ui-report.md`, `check_design_ui-stdout.log` | PASS |
| 3 | QA-009 poll retry | `check_design_poll_retry.py --port 8161` | 23:52 | 23:52 | 9 checks, 0 failed | `check_design_poll_retry-stdout.log`, `poll-retry.json` | PASS |
| 3 | Stress race | `stress_design.py race --port 8162` | 23:52 | 23:55 | 80 checks, race-a leaks 0/20, race-b stale-wins 0/20, 0 unhandled console errors | `stress_design-race-stdout.log`, `stress-race-results.json` | PASS |
| 3 | Stress bulk | `stress_design.py bulk --port 8162` | 00:01 | 00:01 | 43/43 checks, 24 generations run | `stress_design-bulk-stdout.log`, `stress-bulk-results.json` | PASS |
| 3 | Coverage run | `coverage_run.py --port 8163` | 00:02 | 00:03 | 123 rows: 112 PASS, 8 BLOCKED, 3 NOT RUN, 0 FAIL; 0 rows differ from committed `coverage.json` | `coverage-run-stdout.log`, `coverage-results.json` | PASS |
| 3 | Design probes | `design_probes.py --port 8164` | 00:04 | 00:05 | 55 checks; 19/19 CONFIRMED-target checks FAIL (none PASS); the two named bug-describing checks (P1 "the loss is permanent", P3 "Generate was not blocked") also FAIL; no other unexpected failure | `design-probes-stdout.log` | PASS |
| 3 | Adversarial (own) | `PASS_DIR/tools/check_qa002_more_menu.py --port 8165` | 23:58 | 23:58 | 21/21 checks | `qa002-stdout.log`, `qa002-more-menu-results.json` | PASS |
| 4 | Traffic probe (background) | `traffic_probe.py --from cjunosevolved ...` | 23:58:44 | 00:06:38 | 73 samples; 2 loss windows, both attributable to a known restart (see below); 0 SSH failures | `ceos-traffic.jsonl` | PASS |
| 4 | cEOS restart (map/devices/stopped) | `check_restart_device.py --device ceos ...` | 23:58:44 | 00:01:06 | 81 checks, 0 failed | `restart-ceos-stdout.log`, `ceos-2026-09-27T235844+0000.json` | PASS |
| 4 | Two tabs (host1) | `check_restart_two_tabs.py --device host1` | 00:02:10 | 00:02:1x | 13 checks, 0 failed | `restart-two-tabs-stdout.log`, `two-tabs-host1-2026-09-28T000210+0000.json` | PASS |
| 4 | Neighbour (ceos/host1, containerlab mode) | `check_restart_neighbour.py` | 00:05:59 | 00:06:4x | 20 checks, 0 failed | `restart-neighbour-stdout.log`, `neighbour-ceos-containerlab-20260928T000559+0000.json` | PASS |
| 4 | API previews + refusals | `curl` × 6 | 00:07:xx | 00:07:xx | see detail below | `api-preview.log` | PASS |
| 4 | XRv9k read-back (pre) | `nodecli.py xrv9k ...` | 00:07:45 | 00:07:59 | Loopback0 10.255.0.4/32; OSPF 2 neighbours FULL (configuration A) | `xrv9k-readback-pre.log` | PASS |
| 4 | XRv9k restart | `check_restart_device.py --device xrv9k --links 2 --ready-budget 1200` | 00:08:04 | 00:12:5x | 28 checks, 0 failed; readiness `booting → ready`, no `failed` state | `xrv9k-restart-stdout.log`, `xrv9k-2026-09-28T000804+0000.json` | PASS |
| 4 | XRv9k read-back (post) | `nodecli.py xrv9k ...` | 00:13:30 | 00:13:40 | Loopback0 10.255.0.4/32 unchanged; OSPF 2 neighbours FULL (freshly re-established) | `xrv9k-readback-post.log` | PASS |
| 5 | Ledger spot check | 10 regression tests | 00:08 | 00:09 | 10/10 pass | `ledger-tests-1.log`, `ledger-tests-2.log`, `ledger-tests-3.log` | PASS |

One transient, self-resolving SSH banner error occurred on the *first* attempt of `show running-config
interface Loopback0` both before and after the XRv9k restart (`paramiko.ssh_exception.SSHException: Error
reading SSH protocol banner`); an immediate retry succeeded both times with identical output. This is an
independent-SSH-tool artifact (a fresh Paramiko connection racing the device's own SSH daemon under load
from the OSPF read moments before), not a product behaviour — no restart, deploy or manager action was
running at either moment — and is recorded here for transparency, not as a finding.

## Live-run detail

**cEOS** (`clab-restore-square-ceos`, kind `arista_ceos`), three restarts via `check_restart_device.py`:

| Entry point | Job id | Message | Readiness | Container id kept |
|---|---|---|---|---|
| map, running | `eda64bb06bf94981ab87b6585f23bb9d` | succeeded · 3 links restored | booting 23:58:59 → ready 23:59:20 (18–21s) | `0e70068d3675…` unchanged, new start time |
| Devices tab, running | `c421f22eb506486582be4a2ba78dc017` | succeeded · 3 links restored | booting 23:59:35 → ready 23:59:56 | same id, new start time |
| map, stopped first (`containerlab stop --node`) | `5d87c31ba53a4e6e9e9653c3c09433b8` | succeeded · 3 links restored | booting 00:00:41 → ready 00:01:02 | same id, new start time |

All three: no `failed` state between Starting and Ready (QA-019/TOOL-002 live proof); other containers'
ids/start times/processes unchanged; the design, plans, Git binding and deployment time were untouched.

**Two tabs** (`host1`, `check_restart_two_tabs.py`, started 00:02:10): a double-click created exactly one
job (`c33fc3d441d443f4896cd97aa0541a31`, succeeded · 2 links restored, container id
`8f8dbe30cad0…` kept, new start time). The older tab's confirm was refused with
`"Another lab operation ran after this review. Review the restart again."` — the corrected QA-020 wording,
not the stale "Wait for the current operation to finish." — dialog stayed open with the reason inline,
Cancel worked, a fresh review then succeeded. The final simultaneous-confirm race produced at most one new
job (`race.new_jobs == 1`) with the loser reading one of the two acceptable refusals. 13/13 checks passed.

**Neighbour** (`ceos` restarted with `host1` stopped via `containerlab stop --node`, started 00:05:59):
review named `host1` as not running and the parked-link case; job `575e18ffb9ec40ec9166b0c7c218b5f2`
succeeded · 3 links restored (containerlab restored the parked link once `host1`'s container reappeared as
a link endpoint); readiness booting 00:06:14 → ready 00:06:35; restarting `host1` itself through the
product afterward (job `f8591a31d0744d5183fc21e5444845ef`, succeeded · 2 links restored) gave `ceos` back
all 3 links (`device_links_final` == `device_links_after`, both length 3) and `host1` its own 2. 20/20
checks passed.

**API previews / refusals** (lab `174386ec12ee496190c585c5796b2662`):

- `clab-restore-square-vjunos-switch`: HTTP 200, `warnings` = `["Known limit of the vJunos-switch image: its
  container cannot be started a second time (the launcher renames its init.conf on the first start and
  fails without it), so this restart leaves the device stopped until you redeploy the lab. Proven on
  vjunos-switch 23.2R1.14 with containerlab 0.79.0."]` — verbatim match against
  `RESTART_KNOWN_LIMITS['juniper_vjunosswitch']` in `clab-backup-ui/app/lab_operations.py`. No restart was
  confirmed for this node (preview only, per the hard rules).
- `clab-restore-square-xrv9k`: HTTP 200, warning verbatim match against
  `RESTART_KNOWN_LIMITS['cisco_xrv9k']`.
- `clab-restore-square-ceos`: HTTP 200, `warnings: []` (no known-limit note, as expected).
- Refusal 1 (node of another lab, `lab_id=nonexistent-lab-id-999`): HTTP 404, `{"detail":"Lab not found."}`,
  no token.
- Refusal 2 (unknown node in the real lab): HTTP 404, `{"detail":"This device is not in the lab."}`, no
  token.
- Refusal 3 (foreign `Origin: http://evil.example.com`): HTTP 403,
  `{"detail":"Use this manager from its own browser page."}`, no token.
- Operation job count: 148 before and 148 after all six preview/refusal calls — no job was created by any
  of them (previews never create a job; the three refusals additionally created no token).

**XRv9k** (`clab-restore-square-xrv9k`, this pass's restart is a *later* restart, after pass 4's 22:32
UTC one): pre-restart read-back (00:07:45–00:07:59) showed Loopback0 `10.255.0.4/32` and OSPF with 2
neighbours FULL (`10.255.0.3` via Gi0/0/0/0, `10.255.0.1` via Gi0/0/0/1) — configuration A intact. Restart
job `753fb53b6c574a3eb93cc78591ba6250` (created 00:08:10, finished 00:08:16, succeeded · 2 links restored).
Readiness recorded states: `[["2026-09-28T00:08:16Z","booting"],["2026-09-28T00:12:57Z","ready"]]` — booting
straight to ready, **no `failed` state**, total boot time 4m41s, well inside the 1200s budget (QA-019
confirmed live on this later restart, not just the first). Post-restart read-back (00:13:30–00:13:40) showed
Loopback0 unchanged at `10.255.0.4/32` and OSPF's 2 neighbours FULL again (freshly re-adjacent, ~22–27s up,
consistent with the interfaces having just come back). **Configuration A survived this later restart**, as
this pass's charter expected; no reapplication was necessary. 28/28 checks passed in
`check_restart_device.py`. The review carried the XRv9k known-limit note (the product cannot distinguish a
first restart from a later one, so the warning is shown every time; this pass's own read-back is what
proves the configuration actually survived this particular, later restart).

## Traffic-probe loss windows

`ceos-traffic.jsonl` (cjunosevolved → 10.255.0.1 "crossing" = ceos loopback, → 10.255.0.3 "other" =
vjunos-switch loopback; 73 samples, 23:58:39–00:06:38):

- **Crossing-leg loss window 1**: 23:58:59–00:00:39 (11 samples at 100% loss, one `None`/probe-error sample
  at 00:00:47) — coincides exactly with the three-restart `check_restart_device.py` run on `ceos`
  (23:58:44–00:01:06). Traffic recovered by the next sample after 00:00:47.
- **Crossing-leg loss window 2**: 00:06:08–00:06:23 (50%, then two 100% samples) — coincides exactly with
  the neighbour check's restart of `ceos` (job created 00:06:09, finished 00:06:13, readiness ready
  00:06:35).
- **Other-leg (vjunos-switch) loss**: 0 throughout — expected, since vjunos-switch was never restarted
  (preview only) and the neighbour check stopped/restarted `host1`, not `vjunos-switch`.
- **SSH failures**: 0 rounds.

Every loss window is attributable to a restart this pass performed; there is no unexplained loss.

## Defect ledger spot check

Ten entries, run individually from `clab-backup-ui/` unless noted:

| ID | Regression test | Result | Live/browser corroboration in this pass |
|---|---|---|---|
| QA-017 | `test_lab_operations.py -k test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note` | OK | XRv9k API preview carries the fresh-disk-limit warning verbatim; ceos preview carries none |
| QA-018 | `test_lab_operations.py -k test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links` | OK | live neighbour check: review named host1, job reported `3 links restored` once the parked link came back |
| QA-019 | `test_lab_operations.py -k test_a_lab_wide_lifecycle_job_drops_every_device_login_proof_for_the_grace_window` and `test_node_readiness.py -k test_a_refused_login_right_after_a_manager_restart_reads_booting_until_the_grace_window_closes` | OK, OK | XRv9k's later restart: readiness went straight `booting → ready`, no `failed` in between |
| QA-020 | `test_lab_operations.py -k test_a_stale_restart_review_hears_the_stale_reason_while_the_previous_job_still_refreshes` | OK | two-tabs live check: stale tab read "Another lab operation ran after this review. Review the restart again.", not the busy-guard wording |
| TOOL-002 | (fix to `check_restart_device.py` itself; no product unit test) | n/a | exact single-`--node` argv assertion and the "no `failed` between Starting and Ready" assertion both ran and passed in every live `check_restart_device.py` invocation (ceos ×3, xrv9k ×1) |
| RD-001 | `test_lab_operations.py -k test_a_restart_device_review_is_stale_when_a_lifecycle_job_lands_during_its_own_helper_calls` | OK | (pre-release fix; no separate live reproduction attempted this pass) |
| QA-014 | `test_lab_operations.py -k test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason` | OK | vjunos-switch was only previewed (never restarted) per the hard rules, so the failed-job path itself was not exercised live this pass; the review's known-limit warning (the client-visible half of the fix) was confirmed via the API preview |
| QA-016 | `test_design_intent.py -k test_engine_identifiers_follow_netlabs_16_character_rule` | OK | (unit only; not exercised through the fixture UI this pass) |
| U-01 | `node --test --test-name-pattern="U-01" tests/test_network_design_ui.js` | 1 matched, 0 fail | (browser-unit only) |
| QA-015 | `node --test --test-name-pattern="QA-015" tests/test_network_design_ui.js` | 2 matched, 0 fail | corroborated structurally by `stress_design.py race`'s 0/20 stale-wins this pass |

## Findings

None.

## Observations

- `docs/netlab-ui-qa/tools/probes/design_probes.py`'s `main()` unconditionally `return 0`, so its own
  process exit code is always 0 even when checks are recorded FAIL (including the 19 intentional
  CONFIRMED-target reproductions) — contradicting its own docstring ("Exit status is 1 if any check
  recorded FAIL"). Harmless for this pass, since the charter's actual criterion is read from the printed
  PASS/FAIL lines, not the exit code, and that is what was checked; recorded for the maintainer in the
  spirit of TOOL-001…TOOL-004.
- The single browser console error captured by `design_probes.py` ("Failed to load resource: … 500") is the
  intentional single-injected-500 fault injection used by probe P7 (QA-009 reproduction), not an unhandled
  error; it is exactly the artifact the probe's own comments describe.
- `coverage_run.py`'s and `design_probes.py`'s raw stdout captures (as saved into `PASS_DIR`, unmodified)
  contain trailing whitespace inside a few of their own printed check-detail lines (their long text wraps
  with a trailing space before the terminal's line break). This is the tools' own console output, not
  something authored in this pass, and is preserved verbatim as evidence rather than edited; if these logs
  are ever committed as tracked files, `git diff --check` would flag them, echoing the pattern already
  recorded as TOOL-003.
- One transient `paramiko` "Error reading SSH protocol banner" occurred on the first XRv9k
  Loopback0 read-back both before and after the restart (see the Steps table note); an immediate retry
  succeeded both times with identical output, so it did not affect the substance of either read-back.

## Not run or blocked

Nothing was skipped. `coverage_run.py`'s own 8 BLOCKED / 3 NOT RUN rows are the tool's documented,
expected-to-be-blocked rows (fixture has no real SSH endpoint for Apply-to-devices' reachable/eligible
branches) and matched the committed `docs/netlab-ui-qa/coverage.json` row-for-row (0 differences across all
123 rows), so they are not reported again here as blocked steps of this pass.

## Verdict: CLEAN
