---
paths:
  - "clab-backup-ui/app/restore*.py"
  - "clab-backup-ui/app/design_apply.py"
  - "clab-backup-ui/app/design_provision.py"
  - "clab-backup-ui/app/design_ownership.py"
  - "clab-backup-ui/app/design_eos.py"
  - "clab-backup-ui/app/design_iosxr.py"
  - "clab-backup-ui/app/design_junos.py"
  - "clab-backup-ui/app/node_services.py"
  - "clab-backup-ui/app/node_readiness.py"
  - "clab-backup-ui/app/runner.py"
  - "clab-backup-ui/app/telemetry_retirement.py"
---

# Routing: device transactions (this rule loaded because you touched one)

This code talks to network operating systems. The invariants are in `CLAUDE.md` "Devices"; the live
facts and the support matrix are in `docs/multi-platform-restore/README.md` and
`docs/netlab-integration/PROVISIONING.md`.

- **Builder.** `clab-network-specialist` (Opus) for anything that arms, confirms or reads back a
  transaction; the lead or `clab-fable-specialist` for the surrounding service code.
- **Reviewer.** `risk-reviewer` on the diff; `clab-network-specialist` reviews what it did not write.
  Both need the `clab-network-transactions` skill, which they preload.
- **Never.** A paste or merge sold as a restore; a faked timed recovery; confirming a pending change
  that is not the manager's own; an outcome reported `rolled_back` without a read-back; a new kind
  declared supported without live proof; PyEZ, ncclient or lxml for Junos.
- **Evidence.** Unit tests (`test_restore*.py`, `test_design_*.py`, `test_node_readiness.py`,
  `test_runner_resilience.py`) are not live evidence; say which kind you have. A live pass is run or
  assigned by the lead, one operator per lab, images from `docs/git-redesign/LIVE-ENV.md`.
