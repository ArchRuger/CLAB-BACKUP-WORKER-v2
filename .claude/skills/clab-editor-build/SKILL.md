---
name: clab-editor-build
description: "Work on the embedded React/TypeScript topology adapter and reproduce its assets."
---

# clab-editor-build

React and TypeScript work is limited to the owned embedded editor adapter in
`clab-backup-ui/lab-builder/`, especially `src/main.tsx`. The surrounding pages
and scripts remain plain JavaScript. Read the pinned @containerlab/clab-ui version,
package-lock.json and build.mjs before changing integration behavior.

Use Node 24 or the compatible version required by the current repository. Run in
that build directory: `npm ci`, `node build.mjs`, then `node build.mjs --check`.
Commit regenerated assets and manifests together with source through the owning
Fable session. Never hand-edit app/static/lab-builder bundles or modify upstream
vendor files in place. Coordinate release cache busting with the lead.

Exercise create, reopen, edit, save, map-only mode, endpoint mapping, validation,
round trips and failure/cancel paths. Apply only client React principles from
Vercel guidance; no Next.js server components, Vercel deployment or telemetry.
The runtime lab VM does not need an npm build to serve the committed assets.
