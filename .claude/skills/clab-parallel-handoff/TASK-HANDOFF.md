# Task assignment and handoff template

Copy into the coordination issue (two VMs) or the delegation prompt (one VM). Every line is filled or
struck through; nothing is implied.

## Assignment

- Task ID:
- User-requested outcome:
- Owner: A or B (two VMs) / agent name (one VM)
- Base commit:
- Task branch or worktree:
- Exact writable paths:
- Read-only dependencies:
- API or schema contract between slices:
- Assigned VM / lab (one operator per live lab):
- Required invariants (CLAUDE.md sections, path-scoped rules that apply):
- Acceptance checks (commands, expected results):
- Requested model / effort / rationale:

## Completion or pickup

- Head commit and remote verification (`git rev-parse HEAD`, `git ls-remote`):
- Changed paths:
- Actual model / effort observed in execution metadata (`/tasks`; for a workflow the per-agent transcript `agent-<id>.jsonl`):
- Checks actually run (command, exit status, evidence path):
- Validation level (static / unit / fixture / engine / live NOS / VM / CI), each named separately:
- Findings and unresolved blockers:
- Uncommitted work:
- Next action:
- CI-list additions and release notes proposed for the lead:
