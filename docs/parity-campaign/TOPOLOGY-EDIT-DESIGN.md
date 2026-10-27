# Topology editing from the Topology view (campaign 2, chunks T01 to T08)

Design for adding devices and editing links from a lab's Topology view through the embedded editor, with a
reviewed save for a deployed lab and an explicit Apply. Written by the lead on 2026-10-27 against release 1.31.6
(`e709f3d`). **Section 12 holds the review answers and the amendments; where an amendment and an earlier section
disagree, the amendment binds.** The owner's requirements are section 7 of the campaign instruction (recorded in
[CAMPAIGN-2.md](CAMPAIGN-2.md)).

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

## 12. Review answers and amendments (T02, 2026-10-27)

### 12.1 UI review (`clab-ui-reviewer`, Opus 5.5, high; 25 findings: 9 must-fix, 11 should-fix, 5 low)

| # | Severity | Finding (short) | Answer |
|---|---|---|---|
| 1 | must-fix | The post-save `/api/lab-definitions` re-registration replaces the lab's nodes and drawing with the file's, so an added-not-created device makes the lab Partially running and a removed-still-running device vanishes from Devices before Apply. | **Accepted; amendment A1.** A deployed save does not re-register. The manager re-registers a lab's definition (nodes, drawing through `keep_document`) when an `apply`, `deploy` or `redeploy` job of that lab **succeeds**, from the file on the VM, in `LabOperations` next to `record_deployment()`; the page re-registers itself only after an undeployed `revise` (today's behaviour). Acceptance 9.10 checks the lab view between save and Apply. |
| 2 | must-fix | Edit map saves the document to the manager only; Edit topology would open the VM's annotations file and the save would overwrite the manager's map with it. | **Accepted; amendment A2.** With `#lab=<id>` the builder takes the annotations from `GET /api/labs/<id>/map-document` (the manager's kept document, what Edit map and Arrange edit) and the topology text from the VM; the save writes that document beside the file, so the two agree afterwards. Without a kept document the VM file is used as today. Acceptance 9.11: Edit map work survives an Edit topology save. |
| 3 | must-fix | The page sends `deployed` only for Running / Partially running; a Stopped or Unknown lab, or one deployed after the page opened, hits the old refusal. | **Accepted; amendment A3.** The flag means "this page knows the deployed-save contract" and is sent whenever the capability offers it (`revise.deployed`); the helper decides from the containers it lists now: no container → an ordinary revise; containers in any state → the deployed-save warnings, worded by state ("3 devices keep running, 2 stay stopped, as they are"). `state` is refreshed before the request. |
| 4 | must-fix | Review changes… on the builder page would run the apply review without the lab page's safeguards (last-save line, Save first, re-check after the job). | **Accepted; amendment A4.** The builder's control is **Back to lab and review changes…**: it navigates to `/#lab=<id>&view=topology&review=apply`; the lab page opens the apply review (every safeguard) and clears the parameter. The builder never runs a lifecycle review. |
| 5 | must-fix | "Lab actions ▾ › Review changes…" does not exist. | **Accepted.** The item is **Apply topology changes…**; Review changes… is the banner's and Deployment details' button. Every sentence names the real one. |
| 6 | must-fix | The old "destroy first" texts stay. | **Accepted; amendment A6** lists each text and its replacement: `builderNotice` ("…can only be saved to the VM after the lab is destroyed") → "This lab is running: saving changes the file and the map, not the devices; applying is a separate step."; the `revise` review body's "Only possible while the lab is not deployed." → removed, the deployed sentences come from the helper's warnings; the comment at `builderSaveRefused`; LAB-BUILDER.md lines 55, 217–224, 234; `docs/LAB-OPERATIONS.md` where it repeats it. The bar gets its own line element for the lab state. |
| 7 | must-fix | After a deployed save the pill is green "Saved on the VM" and the toast says "My labs now shows…". | **Accepted; amendment A7.** While the lab is deployed and the plan has changes (or could not be checked) the pill is the warning tone **Saved on the VM · not applied**; the one toast after a deployed save is "Saved to the VM. The running lab is unchanged until you apply the changes." The "My labs now shows…" toast is for the undeployed save only. |
| 8 | must-fix | The save review warns about removed devices only, not about recreates; "file only" is untrue. | **Accepted; amendment A8.** The helper's deployed-save warnings: (a) "This lab is running. Saving replaces the topology file and the map layout; the devices are not changed." (b) the removed-devices sentence, (c) "Applying later recreates every device whose definition changed (image, kind, environment, startup configuration) and, for kinds that cannot add links live, the neighbours of a changed link: their configuration on the device is lost then. Use **Save** in the lab header first to keep it." (d) the no-dry-run sentence. Device names, not container names (#23). |
| 9 | must-fix | A native `confirm()` discards an old draft on Enter; an unchanged VM file continues a stale draft silently. | **Accepted; amendment A9.** A dialog with **Continue my draft (from <date>)** and **Start from the VM version** (default, focused), Download offered, no native confirm; a continued draft shows the date in the bar line. |
| 10 | should-fix | Placement contradicts itself. | **Accepted.** One list: owner button `#topology-edit` in the map tools beside Edit map (the two share one group, labelled by what they change); mirrors in Lab actions ▾ › Advanced options beside Edit map, and in the Tools › Map card; at 390 px the two editor buttons move into More ▾ as the C06 items do. |
| 11 | should-fix | Two editors with similar names; a third way in exists (Open in Lab Builder… / "Edit visually…"). | **Accepted.** Names by what they change: **Edit map** "positions and drawing, kept in the manager"; **Edit topology** "devices and links, saved to the lab file on the VM; applying is a separate step". The Topology-file dialog's *Open in Lab Builder…* becomes the same Edit topology entry (one name everywhere); the map editor's note gets a pointer sentence. |
| 12 | should-fix | The refusal list is short. | **Accepted.** Reasons inline at the entry: no VM file; VM not connected; helpers older than the manager; lab busy (a job running); status Unknown; the file outside the trusted roots or unreadable. Edit map's "Import a map first." stays its own. |
| 13 | should-fix | The bar line only while the plan has changes. | **Accepted.** Sentences for: plan with changes; no dry run on this containerlab; the check failed; a map-only save ("the running lab matches the file"). Each names Lab actions ▾ › Apply topology changes… where it applies. |
| 14 | should-fix | No way back after a deployed save. | **Accepted, documented path now, feature later.** The recovery copy's path is in the job result (`recovery_path`) and the guide says how an operator restores it; a reviewed "Put back the previous file" is a follow-up chunk (recorded in CAMPAIGN-2 as T09, PLANNED). |
| 15 | should-fix | Keyboard and focus unspecified. | **Accepted.** The lab-state line is a plain element (not a live region); one polite announcement after a save; focus moves to the bar's primary control after the output dialog closes; "← My labs" becomes **Back to lab** when `#lab` is set; 390 and 760 px in the fixture pass. |
| 16 | should-fix | Stored templates hide catalog kinds. | **Accepted.** Catalog kinds missing from the stored list are appended (never replacing a stored entry); a test. |
| 17 | should-fix | Catalog not loaded → rules silently skipped. | **Accepted.** The check's caption says "Interface names were not checked: the manager's catalog did not load." |
| 18 | should-fix | The capability sentence fires on every `linux` host and says "the manager can deploy". | **Accepted.** Informational, once per kind, never for `linux`: "Devices of kind X: containerlab deploys them; the manager has no backup, restore or design support for this kind." |
| 19 | should-fix | cEOS template pattern `eth{n}` vs scheme `EthernetN`. | **Accepted.** Each kind's scheme accepts the container name and the alias (`topology.PORT_RULES` plus `CONTAINER_NAME`); the templates' own patterns raise no warning (a test). |
| 20 | should-fix | Missing acceptance steps. | **Accepted.** Added as 9.10–9.21 below. |
| 21 | low | Wrong claims (pill words, Help entry, template counts, `opReviewChanges(labId)`, `supported_kinds()`). | **Corrected** by this section; the earlier text is history. Seven templates. |
| 22 | low | Undo/redo keys undocumented; no bar buttons in the builder. | **Accepted.** Undo and Redo buttons in the builder bar (edit mode: the engine's `undo`/`redo` through `dispatchCommand`, as the palette does) and the shortcut rows with their source line. |
| 23 | low | Container names and wrong counts in the helper sentence. | **Accepted** (see #8): device names from the topology, counted by state. |
| 24 | low | Drafts… › Open loses `#lab`; the ellipsis. | **Accepted.** `lab` is kept in the hash; the entry is **Edit topology…** (a page change, like Open in Lab Builder…) and Edit map stays as it is. |
| 25 | low | The old-helper fallback; `deployed:true` on a not-running lab. | **Stated** in A3: the launcher refuses mixed helpers, so the capability check is belt and braces; the flag on a lab with no container is ignored. |

### 12.2 Amendments (bind over sections 1 to 9)

- **A1 Re-registration.** A deployed save never re-registers the lab. `LabOperations.execute` re-registers the lab
  from the VM file after a successful `apply`, `deploy` or `redeploy` job (the same path as `/api/lab-definitions`:
  nodes, drawing with `keep_document`, saved settings preserved), under the store lock, with an event. The undeployed
  `revise` keeps the page's own re-registration.
- **A2 Map source.** With `#lab`, the builder's annotations come from `/api/labs/<id>/map-document` when the lab has a
  kept document, else from the VM file; the save writes them beside the file; `revise`'s `base.annotations` is then the
  hash of whatever was opened (the helper compares against the VM file: when the document came from the manager, the
  page sends `base.annotations` as the VM file's hash it read at open, so the stale check still works).
- **A3 The flag.** `deployed: true` is sent whenever `capabilities.actions.revise.deployed` is true (after a `refresh()`);
  the helper decides by the containers it lists; its warnings are worded by state and use device names.
- **A4 Apply from the builder.** `Back to lab and review changes…` → `/#lab=<id>&view=topology&review=apply`; the
  lab page opens the apply review once and drops the parameter from the hash.
- **A6 Retired texts.** As listed in #6.
- **A7 Pill and toast.** As in #7; the plan is read with `opLoadPlan(labId, true)` after the job and after the page
  opens with `#lab`.
- **A8 Helper warnings.** As in #8 (four sentences, device names, counts by state).
- **A9 Old draft dialog.** As in #9.
- **Entry and names.** As in #10 and #11; the shortcuts dialog gets the editor's undo/redo rows and the builder bar
  the two buttons (#22).

### 12.3 Acceptance additions (T07, section 9 continued)

10. Between a deployed save and Apply: the lab stays Running, the map and Devices show the running devices, the
    pending notice shows the plan; a device the file no longer defines can still be opened and backed up.
11. Edit map work (a moved device, a text) survives an Edit topology save; Arrange then Edit topology then save keeps
    the arranged positions.
12. Stopped, Partially running and Unknown labs: the save review's sentences per state; no "destroy first" anywhere.
13. A changed image on a running device shows as a recreate in the save review and in the apply review.
14. An old changed draft against a changed VM file: the dialog, both choices, nothing lost on Enter.
15. Keyboard-only pass and 390/760 px for the entry, the bar, the dialog and the review.
16. Pill and toast wording after a deployed save; no text reads as applied.
17. Apply from the builder's control lands on the lab page's review with the last-save line.
18. A device stops between review and confirm: the run is refused and the review re-opens with the new plan.
19. A browser with stored templates sees the catalog kinds appended.
20. No dry run on the VM: the sentences of #13.
21. The seven catalog templates (six kinds and `linux`) addable from the palette with their exact images.

### 12.4 Risk review (`risk-reviewer`, Opus 5.5, high; 20 findings: 5 must-fix, 10 should-fix, 5 low)

| # | Severity | Finding (short) | Answer |
|---|---|---|---|
| R1 | must-fix | Apply's reconcile lists both ends of an added link as `restarted`; on XRv9k a restart boots a fresh disk (configuration back to factory) and a vJunos-switch container cannot start a second time; the apply review shows reasons only; F7 is proven with `linux` nodes only. | **Accepted; amendment A10.** The manager annotates the plan's `restarted` and `recreated` rows with `RESTART_KNOWN_LIMITS[kind]` (and the stop limits) in the apply review and in the deployed-save review, and the apply review carries a **Back up these devices first** line (the lab header's Save, or Back up configuration) when a listed device's kind loses its configuration on restart. A live fact per kind (what reconcile does to a running vJunos-switch, vJunos-router, cJunosEvolved, XRv9k and cEOS when a link is added) is gathered in T07 before any acceptance claim; F7 is marked "proven for `linux`" until then. |
| R2 | must-fix | A deployed save re-registers at once and drops still-running devices before Apply destroys them (Devices tab, Git save, backups, terminals; Restart/Stop refused for a device not in the VM file). | **Accepted** (same as UI #1; amendment A1): re-registration after a successful Apply/deploy/redeploy only. Acceptance 9.10 proves a removed-still-running device can be opened and backed up between save and Apply. |
| R3 | must-fix | `affected` for `revise` comes from `groups.get(name)`, so a lab deployed with `--name` or found by path only binds nothing. | **Accepted; amendment A11.** For `revise` the helper's `affected` is the `running` set (name and path matches, sorted by container name), so it is in the digest; a helper test proves a lab found by path only yields a non-empty `affected` and a changed container id refuses the run. |
| R4 | must-fix | Edit topology would open and save the VM's annotations file and the re-registration replaces the manager's map without a revision check. | **Accepted** (UI #2; amendment A2, extended): the page carries the map document's `revision`; the preview compares it with the lab's current one and answers 409 "The map changed in the manager since you opened Edit topology. Reopen it; your topology changes stay in this browser." when it differs. |
| R5 | must-fix | The flag condition and the helper's idea of "deployed" differ; the unflagged refusal says "destroy". | **Accepted** (UI #3; amendment A3): the flag is sent whenever the capability offers it; the helper judges; the unflagged refusal is reworded: "This lab has running devices. Reopen the lab in the manager and save again." (never "destroy"); the tests that pin the old sentence are rewritten. |
| R6 | should-fix | The manager-side 409 adds only false refusals. | **Accepted: dropped.** |
| R7 | should-fix | The builder's save carries no `lab_id`, so `forget_plan` and the plan re-check never fire; adding it brings "Lab not found" refusals. | **Accepted; amendment A12.** The page sends `lab_id` when, after `refresh()`, the lab is still in `state.labs`; otherwise a path-only save (today's shape). §6 row 8 is decided: a removed lab saves without `lab_id`. |
| R8 | should-fix | The helper has no YAML reader; the "removed devices" sentence cannot be built there. | **Accepted; amendment A13.** The manager builds the deployed-save sentences from digested inputs only: the helper's `affected` (names, ids) and `parse_definition(text)` of the request's own text (prefix and `container_matches`), as the cPTX warnings are built; never from the Store's discovery. |
| R9 | should-fix | The option plumbing: the manager's save whitelist (`lab_operations.py:714`), `OPTION_LABELS`, the helper's bool loop. | **Accepted; amendment A14** names the three edits and the tests: `deployed` with any other action answers 400 (never a KeyError 500); a non-bool is refused by both sides. |
| R10 | should-fix | The invariant "`revise` needs an undeployed lab" changes; owner sign-off and binding wording. | **The owner's instruction of 2026-10-27 is the sign-off** ("This request authorizes the necessary scoped extension of those old topology-editing restrictions… Implement any new deployed-draft save contract explicitly, with replacement checks and review. Do not simply remove the deployed-lab guard."). The new invariant, in the reviewer's words, goes into CLAUDE.md with the release: "`revise` writes only the topology and map files, bound to the opened versions' hashes; on a lab with containers it runs only with `deployed: true` and binds every container found by name or path into the digest; it never runs a containerlab command (`argv` and `steps` empty)." Each clause is pinned by a helper test; the old unflagged-refusal test keeps its claim with the new sentence. |
| R11 | should-fix | Renames and definition changes (kind, image, env, startup-config) mean recreate at Apply; identity follows `definition_node`. | **Accepted** (with UI #8, amendment A8): the deployed-save warning lists renamed devices and devices whose definition changed, from comparing the old and new parse on the manager (A13), with "configuration not saved is lost at Apply; a renamed device is a new device to its history and logins". |
| R12 | should-fix | `/api/lab-definitions` without `deployed_name` resets `deployment_name`. | **Accepted**: A1's manager-side re-registration keeps `deployment_name`, `hidden` (R20) and the saved settings; the page's undeployed re-registration sends `deployed_name = lab.deployment_name`. |
| R13 | should-fix | `(?i)` is not a JS flag; a NOS-only scheme would warn on every `ethN`. | **Accepted** (UI #19): the catalog serves `pattern` without inline flags plus `flags: "i"`; the scheme accepts the NOS name and `ethN` and flags only the reserved `ethN` and names outside both. |
| R14 | should-fix | The catalog schema lacks `name`, `pinned`, `match`; the counts are wrong. | **Accepted**: the entry carries `template: {name, baseName, icon, env?, match, pinned}`; seven templates; the equality test covers every field. |
| R15 | should-fix | Per-kind `impairments` has no per-kind source. | **Accepted: dropped** from the entry (it is a VM-wide capability). |
| R16 | low | Binding `state` makes a file-only save fail beside a crash-looping container. | **Accepted**: for `revise` the digest binds container name and id, not state. |
| R17 | low | Acceptance proves veths only. | **Accepted**: 9.1 and 9.2 add the NOS's `show interfaces` on both ends, unchanged container ids of untouched devices, and a configuration read-back before and after Apply. |
| R18 | low | The fixture's fake helper hardcodes the old refusal; the student guide quotes the old notice. | **Accepted**: the fixture learns `deployed` (T04a); the student guide is in scope (D10, the owner reopened it on 2026-10-27). |
| R19 | low | No inline reason for a lab outside the trusted roots or deployed under another name. | **Accepted** (UI #12 list extended). |
| R20 | low | Re-registering clears *Hide from Home*. | **Accepted** (R12): `hidden` is kept. |

### 12.5 Amendments from the risk review (bind as 12.2 does)

- **A10 Plan limits.** The manager adds `limits: {<device>: <sentence>}` to the plan it shows (from `RESTART_KNOWN_LIMITS`
  and `STOP_KNOWN_LIMITS` by the device's kind in the parsed file), `opPlanMarkup` prints the sentence under the row,
  and the apply review shows "Back up these devices first: …" when any listed kind loses its configuration on a restart
  or recreate. Until the per-kind live fact exists, the sentence for the vrnetlab kinds says the restart's effect on
  the configuration is unverified on that kind.
- **A11 Binding.** `affected` for `revise` = the `running` rows (name and path), name and id in the digest.
- **A12 lab_id.** Sent when the lab still exists; `forget_plan(lab_id)` then fires; a removed lab saves by path.
- **A13 Sentences on the manager.** From `affected` and `parse_definition` of the request's text (old file and new
  text): removed, renamed and changed devices; never from discovery.
- **A14 Plumbing.** `OPTION_ACTIONS['deployed'] = ('revise',)` with `OPTION_LABELS['deployed'] = 'Save while deployed'`;
  the manager's revise whitelist admits `deployed` (bool) and `lab_id`/`map_revision` as request fields, not options;
  the helper's bool loop includes `deployed`; tests for the 400s.
- **Invariant wording** (R10) goes to CLAUDE.md with the release that ships T03.

**Verdict after the answers:** build. T03 (helper), T04a (manager: preview sentences, plan limits, re-registration
after Apply, `lab_id`, map revision, the fixture), T04b (catalog module, route, tests), T05 (adapter: undo/redo
handle), T06 (pages and checks) run in parallel on disjoint files against the contracts above; T07 gathers the
per-kind reconcile facts first, then runs the acceptance list.
