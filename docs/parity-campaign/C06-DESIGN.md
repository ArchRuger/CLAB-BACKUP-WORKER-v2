# C06 design: Topology tab parity

Rows R043 (link up/down colours), R069 (find a device, link hover), R066 (stored annotation styles), R070 (boxed node
and elbow link styles, the renderer's half), R067 (Download picture: SVG and PNG), R068 (draw.io layout and theme),
R064 (one-click arrange outside Edit map). Written against `claude/parity-campaign` at `08e7336` (release 1.31.2,
containerlab 0.79.0 and Docker 27.5.1 on the VM). Nothing here deploys, writes to the VM or touches a device; the one
helper change is a read-only option of C03's `interfaces` mode (§2.1). R044 and R045 (rate tiles, a link chart) are
not in this chunk: the README's row list for C06 leaves them out and they need a counter history the browser does not
keep yet.

Where the binding UI contract is touched: `docs/redesign/DESIGN-SPEC-ADDENDUM.md` C.41 ("Download the map file or
export it to draw.io from the editor. (no new export code path)") is amended by this chunk (§5): the Topology tab gains
its own Download picture and a draw.io export dialog; the editor's buttons stay.

## 0. Facts verified live for this design (2026-10-23, this VM)

Read-only on the manager (release 1.31.2 at http://127.0.0.1:8081) and the `parity` lab (five nodes, lab id
`d7e3a468…`), plus one disposable two-cEOS lab `c06probe` deployed from the scratchpad (`free -g`: 27 GB available
before it), stopped and started with Docker, admin-shut over SSH, and destroyed with `containerlab destroy --cleanup`
(no `c06probe` container remains; the parity lab was not touched).

1. **C03's per-node answer.** `GET /api/operations/interfaces?lab_id&node` answers in 0.22–0.41 s per node (one SSH
   session and one `docker inspect` plus one lab-wide `containerlab inspect interfaces` per call). The rows carry the
   shape C03 promised: `{name, alias, state, mac, type, mtu, ifindex, port, role}`; vrnetlab kinds fill `alias`
   (`ge-0/0/0`, `Gi0/0/0/0`, cJunosEvolved `et-0/0/0` on `eth4`), cEOS leaves `alias` empty and the manager's `port`
   is `Ethernet1` only through `displayed_interface`; `lo`, `tap1`, `tap2`, XRv9k's `ctrl-dummy`/`dev-dummy`
   (`state: down`, type `tuntap`) are `internal`.
2. **A C03 defect, outside this chunk's files, that this chunk must not depend on.** For `ceos` and `cjunos` the route
   answers 409 `Docker on the VM did not answer about this container.` Reproduced with the helper's exact command:
   `docker inspect --type container --format '…{{with .State.Health}}{{.Status}}{{end}}…'` fails on Docker 27.5.1 with
   `template parsing error: … map has no entry for key "Health"` for a container that defines no healthcheck (cEOS,
   cJunosEvolved); `{{with index .State "Health"}}{{.Status}}{{end}}` answers `exited ` for such a container and
   `running healthy` for `vrt`. C03's live pass used `vrt`, which has a healthcheck. The fix is one constant in
   `host_operations.py` (`INSPECT_FORMAT`), the file C05 S1 owns right now: the lead decides where it lands (§6, S0).
   C06 is designed so that link colours never need `docker inspect` (decision 1).
3. **The lab-wide listing is cheap and complete.** `containerlab inspect interfaces --name parity -f json` takes 59 ms
   and lists all five containers with every interface; it lists **running containers only**.
4. **What a down link looks like to containerlab** (`c06probe`, two cEOS, links `a:eth1–b:eth1`, `a:eth2–b:eth2`):
   both up → `eth1 up`, `eth2 up` on both; `docker stop b` → `b` disappears from the listing and `a` keeps **only
   `eth0`** (the veth pairs are gone with the far container); `docker start b` → both list `eth0` only (the links do
   not come back, as `docs/LAB-OPERATIONS.md` says of a Docker-stopped node); EOS `interface Ethernet1 / shutdown` →
   `eth1` reads **`dormant` on both ends** (the near end and the neighbour); `no shutdown` → `up` again within 3 s.
   So "down" has three shapes: state not `up` (`down`, `dormant`, `lowerlayerdown`, `unknown`), the interface missing
   from a listed device, and the device missing from the listing.
5. **The parity drawing** (`GET /api/labs/{id}/topology`): `placed: False`, nodes on the default grid (0,0 … 640,0),
   five links whose endpoints carry the NOS names (`ge-0/0/0`, `et-0/0/0`, `Gi0/0/0/0`, cEOS `eth1`) and the
   `capture_interface` (`eth1`, `eth4`, …); no decorations; settings cream background `#fdf6e3`.
6. **draw.io today.** The manager's `GET /api/labs/{id}/drawio` returns 12 KB of editable XML from the saved positions
   (`layout=interactive` only; `horizontal` and `vertical` are 400, pinned by
   `test_removed_drawio_layouts_rejected`). `containerlab graph --drawio` runs the `clab-io-draw` **container**
   (`--drawio-version`, `--drawio-args`), a Docker-run tool the manager can never call; its themes `nokia_modern`,
   `nokia`, `grafana` and layouts `horizontal`/`vertical` are therefore reproduced by the manager's own exporter or not at all.
7. **The pinned editor bundle (0.3.2)** knows `lineStartArrow`, `lineEndArrow`, `lineArrowSize`, `roundedBackground`
   (default **true** in its text renderer), group `level` and `parentId`; it knows no `nodeStyle`, `linkStyle` or
   `boxSpacing` (0.4.0). Its icon set is `switch, host, pe, bridge, super-spine, container, cloud, server, client,
   leaf, dcgw, ue, spine, rgw, pon, controller` (16); `map-editor-page.js` `MAP_ICONS` lists 14 and lacks `host` and
   `container`; `topologyGlyph` draws `host` as a server and `container` as a router. Upstream 0.4.0's `nodeBox.ts`
   (read on GitHub, not runnable here) sizes a boxed node as a **square** of `max(80, …)` px (narrow 64), centred on
   the icon's anchor, name at 12 px inside under the icon, middle-truncated, links attached to the box outline; its
   per-node appearance object normalises to `color, opacity, blur, borderColor, borderWidth, cornerRadius, textColor,
   shadow`, but the key under which a `nodeAnnotations` entry stores that object is not in the 0.3.2 bundle or the
   published examples (assumption A3).
8. **Memory for a probe lab**: two cEOS containers cost under 2 GB; `free -g` before and after showed 27 and 26 GB available.

## 1. Decisions in one place

1. **Link state comes from one lab-wide helper call, not from N per-node calls.** C03's `interfaces` mode gains the
   option `{'all': true}` (no `node`, no `container`): the lab is bound once per call by one fixed `containerlab
   inspect --name <lab> -f json` whose every row's `labPath` must pass `self.trusted()` (else `container_of`'s
   trusted-roots sentence, nothing listed), then the same fixed argv `containerlab inspect interfaces --name <lab>
   -f json`, every listed container reduced to `{name, interfaces: [{name, alias, state, type}]}` (a reducer of its
   own: no `mac`, `mtu`, `ifindex`), no `docker inspect`, no counters, no facts (§2.1). The widening of the mode's
   option whitelist is reviewed by `risk-reviewer` on the S0 diff under the campaign's standing instruction (every
   helper addition is a security-sensitive change). Why one call: one SSH session per poll instead of five
   (`remote()` opens a connection per request, `lab_operations.py:141`); about 120 ms on the VM (two 60 ms
   listings) instead of five times 0.3 s; it inspects no container; and it leaves C03's three diagnostics slots to
   the drawer. The manager route is
   `GET /api/operations/link-state?lab_id=` (§2.2), a GET so no `api.request` event per poll, answering 200 with
   `available: false` and a reason when the helper is old or the lab unlinked (never a 409: a poll must not treat
   "colours are off here" as an error). A fallback to per-node calls is deliberately not built: two code paths for one
   picture, and the per-node path is the one with the defect.
2. **A wire's state is a class swap, never a rebuild**, as `renderMapState` does for devices: `link-up`, `link-down`,
   or neither (unknown). The rule, per wire: `down` when either end's listed interface state is not `up` (so
   `dormant`, `down`, `lowerlayerdown`, `unknown`), or when the end's device is listed but the interface is missing, or
   when the end's device is not listed at all (not running); `up` when both ends are listed and `up`; otherwise
   unknown (the lab-wide answer is unavailable, or the end's device is not a lab device). An unmatched drawing node
   (`inventory_name` null) makes its wires unknown, never down.
3. **Colour, pattern and words, never colour alone.** A down link is `var(--danger)` (`#b3261e`, 6.54:1 on the surface,
   5.9:1 on the cream canvas) **and dotted** (`stroke-dasharray: 2 4`, width 3); C05's impaired link is `var(--warn)`
   dashed `7 4`; a link that is both is drawn down (down wins, the hover text names both). An up link keeps `--wire`:
   five green wires would shout on every healthy lab for no information, and "up" and "unknown" are told apart by the
   summary line, not by the stroke. Every stroke rule is `.topology-wire.link-down path:not(.capture-hit)` (the
   invariant); `path.capture-hit` keeps its 16 px transparent hit area, so clicking a down link still opens Capture.
   The words: a `role="status"` summary under the tools (`#map-links`), the wire's `<title>`, its `aria-label` and the
   hover line (§3.4) all say `down`, with the reason per end (§3.2). A legend line appears only while colours are on.
4. **One poll plan, C03's, with a floor.** `map-tools.js` reuses `diagPollNext(plan, answer, now)` from
   `device-diagnostics.js` (which loads before it) with the same back-off, stop and pause rules; `diagPollNext` gains
   an optional `plan.floor` (default `DIAG_INTERVAL`, so the drawer is unchanged) used where it halves the interval on
   success, and the map seeds `{interval: 10000, floor: 10000}`, so two successes in a row still give 10 s (tested).
   The plan runs only while all of these hold: the Topology tab is shown and the map stage is `map`, the page is
   visible (`pageVisible()`), the device drawer is closed (`$('details-dialog').open` false: the drawer's own polls
   own the slots then), the lab is linked (a public lab with a `deployment_name`; checked first, and an unlinked lab
   gets its sentence without a request), and `lab.deployment.status` is `Running` or `Partially running` (the
   discovery status, **not** `labStateOf().key`: a booting lab, a lab with a running operation and a lab in
   *attention* are exactly where a student wants link state). `mapLinkSchedule()` is idempotent and cheap (it returns
   at once when a timer is armed or a request is in flight, and fetches nothing itself); it is called, guarded, at
   the top of `refreshMap` before the unchanged-drawing early return, so every tab visit (`showTab` calls
   `refreshMap`) and every 4 s render re-checks the run conditions without ever fetching on the render itself. One
   request in flight at a time; a 503 keeps the last colours under "Link state paused, retrying…"; three errors stop
   with Retry and 30 minutes pause with Resume, and in both the chip and every state clause carry the time of the
   last answer ("as of 14:02"); when the lab stops being Running/Partially running or the answer is `available:
   false`, the `link-*` classes and `data-state-text` are cleared (through `mapWireText`) so no wire shows a state
   that is not current; a hidden tab stops and one fresh fetch replaces the colours on return. Opening the drawer
   stops the plan; closing it starts one fresh fetch and the plan again.
5. **Find a device is a filter, not a search engine.** A visible labelled `<input type="search" id="map-find">` in the
   map tools; case-insensitive substring over the **same haystack the Devices search uses** for a matched device
   (`renderDeviceList`: `name`, `address`, `platformLabel(platform)`, plus the drawn label), and the label alone for a
   drawing node that is not a lab device (C03 decision 9: no `* ? +` grammar); non-matching devices and the wires
   touching them get `dimmed` (opacity .25, pointer events kept); the count is announced in `#map-links`'s sibling
   `#map-find-count` (`role="status"`: "2 of 5 devices match", "No device matches"); Enter fits the view to the
   matches; Escape on the input's own `keydown` (not a document listener) clears a non-empty field and stops the
   event there, so the expanded map stays open; a second Escape on an empty field falls through to `topology.js`'s
   handler as today; the filter is per page and per lab (cleared on `selectLab`), never stored, and does not touch
   `#search`. The hint under the field says "Name, address or platform".
6. **Link hover lights the link and its two devices and tells the student what it is.** Delegated `pointerover` /
   `pointerout` and `focusin` / `focusout` on `#topology-map` (element listeners, allowed outside `shell.js`) toggle
   `hover` on the wire and `hover-end` on its two device groups (found by `data-link-ends`, §3.5) and show the hover
   line `#map-link-hover` (bottom-right chip inside the stage) with the composed wire text. **The composition hook**:
   one function `mapWireText(group)` in `topology.js` builds `<title>` from the wire's fixed `data-base`
   (`a:ifA — b:ifB`) plus the clauses, and `aria-label` from the renderer's `data-aria-base` (today's `Capture a:ifA
   to b:ifB`) plus the same clauses, the clauses being two optional data attributes, `data-state-text` (written by
   this chunk) and `data-impaired-text` (written by C05's `renderMapImpairments`). Either feature writes its
   attribute and calls `mapWireText`; neither rewrites the other's words, and the accessible name keeps its "to".
   The name-plus-description repeat (an SVG `<title>` beside an `aria-label` is read as the description) is
   accepted and stated: a screen reader hears the base twice and the clauses twice, consistently. **One attribute
   contract**: `data-link-ends` is device-only (`<nodeA>|<nodeB>`, §3.5) for Find and hover; C05's impairment
   matcher reads interfaces from the existing `data-capture-endpoints` JSON. C05 §4.3 is amended by one sentence
   (§9, row 16); its CSS, counts and Clear button are unchanged.
7. **Stored styles the renderer honours** (R066, R070 render-only), each parsed by `topology.py` so the drawing
   carries it, exported back by `layout.annotations()`, and accepted by `layout.decorations()` so the older dialog
   keeps it: line `lineStartArrow`, `lineEndArrow`, `lineArrowSize`; text `roundedBackground`; group `level` (z-order
   and nested padding); viewer `nodeStyle` (`icon` | `boxed`), `boxSpacing` (`default` | `narrow`), `linkStyle`
   (`straight` | `elbow`); and the two icon glyphs the editor offers that the renderer and `MAP_ICONS` lack (`host`,
   `container`). Per-node boxed appearance is **not** honoured until its key is verifiable (assumption A3): a boxed
   node is drawn with the theme. `layout.keep_document` stays true because this chunk adds no place that sets
   `lab['drawing']`: the arrange route (decision 10) changes positions in the drawing **and** in the stored document
   and then calls `keep_document(lab, text)`, exactly as the map-document save does.
8. **Download picture is built in the browser and only there.** The rendered `#topology-map` is cloned, the
   stylesheet's effect is inlined as attributes from `getComputedStyle` for a fixed property list, interactive and
   live-only markup is removed (`path.capture-hit`, `tabindex`, `role`, `aria-*`, `data-*`, the state badge unless
   asked for), the `viewBox` is the whole map or the current view, and the text is saved as `<lab>-map.svg`; PNG draws
   that SVG through a `data:image/svg+xml` URL (CSP `img-src 'self' data:`; a `blob:` URL is refused by the policy)
   onto a canvas at 2× and saves `<lab>-map.png` through `canvas.toBlob`. Nothing is posted to the manager.
9. **The draw.io export gets a layout and a theme, both the manager's own.** `GET /api/labs/{id}/drawio?layout=map|
   rows|columns&theme=manager|print`; `interactive` stays as an alias of `map` for the two editor pages, anything else
   is 400. `rows` and `columns` use `layout.arrange()` (decision 10) for the export only; the stored map is untouched,
   and in those two layouts groups, shapes and notes are left out because they were placed for the saved positions
   (the dialog says so). `print` is a black-on-white theme for paper; `manager` is today's output. The upstream
   `nokia*` and `grafana` themes are not reproduced (fact 0.6): the student sees three plain choices on the Topology
   tab (§3.7); the editor's own *Export to draw.io* button keeps today's call (map layout, manager theme).
10. **One-click arrange is a saved map change, made explicit and undoable once.** More ▾ › **Arrange devices…** opens a
    small dialog with three choices, each a button that acts at once (one click inside the dialog; the dialog is the
    sentence that this moves every device and saves the map): **Rows** (layers of a breadth-first walk as rows),
    **Columns** (the same, turned), **Ring**. The browser posts `POST /api/labs/{id}/arrange {mode, revision}`; the
    server computes the positions with the pure `layout.arrange(drawing, mode)`, writes them into the drawing
    (`placed: True`) and into the stored annotations document, calls `keep_document`, saves, and answers the new
    revision. The page then re-fetches the map and renders what the server has: nothing is shown as kept before the
    server kept it. **Undo is exact and lives on the server**: `/arrange` keeps in memory (never persisted) the lab's
    previous `{drawing, annotations, annotations_for, map_written_at}` (with `placed` inside the drawing) keyed by
    the new revision; the caption offers **Undo arrange** once, which posts `{undo: true, revision}`; the server
    restores exactly those keys when the revision still matches (same OSError rollback), so `placed`, the default-grid
    caption, discovery's adoption of the VM's annotations file and `runner.map_changed_in_manager()` all return to
    their pre-arrange values. A revision that moved meanwhile answers **412** with its sentence and the button goes;
    a busy 409 keeps it. Undo is not the editor's history (that lives in `map-editor-page.js` for the editor's
    session); it is one explicit, server-checked step, and the editor's Undo is unaffected (its baseline is the
    document it opened). A lab whose drawing sits on the default grid (`placed: False`, R064) gets a caption sentence
    pointing at it.
11. **Degraded states are sentences, not failures**: an old helper (`capabilities` without `link_state`), an unlinked
    lab, a lab that is not running, a device the manager cannot name a container for, a 503, an unreachable VM, a
    browser that cannot encode PNG, an export of a map with nothing to arrange. Each has its text in §3.9 and §7.
12. **Not implemented, with the reason**: the `* ? +` grammar (decision 5); link colours in the preview and the two
    editor pages (no live lab there); per-node boxed appearance (A3); the telemetry style (`style: telemetry-style`,
    0.4.0, needs rates); rate tiles and link charts (R044/R045, not in this chunk's rows); a PNG background image or
    custom font (nothing beyond the page's own styles is embedded).

## 2. Backend contract

### 2.1 Helper: the `all` option of `interfaces` (`clab-backup-ui/app/host_operations.py`)

- Request `{'mode': 'interfaces', 'name': <lab>, 'options': {'all': true}}`. The option set is exactly
  `{'node', 'container'}` (today) **or** exactly `{'all'}` with `all is True` (`type(value) is bool`); any other set
  or value → `ValueError('Unsupported interface options.')`, nothing run. `identity(name)` as today, no default.
- **Binding first**: one fixed `[self.clab, 'inspect', '--name', lab, '-f', 'json']` (`INSPECT_TIMEOUT`,
  `INSPECT_LIMIT`; about 60 ms live); a non-zero exit or non-JSON output → `{'nodes': [], 'present': False}` (no lab
  of that name is running: not an error); every row's `labPath` must pass `self.trusted()`, else
  `ValueError('This lab was deployed from outside the trusted lab roots. Add its project root during operations
  setup.')` (`container_of`'s sentence) and nothing further runs. The invariant that every read binds a lab name to a
  trusted topology path stays literal for the `all` path.
- Then the argv as today (`[self.clab, 'inspect', 'interfaces', '--name', lab, '-f', 'json']`, `INSPECT_TIMEOUT`,
  `INSPECT_LIMIT`); a non-zero exit raises the existing sentence; non-JSON output → `{'nodes': [], 'present': False}`.
- Result `{'nodes': [{'name': <container ≤ 253>, 'interfaces': [{'name', 'alias', 'state', 'type'}]}], 'present':
  True}`: a reducer of its own (`link_rows(entry['interfaces'])`: the four strings cut at 64, at most 256 rows per
  container, at most 512 containers). No `mac`, `mtu`, `ifindex`, `facts`, `counters`, `docker inspect`. Bound: the
  output never exceeds the 4 MiB input (`INSPECT_LIMIT`) minus the dropped fields, so it stays under `remote()`'s
  3 MiB-per-line reader limit for any listing containerlab can produce within the input cap. The helper does not
  filter by node: binding a container to a manager device is the manager's job (`expected_container`).
- `capabilities` adds `'link_state': bool(self.help('inspect', 'interfaces'))`: probed from containerlab's own help
  text like every other capability, false on a containerlab before 0.64 even with a current helper.
- The dispatch in `main()` is unchanged (same mode, outside the host lock); `test_main_dispatches_the_two_modes_and_
  nothing_wider` and the gateway whitelist test are unchanged in claim.
- `VERSION` lockstep: this is a helper change and so a release with `set-release.py` and `start-manager.sh
  --enable-operations` on every VM; until then the manager sees no `link_state` and the map shows §3.9's sentence.
  The `INSPECT_FORMAT` health fix of fact 0.2 already landed with C05's helper slice (`524fba4`); S0 is the option only.

### 2.2 Manager: `GET /api/operations/link-state?lab_id=` (`clab-backup-ui/app/device_diagnostics.py`)

- `lab_id` ≤ 64. Under the store lock copy the lab's `id, name, deployment_name, container_prefix` and every node's
  `name, short_name, definition_node, kind, platform`. 404 for an unknown lab.
- Without `deployment_name`: `{available: false, reason: 'unlinked', text: UNLINKED_SENTENCE…}` (200). From the
  cached capabilities (`self.operations.cap_cache`, the same read `folder_of` uses; no new helper call): no
  `link_state` key at all (a helper before this release) → `{available: false, reason: 'helper', text: "Link state
  needs the updated VM helper (ask your instructor or administrator). Links are drawn from the topology file."}`;
  `link_state: false` with the manager's own `version` → `{available: false, reason: 'containerlab', text: "Link
  state needs containerlab 0.64 or later on the VM (it has <version>). Links are drawn from the topology file."}`
  (`<version>` from the capabilities' `containerlab`, or omitted). With no cached capabilities, ask the helper anyway
  and turn an `HTTPException` whose detail is `OLD_HELPER_SENTENCE` or `'Unsupported interface options.'` (the
  409 `ask()` already raises) into the `helper` answer.
- Otherwise `self.diagnose({'mode': 'interfaces', 'name': deployment_name, 'options': {'all': True}}, 30)` (one slot of
  the three; a 503 is the existing busy sentence). For every node with `expected_container(lab, node)` non-empty, find
  its entry by container name. Answer:
  `{available: true, devices: {<node name>: {listed: bool, interfaces: [{name, alias, state, port, role}]}},
  listed: n, of: m, fetched_at}` where `port` and `role` come from `displayed_interface` / `interface_role` with the
  node's `kind` (then `platform`), `of` counts the lab's devices with a container name, and a device without one is
  simply absent from `devices` (the browser treats it as unknown). Rows are field-by-field copies, ≤ 256 per device;
  `mac`, `mtu`, `ifindex` are not copied (the map does not show them; the drawer has its own call). Nothing is stored,
  logged or put in an event; GET → no `api.request` line.

### 2.3 The matcher (`map-tools.js`, pure, tested): `mapLinkStates(drawing, answer)`

For every drawing link `[{node, interface, capture_interface}, …]`: the device is `drawingNode.inventory_name`; the
end's row is the first interface of `answer.devices[device].interfaces` whose `name`, `alias` or `port` equals the
endpoint's `interface` or whose `name` equals the endpoint's `capture_interface` (case-sensitive, cEOS `eth1` and
`Ethernet1` both land through `port`/`capture_interface`). The per-end result is one of `up`, `down` (`state !== 'up'`,
with `state` kept as the reason word), `missing` (device listed, no row), `not-running` (device not listed),
`unknown` (device not a lab device, or `available: false`). The wire state is `down` if any end is `down`, `missing`
or `not-running`; `up` if both ends are `up`; else unknown. Returns `[{index, state, ends: [{label, interface, name,
end}]}]` plus `counts: {up, down, unknown}`.

### 2.4 `topology.py` `parse_drawing`: new fields

- Decorations: `lineStartArrow`, `lineEndArrow` (`is True` → `True`, else `False`), `lineArrowSize` (`bounded(…, 10,
  4, 40)`), `roundedBackground` (default **True**, the 0.3.2 renderer's default, so an imported note looks as the
  editor shows it; `False` only when the document says `false`), group `level` (`bounded(int, 1, 1, 10)`, groups only;
  a group with a higher level is drawn **above** one with a lower level within the groups' z band: the default
  `zIndex` of a group stays `-1`, and ties are broken by `level` then document order).
- Settings: `nodeStyle` (`'boxed'` when the document says `boxed`, else `'icon'`), `boxSpacing` (`'narrow'` or
  `'default'`), `linkStyle` (`'elbow'` or `'straight'`). Unknown values fall back to the defaults, as `labelMode` does.
- `schema` stays 3: every new key has a default, so drawings stored before this chunk render as today except that text
  backgrounds become rounded (the editor already shows them so). `layout.annotations()` writes the new keys back
  (`lineStartArrow`, `lineEndArrow`, `lineArrowSize` on shapes; `roundedBackground` on texts; `level` on groups;
  `nodeStyle`, `boxSpacing`, `linkStyle` in `viewerSettings`), so a lab without a stored document round-trips them.
  `layout.decorations()` adds `lineArrowSize` and `level` to `ranges`, `roundedBackground`/`lineStartArrow`/
  `lineEndArrow` as booleans (`is True`), so the simple dialog's save keeps them.

### 2.5 `layout.arrange(drawing, mode)` (pure, deterministic)

- `mode in ('rows', 'columns', 'ring')`, else `ValueError('Choose rows, columns or a ring.')`. Nodes are the drawing's
  nodes in document order; links the drawing's links. Grid constants: 160 px between neighbours in a row, 120 px
  between rows (the `grid_position` constants, so a one-row result for an unlinked lab equals the default grid).
- `rows`: for every connected component (largest first, then by first node id), a breadth-first walk from the node
  with the most links (ties: lowest id); layer k is row k, nodes within a row ordered by their parent's column then id;
  rows are centred on the widest row; components sit side by side with one empty column between them; isolated nodes
  make a last row. `columns`: `rows` with x and y swapped. `ring`: every node on a circle in document order, radius
  `max(120, 160 * n / (2π))`, centred at the bounding box's centre of the current positions (so a ring replaces the
  grid roughly in place).
- Returns `{node_id: [x, y]}` of integers, every coordinate within ±100000. Nothing else of the drawing changes.

### 2.6 `POST /api/labs/{id}/arrange` (`lab_operations.py`, beside `/layout`)

- Body (`extra='forbid'`): `mode: str | None`, `undo: bool = False`, `revision: str` (required, 1..64). Exactly one
  of `mode` and `undo` → else 400 `'Choose an arrangement or undo, not both.'`. No client-supplied positions.
- Under the store lock: `self.guard(lab_id)` (409 `'Wait for the current lab operation to finish.'` while an
  operation runs, as `/layout`); 404 without a drawing (`'Import a topology map first.'`); `revision !=
  revision(lab['drawing'])` → **412** `{detail: 'The map changed since you looked at it. The map was reloaded; try
  again.', reason: 'stale'}` (its own status, so the page can tell it from the busy 409); `len(nodes) < 2` with
  `mode` → 400 `'Nothing to arrange: this map has one device.'`.
- Arrange: `new = arrange(drawing, mode)`; deep-copy the drawing, apply, `placed = True`. If `lab.get('annotations')`
  and `annotations_for == revision(old drawing)`: parse the stored text (it parsed when it was saved), set `position:
  {x, y}` on each `nodeAnnotations` / `networkNodeAnnotations` entry whose `id` is a drawing node id, append `{id,
  position}` for a drawing node that has no entry, `json.dumps(…, ensure_ascii=False, indent=2)`; otherwise take
  `json.dumps(annotations(new drawing))` (the document the editor would open anyway). Before changing anything, copy
  `previous = {k: lab.get(k) for k in ('drawing', 'annotations', 'annotations_for', 'map_written_at')}` (deep).
  Then `lab['drawing'] = new; keep_document(lab, text); store.save()` with the same OSError rollback the map-document
  save has (every key restored from `previous`); on success remember `self.arrange_undo[lab_id] = (new revision,
  previous)` in memory only (one entry per lab, never persisted, gone on restart); event `topology.layout` with the
  message `Devices arranged in rows` / `… in columns` / `… in a ring`.
- Undo (`undo: true`): the entry for `lab_id` must exist and its revision must equal both the request's `revision`
  and `revision(lab['drawing'])`, else 412 with the stale sentence and `reason: 'stale'` (and the entry dropped);
  then every key of `previous` is restored exactly (a key that was `None` is popped, as the map-document rollback
  does), `store.save()` with the same OSError rollback, the entry dropped, event `Device positions restored`. So
  `placed`, the default-grid caption, discovery's adoption of the VM's annotations file (`unplaced()`) and
  `runner.map_changed_in_manager()` return to their pre-arrange values. A map-document save, a `/layout` save, an
  import or a sync in between changes the drawing's revision, so Undo is refused rather than applied over them.
- Answer `{saved: True, revision, undo: bool}` (`undo` true when an Undo entry now exists for this revision). The
  sentences are the student's; nothing names a path.

### 2.7 `GET /api/labs/{id}/drawio?layout=&theme=` and `drawio_export.drawio(lab, layout, theme)`

- `layout in ('map', 'interactive', 'rows', 'columns')` (`interactive` → `map`), else 400 `'Choose a supported
  layout.'` (the kept sentence); `theme in ('manager', 'print')`, else 400 `'Choose a supported theme.'`. Defaults
  `map`, `manager`: the editor pages' calls are unchanged. `POST /drawio` (the simple dialog) gains nothing.
- `rows` / `columns`: positions from `arrange()` on a deep copy of the drawing, **decorations dropped**, settings kept.
- `print`: page background `#ffffff`; node cells `fillColor=#ffffff;strokeColor=#000000;strokeWidth=1.5;
  fontColor=#000000;labelBackgroundColor=none`; symbol strokes `#000000`; links `strokeColor=#000000;strokeWidth=2`;
  interface labels `fontColor=#333333;labelBackgroundColor=#ffffff`; decorations keep their geometry, borders become
  `#000000`, fills `none`, text `#000000`. Colours a person set in the map are dropped by design: print is for paper.
- `manager` with `layout=map` is byte-for-byte today's output for a drawing **without text decorations** (pinned by
  a golden comparison on such a fixture); a drawing with notes gains `rounded=1` on its text cells because
  `roundedBackground` now defaults to true (§2.4), which is the editor's own default.
- New: line arrowheads (`startArrow=classic` / `endArrow=classic`, `startSize`/`endSize` = `lineArrowSize`) and
  `rounded=1` on text cells with `roundedBackground`; boxed nodes as `rounded` 80×80 (64 narrow) cells with the name
  inside (`verticalAlign=bottom` inside the cell) when `settings.nodeStyle == 'boxed'`; elbow links as
  `edgeStyle=orthogonalEdgeStyle` when `linkStyle == 'elbow'`.
- The filename stays `<lab>.drawio` for `map`; `rows`/`columns` save `<lab>-rows.drawio` / `<lab>-columns.drawio`.

## 3. The UI

Files: `map-tools.js` (new; loaded after `device-diagnostics.js` and before `diagram-editor.js`, with `?v=` in
`index.html`), `index.html` (tool bar, menu, dialogs, captions), `style.css` (new rules only), `topology-render.js`
(decoration and link markup, boxed and elbow, glyphs, `data-link-ends`), `topology.js` (three hooks, §3.0),
`map-editor-page.js` (`MAP_ICONS` two entries). No inline styles; `esc()` on every interpolation; every new top-level
name starts with `mapTool` or `mapLink` (no collision with `topology.js`'s `map*` names: `test_page_load_ui.js`).

### 3.0 Hooks in `topology.js` (the only edits there)

1. `refreshMap`: at its top, before the unchanged-drawing early return, `if(typeof mapLinkSchedule==='function')
   mapLinkSchedule()` (idempotent: re-checks the run conditions on every visit and render, fetches nothing by
   itself); and after `renderMapState()`, `if(typeof mapToolsRendered==='function')mapToolsRendered(drawing)` (the
   map was rebuilt: re-apply find dimming and the cached link classes, reset the hover). C05 adds its own line after
   the second; order does not matter, each re-applies its own classes.
2. `mapStage(kind)`: disables `#map-find` and the three new menu items with the tools (`off`), and hides `#map-links`,
   `#map-find-count`, `#map-link-hover` when `kind !== 'map'`.
3. `mapWireText(group)` (decision 6): `const clauses=[group.dataset.stateText,group.dataset.impairedText].filter(Boolean);
   const base=group.dataset.base||group.querySelector('title')?.textContent||'',aria=group.dataset.ariaBase||
   group.getAttribute('aria-label')||'';title.textContent=[base,...clauses].join(' · ');group.setAttribute('aria-label',
   [aria,...clauses].join(' · '))` and returns the title text. On first use it stores the original title in
   `data-base` and the original `aria-label` in `data-aria-base` when the renderer did not emit them (§3.5), so the
   accessible name stays `Capture a:if to b:if` plus clauses and the title `a:if — b:if` plus clauses; both are
   pinned in `test_topology_menu_ui.js`. C05's `renderMapImpairments` writes `data-impaired-text` and calls this
   instead of restoring titles itself (its own design is amended by the sentence in §9 row 16; its words are unchanged).

### 3.1 The tool bar and the More ▾ menu (`index.html`)

`.map-tools`: `<label for="map-find" class="map-find-label">Find</label><input type="search" id="map-find"
class="map-find" placeholder="Device name" autocomplete="off" aria-describedby="map-find-count">` before **Fit**;
then Fit, +, −, Expand, Edit map, More ▾ as today. The input is 11 em wide at desktop and full width in the wrapped
bar below 760 px (the bar is already `flex-wrap: wrap` and `position: static` there).

`#map-more-menu`: **Import map…** · **Download picture…** (`#map-picture`) · **Export to draw.io…** (`#map-drawio-export`)
· **Arrange devices…** (`#map-arrange`) · `hr.menu-sep` · **Open all CLIs ↗** · **Back up all configurations**. Seven
items and one separator: about 270 px, inside the stage's minimum height of 420 px (360 px below 760 px, where the bar
is in flow at the top). The bar also carries Find and, once C05 lands, its impairment chip and Clear button, so it
may wrap and the menu starts lower: the fixture pass checks the last item fully visible at 1440, 1280, 760 and 390
with the C05 chip and Clear button shown and the stage at its minimum height, and S3 rewrites the clipped-menu note
in `style.css` to the measured limit (seven items plus a separator at a wrapped two-row bar); if a viewport fails,
the menu is rendered `position: fixed` from the button's rectangle rather than trimmed. The three new items are
disabled with the tools and carry a visible `<small class="menu-reason">No map yet</small>` like their siblings (and
`title`); they are not proxied elsewhere (one owner, no `data-proxy`), except that the Tools card "Map" sentence
changes (§5).

Captions inside the stage, each a chip like `#map-status`: `#map-status` (bottom-left, unchanged) gains a sibling line
`#map-links` (`role="status"`, bottom-left above it) for link state, `#map-find-count` (`role="status"`, bottom-left
above both, shown only while the filter is non-empty) and `#map-link-hover` (bottom-right, `aria-hidden="true"`: its
words are already in the wire's `aria-label`). An `#map-arrange-hint` `<button class="button ghost small">` sits in
`#map-links`'s row when the drawing is on the default grid (§3.8).

### 3.2 Link state (`map-tools.js`)

- `mapLinkFetch(labId)`: `GET /api/operations/link-state?lab_id=`; the answer is kept in `mapLinkCache[labId]`
  (browser memory only). `mapLinkApply(answer)`: `mapLinkStates(current drawing, answer)` then, per wire group in
  document order (`map.querySelectorAll('.topology-wire')[index]`), `classList.toggle('link-up', …)`,
  `classList.toggle('link-down', …)`, `data-state-text` set to the clause and `mapWireText(group)` called. Clauses:
  `down: vrt ge-0/0/1 is dormant` (one end) · `down at both ends (dormant: one side may be shut down)` (both ends in
  the same non-up state, worded once, no device blamed: fact 0.4 shows an EOS shutdown reads `dormant` on the
  neighbour too) · `down: vrt ge-0/0/1 is dormant · cjunos et-0/0/0 is down` (two different states, both named) ·
  `down: cjunos et-0/0/0 is missing on the device` · `down: ceos is not running` · `up` · (unknown: no clause, the
  attribute removed). The kernel word (`dormant`, `lowerlayerdown`) is kept in parentheses because it is what the VM
  reported and what an instructor will look for; the student-facing verdict is `down`.
- **What the state means on a VM-in-container device (A1)**: for the vrnetlab kinds (`juniper_vjunosswitch`,
  `juniper_vjunosevolved`, `juniper_vjunosrouter`, `juniper_vqfx`, `cisco_xrv9k`, `vr-xrv9k`: the kinds whose data
  ports are wired to a QEMU guest) the container veth may stay `up` while the port is shut inside the guest. The
  answer marks such a device `vm: true` (a kind tuple in `device_diagnostics.py`) and the words follow: the chip
  counts `Links: n connected` instead of `n up` whenever any end of the lab is a `vm` device, the hover clause for an
  up link ending on such a device reads `connected (the VM's link to vsw; a port shut down inside vsw may not show
  here)`, and the legend reads `dotted red = down (container link)`. The live pass (§6) settles whether `disable`
  on `vsw` is visible: if it is, the `vm` wording is dropped for that kind by removing it from the tuple (one line);
  if not, the wording ships as written. §5's guide text promises only what the container link shows.
- `#map-links` text: `Links: n up · m down` (with `m down` omitted when 0) or `Links: n up` and, when some are
  unknown, ` · k not checked`; when `available: false`: `Link state off: <text>` once, not repeated by the poll, and
  every `link-*` class and `data-state-text` cleared; while a 503 or error keeps old colours: `Link state paused,
  retrying…`; stopped: `Link state stopped (as of 14:02). <Retry>`; paused after 30 minutes: `Link state paused
  (as of 14:02). <Resume>`, and in both stopped and paused each kept clause gains ` (as of 14:02)` through
  `mapWireText`. The chip's text changes only when its words change (no announcement storm). While the lab's
  `deployment.status` is not Running or Partially running the chip reads `Links are drawn from the topology file;
  the lab is not running.`, the classes and clauses are cleared, and no request is made; an unlinked lab reads the
  unlinked sentence of §3.9 without a request.
- Legend: a `<span class="map-legend">` inside `#map-links`, shown only while `available` is true: a 24 px inline SVG
  sample of the dotted red stroke with the text `dotted red = down` and, when C05's cache has any impairment, the
  dashed amber sample `dashed amber = impaired`. Screen readers get the words from the chip; the samples are
  `aria-hidden`.
- The poll (decision 4): `mapLinkPoll` holds `{timer, inFlight, plan, lastAt}`; `mapLinkSchedule()` returns at once
  when `timer` or `inFlight` is set, otherwise evaluates the run conditions and either arms the timer (first fetch
  after 0 ms when nothing has been fetched for this lab, else after the plan's delay) or clears the state and the
  classes per the condition that failed. It is called at the top of `refreshMap` (every `showTab('topology')` and
  every 4 s render reach it), from the drawer's `close` event in `shell.js` (one guarded call `if(typeof
  mapLinkDrawerClosed==='function')mapLinkDrawerClosed()` next to the existing `resetDeviceDiagnostics` call) and from
  `diagVisibilityChanged` in `device-diagnostics.js` (the same guarded call to `mapLinkVisibility()`, so `shell.js`
  keeps its one `visibilitychange` listener). Tested: tab away and back with the drawing unchanged, then the lab from
  Stopped to Running, gives exactly one fetch each. `selectLab` → `mapToolsReset()` clears the cache, the filter, the
  plan and the classes.
- Composition with C05's badge: a wire can carry `link-down` and `impaired`; CSS gives `link-down` the last word on
  the stroke (`.topology-wire.link-down path:not(.capture-hit)` is written after `.impaired`'s rule), the title names
  both clauses. `mapLinkApply` never touches `impaired`, `data-impaired-text`, the count chip `#map-impaired` or the
  Clear button.

### 3.3 Find a device

`mapFindApply(term)`: `term = value.trim().toLowerCase()`; for every `.map-device`, the haystack is, for a matched
device `n` of `current().nodes` (by `data-map-node`), `(n.name+' '+n.address+' '+platformLabel(n.platform)+' '+
label).toLowerCase()` (the Devices search's own expression, `app.js` `renderDeviceList`, plus the drawn label), and
for an unmatched drawing node the label alone; `match = !term || haystack.includes(term)`; `classList.toggle('dimmed',
!match)`; every `.topology-wire` whose two `data-link-ends` devices are both non-matching gets `dimmed` too (a wire
with one matching end stays), so the student sees a device **and** what it connects to. `#map-find-count`: hidden
when the term is empty; `n of m devices match` / `1 of m devices matches` / `No device matches "<term>"` (escaped),
and the field's hint reads `Name, address or platform`. Enter: `mapBox` fits the matching devices' bounding box plus
60 px (falls back to Fit when nothing matches) through `setMapBox` (`topology.js` globals). Escape in the field: when
it holds a term, clear it, keep focus, `preventDefault()` and `stopPropagation()` (the expanded map stays open); when
it is empty, let the event through (the next handler closes the expanded map as today); tested with the map
expanded. Dimming is CSS opacity on the group (`.map-device.dimmed, .topology-wire.dimmed {opacity:.25}`), so the
device stays clickable and focusable and `renderMapState` keeps swapping its state class. `mapToolsRendered`
re-applies the current term after a rebuild. The filter never reaches `#search` on the Devices tab.

### 3.4 Link hover

Delegated on `#topology-map`: `pointerover` whose target is inside a `.topology-wire` adds `hover` to that wire and
`hover-end` to the two groups named by `data-link-ends` (looked up by `[data-map-node="…"]`, or by `data-map-id` for an
unmatched drawing node) and writes `mapWireText(wire)` into `#map-link-hover` (unhidden); `pointerout` leaving the wire,
and `focusout`, clear them; `focusin` on a wire does what `pointerover` does, so keyboard users get the same line.
CSS: `.topology-wire.hover path:not(.capture-hit){stroke:var(--accent);stroke-width:4}` is the existing `:hover` rule
written once more for the class (the `:hover` rule itself stays for the no-script case); `.map-device.hover-end
.device-body{stroke:var(--accent);stroke-width:3}`. Nothing else fades: the find filter already owns dimming, and two
competing opacity rules would read as a flicker. The hover line reads, for example, `vrt:ge-0/0/1 — cjunos:et-0/0/0 ·
down: vrt ge-0/0/1 is dormant` and, with C05, `· impaired at vrt ge-0/0/1 (traffic leaving vrt): delay 20ms`.

### 3.5 The renderer (`topology-render.js`)

- `topologyLink` emits `data-link-ends="<nodeA>|<nodeB>"` (inventory names, or `#<map id>` when unmatched, escaped;
  device-only, the one contract: C05's matcher reads interfaces from `data-capture-endpoints`), `data-base="<a:ifA —
  b:ifB>"` (the title text) and `data-aria-base="Capture <a:ifA> to <b:ifB>"` (today's `aria-label` text) on every
  wire group, including the self-link. Markup is otherwise unchanged for `straight`, so the existing geometry tests
  keep their claims.
- Elbow (`settings.linkStyle === 'elbow'`): the wire path is `M ax ay H mx V by H bx` with `mx` at the horizontal
  midpoint when `|dx| ≥ |dy|`, else `M ax ay V my H bx V by`; the two ends leave the icon (or the box) on the side the
  first segment runs along; interface labels sit on the first and last segments at the same offsets as today, rotated
  to read along a vertical segment (`transform="rotate(-90 …)"`); the self-link stays a loop. Every path keeps the
  `capture-hit` twin. Parallel links between the same pair fan out by 12 px per extra link in both styles (today they
  overlap; the editor fans them out).
- Boxed (`settings.nodeStyle === 'boxed'`): `topologyNode` draws, around the existing 40 px body, a `<rect
  class="device-box">` of size 80 (`boxSpacing === 'narrow'`: 64), centred on the icon's anchor, `rx` 10 (8 narrow),
  with the label **inside** the box under the icon at 12 px (the label group gets class `device-label-boxed`; the
  `labelPosition` is ignored in this style, as upstream does), middle-truncated to fit (`mapBoxedLabel(text, 10|8)`,
  pure; the full name stays in `<title>` and `aria-label`); the state badge moves to the box's corner. Theme colours
  through CSS (`.device-box{fill:var(--surface);stroke:var(--line-strong)}`), `iconColor` only on the inner body as
  today. `topologyLink` attaches the wire to the box outline (radius 40 or 32 instead of 20) when boxed.
- Arrowheads: `topologyDecoration` for `type === 'line'` emits `<marker>` definitions once per drawing in
  `topologyMarkup`'s `<defs>` is not possible per colour, so each line with an arrow gets its own `<polygon>` at the
  end(s), sized `lineArrowSize`, filled with the line's `borderColor`, exactly as the 0.3.2 SVG exporter draws them
  (`mr()` in the bundle: a triangle whose tip is the line end and whose base is `size` back along the line); the line
  itself is shortened by `size` at an arrow end so the tip is sharp.
- Rounded text backgrounds: the text decoration's `<rect>` gets `rx="6"` when `roundedBackground !== false`.
- Group z-order and nesting: decorations are sorted by `zIndex`, then `level` (groups), then index; a group whose
  bounds lie inside another group's bounds is drawn after it (so above it) regardless of `level` ties, and gets no
  extra inset (the editor pads nested groups by their own stored geometry).
- Glyphs: `topologyGlyph('container')` draws a box with a lid line (`M-13-9H13V13H-13ZM-13-3H13M-6-9V-13H6V-9`);
  `host` keeps the server glyph but is listed in `MAP_ICONS` (`['host','Host'],['container','Container']`, in the
  editor's order) so Device look offers it. `firewall` and `vm` are not in the 0.3.2 bundle (fact 0.7) and are not added.
- `measureTopology` is unchanged (labels are measured by class; the boxed label uses the same classes).

### 3.6 Download picture… (`#map-picture-dialog`)

A `<dialog>` with a `<form>`: fieldset **Format** (radio `SVG` default / `PNG`), fieldset **Area** (`Whole map` default
/ `What is shown now`), checkboxes `Background colour` (checked; off = transparent), `Device state and link colours`
(unchecked: a report picture should not carry a moment's state), a `role="status"` line, Cancel and **Download**.
`mapPictureSvg(options)` (pure over a cloned `<svg>` element and a style reader, tested with a fake `getComputedStyle`):
**first neutralise the live map** (`mapPictureNeutral(map, stateOff)` returns a restore function and is called in a
`try … finally`): remove `hover`, `hover-end` and `dimmed` from every element, clear the hover line, and when the state
option is off put every `.map-device` on `state-neutral` and drop every `link-*` class (the `impaired` class too),
remembering each element's original class list; read the computed styles while the map is in that state; restore
everything in `finally`, then `renderMapState()` and `mapToolsRendered()` re-apply what the page shows. Tested with
the fake style reader: a Ready device and a dimmed device in a state-off export come out with the neutral stroke and
opacity 1, and the live map is unchanged afterwards. Then clone `#topology-map`; remove `path.capture-hit`, `[aria-hidden]` glyph groups when state is off, `.device-state-dot`
and `.device-state-glyph` when off, every `tabindex`, `role`, `aria-*`, `data-*` attribute and the `<title>` elements
(the SVG is a picture, the names are drawn as text); drop `link-*`, `hover*`, `dimmed`, `state-*` classes when state is
off (keep `link-down`/`impaired` strokes inlined when on); for every element copy these computed properties into
presentation attributes when they differ from the SVG default: `fill, fill-opacity, stroke, stroke-width,
stroke-dasharray, stroke-linecap, stroke-linejoin, opacity, font-family, font-size, font-weight, display,
visibility, text-anchor`; set `viewBox` to `mapBounds` (whole) or `mapBox` (shown), `width`/`height` to the viewBox
size, `xmlns`; without background, remove `rect.topology-bg` and `rect.topology-grid`; with it, give the bg rect the
viewBox's bounds and the computed fill. Serialise with `XMLSerializer`, save through `<a download>` as
`<lab>-map.svg` (lab name cleaned with the SuperPuTTY export's rule: `[<>:"/\\|?*\x00-\x1f]` → `_`, 150 chars).
PNG: `Image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgText)`; on load, a canvas of
`min(2, 8192 / longest side)` × the viewBox size, white or transparent per the option, `drawImage`, `toBlob('image/png')`
→ `<lab>-map.png`. Errors to the status line: `The PNG could not be made in this browser. Download the SVG instead.`
(image error or `toBlob` null); `The map is too large for a PNG here (over 8192 px). Download the SVG.` Nothing is sent
to the manager; the dialog closes on success with the toast `Picture saved as <name>.`

### 3.7 Export to draw.io… (`#map-drawio-dialog`)

Fieldset **Arrangement**: `As on the map` (default) / `Rows` / `Columns`; fieldset **Theme**: `Manager colours`
(default) / `Print (black and white)`; the form-help `Rows and Columns arrange the devices for the file only; your map
is not changed, and notes, boxes and groups are left out of those two.`; a `role="status"` line; Cancel and
**Download**. Download fetches `/labs/<id>/drawio?layout=<map|rows|columns>&theme=<manager|print>` through `api()`,
checks the response and saves the blob through an `<a download>` named by `attachmentName(response, '<lab>.drawio')`
(the SuperPuTTY export's pattern, `topology.js`'s `export-form` handler); a 400, 404 or 500 shows the server's
sentence in the status line instead of a downloaded error file. The Tools card keeps **Edit map** and says where the
exports are (§5).

### 3.8 Arrange devices… (`#map-arrange-dialog`) and Undo

The dialog: `<h2>Arrange devices</h2><p>Every device moves and the map is saved. Notes, boxes and groups stay where
they are. You can undo this once, right after.</p>`, and when the drawing has groups a second sentence `<n> groups
will no longer surround their devices.`; three buttons `Rows`, `Columns`, `Ring`, each `data-arrange="rows|columns|
ring"`, plus Cancel. `Rows` and `Columns` are disabled with the visible reason `This map has no links to arrange by`
when `drawing.links` is empty (`Ring` stays). A click disables the three (`Arranging…`), posts `/labs/<id>/arrange
{mode, revision: drawing.revision}` (the revision the Topology view fetched: `bind_drawing` emits it), closes the
dialog, `refreshMap(true)`, toast `Devices arranged in rows.` and `#map-links`'s row shows **Undo arrange** while the
answer said `undo: true`, until the lab changes, the drawing's revision changes by someone else (the next `refreshMap`
compares `drawing.revision` with the answer's `revision`) or Undo is used. Undo posts `{undo: true, revision}`; a
**412** (stale) shows the server's sentence in `#map-status`, removes the button and `refreshMap(true)`; a busy
**409** shows its sentence and keeps the button (nothing changed, the student can try again after the operation).
Errors on arrange: 409 busy → the server's sentence (`Wait for the current lab operation to finish.`) in the dialog's
status; 400 one device → its sentence. Nothing is drawn from the browser's own idea of the result: the map always
re-renders from `GET /topology`.

Default-grid caption (R064): when `drawing.placed === false` (the binding answer carries it) and the drawing has two
or more nodes, `#map-links`'s row shows the sentence `Devices sit on the default grid.` with the ghost button
**Arrange devices…** (`#map-arrange-hint`, opening the same dialog); it goes when `placed` is true (and comes back
after an exact Undo, which restores `placed`). The empty state (`drawing === null`, an inventory import) is
unchanged: there is nothing to arrange without a map.

### 3.9 Empty and degraded states

| Situation | What the student sees | Where |
|---|---|---|
| Old helper (no `link_state` key) | Wires as today, classes cleared; `#map-links`: `Link state off: Link state needs the updated VM helper (ask your instructor or administrator). Links are drawn from the topology file.`; no poll | §2.2, §3.2 |
| Current helper, containerlab before 0.64 (`link_state: false`) | `Link state off: Link state needs containerlab 0.64 or later on the VM (it has 0.6x.y). Links are drawn from the topology file.`; no poll | §2.2 |
| Lab not linked to the VM (no `deployment_name`) | Checked first in the browser, no request: `Link state off: This lab is not linked to a lab on the VM. Link it under Advanced › Link to a running lab… to see link state.` | §3.2 |
| Lab not running (`deployment.status` Not deployed, Stopped, Unknown) | `Links are drawn from the topology file; the lab is not running.`; classes and clauses cleared; no request | §3.2 |
| Lab booting, in an operation, or Partially running | Polled: these are where link state matters most | decision 4 |
| Poll stopped (three errors) or paused (30 minutes) | Colours kept with the time: chip `Link state stopped (as of 14:02). Retry` / `… paused (as of 14:02). Resume`; every clause carries `(as of 14:02)` | §3.2 |
| VM-in-container device (A1, `vm: true`) | Chip counts `connected`; an up link's clause says the VM's link may not show a port shut inside the guest | §3.2 |
| Device the manager cannot name a container for | Its wires unknown; counted in `k not checked`; the hover clause for that end is `not checked (no container name)` | §2.3 |
| 503 (slots busy) or VM unreachable | Last colours kept, `Link state paused, retrying…`; after three errors `Link state stopped. Retry` | §3.2 |
| Drawer open | Poll stops silently; colours stay; resumes with one fetch on close | decision 4 |
| Hidden tab | Poll stops; one fresh fetch on return | decision 4 |
| Unmatched drawing node | Not dimmed by Find unless its label fails the term; its wires never read down | §2.3, §3.3 |
| No map | Find, the three menu items and the chips are off (`No map yet`); the empty state is today's | §3.0 |
| Find matches nothing | `No device matches "<term>"`; everything dimmed; Enter does Fit | §3.3 |
| PNG cannot be made | The dialog's status sentence; the SVG option stays | §3.6 |
| Arrange on a one-device map | 400 `Nothing to arrange: this map has one device.` in the dialog; the grid hint is not shown for one device | §2.6, §3.8 |
| Arrange or Undo while an operation runs | 409 `Wait for the current lab operation to finish.`; Undo stays offered | §2.6, §3.8 |
| Map changed under the student (arrange or Undo) | 412 `The map changed since you looked at it. The map was reloaded; try again.`; Undo removed; `refreshMap(true)` | §2.6, §3.8 |
| Undo after a manager restart | The in-memory entry is gone: 412 with the stale sentence; the map is as last saved | §2.6 |
| draw.io export fails (400, 404, 500) | The server's sentence in the dialog's status line; no file | §3.7 |
| draw.io with an unknown layout or theme (hand-typed URL) | 400 `Choose a supported layout.` / `Choose a supported theme.` | §2.7 |

## 4. Tests per layer

- `test_host_diagnostics.py` (helper): `interfaces` with `{'all': True}` runs exactly two fixed argvs in order
  (`inspect --name <lab> -f json`, then `inspect interfaces --name <lab> -f json`), never `docker`; a binding row whose
  `labPath` is outside the roots refuses with `container_of`'s trusted-roots sentence and the second argv never runs;
  a binding that is not JSON or exits non-zero answers `present: False` with no second call; rows are reduced to
  exactly `{name, alias, state, type}` (no `mac`, `mtu`, `ifindex`; strings cut at 64); with a fake runner that
  bypasses `capture`'s size limit, 513 containers × 300 rows are cut to 512 × 256 and the serialised result is
  smaller than the fake input; refused with nothing run: `{'all': 1}`, `{'all': True, 'node': 'x'}`, `{'all':
  False}`, a missing `name`; `capabilities` carries `link_state` true when the fake `clab inspect interfaces --help`
  answers and false when it fails; `main()` dispatches the same mode set as before (the existing dispatch test's list
  is unchanged).
- `test_device_diagnostics.py` (manager): `/link-state` without `deployment_name` → 200 `available: false,
  reason: 'unlinked'`; cached capabilities without a `link_state` key → `reason: 'helper'` and **no** helper call;
  cached capabilities with `link_state: false` and `containerlab: '0.60.0'` → `reason: 'containerlab'` with the
  version in the sentence and no helper call; with the flag → one `remote` call whose request is exactly `{'mode':
  'interfaces', 'name': <deployment>, 'options': {'all': True}}`; devices are keyed by manager node name through
  `expected_container` (a `container_prefix` lab, a node without `definition_node` is absent from `devices`);
  `port`/`role` as C03's route gives them (cJunosEvolved `eth4` → `et-0/0/0`); `vm: true` for the vrnetlab kinds and
  absent otherwise; a device absent from the listing is `listed: false`; the answer never carries `mac`, `mtu`,
  `ifindex`, `facts` or an id; 20 polls leave `events.jsonl` byte-identical and the Store free of interface rows; a
  patched `ask()` raising the 409 with `OLD_HELPER_SENTENCE`, or with `'Unsupported interface options.'`, gives the
  `helper` answer (200); the fourth concurrent call is a 503.
- `test_topology.py`: `parse_drawing` keeps `lineStartArrow`/`lineEndArrow`/`lineArrowSize` (bounded), `roundedBackground`
  default true and false when said, group `level`, `nodeStyle`/`boxSpacing`/`linkStyle` with defaults for unknown
  values; `test_import_retains_annotation_visual_fields` gains the new keys (its existing claims kept); the
  round trip `annotations(parse_drawing(x))` carries them.
- `test_layout.py` (new file or in `test_topology.py`): `arrange` modes on a chain, a star, a ring, two components and
  isolated nodes (deterministic, integers, within bounds, no two nodes at one point, a one-row result equals
  `grid_position` for an unlinked lab); `decorations()` accepts and bounds the new keys.
- `test_lab_operations.py`: `test_removed_drawio_layouts_rejected` is **rewritten** as `test_drawio_layouts_and_themes`
  and keeps its claim: `horizontal` and `vertical` are still 400 (the helper-run graph stays removed), beside
  `diagonal` and `theme=neon` with the sentences; `rows` and `columns` answer 200 with `node-*` and `link-*` cells and
  no `annotation-*` cells, `map` and `interactive` are byte-identical for `theme=manager`, `print` carries no
  `#0066ff` and a white background; a drawing without text decorations exports byte-identically to a golden file;
  the filename rule. `test_layout_drawio_favorite_and_no_vm_mutation` keeps its claim and adds `theme=manager`. New:
  `/arrange` with `mode=rows` moves every node, sets `placed`, rewrites the stored document's positions and keeps
  every other key byte-for-byte (`somethingNew`, `groupId`, `lineEndArrow`), `annotations_for == revision(drawing)`
  afterwards, answers `undo: true`; `{undo: true, revision}` restores the lab dict **exactly** (`drawing` with
  `placed`, `annotations`, `annotations_for`, `map_written_at`, and `runner.map_changed_in_manager()` back to its
  pre-arrange value) apart from the two events; a stale revision is 412 with `reason: 'stale'` and changes nothing
  (for arrange and for undo); Undo after a map-document save in between is 412; Undo with no entry (a fresh
  `create_app`, the restart case) is 412; a running operation is 409 for both and leaves the Undo entry in place
  (a later Undo succeeds); both `mode` and `undo`, or neither, is 400; one device is 400; no helper call
  (`remote.call_count` unchanged); an OSError on save restores every key and keeps no Undo entry.
- `test_topology_ui.js` (renderer): `data-link-ends` and `data-base` on wires including the self-link; elbow paths
  (`H`/`V` segments, labels rotated on vertical segments, the hit twin present); fan-out of parallel links; boxed
  nodes (80/64 px box, label inside, truncation, badge position, wire radius 40/32); arrowheads (polygon count, line
  shortened, size); `rx` on text backgrounds by default and absent when `false`; group ordering by `level` and
  containment; the `container` glyph; the straight-link geometry tests unchanged.
- `test_map_tools_ui.js` (new; `test_topology_menu_ui.js` harness, loading `status.js`, `topology.js`, `map-tools.js`):
  `mapLinkStates` (the five end results, both-ends-down, unmatched node, `available: false`, alias/port/capture
  matching for cEOS and vrnetlab names); the chip words for every count and state; the legend only when available;
  the both-ends wording (`down at both ends (dormant: …)` once, two different states both named); the `vm` wording
  (`connected`, the VM's-link clause) and its absence for a cEOS-only lab; `mapLinkApply` toggles exactly
  `link-up`/`link-down`, writes `data-state-text`, leaves `impaired` and `data-impaired-text` alone and `mapWireText`
  joins both clauses; the poll: `mapLinkSchedule` is idempotent (two calls arm one timer; none while in flight),
  the run conditions on `lab.deployment.status` (a booting lab, a lab with a running operation and a Partially
  running lab are polled; Not deployed, Stopped, Unknown are not; an unlinked lab gets its sentence and no request;
  tab hidden, drawer open, stage not `map`: no fetch), tab away and back with the drawing unchanged then Stopped to
  Running gives exactly one fetch each, two successes keep the 10 s delay (`floor`), the transitions (to not
  running and to `available: false` clear the classes and clauses; stop and pause write the time into chip and
  clauses; a 503 keeps them under the retrying text); Find: the haystack (name, address, platform label, label;
  label only for an unmatched node), dimming of devices and of wires with two dimmed ends, the count sentences, Enter
  fits, Escape on a term stops propagation with the map expanded (the expanded class stays) and on an empty field
  falls through (the class goes), no document listener added (the harness's `document.addEventListener` is a spy);
  hover: classes on the wire and its two ends, the hover line text, cleared on `pointerout`/`focusout`;
  `mapPictureSvg` with a fake style reader: the live map is neutralised before reading and restored after (a Ready
  device and a dimmed device in a state-off export give the neutral stroke and opacity 1; the live classes are back
  afterwards), hit paths, aria, data and titles removed, state removed unless asked, computed `stroke` inlined,
  viewBox per option, background per option, file names; the draw.io dialog fetches through `api()`, saves the blob
  with the `Content-Disposition` name and shows a 400's sentence; the arrange dialog shows the group count, disables
  Rows and Columns without links, posts `{mode, revision}`, calls `refreshMap(true)`, offers Undo while `undo` is
  true, keeps it on a 409 and drops it on a 412 or a revision change; the grid hint only for two or more devices;
  `mapToolsReset` on lab change; `mapBoxedLabel` truncation.
- `test_device_diagnostics_ui.js`: `diagPollNext` with `plan.floor` 10000 keeps 10 s after two successes and
  without `floor` behaves as before (5 s floor).
- `test_topology_menu_ui.js`: `mapStage('empty')` disables the new controls; `mapWireText` composition pinned for
  both texts (`aria-label` = `Capture a:eth1 to b:eth1 · up`, `title` = `a:eth1 — b:eth1 · up`, both from the
  renderer's `data-aria-base`/`data-base` and with C05's clause appended). `test_page_load_ui.js`: the new script
  loads with the page (no duplicate top-level name); the Tools card sentence of §5 is pinned there (the old sentence
  had no test pin at `08e7336`; the new one gets one). `test_map_editor_ui.js` or `test_lab_builder_ui.js`:
  `MAP_ICONS` lists `host` and `container`.
- Fixture pass (`clab-ui-qa`, `fixture_manager.py` learns `{'all': True}` and `link_state` in capabilities; a scripted
  state where one interface is `dormant` and one device absent): at 1440/1280/760/390: red dotted wire with the chip
  words and hover line, Find dims and counts, Enter fits, picture download events for SVG and PNG (file names), the
  draw.io dialog's URL per choice, Arrange rows then Undo (the map re-renders from the server each time; `placed`
  flips), the More menu's last item fully visible at 390, no inline style, no console error, `#topology-map` bottom
  within the viewport at 1366×768 (`verify_after.py`'s existing check still passes with the new chips).
- CI: the lead appends `test_map_tools_ui.js` (and `test_layout.py` if separate) to the lists.

## 5. Documentation

- `docs/LAB-OPERATIONS.md` "The map and its editor": replace the sentence "The Topology tab draws less than the editor
  can store: line arrows, rounded text backgrounds and nested group levels are kept in the map document and shown by
  the editor, but are not drawn on the Topology tab (…)" with: "The Topology tab draws what the editor stores: line
  arrows, rounded note backgrounds, nested group levels, and a map saved by the VS Code extension in the boxed node
  style or with elbow links is drawn in that style (the per-device box colours of that newer editor are not drawn
  yet). Devices and links of a lab whose map was never placed sit on a grid; **More ▾ › Arrange devices…** lays them
  out in rows, columns or a ring and saves the map, with **Undo arrange** offered once (it puts the map back exactly
  as it was); Edit map's own layouts stay."
  Add a paragraph "Link state on the map": "On a VM whose helper reports `link_state` (containerlab 0.64 or later),
  the Topology tab asks the VM every ten seconds, while the tab is open and the device panel closed, which container
  links are up. A link whose container interface is not up on either end (gone with a stopped neighbour, or set down
  or dormant by the device: a cEOS `shutdown` shows this way) is drawn red and dotted; the caption under the map
  counts links and names the reason when you hover or focus a link; links the manager cannot check keep the plain
  stroke and are counted as not checked. For a device that runs as a virtual machine inside its container
  (vJunos-switch, vJunos-router, vJunosEvolved, vQFX, XRv9k) the state is the VM's link to the device: a port shut
  down inside the device may still read connected there, and the caption says *connected* rather than *up* for such
  labs. Nothing of this is stored. Without the updated helper, or for a lab that is not linked or not running, links
  are drawn from the topology file and the caption says so." Lines 63–66 ("Removed in earlier releases: …
  horizontal/vertical diagram exports …") keep their sentence and gain: "The manager's own **Rows** and **Columns**
  arrangements in *Export to draw.io…* are new and are not that removed helper-run graph; `layout=horizontal` and
  `layout=vertical` stay rejected." Add under the More ▾ paragraph: "**Download picture…** saves the map as SVG or PNG (whole map or
  the current view, with or without the background colour and the devices' state), made in the browser. **Export to
  draw.io…** offers the arrangement (as on the map, rows, columns) and a theme (manager colours, or black and white for
  printing); rows and columns arrange the file only and leave notes, boxes and groups out. **Find** above the map
  filters devices by name and dims the rest; Enter fits the view to the matches."
- `docs/ui-review-001/MAP-PARITY.md` §3 "Known gaps": the Topology view limit sentence becomes history ("Until C06
  of the parity campaign the Topology tab did not draw line arrows, rounded text backgrounds and nested group levels;
  it does since.") and row 15 gains "The Topology tab has its own **Download picture…** (SVG, PNG) since C06."
- `clab-backup-ui/NODE-FEATURES.md`: the line that says links never show live status is rewritten to point at the
  link state paragraph (the word "never" goes; "from the VM's interface listing, not from the devices" stays true).
- `docs/redesign/DESIGN-SPEC-ADDENDUM.md` (the lead): amendment L, "C06 (release X): the Topology tab's More ▾ gains
  Download picture…, Export to draw.io… and Arrange devices…; C.41's 'no new export code path' is superseded for the
  map picture (browser-only) and the draw.io dialog (the existing route with two query values). The helper-run
  horizontal/vertical graph of the old UI stays removed (`layout=horizontal|vertical` remain refused; the inventory's
  'must not reappear' line stands); the manager's own `rows`/`columns` arrangement, computed by `layout.arrange()`
  without the helper, is new and is not that feature. The Tools 'Map' card sentence becomes 'Edit map also downloads
  the map file. Download picture… and Export to draw.io… are in the Topology tab's More ▾ menu.'"; `index.html`'s
  Tools card sentence changes accordingly (S3) and is pinned in `test_page_load_ui.js`.
- `docs/redesign/inventory/docs.md:68` (S5): the "Removed (must not reappear; rejected by helper)" line keeps
  "horizontal/vertical diagram exports" and gains "(the helper-run graph; the manager's own rows/columns draw.io
  arrangement since C06 is a different feature)".
- `docs/parity-campaign/PARITY.md` rows R043, R064, R066, R067, R068, R069: status to present with the release; R070:
  "renderer half present (boxed, elbow from `viewerSettings`); editor half blocked on 0.4.0".
- `CLAUDE.md` invariants (the lead): the stroke rule is already there; add, narrowly: "`/arrange` rewrites the stored
  document's positions with the drawing and calls `layout.keep_document`, and its Undo restores the previous
  document and drawing exactly; `PUT /layout` deliberately leaves the document behind
  (`runner.map_changed_in_manager` relies on that mismatch)."

## 6. Slices, acceptance checks, the live pass

| Slice | Owner | Files (disjoint) | Size |
|---|---|---|---|
| S0 helper option | the lead or `clab-fable-specialist` (`routing-privileged-paths.md`), **after C05 S1 frees `host_operations.py`** or folded into C05's helper diff by the lead; `risk-reviewer` on the diff | `app/host_operations.py`, `tests/test_host_diagnostics.py` | S (about 25 lines of code, 60 of tests; plus the one-constant `INSPECT_FORMAT` fix if folded) |
| S1a model and export | `clab-backend-engineer` | `app/topology.py`, `app/layout.py`, `app/drawio_export.py`, `app/lab_operations.py` (**the `/drawio` query values only**, two lines the lead specifies), `tests/test_topology.py`, `tests/test_layout.py` (new), `tests/test_lab_operations.py` (the drawio tests) | M (about 150 lines of code, 200 of tests) |
| S1b privileged routes | `clab-opus-specialist` (`routing-privileged-paths.md`: `lab_operations.py` is a privileged path and `/link-state` is a helper client); `risk-reviewer` on the diff | `app/lab_operations.py` (`/arrange` and its Undo memory), `app/device_diagnostics.py` (`/link-state`, the `vm` kind tuple), `tests/test_lab_operations.py` (the arrange tests), `tests/test_device_diagnostics.py` | M (about 110 lines of code, 180 of tests); starts after S1a has landed `layout.arrange` or on a worktree stacked on it |
| S2 renderer | `clab-ui-builder` | `app/static/topology-render.js`, `app/static/style.css` (renderer rules: `.device-box`, `.link-*`, `.dimmed`, `.hover*`, chips; the clipped-menu note), `app/static/map-editor-page.js` (`MAP_ICONS`, two entries), `tests/test_topology_ui.js` | M (about 120 lines of code, 150 of tests) |
| S3 map tools | `clab-ui-builder` (a second one, after C04 S2 has landed its `topology.js` lines) | `app/static/map-tools.js` (new), `app/static/index.html`, `app/static/topology.js` (the three hooks of §3.0), `app/static/device-diagnostics.js` (the `plan.floor` in `diagPollNext` and one guarded call in `diagVisibilityChanged`), `app/static/shell.js` (one guarded call in the drawer's `close` listener), `tests/test_map_tools_ui.js` (new), `tests/test_device_diagnostics_ui.js` (the floor test), `tests/test_topology_menu_ui.js`, `tests/test_page_load_ui.js` | L (about 360 lines of code, 400 of tests) |
| S4 fixture and QA | `clab-ui-qa` | `docs/redesign/tools/fixture_manager.py`, a new `docs/parity-campaign/tools/check_c06.py` | S |
| S5 docs | `docs-auditor` | `docs/LAB-OPERATIONS.md` (the map section, the More ▾ paragraph and lines 63–66), `docs/ui-review-001/MAP-PARITY.md`, `docs/redesign/inventory/docs.md:68`, `clab-backup-ui/NODE-FEATURES.md`, `docs/parity-campaign/PARITY.md` rows | S |
| Lead | `DESIGN-SPEC-ADDENDUM.md` amendment L, `CLAUDE.md` line, release records, `?v=` for the new script, CI lists, the live pass | |

Contracts between slices: S1b → S3 is §2.2's answer shape (with `vm`) and §2.6's request, answer and status codes;
S1a → S3 is §2.7's query values; S1a → S2 is §2.4's drawing keys; S1a → S1b is `layout.arrange()`; S2 → S3 is
`data-link-ends`, `data-base`, `data-aria-base` and the class names of §3.5; S0 → S1b is §2.1. S2 and S3 can start on
the fixture with hand-written answers while S0/S1 are in flight; S3 must not start before C04 S2's `topology.js`
edits are committed (one owner per file). C05's `renderMapImpairments` (not yet built) adopts `mapWireText` and
reads interfaces from `data-capture-endpoints` when it lands; if C05's UI lands first, S3 takes over its title
handling in the hook.

Acceptance checks for `/clab-slice-verify`:

S0: `-p test_host_diagnostics.py -v`, `-p test_gateway_whitelist.py -v`, then (1) no `docker` argv appears in the
`all` path (grep the function and the fake runner's log); (2) the option whitelist is exact (the five refusals run
nothing); (3) `main()`'s dispatch list is unchanged; (4) with a fake runner that bypasses `capture`'s size limit, 513
containers with 300 rows each are cut to 512 × 256, each row has exactly the four keys, and the result's JSON is
smaller than the fake listing; (5) the binding listing runs first and a `labPath` outside the roots stops the call
before the interfaces argv (the fake runner's log has one entry).

S1a: `-p test_topology.py -v`, `-p test_layout.py -v`, `-p test_lab_operations.py -k drawio -v`, then (1)
`drawio(lab, 'map', 'manager')` equals the pre-change output for a fixture without text decorations (a golden
comparison in the test) and `horizontal`/`vertical` are still 400; (2) `arrange()` on the same input twice gives the
same output; (3) `parse_drawing` on the existing fixtures gives the same nodes and links as before plus the new
defaulted keys (no geometry moves).

S1b: `-p test_lab_operations.py -k arrange -v`, `-p test_device_diagnostics.py -k link_state -v`, then (1)
`/link-state` never returns `mac`, `mtu`, `ifindex`, `facts`, a container id or a raw helper result; (2) after
`/arrange` the stored document and the drawing agree (`annotations_for == revision(drawing)`) and every unknown key
survives byte-for-byte; (3) arrange then Undo leaves the lab dict equal to before apart from events (a deep
comparison), including `placed`, `map_written_at` and `runner.map_changed_in_manager()`; (4) `/arrange` never calls
`remote`; (5) the Undo memory is never written to the Store file (grep the saved state for the previous drawing's
revision); (6) a busy 409 leaves the Undo entry, a 412 drops it.

S2: `node --test tests/test_topology_ui.js tests/test_page_load_ui.js`, `node --check` on each script, then (1) every
stroke rule added to `style.css` contains `:not(.capture-hit)` (grep); (2) `path.capture-hit` is emitted for every
path including elbow segments and self-links; (3) no `fill`/`stroke` attribute is emitted for a value the drawing
does not define (the CSS-defaults test keeps passing); (4) the straight-link geometry tests are byte-identical in
claim; (5) `lab-builder.css` is untouched (`.lab-builder #root svg{max-width:none}` kept).

S3: `node --test tests/test_map_tools_ui.js tests/test_topology_menu_ui.js tests/test_page_load_ui.js
tests/test_shell_ui.js tests/test_device_diagnostics_ui.js`, `node --check`, `python3 deploy/verify-release.py`
(the new `?v=`), then (1) `grep -c 'document.addEventListener\|window.addEventListener' map-tools.js` is 0; (2)
`esc()` on every interpolation of a label, interface name, term or server sentence (grep the templates); (3) no
inline `style=` in the new markup; (4) the poll makes no request when the drawer is open, the tab hidden, the lab not
running or the stage not `map`; (5) `mapLinkApply` never touches `impaired` or `data-impaired-text`; (6) the arrange
flow never writes positions into the DOM itself (grep: no `transform=` written by `map-tools.js`); (7) the PNG path
builds a `data:` URL, never `blob:`; (8) the Devices `#search` value is unchanged by Find; (9) the More menu's last
item is fully visible at 390 px (fixture screenshot); (10) a focused `#map-find` survives the 4 s poll and a map
re-render (the input is static markup; `refreshMap` replaces only the SVG).

Live pass on the `parity` lab (the lead, one operator; the manager and helper rebuilt from the tree): open Topology:
five wires plain, `#map-links` reads `Links: 5 connected` (the lab has `vm` devices) within 10 s with the legend;
type `vr` in Find: `vrt` stays, four devices and the three wires not touching `vrt` dim, `1 of 5 devices matches`,
Enter fits; Escape clears. On `ceos` (SSH) `interface Ethernet1 / shutdown`: within 10 s the `xrv9k–ceos` wire turns
red dotted, the chip reads `Links: 4 connected · 1 down`, and the hover reads either `xrv9k:Gi0/0/0/1 — ceos:eth1 ·
down at both ends (dormant: one side may be shut down)` (if XRv9k's veth follows the neighbour as cEOS's did in
fact 0.4) or `… · down: ceos Ethernet1 is dormant` (if it stays up): record which, with both ends' states from the
lab-wide listing, in `evidence/c06-live.md`; `no shutdown` → back to 5 connected. **A1 check** (lead's decision 4):
on `vsw`, `set interfaces ge-0/0/0 disable` and commit; within 10 s read the chip and the listing's state for
`clab-parity-vsw eth1` and `clab-parity-vrt eth1`; `delete interfaces ge-0/0/0 disable` and commit. If `eth1` left
`up`, the `vm` wording ships for the vrnetlab kinds as written; if it changed, the lead removes
`juniper_vjunosswitch` (and any other kind proven) from the `vm` tuple and the chip reads `up` for such labs. Open
`vrt`'s panel: the chip stops changing (poll off); close it: one fetch. Download picture: SVG and PNG open in
an image viewer with the five devices and labels, no state badges by default, the cream background; with the state
option on and `ceos` shut, the red dotted wire is in the SVG. Export to draw.io rows / print: the file opens in
diagrams.net with five devices in BFS rows and black strokes. Arrange devices › Rows: the map re-renders in rows, the
caption's grid sentence goes, `GET /map-document` shows the rewritten positions and the document otherwise as it was;
Undo arrange restores the grid **and** the grid sentence (`placed` back to false, checked through `/topology`);
Edit map opens on the arranged document and its Undo is disabled (a fresh session).
No device is stopped or restarted for this pass (the stopped-neighbour case was proven on the probe lab, fact 0.4).
Record in `evidence/c06-live.md`.

## 7. Every refusal and dead end, with its wording

Dead ends removed: a link that looks the same up or down (R043); "where is device X on a forty-node map" (Find); a
link you cannot name without clicking it (hover line); a map imported from VS Code that loses its arrows, rounded notes
and nesting on the Topology tab (R066); a boxed or elbow map drawn as icons and straight lines (R070 render half); a
report that needed the editor open to get a picture (R067); a draw.io file that could only mirror the saved positions
and only in the manager's colours (R068); a lab cloned from GitHub whose devices sit in a row of eight forever unless
someone opens Edit map (R064); two code paths for titles when impairments and link state meet (decision 6).

Refusals kept: Edit map stays behind `MAP_COMMANDS` (nothing here touches the adapter or the editor page's commands);
`Remove lab` and `Start fresh` untouched; nothing uploads; no helper mode writes; an operation in progress blocks a map
save (`guard`). New refusals, each with its sentence (every one a 400/409 the UI shows verbatim):

| Refusal | Wording |
|---|---|
| `interfaces` with an option set that is neither `{node, container}` nor `{all: true}` | `Unsupported interface options.` (helper; the manager maps it to the helper-update sentence) |
| `interfaces` `all` for a lab whose binding listing names a topology outside the trusted roots | `This lab was deployed from outside the trusted lab roots. Add its project root during operations setup.` (helper, `container_of`'s sentence; nothing listed) |
| `/arrange` with both or neither of `mode` and `undo` | `Choose an arrangement or undo, not both.` |
| `/arrange` or its Undo with a stale revision, or Undo with no entry (after a restart) | 412 `The map changed since you looked at it. The map was reloaded; try again.` (`reason: 'stale'`) |
| `/arrange` on a one-device map | `Nothing to arrange: this map has one device.` |
| `/arrange` or Undo while an operation runs | 409 `Wait for the current lab operation to finish.` (the existing guard; Undo stays offered) |
| `/arrange` without a drawing | `Import a topology map first.` (existing) |
| `/drawio` with an unknown layout or theme | `Choose a supported layout.` / `Choose a supported theme.` |
| `/link-state` for an unlinked lab | 200, `available: false`, the unlinked sentence of §3.9 |
| `/link-state` on an old helper | 200, `available: false`, the helper sentence of §3.9 |
| PNG the browser cannot make | `The PNG could not be made in this browser. Download the SVG instead.` |
| PNG over 8192 px | `The map is too large for a PNG here (over 8192 px). Download the SVG.` |

## 8. Assumptions, what to attack, questions for the reviewers

Assumptions, each named so the review can refute it:

- **A1** `containerlab inspect interfaces` reports the kernel `operstate` of the container veth and nothing else;
  `dormant` on an EOS admin-shut port was observed live (fact 0.4). For the VM-in-container kinds
  (`juniper_vjunosswitch`, `juniper_vjunosevolved`, `juniper_vjunosrouter`, `juniper_vqfx`, `cisco_xrv9k`,
  `vr-xrv9k`) the veth is wired to a QEMU guest and a shutdown inside the guest very likely leaves it `up`: that is
  **not** assumed away. The design ships the `vm` wording (§3.2: `connected`, "the VM's link to the device; a port
  shut down inside the device may not show here") for those kinds and the guide promises only the container link
  (§5); the live pass's reversible `disable` on `vsw` (lead's decision 4) decides per kind whether the wording is
  kept or the kind leaves the tuple. Any value other than `up` is treated as down, so an unexpected word still
  colours the link and the hover shows the word.
- **A2** A device missing from the listing is "not running" (containerlab lists running containers only, fact 0.3), so
  its links are down; a `containerlab stop`ped device parks its link ends and the links come back on start, a Docker-
  stopped one loses them (fact 0.4 and `docs/LAB-OPERATIONS.md`); in both cases "down" is true while it is stopped.
- **A3** Per-node boxed appearance keys are not verifiable from the pinned 0.3.2 bundle (fact 0.7); boxed nodes use the
  theme until C11 (the 0.4.0 upgrade) names them. The box geometry follows upstream's `nodeBox.ts` as read on GitHub.
- **A4** `encodeURIComponent` of the serialised SVG as a `data:` URL stays well under browser URL limits for a 2000-node
  drawing (about 1 MB of markup; Chromium and Firefox accept data URLs of several MB for images); the 8192 px canvas cap
  is the common safe edge.
- **A5** `getComputedStyle` on a cloned-but-detached element returns nothing useful, so `mapPictureSvg` reads the
  styles from the **live** elements in document order and writes them onto the clone (same `querySelectorAll` order on
  both trees), **after neutralising the live map** (hover, dimming and, with state off, state and link classes
  removed, restored in `finally`, §3.6) so a report picture carries no moment's state; the test pins the pairing and
  the neutral values.
- **A6** C04 S2's `topology.js` edits (the Console menu item) land before S3; C05's `renderMapImpairments` is not built
  yet and adopts `mapWireText` (its design is amended by one sentence here).
- **A7** The `clab-io-draw` themes are out of reach by the Docker-socket invariant (fact 0.6); a manager theme named
  `nokia` would misname a different drawing, so the names are `manager` and `print`.

Attack (for `risk-reviewer`): the `all` option lists every container of a lab name the caller supplies, bound once
per call by the trusted-roots check on the lab's own listing (§2.1): is a lab whose `labPath` passes but whose
containers were joined from elsewhere possible (containerlab labels every container of a deploy with the same
`clab-topo-file`; a container re-labelled by hand is outside the threat model the per-node form already accepts)?
Does the answer carry anything the per-node form does not (container names and the four interface fields of the
same lab; no ids, pids, MACs, labels, paths)? The `/arrange` route rewrites a stored document: can it turn a
document that parsed into one that does not (it changes only `position` objects and appends `{id, position}`; it
re-parses nothing; the next map-document save re-derives the drawing from the text as today; a rewrite that throws
leaves both untouched and answers 500)? The Undo memory: one entry per lab in process memory, dropped on use, on a
stale check and on restart; can it grow (no: at most one per lab id, overwritten by the next arrange) or be read by
another lab's request (keyed by lab id, matched against that lab's revision)? Can `/arrange` be used to move the map
out from under an open editor (the editor's own save compares its revision and refuses:
`test_the_map_document_is_kept_whole` pins the 409)? The `revision` requirement: can a client skip it (no:
required, min length 1)? `/link-state` as a
poll: 10 s × every open Topology tab × one slot each: three students polling fill the three slots for 60 ms each; the
drawer's Follow poll gets a 503 at worst once and retries (C03's plan); is 10 s too eager (the default could be 15 s)?
Is anything persisted or logged (no `Store.event`, GET not audited, no `print`)? The `print` theme and `rows`
layouts drop decorations: is a dropped decoration ever a loss of data (no: the stored map is never changed by an
export)? The PNG path: `canvas.toBlob` of a cross-origin-tainted canvas throws; a `data:` SVG with no external
references does not taint (every `fill` is a colour, there is no `<image>`; assert in the test that the clone has no
`<image>`, `<use>` or `url(` reference).

Attack (for `clab-ui-reviewer`): is red-dotted-plus-words enough for a colour-blind student when C05's amber dashes sit
beside it (the patterns differ: `2 4` dots vs `7 4` dashes; the chip counts both; the hover names both)? Does "up" with
the plain stroke read as "not checked" (the chip distinguishes `n up` from `k not checked`; is a subtle `link-up`
treatment, for example a 1 px darker stroke, worth the noise)? Is a 10 s refresh slow enough to feel calm and fast
enough to be trusted after a `shutdown` (the hover line could show `checked 7 s ago`)? Does the Find field in the tool
bar crowd the 390 px layout (the bar wraps; the fixture screenshot decides)? Should Find also match the platform word
(`Junos`) as the Devices search does (`renderDeviceList` matches `n.name` and `short_name` only; parity kept)? The
arrange dialog asks for one click among three with no preview: is the Undo button enough, given the editor's layouts
show the result before saving? Is `Device state and link colours` off by default right for a troubleshooting
screenshot (the student can tick it; the default serves the report)? Does the default-grid caption nag a student who
likes the grid (it goes when the map is `placed`, which any drag in Edit map sets; a dismiss is not offered: attack)?
The Tools card sentence and the editor's buttons now describe two export places: is the wording unambiguous? The
hover line is `aria-hidden` because the wire's `aria-label` carries the text; the wire's `<title>` carries the same
clauses as its description, so a screen reader on a focused wire hears name then description, each with the clause
(accepted and stated in decision 6): confirm the repeat is tolerable in NVDA and VoiceOver on the fixture, or ask for
the clauses in the `aria-label` only.

Questions for the lead: (1) where the `INSPECT_FORMAT` fix lands (fact 0.2) and whether C03's VALIDATION should note
the two-of-five failure; (2) whether `link_state` should also gate on `containerlab ≥ 0.64` from `capabilities`
(`inspect interfaces` is 0.64+; an older containerlab answers "unknown command", the helper's exit sentence reaches
the chip and the plan stops after three errors, which is acceptable without a gate); (3) whether the addendum
amendment L is written by the lead with this chunk's release.

**Lead's decisions on the open questions:** (1) the `INSPECT_FORMAT` health fix landed with the C05 helper slice
(`524fba4`; C03-DESIGN §11 records the two-of-five live failure), so S0 is only the `{all: true}` option; (2) `link_state`
is gated on the probed `inspect interfaces` help text in `capabilities`, not on a version number, like every other
capability; (3) the lead writes addendum amendment L with this chunk's release; (4) A1 is checked in the live pass by
a reversible interface `disable` on `vsw` ge-0/0/0 (a configuration change the lead makes and reverts; the parity
rule forbids stopping a node, not configuring one).

## 9. Review answers

One row per confirmed finding of `/clab-design-review` (28 confirmed: 1 must-fix, 22 should-fix, 5 optional; 4
refuted, which need no row), in the review's order, with the lead's binding decisions applied.

| # | Finding | Answer | Where |
|---|---|---|---|
| 0 | should-fix: the `{all: true}` option skips the trusted-root binding every per-node read has | Accepted with change (lead's decision): the `all` path binds the lab once per call with one fixed `containerlab inspect --name <lab> -f json` and refuses with `container_of`'s trusted-roots sentence unless every row's `labPath` passes `self.trusted()`; the false "exposes nothing more" claim is replaced; §1 states that the option-whitelist widening is reviewed by `risk-reviewer` on the S0 diff under the campaign's standing instruction | §1.1, §2.1, §4 helper tests, §6 S0 (5), §7, §8 attack |
| 1 | should-fix: helper result shape contradicts decision 1 and is not bounded below the reader limit | Accepted (lead's decision): a reducer of its own emits only `{name, alias, state, type}`; the bound is restated as never exceeding the 4 MiB input minus the dropped fields (under `remote()`'s 3 MiB line); S0 check (4) is rewritten against a fake runner that bypasses `capture`'s size limit | §1.1, §2.1, §4, §6 S0 (4) |
| 2 | should-fix: `diagPollNext` cannot hold a 10 s base, the first success halves it | Accepted (lead's decision, with 13): `diagPollNext` gains an optional `plan.floor` (default `DIAG_INTERVAL`, drawer unchanged); the map seeds `floor: 10000`; a test in `test_device_diagnostics_ui.js` and one in `test_map_tools_ui.js` pin that two successes keep 10 s | §1.4, §4, §6 S3 files |
| 3 | should-fix: A1 has no fallback and the words promise more than the veth state shows | Accepted with change (lead's decision): the fallback wording is written now (`Links: n connected`, the hover's "the VM's link to <device>; a port shut down inside <device> may not show here", legend "down (container link)"), the answer flags the vrnetlab kinds `vm: true` (named tuple), §5 promises only the container link and names the kinds; the live pass's reversible `disable` on `vsw` settles the kind list | §3.2 (A1 paragraph), §3.9, §5, §6 live pass, §8 A1 |
| 4 | should-fix: Undo arrange does not restore `placed`, the stored document or the ownership marker | Accepted with change (lead's decision, with 21): Undo is exact on the server; `/arrange` keeps in memory, never persisted, the previous `{drawing (with placed), annotations, annotations_for, map_written_at}` keyed by the new revision; Undo posts `{undo: true, revision}` and restores exactly those with the same OSError rollback; the client `positions` mode is dropped; tests compare the lab dict before and after | §1.10, §2.6, §3.8, §4, §6 S1b (3), (5) |
| 5 | should-fix: a busy 409 removes the one-step Undo although nothing changed | Accepted (lead's decision): the stale refusal is its own 412 with `reason: 'stale'`; Undo is removed only on it and kept on the busy 409; the guard sentence is corrected to `Wait for the current lab operation to finish.` everywhere | §1.10, §2.6, §3.8, §3.9, §7, §4 |
| 6 | should-fix: wrong sentence when containerlab, not the helper, lacks `inspect interfaces` | Accepted (lead's decision): `'link_state': bool(self.help('inspect', 'interfaces'))`; `/link-state` distinguishes `reason: 'containerlab'` (capabilities present with the manager's version, flag false) with its own sentence naming 0.64 and the VM's version; row in §3.9, tests | §2.1, §2.2, §3.9, §4 |
| 7 | should-fix: the proposed `CLAUDE.md` invariant contradicts the existing `/layout` route | Accepted (lead's decision): the line is narrowed as the finding words it: `/arrange` rewrites the document with the drawing and calls `keep_document` (and its Undo restores both exactly); `PUT /layout` deliberately leaves the document behind (`runner.map_changed_in_manager`) | §5 `CLAUDE.md` bullet |
| 8 | should-fix: the rewritten drawio test drops the claim that `horizontal` and `vertical` are refused | Accepted (lead's decision): `test_drawio_layouts_and_themes` keeps `('horizontal', 'vertical')` → 400 beside `diagonal` and `neon` | §4, §6 S1a (1) |
| 9 | should-fix: S1 edits a privileged path but is staffed with `clab-backend-engineer` | Accepted (lead's decision): S1 is split; the `/arrange` (with its Undo memory) and `/link-state` parts are S1b for `clab-opus-specialist` with `risk-reviewer` on the diff; S1a keeps the model, `layout.arrange`, the exporter and the two specified `/drawio` lines | §6 table, contracts, S1a/S1b checks |
| 10 | optional: the `manager` theme is not byte-identical for maps with notes | Accepted as proposed (lead's decision): the byte-identity claim is restricted to drawings without text decorations; a note gains `rounded=1` because `roundedBackground` now defaults to the editor's true; the golden test uses such a fixture | §2.7, §4, §6 S1a (1) |
| 11 | optional: stale text about the `INSPECT_FORMAT` fix and the old-helper mapping | Accepted (lead's decision): the fold-in text is removed (the fix landed with C05's helper slice, `524fba4`); `/link-state` matches the `HTTPException` detail against `OLD_HELPER_SENTENCE` and `'Unsupported interface options.'` | §2.1, §2.2, §4 |
| 12 | **must-fix**: the link-state poll never starts again after a tab switch or a lab start | Accepted (lead's decision): `mapLinkSchedule()` is idempotent and cheap (returns when a timer is armed or a request is in flight, fetches nothing itself) and is called, guarded, at the top of `refreshMap` before the unchanged-drawing early return, which `showTab` and every 4 s render reach; test: tab away and back with the drawing unchanged, then Stopped to Running, gives exactly one fetch each | §1.4, §3.0 hook 1, §3.2 poll, §4 |
| 13 | should-fix: `diagPollNext` polls every 5 s after the first success | Accepted with 2 (lead's decision): the `plan.floor`; `device-diagnostics.js` is in S3's files; pinned in `test_map_tools_ui.js` | §1.4, §4, §6 |
| 14 | should-fix: the run condition on `labStateOf` gives wrong sentences and hides the unlinked state | Accepted (lead's decision): the condition reads `lab.deployment.status in ('Running', 'Partially running')`, never `labStateOf().key`; Unlinked (no `deployment_name`) is checked first and shown without a request; booting, in-operation and attention labs are polled; tests for a booting lab, a lab with a running operation and an unlinked lab | §1.4, §3.2, §3.9, §4 |
| 15 | should-fix: old link colours stay on screen while the chip says they are not current | Accepted (lead's decision): on "not running" and `available: false` the `link-*` classes and `data-state-text` are cleared through `mapWireText`; on stop or pause the time is written into every clause and the chip (`as of 14:02`); the 503 back-off keeps colours under "paused, retrying…"; each transition tested | §1.4, §3.2, §3.9, §4 |
| 16 | should-fix: `data-link-ends` has two incompatible shapes in C05 and C06 | Accepted (lead's decision): one contract, C06's device-only `data-link-ends="<nodeA>|<nodeB>"`; C05's matcher reads interfaces from the existing `data-capture-endpoints` JSON. The amendment to C05-DESIGN §4.3, applied by the lead: "`topologyLink` emits no `data-link-ends` of its own; `impairedWires()` reads each wire's endpoints from the existing `data-capture-endpoints` JSON (`[{node, label, interface}]`), and `renderMapImpairments` writes its clause into `data-impaired-text` and calls `mapWireText(group)` (C06 §3.0) instead of restoring titles itself; the device-only `data-link-ends` is C06's attribute for Find and hover." | §1.6, §3.5, §6 contracts |
| 17 | should-fix: `mapWireText` rewrites the wire's accessible name and drops "to" | Accepted (lead's decision): the renderer emits `data-aria-base` (today's `Capture a:if to b:if`) beside `data-base`; `mapWireText` writes `aria-label` = aria base + clauses and `title` = base + clauses; both pinned in `test_topology_menu_ui.js`; the name-plus-description repeat is accepted and stated, and the §8 question is rewritten to ask whether the repeat is tolerable | §1.6, §3.0 hook 3, §3.5, §4, §8 |
| 18 | should-fix: Escape in Find also closes the expanded map | Accepted (lead's decision): Escape on a field that holds a term clears it and calls `preventDefault()` and `stopPropagation()`; a second Escape on an empty field falls through to the expanded-map handler; harness test with the map expanded | §1.5, §3.3, §4 |
| 19 | should-fix: Find's parity claim with the Devices search is wrong | Accepted (lead's decision): Find matches the same haystack as `renderDeviceList` (`name`, `address`, `platformLabel(platform)`, plus the drawn label) for matched devices and the label alone for unmatched drawing nodes; the hint says "Name, address or platform"; the §8 sentence is corrected | §1.5, §3.3, §4 |
| 20 | should-fix: the picture inlines live computed styles, so the state-off picture still carries state, dimming and hover | Accepted (lead's decision): `mapPictureNeutral` removes hover, hover-end and dimming and, with state off, puts every device on `state-neutral` and drops `link-*`/`impaired` before the styles are read, restoring everything in `finally`; tested with the fake style reader (Ready device and dimmed device give the neutral stroke and opacity 1) | §3.6, §4, §8 A5 |
| 21 | should-fix: Undo arrange restores positions but not the lab's map state | Accepted with 4 (lead's decision): the server-side exact Undo restores `placed`, the document, `annotations_for` and `map_written_at`; test: arrange then undo leaves the lab dict equal apart from events, and the grid caption returns | §2.6, §3.8, §4, §6 S1b (3), live pass |
| 22 | should-fix: rows/columns bring back an export the redesign contract lists as "must not reappear", docs not amended | Accepted (lead's decision): amendment L states that the old helper-run horizontal/vertical graph stays removed (`layout=horizontal|vertical` refused, the inventory line stands) and that the manager's own rows/columns arrangement is new; `docs/redesign/inventory/docs.md:68` and `docs/LAB-OPERATIONS.md` lines 63–66 join S5's edits; the test keeps `horizontal`/`vertical` → 400 | §5, §6 S5, §4 |
| 23 | should-fix: when both ends read dormant the hover blames both, and the live pass expects the opposite of fact 0.4 | Accepted (lead's decision): both ends in the same non-up state are worded once, `down at both ends (dormant: one side may be shut down)`; one down end stays named; two different states are both named; the live-pass expectation is rewritten to record both ends' states (including what the vrnetlab neighbour reports) in `evidence/c06-live.md` | §3.2, §4, §6 live pass |
| 24 | should-fix: the new Tools card sentence drops the pointer to the map file download | Accepted (lead's decision): the sentence becomes "Edit map also downloads the map file. Download picture… and Export to draw.io… are in the Topology tab's More ▾ menu."; it is pinned in `test_page_load_ui.js` (no test pinned the old sentence at `08e7336`; the new one gets a pin rather than a deletion) | §5 amendment L, §4 |
| 25 | optional: Arrange gives no warning about groups and allows no-op layouts | Accepted as proposed (lead's decision): the dialog counts the groups that will no longer surround their devices; Rows and Columns are disabled with a visible reason when the drawing has no links; `#map-arrange-hint` only for two or more devices | §3.8, §3.9, §4 |
| 26 | optional: download anchors hide draw.io export errors | Accepted as proposed (lead's decision): the draw.io dialog fetches through `api()`, saves a blob named by `attachmentName`, and shows the server's sentence in its status line on failure | §3.7, §3.9, §4 |
| 27 | optional: the More ▾ menu grows against the clipping note; disabled items show no visible reason | Accepted as proposed (lead's decision): the fixture pass checks the last item at 1440, 1280, 760 and 390 with C05's chip and Clear button shown and the stage at its minimum height, S2 updates the CSS note, a failing viewport renders the menu `position: fixed` from the button's rectangle; the three new items carry `<small class="menu-reason">No map yet</small>` | §3.1, §4 fixture pass, §6 S2 files |

## 10. Verification answers (`/clab-slice-verify` on `claude/c06-int` at c733849, six workers; every acceptance check held, eight breaks)

| Finding | Answer | Where |
|---|---|---|
| High: `test_lab_operations.py` red after the merge (C05's review follow-up tests landed inside `ArrangeTests` and lost their class's helpers) | Fixed by the lead: the C05 block moved back into `NodeActionAndOptionTests`, `ArrangeTests` follows it (141 tests OK) | `tests/test_lab_operations.py` |
| Medium: the script-load race fix did not hold (the forced `refreshMap(true)` was superseded by the next plain refresh, which returned at the unchanged-key early return) | Fixed: `map-tools.js` clears `mapKey` before the forced refresh, so whichever request finishes last redraws with the hooks in place | `map-tools.js` (last line); §3.0 |
| Medium: at 390 px the More menu's last item sat under the `#map-links` chip (stage 274 px, minimum 360 px) | Fixed in `style.css` per its own note; the last item is hit at top, middle and bottom at 390×700 | §3.1 |
| Medium: one transient 409 (VM unreachable, a non-zero listing exit) turned link state off for good with no Retry | Fixed: a 409 takes the 503 path (colours kept, "paused, retrying…", three errors then Retry); only a 200 `available: false` means "colours are off here" | `map-tools.js` `mapLinkRun`; §3.9 |
| Medium: after an unavailable answer on one lab, other labs were never polled (`mapToolsReset` kept `poll.mode`) | Fixed: the reset clears `mode` | `map-tools.js` |
| Low: a double click on Undo arrange sent two requests and showed the stale sentence after a successful undo | Fixed: an in-flight guard, the button disabled while the request is out | `map-tools.js` `mapArrangeUndoRun` |
| Low: the helper's link-state output can exceed its input and the manager's 3 MiB line limit (`ensure_ascii` expands astral characters twelvefold) | Open point: real rows are ASCII and larger than the reduced ones; the design's "smaller than the input" wording is corrected to "bounded"; a byte-measured cut is the fix if it ever bites (it fails closed as a 409) | §2.1 |
| Low: the matcher matched an endpoint with an empty interface to the first row with an empty alias or port | Fixed: an empty interface never matches by alias or port; the wire stays unknown | `map-tools.js` `mapLinkEnd`; §2.3 |

## 11. Risk review answers (one `risk-reviewer` pass over the backend diff; no must-fix, three should-fix)

| Finding | Answer | Where |
|---|---|---|
| A containerlab older than 0.64 is misreported when the capabilities cache is cold (the second listing is a dict, every device `listed: false`, every wire drawn down) | Fixed: `lab_links` raises a dedicated sentence when the second listing is not a list, mapped to `available: false, reason: 'containerlab'` | `host_operations.py`, `device_diagnostics.py`; §2.1, §2.2 |
| Undo could discard a later Edit map save that left the drawing unchanged (the revision alone was compared) | Fixed: the Undo entry keeps a digest of the map state after the arrange save; a mismatch is the stale 412 | `lab_operations.py`; §2.6 |
| A lab deployed outside the trusted roots got a 409 on every poll ("stopped. Retry" that never succeeds) | Fixed: mapped to `available: false, reason: 'roots'` with the helper's sentence | `device_diagnostics.py`; §3.9 |
| Notes: the two-call window between the binding listing and the interfaces listing; the re-serialised document (`allow_nan`, lone surrogates); Undo entries of removed labs never dropped; the capabilities cache not compared with the host revision; "not running" wording when Docker itself is down | Recorded as open points; none widens a privilege | §2 |

## 12. Live pass (the parity lab through the manager rebuilt from the merged tree, 2026-10-23)

| Step | Result |
|---|---|
| `GET /api/operations/link-state` for the parity lab | `available: true`, 5 of 5 listed; `vsw eth1 (ge-0/0/0)`, `vrt eth1 (ge-0/0/0)`, `xrv9k eth2 (Gi0/0/0/1)`, `ceos eth1` all `up` |
| cEOS `interface Ethernet1` / `shutdown` over SSH | within 12 s `ceos eth1` read `dormant` (the wire is drawn down); `xrv9k eth2` stayed `up` (the XRv9k veth does not follow its neighbour); `no shutdown` → `up` again within 12 s |
| **A1 check** on vJunos-switch: `set interfaces ge-0/0/0 disable`, commit | `vsw eth1` and `vrt eth1` both stayed `up` after 12 s; the `vm` wording (`connected` instead of `up`) ships for the vrnetlab kinds as written; reverted with `delete … disable`, commit |
| `POST /arrange {mode: rows}` on the placed drawing | 200, new revision, 5 of 5 devices moved, `placed` true, `/map-document` rewritten |
| `POST /arrange {undo: true}` | 200, positions and revision back exactly; a second Undo with the old revision → 412 `stale` with the sentence |
| `GET /drawio?layout=rows&theme=print` and `layout=map&theme=manager` | 200, XML documents; `layout=bogus` → 400 "Choose a supported layout." |
| Not run live | the browser chip, Find, hover and Download picture on the live lab (covered by the fixture QA at three widths and `check_c06.py`); the link-state helper on a VM with an old containerlab |
