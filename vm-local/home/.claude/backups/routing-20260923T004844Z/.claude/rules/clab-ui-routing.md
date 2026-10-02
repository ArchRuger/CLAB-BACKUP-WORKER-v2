<!-- clab-ui-routing-setup-v1 -->
# Task routing (UI and full-stack feature work)

For UI work and full-stack features such as multi-platform restore, use Fable 5.1 (claude-fable-5-1) as the lead and these named subagent types:
- clab-ui-scout / haiku: bounded file, selector, reference, capability-gate and test inventory; evidence indexes.
- clab-ui-builder / sonnet: implementation, routine debugging, docs, and tests.
- clab-ui-reviewer / opus: ambiguous design, architectural risk, and consequential review.
- clab-ui-qa / sonnet: independent behavioral, browser and (when assigned) live-device verification.

Invoke these definitions by their exact names. Keep each definition's model;
do not override it without a task-specific reason and disclose substitutions.
Use scripts for deterministic checks. Do not use premium models for inventory.
Agent definitions select execution defaults; semantic routing remains a lead
responsibility, not an automatic classifier or a guarantee of account access.
Keep the fallback for unassigned subagents on Sonnet, not the lead's model.

Before delegation, state task, agent, requested model, scope, and acceptance
check. Verify the effective model in tool/task metadata when exposed; otherwise
report it as unverified. Reuse targeted evidence rather than sending every worker
the full history. Keep two or three independent workers active when useful;
use disjoint file ownership or worktrees and avoid recursive delegation.

The lead integrates results and owns shared files, release markers, commits,
pushes, and pickup notes. Follow the active task's authorization and existing
patch-checkpoint workflow. These rules do not themselves authorize Git writes.
Preserve existing functionality; tests use disposable fixtures, and a shared live lab has one
operator at a time, assigned by the lead. Escalate ambiguity
before expanding scope. An implementer must not be the only verifier of its work.
