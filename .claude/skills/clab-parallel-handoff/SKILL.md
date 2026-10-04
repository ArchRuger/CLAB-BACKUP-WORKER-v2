---
name: clab-parallel-handoff
description: "Coordinate two VM-local Fable sessions using exact file ownership and GitHub handoffs."
---

# clab-parallel-handoff

Applies only while the owner has declared two VMs active
(`.claude/rules/00-clab-two-worker-routing.md`). A single session is its own lead and
needs none of this; inside one VM the lead hands a worker its files or a worktree.

Worker A owns cross-VM integration, release numbers and the shared coordination
issue. Worker B takes tasks explicitly assigned there. Each VM has a separate clone,
branch, manager state directory, Docker daemon/labs and local session history.
A matching Claude task-list ID is not a distributed lock or message transport.

A task assignment contains ID, owner A/B, base SHA, branch, exact writable files,
read-only dependencies, API contract, acceptance checks, live lab identity and
handoff requirements. A is the single writer of the assignment table. B must not
self-assign overlapping files. Renames/deletions include both paths in the claim.
If a dependency is not ready, work on another disjoint assigned task or report the
blocker; do not invent a second conflicting contract.

Each local Fable may stage exact owned files, commit and push its own task branch.
Subagents return patches/evidence to that Fable. Do not switch branches while local
editors are active. Separate worktrees must be created from the assignment's explicit
base SHA; never assume a default worktree contains the parent's in-progress changes.

Before handing off record HEAD, base, files, tests, evidence, runtime routing,
uncommitted work, known gaps and next step. Push checkpoints before long operations,
verify remote SHA and never force-push or silently discard another worker's work.
No shared filesystem, Redis service or always-running agent framework is required.
