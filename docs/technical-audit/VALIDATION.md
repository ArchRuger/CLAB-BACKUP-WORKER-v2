# Technical audit: validation record

What was actually run, by evidence class: **static** (read or searched), **unit** (Python and `node:test`
suites), **fixture** (the fixture manager in a browser), **CI**, **live** (the dev VM, its lab, a Git remote).

## Baseline (base `main` `b1ced1d`, 1.30.38, 2026-09-23)

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -t tests` (venv, `PATH` prefixed) | 1096 tests OK, 1 skipped (opt-in EOS SSH fixture), 95.7 s, 227 MB peak RSS |
| `node --test tests/*.js` (Node 18) | 274 pass, 0 fail |
| `python3 deploy/verify-release.py` | passes (1.30.38) |
| `python3 docs/maintenance-audit/tools/check_links.py` | 132 files, 0 problems |
| CI on `main` `b1ced1d` | success (run 35843059851, 4 m 7 s) |
| Live manager | `/api/state` 1.30.38, helpers 1.30.38; telemetry API reports cEOS streaming, cJunosEvolved failed (subscription rejected, 76 attempts), XRv9k failed (548 attempts, 30 s retry), two unsupported |
| Listening ports | 8081 (manager), 9090 (Prometheus, loopback), 5001/5801 (capture, loopback); 3000 closed (Grafana exited) |
| Disk | 50G used / 19G free of 72G; Docker images 24.1 GB (grafana-oss 1.47 GB, prometheus 372 MB) |

## Routing (observed from subagent transcript metadata)

Evidence: the `"model"` fields of each worker's transcript under the session's task directory, counted with
`grep -o '"model":"[^"]*"' <task>.output | sort | uniq -c`; no route was inferred from an agent's self-description.

| Task | Agent definition | Requested | Observed | Result |
|---|---|---|---|---|
| Director (scope, integration, releases, records, commits) | session | claude-fable-5-1 | the session runs as Fable 5.1 (`CLAUDE_CODE_EXECPATH` 2.1.280, project settings model `claude-fable-5-1`) | pass |
| Retirement migration module and its tests | `clab-opus-specialist` | claude-opus-5-5 | `claude-opus-5-5` (120 turns) | pass |
| Backend removal | `clab-ui-builder` | sonnet | `claude-sonnet-5` (187) | pass |
| Deploy tooling removal and the teardown script | `clab-ui-builder` | sonnet | `claude-sonnet-5` (254) | pass |
| Frontend removal and the migration notice | `clab-ui-builder` | sonnet | `claude-sonnet-5` (201) | pass |
| Guides | `docs-auditor` | sonnet | `claude-sonnet-5` (328) | pass |
| Read-only audits AU1 (backend), AU2 (frontend), AU3 (helpers, deploy, dependencies), AU4 (tests, CI, docs) | `clab-ui-qa` | sonnet | `claude-sonnet-5` (123, 199, 179, 392) | pass |
| Risk review of the removal, the migration and the teardown | `risk-reviewer` | claude-opus-5-5 | `claude-opus-5-5` (103 at the time of the count) | pass |

Haiku (`clab-ui-scout`, `mechanical-editor`) was not needed in chunk 1: the inventory was produced by scripts
(`git grep`, `wc`, `pip show`, `docker inspect`) and the decided mechanical edits were small enough for the lead.

## Chunk 1 (1.30.39, `73c6712`): telemetry and Grafana retired

| Check | Class | Result |
|---|---|---|
| Full suites on the committed tree | unit | Python 1078 OK (1 skipped), browser 281 OK, every deploy-script suite OK with the system python |
| Release check, links, `bash -n`, `node --check`, `git diff --check`, CI list versus `tests/` | static | clean; only the opt-in `test_eos_ssh.py` is outside CI |
| Upgrade rehearsal on the isolated copy of the pre-change data (`tools/upgrade_rehearsal.py`) | unit on real data | PASS: protected fields identical, ledger kept for `cjunosevolved` (1), idempotent |
| Risk review (Opus 5.5) | review | 2 must-fix + 7 should-fix, all applied (VALIDATION.md of the app has the list) |
| VM upgrade through `start-manager.sh` from the 1.30.39 worktree | live | stack removed as the dry run listed; second pass after the recreate archived the recreated maps folder; manager and helpers 1.30.39 |
| Absence on the VM | live | no labelled container/volume, images gone, ports 3000/9090 closed, `.env` without `TELEMETRY_*`, retired helper mode refused, no `telemetry` key in `/api/state` |
| Health check (`check-install.sh`, ordinary account) | live | 61 PASS, 1 WARN (folder-coverage cap, pre-existing), 0 FAIL; *Retired telemetry stack* PASS |
| Resources | live | manager idle 72 MiB / 44 threads → 52 MiB / 10 threads; image 525 → 494 MB; 1.85 GB of images freed |
| Browser checks, device-line removal, retained workflows | live | Sonnet QA, `tools/check_release_1_30_39.py`: 142 PASS / 0 FAIL / 3 INFO (`evidence/r39-live-qa.md`, `.json`, six screenshots) |
| Independent device read-back after the removal | live | `nodecli.py` on cjunosevolved: only `set system services ssh`; extension-service empty |
| Single-node restore after a deliberate drift | live | cEOS restored from commit `a46b956` in 6 s, `verified`, drift gone on read-back (`evidence/r39-restore-ceos.json`) |
| CI | CI | push run 35852987703 and PR #54 run 35853033263 both green (2 m 56 s and 3 m 16 s, about a minute less than before without the Grafana smoke) |
| Not exercised live in this chunk | | four-node parallel restore, failure harnesses, lab builder publish/revise, map editor (unchanged code; final integrated pass) |

## Chunks 2 to 4 (1.30.40 `f21125e`, 1.30.41 `e192ead`, 1.30.42 `0cd18a7`)

| Check | Class | Result |
|---|---|---|
| Full suites at each commit | unit | 1.30.40: Python unchanged (1078), browser 281; 1.30.41: browser 281, deploy suites 57+7+15+38; 1.30.42: Python 1134 OK (1 skipped), browser 281, every deploy suite OK |
| Release check, links, `bash -n`, `node --check`, `git diff --check` at each commit | static | clean each time |
| CI (push and pull request) | CI | green for `f21125e`, `e192ead`, `0cd18a7` (about 3 minutes each) |
| Fixture browser evidence for the frontend fixes (1.30.40) | fixture | favourite star pixel-sampled in both states; wires and link click; `verify_after.py` 97 of 97 at three viewports (Sonnet builder, scratch `FIXTURE_DATA`) |
| Editor bundle after the dependency overrides (1.30.41) | build + browser | Node 24 rebuild reproducible (`--check`, 132 files), `npm audit` 0 (was 5), CI rebuild green; Playwright smoke on the rebuilt bundle 9 of 9 (blank lab, palette drag, link, YAML panel, map editor on the map fixture) |
| Risk review of the backend chunk (1.30.42) | review | Opus: 1 must-fix + 6 should-fix, all applied; the reviewer's reproducers (`rr2mod.py`, `git_lock.py`, `restore_size.py`) and fuzzers rerun clean on the final code |
| Redaction measurements (1.30.42) | unit | 65 µs per 4 KiB chunk, 120 of 120 live lines, 80,000 + 60,000 fuzz cases equal to whole-output redaction |
| VM upgrade to 1.30.42 through `start-manager.sh` (already-retired case) | live | both teardown passes "nothing to retire"; manager and helpers 1.30.42; state intact (1 lab, 38 jobs, 5 Git jobs, 12 restore jobs, 44 operations); 5 of 5 nodes ready; idle 53 MiB / 10 threads; image 494 MB with 30 Python packages (pygnmi and its three exclusive transitives gone) |
| Integrated live QA, restore harnesses, fresh-install VM | live | recorded in the chunk 5 section below |

## Chunk 5 (final integrated pass on the 1.30.42 build)

| Check | Class | Result |
|---|---|---|
| Integrated browser, API, builder and map checks (`tools/check_release_1_30_42.py`) | live | 149 checks, 0 FAIL, 1 INFO (`evidence/r42-live-qa.md`, eight screenshots) |
| Pair upload through *Upload a lab file* to the real VM; pair dropped into the lab builder | live | both proven in a real browser (`r42-C1-upload-review.png`, `r42-C2-builder-drop-pair.png`): the earlier stream's two open gaps |
| Builder publish, revise, import, manager-only removal; map editor save and reload | live | PASS (`r42-C3-*.png`) |
| Fresh install on a brand-new Ubuntu 24.04 nested VM (`tools/fresh_install_vm.py`) | live, isolated | six phases, health check 54 PASS / 0 FAIL, *Retired telemetry stack* PASS, repeat upgrade idempotent, reboot cycle, VM connection from the fresh manager (`evidence/r42-fresh-install.md`) |
| Four-node parallel restore from `f12421e` and from `27ccd71` | live | all `verified`, targets overlapped (`r42-restore-all-four-to-a.json`, `r42-final-restore-to-a.json`) |
| Foreign change during the restore (`mixed_failure.py`) | live | `partial`: three verified, XRv9k refused unchanged, foreign change rolled back by itself, recovery verified (`r42-mixed-failure-xrv9k.json`) |
| Connection loss to one node during the restore (`isolation_all_four.py`) | live | three verified, the victim `failed` with no change, iptables clean (`r42-isolation-xrv9k.json`) |
| Management cut during the confirm reconnect, 2 minutes (`armed-cut`) | live | late confirmation inside the 5-minute window, no rollback (`r42-armed-cut-cjunosevolved.json`) |
| Restart recovery (`restart-confirming --node ceos`) | live | manager restarted at `confirming`, back in 1 s, job `interrupted` then rechecked to `verified`, read-back A (`r42-restart-confirming-ceos.json`) |
| Rollback read-back (drift to B, cut longer than the 5-minute timer during the confirm reconnect) | live | the device undid the change itself; the manager reported `rolled_back` only after reading B back; job `failed`, nothing restored (`r42-armed-cut-cjunosevolved-rollback.json`) |
| Final restore of all four nodes to A and read-back | live | `succeeded`, all `verified`, 0 missing / 0 extra statements per node against the saved folder; iptables clean |
| VM folders created by the QA | cleanup | `BGP_TheoryToPractice.clab.yaml(+annotations)` and `qa42-builder/` removed from the trusted root by the lead |
