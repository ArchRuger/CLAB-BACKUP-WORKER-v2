---
name: visual-lab-builder
description: "Visual lab builder (SR Labs clab-ui embed) — built and released as 1.30.0 on 2026-09-20, PR #39; where the pickup file, research and tools live, and what is still open"
metadata: 
  node_type: memory
  type: project
  originSessionId: 2b0e597f-39bf-4403-8d37-3e4a96f0a0a9
  modified: 2026-09-20T02:26:42.909Z
---

The visual lab builder was approved on 2026-09-20 (all recommended defaults) and built the same day on branch `claude/visual-lab-builder`, released as **1.30.0**, pull request **#39** on ArchRuger/CLAB-BACKUP-WORKER-v2 (the user merges). `docs/lab-builder/PICKUP.md` in the repo holds the decisions, progress and the "open after this release" list; the 1.30.0 section of `agent instructions.md` holds the facts to preserve; `docs/LAB-BUILDER.md` is the user guide.

Shape: `@containerlab/clab-ui` 0.3.2 pinned exactly and embedded unmodified on `static/lab-builder.html` with our own host (`clab-backup-ui/lab-builder/src/main.tsx`, editing engine in the page); drafts in browser localStorage; reviewed save through new helper actions `publish` / `revise` in `host_operations.py`; assets prebuilt and committed (`node build.mjs`, `--check` compares the manifest; Node 24 portable in `~/research/lab-builder/tooling/`).

Research, the independent review, the feasibility report, the prototype and all evidence are outside the repo in `~/research/lab-builder/` (persistent; `/tmp` was wiped by an unexpected VM power-off on 2026-09-20).

**Why:** a later session will be asked to extend or upgrade this; the non-obvious constraints (script-src stays 'self', never flush drafts on a timer, controls hidden by data-testid with a guarding test, svg max-width override) are easy to break.

**How to apply:** validate any change with `docs/lab-builder/tools/student_workflow.py` against the fixture manager (38 checks) and, when the helper changes, live with `--base http://127.0.0.1:8081 --template "Linux host" --job-timeout 240000`; the live dev VM runs 1.30.0 from this branch since 2026-09-20. Still open: deploy a builder-made lab with router images; `setup-operations.sh` has no `--refresh` flag (run it without options, then `setup-engineer-access.sh --refresh`). The user allowed live testing on this VM for this feature. Subagents must be told explicitly: no sudo / docker / paths outside the repo unless the task needs it (two readers overstepped a read-only brief). See [[user-pr-workflow]], [[dev2-host-environment]], [[fixture-manager-browser-validation]].
