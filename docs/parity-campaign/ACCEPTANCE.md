# Parity campaign: current acceptance matrix

The acceptance matrix of the parity campaign against the baseline [PARITY.md](PARITY.md) (dated 2026-10-23 01:00).
It describes revision `e709f3d` on `claude/parity-campaign`, release 1.31.6, as of 2026-10-27. It records what the
design answers ([C02](C02-DESIGN.md) to [C09](C09-DESIGN.md)), [PICKUP.md](PICKUP.md) "Log",
`clab-backup-ui/VALIDATION.md` and `docs/CHANGELOG.md` say; the implementation location was confirmed by one grep of
the symbol in `clab-backup-ui/app/`, nothing was re-run for this file. The chunk numbers are those of
[README.md](README.md) (PARITY.md's own proposal numbers chunks differently, and its R075 sits in a chunk README does not
claim). Where a record could not be found the cell says "unverified".

**Vocabulary.** *Implementation status* is one of: shipped, partial, not started, not pursued. It is kept apart from
*verification*, whose type letters are U unit (Python or `node --test`), F fixture or browser (the fixture manager,
Playwright, `check_c06.py`), L live (the `parity` lab through the manager on the development VM), and `none`.
"Where recorded" names the design section or the VALIDATION release; "pre-campaign" means the row was at parity before
the campaign and no campaign record tests it as a row. Static checks (`node --check`, `verify-release.py`,
`check_links.py`) are recorded by every release and are not repeated per row. A review is not a test: reviews are
listed in the gaps table when one was dropped.

| R-id | Feature | Baseline | Chunk | Intended behaviour | Implementation location | Impl. status | Verification (type: where recorded) | Tested revision / release | Remaining work | Owner |
|---|---|---|---|---|---|---|---|---|---|---|
| R035 | vJunos-router as managed kind | absent | C01 | Backups, downloads, saves, catalog know the kind; restore and design stay off | inventory.py `JUNOS_ROUTERS`, `PLATFORMS`, `CONSOLE_PORTS` | shipped (restore off by design) | U+L: `VJunosRouterKindTests`; 5/5 test logins and backups on the parity lab, router on the local nested image (VALIDATION 1.31.2; PICKUP 02:30, 02:44) | 673c0e6 / 1.31.2 | Published image crash-loops on the nested VM (C00); bare-metal boot unverified; node record keeps imported tag until Sync from VM | lead |
| R025 | Copy on drawer facts and operation output | absent | C02 | Copy buttons put the shown value on the clipboard, also inside dialogs and on plain http | clipboard.js `copyText`; operations.js; terminal.js | shipped | U+F+L: `test_clipboard_ui.js`; fixture Chromium+Firefox over http (C02 §8, VALIDATION 1.31.2); drawer Copy rows live on `vrt` (VALIDATION 1.31.3) | d00ccf1..c3f3d94 / 1.31.2; live 1.31.3 | none | none |
| R110 | Terminal font size and zoom chords | absent | C02 | Toolbar and Alt chords change the xterm font size, remembered | terminal.js `FONT_SIZES`, `clampFont` | shipped | U+F: `test_terminal_ui.js`; fixture (C02 §8, VALIDATION 1.31.2). Font size not named in the live terminal pass | d00ccf1..c3f3d94 / 1.31.2 | Alt chords no longer reach readline CLIs (recorded trade-off, C02 §8) | none |
| R111 | Terminal copy selection or screen, clear | absent | C02 | Copy and Clear in the toolbar | terminal.js `clearScreen` | shipped | U+F: `test_terminal_ui.js`; fixture paste-back of exact values (VALIDATION 1.31.2) | same / 1.31.2 | none | none |
| R112 | Terminal export (screen, session) | absent | C02 | Save screen and Save session with fixed names and contents | terminal.js `sessionText`, `sessionParts` | shipped | U+F+L: export names and contents on the live cEOS terminal (VALIDATION 1.31.2, clab-ui-qa re-check) | same / 1.31.2 | none | none |
| R010 | Stop a running lifecycle command | absent | C02 | Stop ends the helper process group; job `cancelled`; lock freed | lab_operations.py `OperationStopped`, `cancel_requested`; operations.js banner Stop | shipped | U+F+L: `OperationStopTests` (25); `evidence/c02-live-stop.md` (two runs: group gone 1.0 s/1.6 s, lock free 1.0 s/1.2 s); SIGKILL escalation not reached | d00ccf1..c3f3d94 / 1.31.2 | none (SIGKILL path not exercised live) | none |
| - | Hide the editor About entry (no R-id) | - | C02 | `navbar-about` hidden in both editor pages | lab-builder.css `[data-testid="navbar-about"]` | shipped | U: `test_lab_builder_ui.js` hidden-id pin (C02 §4). No browser record found | 1.31.2 | unverified in a browser | none |
| R020 | Container logs viewer | absent | C03 | Tail, Find, Follow, Export; redacted, never persisted | device_diagnostics.py; host_operations.py `logs`; device-diagnostics.js | shipped | U+F+L: `test_host_diagnostics.py`, `test_device_diagnostics*.py/js`; live on vrt, vsw, xrv9k, then ceos and cjunos after the Health-format fix (C03 §11; VALIDATION 1.31.2, 1.31.3) | helper c3f3d94 / 1.31.2; UI ac73779..cd91e2d / 1.31.3 | Redaction is keyword-based (heuristic); no live check beyond the listed kinds | none |
| R028 | Interface list with state, alias, role | absent | C03 | Interfaces section of the device drawer; Junos port names as aliases | device_diagnostics.py; host_operations.py `interfaces`; device-diagnostics.js | shipped | U+F+L: vrt 6 interfaces; ceos 16, cjunos 15 after fix (VALIDATION 1.31.2, 1.31.3) | same / 1.31.3 | none | none |
| R029 | Bounded interface counter sample | absent | C03 | RX/TX rates from a second sample, no streaming | host_operations.py `interfaces` (`counters_reason`); device-diagnostics.js | shipped | U+F+L: rates from the second sample live (VALIDATION 1.31.2, 1.31.3) | same / 1.31.3 | none | none |
| R030 | Containerlab version | partial | C03 | Version shown in the menu and Diagnostics when capabilities are cached | diagnostics.py `containerlab_version`; operations.js menu; debug.js | shipped (version only; update check not pursued) | U+F+L: menu version live (VALIDATION 1.31.3); Diagnostics wiring added after verification M1 (C03 §11) | cd91e2d / 1.31.3 | none | none |
| R013 | Inspect table extras | partial | C03 | Sort, filter, container id, owner and more columns | operations.js `opInspectionRows`, `opInspectionTable` | shipped | U+F+L: `test_operations_ui.js`; Owner `archtop` live (VALIDATION 1.31.3) | same / 1.31.3 | none | none |
| R091 | View files in the lab folder | partial | C03 | Read-only, redacted viewer (`browse` files mode, `view`) bounded to the lab folder | device_diagnostics.py `browse`, `folder_of`; operations.js `opBrowse` | shipped | U+F+L: files down to `ceos/flash/startup-config` live (VALIDATION 1.31.3) | same / 1.31.3 | Parent-symlink sentence unreachable (C03 §10 optional); see gaps | lead (next helper change) |
| R100 | Images on the VM, used by, missing | partial | C03 | Images dialog from the Manager menu | device_diagnostics.py `vm_images`, `image_answer`; operations.js `opImages` | shipped | U+F+L: 14 images, `used_by` live (VALIDATION 1.31.2); fixture 1.31.3 | same / 1.31.3 | No image-id column (C03 §11 L6, accepted); `used_by` shows topology tag, not the running local image | none |
| R021 | Serial console for vrnetlab kinds | absent | C04 | Console button once healthy; one console per device; gated server-side | node_services.py `console_gate`; node_console.py; terminal.js; status.js `consoleState` | shipped | U+F+L: `test_node_console.py`, `test_nodes.py`; 52/52 fixture checks; live on `vrt` only (VALIDATION 1.31.3) | cd91e2d / 1.31.3 | Live proof only for vJunos-router; vsw and xrv9k (also in `CONSOLE_PORTS`) not exercised live; relaunch-in-place window (C04 §8) | lead |
| R024 | Container facts in the device drawer | partial | C04 | Container section: id, kind, running image, all addresses, state, Copy | discovery.py (`container_id`, then `id`); app.js `renderDetails` | shipped | U+F+L: vrt Container section live; id break found and fixed (VALIDATION 1.31.3) | 31c48d0..cd91e2d / 1.31.3 | Live pass on vrt only | none |
| R040 | Link impairments set and reset | absent | C05 | Delay, jitter, loss, rate on a device interface; management interface refused | impairments.py; host_operations.py `netem-set`, `netem-reset`; device-impairments.js | shipped | U+F+L: `test_impairments.py` (32); drawer 24/24 fixture; live Apply/Reset/Clear all on `ceos`; vJunos row break fixed (`2d8afde`) and re-checked on ceos only (VALIDATION 1.31.4) | 3b36667 + fixes / 1.31.4 | Persistence across Restart, Stop/Start, Redeploy NOT run; no vJunos live re-check after the alias fix | lead |
| R041 | Per-node impairments table, Clear all | absent | C05 | All interfaces of a device in one table; Clear all from the map | impairments.py; host_operations.py `netem-show-all`; device-impairments.js | shipped | U+F+L: ceos Clear all clean in 1.6 s live (VALIDATION 1.31.4) | same / 1.31.4 | Same lifetime gap as R040 | lead |
| R042 | Impairments visible on the map after reload | absent | C05 | Wire title and caption "n links impaired" | topology.js; topology-render.js; impairments.py | shipped | F+L: map badge 35/35 fixture; caption and wire title live on ceos (VALIDATION 1.31.4) | same / 1.31.4 | Survival across restart/redeploy unverified (design §6 step 7) | lead |
| R005 | Start and Stop one device | absent | C05 | Reviewed start-node / stop-node under the host lock | host_operations.py `start-node`, `stop-node`; app.js `nodeActions`; topology.js | shipped | U+F+L: Stop then Start `ceos`, Ready ~1 min later (VALIDATION 1.31.4) | same / 1.31.4 | none | none |
| R006 | Apply with dry-run plan | partial | C05 | Apply review shows the plan (create/recreate/links) before running | host_operations.py `apply-plan`; impairments.py; operations.js | shipped | U+F+L: "Nothing to apply" and a real plan live (VALIDATION 1.31.4) | same / 1.31.4 | Apply recreates neighbours whose kind lacks live link support (containerlab behaviour; open point, C05 §12) | lead |
| R007 | Pending-changes indicator | absent | C05 | Banner line when the topology file differs from the deployed lab | lab_operations.py; impairments.py; app.js | shipped | F+L: pending line fixture; banner "Review changes…" after the filtered destroy live (VALIDATION 1.31.4) | same / 1.31.4 | none | none |
| R008 | Deploy/destroy by node filter | absent | C05 | `nodes` option, button names the device | host_operations.py (`nodes`, `--node-filter`); operations.js | shipped | U+F+L: filtered destroy of `ceos` live, others stayed running (VALIDATION 1.31.4) | same / 1.31.4 | none | none |
| R009 | Extra run flags (max workers etc.) | partial | C05 | Run with options on deploy, redeploy, destroy, save | host_operations.py (`max-workers`); operations.js | shipped | U+F+L: Max workers 2 live (VALIDATION 1.31.4); other flags unit/fixture only | same / 1.31.4 | Flags other than Max workers unverified live | lead |
| R011 | Save one device configuration | partial | C05 | Drawer action runs `containerlab save --node-filter` | app.js `nodeDrawerActions`; operations.js | shipped | U+F+L: ran on `vrt` (VALIDATION 1.31.4) | same / 1.31.4 | none | none |
| R043 | Link up/down colours | absent | C06 | Wires coloured from the helper-run interface listing; chip shows state | device_diagnostics.py `link-state`; host_operations.py `interfaces` (`all`); map-tools.js `mapLinkStates` | shipped | U+F+L: `test_map_tools_ui.js`, `check_c06.py`; API live 5/5, cEOS `dormant` in 12 s (C06 §12; VALIDATION 1.31.6) | c733849 + merge / 1.31.6 | Browser chip not run on the live lab; containerlab <0.64 unit only; vJunos shows `connected` (veth stays up) | lead |
| R066 | Stored annotation styles on the Topology tab | partial | C06 | Renderer honours stored text/shape styles, nesting | topology.py `parse_drawing`; topology-render.js | shipped | U+F: `test_topology*.py/js`, `check_c06.py` (VALIDATION 1.31.6). Live not run | c733849 / 1.31.6 | No live browser check | lead |
| R067 | Download picture (SVG, PNG) | partial | C06 | `#map-picture-dialog`, SVG and PNG via data URL | map-tools.js; index.html | shipped | F: `check_c06.py` at 1440 (54 ok) and fixture QA; live not run (VALIDATION 1.31.6) | c733849 / 1.31.6 | No live browser check | lead |
| R068 | draw.io export layout and theme | partial | C06 | `GET /drawio?layout=&theme=`; map, rows, print, manager | drawio_export.py `drawio` | shipped | U+L: golden fixture; API 200/400 live (C06 §12) | 1.31.6 | none | none |
| R069 | Find a device, link hover | absent | C06 | Find box highlights; hover highlights wire | map-tools.js; topology.js | shipped | F: `check_c06.py`, fixture QA at 3 widths; live not run (VALIDATION 1.31.6) | c733849 / 1.31.6 | No live browser check | lead |
| R064 | Arrange devices outside Edit map | absent | C06 | `POST /arrange` rows/columns; Undo; keeps map document | layout.py `arrange`, `keep_document`; lab_operations.py | shipped | U+F+L: `test_layout.py`; live arrange and exact Undo, stale Undo 412 (C06 §12) | 1.31.6 | Undo entries of removed labs never dropped (C06 §11 note) | lead |
| R070 | Boxed node and elbow link styles | absent | C06 / C11 | Render half: stored styles drawn on the Topology tab. Editor half: needs clab-ui 0.4.0 | topology.py; topology-render.js (render half) | partial (editor half blocked) | unverified: render half rides inside the C06 unit and fixture evidence, no row-specific record found | 1.31.6 | Editor half blocked until 0.4.0 is on npm | upstream (npm) |
| R051 | One Wireshark per interface or for all | absent | C07 | Capture dialog: one session per interface or one for all connected | capture.py `LaunchRequest`, sets; capture.js | shipped | U+F+L: `CaptureSetTests`; 71 fixture checks; ceos All connected live (VALIDATION 1.31.5) | d4eb1f4, review base 6c3f5d5 / 1.31.5 | No real-device packet content inspected | lead |
| R052 | Capture both ends of a link | partial | C07 | Wire click opens link mode with both ends; one set request | capture.js wire menu; capture.py | shipped | U+F+L: vsw-vrt, two sessions, viewer title (VALIDATION 1.31.5) | same / 1.31.5 | Same | lead |
| R053 | Remembered selection and open mode | absent | C07 | `clab.capture.` memory written after a full success | capture.js; shell.js | shipped | F+L: memory restored both ends / one end (VALIDATION 1.31.5) | same / 1.31.5 | none | none |
| R054 | End all my sessions | partial | C07 | `POST /api/capture/sessions/end-all`, count re-read first | capture_sessions.py; capture.js | shipped | U+F+L: `{ended: 4, failed: []}` live (VALIDATION 1.31.5) | same / 1.31.5 | none | none |
| R071 | YAML schema diagnostics, completion, hover | partial | C08 | Problems list and gutter from the schema matching the VM containerlab; no completion/hover | lab-builder-check.js; lab-builder-yaml.js `locateYaml`; app/static/clab-schema | partial (diagnostics only) | U+F: `test_clab_schema.py`, `test_lab_builder_check_ui.js`; fixture 1440/760/390; `containerlab validate` probes on the VM for rules (C08 §10; VALIDATION also cites a §11 that the design lacks). No live deploy | 0fc010b / 1.31.6 | Completion and hover need Monaco / 0.4.0 (C11) | upstream (npm) |
| R072 | Stage validation with Juniper example | partial | C08 | `wait-for` and exec checks; help example | lab-builder-check.js; lab-builder-page.js; lab-builder.html | partial (checks only; no Stages tab) | U+F as R071. Deploy ordering on a wait-for loop never proven live (C08 §7.4 evidence file absent) | 0fc010b / 1.31.6 | Live deploy proof not run; Stages tab blocked | lead |
| R090 | Home lab filter | present (sic) | C09 | Filter by lab/device name, whole-label state | status.js; home.js `homeLabMatch` | shipped | U+F: `test_home_ui.js`, fixture 1440/760/390 Chromium+Firefox (C09 §10; VALIDATION 1.31.6). No live browser | e398842 / 1.31.6 | Baseline cell says present but its gap and the critic say no filter existed | none |
| R122 | Help group in the Manager menu | present (sic) | C09 | Help, kinds link, shortcuts, preferences in the menu | index.html; app.js | partial (student-guide item hidden) | U+F: `test_readiness_ui.js`, fixture (C09 §10) | e398842 / 1.31.6 | Guide item hidden: PDF not staged, owner question open (C09 §9 row 0, 5) | owner |
| R123 | Keyboard shortcuts dialog | present (sic) | C09 | Table of keys; reverse pin maps every keydown site | preferences.js; index.html | shipped | U+F: `test_shell_ui.js` pin, fixture (C09 §10) | e398842 + cite fixes / 1.31.6 | Stale device-menu order check in `verify_after.py` line 124 | lead |
| R125 | Per-browser preferences and Reset | present (sic) | C09 | Preferences dialog lists stored keys by family; Reset confirmation names effects | preferences.js; shell.js | shipped | U+F: `test_preferences_ui.js`, fixture (C09 §10) | e398842 + 6cf477e / 1.31.6 | No live browser | none |
| R039 | Load onto vJunos-router | absent | C10 | NOS-transaction restore proven live, then kind joins supported kinds | restore_junos.py `SUPPORTED_KINDS` (router absent) | not started | none | - | Needs a booting router (published image fails nested), driver proof with `docs/multi-platform-restore/tools` | lead + clab-network-specialist |
| R073 | Defaults and Groups inheritance editor | absent | C11 | Editor tab (0.4.0) | - | not started (blocked) | none | - | Blocked: npm lists clab-ui 0.3.2 only (per lead 2026-10-27, not re-checked here) | upstream (npm) |
| R074 | Kind-specific settings tab | absent | C11 | Editor tab (0.4.0) | - | not started (blocked) | none | - | Blocked as R073 | upstream (npm) |
| R076 | Rotation control | absent | C11 | Editor feature (0.4.0) | - | not started (blocked) | none | - | Blocked as R073 | upstream (npm) |
| R047 | Hide dummy links toggle | absent | C11 | Editor feature (0.4.0) | - | not started (blocked) | none | - | Blocked as R073 | upstream (npm) |
| R048 | Wait-for dependency arrows | absent | C11 | Editor feature (0.4.0) | - | not started (blocked) | none | - | Blocked as R073 | upstream (npm) |
| R077 | Several mgmt networks, macvlan | partial | C11 | Editor settings (0.4.0) | - | not started (blocked) | none | - | Blocked as R073 | upstream (npm) |
| R044 | Traffic Rate annotation, link rate labels | partial | none | Rate tiles on the map | - | not started | none | - | C06 §0: not in that chunk's rows; no chunk claims it | lead (decide) |
| R045 | Link info panel with RX/TX chart | absent | none | Link chart | - | not started | none | - | C06 §0: not in C06; no chunk claims it | lead (decide) |
| R001 | Deploy / Start lab | present | - | Already at parity at baseline | operations.js `opReviewCopy`; lab_operations.py | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R002 | Redeploy, Destroy, cleanup variants | present | - | Already at parity at baseline | host_operations.py `--cleanup` probe; Lab actions menu | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R003 | Lab-wide Start/Stop/Restart | present | - | Already at parity at baseline | operations.js `opReviewCopy` | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R004 | Restart one device | present | - | Already at parity at baseline | host_operations.py `restart-node` | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R012 | Operation output, history, Try again | present | - | Already at parity at baseline | operations.js `opShowJob`, `opHistory`, `opRetryRequest` | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R015 | Deploy from URL, popular labs | present | - | Already at parity at baseline | operations.js `opClone`, `opPopular` | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R016 | Topology file browse/create/upload/delete | present | - | Already at parity at baseline | operations.js; host_operations.py `create`/`delete` | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R017 | Per-node status badge | present | - | Already at parity at baseline | status.js `deviceState`; topology.js | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R023 | SSH to a node / all nodes | present | - | Already at parity at baseline | node_services.py; workspace.js | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R046 | Link label mode and distance | present | - | Already at parity at baseline | map-editor.html `#map-link-dialog` | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R050 | Browser Wireshark from node/interface/link | present | - | Already at parity at baseline | capture.js; capture_sessions.py | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R058 | VNC readiness wait, saved pcaps | present | - | Already at parity at baseline | capture.js; capture_sessions.py | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R060 | Visual topology editor | present | - | Already at parity at baseline | lab-builder.html on clab-ui 0.3.2 | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R061 | Bulk link, find, lock, undo/redo | present | - | Already at parity at baseline | lab-builder.html | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R062 | Annotations in the editors | present | - | Already at parity at baseline | map-editor-page.js | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R063 | Layout menu in the editors | present | - | Already at parity at baseline | map-editor-page.js | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R078 | Node templates | present | - | Already at parity at baseline | lab-builder-page.js | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R080 | Lab Settings dialog | present | - | Already at parity at baseline | lab-builder (0.3.2) | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R094 | Favorites and Recent ordering | present | - | Already at parity at baseline | home.js `homeOrder` | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R114 | Detach terminal, reconnect | present | - | Already at parity at baseline | terminal.html | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R126 | Responsive, reduced motion, contrast | present | - | Already at parity at baseline | style.css | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R133 | Reviewed lab operations; Save and Load | present | - | Already at parity at baseline | git_progress.py; restore.py | shipped (pre-campaign) | pre-campaign: not re-tested as a row; suites run in every release | pre-campaign | none | none |
| R014 | Live push of container/interface events | partial | - | Excluded | - | not pursued | n/a | - | Helper protocol is request/response NDJSON to EOF; polling plus bounded samples (R029) suffice | none (excluded) |
| R022 | Shell inside a container (docker exec) | absent | - | Excluded | - | not pursued | n/a | - | Needs a Docker socket or an interactive helper PTY; SSH CLI and serial console cover the need | none (excluded) |
| R026 | Pause/unpause a node | absent | - | Excluded | - | not pursued | n/a | - | Mutating Docker verb outside containerlab lifecycle; Stop/Start device (R005) covers it | none (excluded) |
| R036 | vJunosEvolved kind | absent | - | Excluded | - | not pursued | n/a | - | No image on the VM to prove it; only live-proven kinds are supported | none (excluded) |
| R055 | Several captures as tabs in one viewer | absent | - | Excluded | - | not pursued | n/a | - | Not pursued in C07 §8: one RFB per viewer page; two browser tabs instead | none (excluded) |
| R056 | Edgeshark hand-off to local Wireshark | absent | - | Excluded | - | not pursued | n/a | - | Browser Wireshark is the capture path; session service alone holds the Docker socket | none (excluded) |
| R057 | Edgeshark install and capture settings | absent | - | Excluded | - | not pursued | n/a | - | Same as R056; image pinned by digest, no client-supplied image | none (excluded) |
| R065 | Geo layout | absent | - | Excluded | - | not pursued | n/a | - | Needs external tiles and a relaxed CSP | none (excluded) |
| R075 | Node login fields from the topology file | absent | - | Excluded | - | not pursued | n/a | - | Login order profile > inventory > kind default is binding; field hidden on upgrade | none (excluded) |
| R079 | Custom icon upload | absent | - | Excluded | - | not pursued | n/a | - | Needs host storage (write mode removed); browser-only icons would not travel with the map | none (excluded) |
| R081 | Grafana bundle, Telemetry style | absent | - | Excluded | - | not pursued | n/a | - | Telemetry and Grafana retired (2026-09-23) | none (excluded) |
| R092 | Arbitrary file create/rename/delete/edit in lab folder | absent | - | Excluded | - | not pursued | n/a | - | Helper write mode removed; read-only viewing shipped as R091 | none (excluded) |
| R093 | Download lab folder as archive | partial | - | Excluded | - | not pursued | n/a | - | Bundle protocol is four named files; Save then Download ZIP covers it | none (excluded) |
| R095 | Shared labs, owner labels | absent | - | Excluded | - | not pursued | n/a | - | No login by design | none (excluded) |
| R096 | Several labs open in tabs | absent | - | Excluded | - | not pursued | n/a | - | Redesign fixes the workspace shape; browser tabs suffice | none (excluded) |
| R097 | Multiple lab hosts, sign-in | absent | - | Excluded | - | not pursued | n/a | - | No login, one VM, one Store | none (excluded) |
| R101 | Per-kind image guidance | absent | - | Excluded | - | not pursued | n/a | - | Not pursued (C09 §8); Help kinds link is a pointer to containerlab.dev only | none (excluded) |
| R103 | Remove a local image | absent | - | Excluded | - | not pursued | n/a | - | Destructive on a shared VM whose images load from tarballs | none (excluded) |
| R113 | Terminal tabs and split panes | absent | - | Excluded | - | not pursued | n/a | - | Redesign contract; browser tabs give independent sessions | none (excluded) |
| R120 | Dark mode and themes | absent | - | Excluded | - | not pursued | n/a | - | Binding UI contract allows dark only for toast and terminal (README C09). PARITY proposed a simple dark mode: contradicted | none (excluded) |
| R121 | Theme editor, import/export | absent | - | Excluded | - | not pursued | n/a | - | Out of scope | none (excluded) |
| R130 | Terminal sharing via SSHX/GoTTY | absent | - | Excluded | - | not pursued | n/a | - | Third-party relays, weak defaults on a login-free manager | none (excluded) |
| R131 | fcli reports | absent | - | Excluded | - | not pursued | n/a | - | SR Linux only, pulls an image per run | none (excluded) |
| R132 | Embeddable viewer | absent | - | Excluded | - | not pursued | n/a | - | Documentation-site tooling; Download picture (R067) covers course material | none (excluded) |
| R134 | Endpoint health metrics | absent | - | Excluded | - | not pursued | n/a | - | Manager never gets host metrics | none (excluded) |

## Recorded gaps to reconcile

| # | Gap | Rows | Recorded in | Note |
|---|---|---|---|---|
| 1 | Full `/clab-review-changes` on C06, C08 and C09 deferred for budget; replaced by one `risk-reviewer` pass (C06 backend diff) and one `clab-ui-reviewer` pass each (C08, C09) | R043, R064, R066 to R070; R071, R072; R090, R122, R123, R125 | PICKUP 17:30 entry; VALIDATION 1.31.6 "Not run" | Not run, still open |
| 2 | C10: Load onto vJunos-router not started; kind stays out of `SUPPORTED_KINDS` | R039 | PICKUP 17:30; README C10 | Needs a booting router |
| 3 | C11: editor 0.4.0 blocked. The lead's brief says npm lists only 0.3.2 as of 2026-10-27 (not re-checked here) | R060 to R074, R047, R048, R076, R077; the editor half of R070, R071, R072 | README C11; PARITY "C13" | Blocked upstream |
| 4 | C05 impairment lifetime across Restart device, Stop/Start device and Redeploy not run; the caption is worded cautiously until then | R040, R041, R042 | C05-DESIGN §9 row 26, §12; VALIDATION 1.31.4 "Not run" | Also no vJunos live re-check after the alias fix (only ceos) |
| 5 | C07: no capture proof with real device packets; viewer loading only, loopback packets in CI smoke | R051, R052 | C07-DESIGN §11; VALIDATION 1.31.5 "Not run" | Chromium only on the VM |
| 6 | C06 "Not run live": browser chip, Find, hover, Download picture on the live lab; link-state helper on containerlab older than 0.64 | R043, R067, R069 (R066, R070 by extension) | C06-DESIGN §12; VALIDATION 1.31.6 | Fixture evidence only |
| 7 | `docs/redesign/tools/verify_after.py` line 124 still expects menu order `Open, Capture, Back, Restart, Device`; Console, Stop and Start device were added by C04 and C05 | R021, R005 (menu), R123 | C09-DESIGN §10 last row | Tool expectation stale; lead refreshes it |
| 8 | C03 §10 optional: parent-directory `O_NOFOLLOW` branch unreachable for a symlinked parent (open still refused) | R091 | C03-DESIGN §10 | Next helper change |
| 9 | C03 §11 L6: Images dialog has no image-id column (accepted, design has none) | R100 | C03-DESIGN §11 | Closed by decision |
| 10 | C03 §11 L13: a disabled Capture button's reason only in the caption | R020, R028 (drawer) | C03-DESIGN §11 | No change, by design |
| 11 | C03 §11 live: Image row and "used by" show the topology tag while `vrt` runs the local nested derivative | R100, R024 | C03-DESIGN §11 | C04's Container section shows the running image |
| 12 | C04 §8 residual risk: console gate reads discovery's view; relaunch-in-place and out-of-band restart windows; fourth review condition not built | R021 | C04-DESIGN §8 | Live proof only on `vrt` |
| 13 | C05 §12 live: Apply after a filtered destroy recreates neighbours whose kind cannot add links live | R006, R008 | C05-DESIGN §12 | containerlab behaviour, open point |
| 14 | C06 §10 low: link-state output can exceed the input and the 3 MiB line limit (fails closed as 409) | R043 | C06-DESIGN §10 | Byte-measured cut if it ever bites |
| 15 | C06 §11 notes: two-call window, re-serialised document, Undo entries of removed labs, capabilities cache not compared with host revision, "not running" wording when Docker is down | R043, R064 | C06-DESIGN §11 | Recorded, no privilege widened |
| 16 | C07 §10 and §11 cosmetic: dialog says `label: port`, session rows show the NOS name; two sessions on one end share a row label; relay logs a `WebSocketDisconnect` traceback; viewer asset probe 404 | R051, R052 | C07-DESIGN §10, §11 | One naming rule pending |
| 17 | C07 §12 optional: owner cookie lost when a launch request raises; the fixture's id derivation is a third copy under no automated check | R051, R054 | C07-DESIGN §12 | Open points |
| 18 | C09 §9 rows 5 and 13: student-guide item hidden (PDF not staged, owner question open); R101 recorded as not pursued (README applied it, PARITY.md baseline unchanged) | R122, R101 | C09-DESIGN §9, §8 | Owner decision |
| 19 | C09 §10 verification row: same as gap 7 | R123 | C09-DESIGN §10 | Duplicate of 7 |

Gaps 4, 6 and 7 to 19 carry the 17 open design-table rows (C03 §10 optional, §11 L6, L13 and live row = 8, 9, 10, 11; C04 §8 = 12;
C05 §9 row 26 = gap 4 and §12 live row = 13; C06 §10 low, §11 notes, §12 = 14, 15 and gap 6; C07 §10 cosmetic, §11
cosmetic, §12 two optional = 16 and 17; C09 §9 rows 5 and 13, §10 = 18 and 7), merged where rows overlap.

Evidence inconsistencies found while building this file:

- VALIDATION 1.31.6 cites "C08-DESIGN §11" and "C09-DESIGN §11" (and PICKUP the same); both designs end at §10, so the
  `clab-ui-reviewer` answers for C08 and C09 are in no design section. They are visible only in VALIDATION and the
  merge commits `7e4eb31`, `57d6060`.
- C08-DESIGN §7.4 plans a live deploy proof of stage ordering with evidence in `evidence/c08-live.md`; the file does
  not exist and VALIDATION says C08 has no live pass.
- PARITY.md marks R090, R122, R123 and R125 "present" in the Manager column while their gap and the critic say the
  feature did not exist; the baseline status column is unreliable for them.
- PARITY.md proposes a simple dark mode (R120); README (C09) and C09-DESIGN §1 record it as not pursued.

## Counts

98 rows in the matrix above (the nine unnumbered at-parity items of PARITY.md "Already at parity" are not rows).

| Implementation status | Rows |
|---|---|
| not pursued | 25 |
| not started | 9 |
| partial | 4 |
| shipped | 38 |
| shipped (pre-campaign, at parity) | 22 |

| Verification (best level recorded) | Rows |
|---|---|
| fixture (with unit where U) | 11 |
| live (with unit/fixture) | 29 |
| n/a (excluded) | 25 |
| none | 9 |
| pre-campaign (not re-tested) | 22 |
| unit only | 1 |
| unverified | 1 |
