# Save location fix: requirement and acceptance matrix

Status words: PASS, FAIL, BLOCKED, NOT RUN. Every PASS names the build it ran on (image id or
`clab-backup:<release>`), the source commit and the evidence file under `evidence/`. Historical
evidence of earlier releases does not count.

## A. Reproduction and automated regressions

| # | Check | Status | Build / commit | Evidence |
|---|---|---|---|---|
| A1 | Live reproduction: choosing `save-fix/working/latest` nests `save-fix/working/latest/latest` (browser, payload, registry, journal, `ls-tree`) | PASS (bug reproduced) | `clab-backup:1.30.30`, source `6c3e8b3` | `evidence/00-repro-nested-latest.md`, `.json`, `00-*.png` |
| A2 | Live reproduction: `Final/manifest.json` (direct) not offered for Apply; version and preflight refuse it | PASS (bug reproduced) | `clab-backup:1.30.30`, source `6c3e8b3` | `evidence/01-repro-apply-manifest.md`, `.json`, `01-*.png` |
| A3 | Helper regressions (`test_host_git.py`): reserved names refused, any manifest folder readable, root, nested legacy folder ignored by publish | PASS, failing first on the unmodified helper | working tree of 1.30.31 | 65 tests OK (VALIDATION.md) |
| A4 | Manager regressions (`test_git_progress.py`, `test_restore.py`): 400/409 rules, exact paths, commit pinning, malformed manifest, unknown commit | PASS, failing first | working tree of 1.30.31 | 43 + 50 tests OK (VALIDATION.md) |
| A5 | Browser regressions (`test_git_places_ui.js`, `test_git_progress_ui.js`, `test_restore_ui.js`) | PASS, failing first | working tree of 1.30.31 | 209 browser tests OK; fixture sweep 98/98 ×3 viewports (VALIDATION.md) |
| A6 | Full suites, `verify-release.py`, `git diff --check`, `check-install.sh` | PASS (899 Python, 209 browser, release check, diff check; `check-install.sh` exit 2 only for the pre-existing telemetry warning, same before the change) | working tree of 1.30.31 | VALIDATION.md |

## B. Real Git and browser proof (running manager, real browser, GitHub remote)

| # | Check | Status | Build / commit | Evidence |
|---|---|---|---|---|
| B0 | Legacy recovery: notice text, rebind `save-fix/working` without moving files, selecting `.../latest` resolves to parent, `POST .../destination` 400 (reserved name) / 409 (below manifest) | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/10-b0-legacy-recovery.md`, `.json` |
| B1 | Select `working` as save location, save, review, upload; remote paths verified with Git | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/11-b1-b2-saves.md`, `.json` |
| B2 | Three more Latest saves with real changes, including after selecting the existing `latest`, a reload and a manager restart: one `working/latest`, no chain, history intact | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/11-b1-b2-saves.md`, `.json` |
| B3 | Unchanged save: no commit, no directory; cancelled review pushes nothing; completed review uploads | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/12-b3-unchanged-cancel.md`, `.json` |
| B4 | Two checkpoints, then Latest again: both checkpoints intact; baseline, compare, history, ZIP | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/13-b4-checkpoints-baseline.md`, `.json` |
| B5 | Incomplete capture and failed push: prior snapshot / local commit preserved, honest retry, no duplicate nesting | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/14-b5-faults.md`, `.json` |
| B6 | Second checkout commits `Final`, `Broken`, a deeper folder; sync through the product; discoverable without rebinding | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/15-b6-discovery.md`, `.json` |
| B7 | Apply from the folder browser, Save location's browser, Saved versions and a historical version view; exact source path and commit in review and results; reopen/refresh; keyboard; narrow viewport | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/16-b7-apply.md`, `.json`, `16-b7-restore-submit.json`, `16-b7-stale-invalid.json` |
| B8 | After applying a named state, Save again targets `working/latest`; named snapshot unchanged; another lab's binding unaffected | PASS | `clab-backup:1.30.31` (`d356c1d9253d`) / source `6c3e8b3` (dirty) | `evidence/17-b8-after-apply.md`, `.json` |

## C. Live devices, all four images (cEOS 4.35.0F, cJunosEvolved 26.2R1.7-EVO, vJunos-switch 23.2R1.14, XRv9k 24.3.1)

| # | Check | ceos | cjunosevolved | vjunos-switch | xrv9k | Evidence |
|---|---|---|---|---|---|---|
| C1 | State A captured through normal saves; `Final`, `Broken`, Latest distinguishable | PASS | PASS | PASS | PASS | `evidence/20-c-preparation.md` (`clab-backup:1.30.31` (`3dfc4912c163`) / `8ea56e0`) |
| C2 | Apply from direct `Final/manifest.json` through the UI; independent readback proves the values | PASS | PASS | PASS | PASS | `evidence/21-c2-final.md` (`clab-backup:1.30.31` (`3dfc4912c163`) / `8ea56e0`) |
| C3 | Apply from direct `Broken/manifest.json` | PASS | PASS | PASS | PASS | `evidence/22-c3-broken.md` (`clab-backup:1.30.31` (`3dfc4912c163`) / `8ea56e0`) |
| C4 | Apply from `working/latest/manifest.json` (never `latest/latest`) | PASS | PASS | PASS | PASS | `evidence/23-c4-latest.md` (`clab-backup:1.30.31` (`3dfc4912c163`) / `8ea56e0`) |
| C5 | Across the matrix: nested folder, legacy parent convenience, checkpoint/baseline, historical commit | PASS | PASS | PASS | PASS | `evidence/24-c5-*.md` (`clab-backup:1.30.31` (`3dfc4912c163`) / `8ea56e0`) |
| C6 | Pre-restore backup, management reachability, data plane, per-node status, no reboot, binding and source unchanged, follow-up backup | PASS (data plane: see `30-c6-dataplane.md`) | PASS (same) | PASS (same) | PASS (same) | `evidence/26-c6-summary.md`, `30-c6-dataplane.md` (`clab-backup:1.30.31` (`3dfc4912c163`) / `8ea56e0`) |
| C7 | Mixed four-device selection; one controlled per-node failure; recovery | PASS (three verified, xrv9k refused for a foreign pending change, `partial`, recovered) | | | | `evidence/27-c7-mixed.md` (`clab-backup:1.30.31` (`3dfc4912c163`) / `8ea56e0`) |
| C8 | Invalid source and stale review rejected before any device mutation | PASS (14/14: unknown commit 409, corrupt manifest 409, missing artifact refused, stale review applies the reviewed commit) | | | | `evidence/28-c8-rejections.md` (`clab-backup:1.30.31` (`3dfc4912c163`) / `8ea56e0`) |
