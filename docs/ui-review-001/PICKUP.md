# UI review 001 — pickup notes

Read this, then `CHECKLIST.md`, then `git log --oneline origin/claude/ui-review-001` before doing
anything: Git and the remote are the authority for what was committed and pushed, this file is not.

## How the work is delivered

- Branch `claude/ui-review-001`, cut from `main` `21823c6` (release 1.30.1). The maintainer merged it up to 1.30.9 as pull request #41 on 2026-09-20 (`main` `d588c9a`); the branch was fast-forwarded to that merge and the work continues on it, to be offered as a second pull request. Remote `origin` =
  `https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2.git`. Push with the `ArchRuger` gh account
  (`gh auth switch -u ArchRuger`), then switch back to `pruger-dev` so lab saves keep working.
- One chunk = implement → tests → browser check → `python3 deploy/set-release.py X.Y.(Z+1)` → the three
  history sections + this file + the checklist → `python3 deploy/verify-release.py` → one commit →
  push → verify the remote SHA → look at CI → next chunk. Never force-push, no tags, no releases.
- The review PDF was not on the VM; requirements come from the maintainer's written brief, which is
  summarised in `CHECKLIST.md`.

## How a chunk is validated

```bash
cd ~/projects/clab-manager/clab-backup-ui
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests
node --test tests/*.js
cd ~/projects/clab-manager
FIXTURE_DATA=<scratch dir> clab-backup-ui/.venv/bin/python docs/redesign/tools/fixture_manager.py --port 8090 &
CLAB_SHOTS=~/ui-review/review-001/chunkNN/verify-after clab-backup-ui/.venv/bin/python docs/redesign/tools/verify_after.py
clab-backup-ui/.venv/bin/python docs/ui-review-001/tools/check_uiNNN.py     # the chunk's own check
```

Stop the fixture only with `pkill -f "^[^ ]*python[^ ]* docs/redesign/tools/fixture_manager.py"` in a
command of its own. Chunk checks change fixture state; use a fresh `FIXTURE_DATA` directory per run.
Screenshots and reports: `~/ui-review/review-001/chunkNN/` on the dev VM (not in Git).

## Done

| Release | Requirement | What | Evidence |
|---|---|---|---|
| 1.30.2 | UI-001 | *Also running on the VM* moved to **Manager ▾ › Labs found on the VM…** (dialog `#vm-labs-dialog`, count line under the menu entry) | `check_ui001.py` 7/7, `verify_after.py` 95/95 ×3, `~/ui-review/review-001/chunk01/` |
| 1.30.3 | UI-005 | *Advanced options* group at the bottom of **Lab actions ▾** (`data-menu-group` / `data-menu-panel`, behaviour in `shell.js` `initMenu`) | `check_ui005.py` all passed, `verify_after.py` 95/95 ×3, `~/ui-review/review-001/chunk02/` |
| 1.30.4 | UI-004 | Explanation pane in the Save progress menu (`gitSaveHelp`, `gitSaveMenuPlacement` in `git-progress.js`) | `check_ui004.py` 74/74 at five window sizes, `verify_after.py` 95/95 ×3, `~/ui-review/review-001/chunk03/` |
| 1.30.5 | UI-007 A + B | *Git repo details*; `#git-change-folder` open on entry, fold remembered per lab (`gitFolderCollapsed`) | `check_ui007ab.py` 11/11, `verify_after.py` 96/96 ×3, `~/ui-review/review-001/chunk04/` |
| 1.30.6 | UI-007 C | Mandatory review before an upload, enforced in `app/git_progress.py` (`Retry.reviewed`) and driven by `gitReviewJob` | `check_ui007c.py` 17/17, `verify_after.py` 97/97 ×3 on fresh fixture data, python 706, `~/ui-review/review-001/chunk05/` |
| 1.30.7 | UI-008 part 1 | Planned folders kept by the manager (`git_folders`, tree `planned`, `plan: true`, `DELETE …/folders`); fixture helper made faithful | `check_ui008a.py` 17/17, `verify_after.py` 97/97 ×3, python 708, node 174, `~/ui-review/review-001/chunk06/` |
| 1.30.8 | UI-008 part 2 | Tree expansion owned by the student (`gitPlacesState.expanded`, `.git-twist`), `current` vs `selected`, focus and scroll kept | `check_ui008b.py` 21/21, `verify_after.py` 97/97 ×3, node 176, `~/ui-review/review-001/chunk07/` |
| 1.30.9 | UI-006 | Devices tab: list indent removed, one list grid with subgrid rows, aligned heading controls (CSS only) | `check_ui006.py` 89/89 at five sizes, `verify_after.py` 97/97 ×3, before/after in `~/ui-review/review-001/chunk08/` |
| 1.30.10 | UI-002 part 1 | Home `#home-start` cards (Deploy: VM file / upload; Build), `opUpload()` through the reviewed `create`, `opPublishedPath()` | `check_ui002a.py` 25/25, `verify_after.py` 97/97 ×3, node 180, `~/ui-review/review-001/chunk09/` |
| 1.30.11 | UI-002 part 2 | *Recent labs* / *All labs* tabs, `last_deployed` recorded by the manager, no Continue block, card title width | `check_ui002b.py` 20/20, `verify_after.py` 98/98 ×3, python 709, node 182, `~/ui-review/review-001/chunk10/` |
| 1.30.12 | UI-003 step A | `MAP-PARITY.md`: capability matrix from the code, approach chosen; live read-only check of 1.30.11 on the dev VM | `~/ui-review/review-001/live-1.30.11/` |
| 1.30.13 | UI-003 step B | Manager keeps the full annotations document (`lab['annotations']`, `keep_document`, `map_document`), `GET`/`PUT …/map-document` | python 711 (unit/API only, no browser) |
| 1.30.14 | UI-003 steps C + D | Adapter map mode (`mapOnly`, `MAP_COMMANDS`), `map-editor.html` / `map-editor-page.js`, Edit map wired by `map_editor`, exports and import kept | `check_ui003.py` 27/27, `verify_after.py` 98/98 ×3, node 186, python 711, bundle `--check` OK, `~/ui-review/review-001/chunk13`, `chunk14` |

## Next

**UI-003 is the only open requirement, and it is not complete.** What remains (step E of `MAP-PARITY.md`):

1. **Drive every ◐ row in a browser and save it**: extend `docs/ui-review-001/tools/check_ui003.py` (shape
   with resize/rotate/arrows, group creation and dragging a device in, copy/paste/duplicate, a generated
   layout, link label offset, link label mode, grid appearance, SVG export), each followed by save →
   reopen → compare the stored document, then flip the row to ☑.
2. **Row 8, undo / redo**: absent in the editor's view mode. Options: a page-level history of the
   annotations document (remount with an earlier text), or running the editor in edit mode with the
   whitelist and hiding the topology tools by test id. Decide after trying the first.
3. **Row 9, device look** (icon, colours, label position): upstream edits it with `editNode`. An adapter
   translation would accept `editNode` only when nothing but annotation fields differ, and write them as
   `nodeAnnotations`; view mode does not show that editor, so this depends on the decision in 2.
4. **The Topology view draws less than the editor stores** (rotation, line arrows, rounded text
   background, nested levels): extend `parse_drawing` / `topology-render.js` where cheap, document the rest.
5. **Live pass**: rebuild the development manager (`sudo bash deploy/start-manager.sh --manager-only`) at
   this release or later and open Edit map through `http://192.168.132.132:8081` on a scratch lab
   (the immutable bundle only updates with the release number). Do not edit the maintainer's course maps
   without asking.

## Known limits and open points

- Every release of this branch was validated against the fixture manager; 1.30.11 also had a read-only live pass. CI was green for 1.30.2 to 1.30.12 when this was written (`gh run list --branch claude/ui-review-001`).
- UI-007 C was never exercised against a real Git host: do one real save → review → upload on the dev VM when the development manager is rebuilt from this branch. The development manager running on the VM
  (`containerlab-node-manager-backup-ui-1`) is rebuilt with `sudo bash deploy/start-manager.sh
  --manager-only` (helpers must match the release); last done at **1.30.11 (`ae73300`) on 2026-09-20**,
  followed by a read-only live check through `http://192.168.132.132:8081` (see VALIDATION, 1.30.12).
- `docs/TOUR.md` images of Home still show the old page; they are replaced once UI-002 has settled Home.
- The successful import confirmation was not exercised in a browser (the fixture VM refuses the preview).

- Seen while fixing UI-008, not addressed: if the manager's `bind_lab` fails after the VM already retired the old registration (`destination` route), the lab keeps pointing at a registration that no longer exists. Pre-existing; needs a decision on recovery (re-register the source).

- Seen at 200 % zoom (640 CSS px), predating this work: the lab banner is drawn far too tall and the top bar brand overlaps the breadcrumb.

## Unfinished work

None. The working tree is clean after each pushed chunk.
