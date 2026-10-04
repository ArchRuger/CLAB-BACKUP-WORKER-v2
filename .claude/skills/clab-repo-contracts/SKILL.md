---
name: clab-repo-contracts
description: "Read CLAB architecture and preserve repository invariants before implementation or review."
---

# clab-repo-contracts

Read `CLAUDE.md`, `docs/REPOSITORY-MAINTENANCE.md`, the relevant portion of
`docs/ARCHITECTURE.md`, and the newest applicable handoff section. Do not load the
entire historical `agent instructions.md` into every task. Verify current HEAD,
branch, VERSION and worktree status instead of trusting historical pickup files.

Preserve existing functions and behavioral assertions. The manager is FastAPI,
plain JavaScript and an encrypted, single-process Store; React belongs only to the
embedded editor. Never introduce a second manager against the same data directory.
Tests use fresh temporary data: constructing a Store can change persisted state.

The development worker may administer the assigned disposable VM. The shipped
manager must remain non-root, without a Docker socket, with its reviewed host
gateway, trusted roots, same-origin/WS checks and secret filtering intact. Device
work stays on direct NOS SSH, not a new generic host execution helper. Do not add
PyEZ/ncclient/lxml to replace the existing Junos path. Telemetry and Grafana remain
retired; preserve required retirement migration/cleanup. Do not update the student
guide unless the user explicitly reopens that scope.

Before editing identify the exact owner of every file in the assignment. Changes
to contracts, shared release markers or live lab ownership go through the lead.
Use current vendor documentation for release-specific NOS behavior. Never equate
successful configuration generation with successful device application.
