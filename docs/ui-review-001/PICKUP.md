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

## Next

Chunk 3 = **UI-004** (explanations for the Save progress options: `#git-save-menu` in `index.html` is a
`<details>` with `.git-save-options`; the actions are dispatched on `data-git-action` in
`git-progress.js`; derive each text from what the action really does there and in
`app/git_progress.py`; hover **and** keyboard focus; must not clip or cover an action). Then the order
at the end of `CHECKLIST.md`.

## Known limits and open points

- 1.30.2 and 1.30.3 were validated against the fixture manager only; CI was green for 1.30.2 (run 35515090009). The development manager running on the VM
  (`containerlab-node-manager-backup-ui-1`) is rebuilt with `sudo bash deploy/start-manager.sh
  --manager-only` (helpers must match the release); record here when that was last done: **not yet for
  this branch**.
- `docs/TOUR.md` images of Home still show the old page; they are replaced once UI-002 has settled Home.
- The successful import confirmation was not exercised in a browser (the fixture VM refuses the preview).

## Unfinished work

None. The working tree is clean after each pushed chunk.
