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
