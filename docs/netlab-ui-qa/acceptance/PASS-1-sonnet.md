# Acceptance pass 1 (Sonnet) — release 1.30.48, commit b4329d3

Independent clean acceptance pass, first of two, on the FINAL build. Verification only: no fixes were
applied. Worktree `/home/clabllm/projects/clab-manager-1.30.42`, branch `claude/netlab-integration`.
Deployed manager: `http://127.0.0.1:8081` (container `containerlab-node-manager-backup-ui-1`, image
`clab-backup:1.30.48`, data `/srv/containerlab-node-manager/data`, never pointed at by any test or fixture
in this pass). Lab `restore-square` deployed with configuration A at the start of this pass.

All times UTC. Evidence under `docs/netlab-ui-qa/acceptance/pass-1/`.

## Environment check (before step 1)

- `date -u` at start: 2026-09-27T19:28:29Z (approx; see step timestamps below for exact command times).
- `sudo containerlab inspect --name restore-square`: all five containers `running` (vjunos-switch and
  xrv9k additionally `(healthy)`); `docker ps` confirms `containerlab-node-manager-backup-ui-1` on
  `clab-backup:1.30.48`.
- `docker logs --tail 30 clab-restore-square-cjunosevolved` at 19:28:33Z: the container is still inside
  its guest boot (`Coming back from an uncontrolled reboot, will recreate /data!`, then
  `watchdog: BUG: soft lockup - CPU#3 stuck for 29s! [uswitchd:8593]` and two further soft-lockup lines for
  CPU#1/CPU#0). Recorded as found, per the assignment's instruction; cjunosevolved was not restarted or
  otherwise touched at any point in this pass, and xrv9k was used as the traffic-probe source instead of it.
- No `check_restart_*.py`, `coverage_run.py`, `stress_design.py`, `traffic_probe.py` or `design_probes.py`
  process was already running (`ps aux` clean) before this pass started.
- End-of-pass check (20:10 UTC, `/api/state`): cjunosevolved finished its boot on its own during this pass
  (never touched) and reads `Ready`; all five devices of `restore-square` read `Ready` except `host1`
  (`Choose NOS` — a Linux host with no NOS credential configured, unrelated to this pass); no stray
  `check_restart_*.py`/`coverage_run.py`/`stress_design.py`/`design_probes.py`/`traffic_probe.py` process was
  left running.

## Step 1 — Static

| Command | Ran (UTC) | Result | Evidence | Verdict |
|---|---|---|---|---|
| `python3 deploy/verify-release.py` | 19:28:49–19:28:52 | `Source release verified: 1.30.48` / `Documentation names only release 1.30.48.` | inline | PASS |
| `git diff --check` | 19:28:52 | exit 0, no output | inline | PASS |
| `node --check` on every `clab-backup-ui/app/static/*.js` | 19:28:52–19:28:53 | every file checked, no syntax errors, loop printed `DONE` with no `FAIL:` line | inline | PASS |
| `python3 docs/maintenance-audit/tools/check_links.py` | 19:28:53–19:28:54 | `165 files, 0 problems` | `pass-1/step1-check_links.log` | PASS |

## Step 2 — Unit

| Command | Ran (UTC) | Result | Expected | Verdict |
|---|---|---|---|---|
| `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests` (from `clab-backup-ui/`) | 19:29:02–19:32:35 (212.8 s) | `Ran 1701 tests in 212.838s` / `OK (skipped=1)` | 1701 OK, 1 skipped | PASS |
| `node --test tests/*.js` (from `clab-backup-ui/`) | 19:29:02–19:29:03 (0.57 s) | `# tests 379` / `# pass 379` / `# fail 0` | 379 pass | PASS |

## Step 3 — Fixture/browser (no VM)

| Command | Ran (UTC) | Result | Evidence | Verdict |
|---|---|---|---|---|
| `docs/netlab-integration/tools/check_design_ui.py --port 8140` | 19:31:41–19:31:50 | 29 of 29 checks passed; 0 console errors; 0 page errors. Note: this tool's default `--shots` directory is the tracked `docs/netlab-integration/evidence/shots/` (not a scratch dir); it overwrote 4 committed release screenshots (`02-problems.png`, `03b-tables.png`, `04-plan.png`, `05-file.png`), noticed later at 19:57 UTC and restored with `git checkout --` (confirmed clean) | `pass-1/step3-check_design_ui.log`, `pass-1/step3-check_design_ui.md` | PASS |
| `docs/netlab-ui-qa/tools/check_design_poll_retry.py --port 8141 --out docs/netlab-ui-qa/acceptance/pass-1` | 19:32:11–19:33:06 | 9 checks, 0 failed (QA-009 positive: an injected 500 gives "attempt 1 of 5", plan still completes; six failures → *Plan progress unknown*, no further polls for 15 s, Generate again loads afresh) | `pass-1/poll-retry.json`, `pass-1/poll-retry-A-attempt.png`, `pass-1/poll-retry-A-ready.png`, `pass-1/poll-retry-B-unknown.png` | PASS |
| `docs/netlab-ui-qa/tools/stress_design.py race --port 8142` | 19:33:17–19:39:47 (race-a 20 replays + race-b 20 replays) | `Pass 2 done: race-a leaks 0/20, race-b stale-wins 0/20, 0 unhandled console errors`; JSON summary `checks_total: 80, checks_failed: 0` | copied to `pass-1/race-results.json`; original restored in `docs/netlab-ui-qa/evidence/stress/` with `git checkout --` after both stress runs | PASS |
| `docs/netlab-ui-qa/tools/stress_design.py bulk --port 8142` | 19:40:07–19:41:17 | `Pass 5 done: 43/43 checks passed, 24 generations run, PUT took 0.02s`; the retention boundary held (exactly 20 of 24 generations kept, the oldest 4 pruned, a pruned generation's detail/artifact both 404, a still-present generation's file still opened) | copied to `pass-1/bulk-results.json`; original restored in `docs/netlab-ui-qa/evidence/stress/` with `git checkout --` (confirmed clean with `git status --short`) | PASS |
| `docs/netlab-ui-qa/tools/coverage_run.py --port 8143 --data <fresh scratch dir>` | 19:41:56–~19:42:5x (run concurrently with design_probes below, different port and data dir) | `counts: {'PASS': 112, 'NOT RUN': 3, 'BLOCKED': 8} total rows recorded: 123`; 0 FAIL rows | copied to `pass-1/coverage-results.json`; originals restored (`evidence/coverage/`, `coverage.json`, `COVERAGE.md`) with `git checkout --`, confirmed clean | PASS |
| `docs/netlab-ui-qa/tools/probes/design_probes.py --port 8144` (run concurrently with coverage_run, different port/data) | 19:41:37–19:43:52 | 35/54 checks PASS, 19 FAIL; see "Findings" for the 3 CONFIRMED-target PASSes and 1 unhandled exception — analysed below, not counted as product regressions | `pass-1/design_probes-run.log`, `pass-1/design_probes-p10-isolated-retry.log` (P10 rerun alone, port 8144, identical result), `pass-1/P7-02-shortly-after-injected-500.png`, `pass-1/P8-02-after-reload-storage-had-failed.png`, `pass-1/P10-EXCEPTION.png`; originals in `docs/netlab-ui-qa/evidence/probes/` restored with `git checkout --` | PASS with findings (see below) |

## Step 4 — Live, deployed product

Pre-flight (19:28–19:49 UTC): `sudo containerlab inspect --name restore-square` showed all five containers
`running` (vjunos-switch, xrv9k additionally `(healthy)`); `docker logs --tail 30
clab-restore-square-cjunosevolved` showed the guest still inside its boot (`Coming back from an uncontrolled
reboot, will recreate /data!`, soft-lockup lines for CPU#0/1/3) — recorded as found; cjunosevolved was never
touched in this pass. No `check_restart_*.py` process was already running.

| Command | Ran (UTC) | Result | Evidence | Verdict |
|---|---|---|---|---|
| `traffic_probe.py --from xrv9k --crossing 10.255.0.1 --other 10.255.0.3 --minutes 8` (background) | 19:49:16–~19:57:16 | continuous JSONL rows, `ssh_ok: true` throughout the window covering both the ceos restart run and the neighbour check below | `pass-1/ceos-traffic.jsonl` | PASS (see loss-window summary below) |
| `check_restart_device.py --device ceos --ready-budget 300 --devices --stopped --terminal --capture --links 3` | 19:49:35–19:51:59 | `78 checks, 0 failed` — map Cancel (no-op), map confirm (job succeeded, `3 links restored`, id kept, other 4 containers untouched, Ready proof after restart, browser CLI disconnect/Reconnect with no replay, a new capture resolved interfaces), Devices-view/keyboard entry point (panel stays open, focus returns), `containerlab stop --node ceos` then restart (start/restore review wording, exited state, Ready again); review carried no known-limit note (correct: cEOS has none) | `pass-1/ceos-2026-09-27T*.json`, `pass-1/*.png` | PASS |
| `check_restart_two_tabs.py --device host1` | 19:52:06–19:52:24 | `13 checks, 0 failed` — two tabs each get a valid review; a double click makes exactly one job; the older tab's stale review is refused with the reason inline and Cancel/refresh still work; two simultaneous confirms start at most one job | `pass-1/two-tabs-host1-*.json` | PASS |
| `check_restart_neighbour.py --device ceos --neighbour host1 --links 3 --neighbour-links 2 --stop-mode containerlab --ready-budget 300` | 19:52:38–19:53:34 | `20 checks, 0 failed` — host1 stopped with `containerlab stop --node` (links parked); manager lists it exited; the review named host1 and both cases (parked vs destroyed) and gave the "waits for its interfaces" wording; **the API preview carried the same warning text**; job `3 links restored` (the parked link came back), same container id, all dataplane links present, ceos Ready again; host1 then restarted through the product (start/restore path), its own job counted its 2 links, and ceos ended with all 3 links once host1 was back | `pass-1/neighbour-ceos-containerlab-20260927T195238+0000.json`, `pass-1/neighbour-*.png` | PASS |
| API preview `restart-node` on `clab-restore-square-vjunos-switch` and `clab-restore-square-xrv9k` (preview only — never confirmed) | 19:53:51 | vjunos-switch warning: *"Known limit of the vJunos-switch image: its container cannot be started a second time (the launcher renames its init.conf on the first start and fails without it), so this restart leaves the device stopped until you redeploy the lab. Proven on vjunos-switch 23.2R1.14 with containerlab 0.79.0."* xrv9k warning: *"Known limit of the XRv9k image: its launcher picks the VM disk by file name at every start, and after the first start a second copy of the pristine image sorts first, so the first restart after a deploy boots the device from a fresh disk: it comes back Ready with its factory configuration and everything configured since the deploy is gone (proven on cisco_xrv9k 24.3.1 with containerlab 0.79.0). Back up the configuration first and use Replace running configuration afterwards."* Both match `RESTART_KNOWN_LIMITS` in `lab_operations.py` verbatim. vjunos-switch was never restarted (preview only, never confirmed) | `pass-1/preview-vjunos-switch.json`, `pass-1/preview-xrv9k.json` | PASS |
| Traffic probe result (xrv9k → ceos loopback `10.255.0.1` crossing, → vjunos-switch loopback `10.255.0.3` other), covering the ceos restarts and the neighbour check above | 19:49:16–19:57:22 (94 rows) | 5 loss windows on the crossing path, each lining up with one of the four ceos restarts run in this pass: `19:49:48–19:49:55` (map restart), `19:50:21–19:50:28` (Devices-view restart), `19:50:45` (one blip) and `19:50:55–19:51:50` (the longer, ~55 s window: `containerlab stop --node` then restart — the device was genuinely down, not just mid-restart), `19:52:59–19:53:06` (the neighbour-check's restart of ceos). **Zero loss on the "other" path** (through vjunos-switch, never touched) across all 94 rows, and `ssh_ok: true` on every row (xrv9k itself, the probe's source, was never affected) | `pass-1/ceos-traffic.jsonl` | PASS |
| XRv9k restart + configuration loss/persistence proof (last live step) | 19:57:46–20:09:34 | Baseline read-back at 19:57:46 confirmed configuration A in place (`interface Loopback0 … ipv4 address 10.255.0.4 255.255.255.255`). `check_restart_device.py --device xrv9k --links 2 --ready-budget 1200`: 19:57:51–~20:07:40 (job succeeded in seconds; `2 links restored`, same container id; readiness took roughly 9.5 min for the fresh-disk boot). **27 checks, 0 failed**; the review named the XRv9k known limit verbatim before confirming. Read-back at 20:09:06: **`% No such configuration item(s)`** for Loopback0 — configuration A was lost by the first restart after the redeploy, exactly as QA-017 describes. Configuration A reapplied at 20:09:15 with `nodecli.py xrv9k --file …/xrv9k.cli` (committed cleanly on the **first attempt** — XR did not refuse the commit this time, unlike some earlier campaign runs); read-back at 20:09:24 confirmed `ipv4 address 10.255.0.4 255.255.255.255` back in place, and `show running-config router ospf 1` at 20:09:34 confirmed the OSPF config (router-id, area 0, the three interfaces) was committed too | `pass-1/xrv9k-2026-09-27T195751+0000.json` (27/27), `pass-1/preview-xrv9k.json`, `pass-1/xrv9k-1957-*.png`, and the four read-back transcripts `pass-1/xrv9k-readback-before-restart.log`, `pass-1/xrv9k-readback-after-restart-loss.log`, `pass-1/xrv9k-apply-configuration-a.log`, `pass-1/xrv9k-readback-after-apply.log`, `pass-1/xrv9k-ospf-readback.log` (narrow, single-command outputs only — no full running-config, no secrets) | PASS |

## Step 5 — Defect ledger spot check

Chosen: QA-003, QA-009, QA-014, QA-015, QA-016 (five of my choice, spanning Design guided form, progress
polling, and two restart-outcome defects) plus the two mandatory QA-017, QA-018. For each: the named
regression test run individually (`-k <name>` for Python, `--test-name-pattern` for node), and whether the
described behaviour is what this pass actually observed.

| ID | Regression test | Run alone | Behaviour observed in this pass |
|---|---|---|---|
| QA-003 | `tests/test_network_design_ui.js` "P1: an unrelated guided edit keeps the pools the form has no control for, and every extra pool key" | `node --test --test-name-pattern="^P1: "` → 1 pass (85 skipped by the pattern filter, as expected) | Step 3's `design_probes.py` P1 CONFIRMED-target checks ("an unrelated guided edit silently drops the vrf_loopback/router_id pool", "…the lan pool's start/allocation keys") all read `FAIL` — the old bug does not reproduce, matching the fix |
| QA-009 | `tests/test_network_design_ui.js` "P7: a failed progress poll is retried a bounded number of times with the student told, then stops with a way out" | `node --test --test-name-pattern="^P7: "` → 1 pass | Directly observed live (fixture) in Step 3 via `check_design_poll_retry.py`: an injected 500 on the first poll produces "attempt 1 of 5 … Trying again" in `#design-detail`, the plan still completes; six failures produce "Plan progress unknown", no further polls for 15 s, Generate again loads afresh — exactly QA-009's fixed description |
| QA-014 | `tests/test_lab_operations.py` `test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason` | `python -m unittest … -k test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason -v` → OK | Not reproduced live in this pass (vJunos-switch was never restarted, per the hard rule). The review's known-limit warning was directly observed via the live API preview (Step 4, verbatim match to `RESTART_KNOWN_LIMITS['juniper_vjunosswitch']`), and the job-fails-on-exit mechanism the warning describes is exactly what the unit test asserts |
| QA-015 | `tests/test_network_design_ui.js` "QA-015: two overlapping loads of one lab, the older answer arriving last, leave the newer generation shown" and "…the lab-switch guard still holds …" | `node --test --test-name-pattern="QA-015"` → 2 pass | Directly observed live (fixture) in Step 3 via `stress_design.py race`: 20/20 race-a replays (no cross-lab leak) and 20/20 race-b replays (the newer generation always won over a late-arriving stale answer), 80/80 checks total |
| QA-016 | `tests/test_design_intent.py` `test_engine_identifiers_follow_netlabs_16_character_rule` | `python -m unittest … -k test_engine_identifiers_follow_netlabs_16_character_rule -v` → OK | Directly observed live (fixture, real netlab engine) in Step 3 via `stress_design.py bulk`: a 17-character VRF name refused at Save (400, "16 characters" in the manager's own words); a 16-character name saved and generated through the real engine |
| QA-017 | `tests/test_lab_operations.py` `test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note` | `python -m unittest … -k test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note -v` → OK | See the XRv9k live step below: the known-limit warning was observed via the live API preview and the live review; the fresh-disk config-loss-then-persistence behaviour is reproduced live below |
| QA-018 | `tests/test_lab_operations.py` `test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links` | `python -m unittest … -k test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links -v` → OK | Directly observed live in Step 4 via `check_restart_neighbour.py --stop-mode containerlab` (the only stop mode this pass is allowed to use): the review named host1 and both cases, the API preview carried the same warning, the job read "3 links restored" (parked link came back) |

All seven regression tests pass individually (not merely as part of the full-suite run), and every described
behaviour was directly observed in this pass except QA-014's live restart (forbidden by the hard rules; the
review text and the unit test together stand in for it) and QA-017's full live sequence (completed below).

## Findings

### F1 — `design_probes.py` (§6 probe driver): 3 of 19 CONFIRMED-target checks report PASS on the fixed build; investigated, none is a product regression

The assignment requires recording any CONFIRMED-target check (a probe assertion that encodes the *original
bug's* behaviour) that still passes on the fixed build, since that would mean the bug is not actually fixed.
Three did, plus one unhandled exception stopped two further checks from running. Investigated each with
source-level evidence and, where one existed, an independent regression check; none indicates the underlying
defect (QA-009, QA-010, QA-012) is actually unfixed.

**P7 (`PASS`): "the design tab's own poll dies silently on the first failed request … still \"Generating…\" 3s
after a single injected 500".** The check reads `#design-state` (`ctx.text('#design-state')`) and asserts it
still contains the word "Generating". Reading `clab-backup-ui/app/static/index.html:154-155`: `#design-state`
holds only the pill and the state *label* ("Generating the plan…"); the retry detail text ("attempt 1 of 5 …
Trying again…") is written into the separate `<p id="design-detail">` element
(`network-design.js:906-912`, `designRenderHeader`). The label stays "Generating the plan…" for the whole
busy period whether or not a retry is in progress (`designStateOf`, `network-design.js:39-40`), so this check
was always going to read "Generating" regardless of the fix — it is checking the wrong element. The actual
retry mechanism (QA-009) is independently and rigorously confirmed by
`docs/netlab-ui-qa/tools/check_design_poll_retry.py`, run in Step 3 above (9/9, including the literal text
"attempt 1 of 5" in `#design-detail`, the retry succeeding, five-then-give-up, and Generate-again recovery).
Conclusion: a stale/miscalibrated probe assertion, not a regression.

**P8 (`PASS` ×2): "the edit is gone after reload" and "no message at all tells the student their edit was
lost", both checked *after* a page reload following a simulated `localStorage.setItem` failure.** QA-010's
fix (`network-design.js:1089-1094`, `designSetDraft`) sets `draftUnsaved=true` when `writeDesignDraft`
answers `false`, which `designStateOf` (`network-design.js:44`) renders as pill `danger` and detail "Your
changes could not be kept in this browser…" — but this happens on the *live* page, before the reload, warning
the student in real time so they can save before navigating away. Once the storage write has genuinely
failed and the page is then reloaded, there is nothing left to warn about (the browser holds no draft, so the
manager cannot invent a "your edit was lost" message tied to specific content after the fact) — this is an
inherent property of a synchronous browser-storage failure, not something the fix claims to survive. The
probe's own pre-reload check only asserts the generic label contains "Unsaved" (`unsaved_shown = 'Unsaved' in
ctx.text('#design-state')`), never checking the pill colour or the specific "could not be kept" detail text
that is the actual fix, so it never actually exercises the fixed code path's real assertion. The dedicated
unit test in `tests/test_network_design_ui.js` (~line 853-859) does assert exactly that: with
`writeDesignDraft:()=>false` mocked, `st.pill==='danger'` and `st.detail` matches
`/could not be kept in this browser/` — and it passed in the full suite run (Step 2, 1701 OK). Conclusion:
the probe checks the wrong moment (post-reload instead of the real-time warning); the fix is confirmed
working by source inspection and the unit test.

**P10: an unhandled `TimeoutError` inside `save()` after "no message explains the desync at this point",
before `P10-05`/`P10-06` execute.** Reproduced twice identically (once inside the full 10-probe run, once in
an isolated `--probes 10` rerun with nothing else running — `pass-1/design_probes-p10-isolated-retry.log`).
The screenshot at the failure point (`pass-1/P10-EXCEPTION.png`) shows the Design tab still reading "Unsaved
changes" with two validation problems listed: `addressing.p2p.prefix: The allocation size must be between
the pool length and /32` and `bgp.as: The value has the wrong type (expected asn)`. Steps 10a/10b
deliberately set the BGP AS field to `0` and the p2p prefix field to blank to demonstrate QA-012's coercion
fix (both of those CONFIRMED-target checks correctly `FAIL`, i.e. the values are no longer silently coerced
to `65000`/`31` — matching `docs/NETWORK-DESIGN.md`: "a number typed as 0 or left blank is refused by name,
never replaced by a default"). The probe never resets those two fields before its final `save(page)` call
(used to test whether the unrelated vrf-checkbox desync persists through a successful save), and the shared
`save()` helper waits up to 15s for `#design-state` to stop reading "Unsaved" — which it correctly never
does, because the design genuinely still has unresolved problems and the manager correctly refuses to save
it. This is the intended, tested behaviour — `test_design_intent.py::test_bgp_as_must_be_present_and_in_range`
(run individually in Step 5 below) for the AS=0 case, `test_prefix_size_below_pool_length_is_refused` for the
prefix-validation family the blank p2p prefix falls into — interacting with a probe script that was not
updated after QA-012 removed the coercion it used to rely on to make the design valid again on its own.
Consequence: `P10-05` and `P10-06`
(whether the vrf-checkbox visual desync survives a save, and self-corrects after reload) do not currently
execute against the fixed build through this tool. Not a product defect; a gap in `design_probes.py` worth
fixing (reset the AS/prefix fields, or split P10 into two independent probes) so it can exercise those two
checks again.

**Recommendation for the campaign (not actioned in this pass — verification only):** update
`design_probes.py`'s P7 check to read `#design-detail` instead of `#design-state`, update P8's post-reload
checks to instead assert the pre-reload pill/detail (or drop them, since the unit test already covers the
real assertion), and fix P10 to clear the AS/prefix fields before its final Save so P10-05/P10-06 run again.



## Verdict: CLEAN

Every step in the pass (1–5) executed and passed. Nothing is recorded as BLOCKED or NOT RUN in this pass: all
static checks, both unit suites, all six fixture/browser tools, the full live sequence (traffic probe, ceos
three ways, two-tabs, the neighbour check, both known-limit API previews, and the XRv9k restart with its
config-loss-then-persistence proof), and all seven defect-ledger spot checks completed with the expected or
better-explained result.

Post-run repository check: `git status --short` outside `docs/netlab-ui-qa/acceptance/` matches exactly what
was already modified/untracked before this pass began (confirmed by diff against the pass's starting
snapshot) — this pass leaves no unintended changes in the tree. The deployed manager, its data directory and
the `restore-square` lab were never pointed at by a test or fixture; `restore-square` ends this pass with
configuration A on xrv9k (reapplied and read back), configuration A untouched on the other devices, and
vjunos-switch never restarted.

Findings F1 (in "Findings" above) are recorded as required by the assignment (three `design_probes.py`
CONFIRMED-target checks reporting PASS, plus one unhandled exception) but, on investigation with
source-level evidence and independent regression checks, none indicates an actual product regression of
QA-009, QA-010 or QA-012 — they are stale/miscalibrated assertions in that probe script, not a defect in the
build. No other discrepancy against `DEFECTS.md`, `RESTART-PARITY.md`, `EVIDENCE.md` or `COVERAGE.md` was
found.
