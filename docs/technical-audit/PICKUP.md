# Technical audit: pickup file

Read this first, then [AUDIT.md](AUDIT.md) (findings and dispositions), [FEATURE-PARITY.md](FEATURE-PARITY.md),
[TELEMETRY-REMOVAL.md](TELEMETRY-REMOVAL.md) and [VALIDATION.md](VALIDATION.md). Git and GitHub are the
authority for what is committed, pushed and merged; this file records state between sessions.

## Branch, releases, commits

- Branch `claude/technical-audit`, cut 2026-09-23 from `origin/main` `b1ced1d` (release 1.30.38, PR #53 merged).
  Remote `origin` = ArchRuger/CLAB-BACKUP-WORKER-v2. Push with the `ArchRuger` gh account, switch back to
  `pruger-dev` afterwards so lab saves keep working.
- Local uncommitted routing files (`.claude/settings.json`, `.claude/agents/*`, `.claude/rules/`, a PDF) stay
  uncommitted on purpose (the user's earlier choice); never `git add -A`.
- Releases: one +0.0.1 per chunk with `deploy/set-release.py`. Chunk table below.

## Environment (clab-llm-dev2, 2026-09-23 10:00 UTC)

- Disk 72G: 50G used / 19G free at start. Memory 67G. Docker 29.8.1. Python 3.12.3; system Node 18.19.1 (Node 24
  is only needed to rebuild the editor bundle; not installed; the bundle is not changed by this audit).
- Manager 1.30.38 (`~/projects/clab-manager-1.30.38`, worktree of `af6497f`) on `http://127.0.0.1:8081`, helpers
  1.30.38, capture stack `clab-manager-capture` running, telemetry stack `clab-manager-telemetry` present
  (Prometheus running with restart `unless-stopped`, Grafana exited, two tmpfs volumes; compose labels point at the
  removed worktree `~/projects/clab-manager-1.30.37`).
- Lab `restore-square` deployed (cEOS, cJunosEvolved, vJunos-switch, XRv9k, host1), imported as lab
  `174386ec12ee496190c585c5796b2662`, bound to `restore-square/qa-1-30-37` of `~/labs/CLAB-MNGR-DEV-LLM`.
- The old provisioner added exactly one line on `clab-restore-square-cjunosevolved`:
  `set system services extension-service request-response grpc clear-text port 32767` (four `telemetry.configure`
  events, re-added after each restore; read back over SSH on 2026-09-23 09:50 UTC; absent from the "Configuration A"
  reference). cEOS and XRv9k: `applied = 0` (their base configurations already carried gRPC).
- Recovery copies (before any migration): `/srv/containerlab-node-manager/data.pre-telemetry-retirement-20260923T095431Z`
  (state.enc and state.key checksums verified), `/srv/containerlab-node-manager/telemetry.pre-retirement-20260923T095431Z`,
  `/root/clab-env.pre-telemetry-retirement-20260923T095431Z`.

## Routing

Claude Code 2.1.280; project settings model `claude-fable-5-1`, `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`, force `0`,
`ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-5-5`; agents `clab-ui-scout` (haiku), `clab-ui-builder` / `clab-ui-qa` /
`docs-auditor` (sonnet), `mechanical-editor` (haiku), `clab-ui-reviewer` / `risk-reviewer` / `clab-opus-specialist`
(`claude-opus-5-5`). Observed routes are recorded in VALIDATION.md.

## Chunks

| Chunk | Content | Release | Commit | Status |
|---|---|---|---|---|
| 0 | Baseline, inventory, preservation matrix, records skeleton, four read-only audits (AU1 backend, AU2 frontend, AU3 helpers/deploy, AU4 tests/docs) | none | (records land with chunk 1) | done except AU4 |
| 1 | Telemetry and Grafana retirement with the state, VM and device migration; risk review applied; VM upgraded, device line removed and read back, retained workflows proven | 1.30.39 | `73c6712` (pushed; PR #54; CI green) + records commit | done |
| 2 | Backend and state debt: A-001, B-001 to B-006, T-003 | 1.30.40 | | implemented (Sonnet + Opus), gates and deployment pending |
| 3 | Frontend, tooling and guide debt: F-001 to F-006, T-001, T-002, D-001, D-002 | 1.30.41 | | implemented (Sonnet builder, docs auditor), gates pending |
| 4 | Deploy and dependency debt: S-001, S-005, D-003, S-002 evaluation (Node 24 under `~/.local/node24`) | 1.30.42 | | planned |
| 5 | Final integrated pass: four-node restore, harnesses, builder, fresh-install evidence, resource comparison, records | | | planned |

## Exact next action

Chunk 2 is in the working tree (backend: `runner.py`, `git_progress.py`, `restore.py`, `main.py`, `node_readiness.py`,
`diagnostics.py`, `lab_operations.py` and tests) together with chunk 3 (static files, `verify_after.py`, two guides).
Commit them as two releases by path: run the gates, `set-release.py 1.30.40`, write the three history sections for the
backend chunk, commit only its files; then the same for 1.30.41 with the frontend and guide files. Deploy each build
(`git worktree add ~/projects/clab-manager-<release>`, copy the VM's `.env`, `sudo bash deploy/start-manager.sh`), run
the targeted live checks (chunk 2: a lab-wide backup with the trimmed lists, an operation with output, a manager
restart; chunk 3: the Playwright tool against the fixture and the real manager at three viewports), record, push,
check CI. Then chunk 4 (deploy and dependencies) and the final integrated pass. An orphaned Wireshark container
(`clab-capture-…5f63919b…`) from a QA script bug was left to the session service's 15-minute idle expiry: confirm it
is gone before the final pass.
