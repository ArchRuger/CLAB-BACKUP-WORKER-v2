# UI/UX changes 2: pickup file

Read this first, then `CHECKLIST.md` (the ten requirements with status and release) and `FINAL-REPORT.md` once it
exists. The assignment is the developer's email *Ui/Ux Changes 2* of 2026-10-02 (nine screenshots; the `.eml` stays
outside Git in the worktree root), walked as a first-time student after a fresh install. The goal behind every item:
a first-time student is never confused, blocked or surprised by the UI.

## Branch, base, numbering

- Branch `claude/ui-ux-changes-2`, cut from `origin/main` `79f9a90` (release 1.30.50, the newest release on `main`).
  Worktree `~/projects/clab-manager-1.30.42` (the same worktree the netlab stream used; see the note below).
- Releases of this stream start at **1.30.52**, not 1.30.51: the netlab stream's uncommitted 1.30.51 (QA-021, the
  lab-bound design dialogs) was sitting in this worktree and its image `clab-backup:1.30.51` is built and was the
  running manager when this stream started. Reusing the number would have produced two different 1.30.51 trees.
  That work was cut on top of 1.30.57 as 1.30.58 on 2026-10-02 (PR #62, `docs/netlab-ui-qa/PICKUP.md`).
- The netlab stream's uncommitted work was preserved as a local WIP commit on `claude/netlab-integration` (message
  "WIP (set aside by the ui-ux-changes-2 stream): …"); it is **not pushed**. To continue that stream:
  `git checkout claude/netlab-integration && git reset --soft HEAD~1` restores the uncommitted state exactly.
- Push with the `ArchRuger` gh account (`gh auth switch --user ArchRuger`), then switch back to `pruger-dev` so lab
  saves keep pushing. Commit the intended files only (never `git add -A`: `.claude/`, the prompt files and the `.eml`
  in the worktree root stay out).

## Environment (clab-llm-dev2, 2026-10-02)

- Full dev VM: Docker 29.8.1, containerlab 0.79.0, the manager container `containerlab-node-manager-backup-ui-1`
  on the host network at `http://192.168.132.132:8081` (data `/srv/containerlab-node-manager/data`), capture stack
  `clab-manager-capture`. The manager compose file is this worktree's `clab-backup-ui/compose.yml`; rebuild with
  `sudo bash deploy/start-manager.sh --manager-only` (helpers refreshed by the launcher) or, for the image alone,
  `docker compose -f clab-backup-ui/compose.yml up -d --build`.
- NOS images on the VM: `n24l/cisco_xrv9k:24.3.1`, `n24l/ceos:4.35.0F`, `n24l/cjunosevolved:26.2R1.7-EVO`,
  `n24l/vjunos-switch:23.2R1.14`, `ghcr.io/srl-labs/network-multitool:latest`. Lab `restore-square` (four images +
  `host1`) exists with its NOS containers exited at the start of the stream; `netlab-test` and `Quick-Test` are
  in My labs, not running.
- Tooling: Python 3.12 venv `clab-backup-ui/.venv` (app requirements, httpx, Playwright 1.63 with Chromium 1243 in
  `~/.cache/ms-playwright`; headless Chromium needs `LD_LIBRARY_PATH=$HOME/.local/lib/chromium-deps`, exported by
  `~/.bashrc` for login shells only). Node 24 for the editor bundle: `~/.local/node24/bin` (system Node is 18);
  `cd clab-backup-ui/lab-builder && npm ci && node build.mjs` then `node build.mjs --check`.
- Subagent routing: user settings force `CLAUDE_CODE_SUBAGENT_MODEL=sonnet` for agents without a model of their own;
  the project agents carry theirs (`risk-reviewer` opus, `docs-auditor` sonnet, `mechanical-editor` haiku).

## Plan: release-sized chunks

| Chunk | Items | Release | Status |
|---|---|---|---|
| 0 | Orientation, workspace, baseline, plan | none | done |
| 1 | 1 (installer advice), 9 (hide a lab) | 1.30.52 | done: both verified live on the dev VM (evidence below) |
| 2 | 3, 4 (image and version written as typed; no automatic latest) | 1.30.53 | done: six tracked editor patches (`lab-builder/patches.mjs`), verified live |
| 3 | 2 (image usable on this VM: read-only helper mode, builder status) | 1.30.54 | done: helper modes risk-reviewed (findings applied), verified live |
| 4 | 5, 6, 7 (labels: no Apply step, four corners everywhere, Edit map uses the builder's own node editor) | 1.30.55 | done: six more editor patches, verified live |
| 5 | 8 (topology preview investigation and fix) | 1.30.56 | done: four causes, fixed, verified live |
| 6 | 10 (topology and annotations travel with every backup, Git save and download) | 1.30.57 | done: risk-reviewed (findings applied), verified live with the real helpers |

The order puts shared groundwork first: 3 and 4 touch the same template fields; 5, 6 and 7 share the label and
appearance code; 8 depends on how 6 is drawn.

## Evidence

- Item 1: `evidence/item1/installer-lock-recovery-1.30.52.txt` is the installer's own screen on the dev VM with the dpkg
  frontend lock held by a harmless `fcntl.lockf` process and one basic package missing (`tools/installer_lock_repro.py`,
  which removes `curl` and its three metapackages for the run and reinstalls them): the holder line, the rule, the new
  restart advice, the copyable command, choice 3 back to the menu, exit. Before: the developer's screenshot (no advice).
- Item 9: `evidence/item9/` (1440×900): `before-01-card-menu-1.30.51.png` (the ⋯ dialog without Hide), then
  `02-card-menu-hide`, `03-home-hidden` (the card gone, the note, the toast), `04-vm-labs-dialog-hidden` (*Hidden from
  Home* with Show on Home, beside the removed-and-excluded list), `07-home-after-readd` (the card back after *Add to My
  labs without starting* from the topology browser). `tools/check_hide_lab.py`: 17 of 17 checks on the deployed 1.30.52,
  including a discovery pass with the card staying away and zero console/page errors.

- Items 3 and 4: `evidence/item3-4/` (1440×900): `before-02-version-cleared-shows-latest.png` and
  `before-04-yaml-latest24.3.1.png` on 1.30.52 (`tools/check_image_fields.py`: 8 of 11 checks failed, every failure the
  developer's complaint), `after-02-version-cleared-empty.png` and `after-04-node-placed.png` on the patched bundle
  (11 of 11). Regression after the bundle change, against the fixture manager: `docs/lab-builder/tools/student_workflow.py`
  41 PASS (Linux host template), `docs/ui-review-001/tools/check_ui003.py` and `check_ui003b.py` clean.

- Item 2: `evidence/item2/` (1440×900): `before-template-dialog-1.30.52.png` (no image status anywhere), then the
  builder's image line (`01-image-line-on-vm`, `03-image-line-missing`), the Image field's list (`02-…`), the save
  review (`04-…`) and a deploy review (`05-…`) on 1.30.54. `tools/check_image_availability.py`: 12 of 12 on the
  deployed manager and on the fixture. The risk review's findings and their fixes are in the 1.30.54 VALIDATION section.

- Items 5, 6, 7: `evidence/item5-7/` (1440×900): the developer's two screenshots as the before state, then
  `01-builder-top-right` (the node editor's corner choice applied with no Apply button), `02-map-device-menu` (*Device
  look* in Edit map's device menu), `03-map-device-look-panel` (the icon and label sections only),
  `04-map-bottom-left`, `05-topology-tab-corner` (the Topology tab drawing the saved corner).
  `tools/check_labels.py`: 20 of 20 on the deployed manager; `check_ui003.py` and `check_ui003b.py` on the fixture.

- Item 8: `evidence/item8/`: `before-developer-preview.png` (the email), `before-01-editor-canvas.png` and
  `before-02-preview-dialog-1.30.55.png` (the same builder-made lab `uiux2-prev-200859` in the editor and in the preview
  on 1.30.55: every device "Not in this lab" and dashed, the caption on the downward link's interface label, router
  arrows for Linux hosts), then `after-01-preview-from-vm.png` and `after-02-preview-from-upload.png`.
  `tools/check_preview.py`: 10 of 10 on the deployed manager.

- Item 10: `evidence/item10/live-run-1.30.57.txt` (the product's own API on the dev VM: publish, deploy a cEOS lab,
  backup, ZIP, connect to the registered repository under `uiux2-tests/<lab>`, save on the VM only, version view,
  destroy) and `local-commit-in-the-dev-checkout.txt`; `tools/check_backup_topology.py` (reuses a deployed lab of the
  same name when `CLAB_LAB` names one; waits for the job queue, which the readiness monitor's own login test fills
  right after a device becomes ready).

## Exact next action

The stream is complete: every item is done and verified live (see `FINAL-REPORT.md`, which also lists what the
developer still decides: the sudo-less Docker request outside the ten items, and whether *Link labels…* should follow
item 7). A next session continues from the open points there; the VM leftovers are listed at its end. (Superseded:
chunk 6 notes below.)

Chunk 6 (item 10): the topology and annotations travel with every backup. Established by reading the code: a backup
job writes `backups/<lab>/history/<job>/<file>` and `latest/` (`runner._execute`), its job record holds per-node
outcomes (`file`, `sha256`, `restore_file`); the Git save builds `{manifest, files}` in `git_progress.captured_snapshot`
(schema 2; entries without `node` are accepted by the helper and ignored by restore, as the design export already
uses), the helper `host_git.publish` refuses files outside the manifest and counts every old `path` as a device for
the removal review; the ZIP of a backup is `main.py download()` (succeeded nodes + the decorated job as manifest.json);
the VM's files as of the last discovery pass are `discovery.sources[deployment_name]` (`vm_files.decode_bundle`:
definition and annotations bytes, paths, sha256) and the manager's own copies `lab['definition_yaml']` /
`layout.map_document(lab)`. Plan: capture the topology and annotations at backup time into the job folder with
provenance (VM file or manager copy) on the job record, carry them into Git saves as manifest entries without `node`
(`kind: topology|annotations`), into both ZIPs, keep restore ignoring them, and have the helper not count them as
devices; risk review of the helper diff. (Superseded: chunk 5 notes below.)

Chunk 5 (item 8): the topology preview. Established by reading the code: the preview is `opMapPreview` in
`operations.js`, opened from the Topology file dialog's *Preview topology* (`opEdit`, also the dialog the builder hands
over to after a save); it parses through `POST /api/operations/parse-yaml` (`parse_drawing` with the VM's
`<topology>.annotations.json` read through the helper, else the grid) and renders with `topologyMarkup(drawing)` from
`topology-render.js`; the parse endpoint never binds the drawing to a lab's inventory (`bind_drawing` runs only for a
lab's own `/topology` route), so every device is `unmatched` and gets the dashed outline and the *Not in this lab*
caption at `y=r+30`, which lands on the interface label of a downward link; an uploaded file's map (`opUpload`) is
never passed to the preview (`path` is empty) so it draws the grid. Reproduce on the real product with a builder-made lab
first (canvas vs preview, every difference listed), then fix. (Superseded: chunk 4 notes below.)

Chunk 4 (items 5, 6, 7): labels and the map editor. Established by reading the pinned package (0.3.2) and upstream
`main`: the editor's `normalizeNodeLabelPosition` (nodeStyles.ts) accepts top/right/left and draws anything else at the
bottom; `NODE_LABEL_POSITION_OPTIONS` (BasicTab.tsx) is the select's list; the node editor's `Apply` runs `handleApply` →
`editNode` (a topology command) while `onPreview` already redraws the label live; in view mode (map mode) the node editor
is read-only and `editNode` is refused by the adapter. The VS Code extension 0.26.3 pins `@srl-labs/clab-ui 0.3.1` (the
same normaliser), so a file with a corner value opens there with the label drawn at the bottom. Plan: build-time patches
for the four corner options and their styles plus auto-apply of the appearance fields; the manager's renderer, the
preview and the draw.io export learn the corners; in map mode the adapter translates `editNode` into an annotation-only
document change so the editor's own node editor replaces the Device look dialog. (Superseded: chunk 3 notes below.)

Chunk 3 (item 2): whether an image is usable on this VM. Facts established so far: the template defaults are
`BUILDER_TEMPLATES` in `lab-builder-page.js` (`vrnetlab/cisco_xrv9k:24.3.1`, `vrnetlab/juniper_vjunos-switch:23.2R1.14`,
`ceos:4.35.0F`, `cjunosevolved:26.2R1.7-EVO`), replaced per kind by the first image the topologies in My labs use
(`GET /api/operations/known-images`, `lab_operations.py`); a fresh install has no labs, so the placeholders are shown
and the guide says the manager cannot see the VM's images. The operations helper (`host_operations.py`, modes
`capabilities`/`read`/`browse`/`popular`/`preview`/`run`) runs containerlab as root; a read-only mode that lists the
VM's local images (`docker image ls --format json`, fixed argv, no client input) and, per validated reference, asks the
registry (`docker manifest inspect <ref>`, strict reference grammar, bounded timeout) is the planned addition, routed
through `lab_operations.py` with a short cache and never on the editor's critical path; `risk-reviewer` must review the
helper diff before the chunk is called done. Measured on the dev VM: `docker manifest inspect` answers in 0.2–2.3 s for
present, absent and unresolvable references (`vrnetlab/cisco_xrv9k:24.3.1` → denied/unauthorized, i.e. not on Docker Hub).
