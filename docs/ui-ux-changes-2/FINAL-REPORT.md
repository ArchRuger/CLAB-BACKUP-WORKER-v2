# UI/UX changes 2: final report

The developer's email *Ui/Ux Changes 2* (2026-10-02, nine screenshots) walked a fresh install as a student and listed
ten points of friction. This report gives, per item, the status, what changed and in which release, where the
evidence is, every decision made on the developer's behalf with its reason, and what he still has to decide. The
work is on `claude/ui-ux-changes-2` (pull request #60 to `main`, releases 1.30.52 to 1.30.57); `CHECKLIST.md`
carries the same statuses, `PICKUP.md` the state for a next session, `evidence/` the sanitised screenshots and
screens, `tools/` one live check per item.

Status words: **done, verified live** = seen working in a real browser or through the product's own API against the
installed manager on the dev VM `clab-llm-dev2`; **done, fixture only** = verified only against the fixture manager;
**partly done**; **not done**. "Not verified" sentences name what was not exercised.

## The ten items

### 1. Installer package-lock error: done, verified live (1.30.52)

The *Package lock recovery* screen, and `apt_lock.py --show` / `--wait`, add one line after the rule that nothing is
killed or deleted: right after a VM snapshot rollback or a reboot a normal restart of the VM clears the lock too,
every completed setup step is kept, run the installer again afterwards. Advice only; a test scans both scripts for
any restart, kill or delete command token. `docs/INSTALL.md` has the new screen.
Evidence: `evidence/item1/installer-lock-recovery-1.30.52.txt` is the real installer's screen on the dev VM with the
dpkg frontend lock held by a harmless process (`tools/installer_lock_repro.py`). Not verified: a real snapshot
rollback (the VM was not rebooted; the advice is text, and Ubuntu's own shutdown ordering is relied on for "lets the
running upgrade finish").
Decision: an installed VM never reaches `apt-get install` in that phase, so the reproduction removes one basic package
(`curl`, with three metapackages) for the run and reinstalls it; the tool says so and is for the dev VM only.

### 2. Default image that cannot be used: done, verified live (1.30.54)

Two read-only modes of the operations helper (`images`: the VM's image list; `image-check`: per validated reference,
on the VM or offered by its registry, `docker image inspect` / `docker manifest inspect`, nothing pulled), served by
the manager with caches and one VM question in flight. The builder's Image field lists the VM's images; a template
takes the image My labs use, else one the VM has for that kind, else the placeholder; a line under the builder's bar
says, in the background and never blocking, for each image of the draft whether it is on the VM, pullable, or found
nowhere (amber, with the way out); every *Save to the VM…*, *Start lab* and *Redeploy lab* review lists the images
with the VM's answers and calls out the one found nowhere. The independent risk review's findings were applied before
the release (strict full-match of the reference, single-flight lock, longer answer caches against a registry's pull
allowance, prompt cancellation, a broken credential helper read as "unknown", the client's text only with an unknown
answer).
Evidence: `evidence/item2/` (before: the template dialog with no status; after: the line, the list, the reviews);
`tools/check_image_availability.py` 12 of 12 on the deployed manager and on the fixture.
Decisions: the registry probe is not gated by the VM's `network` flag (that flag gates content downloads; the probe
reaches only registries a deploy would pull from; the reviewer agreed); the student still decides (nothing is refused,
the review says what will fail); `vrnetlab/cisco_xrv9k:24.3.1` is answered *not on the VM and no registry offers it*
because Docker Hub answers "denied" for that repository, which is also what a private image needing a login answers,
so the wording names both. Not verified: a private registry needing a login; a deploy that actually fails for an
absent image (the review warns; nothing was deployed with such an image); the template default taken from a VM image
rather than from My labs (unit-tested; on this VM every kind already has an image in My labs).

### 3. Image reference written exactly as typed: done, verified live (1.30.53)

Reproduced first: the editor filled `latest` into a cleared Version field at once, so a version typed afterwards was
appended to it and the YAML received `n24l/cisco_xrv9k:latest24.3.1`. Six tracked build-time patches to the pinned
editor package (`clab-backup-ui/lab-builder/patches.mjs`, applied by `build.mjs`, pinned by a bundle test and by the
build itself failing on a moved anchor) make the YAML receive exactly `<image>:<version>`.
Evidence: `evidence/item3-4/before-*.png` (1.30.52) and `after-*.png`; `tools/check_image_fields.py` 11 of 11.

### 4. No automatic "latest": done, verified live (1.30.53)

The Version field is the student's: clearing it keeps it empty, pasting or choosing another image keeps whatever
version is typed (empty stays empty), an untagged image reads as an empty version, an unknown image offers no version;
the tags this site already uses for a known image stay offered in the list, none is picked.
Decision (the empty version): an empty version writes the image alone (`image: n24l/vjunos-switch`), which Docker
reads as that image's `latest` tag at deploy time; the guide says so (`docs/LAB-BUILDER.md`).

### 5. No Apply step for labels and annotations: done, verified live (1.30.55)

In the node editor the choices one clicks (label position, label text direction, icon, the label's *Transparent* box)
apply the moment they are chosen, each one step of the editor's Undo; the Apply button appears only for the fields
one types or drags (name, kind, image, the colour pickers, the corner radius). A device template's dialog keeps Save.
Decision: the colour pickers and the corner radius keep Apply because they fire on every pixel of a drag or every
digit typed, which would flood the undo history with steps.
Evidence: `tools/check_labels.py` (20 of 20), `evidence/item5-7/01-builder-top-right.png`.

### 6. Corner label positions: done, verified live (1.30.55)

*Top left*, *Top right*, *Bottom left*, *Bottom right* join bottom, top, left and right in the editor's select and
canvas, the manager's Topology tab and preview renderer, the draw.io export and the map editor page.
What the VS Code extension does with a corner, established from the code and not by running VS Code: the extension
(0.26.3) pins `@srl-labs/clab-ui 0.3.1`, whose label normaliser, like upstream `main`, maps any unknown position to
`bottom` and never refuses the file; a map that uses a corner opens there with that label drawn below the icon.
Evidence: `evidence/item5-7/04-map-bottom-left.png`, `05-topology-tab-corner.png`; the draw.io style pairs are
unit-tested and checked live.

### 7. Edit map should use the builder's UI: done, verified live (1.30.55)

The page's *Device look…* dialog is gone. In Edit map, right-click a device and choose *Device look*: the editor's
own node editor opens with only the *Icon* and *Label & Direction* sections (the editor's view mode has no edit
entries, so a patched menu adds this one; the Basic tab's *Node Parameters* and the other tabs are hidden in map
mode), with the same immediate apply and corners as in the builder. Map mode's guarantees hold: the node editor's
`editNode` is a topology command, so the adapter turns it into a change of the map document (the former dialog's
validated merge of the six look keys) applied as one annotation-only engine step, a payload that would rename the
device is refused, the topology text is checked unchanged after every step, Undo / Redo stay the page's, nothing is
deployed.
Evidence: `evidence/item5-7/02-map-device-menu.png`, `03-map-device-look-panel.png`; `tools/check_labels.py`;
`docs/ui-review-001/tools/check_ui003.py` (row 9 rewritten) and `check_ui003b.py` clean on the fixture.
Link labels…: left as it is (its page dialog stays). Should it follow? The editor's link editor is also edit-mode only
and would need the same translation of its `editLink` command into an `edgeAnnotations` change; it is one field (the
label distance) and the dialog is not in the developer's list, so it was left alone. The developer decides.

### 8. Topology preview does not match: done, verified live (1.30.56)

Investigated first on the real product (`evidence/item8/before-*`): a lab built in the builder, saved to the VM,
opened in the editor canvas and in the preview side by side, every difference measured through the DOM. Positions,
links, groups and text followed the map file; what did not: every device was captioned *Not in this lab* and dashed
(the preview is drawn by the lab map's renderer, which treats a device without an inventory binding as "not one of
this lab's devices", and a file being looked at has no lab), the caption sat on the interface label of a downward
link and the renderer put interface labels 40 px along the wire whatever the device label did, Linux hosts carried
the router's arrows (three-glyph icon mapping), and a map uploaded from this computer never reached the preview.
Fixed: a preview mode of the renderer (no buttons, no false caption, *Not in the topology file* only for a device the
map names but the topology does not), the parse endpoint marking which devices the topology names, interface labels
moved past a device label in a wire's way (also on the Topology tab), the editor's icon names, the uploaded map
previewed. The causes are in the changelog entry.
Evidence: `evidence/item8/after-*`; `tools/check_preview.py` 10 of 10.

### 9. Hide a lab: done, verified live (1.30.52)

*Hide from Home* in the card's ⋯ dialog (and in *All lab operations…*): a flag on the lab record and nothing else; the
lab keeps its devices, backups, history, saved progress and Git binding, nothing on the VM changes, a running lab
keeps running, the 30-second discovery never puts the card back. Home says how many labs are hidden and names the two
ways back: *Choose a file on the lab VM…* › the topology › *Add to My labs* (the same lab, flag cleared) and *Manager ▾
› Labs found on the VM… › Hidden from Home › Show on Home*. Built on the favourite's settings route and the topology
browser's registration, beside the existing *Remove from this manager*.
Evidence: `evidence/item9/`; `tools/check_hide_lab.py` 17 of 17, including a discovery pass with the card staying away.
Decision: one click, no confirmation (reversible in two ways, a notice names them).

### 10. Topology travels with every backup: done, verified live (1.30.57)

Every backup that saved a configuration (on demand, scheduled, or the capture behind a Save progress) embeds the
lab's containerlab file and map beside the configurations: the files beside the deployed topology on the VM as of
the last discovery pass (within thirty seconds of the capture), else the manager's copy; the record says which, the
path, when it was read and the digests. They download in the ZIP under the lab's names and travel into every Git save
(latest, checkpoint, baseline) as manifest entries of their kind, never as devices: restore ignores them, compare
shows their changes, the Git helper counts only device entries for the removal review. Older backups and snapshots
carry none and work as before; the schema stays 2. The independent risk review's two must-fix and three should-fix
findings were applied (no read time in the manifest so an unchanged save stays unchanged; a lab name starting with a
dash gets a usable file name; a capture error never fails the backup; stale embedded files are cleared from `latest/`;
restore never needs the embedded files).
Evidence: `evidence/item10/live-run-1.30.57.txt` (the product's own API on the dev VM: publish, deploy a cEOS lab,
backup, ZIP, connect, save on the VM only, version view, destroy) and `local-commit-in-the-dev-checkout.txt`.
Limit: the manager cannot see a topology file edited on the VM after a deploy without a redeploy; what travels is the
file as it was at capture time (and the VM's annotations file, or the manager's own map when the VM has none).
Not verified: a scheduled backup live (same code path as on demand; unit-tested), a checkpoint or baseline save live
(same snapshot builder; unit-tested with the real Git helper).

## Outside the ten items

- The email ends with "Make docker commands sudo less for the clab-manager. This will prevent errors." Not done: it
  asks for a change to the security boundary (the manager has no Docker socket and no root; every host action goes
  through the forced-command account and the sudoers helpers), which this stream was told not to widen. The
  developer decides; if the errors he saw were the exited `restore-square` NOS containers or a helper version
  mismatch, those have other causes.
- The netlab stream's uncommitted 1.30.51 (the lab-bound design dialogs, passes 7 and 8) sits as a local WIP commit on
  `claude/netlab-integration` in this worktree (`git reset --soft HEAD~1` restores it; never pushed), which is why this
  stream is numbered from 1.30.52.

## Things left on the dev VM

- The lab folder `uiux2-prev-200859` (the preview tool's default lab; kept) under `/srv/containerlab-node-manager/projects`;
  the item 10 test lab `uiux2-bk-203408` was destroyed, removed from the manager and its folder deleted, its backup
  files stay under the manager's data as every removed lab's do.
- A Git registration `uiux2-tests/uiux2-bk-203408` in `/etc/clab-manager/git.json` and two local, unpushed commits
  (`6455fc6`, `386ba9c`, the item 10 proofs with the real Git helper) in `~/labs/CLAB-MNGR-DEV-LLM`, which was already
  one commit ahead of its remote before this stream.
- The exited `restore-square` NOS containers (18 GB of writable layers) filled the root filesystem together with the
  stream's rebuilds; superseded manager images and the Docker build cache were pruned, the lab's containers were left
  alone.
