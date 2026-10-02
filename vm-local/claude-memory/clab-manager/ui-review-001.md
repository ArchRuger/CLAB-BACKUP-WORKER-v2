---
name: ui-review-001
description: "UI review 001 (2026-09-20): branch claude/ui-review-001, one patch release per chunk 1.30.2–1.30.17, all eight requirements delivered, PR #43 open, where the notes and evidence are"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7e775f2a-652e-4e3b-a920-d048ad8167c5
  modified: 2026-09-20T16:40:39.375Z
---

On 2026-09-20 the user gave a written brief (their `Containerlab_Node_Manager_UI_Review_001.pdf` was NOT on the VM) with requirements UI-001…UI-008 and a mandatory delivery unit: one bounded chunk = tests + browser check + exactly +0.0.1 via `deploy/set-release.py` + CHANGELOG/VALIDATION/agent instructions + commit + push + verify remote + look at CI, then continue without asking. They explicitly authorized commits and pushes for this work. Branch `claude/ui-review-001`; they merged it up to 1.30.9 as PR #41 mid-session, I fast-forwarded the branch to that merge and continued (a second PR is still to be opened by them or on request).

State on 2026-09-20 (end of the second session): releases 1.30.2–1.30.17 pushed, CI green for all; head `3578907`; **PR #43** open for 1.30.10–1.30.17 (#41 merged up to 1.30.9). All eight requirements delivered. UI-003: the user chose a *page-level* undo history and approved an editable device look; Edit map is the builder's editor in map mode (`map-editor.html`, adapter `mapOnly` + `MAP_COMMANDS`, page dialogs *Device look…* / *Link labels…* and Undo/Redo via the adapter's `applyAnnotations` = `setAnnotationsContent` + a `topology-host:snapshot` window message). Known limit left by decision: the Topology tab keeps but does not draw line arrows, rounded text backgrounds and nested group levels (would widen the manager's drawing schema; ask first). Never exercised against real services: review-and-upload to the Git host, upload + `create`, folder move.

**Why:** a later session will be asked to continue or finish UI-003, or to open the PR.

**How to apply:** read `docs/ui-review-001/PICKUP.md` first, then `CHECKLIST.md` and `MAP-PARITY.md`; per-chunk browser checks are `docs/ui-review-001/tools/check_ui*.py` (fixture manager on a FRESH `FIXTURE_DATA` each run; restart it after any `app/*.py` change); evidence in `~/ui-review/review-001/` on the VM. The fixture's scripted Git helper was made faithful (retire, overlap refusal) because it had hidden the UI-008 bug. Rebuilding the editor bundle needs Node 24 from `~/research/lab-builder/tooling/` (`node build.mjs`, then `--check`). The dev manager was rebuilt to 1.30.17 with `sudo bash deploy/start-manager.sh --manager-only`; live checks only on the QA lab `qa-nos-105458`, never edit the user's course labs/repo without asking. See [[user-pr-workflow]], [[fixture-manager-browser-validation]], [[lab-builder-quality-pass]], [[dev2-host-environment]].
