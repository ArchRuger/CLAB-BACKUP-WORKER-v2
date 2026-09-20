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

## Next

Chunk 5 = **UI-007 C**: remove the *Let me review changes before they are uploaded* checkbox
(`#git-review-before-push` in `gitRenderRepository`, `git-progress.js`) and make the review mandatory.
Where the flag lives: `review_before_push` in `app/git_progress.py` (the binding, the job, `status =
'review_pending'` near line 420, the save route near line 696 `review = binding.get(...) and
data.push`), sent by the frontend in the binding PUT, in connect-by-URL and as `false` in the first-save
flow. To decide first: which paths are user-started (Save progress, checkpoint, baseline, first save)
and whether anything scheduled or non-interactive creates Git jobs (if it does and shares the flag, ask
the maintainer instead of guessing). A saved `false` must not bypass the review, so enforce it in the
manager, not only in the page. Update `gitSaveHelp('checkpoint')`, the save dialog's *Upload after
saving* wording, `docs/GIT-PROGRESS.md` and the tests that pin the opt-out. Then the order at the end of
`CHECKLIST.md`.

## Known limits and open points

- 1.30.2 to 1.30.5 were validated against the fixture manager only; CI was green for 1.30.2, 1.30.3 and 1.30.4 (`gh run list --branch claude/ui-review-001`). The development manager running on the VM
  (`containerlab-node-manager-backup-ui-1`) is rebuilt with `sudo bash deploy/start-manager.sh
  --manager-only` (helpers must match the release); record here when that was last done: **not yet for
  this branch**.
- `docs/TOUR.md` images of Home still show the old page; they are replaced once UI-002 has settled Home.
- The successful import confirmation was not exercised in a browser (the fixture VM refuses the preview).

## Unfinished work

None. The working tree is clean after each pushed chunk.
