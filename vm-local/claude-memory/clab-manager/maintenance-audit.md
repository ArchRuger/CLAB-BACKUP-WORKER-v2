---
name: maintenance-audit
description: "Documentation audit + tech-debt cleanup (2026-09-20): branch claude/maintenance-audit from main d510b7a, releases 1.30.18 onwards one per chunk, where the record and pickup are, routing constraint found"
metadata:
  type: project
---

On 2026-09-20 the user gave a long written brief: documentation audit and bounded technical-debt cleanup, one patch release per chunk (same delivery unit as [[ui-review-001]]: checks, `set-release.py` +0.0.1, three history sections, commit, push, verify remote SHA, look at CI, continue without asking), explicit authorization to commit and push, NOT to merge, tag, deploy or publish. Their stated top priority was routing each task to the right model (Sonnet lead, Haiku mechanical, Opus risk review, Fable only for a named unresolved problem).

Found: `~/.claude/settings.json` sets `CLAUDE_CODE_SUBAGENT_MODEL=claude-fable-5-1` and `availableModels: ["claude-fable-5-1"]`, so every subagent runs on Fable whatever `model` is requested (verified with three probes; each worker costs ~80k tokens before doing anything). The brief forbade changing global settings, so the lead did deterministic/shared-file work itself and used few workers. If the user removes those two settings, the brief's routes become real.

State at the end of the session (2026-09-20): five chunks, releases 1.30.18–1.30.22, head `8aa4ee1`; the user merged chunks 1–3 as PR #44 mid-session (branch fast-forwarded to the merge); **PR #45** open for 1.30.21–1.30.22. CI green up to 1.30.21 when checked. Three project agents exist in `.claude/agents/` (docs-auditor=sonnet, mechanical-editor=haiku, risk-reviewer=opus), never exercised on their intended models.

Later the same day the user picked six open items (scaffold tool + mandatory review, image compose line, image-install docs, `lastOpened`, dead code in `host_git.py`/`restore.py` after a risk review, manager-side `unchanged` save status): done as 1.30.23–1.30.26, head `0132e0b`, **PR #46** open (#44 and #45 merged; the branch is fast-forwarded to main after each merge). Still open in AUDIT.md §5: `recreate-manager.sh` on prepared-image installs, wiring `pending_rollback_shell`, log mojibake, half-failed folder change, `CAPTURE_BIND/PORT`, vJunos-switch wording, Wiki map section, fixture helper never answers `unchanged`. Pitfall: `deploy/verify-helper.py` waits on stdin; never call it without input.

**Why:** a later session will continue or be asked about this audit, or about why routing did not happen.

**How to apply:** read `docs/maintenance-audit/PICKUP.md` then `AUDIT.md` (dispositions, workflow-to-guide map, remaining debt incl. two confirmed-by-reading defects: `deploy/scaffold-lab.py snapshot` cannot finish since the mandatory upload review; an unchanged save opens an empty review). `CLAUDE.md` no longer imports `agent instructions.md`; it has an invariant digest + routing table (do not re-import). Gates per chunk: both suites, `verify-release.py`, `docs/maintenance-audit/tools/check_links.py`, `git diff --check`, and `verify_after.py` on a fresh fixture for UI changes. `docs/maintenance-audit/` is a living-docs folder (no old release numbers; name chunks by number). Push with the ArchRuger gh account then switch back ([[user-pr-workflow]]). Browser checks per [[fixture-manager-browser-validation]]; Pillow for screenshot diffs is not in the venv (use a scratch venv).
