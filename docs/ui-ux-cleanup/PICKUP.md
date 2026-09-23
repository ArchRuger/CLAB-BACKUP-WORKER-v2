# UI/UX cleanup (Setup Script Cleanup Log): pickup file

Work stream started 2026-09-23 from the user's *Setup Script Cleanup Log* PDF (25 pages; the PDF itself is
not committed). Read this file first, then `REQUIREMENTS.md` (page → requirement → status) and
`VALIDATION.md` (what was actually run).

## Branch, version, commits

- Branch `claude/ui-ux-cleanup` from `main` `c0851b7` (release 1.30.35). Remote: ArchRuger/CLAB-BACKUP-WORKER-v2.
- Current release: see `clab-backup-ui/VERSION`. Chunks bump +0.0.1 each with `deploy/set-release.py`.
- Working commit / remote commit: (updated per chunk below).

## VM state (clab-llm-dev2, 2026-09-23)

- Disk before cleanup: 51G used / 18G free of 72G (the prompt's "62.4 GB used of 75 GB" was measured
  differently; `df` is authoritative). After cleanup: 41G used / 28G free. Removed: Docker build cache
  (6.5 GB), 14 superseded local manager images `clab-backup:1.29.1 … 1.30.33` (about 5 GB of unshared
  layers; the running `clab-backup:1.30.35` and the in-use `clab-capture-service:1.29.1` were kept),
  the APT package cache (0.5 GB). Nothing under `/srv`, no node images, no volumes, no checkouts, no
  archives were touched. The journal (1 GB, active files) was left alone: the target was met.
- Manager `http://127.0.0.1:8081` runs 1.30.35 with helper 1.30.35; VM connection configured
  (127.0.0.1:22, clab-discovery, helper mode). No lab deployed at start; `link-basics` is staged under
  `/srv/containerlab-node-manager/projects/`; `restore-square` topology is in
  `projects-archive-2026-09-22/` (see `docs/student-quick-start/PICKUP.md` for every archive).
- Student quick-start guide: out of scope; not modified.

## Claude routing (VM-local, uncommitted by the user's earlier choice)

- Claude Code 2.1.280 (native, `~/.local/bin/claude`), the minimum for Opus 5.5. Backup of the files
  changed: `/home/clabllm/.claude/backups/routing-20260923T004844Z` (`MANIFEST.txt` lists them).
- Project `.claude/settings.json`: model `claude-fable-5-1`, env `ANTHROPIC_DEFAULT_FABLE_MODEL`,
  `ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-5-5`, `CLAUDE_CODE_SUBAGENT_MODEL=sonnet`, force `0`;
  `availableModels` adds `claude-opus-5-5` and `claude-fable-5-1` to the aliases. User file: the stale
  forced `CLAUDE_CODE_SUBAGENT_MODEL=claude-fable-5-1` reconciled to `sonnet`; its allowlist kept
  `claude-fable-5-1` and gained `haiku`, `sonnet`, `claude-opus-5-5`.
- Agents: `clab-ui-reviewer` and `risk-reviewer` pinned to `claude-opus-5-5` (tools unchanged, still
  read-only); new `clab-opus-specialist` (`claude-opus-5-5`, no tool restriction). Policy in
  `.claude/rules/fable-opus-routing.md`; `clab-ui-routing.md` reconciled.
- Observed routes: see VALIDATION.md "Routing".

## Chunks

| Chunk | Content | Release | Commit | Status |
|---|---|---|---|---|
| 0 | baseline, cleanup, routing, requirement map | none (no shipped content) | (in 1.30.36) | done |
| 1 | A2–A7, B1, B2, B4–B7, D1 (setup, onboarding, import, deploy review, notices, multitool, device rail, capture mapping) | 1.30.36 | `f47d3b8` + records commit | done; B3 and a helper must-fix carried to 1.30.37 |
| 2 | A1, B3, helper hardening, E1–E7, D2, C1–C4 (Junos .cfg, preview size, save labels/destination/diff, restore diff/stages/parallel, Test logins, lab builder) | 1.30.37 | `96b72d7` (CI green, PR #53) | done; live records in the 1.30.38 entry |
| 3 | D2 eligibility fix (backup-excluded hosts are login-tested) + 1.30.37 live records | 1.30.38 | | in progress |

## Live validation resources (2026-09-23)

- Lab `restore-square` (four images + `host1` multitool) deployed from `/srv/containerlab-node-manager/projects/restore-square/`
  and imported (lab id `174386ec12ee496190c585c5796b2662`); configuration A applied with `nodecli.py`; the manager runs
  the build of the release under test from a clean worktree `~/projects/clab-manager-<release>` (the VM's `.env` copied
  in). The `clab-discovery` password was reset during the A7 live check (kept in the manager's encrypted store; not
  written anywhere else).
- Known follow-up outside this stream: `docs/student-quick-start/tools/capture_scenario_b.py` waits for the removed
  read-only View YAML dialog (`#builder-yaml-text`); the guide itself is out of scope here.

## Lab and repository state left (2026-09-23 03:40 UTC)

- `restore-square` deployed, all four NOS nodes at configuration A (read back 0/0 against the "Configuration A"
  commit), `host1` Ready; bound in the manager to `restore-square/qa-1-30-37` of `~/labs/CLAB-MNGR-DEV-LLM`
  (remote `pruger-dev/CLAB-MNGR-DEV-LLM`, commits "Configuration A" `f12421e6…` and "Configuration B" pushed by the
  QA pass). Worktrees `~/projects/clab-manager-1.30.3x` hold the built commits; the manager container was last
  recreated from the newest worktree's compose file (same project name, so `deploy/recreate-manager.sh` from the main
  checkout keeps working).
- Superseded local images were removed after each rebuild; disk stays around 20 G free with the five-node lab running
  (its writable layers hold about 8 G).

## Exact next action

Build 1.30.38 from its worktree, run the D2 live recheck (`ssh-check-all` includes `host1`), add the records commit,
push, check CI, update PR #53's description; then remove the older worktrees. The stream is complete after that.
