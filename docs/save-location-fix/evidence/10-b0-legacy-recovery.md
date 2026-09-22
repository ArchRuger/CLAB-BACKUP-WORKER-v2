# B0 — Legacy recovery — evidence

Build: `clab-backup:1.30.31` (working-tree build of `claude/save-location-fix`, image id
`d356c1d9253d`), helpers `1.30.31`, assets `?v=1.30.31`, `http://127.0.0.1:8081`. Source checkout
`git -C ~/projects/clab-manager rev-parse --short HEAD` = `6c3e8b3` (dirty: the branch's uncommitted
working tree that the image was built from). Independent QA run, real Playwright browser against the
real page, plus same-origin API and direct `curl`-equivalent requests. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`). Tool: `docs/save-location-fix/tools/b0_legacy_recovery.py`,
raw record `10-b0-legacy-recovery.json`.

Starting state: bound to `save-fix/working/latest` (the legacy prefix left by the reproduction).

## Result: PASS

| Check | Result | Evidence |
|---|---|---|
| Progress tab shows the legacy notice while bound to `save-fix/working/latest` | PASS | `steps.legacy_notice_text`: *"This lab saves to save-fix/working/latest, a folder named like a saved state, so its saves go to save-fix/working/latest/latest. To save into save-fix/working/latest again, open Change folder…, pick save-fix/working and choose Save this lab here without moving the files."* Screenshot `1x-b0-legacy-notice.png`. |
| Change folder… → `save-fix/working` (the parent) → Save this lab here WITHOUT moving files → binding becomes `save-fix/working` | PASS | Request `POST /api/labs/904a.../git/destination {"prefix":"save-fix/working","move_files":false}` → `200`, response `binding.repository.prefix` = `save-fix/working`. Confirmed independently via `/api/state` after the run: `git_binding.repository.prefix == "save-fix/working"`. Screenshots `1x-b0-confirm-dialog.png`, `1x-b0-rebound.png`. The legacy notice disappears once rebound (`legacy_notice(page) == ''`). |
| Selecting `save-fix/working/latest` itself resolves the choice to its parent | PASS | Button title: *"This is the saved state of save-fix/working. Saves go to save-fix/working/latest. This lab already saves here."* — names the resolved parent (`save-fix/working`), not the reserved child. The button came back **disabled** rather than enabled, because by this point in the same run the lab was already bound to that resolved parent (the step immediately above) — "already saves here" is itself the confirmation the resolution landed on the parent. No POST was sent for this sub-step (would have 409'd as a no-op "already saves to that folder"); this is a QA-script interpretation note, not a defect — see `note_on_check_correction` in the JSON. Screenshot `1x-b0-select-latest.png`. |
| `POST …/git/destination {"prefix":"save-fix/working/latest"}` | **400** | `{"detail": "latest, baseline and checkpoints are the folders Save progress writes inside a lab folder. Choose the folder above them: its saves go to save-fix/working/latest."}` |
| `POST …/git/destination {"prefix":"save-fix/Final/sub"}` | **409** | `{"detail": "save-fix/Final is a saved configuration (it holds manifest.json). Choose the folder above it or a folder beside it."}` |
| No page/console errors during the run | PASS | — |

## State left for B1

Lab `restore-square` is now bound to `save-fix/working` (not `.../latest`), matching B1's precondition
("Expect `snapshot_path` = `save-fix/working/latest` (the ORIGINAL snapshot folder updated in
place)"). Repository `~/labs/CLAB-MNGR-DEV-LLM`: local `main` == `origin/main` (`git_binding.revision`
unchanged by a destination-only change; no commit was made in B0, only a registration/rebind).
