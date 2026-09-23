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
| 0 | baseline, cleanup, routing, requirement map | none (no shipped content) | | in progress |

## Exact next action

Finish the requirement map from the scout reports, then chunk 1 (setup and onboarding, A1–A7).
