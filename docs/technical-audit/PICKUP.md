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
| 1 | Telemetry and Grafana retirement with the state, VM and device migration; markers at 1.30.39; gates green on the integrated tree; risk review requested | 1.30.39 | | integrated, awaiting the risk review, then the VM deployment and the live checks |
| 2+ | Audit-driven debt (backend/state/drivers; frontend/editor; deploy/dependencies/tests; documentation) | 1.30.40+ | | planned |

## Exact next action

Chunk 1 is integrated (working tree, uncommitted): apply the risk review's must-fix items, rerun the gates, commit,
create the worktree `~/projects/clab-manager-1.30.39`, copy the VM's `.env` in, run `sudo bash …/deploy/start-manager.sh`
(which retires the old stack before the build), verify `/api/state` 1.30.39 and helpers 1.30.39, remove the Junos
Evolved line through the lab notice, read the device back with `nodecli.py`, run `check-install.sh`, the browser QA
and the capture check, record everything in VALIDATION.md, push and open the pull request.
