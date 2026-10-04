---
name: clab-release
description: "Integrate and checkpoint a tested CLAB release; the lead only."
---

# clab-release

Only the lead allocates the next application release and writes the shared release
records. A worker's commits are durable checkpoints, not releases. While two VMs are
active the lead is worker A (`.claude/rules/00-clab-two-worker-routing.md`) and B's
feature commits are checkpoints.

Decide the number from the current checkout by `docs/REPOSITORY-MAINTENANCE.md`:
patch for a compatible fix, minor for a compatible feature, major for a breaking
change. One release per completed deliverable; never hardcode an old version, reuse
a released number or let two sessions allocate the same one. A breaking change needs
the owner's direction.

Use deploy/set-release.py, never hand-edit the synchronized markers, and run it only
after every local editor has stopped. Update the leading CHANGELOG, VALIDATION and
agent instructions sections with evidence actually collected, carrying each worker's
task-specific evidence into the shared record.

Gate on focused and full applicable Python unittest/Node suites, git diff --check,
verify-release.py, the link check, shell syntax, rebuilt-editor verification where
applicable, explicit CI test-list inclusion and relevant browser/live acceptance.
Separate static, unit, fixture, real engine, live NOS, VM deployment and CI evidence.
Record blocked checks explicitly; red or unrun acceptance is not a release pass.

Review merged code independently, commit only the intended paths, push the task or
integration branch and verify remote HEAD. Merge through the existing protected
workflow when authorized; do not force-push, bypass branch protection, publish images
or create remote release tags merely because the VM is disposable. Save a concise
pickup note before approaching context or usage limits. No student-guide changes.
