# UI review 001 — pickup notes

Read this, then `CHECKLIST.md`, then `git log --oneline origin/claude/ui-review-001` before doing
anything: Git and the remote are the authority for what was committed and pushed, this file is not.

## How the work is delivered

- Branch `claude/ui-review-001`, cut from `main` `21823c6` (release 1.30.1). Remote `origin` =
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

## Next

Chunk 9 = **UI-002 part 1** (Home: Deploy and Build as the two primary actions). Today: `#home` in
`index.html` has a hero with a secondary *Deploy a new lab* button (`#home-deploy` → `openDeploy()` in
`operations.js`, the VM file browser), the empty state has *Deploy a new lab*, *Build a lab visually…*
(a link to `/static/lab-builder.html`) and *Import lab files…* (`openSetup()` in `management.js`, the
upload dialog). Plan: two equal cards above the lab list on every Home (with and without labs): DEPLOY
with *Choose a lab file on the VM…* (`openDeploy`) and *Upload lab files from this computer…*
(`openSetup`), BUILD opening the builder directly; wording that says where the files are; disabled
reasons as visible text when the VM is not connected (upload and Build do not need the VM — check).
Chunk 10 = **UI-002 part 2**: lab list under a *Recent labs* tab ordered by the most recent deployment.
First find what the manager really records (`lab['deployment']`, operations history in
`state.operations` with `action` deploy/redeploy and `finished`, `lab.created`); never invent a time;
labs without one go last in a stable order (name), and say so in this file. Keep favourites, card
actions and *Continue where you left off* no more prominent than the two actions; the tab and the order
must not change on the 4 s poll. Then UI-003 (map parity): start with the capability matrix
`docs/ui-review-001/MAP-PARITY.md` from the bundled editor and `diagram-editor.js`.

## Known limits and open points

- 1.30.2 to 1.30.9 were validated against the fixture manager only; CI was green for 1.30.2 to 1.30.8 (`gh run list --branch claude/ui-review-001`).
- UI-007 C was never exercised against a real Git host: do one real save → review → upload on the dev VM when the development manager is rebuilt from this branch. The development manager running on the VM
  (`containerlab-node-manager-backup-ui-1`) is rebuilt with `sudo bash deploy/start-manager.sh
  --manager-only` (helpers must match the release); record here when that was last done: **not yet for
  this branch**.
- `docs/TOUR.md` images of Home still show the old page; they are replaced once UI-002 has settled Home.
- The successful import confirmation was not exercised in a browser (the fixture VM refuses the preview).

- Seen while fixing UI-008, not addressed: if the manager's `bind_lab` fails after the VM already retired the old registration (`destination` route), the lab keeps pointing at a registration that no longer exists. Pre-existing; needs a decision on recovery (re-register the source).

- Seen at 200 % zoom (640 CSS px), predating this work: the lab banner is drawn far too tall and the top bar brand overlaps the breadcrumb.

## Unfinished work

None. The working tree is clean after each pushed chunk.
