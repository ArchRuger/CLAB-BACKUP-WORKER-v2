# Topology editing from the Topology view (campaign 2, chunks T01 to T08)

Design for adding devices and editing links from a lab's Topology view through the embedded editor, with a
reviewed save for a deployed lab and an explicit Apply. Written by the lead on 2026-10-27 against release 1.31.6
(`e709f3d`); the review answers follow in section 12. The owner's requirements are section 7 of the campaign
instruction (recorded in [CAMPAIGN-2.md](CAMPAIGN-2.md)).

## 0. What exists and is reused (facts, with their locations)

- **F1. The builder already edits an existing lab.** `lab-builder.html#path=<vm path>` opens the lab's topology
  file and map from the VM (`builderOpenFromVm`, `lab-builder-page.js`) in the editor's `edit` mode
  (`main.tsx`: `TopologySessionCore` over a two-document store, every command of the engine including `addNode`,
  `editNode`, `deleteNode`, `addLink`, `editLink`, `deleteLink`, `batch`, `undo`, `redo`), with device templates,
  the image check and the C08 YAML check. The draft lives in the browser; opening the same file continues it.
- **F2. The save is the reviewed `revise`.** `builderSaveRequest()` sends `{action: 'revise', path, options:
  {text, annotations, base: {yaml: <sha256>, annotations: <sha256>}}}`; the manager's preview parses the text,
  refuses a changed lab name, shows the unified diff and the images; the helper (`host_operations.plan`, `revise`)
  binds the request to the opened versions' hashes, keeps a recovery copy in `.clab-manager-history`, and refuses
  a deployed lab: `'This lab is deployed. Destroy it before saving topology changes.'`. After the job the page
  posts `/api/lab-definitions` so My labs follows the saved topology.
- **F3. The apply plan exists.** `apply` is a reviewed lifecycle action whose review carries containerlab's
  `deploy --dry-run --format json` reduced to `added`, `started`, `restarted`, `recreated`, `removed`,
  `links_added`, `endpoints_removed` with reasons (`apply_plan()` in the helper, `opPlanMarkup()` in
  `operations.js`, configuration-loss notes on recreate and remove); the plan is in the review digest, so a lab
  that changed between review and run is refused. `GET /api/operations/apply-plan` is the same dry run on demand
  (C05), shown as the lab banner's pending-changes notice and in Advanced › Deployment details.
- **F4. Edit map is a separate page** (`map-editor.html`, `view` mode, `MAP_COMMANDS` whitelist) reached from the
  Topology tab (`#map-edit`, mirrored in Lab actions ▾ › Advanced options). It stays exactly as it is.
- **F5. The page `/` keeps no React, no inline styles and `script-src 'self'`**; the editor bundle is loaded by
  `lab-builder.html` and `map-editor.html` only. A bundle change reaches browsers only with a release number.
- **F6. The catalog is split today:** `BUILDER_TEMPLATES` in `lab-builder-page.js` (five kinds and `linux`, exact
  images, interface patterns), `inventory.PLATFORMS` / `DEFAULT_CREDENTIALS` / `ALIASES` / `CONSOLE_PORTS` (the
  manager's device support), `topology.PORT_RULES` (interface naming with the reserved-interface offset),
  `restore_junos.SUPPORTED_KINDS` and `design_capabilities` (the gated capabilities).
- **F7. containerlab reconciles.** `containerlab deploy` on a deployed lab creates the devices and links that are
  new in the file, recreates the ones whose definition changed, and removes the ones no longer in it (facts
  F8/F9 of C05-DESIGN; the dry run lists them).

## 1. Decisions

1. **One editor, one page.** The Topology view gets an **Edit topology…** entry that opens the lab builder on the
   lab's own file (`#path=<vm path>&lab=<id>`), the way Edit map opens the map editor. The builder page shows which
   lab it edits, a **Back to lab** link, and the lab's running state. No second editor, no React on `/`, no
   change to the engine's command set in edit mode (it is the builder's full set already). Edit map keeps its
   drawing-only contract and `MAP_COMMANDS` is not touched.
2. **The canonical catalog is served by the manager.** A new module `catalog.py` composes one list from the
   registries in F6 (kind, label, exact default image, aliases, login default present or not, interface naming
   with the reserved interfaces and the first data port, which capabilities the manager has for the kind: backup,
   restore, network design, console, impairments) and `GET /api/catalog` serves it. The builder's templates come
   from it; `BUILDER_TEMPLATES` stays as the offline fallback and a test keeps the two equal. The C08 check gets
   the catalog's interface rules (a reserved interface or a name outside the kind's scheme is a warning, never a
   refusal: the student may know better, and other kinds stay allowed). The six entries are the campaign's images
   plus `linux` (`ghcr.io/srl-labs/network-multitool`); vSRX joins through B02.
3. **A deployed lab may be saved, explicitly.** `revise` takes one new option, `deployed: true` (bool, whitelisted
   for `revise` only). Without it a deployed lab is refused as today (an old page keeps the old behaviour). With it
   the helper binds the save to the running containers it lists now (`affected`, already part of the digest: a
   device that stops, starts or disappears between review and run changes the digest and the run is refused), and
   the review says in the student's words that the file changes and the devices do not, names the running devices
   the new file no longer defines, and that Apply is a separate reviewed step. The file write is the existing
   `revise` (hash-bound, recovery copy, same-folder, trusted roots, one host lock). Nothing deploys, restarts,
   recreates or destroys from a save.
4. **Apply is the existing review.** After a deployed save the page offers **Review changes…** which runs
   `opReviewChanges(lab)`: a fresh dry run, the plan (created, started, restarted, recreated with reasons, removed,
   links to connect, link ends to disconnect, the configuration-loss notes) and the explicit confirm. For an
   undeployed lab the page offers **Back to lab**, where Start lab is the existing deploy review. On a VM whose
   containerlab has no `--dry-run` the review says the command runs without a plan (existing wording) and the save
   review adds that Apply recreates what changed; nothing destroys and redeploys silently.
5. **Three states are visible, always:** the draft in this browser (status pill: Draft, Saved on the VM, Saved with
   newer changes, Not stored), the file on the VM (the review's diff; Advanced › Deployment details), and the
   running lab (the pending-changes notice with the plan; Deployment details "Differs from the running lab"). A
   save is never shown as applied; the toast after a deployed save says the running lab is unchanged.
6. **Nothing silently drops.** The engine keeps keys it has no field for (F1, documented in LAB-BUILDER.md: a
   comment on an edited link may go, a renamed device moves to the end). The diff in the review shows every change
   including normalisation, and the YAML check's warnings name anything the manager cannot read back. A text the
   engine cannot parse is not opened (existing).

## 2. The student workflow

1. **Enter.** Topology tab › Lab actions ▾ › **Edit topology…** (and the map caption's link beside Edit map). The
   item is available when the lab has a topology file on the VM and the VM is connected; otherwise its reason is
   shown inline (the existing `data-proxy` mirror pattern, owner `#topology-edit` next to `#map-edit`). A lab
   without a VM file (imported from an inventory) keeps only the map dialog, as today. The builder opens with the
   lab's current file and map (`builderOpenFromVm`), its bar reads "Editing *name* · Back to lab", and a line under
   it says "This lab is running on the VM (5 devices). Saving changes the file; applying the changes is a separate
   step." or "This lab is not deployed." The draft that already exists for this file continues (F1).
2. **Add a device.** The palette's templates are the catalog (exact image, kind, interface pattern, icon); a custom
   template or another kind the editor's schema knows stays possible. A device of a kind the manager has no
   capabilities for carries the catalog's sentence in the YAML check ("The manager can deploy *kind* but not back
   it up, restore it or design for it"); an image not on the VM carries the image check's sentence (existing). Names
   are unique by the engine's own rule; the C08 check repeats it as an error.
3. **Links.** Add, re-point an endpoint, change the interface, delete: the editor's own interactions. The C08 check
   flags a reused interface (`link-duplicate`, existing), a missing device (`link-node`), both ends on one interface,
   and, new, a reserved interface or a name outside the kind's scheme (from the catalog: cJunosEvolved `eth1` to
   `eth3`, vJunos `ge-0/0/N` with `eth(N+1)`, XRv9k `Gi0/0/0/N`, cEOS `EthernetN`). Special endpoints (`host:`,
   `mgmt-net:`, `macvlan:`, `vxlan`, `dummy`, the long forms) stay as they are: the check knows them and the engine
   keeps them (existing).
4. **Inspect and save.** Save changes to the VM… → the review: the diff against the VM file, the images, the
   warnings, and for a running lab the deployed-save sentences (section 4). Confirm writes the file; the previous
   version is kept. The page posts `/api/lab-definitions` (existing) and, for a running lab, refreshes the plan.
5. **Deploy or apply.** Not deployed: Back to lab › Start lab (existing review). Deployed: the page's bar shows
   "Saved. The running lab differs from the file: *r3 to create · 1 link to connect*" with **Review changes…** (the
   apply review, fresh plan, explicit confirm) and the Topology tab shows the same notice (existing banner).
6. **Undo, redo, discard.** The editor's undo and redo (edit mode, existing). Discard: *Drafts…* › delete the draft,
   or *Open the VM version* in the save-problem dialog (existing); neither touches the VM.

## 3. The catalog (`catalog.py`, `GET /api/catalog`)

One entry per kind the manager manages, plus `linux`:

```
{kind, label, image, aliases: [...], login_default: bool, interfaces: {pattern, first_port, reserved: [...], scheme: <regex source>},
 capabilities: {backup, restore, design, console, impairments: bool}, template: {baseName, icon, env?}}
```

Sources: `inventory.PLATFORMS` and `DEFAULT_CREDENTIALS` (kind, label, login default), `inventory.ALIASES`
(aliases), `topology.PORT_RULES` (scheme, first port, reserved count), `restore_drivers.supported_kinds()`
(restore), `design_capabilities` (design), `inventory.CONSOLE_PORTS` (console), and the exact images pinned in one
place, `catalog.IMAGES` (moved from `BUILDER_TEMPLATES`, which keeps a copy for offline use; `test_catalog.py`
parses the JS constant and asserts equality). The route is read-only, takes no input, exposes no secret (a login
default is a boolean here; the registry stays server-side). The builder fetches it beside `known-images` and
`images` at start (5 s race, existing) and builds `builderTemplateList()` from it; stored templates keep
precedence (existing migration rules). The YAML check reads `window.builderCatalog` when present.

## 4. The deployed save (helper and manager)

Helper `plan()`, action `revise`:

- `options` whitelist gains `deployed` (bool; refused for every other action and with any other type).
- `running` is computed as today. If `running` and not `options.get('deployed') is True`: the existing refusal.
- If `running` and `deployed`: `affected` = the running rows (name, id, state) as for lifecycle actions (already
  digested); warnings:
  - "This lab is running. Saving replaces the topology file only: the 5 running devices keep running as they are.
    Apply topology changes (Lab actions ▾ › Review changes…) is the separate, reviewed step that changes the lab."
  - When the new text no longer defines a running device: "Running devices the new file does not define: X, Y.
    They keep running until Apply removes them; their unsaved configuration is lost then." The names come from
    `topology_images()`-style parsing of the new text (`parse_definition` is manager-side; the helper compares
    `rows` names against the node names it parses with its own YAML reader, as `pending_plan` does).
  - When `deploy --dry-run` is unavailable: "The installed containerlab cannot show what Apply will change."
- `revise()` (the run) is unchanged: hash-bound write, recovery copy.
- `capabilities()` reports `revise: {available: true, deployed: true}` so an old helper (no `deployed`) makes the
  page fall back to the old sentence instead of a refused option.

Manager preview, action `revise`: `options` may carry `deployed` (bool). When the lab's status in the Store is
Running or Partially running and `deployed` is absent, the manager answers 409 with the sentence that names the
flag ("This lab is running. Saving while it runs changes the file only; the page must say so and ask again." is
not shown to students: the page always sends the flag when it knows the lab runs, and the 409 protects an older
page). The pending-plan cache for the lab is cleared when the revise job succeeds (`forget_plan`, existing), so the
next banner render asks for a fresh plan.

## 5. Pages

- `lab-builder-page.js`: `#lab=<id>` beside `#path=`; the bar's lab line and Back to lab (`mapBackUrl` pattern);
  `builderSaveRequest()` adds `deployed: true` when `state.labs` says the lab is Running or Partially running and the
  capabilities say the helper takes it; after a deployed save `opLoadPlan(lab.id, true)` and a bar line with
  **Review changes…** (`opReviewChanges`, already loaded on this page) while the plan has changes; the status pill's
  words unchanged. Templates from `/api/catalog` with the fallback. The welcome text names the lab when `#lab` is set.
- `lab-builder-check.js`: the interface rules from the catalog (warnings `iface-reserved`, `iface-scheme`).
- `topology.js` / `index.html`: `#topology-edit` owner button in the map tools beside Edit map, mirrored in Lab
  actions ▾ (`data-proxy="topology-edit"`), with the reasons: no VM file, VM not connected, lab busy. Help: the
  shortcuts dialog and the Help group's Lab builder entry mention the entry (C09 wording rules).
- `map-editor-page.js`: untouched.

## 6. Concurrency and failure

| Case | Behaviour (existing unless marked new) |
|---|---|
| File edited on the VM after opening | the save is refused by the hash check; the dialog offers Open the VM version or Review the differences |
| Two browser tabs on one draft | the draft's revision token refuses the stale tab's persist; the problem overlay says so |
| Stale preview | the preview token expires in 300 s; the digest refuses a changed source, plan or container set |
| A device stops or starts between review and confirm (new case) | `affected` is in the digest: the run is refused with the existing "changed on the VM" sentence; review again |
| Manager restart during a save | the job is marked interrupted; `builderReconcile()` asks the VM whether the save landed |
| Failed save | nothing written; the draft stays; the dialog gives the reason |
| Partial Apply result | the job output lists per-device results; the banner re-checks the plan after the job (`opPlanDue` reason `job`) |
| Lab removed from the manager while the builder is open | the save still works on the VM file; `#lab` lost → the bar falls back to the file name |

## 7. Validation before execution

Client: the engine's unique names; the C08 check (`link-node`, `link-duplicate`, both-ends, special endpoints, and
the new interface rules); the image check. Manager: `parse_definition` at review (a literal topology, at least one
device, the lab name unchanged), the images list for the review's own image check. Helper: text limits, the YAML
reader of `pending_plan`, the hashes, the trusted root, the lock. containerlab itself at Apply.

## 8. After save and apply

`/api/lab-definitions` re-imports the definition and the map for the lab (existing: the device list and the
manager's map follow); discovery's next pass reconciles the containers; link state (C06) and impairments (C05)
re-read on their triggers; captures, SSH, Git save and Network Design bindings key on node names, so a renamed
device is a new device to them (documented, not changed).

## 9. Acceptance (T07)

Browser → file → runtime, on the fixture and live on `parity` (vJunos-switch, cJunosEvolved, cEOS, XRv9k, the
nested vJunos-router derivative) and `camp-vsrx`:

1. Add a `linux` host and a catalog device to the running `parity` lab from Edit topology…, connect them, save
   (deployed save: the review names the running devices and the plan warning), see the pending notice, Review
   changes…, confirm, see the devices come up, and `docker exec … ip link` shows the new veth on both ends.
2. Change a link endpoint and remove a link; save; apply; the plan lists the link ends to disconnect and the link
   to connect; afterwards `containerlab inspect interfaces` agrees.
3. Save and reload: the YAML and the annotations on the VM are the saved texts; the recovery copy exists.
4. Undo and discard: no helper call, no file change (the fixture's helper log is empty).
5. Stale revision: edit the VM file between open and save → refused, nothing written.
6. Invalid endpoint, reused interface, reserved cJunosEvolved `eth2`: the check names them; the reused interface
   is still refused by containerlab at Apply with its own line.
7. Running versus undeployed: the same draft on an undeployed lab saves without the deployed sentences and offers
   Start lab; on a running lab offers Review changes…
8. Apply failure recovery: an image that does not exist on the VM for the new device → the apply job fails, the
   other devices keep running, the banner shows the plan again, and a corrected save plus apply succeeds.
9. All six catalog entries addable from the palette with their exact image (fixture, automated).

## 10. Documentation (T08)

`docs/LAB-BUILDER.md` (Saving again: the deployed save), `docs/LAB-OPERATIONS.md` (the map and its editor:
Edit topology…; Apply), Help entries, the student guide (D10), `NODE-FEATURES.md` (the catalog), the handoff
section and CLAUDE.md's invariants ("Edit map stays drawing-only; a deployed save never deploys").

## 11. Not in this design

The editor 0.4.0 features (C11, blocked upstream); an in-page React editor on `/`; the engine's own deploy
controls; editing a lab that has no file on the VM; per-kind vendor notes (R101).

## 12. Review answers

Filled by T02.
