# Two VMs working at once (applies only when declared)

A session is its own lead and follows `fable-opus-routing.md`. This file adds the coordination
protocol for the case where the owner runs two VM-local Fable sessions on this repository at the same
time. It is inactive until the owner declares the second VM active. It changes commit and release
ownership only, never the routing policy or the product's rules.

- **Worker A is the integration and release lead.** A alone writes the assignment table in the
  coordination GitHub issue, integrates tested slices one at a time, runs `deploy/set-release.py`,
  writes the shared release histories and edits the explicit CI test lists. **Worker B is a parallel
  implementation lead**: it takes the tasks assigned there, checkpoints its own branch, and supplies
  proposed changes and evidence instead of a competing release bump.
- A task has an ID, owner, base SHA, branch, exact writable paths, acceptance checks, API contract and
  live lab target. No two active tasks write the same file. The starting lanes (A: backend, host and
  NOS; B: vanilla UI, editor and browser QA) are not silos: A may move one once the new ownership is
  acknowledged before editing.
- Each VM has its own clone, scratch test data, manager state, Docker daemon and labs. Never share the
  encrypted Store, `.claude` session directories or task-list files. GitHub issues, branches and pull
  requests are the control plane; a local task list is neither communication nor mutual exclusion.
- `set-release.py` touches many files: A runs it only after local editors have stopped and B's
  incoming changes are coordinated. Each lead verifies the remote commit after pushing a checkpoint.
