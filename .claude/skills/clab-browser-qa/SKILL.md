---
name: clab-browser-qa
description: "Run reproducible student workflow and failure-path browser validation on CLAB."
---

# clab-browser-qa

Start from the repository's existing fixture_manager.py and Playwright tools under
`docs/redesign/tools/`, `docs/ui-review-001/tools/` and the relevant feature folder.
Create a unique scratch FIXTURE_DATA per run, do not use live manager data, and
restart the fixture after backend changes. Record browser version, viewport,
application commit and exact route/steps. Prefer existing Python Playwright tooling.

Test workflows, not just button presence: launch/import, inventory, design, generate,
review/apply, backup/download, Git save, restore, restart one node, terminals, map
editing and capture as relevant. Include cancellation, errors, long-running status,
refresh/reconnect and keyboard-only use. Capture console and failed requests as
well as screenshots; scrub secrets before saving evidence.

Because the application polls and uses WebSockets, wait for explicit UI conditions
and locator assertions, not a blanket network-idle condition or arbitrary sleeps.
Only mock at a named boundary; label fixture evidence as fixture evidence. Browser
success does not establish live NOS configuration or rollback correctness.

File a reproducible finding with severity, expected/actual, owned paths, regression
test and evidence. Re-run the original failing path after the fix and adjacent
flows before calling it fixed. Automation failures are not product failures until
reproduced and diagnosed.
