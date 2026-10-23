---
paths:
  - "clab-backup-ui/VERSION"
  - "docs/CHANGELOG.md"
  - "clab-backup-ui/VALIDATION.md"
  - "agent instructions.md"
---

# Routing: release markers and the history files (this rule loaded because you touched one)

- **The lead only.** A worker proposes release notes and evidence in its hand-back; it never edits
  these files or allocates a number. Skill: `clab-release`.
- **The number moves with the tool.** `python3 deploy/set-release.py X.Y.Z` is the only way; then the
  three sections (`## Changes in X.Y.Z`, `# … — X.Y.Z` in VALIDATION and in the handoff file) are
  written by hand and `python3 deploy/verify-release.py` must pass. Patch for a compatible fix, minor
  for a feature, major for a breaking change.
- **What VALIDATION may say.** Only what was run, by kind: static, unit, fixture and browser, real
  engine, live NOS, VM, CI. A build, deployment, device test or push that did not happen is not
  claimed. The handoff section is short: what the next agent must preserve, with links.
- **Living guides** name no release of their own; history phrases (`since 1.31.0`) are allowed
  anywhere. `docs/REPOSITORY-MAINTENANCE.md` has the rules and `python3
  docs/maintenance-audit/tools/check_links.py` the link check.
