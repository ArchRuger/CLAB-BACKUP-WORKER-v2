---
name: student-quick-start
description: "Illustrated student quick-start PDF work stream (2026-09-22): delivered at 1.30.35 on PR #51, VM changes, repos, where to pick up"
metadata:
  type: project
---

Done 2026-09-22 on `claude/student-quick-start` (from `main` 132122b = 1.30.32), PR #51: releases 1.30.33 (Scenario A +
helper identity fix `host_git.ensure_identity`), 1.30.34 (Scenario B), 1.30.35 (final PDF, 20 pages, two independent QA
replays 21/21 PASS, Opus review applied). Deliverables in `docs/student-quick-start/` (PDF, `source/guide.md`, `build.sh`
WeasyPrint pipeline, `screenshots/spec.json`, `examples/`, `tools/`, `evidence/`, VALIDATION.md, PICKUP.md).

**Why:** the user asked for a finished, validated, illustrated PDF built by executing both workflows on the disposable VM, +0.0.1 per chunk.

**How to apply:** read `docs/student-quick-start/PICKUP.md` first. VM state: old manager data in
`/srv/containerlab-node-manager/data.pre-quickstart-2026-09-22`, old lab folders in `projects-archive-2026-09-22/`, Git
registry backups `/etc/clab-manager/git.json.*`, `restore-square` destroyed (topology archived). Repos under `pruger-dev`:
`netlab-course` (public template), `netlab-course-student` (demo copy), `my-network-labs-authoring` (renamed from
`my-network-labs`), `*-qa`/`*-qa2` replay copies. Reset tools: `tools/reset_scenario_a.sh <repo>`, `reset_scenario_b.sh <repo>`.
The guide's byline states the release it was tested with (not moved by set-release.py). Routing verified from transcripts:
scout haiku, builders/QA/writer sonnet, reviewer opus, lead Fable. See [[user-pr-workflow]], [[dev2-host-environment]].
