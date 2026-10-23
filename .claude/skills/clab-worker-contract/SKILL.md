---
name: clab-worker-contract
description: "The standing contract of every delegated worker in this repository: what a worker may do, what belongs to the lead, how to report. Preloaded into every project agent; load it when you act as a worker without one."
user-invocable: false
---

# Worker contract

## Every worker

- Follow `.claude/rules/fable-opus-routing.md`, the lead's assignment and the skills preloaded for your
  role. `CLAUDE.md` is in your context; its routing table names the handoff sections and guides for your
  area: read those, not the whole history.
- You are not the lead. Do not allocate release numbers, edit the shared release records
  (`docs/CHANGELOG.md`, `clab-backup-ui/VALIDATION.md`, `agent instructions.md`) or the explicit CI test
  lists, push, merge or start further orchestration. Delegate only what your own slice needs.
- Own only the assigned paths. Hand changes to the lead; commit only inside a worktree the lead gave
  you, never on the lead's branch. When your slice needs a delegate, use a named project agent, never
  the built-in general-purpose one (it carries tools the project agents are denied).
- Development operations on the assigned disposable VM are authorized when they are part of your task.
  A live lab has one operator at a time; measure memory before starting one.
- Tests and fixtures use fresh temporary data. Never point a test, a fixture or a `Store` at live data
  (`/srv/containerlab-node-manager/data`); constructing a `Store` writes state.
- Return: changed paths, findings, every check you ran with its exact command and exit status, where
  the evidence is, what you could not verify, and the next action. Never call an unrun check passed;
  never claim a VM, browser or live-device validation that did not happen.
- Do not report a model identity from your own text: the lead checks execution metadata.

## Read-only reviewers and scouts (`risk-reviewer`, `clab-ui-reviewer`, `clab-ui-scout`)

- You never edit, commit, start services or delegate. Send reproduction needs to the lead for a QA
  worker rather than touching the target.
- Return findings with file and symbol evidence (`path:line`), the checks you actually performed,
  limitations and the next action. "None found" is a valid answer for a category. End with a
  one-line verdict.
