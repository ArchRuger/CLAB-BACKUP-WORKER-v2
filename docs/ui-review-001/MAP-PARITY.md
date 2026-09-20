# UI-003 — map-editing capability matrix and approach

Made on 2026-09-20 from the code, not from screenshots: the installed editor is
`@containerlab/clab-ui` **0.3.2** (pinned in `clab-backup-ui/lab-builder/package.json`; read from
`node_modules/@containerlab/clab-ui/dist`, adapter `lab-builder/src/main.tsx`, hidden controls in
`app/static/lab-builder.css`); *Edit map* is `app/static/diagram-editor.js` over the manager's drawing
(`app/topology.py` `parse_drawing`, schema 3; saved by `PUT /api/labs/{id}/layout`; exported by
`app/layout.py` `annotations()` and `app/drawio_export.py`). Nothing here was tried in a browser yet;
each row is checked there when it is implemented.

Status: ☐ open · ◐ partly · ☑ done (with the release).

## 1. Capabilities

| # | Map-editing capability | Visual builder 0.3.2 | Edit map today | Status |
|---|---|---|---|---|
| 1 | Move devices by dragging | yes, snaps to a 20 px grid | yes, free; also X/Y fields | ☐ |
| 2 | Generated layouts (preset, force, auto, radial) | yes (`navbar-layout`) | no | ☐ |
| 3 | Free text: add, edit in place, font family/size/colour, bold, italic, underline, alignment, background, rotation, rounded background | yes (pane menu, palette, inline toolbar, panel) | add/move/delete; text, size, colour, fill, opacity, alignment, weight only | ☐ |
| 4 | Shapes: rectangle, circle, line; fill colour/opacity, border colour/width/style, corner radius, rotation, **line arrows and arrow size** | yes, with resize and rotate handles | rectangle, circle, line; size by number fields; no handles, rotation, corner radius or arrows | ☐ |
| 5 | Groups: create (menu, Ctrl+G, palette), name, level, colours, border, label position, **membership by dragging devices in, nesting** | yes | an imported group is shown and editable as a box; membership (`groupId`, `parentId`) is **dropped on import** | ☐ |
| 6 | Resize and rotate with handles | yes | no | ☐ |
| 7 | Copy, paste, duplicate, delete by keyboard | yes (annotations only in view mode) | delete by button only | ☐ |
| 8 | Undo / redo | yes in edit mode; **absent in view mode** | undo (30 steps), no redo | ☐ |
| 9 | Device look: icon, icon colour, corner radius, label position, label direction, label background | yes, but through `editNode` (a topology command, edit mode only) | imported and drawn, not editable | ☐ |
| 10 | Per-link endpoint label offset | yes (Link editor → `edgeAnnotations`) | imported and drawn, not editable | ☐ |
| 11 | Link label mode (show all / on select / hide) | yes (`navbar-link-labels`) | imported, not editable | ☐ |
| 12 | Grid style, line width, colours | yes (Lab settings › Appearance) | colours imported, not editable | ☐ |
| 13 | z-order | field `zIndex` kept; no control in either | field kept | n/a |
| 14 | Zoom, pan, fit | yes | fit only | ☐ |
| 15 | Export: SVG | yes | no | ☐ |
| 16 | Export: draw.io; download `.annotations.json`; import `.annotations.json` | no | **yes, must stay** | ☐ keep |
| 17 | Save with a conflict check; cancel / discard question | draft revision check (`draftWrite`) | yes (`revision`, discard dialog) | ☐ keep |
| — | Not map editing, stays out: add/remove devices and links, kinds, images, lab settings, deploy, Geo layout (hidden), traffic-rate widgets (need runtime statistics), raw YAML/JSON tabs (off: CSP) | | | |

## 2. What the documents hold

The builder writes `<topology>.annotations.json`: `nodeAnnotations`, `networkNodeAnnotations`,
`freeTextAnnotations`, `freeShapeAnnotations`, `groupStyleAnnotations`, `edgeAnnotations`,
`aliasEndpointAnnotations`, `trafficRateAnnotations`, `viewerSettings`; every entry allows extra keys.
The manager keeps **only its own normalised drawing**, not that document: on import it drops what it does
not draw (`groupId`/`parentId`/`level`, `geoCoordinates`, line arrows, `roundedBackground`, alias and
traffic-rate entries, most viewer settings, unknown keys). Any approach that edits the manager's drawing
therefore cannot reach parity and would lose data on a round trip.

## 3. Approach chosen: the builder itself, in map mode

Reuse the embedded editor instead of growing `diagram-editor.js` into a second one.

1. **The manager keeps the full annotations document per lab** (`lab['annotations']`, text, ≤ 1 MiB,
   private like `definition_yaml`), next to the drawing it derives from it with `parse_drawing`. A lab
   that has only a drawing starts from `layout.annotations(drawing)`. New routes read and save that
   document with a revision check; saving re-derives the drawing, so the normal Topology view, the
   draw.io export and the annotations download follow. Unknown keys are stored untouched.
2. **Map mode in the adapter** (`main.tsx`): the editor runs with `mode: "view"` (upstream's state for
   a deployed lab: no add/edit/delete of devices and links, palette Nodes tab inert, lab settings
   Basic/Mgmt off, paste and delete limited to annotations) and unlocked, over the lab's topology text
   and its annotations. Because upstream enforces view mode in the UI only, the adapter **refuses every
   command that is not annotation-only** (`savePositions`, `savePositionsAndAnnotations`,
   `setAnnotations`, `setAnnotationsWithMemberships`, `setEdgeAnnotations`, `setViewerSettings`,
   `setNodeGroupMembership(s)`) and the page refuses to save when the topology text differs from what
   it loaded. Nothing in this path can deploy, publish, revise or touch the VM.
3. **Edit map opens that page** for a lab with a topology text; the old dialog stays for labs without
   one (inventory-only labs) and until the new path is validated. Import map, the annotations download
   and the draw.io export stay where they are.

Known gaps of this approach, to be listed as incomplete unless solved: undo/redo is absent in the
editor's view mode (row 8); the device look goes through a topology command (row 9) and needs either an
adapter translation into `nodeAnnotations` or stays as today; the manager's Topology view draws less
than the editor can store (rotation, arrows, nested groups): what it cannot draw must still be kept.

## 4. Increments

| Step | Content | Release |
|---|---|---|
| A | This matrix and the decision | 1.30.12 |
| B | Manager: store, serve and save the full annotations document; derive the drawing; keep unknown data; tests | 1.30.13 |
| C | Adapter map mode (view mode, command whitelist, topology-unchanged check), page wiring, bundle rebuild, tests | |
| D | Edit map opens the builder in map mode; unsaved-change and cancel behaviour; exports and import kept; browser validation of every row; the Topology view draws what was saved | |
| E | Gaps: undo/redo, device look, anything the browser pass finds | |
