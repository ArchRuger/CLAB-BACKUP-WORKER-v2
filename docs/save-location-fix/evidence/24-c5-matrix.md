# C5 — Across the matrix: nested folder, legacy parent, checkpoint, baseline (no-op), historical
commit — evidence

Build: `clab-backup:1.30.31` (image `3dfc4912c163`), commit `8ea56e0`. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`), bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/c_apply.py`, five runs, raw records `24-c5-nested.json`,
`24-c5-legacy.json`, `24-c5-checkpoint.json`, `24-c5-baseline.json`, `24-c5-history.json`.
Screenshots `2x-c5-{nested,legacy,checkpoint,baseline,history}-{review,running,result}.png`.

Every apply has a real difference except the deliberate baseline no-op (drift to B was inserted once,
before the legacy-parent row, exactly as assigned).

| # | Entry point | Source (as sent to `POST /restore`) | Starting state | Expected end state | Result |
|---|---|---|---|---|---|
| 1 | Nested folder, Save location browser: `save-fix/course/lab/reference/solution` | `{"type":"folder","path":"/save-fix/course/lab/reference/solution","commit":"7c6fb16b…"}` | C (left by C4) | **A** | PASS — real diff (C→A); 18/18 checks |
| 2 | Legacy parent: select `save-fix/Legacy` in the folder browser | `{"type":"folder","path":"/save-fix/Legacy/latest","commit":"7c6fb16b…"}` — **the manager resolved the parent to its `.../latest` child itself**, never `save-fix/Legacy` bare | drifted to B first (a real diff was needed) | **A** | PASS — real diff (B→A); 18/18 checks |
| 3 | Saved versions, checkpoint row `state-B` | `{"type":"folder","path":"/save-fix/working/checkpoints/state-B","commit":"7c6fb16b…"}` | A (left by row 2) | **B** | PASS — real diff (A→B); 18/18 checks |
| 4 | Saved versions, baseline row | `{"type":"folder","path":"/save-fix/working/baseline","commit":"7c6fb16b…"}` | B (left by row 3; baseline = the state-B checkpoint's own capture) | **B (no-op)** | PASS — `no_op: true` on all four targets, `status: verified`, whole-configuration comparison still clean; 18/18 checks |
| 5 | Full history… → commit `967f894546` ("Save restore-square progress", the state-A save) → View → **Apply to running lab…** | `{"type":"git","commit":"967f8945464abbed87ce49830f531ba200ff2e91","path":"/save-fix/working/latest"}` — **commit-pinned Git-version source**, distinct in kind from the folder sources above | B (left by row 4, unchanged by the no-op) | **A** | PASS — real diff (B→A); 18/18 checks |

Every row: all four nodes `verified`, independent `c_lib.classify()` marker matched the expected
state, `readback.py --saved` whole-configuration comparison clean (missing 0, extra 0 net of the one
documented Junos root-authentication exclusion), boot identity unchanged (no reboot), lab binding
unchanged (`save-fix/working`), no page/console errors. Pre/post-restore backup job ids recorded per
row in each raw JSON (`pre_backup_job_id`/`post_backup_job_id`), all `succeeded`.

### Notable behaviour confirmed by row 2 (legacy parent)

Selecting the *folder* `save-fix/Legacy` (which has no `manifest.json` of its own, only a `latest`
child) in the folder browser and clicking **Apply to running lab…** produced a review whose `source`
was `/save-fix/Legacy/latest`, not `/save-fix/Legacy` — the manager resolved the legacy-parent
convenience itself, exactly as the contract in `docs/save-location-fix/PICKUP.md` describes
(`gitApplySource`: `{path: dir.path + '/latest'}` for a legacy parent). The review's `Source:` line
read `Source: Legacy · CLAB-MNGR-DEV-LLM › save-fix/Legacy/latest · …`, naming the resolved path.

### A transient tooling flake, not a device or restore fault

Between rows 3 and 4, `nodecli.py`'s SSH connection to `vjunos-switch` failed twice in a row with
`Error reading SSH protocol banner` (a paramiko-level TCP hiccup, not a device state problem — the
container stayed `healthy` throughout, `docker logs` showed no restart, and the connection succeeded
on nodecli's own built-in retry a few seconds later). Recorded here rather than silently retried away:
no evidence file reflects a failed check because of it; the row was simply re-attempted after
confirming the device was healthy.

## State left for C6/C7

All four devices read **A**. Binding `save-fix/working`; local == origin.
