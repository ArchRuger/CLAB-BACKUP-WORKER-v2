---
paths:
  - "clab-backup-ui/lab-builder/**"
  - "clab-backup-ui/app/static/lab-builder/**"
  - "clab-backup-ui/app/static/lab-builder-page.js"
  - "clab-backup-ui/app/static/map-editor-page.js"
---

# Routing: the embedded topology editor (this rule loaded because you touched it)

The editor is `@containerlab/clab-ui`, embedded through the adapter `lab-builder/src/main.tsx` and
built ahead of time; the committed bundle under `app/static/lab-builder/` is generated.

- **Builder.** `clab-editor-specialist` only, with the `clab-editor-build` skill. The two page
  scripts around it are house-style plain JavaScript and follow `routing-manager-ui.md`.
- **Reviewer.** `clab-ui-reviewer`; `risk-reviewer` when `publish` or `revise` (the reviewed file
  actions) change.
- **Never.** Hand-edit the bundle; add a topology command or the engine's undo and redo to
  `MAP_COMMANDS`; load `operations.js` or `lab-builder-page.js` from `map-editor.html`; flush drafts
  on a timer; show as kept what is not.
- **After a change.** `npm ci`, `node build.mjs`, `node build.mjs --check` in `lab-builder/`; the
  regenerated assets and manifest go to the lead with the source; browsers receive the new bundle only
  with a new release number.
