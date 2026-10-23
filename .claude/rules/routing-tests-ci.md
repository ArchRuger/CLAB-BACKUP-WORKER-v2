---
paths:
  - "clab-backup-ui/tests/**"
  - ".github/workflows/**"
---

# Routing: tests and CI (this rule loaded because you touched a test or the workflow)

- **CI runs an explicit list, not discovery.** A new Python test file is appended with its own `-p`
  line and a new browser test file to the one `node --test` line of
  `.github/workflows/release-check.yml`; only the lead edits that file. The first group runs with the
  system `python3` before the virtual environment exists, so a test there stays stdlib-only.
- **Builder.** `clab-test-engineer` for tests of a named behaviour; `clab-ui-qa` for browser and
  fixture coverage; the implementer of a slice writes its own first failing test.
- **Rules that bite.** A pinned label is rewritten, never deleted; never weaken an assertion to get
  green; tests import `app` from `clab-backup-ui/` with `.venv/bin` on `PATH`; browser tests
  `vm.runInContext` a production script with a fake `$`, `esc` and `state`; a `Store` is built on a
  temporary directory only.
- **Evidence.** Report the exact command and exit status; a run you did not do is not a pass.
