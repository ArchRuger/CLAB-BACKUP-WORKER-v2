# Topology map, renderer and diagram editor — UI inventory

Source of truth (read completely, no lines skipped):

- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/topology.js` (52 lines)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/topology-render.js` (51 lines)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/diagram-editor.js` (84 lines)
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/index.html` (100 lines, skimmed for ids/markup)

Cross-checked (grep + targeted reads, not modified): `app.js`, `capture.js`, `operations.js`, `management.js`, `workspace.js`, `workspace.html`, `style.css`, and backend `topology.py`, `layout.py`, `lab_operations.py`, `runner.py`, `main.py`, `node_readiness.py`, `drawio_export.py`.

Script load order on `index.html` (all `defer`): `app.js` → `topology-render.js` → `topology.js` → `management.js` → `operations.js` → `diagram-editor.js` → `git-progress.js` → `git-places.js` → `restore.js` → `capture.js`. `workspace.html` loads `workspace.js` → `topology-render.js` → `operations.js` → `diagram-editor.js` (the renderer is reused there by `opMapPreview`; `editDiagram` is never called from `workspace.js`).

---

## 1. Globals defined

### topology.js
| Name | Kind | Purpose | Used from other files |
|---|---|---|---|
| `mapKey` | `let` string | Dedupe key `labId + JSON.stringify(drawing)` of last rendered drawing; `refreshMap` skips DOM rebuild when unchanged unless `force` | no |
| `mapRequest` | `let` number | Monotonic request counter; stale `/topology` responses are discarded | no |
| `mapBounds` | `let` `[x,y,w,h]` | Fit bounds measured after render (`measureTopology`) | no |
| `mapBox` | `let` `[x,y,w,h]` | Current SVG viewBox | no |
| `map` | `const` Element | `#topology-map` SVG | **yes** — `capture.js:147-149` adds click/contextmenu/keydown listeners to `map` |
| `setMapBox()` | function | Writes `mapBox` to the SVG `viewBox` attribute | no |
| `mapZoom(factor)` | function | Zooms about the centre; ignored if resulting width `<50` or `>400000` | no |
| `mapDrag` | `let` object/null | Pan drag state `{x,y,box}` | no |
| `mapAction(e)` | function | Click/Enter/Space on `[data-map-node]` → `openDetails(name)` | no |
| `nodeMenu` | `const` Element | `#node-context-menu` | no |
| `contextLab`, `contextNode` | `let` | Lab id and node element the menu was opened for | no |
| `closeNodeMenu(restore=false)` | function | Hides the menu; `restore` refocuses the node | **yes** — `capture.js:148` (link right-click) |
| `openNodeMenu(element,x,y)` | function | Builds and positions the context menu | no |
| `refreshMap(force=false)` | async function | Fetches and renders the map, updates `#map-status` | **yes** — `app.js:93` (`showTab`), `diagram-editor.js:82` |

Event listeners registered at load in `topology.js`: SVG `wheel` (passive:false), `pointerdown`, `pointermove`, `pointerup`/`pointercancel`/`lostpointercapture`, `click`, `keydown` (x2: Enter/Space, ContextMenu/Shift+F10), `contextmenu`; `nodeMenu` `click`, `keydown`; `document` `pointerdown`, `keydown` (Escape), `scroll` (capture phase); `window` `resize`, `blur`; `onclick` for `#map-fit`, `#map-in`, `#map-out`, `#map-expand`, `#import-map`, `#cancel-map`, `#export-sessions`, `#cancel-export`; `submit` for `#map-form`, `#export-form`.

### topology-render.js
| Name | Kind | Purpose | Used from other files |
|---|---|---|---|
| `topologyDecoration(d,index)` | function | SVG markup for a text/rectangle/circle/line/group annotation | no (internal) |
| `topologyNode(n)` | function | SVG markup for one device node | no (internal) |
| `topologyLink(pair,nodes,index,settings)` | function | SVG markup for one wire with interface labels | no (internal) |
| `topologyMarkup(drawing)` | function | Full SVG inner markup (defs, background, grid, scene) | **yes** — `topology.js:39`, `diagram-editor.js:39`, `operations.js:253` (`opMapPreview`, also on `workspace.html`) |
| `measureTopology(svg)` | function | Sizes label background rects from text bbox and returns fit bounds | **yes** — `topology.js:41`, `diagram-editor.js:41`, `operations.js:253` |

### diagram-editor.js
| Name | Kind | Purpose | Used from other files |
|---|---|---|---|
| `diagramAnnotation(type,x,y)` | function | Default new annotation object (see §6) | no |
| `diagramPayload(drawing)` | function | `{positions:{id:[x,y]}, decorations, revision}` | no |
| `diagramMove(item,dx,dy)` | function | Moves item, rounding and clamping to ±100000; a line's `x2/y2` follow | no |
| `editDiagram(id)` | async function | Opens the diagram editor dialog | **yes** — `operations.js:254` (`opLayout`) ← `#map-edit` at `operations.js:279` |

## 2. Globals consumed (defined elsewhere)

From `app.js` (index.html) — equivalents exist in `workspace.js` for the ones marked *: `$`*, `esc`*, `api`*, `json`*, `activeId`*, `current`*, `busy`*, `notify`*, `attachmentName`*, `withForm` (app.js:100 only), `openDetails` (app.js:154), `handleNodeAction` (app.js:106), `sshHint` (app.js:22; guarded by `typeof`), `startJob`/`openCapture`/`openNode` indirectly via `handleNodeAction`.
From `capture.js`: `captureActionAttrs` (guarded by `typeof`).
From `operations.js`: `opDialog`, `opTask`.
`refreshMap` is referenced from `diagram-editor.js` guarded by `typeof` (absent on workspace.html).

`api()` prefixes every path with `/api`; on non-OK it throws `Error(detail)` or `'Check the form fields and try again.'`/`'Request failed'`.

---

## 3. Capabilities — Topology view (`#topology-view`, `topology.js`)

Static markup in `index.html` line 54:

- Section heading: **Lab topology** — "Right-click a node for SSH, backups and capture. Click a link to capture either endpoint."
- Heading actions: `#map-ssh-all` "SSH all nodes ↗", `#map-backup-all` "Back up all configs", `#import-map` "Import topology" (primary).
- `.map-tools` row: `#map-expand` "Expand map", `#map-fit` "Fit map", `#map-in` "+" (aria-label "Zoom in"), `#map-out` "-" (aria-label "Zoom out"), static span "Drag to pan · Links show imported wiring, not live status", `#map-edit` "Edit diagram" (secondary).
- `#map-status` (`role=status`, 12px grey).
- `<svg id="topology-map" viewBox="0 0 1000 600" aria-label="Lab topology" role="group">` — CSS: 100% wide, 600px high (min 350), 1px border, radius 12, `touch-action:none`, `cursor:grab`, font Arial.

### 3.1 Viewing / navigation

| id | Label | Trigger | Behaviour | Gating |
|---|---|---|---|---|
| `topology.map-fit` | Fit map | `#map-fit` click | `mapBox=[...mapBounds]; setMapBox()` — restores the fit computed at last render | always enabled |
| `topology.map-zoom-in` | + (Zoom in) | `#map-in` click | `mapZoom(.8)` | no-op if width would be `<50` |
| `topology.map-zoom-out` | - (Zoom out) | `#map-out` click | `mapZoom(1.25)` | no-op if width would be `>400000` |
| `topology.map-wheel-zoom` | (none) | mouse wheel on SVG, `{passive:false}`, `preventDefault` | `deltaY>0` → `mapZoom(1.15)` (out) else `mapZoom(1/1.15)` (in); zoom is about the viewBox centre, not the cursor | same width limits |
| `topology.map-pan` | Drag to pan | `pointerdown` button 0 on SVG, **not** inside `[data-map-node],[data-capture-endpoints]`; `setPointerCapture` | `pointermove` shifts viewBox by pointer delta × `max(boxW/rectW, boxH/rectH)`; ends on `pointerup`/`pointercancel`/`lostpointercapture` (`mapDrag=null`) | only left button |
| `topology.map-expand` | Expand map / Close expanded map | `#map-expand` click | Toggles class `map-expanded` on `#topology-view`; label becomes "Close expanded map" when expanded; closes node menu. CSS: `position:fixed; inset:14px; z-index:50; background:#fff; padding:24px; radius 16px; box-shadow 0 0 0 30px #203b49aa; flex column`; SVG becomes `flex:1; height:auto; min-height:100px` | always |
| `topology.map-expand-escape` | (keyboard) | `document keydown Escape` when node menu is hidden | Removes `map-expanded` from `#topology-view` and resets `#map-expand` text to "Expand map" (runs on every Escape anywhere in the page, even when not expanded) | — |

### 3.2 Automatic refresh and status text

| id | Trigger | Behaviour |
|---|---|---|
| `topology.map-refresh` | `refreshMap()` called by `app.js showTab(tab)` whenever `tab==='topology'`; `showTab` runs on every `render()`, which runs on every `refresh()` — including the **4-second poll** (`app.js:180 setInterval(()=>refresh(),4000)`), lab selection, and any action that calls `refresh()`. Also `refreshMap(true)` after map import and after diagram save | `GET /api/labs/{activeId}/topology`. Ignores the response if `mapRequest` advanced or `activeId` changed. Computes `key=labId+JSON.stringify(drawing)`; if equal to `mapKey` and not forced → returns without touching DOM (so the map/viewBox/status are only rebuilt when the drawing or its node matching/revision changes). Otherwise: closes node menu, rebuilds `map.innerHTML=topologyMarkup(drawing)`, toggles `labels-on-select` class, measures bounds and resets `mapBox` (i.e., **any re-render resets the user's zoom/pan**) |
| `topology.map-status-empty` | drawing is `null` | SVG emptied; `#map-status` = "No map imported. Upload your annotations and lab topology to get started. The Nodes list remains available." |
| `topology.map-status-summary` | drawing present | `#map-status` = "`{nodes}` map nodes · `{links}` links · `{unmatched}` unmatched. " + (if `skipped_links`) "`{n}` unsupported or one-ended links omitted. " + (if `!has_links_source`) "Import the lab topology with annotations to show wiring." + "Unmatched nodes have no connection actions." (`unmatched` = nodes with no `inventory_name`) |
| `topology.map-status-schema-warning` | `drawing.schema !== 3` | appends " Reimport the original annotations and lab YAML to restore complete styling and NOS interface labels." |
| `topology.map-status-error` | fetch throws and request is still current | `#map-status` = "Could not load map: " + message |
| `topology.map-label-mode-class` | `drawing.settings.labelMode==='on-select'` | SVG gets class `labels-on-select` → CSS hides `.interface-label` (opacity 0) except inside a hovered `.topology-wire` |

### 3.3 Node interactions (matched nodes only — elements with `data-map-node`)

| id | Label | Trigger | Behaviour | Gating |
|---|---|---|---|---|
| `topology.node-open-details` | (node glyph; title "Right-click for SSH and node actions: {inventory_name}") | left click on `[data-map-node]`, or `Enter`/`Space` while the node has focus (`tabindex=0 role=button`) | `openDetails(inventory_name)` → app.js opens `#details-dialog` (Node workspace drawer) | only nodes with `inventory_name`; unmatched nodes have no `data-map-node`, no tabindex, `cursor:default` |
| `topology.node-context-menu-open` | (context menu, `role=menu` aria-label "Node actions") | right-click (`contextmenu`) on `[data-map-node]`; keyboard `ContextMenu` key or `Shift+F10` on a focused node (menu positioned at the node's `rect.right, rect.top`) | `openNodeMenu`: looks up `current().nodes` by name (silently returns if missing); records `contextLab=activeId`; fills menu HTML; shows it at `(x,y)` clamped to viewport with 8px margins using the menu's measured size; focuses first enabled button | — |
| `topology.node-menu-header` | "{short_name‖name}" + small "{address}:{port}" | rendered in menu | informational (`.context-node-name`) | — |
| `topology.node-menu-capture` | "Capture packets" | menu button `data-capture={name}` | via `handleNodeAction` → `openCapture(name)` (capture dialog) | `disabled title="Packet capture is not enabled. Open Capture packets for setup."` when `captureEnabled===false` (capture.js `captureActionAttrs`, fetched once from `GET /api/capture/status`) |
| `topology.node-menu-ssh` | "›_ SSH" + small "New tab ↗" | menu button `data-terminal={name}` | `window.open('/static/terminal.html#lab=…&node=…&label=…','_blank')` | `disabled title=sshHint(n)` when `!n.ssh_ready`; hint text: `nos_login.status==='booting'` → "NOS is still booting; SSH opens when it accepts a login"; `'failed'` → "SSH login failed with the saved credentials; assign a credential profile"; `'unavailable'` → "Node is not running"; otherwise "Assign credentials first" (also the fallback if `sshHint` is undefined). Backend: `ssh_ready = login_configured && nos_login.status in ('ready','unmonitored')` |
| `topology.node-menu-backup` | "↓ Back up configuration" | menu button `data-backup={name}` | closes `#details-dialog`; `startJob('backup',[name])` → `POST /api/labs/{activeId}/jobs {operation:'backup',node_names:[name]}`; switches tab to `backups`; toast "Backup started." (error → toast) | `disabled` (no title) unless `!busy() && n.readiness==='Ready'`. `readiness` ∈ 'Ready' / 'Choose NOS' / 'Needs credentials' / 'Lab unavailable'. `busy()` = any job queued/running, any operation queued/running, any git job queued/capturing/exporting/pushing |
| `topology.node-menu-details` | "ⓘ Node details" | menu button `data-details={name}` | `openDetails(name)` | always |
| `topology.node-menu-activate` | — | click inside menu | if `contextLab!==activeId` (lab switched since opening) → close without acting; else `handleNodeAction(e)` (ignores disabled buttons) then close | — |
| `topology.node-menu-keyboard` | — | `ArrowDown`/`ArrowUp`/`Home`/`End` inside menu | moves focus between **enabled** buttons, wrapping | — |
| `topology.node-menu-dismiss` | — | `document pointerdown` outside menu; `Escape` (restores focus to the node); `window resize`; `window blur`; any `scroll` (capture phase); a map re-render; `#map-expand` toggle; right-click on a link (capture.js) | `closeNodeMenu()` → `hidden=true`, `contextNode=null` | — |

### 3.4 Link interactions (markup from `topology-render.js`, handlers in `capture.js:147-149`)

| id | Trigger | Behaviour |
|---|---|---|
| `topology.link-capture` | left click, right-click (`preventDefault`, also closes node menu), or `Enter`/`Space` on a focused `.topology-wire[data-capture-endpoints]` (`tabindex=0 role=button`, aria-label "Capture A:ifA to B:ifB", title "A:ifA — B:ifB") | `openLinkCapture` parses the JSON `[{node,label,interface},{…}]` → `openCapture('', '', ends)` opens the packet-capture dialog on the first endpoint with endpoint switch buttons; parse failure → toast "Could not read this link. Use Capture packets to browse live interfaces." The `topology.js` click handler also fires but only acts on `[data-map-node]`, so a link click never opens node details |

### 3.5 Import topology dialog (`#map-dialog`, `#map-form`)

| id | Label | Trigger | Behaviour |
|---|---|---|---|
| `topology.import-map-open` | Import topology | `#import-map` click | `#map-form.reset()`, clears `.form-error`, `#map-dialog.showModal()` |
| `topology.import-map-cancel` | Cancel | `#cancel-map` | `dialog.close()` |
| `topology.import-map-submit` | Import map (submit) | `#map-form submit` | `withForm` (disables the submit button, clears then fills `.form-error` with the thrown message) → `POST /api/labs/{labId}/topology` multipart `FormData` (fields `annotations` file `.json` **required**; `topology` file `.yaml/.yml/.json` optional). On success: close dialog; if `activeId===labId` → `refreshMap(true)`; toast "Topology imported." Backend errors: 400 "Invalid drawing: …" (e.g. "Upload a containerlab .annotations.json file", "Annotations must be smaller than 1 MiB", "No nodes found; include the lab topology YAML", "Too many drawing nodes"), 409 "Wait for the lab operation to finish.", 404 "Lab not found" |

Dialog copy: h2 "Import lab topology"; labels "VS Code annotations JSON", "Lab topology YAML or topology-data.json"; help "Annotations supply positions, groups, and notes. Include the topology file to draw links. Imports replace the current map. Connections and credentials remain in your inventory."

### 3.6 Export sessions dialog (`#export-dialog`, `#export-form`) — lives in topology.js although the button is in the control row

| id | Label | Trigger | Behaviour |
|---|---|---|---|
| `topology.export-sessions-open` | Export sessions | `#export-sessions` (control-row `.actions`) | reset form, clear error, `#export-dialog.showModal()` |
| `topology.export-sessions-cancel` | Cancel | `#cancel-export` | close |
| `topology.export-passwords` | "Include saved passwords as plain text" | checkbox `#export-passwords` | read at submit |
| `topology.export-sessions-submit` | Download XML | submit | `withForm` → `POST /api/labs/{labId}/superputty` JSON `{include_passwords}` → `response.blob()` → `<a download>` named by `attachmentName(response,'sessions.xml')` (server sends `{lab}.xml`), `URL.revokeObjectURL` after 1 s; close dialog. Backend 400 e.g. "Duplicate session short names; edit node names before exporting", "Username contains unsupported control characters" |

Dialog copy: h2 "Export SuperPuTTY sessions"; "One lab folder, with a session for every inventory node using its short name and saved SSH address and port."; "Saved credentials take priority. Otherwise, known NOS kinds supply the default username. Your workstation must be able to reach these addresses."; "Optional passwords use PuTTY's -pw argument. Private keys are not exported. Without a saved password, PuTTY prompts at login."

### 3.7 Topology-view buttons wired in OTHER files (listed so the redesign keeps them)

| id | Label | Wired in | Behaviour | Gating |
|---|---|---|---|---|
| `topology.ssh-all` | SSH all nodes ↗ | `management.js:226` | `opNewTab({mode:'ssh',lab:id})` → opens `/static/workspace.html#mode=ssh&lab=…` in a new tab; if blocked shows `opDialog('op-open-tab','Open workspace')` with link | `app.js:57-58`: `disabled` when no node `ssh_ready`; `title` = "Waiting for the NOS to accept SSH logins; this opens automatically" if any node `nos_login.status==='booting'`, else "No node is ready for SSH" |
| `topology.backup-all` | Back up all configs | `management.js:227-232` | `opDialog('backup-all-review','Back up all configurations')`: "{ready} of {total} nodes are ready for a configuration backup. This includes ready nodes that are unchecked in the inventory." + optional "These nodes will be skipped:" list "{short_name‖name} · {readiness}" + button "Back up {n} nodes" → `POST /api/labs/{id}/jobs {operation:'backup',node_names}`; close; `refresh()`; toast "Configuration backup started. View progress in Backup history." | `app.js:59`: `disabled` when `busy()` or no node `readiness==='Ready'`; confirm button disabled when none ready or busy |
| `topology.map-edit` | Edit diagram | `operations.js:279` (inside `if($('import-top'))`) | `opTask(null,()=>editDiagram(activeId))` — errors (e.g. "Import a topology map first.") become toasts | no disabled state; throws when no map |

---

## 4. Rendering (`topology-render.js`) — every automatically drawn element

Input drawing (from `GET /api/labs/{id}/topology`, `bind_drawing`): `{schema:3, nodes:[{id, alias, label, x, y, icon, iconColor, labelPosition, labelBackgroundColor, iconCornerRadius, interfacePattern, direction, inventory_name|null}], links:[[{node,interface,label_offset?},{…}]], decorations:[…], settings:{background, gridColor, labelMode:'show-all'|'on-select'|'hide', endpointOffset}, has_links_source, skipped_links, placed, revision}`. `inventory_name` is set when exactly one inventory node matches the drawing node's `alias` by name / short_name / definition_node / name minus `clab-{lab}-` prefix.

| id | What is drawn | Rules |
|---|---|---|
| `render.background-grid` | `<pattern id="topology-grid">` dots (r .6, 20px pitch, `settings.gridColor` default `#d2cbb5`) over a 400000×400000 rect filled `settings.background` default `#fdf6e3` | always |
| `render.scene-order` | `<g id="topology-scene">` = decorations (sorted by `zIndex` ascending, stable) → links → nodes | decorations always beneath wires and nodes |
| `render.node-glyph` | `g.map-device` translated to `(x+20, y+20)`; 40×40 `rect.device-body` fill `iconColor` (default `#0066ff`), `rx=iconCornerRadius` (default 4), white 1px stroke; `path.device-symbol` white 1.4px: icon name containing "switch" → switch glyph; containing "server"/"linux"/"host" → server glyph; anything else → router glyph. Inner group rotated by `direction` up/right/down/left = 0/90/180/270 | `data-map-id={id}` always |
| `render.node-label` | `g.device-label` with `rect.device-label-bg` (fill `labelBackgroundColor` default `#454545`, rx 3, sized by `measureTopology` to text bbox +4/+2) and white 11px text = `label`. Position by `labelPosition`: default/`bottom` → below (y=r+15, middle); contains `top` → above (y=-r-9); `left` → x=-r-8, y=5, anchor end; `right` → x=r+8, anchor start; `none` → no label | — |
| `render.node-matched` | `data-map-node={inventory_name} tabindex=0 role=button aria-haspopup=menu aria-label="Open {label} actions"`, `<title>Right-click for SSH and node actions: {inventory_name}</title>`; CSS `cursor:pointer`; `:hover`/`:focus` → `.device-body` stroke `#f15b40` 3px; `:focus{outline:none}` | when `inventory_name` |
| `render.node-unmatched` | class `unmatched`; `<title>Unmatched node — no inventory connection</title>`; extra `<text class="unmatched-label">Unmatched</text>` at y=r+30 (9px, `#795b31`); CSS `cursor:default`, body stroke `#6d777b` dashed `3 2`; no data-map-node/tabindex/role → not clickable, not focusable, no menu | when `!inventory_name` |
| `render.link-wire` | `g.topology-wire` with `data-capture-endpoints` (escaped JSON `[{node:inventory_name‖'', label, interface}]`), `tabindex=0 role=button aria-label="Capture {A}:{ifA} to {B}:{ifB}"`, `data-source`/`data-target` node ids, `<title>{A}:{ifA} — {B}:{ifB}</title>`; two paths: invisible `path.capture-hit` (stroke transparent, width 16, `pointer-events:stroke`) and visible path (stroke `#87a9ab` 2px). Straight line from centre to centre shortened by `radius = 20/max(|ux|,|uy|)` at each end; CSS `cursor:pointer` | skipped entirely (empty string) if either endpoint id is not in `nodes` |
| `render.link-self-loop` | when both nodes share the exact centre: cubic bezier loop above the node; no interface labels | — |
| `render.link-interface-labels` | `g.interface-label` per end: rect (`#fffdf4`, opacity .95, sized by `measureTopology`) + 10px `#607d8b` text = interface name, placed at `offset = min(length*.45, radius + (pair[0].label_offset ?? settings.endpointOffset ?? 20))` from each end | omitted when `settings.labelMode==='hide'`; hidden-until-hover when `on-select` (CSS class set by topology.js) |
| `render.annotation-text` | `type==='text'`: background rect (`backgroundColor` default transparent, `fillOpacity` default 1) + `<text>` with tspans per `\n` line (line height `fontSize*1.5`), `fontSize` default 14, `fontFamily` default Arial, fill `fontColor‖color‖#333`, `fontWeight`, `fontStyle`, `textDecoration`, anchor by `textAlign` (left x+4 / center / right x+w-4), first baseline `y+fs+4+paragraphMargin` | text only, never HTML |
| `render.annotation-shape` | `circle` → ellipse; `line` → x1,y1→x2,y2; anything else (`rectangle`, `group`) → rect with `rx=cornerRadius` default 8. Attrs: fill `fillColor` default transparent, `fill-opacity` default .22, stroke `borderColor` default `#78909c`, `stroke-width` `borderWidth` default 1, dasharray dashed `6 4` / dotted `2 3` / (`solid`,`double` → none) | — |
| `render.annotation-shape-label` | if `text`: label at `labelPosition` (default `top-left`; `*-center` → middle; `*-right` → end; `bottom-*` → y+h+18 else y-7), fill `color` default `#607d8b`, `fontSize` default 12, `fontWeight` | — |
| `render.annotation-wrapper` | `<g transform="rotate({rotation} cx cy)" class="topology-annotation" data-decoration-index={original index}>`; CSS `pointer-events:none` on the main map, `pointer-events:all; cursor:move` inside `.diagram-workspace` | — |
| `render.measure` | `measureTopology(svg)`: sets every `.device-label`/`.interface-label` rect to text bbox −4/−2 +8/+4; returns `[bbox.x-35, bbox.y-35, max(200,w+70), max(150,h+70)]` of `#topology-scene`. Requires the SVG to be rendered/visible (`getBBox`) | — |

---

## 5. Diagram editor (`diagram-editor.js`, dialog id `op-layout-editor`)

Opened by `#map-edit` → `opTask(null, ()=>editDiagram(activeId))`. `opDialog` creates/reuses `<dialog id="op-layout-editor" class="operations-dialog">` with header eyebrow "NODE MANAGER", an `×` close button (`data-op-close`, aria-label "Close"), h2 "Edit topology diagram", the body, and a trailing `.form-error`. CSS: `width:min(1500px,96vw)`; workspace grid `minmax(0,1fr) 280px`; SVG `56vh` min 360px, background `#fcfaf1`, `touch-action:none`, `.map-device{cursor:grab}` / `:active{cursor:grabbing}`.

| id | Label | Trigger | Behaviour | Gating |
|---|---|---|---|---|
| `diagram.open` | Edit diagram | `editDiagram(id)` | `GET /api/labs/{id}/topology`; if `null` → throws "Import a topology map first." (toast). Builds dialog, `render()`, `properties()` | — |
| `diagram.intro` | text | rendered | "Add text, boxes, circles and lines. Select an item to edit its appearance or drag it on the canvas. Save keeps changes in this manager. Download JSON to reuse annotations with your VM topology; draw.io exports an editable diagram." | — |
| `diagram.add-text` | Add text | `[data-add-shape=text]` | `checkpoint()`; push `diagramAnnotation('text', cx-100, cy-60)` (text "New text", 240×70, zIndex 1); select it | toast "The diagram supports at most 2000 annotations." when `decorations.length>=2000` |
| `diagram.add-box` | Add box | `[data-add-shape=rectangle]` | as above with type `rectangle` (200×120, zIndex −1) | same |
| `diagram.add-circle` | Add circle | `[data-add-shape=circle]` | type `circle` | same |
| `diagram.add-line` | Add line | `[data-add-shape=line]` | type `line` (x2=x+200, y2=y+120) | same |
| `diagram.undo` | Undo | `#diagram-undo` | pops last JSON snapshot into `drawing`, `changed()`, clears selection. History capped at 30 entries | `disabled` until history non-empty (set in `changed()`) — note: after undoing the last entry the button stays enabled until the next `changed()` |
| `diagram.fit` | Fit diagram | `#diagram-fit` | `bounds=null; render()` → viewBox re-measured. The editor has **no zoom or pan**; the viewBox is frozen at the bounds measured on first render until Fit | — |
| `diagram.select` | Select item (select `#diagram-selection`) | `onchange` | options: "Choose an item" (value ''), "Node: {label‖alias}" (`n:{i}`), "{type}: {text[0..50] ‖ 'Annotation {i+1}'}" (`a:{i}`) | — |
| `diagram.empty-hint` | "Select an item on the canvas or add an annotation." | `#diagram-empty` | hidden when an item is selected | — |
| `diagram.fields` | fieldset "Selected item" | `#diagram-fields` | `disabled` when nothing selected. Always shown: X, Y (number, −100000..100000, step any). `#diagram-annotation-fields` hidden for nodes | — |
| `diagram.annotation-fields` | Text / label (textarea maxlength 4000 rows 3); Width, Height (1..100000); End X, End Y (±100000); Font size (6..160); Text color (color); Fill color (color); Fill opacity (0..1 step .05); Border color (color); Border width (0..20); Border style (solid/dashed/dotted/double); Text alignment (left/center/right); Font weight (normal/bold); button "Remove annotation" | `[data-prop]` inputs | per-input visibility (label hidden): End X/Y only for `line`; Width/Height hidden for `line`; Border color/width/style hidden for `text`. Color inputs show `#416377` when the value is not `#rrggbb` | — |
| `diagram.property-edit` | (any field) | `oninput`/`onchange` | ignored if no item, `!checkValidity()`, empty/non-finite number, or unchanged. Else `checkpoint()`; `x`/`y` → `diagramMove`; `fontColor` also sets `color`; `fillColor` on text also sets `backgroundColor`; `textAlign` on non-text rewrites `labelPosition` (`left|center|right` segment); `text`/`fontSize` on text grows `height` to `lines*fontSize*1.5+8`; `render()` | — |
| `diagram.remove-annotation` | Remove annotation | `#diagram-delete` | only when selection is `a:`; `checkpoint()`; splice; deselect | button visible only inside annotation fields |
| `diagram.canvas-select-drag` | (canvas) | `pointerdown` button 0 on `[data-map-id]` or `[data-decoration-index]` | selects (`n:{diagramNode}` / `a:{index}`), `setPointerCapture`, stores snapshot; `pointermove` beyond 1px → `diagramMove(item, dx, dy)` from original, `render()` each move; `pointerup`/`pointercancel`/`lostpointercapture` → if moved push snapshot to history (cap 30) and `changed()`; refresh properties | nodes and annotations only; background does nothing |
| `diagram.selected-highlight` | — | render | selected element gets class `diagram-selected` (CSS `filter:drop-shadow(0 0 3px #f15b40)`); nodes get `data-diagram-node={i}`, `aria-haspopup` removed, title "Select or drag to reposition" | — |
| `diagram.state` | "No unsaved changes." / "Unsaved changes" | `#diagram-state role=status` | set by `changed()` | — |
| `diagram.close-guard` | Cancel / × / Escape | `#diagram-cancel`, `[data-op-close]`, `dialog.oncancel` (preventDefault) | if `dirty` → show `#diagram-discard` panel "Discard unsaved diagram changes?" with "Keep editing" (`#diagram-keep`, focused; hides panel) and "Discard changes" (`#diagram-discard-confirm`, closes); else close immediately | — |
| `diagram.download-json` | Download annotations JSON | `#op-layout-json` | `opTask(dialog, …)`: `payload()` (runs `#diagram-properties.reportValidity()`; throws "Correct the highlighted diagram field.") → `POST /api/labs/{id}/annotations` JSON `{positions, decorations, revision}` → blob download, name from Content-Disposition (server `{lab}.clab.yaml.annotations.json`, fallback `topology.annotations.json`) | all dialog buttons disabled during the request; error in dialog `.form-error` |
| `diagram.export-drawio` | Export draw.io | `#op-layout-export` | same as above to `POST /api/labs/{id}/drawio` → `{lab}.drawio` (fallback `topology.drawio`); uncompressed editable draw.io XML (`drawio_export.py`) | same |
| `diagram.save` | Save diagram | `#op-layout-save` | `PUT /api/labs/{id}/layout` `{positions:{nodeId:[x,y]}, decorations, revision}`; `dirty=false`; close; if `id===activeId` → `refreshMap(true)`; toast "Diagram saved." | Backend: 404 "Import a topology map first.", 409 "The map changed. Reopen the editor before saving or exporting.", 400 "Unknown map nodes." / "Invalid node coordinates." / "Use at most 2000 annotations and 1 MiB of annotation data." / "Choose text, box, circle, line or group annotations." / "Annotation text must contain at most 4000 printable characters." / "Annotation size or style is outside the supported range." / "Unsupported annotation style." / "Use a supported annotation color.", 500 "Could not save the layout. Try again." Saving sets `drawing.placed=true` server-side (discovery will no longer overwrite positions) |

Not used by these files but present on the backend: `GET /api/labs/{lab_id}/drawio?layout=interactive`.

---

## 6. Data defaults (`diagramAnnotation`)

`{type, text: 'New text' for text else '', x, y, width 240/200, height 70/120, x2:x+200, y2:y+120, fillColor '#79e8f6', fillOpacity .22, borderColor '#416377', borderWidth 2, borderStyle 'solid', cornerRadius 8, color '#416377', labelPosition 'top-left', fontSize 18, fontColor '#193340', fontFamily 'Arial', fontWeight 'normal', fontStyle 'normal', textDecoration 'none', textAlign 'left', backgroundColor 'transparent', paragraphMargin 0, rotation 0, zIndex 1 (text) / −1 (shapes)}`.

## 7. Dialogs

| id | Title | Opened by | Fields / buttons |
|---|---|---|---|
| `map-dialog` | Import lab topology | `#import-map` | file `annotations` (.json, required) "VS Code annotations JSON"; file `topology` (.yaml/.yml/.json) "Lab topology YAML or topology-data.json"; help text; `.form-error`; Cancel (`#cancel-map`); Import map (submit) |
| `export-dialog` | Export SuperPuTTY sessions | `#export-sessions` | checkbox `#export-passwords` "Include saved passwords as plain text"; two help paragraphs; `.form-error`; Cancel (`#cancel-export`); Download XML (submit) |
| `node-context-menu` (div `role=menu`, not a `<dialog>`) | (node name + address:port) | right-click / ContextMenu / Shift+F10 on a matched node | Capture packets; SSH (New tab ↗); Back up configuration; Node details |
| `op-layout-editor` | Edit topology diagram | `#map-edit` → `editDiagram` | toolbar (Add text/box/circle/line, Undo, Fit diagram); SVG `#op-layout-map` (aria-label "Editable lab topology"); properties form (see §5); status line; discard panel; actions Cancel / Download annotations JSON / Export draw.io / Save diagram |
| `op-map-preview` (operations.js, consumer of the renderer) | Topology preview · {name} | `#op-validate` in the VM topology editor | read-only SVG `#op-preview-map` + explanatory sentence |
| `details-dialog` (app.js) | Node workspace | node click / "Node details" | — (documented elsewhere) |
| `capture-dialog` (capture.js) | Capture packets | link click / "Capture packets" | — (documented elsewhere) |

## 8. Persistence

- No `sessionStorage`/`localStorage` writes in these three files. (`activeId` comes from `sessionStorage['activeLab']` managed by app.js.)
- Backend state written: `lab['drawing']` replaced by import (`POST /topology`, event `topology.import`); positions/decorations + `placed=true` by `PUT /layout` (event `topology.layout`); `sessions.export` event on SuperPuTTY export.
- Object URLs for downloads are revoked after 1000 ms (`setTimeout`).

## 9. Timers and polling

- `topology.js` owns no interval. `refreshMap()` is invoked indirectly every **4 s** by `app.js:180 setInterval(()=>refresh(),4000)` → `render()` → `showTab(tab)` → `refreshMap()` when the Topology tab is active. The `mapKey` dedupe prevents DOM churn; a changed drawing (import, save, node matching change, revision) rebuilds the SVG and **resets zoom/pan** and closes the context menu.
- `mapRequest`/`request` counters drop out-of-order responses.
- `setTimeout(…,1000)` to revoke blob URLs after downloads (topology.js:51, diagram-editor.js:79).
- `captureEnabled` is fetched once at page load (`capture.js`) and only affects the "Capture packets" menu item's disabled state.

## 10. Status vocabulary

| Term | Where | Meaning |
|---|---|---|
| "No map imported. Upload your annotations and lab topology to get started. The Nodes list remains available." | `#map-status` | drawing is null |
| "{n} map nodes · {n} links · {n} unmatched." | `#map-status` | counts from the drawing |
| "unmatched" / "Unmatched" / "Unmatched node — no inventory connection" / "Unmatched nodes have no connection actions." | status, node label, node title | drawing node not matched 1:1 to an inventory node; no click/menu |
| "{n} unsupported or one-ended links omitted." | `#map-status` | `skipped_links` from parser |
| "Import the lab topology with annotations to show wiring." | `#map-status` | `has_links_source` false |
| "Reimport the original annotations and lab YAML to restore complete styling and NOS interface labels." | `#map-status` | `schema !== 3` |
| "Could not load map: …" | `#map-status` | fetch error |
| "Expand map" / "Close expanded map" | `#map-expand` | expanded state |
| "Drag to pan · Links show imported wiring, not live status" | `.map-tools` | static hint |
| "New tab ↗" | context menu SSH | opens terminal page in new tab |
| "Ready" / "Choose NOS" / "Needs credentials" / "Lab unavailable" | `node.readiness` (gates Back up items) | backup readiness |
| "booting" / "failed" / "unavailable" / "ready" / "unmonitored" | `node.nos_login.status` (gates SSH via `ssh_ready`) | NOS login monitor |
| "Assign credentials first", "NOS is still booting; SSH opens when it accepts a login", "SSH login failed with the saved credentials; assign a credential profile", "Node is not running" | SSH menu item `title` | why SSH is disabled |
| "Packet capture is not enabled. Open Capture packets for setup." | Capture menu item `title` | capture provider disabled |
| "show-all" / "on-select" / "hide" | `settings.labelMode` | interface label visibility |
| "No unsaved changes." / "Unsaved changes" | `#diagram-state` | editor dirty flag |
| "Discard unsaved diagram changes?" | `#diagram-discard` | close guard |
| "Select or drag to reposition" | node title in editor | — |
| "Topology imported." / "Diagram saved." | toast | success |

## 11. Microcopy a CCNA-level student would not understand

| Text | Where | Problem |
|---|---|---|
| "VS Code annotations JSON" | import dialog label | refers to the containerlab VS Code extension's `.annotations.json`; unexplained tool/file |
| "Lab topology YAML or topology-data.json" | import dialog label | containerlab file internals |
| "Annotations supply positions, groups, and notes. Include the topology file to draw links. Imports replace the current map. Connections and credentials remain in your inventory." | import dialog help | "annotations", "inventory" (Ansible) jargon |
| "No map imported. Upload your annotations and lab topology to get started. The Nodes list remains available." | `#map-status` | "annotations" jargon |
| "{n} unmatched." / "Unmatched" / "Unmatched node — no inventory connection" / "Unmatched nodes have no connection actions." | status + node | implementation concept (drawing↔inventory matching) |
| "{n} unsupported or one-ended links omitted." | `#map-status` | parser detail |
| "Import the lab topology with annotations to show wiring." | `#map-status` | jargon |
| "Reimport the original annotations and lab YAML to restore complete styling and NOS interface labels." | `#map-status` | schema versioning leak; "NOS", "YAML" |
| "Right-click for SSH and node actions: clab-{lab}-{node}" | node title | exposes the raw container/inventory name |
| "NOS is still booting; SSH opens when it accepts a login" / "SSH login failed with the saved credentials; assign a credential profile" / "Assign credentials first" | SSH item title | "NOS", "credential profile" |
| "Packet capture is not enabled. Open Capture packets for setup." | Capture item title | provider/setup concept |
| "Drag to pan · Links show imported wiring, not live status" | map tools | "imported wiring" |
| "Export sessions" / "Export SuperPuTTY sessions" / "PuTTY's -pw argument" / "Private keys are not exported" / "known NOS kinds supply the default username" / "session for every inventory node using its short name" | export dialog | third-party tool, CLI flag, "NOS kinds", "inventory node" |
| "Download annotations JSON" / "Download JSON to reuse annotations with your VM topology; draw.io exports an editable diagram." / "Export draw.io" | editor | file formats and external tools |
| "Save keeps changes in this manager." | editor intro | "this manager" is the app itself |
| "NODE MANAGER" | editor eyebrow | internal branding, not a task |
| "text: …", "rectangle: …", "circle: …", "line: …", "group: …" | `#diagram-selection` options | raw lowercase type keys; "group" is not a creatable type ("Add box" creates "rectangle") |
| "End X" / "End Y" | editor fields | unclear they are a line's second endpoint |
| "Fill opacity" (0–1) | editor field | numeric fraction, no % |
| "The diagram supports at most 2000 annotations." | toast | "annotations" |
| "Correct the highlighted diagram field." | editor error | vague |
| "Import a topology map first." | toast when Edit diagram with no map | "topology map" vs "Import topology" naming |
| "The map changed. Reopen the editor before saving or exporting." / "Wait for the lab operation to finish." / "Unknown map nodes." / "Invalid node coordinates." | backend errors surfaced in dialogs | internal revision/lock concepts |
| "Could not read this link. Use Capture packets to browse live interfaces." | link click failure toast | "live interfaces" |
| "Back up all configs" / "SSH all nodes ↗" | heading buttons | "configs" abbreviation; fine for most but inconsistent with "Back up configuration" |
| "This includes ready nodes that are unchecked in the inventory." | backup-all review | "inventory" |

## 12. Element ids and hooks used

Ids (index.html): `topology-map`, `topology-view`, `map-fit`, `map-in`, `map-out`, `map-expand`, `map-status`, `map-edit`*, `map-ssh-all`*, `map-backup-all`*, `import-map`, `map-dialog`, `map-form`, `cancel-map`, `export-sessions`, `export-dialog`, `export-form`, `export-passwords`, `cancel-export`, `node-context-menu`, `details-dialog`, `toast` (via notify). (*wired in other files.)
Ids created at runtime: `op-layout-editor`, `op-layout-map`, `diagram-undo`, `diagram-fit`, `diagram-properties`, `diagram-selection`, `diagram-empty`, `diagram-fields`, `diagram-annotation-fields`, `diagram-delete`, `diagram-state`, `diagram-discard`, `diagram-keep`, `diagram-discard-confirm`, `diagram-cancel`, `op-layout-json`, `op-layout-export`, `op-layout-save`; SVG ids `topology-grid` (pattern) and `topology-scene` (group) inside every rendered map; `op-preview-map` (operations.js).
Data attributes: `data-map-node`, `data-map-id`, `data-capture-endpoints`, `data-source`, `data-target`, `data-decoration-index`, `data-diagram-node`, `data-capture`, `data-terminal`, `data-backup`, `data-details`, `data-add-shape`, `data-prop`, `data-op-close`.
Classes: `map-device`, `unmatched`, `device-body`, `device-symbol`, `device-label`, `device-label-bg`, `unmatched-label`, `topology-wire`, `capture-hit`, `interface-label`, `topology-annotation`, `diagram-selected`, `labels-on-select`, `map-expanded`, `context-node-name`, `map-tools`, `topology-map`, `op-layout-map`, `diagram-toolbar`, `diagram-workspace`, `diagram-properties`, `diagram-fields`, `form-error`, `button primary/secondary/danger-outline`, `dialog-actions`.

## 13. Redesign risks

1. `capture.js` binds link handlers to the `map` const and calls `closeNodeMenu` from `topology.js`; the global names and script order must survive.
2. Pan-vs-click separation depends on `e.target.closest('[data-map-node],[data-capture-endpoints]')`; renaming those attributes breaks panning or clicking.
3. `handleNodeAction` is shared with the Nodes table and details drawer and dispatches purely on `data-capture`/`data-terminal`/`data-backup`/`data-details`/`data-edit`/`data-check`; the menu must keep those attributes.
4. Menu items' disabled state is computed once at open from `current()`; the menu is closed on any scroll (capture phase), resize or blur, so a scrolling layout will dismiss it constantly.
5. The document-level Escape handler both closes the menu and collapses the expanded map; the `map-expanded` class is applied to the whole `#topology-view` section (heading, tools, status and SVG) with `position:fixed`.
6. `measureTopology` uses `getBBox()`, which needs the SVG rendered and not `display:none`; render-then-hide or lazy tabs will produce wrong fit bounds.
7. Every re-render (import, save, matching change during the 4-s poll) resets `mapBox` to the fit bounds — user zoom/pan is not preserved.
8. Duplicate SVG ids `topology-grid`/`topology-scene` appear when the editor, preview and main map coexist; `url(#topology-grid)` resolves to the first in document order.
9. The editor has no zoom/pan; its viewBox is frozen at first measure until "Fit diagram"; new shapes are dropped at the centre of that box.
10. The editor relies on `opDialog` (header, `data-op-close`, trailing `.form-error`) and `opTask` (disables every enabled button in the dialog during a request, writes the error to `.form-error`). `dialog.oncancel` is intercepted for the dirty guard.
11. `withForm` requires a `button[type=submit]` and a `.form-error` element inside `#map-form` / `#export-form`.
12. Keyboard contract: nodes and wires are `tabindex=0 role=button`; Enter/Space activate; ContextMenu/Shift+F10 open the menu; Arrow/Home/End cycle menu items; unmatched nodes are intentionally not focusable.
13. `labels-on-select` visibility is CSS `:hover` on `.topology-wire`; a redesign that changes the wire structure loses it.
14. `data-capture-endpoints` is a JSON string escaped into an attribute and parsed by capture.js; the `node` field is `''` for unmatched endpoints and the capture dialog switches scope to `host` for those.
15. `#map-edit` is wired inside `if($('import-top'))` in operations.js — removing `#import-top` from the page silently unwires Edit diagram.
16. `topologyMarkup`/`measureTopology` are also consumed by `opMapPreview` on `workspace.html`; renaming or moving them breaks the VM topology preview.
17. Wheel zoom uses `{passive:false}` + `preventDefault` and the SVG has `touch-action:none`; without these, page scroll and touch panning fight the map.
18. `refreshMap` is only called from `showTab('topology')`; the status paragraph and the map are only updated together and only when the drawing JSON changes.
