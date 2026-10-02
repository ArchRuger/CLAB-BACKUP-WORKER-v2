---
name: ui-ux-cleanup
description: "Setup Script Cleanup Log stream (2026-09-23): releases 1.30.36–1.30.38 on claude/ui-ux-cleanup, PR #53, VM/lab state, routing proven, where to pick up"
metadata:
  node_type: memory
  type: project
  originSessionId: 2fd88c6a-6cb4-4603-bd5a-34ee38ac3bcd
  modified: 2026-09-23T03:40:07.770Z
---

Done 2026-09-23 on `claude/ui-ux-cleanup` (from `main` `c0851b7` = 1.30.35), PR #53: 1.30.36 (`f47d3b8` + records
`aa36ea5`: setup defaults/exit, apt_lock.py, Git onboarding, lazydocker, VM-connection seed, map upload, Lab Builder
return, deploy review, notices, multitool login, device rail, capture port mapping), 1.30.37 (`96b72d7`: helper
hardening of the `create` map-file write, Junos `.cfg` snapshots, preview size, save labels/destinations/diffs, restore
diff/stages/parallel (default 4 workers), Test logins, lab builder blank canvas/drop/editable YAML), 1.30.38 (D2
eligibility fix + the 1.30.37 live records). Working record: `docs/ui-ux-cleanup/` (REQUIREMENTS.md page map, PICKUP.md,
VALIDATION.md, `evidence/`, `tools/`, `design/restore-parallel-design.md`).

**Why:** the user's 25-page PDF of fixes; +0.0.1 per chunk; Opus review of consequential changes; live proof on the
four-image lab; Fable directs, Opus 5.5 selectively.

**How to apply:** read `docs/ui-ux-cleanup/PICKUP.md` first. VM: lab `restore-square` (+ `host1` multitool) deployed at
configuration A, bound to `restore-square/qa-1-30-37` in `~/labs/CLAB-MNGR-DEV-LLM`; the `clab-discovery` password was
reset by the A7 live check (in the manager's encrypted store only); worktrees `~/projects/clab-manager-1.30.3x` hold the
built commits (remove when done). Routing proven from transcript metadata: scouts Haiku, builders/QA Sonnet, per-invocation
`opus` override and `clab-opus-specialist`/`risk-reviewer`/`clab-ui-reviewer` on `claude-opus-5-5`; the `.claude/` routing
files stay uncommitted (user's choice); `.claude/rules/fable-opus-routing.md` is the policy. Known follow-up outside the
stream: `docs/student-quick-start/tools/capture_scenario_b.py` still expects the removed View YAML dialog. See
[[user-pr-workflow]], [[multi-platform-restore]], [[dev2-host-environment]].
