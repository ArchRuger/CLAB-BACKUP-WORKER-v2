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

## Next

Chunk 6 = **UI-008** (repository folder browser). Start by reproducing: create `working` under
`JunOS-TEST-2` and watch it disappear. Where to look: `app/static/git-places.js` (`gitTreeModel`,
`gitPlacesMarkup`, `gitPlacesShow`, expansion/selection state in `gitPlacesState`), `gitNewFolder` /
`gitUseFolder` in `git-progress.js`, `POST /api/git/repositories/{id}/folders` and the `/tree` route in
`app/git_progress.py`, and the helper's `browse` mode in `app/host_git.py` (ls-tree of HEAD plus the
sibling registrations as `folders`: an empty registered folder exists only as a registration until its
first save, which is the likely reason it vanishes from a tree built from committed files). The
fixture's scripted helper is in `docs/redesign/tools/fixture_manager.py`; the real helper can be
driven with real Git in `tests/test_host_git.py` (`HostGitPlacesTests`). Do not change `host_git.py`
unless the root cause is there (security-sensitive, needs a helper refresh). Then UI-006, UI-002,
UI-003 as listed at the end of `CHECKLIST.md`.

## Known limits and open points

- 1.30.2 to 1.30.6 were validated against the fixture manager only; CI was green for 1.30.2 to 1.30.5 (`gh run list --branch claude/ui-review-001`).
- UI-007 C was never exercised against a real Git host: do one real save → review → upload on the dev VM when the development manager is rebuilt from this branch. The development manager running on the VM
  (`containerlab-node-manager-backup-ui-1`) is rebuilt with `sudo bash deploy/start-manager.sh
  --manager-only` (helpers must match the release); record here when that was last done: **not yet for
  this branch**.
- `docs/TOUR.md` images of Home still show the old page; they are replaced once UI-002 has settled Home.
- The successful import confirmation was not exercised in a browser (the fixture VM refuses the preview).

## Unfinished work

None. The working tree is clean after each pushed chunk.
