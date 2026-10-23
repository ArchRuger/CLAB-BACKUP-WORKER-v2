---
paths:
  - "clab-backup-ui/app/static/*.js"
  - "clab-backup-ui/app/static/*.html"
  - "clab-backup-ui/app/static/*.css"
  - "clab-backup-ui/tests/*.js"
---

# Routing: the manager UI (this rule loaded because you touched a page script, page or test)

The binding contract is `docs/redesign/DESIGN-SPEC-ADDENDUM.md`; the architecture is `CLAUDE.md`
"Frontend: three different things" and the invariants under "Saving and loading" and "Maps and the
editor".

- **Builder.** `clab-ui-builder` for a slice the lead specified; `clab-fable-designer` for the design
  and wording; `clab-fable-specialist` where state across files is hard. Skill: `clab-manager-ui`.
- **Reviewer.** `clab-ui-reviewer` (read-only) on the finished slice and its evidence; `clab-ui-qa`
  runs the fixture pass per viewport (`/clab-slice-verify` with `ui: true`).
- **Rules that bite.** A top-level name declared in two scripts breaks the page
  (`test_page_load_ui.js`); "no reference in this file" never proves a function unused; `esc()` on
  every interpolation; no inline styles on `/`; browser globals stay in `shell.js`; a new script
  carries `?v=<release>` in every page that loads it and the release owner moves the number; the
  state deciders (`saveChipState`, `loadState`, `saveProblem`) live in `status.js` only.
- **Tests.** `node --test tests/*.js` and `node --check` on the changed script; a new test file is
  appended to the `node --test` line of `.github/workflows/release-check.yml` by the lead. Copy
  `test_operations_ui.js`, `test_readiness_ui.js` or `test_shell_ui.js` as the harness.
