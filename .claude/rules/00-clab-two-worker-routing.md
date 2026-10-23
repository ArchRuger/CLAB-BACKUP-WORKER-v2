# Two VMs working at once (applies only when declared)

A session is its own lead and follows `fable-opus-routing.md`. The two-VM protocol is active only on a
checkout where `.claude/worker.local.json` (ignored by Git) names the worker, `A` or `B`, with
`CLAB_WORKER_ID` in `.claude/settings.local.json`. The owner writes that file on each VM when a two-VM
campaign starts, with the coordination issue it belongs to, and removes it when the campaign ends;
without the file nothing here applies, and a stale file from an earlier campaign is removed, not obeyed.
The protocol itself, with the assignment template, is the `clab-parallel-handoff` skill: load it when
the file is present. It changes commit and release ownership only (A integrates, bumps the release,
writes the shared records and the CI lists; B checkpoints its own branches and supplies changes with
evidence), never the routing policy or the product's rules. GitHub issues, branches and pull requests
are the control plane; a task list or a cross-session message is neither an assignment, an approval
nor a lock.
