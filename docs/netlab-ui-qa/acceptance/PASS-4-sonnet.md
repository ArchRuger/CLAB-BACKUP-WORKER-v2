# Acceptance pass 4 (Sonnet, self-reported) — release 1.30.49, commit 14c2f05

Independent clean-pass gate on the FINAL build. Verification only: no fixes were applied, no tracked file
was edited by this pass. Worktree `/home/clabllm/projects/clab-manager-1.30.42`, branch
`claude/netlab-integration`. Model: Sonnet 5 (self-reported by the harness identifying itself as
`claude-sonnet-5`; not independently verifiable from inside the session).

Deployed manager: `http://127.0.0.1:8081`, container `containerlab-node-manager-backup-ui-1`
(`cf6db46fd8be`, image `clab-backup:1.30.49`, `Up 52 minutes` at the end of this pass), data
`/srv/containerlab-node-manager/data` (never pointed at by any test or fixture in this pass). Lab
`restore-square` (five containers: ceos, cjunosevolved, vjunos-switch, xrv9k, host1), redeployed from the
host CLI at 22:00 UTC on 2026-09-27 after a host crash; the lead applied configuration A to each device as
it booted.

All times UTC. Evidence under `docs/netlab-ui-qa/acceptance/pass-4/` (own adversarial-check script under
`pass-4/tools/`).

## Build, tree and environment

- `git rev-parse --short HEAD` → `14c2f05`. `cat clab-backup-ui/VERSION` → `1.30.49`. Both match the
  assignment.
- `git status --short` at the start showed `M docs/netlab-ui-qa/DEFECTS.md`, `M docs/netlab-ui-qa/EVIDENCE.md`,
  `M docs/netlab-ui-qa/PICKUP.md` (the lead editing record files while this pass ran — expected, not a
  finding), the three untracked `CLAB_*.md` prompt files, `docs/netlab-ui-qa/acceptance/pass-3/` (an earlier
  pass interrupted by a host crash) and this pass's own `pass-4/` folder. Re-checked at the end of the pass:
  unchanged except for this pass's own additions. `git diff --check` clean throughout (see Step 1).
- **`LAB_READY_MARKER`**: did not exist at the start (22:08 UTC); polled every ~60 s. Appeared at
  **2026-09-27T22:14:23Z** (file mtime; the marker's own `"written"` field agrees). Content:
  ```json
  {
   "configured": {
    "ceos": "2026-09-27T22:06:15Z",
    "cjunosevolved": "2026-09-27T22:10:21Z",
    "xrv9k": "2026-09-27T22:12:31Z",
    "vjunos-switch": "2026-09-27T22:14:23Z"
   },
   "written": "2026-09-27T22:14:23Z"
  }
  ```
  Copy: `pass-4/LAB-READY-marker.json`. Pre-flight `/api/state` at 22:16:26Z: all five `restore-square`
  devices read `nos_login.status == "ready"` except host1, which reads `readiness: "Choose NOS"` as expected
  (a Linux host with no NOS credential configured).
- `docker ps` line for the manager at the end of the pass: `cf6db46fd8be  clab-backup:1.30.49  Up 52 minutes
  containerlab-node-manager-backup-ui-1`.
- No stray `check_restart_*.py` / `coverage_run.py` / `stress_design.py` / `design_probes.py` /
  `traffic_probe.py` process was left running at the end of the pass; the one fixture manager this pass
  started for its own adversarial check (port 8155) was stopped and its scratch data directory was under
  `/tmp` (not the repository).

## Steps

| Step | Command | Ran (UTC) | Result | Evidence | Verdict |
|---|---|---|---|---|---|
| 1 | `python3 deploy/verify-release.py` | 22:09:06 | `Source release verified: 1.30.49` / `Documentation names only release 1.30.49.` | `pass-4/step1-static.log` | PASS |
| 1 | `git diff --check` | 22:09:06 | exit 0, no output | `pass-4/step1-static.log` | PASS |
| 1 | `node --check` on every `clab-backup-ui/app/static/*.js` | 22:09:06 | every file checked, no syntax errors, no `FAILED:` line | `pass-4/step1-static.log` | PASS |
| 1 | `python3 docs/maintenance-audit/tools/check_links.py` | 22:09:08 | `169 files, 0 problems` | `pass-4/step1-static.log` | PASS |
| 2 | `unittest discover` (from `clab-backup-ui/`) | 22:09:2x–22:13:2x (253.8 s) | `Ran 1703 tests in 253.768s` / `OK (skipped=1)` — matches the reference figure exactly | `pass-4/step2-python-tail.txt`, `pass-4/step2-unit-full.log` | PASS |
| 2 | `node --test tests/*.js` | (same run) | `# tests 379` / `# pass 379` / `# fail 0` | `pass-4/step2-node-tail.txt` | PASS |
| 3 | `check_design_ui.py --port 8150` | 22:09:16–22:09:2x | `29 of 29 checks passed; 0 console errors (0 handled HTTP responses); 0 page errors.` | `pass-4/check_design_ui.log`, `pass-4/check_design_ui-report.md` | PASS |
| 3 | `check_design_poll_retry.py --port 8151` | 22:09:5x–22:10:1x | `9 checks, 0 failed` | `pass-4/check_design_poll_retry.log`, `pass-4/poll-retry.json`, 3 screenshots | PASS |
| 3 | `stress_design.py race --port 8152` | 22:11:00–22:17:0x | `Pass 2 done: race-a leaks 0/20, race-b stale-wins 0/20, 0 unhandled console errors` (80/80) | `pass-4/stress_design-race.log`, `pass-4/stress-race-results.json`; tracked evidence restored with `git checkout --`, confirmed clean | PASS |
| 3 | `stress_design.py bulk --port 8152` | 22:32:2x–22:34:59 (first attempt at 22:16 crashed on my own mistake — `netlab` not on `PATH`; corrected re-run below counted as the result) | `Pass 5 done: 43/43 checks passed, 24 generations run, PUT took 0.03s` | `pass-4/stress_design-bulk.log`, `pass-4/stress-bulk-results.json`; tracked evidence restored, confirmed clean | PASS |
| 3 | `coverage_run.py --port 8153 --data <fresh>` | 22:32:0x–22:33:47 (first attempt at 22:32:02 crashed the same way; corrected re-run counted) | `counts: {'PASS': 112, 'NOT RUN': 3, 'BLOCKED': 8} total rows recorded: 123` — every row's status matches the committed `docs/netlab-ui-qa/coverage.json` (0 diffs, scripted comparison) | `pass-4/coverage-results.json`, `pass-4/coverage_run.log`; tracked evidence/coverage.json/COVERAGE.md restored, confirmed clean | PASS |
| 3 | `design_probes.py --port 8154 --data <fresh>` | 22:32:1x–22:33:58 | 55 checks; 21 FAIL. All 19 CONFIRMED-target checks FAIL (none passes — verified by grep, no exception) plus the two named bug-describing checks (P1 "the loss is permanent", P3 "Generate was not blocked") also FAIL — exactly the reference expectation | `pass-4/design_probes.log`; tracked evidence/probes restored, confirmed clean | PASS |
| 3 | Own adversarial check: `pass-4/tools/adversarial_restart_preview.py --port 8155` | 22:47:xx (fixture, own scratch `/tmp` data dir) | `4 checks, 0 failed` — restart-node preview refuses a client-supplied `path` (400, exact RD-004 message), refuses an undeclared JSON field (422), a shell/path-traversal-looking node name is refused cleanly (409, never 200/500), confirm with a never-issued token is refused (409) | `pass-4/adversarial-restart-preview.log`, `pass-4/tools/adversarial_restart_preview.py` | PASS |
| 4 | Pre-flight `/api/state` | 22:16:26 | all 5 devices `nos_login.status == "ready"` except host1 (`Choose NOS`) | inline above | PASS |
| 4 | `traffic_probe.py --from cjunosevolved --crossing 10.255.0.1 --other 10.255.0.3 --minutes 8` (background) | 22:16:40–22:24:36 | 68 rows, `ssh_ok: true` throughout | `pass-4/ceos-traffic.jsonl` | PASS (loss windows below) |
| 4 | `check_restart_device.py --device ceos --ready-budget 300 --devices --stopped --terminal --capture --links 3` | 22:17:03–22:19:40 | `81 checks, 0 failed` — matches the reference figure exactly | `pass-4/ceos-2026-09-27T221703+0000.json`, 12 screenshots | PASS |
| 4 | `check_restart_two_tabs.py --device host1` | 22:20:05–22:27:22 (3 runs; see Findings F1) | 1st run: crashed (Playwright 30 s click timeout) at "a fresh review after the refusal is offered again". 2nd run: `13 checks, 1 failed`. 3rd (diagnostic) run: `13 checks, 1 failed`, same failing check both times | `pass-4/check_restart_two_tabs.log`, `pass-4/two-tabs-diag-run.log`, 2 JSON records, 1 screenshot | **FAIL (F1)** |
| 4 | `check_restart_neighbour.py --device ceos --neighbour host1 --links 3 --neighbour-links 2 --stop-mode containerlab --ready-budget 300` | 22:28:32–22:29:33 | `20 checks, 0 failed` — matches the reference figure exactly | `pass-4/neighbour-ceos-containerlab-20260927T222833+0000.json`, 5 screenshots | PASS |
| 4 | API previews: vjunos-switch, xrv9k, ceos + 3 refusals + 1 control | 22:30:01–22:31:41 | vjunos-switch and xrv9k warnings match `RESTART_KNOWN_LIMITS` verbatim; ceos carries none; job count unchanged (137 before/after, both preview batches); node-of-another-lab and unknown-node refused 404 with no token. **Request with no `Origin` header: HTTP 200 with a valid token** (expected 4xx, no token) — see Findings F2. Control test (mismatched Origin) correctly refused 403 | `pass-4/api-previews.log` | **FAIL (F2)** |
| 4 | XRv9k read-back before restart | 22:31:48 | Loopback0 `10.255.0.4/32` present; OSPF 2 neighbours FULL | `pass-4/xrv9k-readback-pre.log` | PASS |
| 4 | `check_restart_device.py --device xrv9k --links 2 --ready-budget 1200` | 22:31:54–22:48:56 (17.0 min) | `28 checks, 0 failed` — review named the XRv9k known limit before confirmation; readiness `booting` (22:32:18) → `ready` (22:48:51) with **no `failed` state in between** (QA-019) | `pass-4/xrv9k-2026-09-27T223154+0000.json`, 4 screenshots, `pass-4/check_restart_device-xrv9k.log` | PASS |
| 4 | XRv9k read-back after restart | 22:49:10 | `% No such configuration item(s)` for Loopback0; no OSPF neighbours — the documented QA-017 first-restart-after-deploy behaviour (this pass's assigned, non-finding expectation), not reproduced as a fresh finding | `pass-4/xrv9k-readback-post.log` | PASS (expected) |
| 4 | Reapply configuration A (`nodecli.py xrv9k --file …/xrv9k.cli --tag pass4-configA`) | 22:49:18–22:49:27 | committed on the **first attempt**, no refusal | `pass-4/xrv9k-reapply-configA.log` | PASS |
| 4 | Read-back after reapply | 22:49:51–22:50:22 | Loopback0 `ipv4 address 10.255.0.4 255.255.255.255` back; `router ospf 1` shows router-id `10.255.0.4`, area 0 with Loopback0 (passive), Gi0/0/0/0 and Gi0/0/0/1 (point-to-point) — configuration A fully restored for the next pass. (One transient `paramiko` "Error reading SSH protocol banner" on the first connection attempt, silently retried by `nodecli.py` itself; the read-back that followed succeeded and is the one recorded) | `pass-4/xrv9k-readback-after-reapply.log` | PASS |
| 5 | Defect ledger spot check | 22:35:26–22:36:29 | see below | `pass-4/ledger-*.log` | PASS |

## Live-run detail

- **cEOS** (`pass-4/ceos-2026-09-27T221703+0000.json`): three restart jobs, all `succeeded · 3 links
  restored`, container id `0e70068d3675` kept throughout (`started` advancing 22:00:07 → 22:17:24 →
  22:18:02 → 22:19:10, one per restart). Map entry point (job `5ef6805b19324328a6cb00e8a6ea98b8`), Devices/keyboard
  entry point (job `8195f2008392480580b17dc5cd5e2b4c`), then `containerlab stop --node ceos` followed by a
  restart through the product (job `c4e98e1da842434f8b9d773bcd2065d6`). Browser CLI disconnect/reconnect with
  no replay; a new capture resolved the restarted device's interfaces.
- **Neighbour check** (`pass-4/neighbour-ceos-containerlab-20260927T222833+0000.json`, `--stop-mode
  containerlab` only, per the hard rule): host1 stopped, links parked; the review named host1 and both
  cases (parked vs destroyed); the API preview carried the same warning; job `3 links restored` (the parked
  link came back); host1 then restarted through the product with its own link count; ceos ended with all 3
  links once host1 was back. 20/20, 0 failed.
- **XRv9k** (`pass-4/xrv9k-2026-09-27T223154+0000.json`): job `607907d277fd496d99ac1676e51cb936`,
  `succeeded · 2 links restored`, container id `5706950aa8de` kept (`started` 22:00:07 → 22:32:15). Readiness
  timeline: `["2026-09-27T22:32:18+00:00","booting"]` → `["2026-09-27T22:48:51+00:00","ready"]` — straight
  through, no `failed`, 16.5 minutes total (within the 1200 s / 20 min budget). Review named the known limit
  verbatim before confirmation. 28/28 checks, 0 failed.
- **Two tabs** (host1): see Findings F1 below — 13 checks run, 1 consistently failed across three attempts.
- **API previews**: `token`s issued: vjunos-switch `070ac44f20614a67a3a7a011073e2340`, xrv9k
  `eff1f19d8ee34a44b09e2ff1e371a250`, ceos `ca351b130adc4898908d4bb0d9f6fd90`; operation job count 137 before
  and after all three previews (no job created by a preview). Refusals: node of another lab → 404 "This
  device is not in the lab."; unknown node → 404 same message; no-`Origin` request → **200** with token
  `4e45b7031c204287b7af3d8be16bc698` (Finding F2); control (mismatched `Origin: http://evil.example.com`) →
  403 "Use this manager from its own browser page." as expected.

## Traffic-probe loss windows

`pass-4/ceos-traffic.jsonl`, 68 rows, 22:16:40–22:24:36, source cjunosevolved, crossing target
10.255.0.1 (ceos loopback), other target 10.255.0.3 (a path that does not cross ceos).

- Crossing-path loss windows: `22:17:13–22:17:51` and `22:18:06–22:19:42` (the second includes a `null`
  sub-window `22:19:18–22:19:42` — `containerlab stop --node ceos` then the restart, the device genuinely
  down, not just mid-restart). These line up with the three cEOS restarts run in this pass (map ~22:17:03,
  Devices-view ~22:17:24–22:18:02, stop+restart ~22:18:02–22:19:40).
- Other-path loss: **0 across every row** — the non-crossing path was never affected.
- `ssh_ok: true` on every row — the probe's own source (cjunosevolved) was never affected.

## Defect ledger spot check

Mandatory: QA-017, QA-018, QA-019, TOOL-002. Five of my choice: RD-001, RD-003, RD-004 (via RD-001/003's
tests plus the live API-preview `path` refusal replayed in my own adversarial check), QA-014, QA-016.

| ID | Regression test | Run alone | Behaviour observed in this pass |
|---|---|---|---|
| QA-017 | `test_lab_operations.py test_the_xrv9k_review_names_the_fresh_disk_limit_and_other_kinds_get_no_note` | OK | Live: the XRv9k review named the known limit verbatim before confirmation (API preview and browser review both); the post-restart read-back showed the factory-fresh loss (`% No such configuration item(s)`) — exactly what this pass's own instructions named as the expected, non-finding outcome for the first restart after the 22:00 redeploy |
| QA-018 | `test_lab_operations.py test_a_neighbour_that_is_not_running_is_named_in_the_review_and_the_job_counts_the_links` | OK | Live: the neighbour check's review named host1 and both cases; the job counted the links; matches |
| QA-019 | `test_node_readiness.py` (22 tests) | all OK | Live: the XRv9k readiness timeline went straight `booting → ready` with no `failed` state, matching the fixed grace-window behaviour |
| TOOL-002 | source inspection: `check_restart_device.py:184` (`argv.count('--node') == 1`, exact match) and `:322` (`'failed' not in words`) | inspected, both hold | Both assertions fired correctly in every live run this pass — the argv check passed on ceos/xrv9k/neighbour runs, and no run showed a `failed` readiness state slipping through |
| RD-001 | `test_lab_operations.py test_a_restart_device_review_is_stale_when_a_lifecycle_job_lands_during_its_own_helper_calls` | OK | Tests the *preview-time* staleness (a lifecycle job appearing while the helper's own preview call is in flight → 409). This pass's Finding F1 is a **different** code path (the *confirm-time* guard, `lab_operations.py:280`) that this regression test does not cover — see F1 |
| RD-003 | `test_lab_operations.py test_restart_device_binds_every_container_naming_shape_exactly` | OK | Not separately exercised live this pass (no crafted container-name request against the live product); the unit test alone stands in |
| RD-004 | (no single named unit test; covered by the `path`-refusal behaviour) | replayed live via my own adversarial check (fixture) and confirmed live via `check_restart_neighbour.py`'s review/known-limit checks | The client-supplied `path` refusal (400, "Restart device uses the lab's own topology file.") was directly reproduced by my own adversarial script against the fixture |
| QA-014 | `test_lab_operations.py test_a_restart_whose_container_exits_right_after_is_a_failed_job_with_the_reason` | OK | Not reproduced live (vJunos-switch was never restarted, per the hard rule); the live API preview's verbatim known-limit warning stands in, as in prior passes |
| QA-016 | `test_design_intent.py test_engine_identifiers_follow_netlabs_16_character_rule` | OK | Directly observed live (fixture, real netlab engine) via `stress_design.py bulk`'s 16/17-character boundary checks (both passed) |

## Findings

### F1 — `check_restart_two_tabs.py` (host1): the older-tab's stale-review refusal reads the generic busy message instead of "Another lab operation ran after this review", reproducible 3/3 attempts

**Command:** `docs/netlab-ui-qa/tools/check_restart_two_tabs.py --url http://127.0.0.1:8081 --lab
restore-square --device host1 --out pass-4/` (run three times: 22:20:05, 22:21:21, 22:26:44).

**Expected** (per the tool's own docstring and DEFECTS.md RD-001): after tab A's double-click job finishes,
tab B confirms its now-stale review and gets refused with `"Another lab operation ran after this review.
Review the restart again."` (`lab_operations.py:499`).

**Observed:** all three runs, tab B's confirm returned `"Wait for the current lab operation to finish."`
(the generic busy message from `guard()`, `lab_operations.py:280`) instead. Run 1 crashed entirely
(Playwright `Locator.click: Timeout 30000ms exceeded` on the *next* map-menu click, because the Restart
button stayed disabled with that same message for the full 30 s). Runs 2 and 3 completed with `13 checks, 1
failed`, always the same check ("the older review is refused with the reason").

**Root-cause investigation (source-level, no fix applied):** `LabOperations.confirm()`
(`lab_operations.py:481-499`) calls `self.guard(preview['lab_id'])` *before* the stale-review check at
line 497-499. `guard()` (`lab_operations.py:279-282`) evaluates `operation_busy(self.store.state)` **with no
`lab_id` argument**, so it is scoped globally across every lab's `operations`/`design_jobs`/`git_jobs`/
`restore_jobs`, not just `restore-square`'s. Live polling of `/api/state` at 1.5 s intervals during a fresh
repro (`pass-4/two-tabs-diag-run.log`) found two separate ~2–3 s busy windows (one for tab A's own
double-click job, a second, later one for step 4's simultaneous-confirm race) with an apparently idle
5–8 s gap between them in which the observed API showed no busy job of any kind — yet tab B's confirm inside
that gap still returned the generic busy message. This means `self.active` (the in-process set gating
`guard()`, `lab_operations.py:266,694,774`) outlives the job's terminal `status='succeeded'` becoming visible
to API clients by a margin the 1.5 s polling did not resolve. I could not narrow this further without
instrumenting the server process, which is out of scope for a verification-only pass. This is **not**
`RD-001`'s regression test (`test_a_restart_device_review_is_stale_when_a_lifecycle_job_lands_during_its_own_helper_calls`),
which exercises the *preview-time* staleness check only (`lab_operations.py:464-466`); the confirm-time path
at line 497-499 appears to have no unit-test coverage for the scenario this tool actually drives (a stale
review racing a real, already-finished job, both hitting `confirm()`).

**Impact:** P2/P3-shaped in isolation (a wrong-but-still-negative message: the older review is correctly
*not* honoured, no double restart occurs, no data is lost — `"no second job and no second restart"` still
passed in both completed runs), but user-visible and directly contradicts the documented/tested behaviour
in `DEFECTS.md` RD-001 and the tool's own docstring. On a busier manager (this shared VM had many other
labs' historical job records), a real second browser tab could show "Wait for the current lab operation to
finish" for longer than the ~1-2 s a student would expect, right after an operation they can see has already
finished.

**Evidence:** `pass-4/check_restart_two_tabs.log` (all three runs), `pass-4/two-tabs-diag-run.log`
(the 1.5 s polling repro), `pass-4/two-tabs-host1-2026-09-27T222121+0000.json`,
`pass-4/two-tabs-host1-2026-09-27T222644+0000.json`, `pass-4/two-tabs-stale-review.png`.

### F2 — `/api/operations/preview` accepts a mutating request with no `Origin` header at all (200, valid token), where the assignment's acceptance criterion requires a 4xx refusal

**Command:** `curl -X POST http://127.0.0.1:8081/api/operations/preview -H "Content-Type: application/json"
-d '{"action":"restart-node","lab_id":"174386ec12ee496190c585c5796b2662","node":"clab-restore-square-ceos"}'`
(no `Origin` header at all) at 22:31:12Z.

**Expected** (this pass's assignment, step 4): "a request without Origin. Every refusal must be a 4xx with
no token."

**Observed:** `HTTP 200` with a full preview body including a valid, usable `token`
(`4e45b7031c204287b7af3d8be16bc698`). A control request with a **mismatched** `Origin` (`http://evil.example.com`)
*was* correctly refused (`403 "Use this manager from its own browser page."`), confirming the guard is
active and this is not a total guard failure.

**Root cause (source-level, `clab-backup-ui/app/main.py:96-101`):** the `guard()` middleware only refuses a
request when the `Origin` header is *present and mismatched*, or when `Sec-Fetch-Site: cross-site` is sent:
```python
origin=request.headers.get('origin')
if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin.rstrip('/') != str(request.base_url).rstrip('/')):
    return JSONResponse({'detail':'Use this manager from its own browser page.'},status_code=403)
```
An absent `Origin` header short-circuits both conditions to `False`, so the request proceeds. This matches
the documented invariant in CLAUDE.md verbatim ("a mutating request needs a body; content-length 0 is
refused... every WebSocket checks Origin itself") — the primary defence for HTTP routes is the
required-JSON-body/Content-Length check (relying on browser CORS preflight to block a real cross-site
attacker from sending a JSON body), not an Origin-presence requirement. I cannot tell from source alone
whether this pass's specific acceptance wording ("a request without Origin" must be a 4xx) reflects a
stricter intended behaviour for the restart-node endpoints specifically (no such origin-presence check
exists anywhere in `lab_operations.py`) or is a documentation mismatch in the assignment; either way, the
literal behaviour tested did not meet the stated criterion, so it is reported as a finding rather than
silently reconciled.

**Impact:** low as an actual security boundary (a same-origin browser's own fetch/XHR calls send `Origin`
for state-changing methods regardless, and a real cross-site attacker's browser cannot omit it either — this
mainly affects non-browser callers, e.g. curl/scripts on the same host, which are not the threat model
`guard()` targets), but it is a literal, reproducible mismatch against this pass's acceptance wording, and no
job was created by it (job count unchanged, 137→137) so it is not a bypass of the reviewed-action contract
itself, only of the Origin check specifically.

**Evidence:** `pass-4/api-previews.log`.

## Observations

- Two of my own runs (`stress_design.py bulk` and `coverage_run.py`) crashed on their first attempt because
  I omitted the venv's `bin` from `PATH` (`netlab is not on PATH`); this is my own tooling mistake, not a
  product or campaign-tool defect, and is recorded here only for transparency. The corrected re-runs (with
  `PATH="$PWD/clab-backup-ui/.venv/bin:$PATH"`) are the results counted in the Steps table above.
- `check_restart_two_tabs.py`'s first attempt (22:20:05) crashed with an unhandled Playwright timeout rather
  than recording a clean `FAIL` and continuing — the script's `check()` helper does not raise on failure, so
  execution continued into a later step whose own 30 s wait then hit the still-busy button and raised an
  uncaught `TimeoutError`, aborting the whole record with no JSON output for that attempt. Worth the
  maintainer's eye alongside F1: a `try/except` around the post-assertion steps (or shortening the click's
  own timeout) would let a run like this still produce a complete JSON record instead of an unhandled crash.
- The shared, long-running VM's `operations` history (137 entries spanning back to 2026-09-22, many labs)
  made the global (not per-lab) scope of `operation_busy()` inside `guard()` easy to notice during F1's
  investigation; this scope is a documented, intentional invariant ("one process, one lock") and is not
  itself reported as a finding.

## Not run or blocked

Nothing was skipped. Every step in the charter and the pass-specific instructions ran to completion,
including the mandatory XRv9k configuration-A reapply and its read-back.

## Verdict: NOT CLEAN

Two findings (F1, F2), both reproducible with a command and evidence file above.
