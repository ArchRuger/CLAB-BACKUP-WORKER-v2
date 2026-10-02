# up-apps-build-theme (condensed reader result recovered from the workflow journal)

Full report with citations: /tmp/claude-1000/-home-clabllm-projects-clab-manager/2b0e597f-39bf-4403-8d37-3e4a96f0a0a9/scratchpad/reports/up-apps-build-theme.md. Nothing was built or run, and both repositories are unmodified. UP = the upstream clone, PUB = the published npm tarball unpacked in scratch work/pack/package, MGR = the manager repo.

CAVEAT FIRST. The upstream repository's latest code (HEAD, clab-ui 0.4.0) differs from what npm delivers. Exactly one version is published: 0.3.2, dated 2026-09-17.

1. COMPOSITION.
- apps/web is only a shell. It has three one-line entries (UP/apps/web/src/main.tsx:1) and a 64-line server.
- The real glue is in two private, unpublished packages, both hard-wired to clab-api-server:
  - standalone-runtime: 24,361 LOC, the browser app.
  - app-server: 8,925 LOC, a Fastify BFF.
- The composition root is standalone-runtime/src/standaloneApp.tsx:
  - createApiClabUiHost (:1274);
  - createClabUiRuntime (:1335);
  - <App initialData runtime slots lifecycleActionsAvailable> (:1668).
- The only provider is MuiThemeProvider. There is no router: navigation is a zustand tab store plus three HTML documents.
- clab-ui entry points used: /session (18 import sites), /host, the root, /monaco/core, /theme, /image-manager, /explorer.
- PUBLISHED 0.3.2: App accepts only initialData, runtime and chrome (PUB/dist/App.d.ts). `slots` and `lifecycleActionsAvailable` appear nowhere in the published dist. So Deploy and Destroy cannot be hidden through a prop today.
- HEAD has no per-feature flags either.
- TopologySessionCore and FileSystemAdapter are public /session exports, and they are present in 0.3.2. "Pages" mode runs the whole topology session in the browser over localStorage (pagesSandboxRuntime.ts:891-903).
- Estimate for our own builder-only island [inferred]: 0.6-1.2k LOC of TypeScript, with no session logic in Python.

2. BUILD.
- Monaco workers load by URL, not as blobs. They come from Vite `?worker` imports (standaloneApp.tsx:13-15), or from window.monaco*WorkerUrl.
- monaco-editor is aliased to the trimmed monaco/core (vite.config.ts:49-53).
- The base path is configurable in three ways:
  - the build default is "./";
  - VITE_PUBLIC_BASE_PATH overrides it at build time (vite.config.ts:21-24);
  - WEB_BASE_PATH sets it at run time by injecting a <base> tag (app-server/src/app.ts:417-426). This variable is not in the documented list.
- The client also works with no <base> tag (standaloneServerOrigin.ts:44-52).
- A bundler is mandatory. clab-ui's dist leaves every dependency and every .css import external (build.mjs:59-82,105).
- Size:
  - The published dist is 2.16 MB of JS before dependencies.
  - The Vite-bundled viewer inside the tarball is 19.2 MB of JS in 113 files. Of that, 8.7 MB is Monaco's TS, CSS and HTML workers, which the alias avoids.
  - A trimmed editor build would be roughly 10-15 MB of lazily loaded JS [inferred].
- Upstream requires exactly Node 24.21.0 and pnpm 12.4.2, enforced by a preinstall hook (UP/package.json:9,39,56). It also uses Vite 8, which needs Node 20.19 or later.
- This VM has Node 18.19.1 and neither pnpm nor corepack. Upstream therefore cannot be built here.
- Bundling the npm package with Vite 5 or 6, or with esbuild, is plausible on Node 18 but untested. Upstream itself bundles clab-ui with plain esbuild for VS Code.

3. CSP.
- Manager policy (MGR app/main.py:123): default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'.
- The manager allows inline styles only on the terminal and capture pages (:122).
- Upstream's own strictest host needs style-src 'unsafe-inline', script-src 'unsafe-eval' and worker-src blob:. It also connects to OpenStreetMap (PanelManager.ts:119).
- Upstream's web server sets no CSP at all.
- Conflicts:
  - (a) Runtime styles. No emotion cache or nonce is configured anywhere upstream. emotion would honour a nonce, but Monaco and clab-ui inject style elements that carry none (MonacoCodeEditor.tsx:139-148). The page therefore needs a per-path 'unsafe-inline' style exception. The manager already has that precedent.
  - (b) Eval. ajv's `new Function` runs at MonacoCodeEditor.tsx:299-304,408. It is outside the try/catch, and ajv is the default validator. Without 'unsafe-eval', YAML validation throws uncaught errors, which would fail the manager's browser gate (verify_after.py:32-33). Configuration cannot fix this.
  - (c) Map. The maplibre worker always uses blob: (useGeoMapLayout.ts:177,214). The Geo menu item is unconditional (Navbar.tsx:673). OpenStreetMap tiles can be replaced through window.maplibreStyle (:67).
  - (d) Fonts. Vite inlined 10 data:font URIs in the real output. The manager's font-src fallback blocks them. Setting assetsInlineLimit: 0 avoids this [inferred].
  - (e) The <base> tag, the inline <style> in the HTML shells, and iframes are all avoidable.
- Not conflicts: Monaco workers, and the bundled @fontsource fonts.
- clab-ui has a single fetch site, with an injectable fetchImpl (host/index.ts:620). It makes no telemetry, update or registry calls.
- The schema URL is only an identifier (enableSchemaRequest:false).
- api.github.com is called only by the VS Code host and, server-side, by the BFF.

4. THEMING.
- There is one static MUI theme. Its palette is entirely var(--vscode-*/--clab-ui-*) references (vscodePalette.ts:19-52).
- Light and dark are two token maps of about 80 entries each, applied by applyThemeVars(mode) (devTheme.ts:200). The INTEGRATORS quickstart shows the wrong signature for that function.
- MuiThemeProvider takes only children, and App wraps itself in it (AppContent.tsx:1455). A custom theme is therefore impossible without forking.
- Colours can be restyled fully through CSS variables. The Roboto font, the corner radius and the Material look are fixed.

5. IMAGE MANAGER.
- The host contract is four methods: listImages, listImageReferences, pullImage, removeImage (host/contracts.ts:179-184). There is no tar import and no registry browsing.
- The catalogue is a static in-source table of 50 kinds, with no source URL. It covers ceos, cjunosevolved, vjunosswitch and xrv9k.
- The /image-manager/catalog entry is pure: it imports only yaml.
- The editor's image picker needs only initialData.dockerImages. The dialog degrades cleanly when there is no image host.
- Image management would need Docker, which for the manager means a new host_operations mode.

6. DESKTOP. It is Electron 44 running the same BFF in-process on 127.0.0.1. It has no SSH tunnels, no updater and no server install.

7. VS CODE.
- It uses a postMessage host and runs TopologySessionCore inside the extension, with a 55-line NodeFsAdapter.
- Deploy goes through vscode.commands, and it needs no clab-api-server.
- Counting this host, three transports exist, which proves the host layer is replaceable.

8. CLAB-VIEWER. It is a 12-line read-only repackaging of the viewer and is not on npm (E404). Its iframe component conflicts with the manager's X-Frame-Options: DENY. It is not a builder.

9. PACE.
- The repo was created 2026-03-31 and has 38 stars, 7 open issues and 3 open PRs.
- FloSch62 has 190 of 208 commits. There were 51 commits in the last week.
- The latest GitHub release is v0.2.2 (2026-08-17).
- In the two days between 0.3.2 and HEAD, MUI went 7→9, maplibre 5→6 and zustand 4→5.
- Every version is 0.x, and no compatibility policy is written down.

## Load-bearing claims

- **[verified-in-code]** The published npm package (@containerlab/clab-ui 0.3.2, the only version) lacks the App `slots` and `lifecycleActionsAvailable` props that HEAD documents. Today a host cannot hide Deploy/Destroy or inject a header through supported props.
  - Evidence: PUB/dist/App.d.ts declares only {initialData, runtime, chrome}. `grep -rl lifecycleActionsAvailable PUB/dist` returned 0 files, for both .d.ts and .js. The tarball's INTEGRATORS.md has 0 mentions of `slots`. HEAD has them at UP/packages/clab-ui/src/AppContent.tsx:301-317. `npm view` shows versions = "0.3.2", created 2026-09-17.
- **[verified-in-code]** Upstream's own strictest host CSP requires style-src 'unsafe-inline', script-src 'unsafe-eval' and worker-src blob:. The manager's CSP allows none of these by default.
  - Evidence: UP/apps/vscode-containerlab/src/reactTopoViewer/extension/panel/PanelManager.ts:119 holds the full CSP string, including connect-src for tile.openstreetmap.org. Manager policy: MGR/clab-backup-ui/app/main.py:122-123. The upstream web server sets no CSP: grep across apps, packages and docs finds CSP only in two VS Code files.
- **[verified-in-code]** YAML schema validation uses ajv code generation (`new Function`). ajv is the default validator, and it is called outside any try/catch from a setTimeout. Without 'unsafe-eval' the editor keeps working, but uncaught errors are thrown, which the manager's browser gate counts. Configuration cannot avoid this.
  - Evidence: The code facts are verified: UP/packages/clab-ui/src/components/monaco/MonacoCodeEditor.tsx:299-304 (new Ajv, compile), :371-375 (try/catch covers the YAML parse only), :408, :455 (monaco-yaml language service off unless window.enableMonacoYamlLanguageService === true), :660-671. ajv's `new Function(` is present in PUB/dist-viewer/assets/MonacoCodeEditor-DJBuQ8ey.js. The gate records console type 'error' and pageerror at MGR/docs/redesign/tools/verify_after.py:32-33,512. The runtime failure mode under CSP is inferred, not executed.
- **[inferred]** A nonce-based style policy is not achievable. The lab-builder page would need `style-src 'self' 'unsafe-inline'`, the same per-path exception the manager already grants terminal.html and capture-session.html.
  - Evidence: Repo-wide grep finds 0 hits for CacheProvider, createCache, StyledEngineProvider or nonce. The bundled emotion code sets a nonce only when the cache has one (PUB/dist-viewer/assets/viewer-CYRFe_Xs.js: `i.nonce!==void 0&&o.setAttribute("nonce",i.nonce)`). clab-ui injects an un-nonced <style> at MonacoCodeEditor.tsx:139-148. The bundled Monaco chunk has 3 createElement('style') calls and 1 nonce reference. Manager precedent: main.py:122. That an outer CacheProvider would reach App's internal provider is inferred from emotion being external to the dist (build.mjs:73-82) and deduped by the consumer (vite.config.ts:55-61).
- **[verified-in-code]** clab-ui cannot be themed with a custom MUI theme without forking. It can be fully recoloured, in light and dark, through CSS custom properties.
  - Evidence: MuiThemeProvider is React.FC<{children}> with a hard-coded theme (UP/packages/clab-ui/src/theme/MuiThemeProvider.tsx:13-18; identical in PUB/dist/theme/MuiThemeProvider.d.ts). App wraps itself in it at AppContent.tsx:1455,1719. Every palette value is a var(--clab-ui-*/--vscode-*) reference (vscodePalette.ts:19-52). The token maps DARK_VARS and LIGHT_VARS are applied by applyThemeVars(mode) at devTheme.ts:23-207. Typography is the literal 'Roboto' and the radius is 4 (vscodeTheme.ts:261-269).
- **[verified-in-code]** A consumer-side bundler is mandatory, and upstream's toolchain cannot run on this VM. Upstream needs exactly Node 24.21.0 and pnpm 12.4.2, enforced by a preinstall hook, plus Vite 8. The VM has Node 18.19.1 and neither pnpm nor corepack.
  - Evidence: UP/packages/clab-ui/build.mjs:59-82,105-106 marks all dependencies, peers and .css imports external. UP/package.json:9,39,56 and UP/scripts/check-package-manager.mjs:1-7 set the Node and pnpm pins. `npm view vite@8.3.0 engines.node` returns "^20.19.0 || >=22.12.0". `node --version` returns v18.19.1, and `which pnpm corepack` found neither. vite@5/6 and esbuild accept Node 18 per the registry, but no such build was run.
- **[verified-in-code]** The host layer is genuinely replaceable, and the topology session can run in the browser. TopologySessionCore and the small FileSystemAdapter interface are public exports, present in published 0.3.2. Upstream already ships three different hosts.
  - Evidence: PUB/dist/session/index.d.ts exports TopologySessionCore and FileSystemAdapter. The interface is at UP/packages/clab-ui/src/core/io/types.ts:42-64. The in-browser session over localStorage is at UP/packages/standalone-runtime/src/pagesSandboxRuntime.ts:147,891-903. The VS Code host uses a 55-line NodeFsAdapter (apps/vscode-containerlab/src/reactTopoViewer/extension/shared/io.ts:10-53) and deploys via vscode.commands (services/LabLifecycleService.ts:27-82,126). The web host goes over HTTP (standaloneLifecycle.ts:235,414). INTEGRATORS.md:246-251 documents a custom ClabUiHost.
- **[verified-in-code]** The upstream web and desktop apps cannot be reused without a separate clab-api-server on the lab host. Their 33k LOC of glue is private and unpublished. A sidecar could not be iframed by the manager.
  - Evidence: UP/docs/manual/gui/web.md:8-16,92-106 and UP/docs/manual/gui/index.md:34-35 state the clab-api-server requirement. `private: true` is set in packages/standalone-runtime/package.json:4 and packages/app-server/package.json:4. LOC counted with wc: 24,361 + 8,925. The manager sends X-Frame-Options DENY and frame-ancestors 'none', and has no frame-src (main.py:118,123). The manager's precedent for another-port apps is location.replace in static/grafana.js, and its static folder contains no iframes.
- **[verified-in-code]** clab-ui itself makes no third-party network calls: no telemetry, update check, registry or catalogue fetch. The only exception is OpenStreetMap tiles in the optional Geo layout, which is overridable. The image catalogue is a static 50-kind in-source table. The catalogue entry and the editor's image picker both work without any image-management backend.
  - Evidence: The single fetch site is UP/packages/clab-ui/src/host/index.ts:617-626, with an injectable fetchImpl. Grep for WebSocket, EventSource, XHR and sendBeacon in clab-ui/src finds none. OSM tiles are at hooks/canvas/useGeoMapLayout.ts:46-68, with the window.maplibreStyle override there. enableSchemaRequest:false is at yaml/index.ts:146-163. The image host contract is 4 methods at host/contracts.ts:179-184. The static table is in image-manager/kindGuidance.ts (50 kinds; :163-210 covers the Junos and XR kinds). catalog.ts:1-14 imports only yaml and internal parsers. The picker reads dockerImages at hooks/editor/useDockerImages.ts:122-160. The dialog fallback is at ImageManager.webview.tsx:741-745.
- **[verified-in-code]** The project is young, effectively single-maintainer and moving fast. Between the published package and HEAD, two days apart, it changed MUI 7→9, maplibre-gl 5→6 and zustand 4→5. Everything is 0.x, and there is no written compatibility policy for the host contracts.
  - Evidence: `gh api repos/srl-labs/containerlab-app` reports created_at 2026-03-31, 38 stars, open_issues_count 10 (7 issues + 3 PRs via the search API). Contributors: FloSch62 190, kaelemc 16. Weekly commits [3,6,0,1,0,0,6,3,1,3,4,51]. There are 8 releases; the latest is v0.2.2, on 2026-08-17. PUB/package.json dependencies compared with the UP/pnpm-workspace.yaml catalog show the version jumps. UP/RELEASING.md:3-13,95-107 describes per-product tags and the rename from @srl-labs/clab-ui, with no semver promise. @containerlab/clab-viewer returns E404 on npm, despite INTEGRATORS.md:665 telling users to install it.

## Open questions

- No browser run under the manager's CSP was done. Three runtime behaviours are inferred from source and the bundled output, not observed. First, the exact failure mode without 'unsafe-eval': an uncaught EvalError per validation cycle is expected. Second, whether Geo layout fails softly via initError when blob: workers are blocked. Third, whether emotion's production insertRule path is blocked by style-src 'self' in Chromium.
- It is untested whether an outer emotion CacheProvider with a nonce reaches App's internal MuiThemeProvider. Even if it does, Monaco's un-nonced style elements appear to make a nonce-only style policy unworkable. I did not find a Monaco nonce option, and did not read Monaco's source because no node_modules are installed.
- The real size of a trimmed editor build is unknown; 10-15 MB is an estimate from the bundled viewer in the 0.3.2 tarball. It is also unknown whether Vite 5/6 or plain esbuild on Node 18.19 can bundle 0.3.2 with React 19 and MUI 7. Nothing was built.
- I could not determine when clab-ui 0.4.0 will be published, or whether the /host and /session contracts changed between 0.3.2 and HEAD. The clone is a single commit with no history, and I found no CHANGELOG for packages/clab-ui (only PUBLISHING.md and INTEGRATORS.md).
- It is not determined how much of the manager's existing operations API maps onto FileSystemAdapter (readFile, writeFile, unlink, rename, exists) without a change to the security-sensitive host_operations.py helper. It is also not determined how pages mode's window.fetch monkeypatch would be replaced by a proper custom ClabUiHost. The 0.6-1.2k LOC glue estimate depends on both.
- Image list, pull and remove for the manager would need Docker access that the manager deliberately lacks. Whether a new host_operations mode is acceptable is a policy question. Upstream offers no tar-import or registry-browse capability to reuse.
- There is a licence metadata inconsistency at the repo root: the LICENSE file is MIT, while package.json says Apache-2.0. clab-ui itself is consistently Apache-2.0. I did not audit the licences of the 22 bundled runtime dependencies.
- I did not inspect the GHCR web image (ghcr.io/srl-labs/containerlab-web), because there is no docker use in this phase. The root LICENSE and RELEASING.md imply a web-v0.3.0 image, but no such Git tag or release exists yet; the latest release is v0.2.2.
- WEB_BASE_PATH is supported in code and has a test script, but it is absent from the documented environment table. I did not determine whether upstream regards sub-path hosting as supported for integrators.
