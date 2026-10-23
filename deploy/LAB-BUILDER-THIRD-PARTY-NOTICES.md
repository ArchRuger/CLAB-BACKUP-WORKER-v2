# Lab builder third-party notices

The lab builder page embeds a third-party editor as prebuilt, committed browser assets under
`clab-backup-ui/app/static/lab-builder/`. Nothing here is installed or built on a lab VM, and the
manager's Python runtime gains no dependency.

| Component | Use | Licence | Modified |
|---|---|---|---|
| `@containerlab/clab-ui` (SR Labs containerlab topology editor) | The topology editor and its editing engine | Apache-2.0 (`clab-ui.LICENSE` beside the assets) | No |
| React, React DOM, MUI, Emotion, React Flow (`@xyflow/react`), zustand, yaml, d3-force, markdown-it, highlight.js, dompurify and their dependencies | Bundled dependencies of the editor | MIT, ISC, BSD-2-Clause, BSD-3-Clause; dompurify under its Apache-2.0 option | No |
| elkjs | Automatic layout | EPL-2.0; source at <https://github.com/kieler/elkjs> | No |
| containerlab topology schema (`schemas/clab.schema.json` of the containerlab release the VM runs, vendored verbatim under `clab-backup-ui/app/static/clab-schema/<version>.json` with `LICENSE` and `SOURCES.txt`) | The YAML panel's Problems list checks a topology against it in the browser; it is read as data and never executed | BSD-3-Clause (Nokia); source at <https://github.com/srl-labs/containerlab> | No (refreshed per release with `clab-backup-ui/lab-builder/fetch-schema.mjs`, which checks the file's digest) |
| Roboto (`@fontsource/roboto`) | Editor typeface files | OFL-1.1 | No |

The complete list with every package's version and licence text is generated from the bundle itself
by `clab-backup-ui/lab-builder/build.mjs`:
`clab-backup-ui/app/static/lab-builder/THIRD-PARTY-NOTICES.txt` (served with the page and linked from
it). The exact package versions are pinned in `clab-backup-ui/lab-builder/package-lock.json`.

Two parts of the editor are left out at build time rather than changed: its code editor (Monaco)
is replaced by an empty stand-in because the YAML and JSON tabs are switched off, and no map tile
service is contacted because the Geo layout is hidden. No upstream file is edited.
