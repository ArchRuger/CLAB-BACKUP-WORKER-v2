# up-public-api-license (condensed reader result recovered from the workflow journal)

Full report: /tmp/claude-1000/-home-clabllm-projects-clab-manager/2b0e597f-39bf-4403-8d37-3e4a96f0a0a9/scratchpad/reports/up-public-api-license.md

Roots: UI = <scratchpad>/containerlab-app/packages/clab-ui (commit be0ec24); TARBALL = <scratchpad>/work/npm-pack/package (npm 0.3.2); MGR = /home/clabllm/projects/clab-manager.

## 0. The clone is not the published package
- Clone manifest is 0.4.0 (UI/package.json:3). npm has only 0.3.2, published 2026-09-17, dist-tag latest.
- HEAD-only features: `App` props `slots`, `viewerOptions` and `lifecycleActionsAvailable` (UI/src/AppContent.tsx:301-317), `./explorer/filter`, and the `<clab-topology>` component. TARBALL/dist/App.d.ts has only `initialData`, `runtime`, `chrome`.
- `@containerlab/clab-viewer` (MIT, dependency-free) is documented as public, but `npm view` returns E404.

## 1. Public surface
- Three upstream lists disagree on the supported entry points:
  - INTEGRATORS.md:33-45 lists `.`, /host, /session, /theme, /explorer, /inspect, /welcome, /node-impairments, /wireshark-vnc, /styles/global.css.
  - README.md:15-27 and the export map (package.json:28-105) add /image-manager(/catalog), /viewer, /viewer/static/*, /monaco/{core,editor-worker,json-worker,yaml-worker}, /monaco-assets.json, /yaml.
  - docs/03-clab-ui.md:23 calls the export map the supported boundary.
- Topology editor: `App` only, as one monolith (src/index.ts:3). No canvas, palette or node-editor component is exported. `useTopoViewerStore` and `subscribeToWebviewMessages` are also exported.
- YAML editor: no public component. `MonacoCodeEditor` is internal and lazy-loaded (PaletteSection.tsx:173). Public pieces are /yaml pure helpers (yaml/index.ts:146-1016), /monaco/core, three one-line worker entries, and monaco-assets.json.
- /host:
  - Factories `createWindowClabUiHost` (:319), `createApiClabUiHost` (:617), `createClabUiRuntime` (:716).
  - Contracts in contracts.ts.
  - `ClabUiExtensions` (runtimeContext.tsx:14-29): nodeEditorTabs, customPaletteTabs, yamlSchema, renderDeployMenuItems, renderAboutModal, disabledTabIds, paletteTabLabels.
  - `ClabUiRuntimeProvider` and hooks; three controller factories.
- /session: `TopologySessionCore` (session/index.ts:10), `FileSystemAdapter`, `createTopologySessionClient`, `parseSchemaData`, message and snapshot types, `TOPOLOGY_HOST_PROTOCOL_VERSION=1`.
- /theme: `MuiThemeProvider`, `vscodeTheme`, `applyThemeVars(mode)`, DARK/LIGHT_VARS.
- /explorer: `ContainerlabExplorerView` (no props), `buildExplorerSnapshot`, message types.
- /welcome: `WelcomePageApp`, `bootstrapWelcomePage`.
- /image-manager: `ContainerlabImageManager(Dialog)`, `ImageManagerApp`, and catalog functions. It needs the optional `host.images`.
- /viewer: `createViewerHost`, `mountViewer`. `dist-viewer/` is a prebuilt read-only iframe page driven by postMessage.

## 2. What the embedder provides
- The embedder owns auth, files, session create/dispose, lifecycle, SSH/capture, custom nodes, icons and SVG export (INTEGRATORS.md:23-29, 586-596).
- `ClabUiHost` (contracts.ts:186-207):
  - Required: postMessage, subscribe, explorer (5 methods), topoViewer (17 methods), topology (`requestSnapshot`, `dispatchCommand`).
  - Optional: meta, images.
- Through `createWindowClabUiHost(options)` every surface is optional. Defaults forward each call to one `postMessage({command,…})` (host/index.ts:54-63, 326-421).
- The topology surface is non-negotiable: the host must support all 20 command verbs (INTEGRATORS.md:557-584, verified against messages.ts).
- Key shortcut: `TopologySessionCore` runs in the browser. There are no Node built-ins in dist, and the build is platform-neutral.
  - It needs only an 8-method `FileSystemAdapter` (core/io/types.ts:42-88).
  - Upstream does this read-only (viewer/createViewerHost.ts:26-98) and editable (test/ui-harness/fakeHost.ts:128, 313-318).
  - A Python backend then only reads and writes `<lab>.clab.yml` and its `.annotations.json`.
  - Upstream caveat: no distributed lock, and saves are not crash-atomic (INTEGRATORS.md:169-175).
- Minimal example: INTEGRATORS.md:71-149. It disagrees with the code in three places:
  - It calls `applyThemeVars(document.documentElement,"dark")`; the real signature is `(mode)` (devTheme.ts:200).
  - `baseUrl:"/api"` plus the hard-coded `/api/topology/*` paths gives `/api/api/…` (host/index.ts:619-622, 661, 687).
  - The snapshot response must be `{snapshot}` (:660, 674), not a bare snapshot.
- Stability: the promise covers the package name, the public subpaths, dist/, and the /host and /session contracts (INTEGRATORS.md:669-683). There is no semver statement and no changelog.
- Maturity:
  - One npm version, 3 days old, 0.x.
  - HEAD already jumps MUI 7→9, maplibre 5→6, zustand 4→5, and elkjs 0.11→0.12.
  - Dependencies are pinned exactly (pnpm-workspace.yaml:83-84).
  - No first-party app consumes the npm artefact (CONTRIBUTING.md:30).
  - Positive: a packed-tarball consumer test, and OIDC provenance on publish.

## 3. Licence
- Licence files:
  - Root LICENSE is MIT, "Copyright (c) 2026 SRL Labs".
  - packages/clab-viewer/LICENSE is byte-identical to the root file.
  - packages/clab-ui/LICENSE is Apache-2.0 (200 lines, appendix unfilled at :189).
  - apps/vscode-containerlab/LICENSE is identical to the clab-ui file.
  - There is no NOTICE file anywhere, and no SPDX or copyright headers in the source.
- Manifests: every one says Apache-2.0 except clab-viewer, which says MIT.
- Tarball: LICENSE is Apache-2.0 (same sha256 as the clab-ui file). It is the only licence file. `license: Apache-2.0` in the manifest.
- Resolution:
  - clab-ui is Apache-2.0 on all three axes.
  - The real upstream inconsistency is the MIT root file against the Apache manifests of the root and the private packages (app-server, standalone-runtime, app-contract, web, desktop). These have no LICENSE file of their own, so their licence is ambiguous if we copy from them.
- Dependency licences (`npm view`):
  - MIT: MUI, Emotion, Monaco, monaco-yaml, @xyflow/react, ajv, zustand, markdown-it, React.
  - ISC: yaml, d3-force.
  - BSD-3-Clause: maplibre-gl, highlight.js.
  - dompurify is (MPL-2.0 OR Apache-2.0).
  - @fontsource/roboto is OFL-1.1.
  - elkjs is EPL-2.0 (licence files read).
- Apache-2.0 §4 (LICENSE:89-128):
  - 4(a): ship the licence text. This applies to source and object form alike.
  - 4(b): mark modified files. It applies only if we patch upstream files.
  - 4(c): retain notices in source form. Upstream has none to retain.
  - 4(d): NOTICE. Not triggered, because there is no NOTICE file.
  - A bundle built from dist is object form.
  - The tarball ships no third-party notices. In dist-viewer, licence banners survive only in ts.worker. We must generate the notices ourselves, as we already do for xterm (MGR/clab-backup-ui/app/static/vendor/README.md).
- Apache-2.0 code may ship inside an MIT project. It stays Apache-2.0 with its own licence file; §4's last paragraph allows different terms for the work as a whole. This is a reading of the text, not legal advice.
- EPL-2.0 (elkjs, a single import at autoLayout.ts:16):
  - §3.1(a) requires a statement that the source is available and where to get it.
  - §3.3 requires keeping notices.
  - Copyleft is limited to modifications of elk itself. Link, bind-by-name and subclass are excluded (LICENSE.md:41-48), so our code is not affected.
  - Keep elkjs as a separate chunk, leave it unmodified, and ship the EPL text.

## 4. Runtime
- Tarball: 6.7 MB packed, 23.5 MB unpacked, 642 files.
  - dist only: no sources and no sourcemaps.
  - ESM only: `type: module`, with only `import` conditions.
  - dist/ is 4.2 MB (2.16 MB of JS, 434 KB gzipped, excluding dependencies). dist-viewer/ is 21 MB.
  - Largest files: ts.worker 6.8 MB, MonacoCodeEditor 3.8 MB, viewer 2.9 MB.
  - CSS in dist: global.css (1.4 KB) and FreeTextNode.css. No fonts or Monaco assets in dist.
- React: `react` and `react-dom` peers at ^19.2.5. MUI, Emotion, xyflow and zustand are externalised dependencies, and there must be a single instance of each.
- DOM is required for the UI entry points. /session, /yaml and /image-manager/catalog also run under Node.
- engines is node>=24. This VM has Node 18.19.1.
- A bundler is required:
  - Every dependency is a bare import (355 @mui/material/* and 191 @mui/icons-material/* statements).
  - JS files contain side-effect CSS imports (chunk-C22TQ353.js:4-7, MonacoCodeEditor chunk :25, chunk-WM5ZW3ZW.js:11076).
  - global.css has bare `@import`s (:7-9).
  - elkjs ships UMD only.
  - Three Monaco workers must be built, with URLs supplied through `window.monaco*WorkerUrl` or `MonacoEnvironment` (MonacoCodeEditor.tsx:185-215).
  - Upstream's own consumer test is an esbuild bundle (scripts/check-packed-clab-ui.mjs:88-93).
- Without CDNs, the only route is an offline bundle committed under static/vendor.
  - I estimate 8-10 MB, from the size of dist-viewer. The manager's whole static/ directory is 808 KB.
  - The release process would need a package.json and lockfile.
- Manager CSP (MGR/clab-backup-ui/app/main.py:116-123):
  - `style-src 'self'` blocks clab-ui's Monaco `<style>` text (chunk :100-111). A per-page 'unsafe-inline' exception would be needed, which is a main.py change.
  - `frame-ancestors 'none'` plus `X-Frame-Options: DENY` blocks the iframe viewer, even same-origin.
  - Geo layout fetches tiles from tile.openstreetmap.org (useGeoMapLayout.ts:51).
- global.css sets `html,body,#root{overflow:hidden}`, so the editor needs its own page.

## Load-bearing claims

- **[verified-in-code]** @containerlab/clab-ui is Apache-2.0 by its own LICENSE file, its manifest and the published tarball. The MIT root LICENSE does not govern it. The unresolved upstream inconsistency is the MIT root file against the Apache-2.0 manifests of the root and the private packages, which have no LICENSE file of their own.
  - Evidence: sha256sum: packages/clab-ui/LICENSE = 43070e2d… (Apache-2.0, 200 lines) = TARBALL/LICENSE = apps/vscode-containerlab/LICENSE. Root LICENSE = d233684d… (MIT, 'Copyright (c) 2026 SRL Labs') = packages/clab-viewer/LICENSE. UI/package.json:6 and TARBALL/package.json:6 say "license": "Apache-2.0"; `npm view` reports license Apache-2.0. A Python loop over every package.json shows Apache-2.0 everywhere except clab-viewer (MIT). `find -iname 'NOTICE*'` finds nothing. CLONE/docs/SOURCES.md:9 calls the root LICENSE Apache-2.0 although it is MIT.
- **[verified-in-code]** Only version 0.3.2 exists on npm, published 2026-09-17. The clone is unpublished 0.4.0. 0.3.2 lacks the App slots, viewerOptions and lifecycleActionsAvailable props, the AppLayoutOptions type, ./explorer/filter and the <clab-topology> component. @containerlab/clab-viewer is not on npm.
  - Evidence: `npm view @containerlab/clab-ui versions time dist-tags` returns versions "0.3.2", created 2026-09-17T08:46Z, latest 0.3.2. `npm view @containerlab/clab-viewer` returns E404. UI/package.json:3 is 0.4.0. TARBALL/dist/App.d.ts declares only initialData, runtime and chrome. `grep -rl lifecycleActionsAvailable TARBALL/dist` finds nothing. The exports diff shows './explorer/filter' only in the clone. `find TARBALL -name 'component*'` finds only the dist/components directory. Diffing INTEGRATORS.md shows the HEAD-only paragraphs.
- **[verified-in-code]** The editor cannot be loaded in a browser without a bundler. dist is ESM with all dependencies as bare specifiers, JS files carry side-effect CSS imports, global.css has bare @imports, elkjs ships UMD only, and three Monaco workers must be built by the host.
  - Evidence: UI/build.mjs:59-82 marks .css and every dependency and peer as external; :92-104 sets format esm, platform neutral and splitting. A grep over TARBALL/dist counts 355 @mui/material, 232 react and 191 @mui/icons-material import statements. CSS imports: dist/chunks/chunk-C22TQ353.js:4-7 (@fontsource/roboto/*.css), MonacoCodeEditor-7TVK3SAJ.js:25, chunk-WM5ZW3ZW.js:11076, dist/viewer/index.js:163. dist/styles/global.css:7-9 has bare @imports. The elkjs lib/elk.bundled.js header is UMD. Workers: MonacoCodeEditor-7TVK3SAJ.js:143-160 and UI/src/monaco/*-worker.ts:1. Upstream's consumer test is an esbuild bundle (CLONE/scripts/check-packed-clab-ui.mjs:88-93).
- **[verified-in-code]** TopologySessionCore, the authoritative YAML and annotations model with revisioning and undo/redo, is publicly exported and runs in the browser behind an 8-method FileSystemAdapter. A non-Node backend therefore only needs file read/write endpoints, not the 20-verb command protocol.
  - Evidence: UI/src/session/index.ts:10 and :37 (exports). UI/src/core/io/types.ts:42-88 (readFile, writeFile, unlink, rename, exists, dirname, basename, join, optional invalidateCache). UI/src/core/host/TopologyHostCore.ts:36-53 and 145-349 (options; getSnapshot, applyCommand, onExternalChange, dispose). Browser use: UI/src/viewer/createViewerHost.ts:26-98 (in-memory filesystem, read-only) and UI/test/ui-harness/fakeHost.ts:128-129 and 313-318 (editable: dispatchCommand calls core.applyCommand). A grep for node:, fs or path imports in TARBALL/dist finds nothing. Caveats are in INTEGRATORS.md:169-175 (single-process serialisation, no atomic conditional write).
- **[verified-in-code]** The host adapter's TypeScript type requires postMessage, subscribe, explorer (5 methods), topoViewer (17 methods) and topology (2 methods). meta and images are optional. createWindowClabUiHost makes every surface optional by defaulting each call to a single postMessage funnel, so the smallest custom adapter is a postMessage router plus a topology implementation. All 20 topology command verbs must be supported.
  - Evidence: UI/src/host/contracts.ts:151-207. UI/src/host/index.ts:54-63 (WindowHostOptions, all optional), :326-421 (defaults that post {command,…}), :423-599 (requestId correlation with a 30 s timeout). INTEGRATORS.md:557-584 lists 20 verbs and says an unsupported command 'is an integration gap'; the list matches a grep of UI/src/core/types/messages.ts. The read-only no-op host is at createViewerHost.ts:100-134.
- **[verified-in-code]** Upstream gives no semver or compatibility commitment. The stated promise covers only the package name, public subpaths, dist/ and the /host and /session contracts. The documented quickstart contradicts the code in three places, and exact-pinned dependencies already jump major versions between 0.3.2 and HEAD.
  - Evidence: INTEGRATORS.md:669-683. A grep for semver, breaking, deprecat and experimental across the docs, README, RELEASING and CONTRIBUTING finds nothing. Quickstart errors: INTEGRATORS.md:81 against UI/src/theme/devTheme.ts:200; :113 against UI/src/host/index.ts:619-622, 661 and 687; :467-469 against :660 and 674-678. Dependency drift: TARBALL/package.json:105-128 (MUI 7.3.11, maplibre 5.24.0, zustand 4.5.7, elkjs 0.11.1) against CLONE/pnpm-workspace.yaml:12-76 (9.4.0, 6.10.0, 5.0.15, 0.12.0), with saveExact and catalogMode strict at :83-84. CONTRIBUTING.md:30 says the apps never consume the npm package.
- **[inferred]** Redistributing a compiled clab-ui bundle inside the MIT-licensed manager is permitted. The obligations are to ship the Apache-2.0 text, mark any upstream files we modify, and ship third-party licences. No NOTICE obligation exists today. The bundled code remains Apache-2.0.
  - Evidence: UI/LICENSE:26-33 (Source and Object definitions), :89-128 (§4(a)-(d) and the final paragraph allowing different terms for the Derivative Work as a whole). No NOTICE file in the clone or the tarball. MGR/LICENSE is MIT (Patrick Ruger). Vendoring precedent: MGR/clab-backup-ui/app/static/vendor/README.md with xterm.LICENSE. The tarball carries no third-party notices: a grep of dist-viewer/assets finds licence banners only in ts.worker-*.js. That Apache-2.0 code may sit inside an MIT project is my reading of the licence text, not legal advice.
- **[documented-only]** elkjs is EPL-2.0, a weak file-level copyleft. Bundling or linking it does not put our code under the EPL. Shipping it requires a source-availability statement, the licence text and keeping its notices. Modifications to elk itself would have to be released under EPL-2.0. Keeping it as a separate, unmodified chunk is the clean form.
  - Evidence: `npm view elkjs@0.11.1 license` returns EPL-2.0. DEPS/elkjs-0.11.1/package/LICENSE.md §3.1(a)-(b), §3.2 and §3.3 were read. The 'Modified Works' definition at lines 41-48 excludes works that 'link to, bind by name, or subclass the Program'. There is a single usage at UI/src/components/canvas/layout/autoLayout.ts:16. The separate-chunk recommendation is my inference.
- **[inferred]** The manager's current security headers conflict with clab-ui. style-src 'self' blocks runtime <style> injection, frame-ancestors 'none' plus X-Frame-Options DENY blocks the iframe viewer even same-origin, and connect-src and img-src block the OpenStreetMap tiles used by geo layout. A per-page exception mechanism exists, but using it is a backend change.
  - Evidence: MGR/clab-backup-ui/app/main.py:116-123 (the CSP string, with the 'unsafe-inline' style exception only for /static/terminal.html and /static/capture-session.html). clab-ui sets style.textContent on a created <style> element: TARBALL/dist/chunks/MonacoCodeEditor-7TVK3SAJ.js:100-111 (source MonacoCodeEditor.tsx:139). TARBALL/dist-viewer/viewer.html has an inline <style>. UI/src/hooks/canvas/useGeoMapLayout.ts:51 uses tile.openstreetmap.org. Style injection by MUI/Emotion and by Monaco's theme service was not browser-tested.
- **[verified-in-code]** Size and toolchain. The published tarball is 6.7 MB packed and 23.5 MB unpacked, dist only, with no sources or sourcemaps. Its own JS is 2.16 MB before any dependency. A full editor bundle would be roughly ten times the manager's entire static directory (808 KB). The package declares node>=24 and this VM has Node 18.19.1.
  - Evidence: npm pack output (package size 6.7 MB, unpacked 23.5 MB, 642 files). `find -name '*.map'` returns 0 and there is no src/. Concatenating dist/*.js gives 2,161,634 bytes, 433,751 gzipped. dist-viewer is 20.9 MB with ts.worker at 6.85 MB and MonacoCodeEditor at 3.81 MB. `du -sb MGR/clab-backup-ui/app/static` gives 807,643. TARBALL/package.json:25-27 sets engines; `node --version` gives v18.19.1. The 8-10 MB bundle estimate is inferred from dist-viewer and was not built.

## Open questions

- Who holds the copyright for clab-ui, and is a NOTICE file planned? The Apache appendix is unfilled (UI/LICENSE:189), there are no source headers, and only the root MIT file names 'SRL Labs'. If a NOTICE appears later, §4(d) starts to apply.
- What licence governs the private packages (app-server, standalone-runtime, app-contract, apps/web, apps/desktop)? Their manifests say Apache-2.0 but the only LICENSE file above them is MIT. This must be clarified with upstream before copying any code from them, for example the Fastify session routes or the file editor.
- When will 0.4.0 be published, and will @containerlab/clab-viewer be published at all? The features most useful to the manager (lifecycleActionsAvailable to hide Deploy, slots, the light viewer and the <clab-topology> web component) exist only at HEAD.
- Does an esbuild or Vite bundle of the 0.3.2 dist actually build on this VM? Node here is 18.19.1 and the package declares >=24. What is the real minified and gzipped size once Monaco's unused workers are dropped? Nothing was built in this phase, which was read-only.
- Can maplibre-gl (geo layout, external OSM tiles, probably a blob: worker) and elkjs (EPL) be stubbed out at bundle time without breaking App? No upstream switch to disable the geo layout option was found. Whether maplibre needs `worker-src blob:` was not verified.
- Exactly which style-src relaxations does the editor need in a real browser under the manager's CSP? Emotion in production mostly uses CSSOM insertRule, which CSP does not block. Monaco's theme service and clab-ui's own <style> textContent need 'unsafe-inline'. A browser test is needed to confirm.
- How does App 0.3.2 behave in edit mode when host.topoViewer and host.explorer are no-ops? 0.3.2 has no prop to hide Deploy and Destroy in the navbar. Whether the ClabUiExtensions (disabledTabIds, renderDeployMenuItems) are enough to neutralise them was not tested.
- Is the React Flow (@xyflow/react) attribution badge shown by clab-ui? MIT does not require it, but this was not checked in the source.
- What are upstream's versioning intentions for the /host and /session contracts? No semver statement or changelog exists. TOPOLOGY_HOST_PROTOCOL_VERSION is 1, with no documented bump policy.
- Does elkjs carry an Exhibit A 'Secondary License' notice? This was not checked. It matters only if GPL code is ever combined.
