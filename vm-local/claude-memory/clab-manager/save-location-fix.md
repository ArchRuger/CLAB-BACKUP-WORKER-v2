---
name: save-location-fix
description: "Stable Latest destination + manifest-based Apply stream (1.30.31+): branch, PR #49, contract, lab and repo state, where to pick up"
metadata: 
  node_type: memory
  type: project
  originSessionId: fbe79636-ea01-4c1c-8b25-b28ed1918326
  modified: 2026-09-22T14:51:26.859Z
---

Work stream started 2026-09-22 on `claude/save-location-fix` (from `main` `6c3e8b3` = 1.30.30): (1) a lab folder can never be
named `latest`/`baseline`/`checkpoints[/x]` and choosing an existing `…/latest` resolves to its parent, so saves never nest
`latest/latest`; (2) *Apply to running lab…* for any folder holding `manifest.json`, exact paths everywhere (leading-slash wire
form; bare reserved names keep the pre-release "this lab's own folder" meaning), the reviewed commit is the applied commit.
Release 1.30.31 = commit `8ea56e0`, PR #49 (merged by the user on 2026-09-22). Release 1.30.32 = `bd2ee6f` (records only, matrix C
all PASS on the four images), PR #50 open; the dev VM runs `clab-backup:1.30.32`.

**Read `docs/save-location-fix/PICKUP.md` first** (contract, reviews, documented limits), then `MATRIX.md` and `evidence/`.

**Why:** the user asked for both requirements with live reproduction first, routing by model (scout Haiku, builder/QA Sonnet,
reviewer Opus, lead Fable, models proven from transcript metadata), +0.0.1 per chunk, honest PASS/FAIL/BLOCKED.

**How to apply:** lab `restore-square` is bound to `save-fix/working` in `~/labs/CLAB-MNGR-DEV-LLM` (the QA fixture folders under `save-fix/` were removed again on 2026-09-22 at the user's request, commit `73c8112`; the
QA credential profile was removed too); the dev VM runs the build
of the pushed commit; `docs/redesign/tools/fixture_manager.py` must patch `restore._probe` (fixed here); run each
`check_ui00x.py` on a FRESH fixture data dir (a second run on mutated data fails on its own leftovers). The user's
`.claude/` routing files stay uncommitted. See [[multi-platform-restore]] and [[user-pr-workflow]].
