# C2 — Apply `/save-fix/Final` (direct manifest) from the folder browser, all four nodes — evidence

Build: `clab-backup:1.30.31` (image `3dfc4912c163`), commit `8ea56e0`. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`), bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/c_apply.py --entry folder --path save-fix/Final`, raw record
`21-c2-final.json` (final clean run). Screenshots `2x-c2-review.png`, `2x-c2-running.png`,
`2x-c2-result.png`.

Starting state: all four devices drifted to **B** (`lab/drift/<node>-B.cli`), independently
confirmed with `docs/save-location-fix/tools/c_lib.py classify_all()` → `B` on all four.

## Real browser path

Progress tab → Change folder… → `save-fix` → `save-fix/Final` → **Apply to running lab…** (the
folder browser's own button on a direct-manifest folder, not a Saved versions row).

Review dialog: `Source: Final state (instructor) · CLAB-MNGR-DEV-LLM › save-fix/Final · saved 19
minutes ago · 7c6fb16b92` — exact folder, 10-char commit. All four devices listed eligible and
checked; ack ticked; **Replace configurations** clicked.

`POST /restore` body's `source`: `{"type": "folder", "path": "/save-fix/Final", "commit":
"7c6fb16b928b62a96313880e43f5fb0d54bf8aef", ...}` — the exact reviewed path and commit, one leading
slash, no substitution.

## Result: PASS (18/18 checks)

| Node | Job status | `no_op` | `persistence` | independent marker after | whole-config vs `save-fix/Final` | boot identity |
|---|---|---|---|---|---|---|
| ceos | verified | false | saved | **A** | missing 0 / extra 0 | unchanged (no reboot) |
| cjunosevolved | verified | false | saved | **A** | missing 0 / extra 0 (the one documented Junos exclusion, `set system root-authentication`, reported separately as `tolerated_root_authentication: 1`, not counted against `extra`) | unchanged |
| vjunos-switch | verified | false | saved | **A** | missing 0 / extra 0 | unchanged |
| xrv9k | verified | false | saved | **A** | missing 0 / extra 0 | unchanged |

Job `succeeded`; `pre_backup_job_id` = `c7de3ee05dda4a38b993015da60de8d8`; `post_backup_job_id` =
`c99464f889ef4e819a0b2fb39833c1b5`. Binding unchanged (`save-fix/working`, no `latest/latest`).
No page/console errors.

### Two tooling bugs caught in this row's evidence script, fixed, and the live restore genuinely
### re-run each time (never papered over by re-scoring a stale result)

1. **Preflight refusal, no device touched.** The first attempt at this row refused at review with
   *"Snapshot file length or checksum did not match its manifest."* — traced to the C1 preparation's
   `git show` extraction stripping trailing newlines (`git()`'s `.strip()`) when seeding
   `save-fix/Final` out of band; fixed with a byte-exact extractor (`c_lib.git_show_raw`, no strip)
   and the four fixture folders recommitted with sha256/size verified against their own manifest
   *before* pushing (see `20-c-preparation.md`). The job never reached `applying` — confirmed no
   device was contacted before the fix.
2. **A scoring bug in this script, not the restore.** `readback.py`'s own `compare_saved` already
   nets the one documented Junos tolerance (`set system root-authentication`, which the restore
   driver may add — `docs/multi-platform-restore/README.md` "Limits that are known and accepted")
   out of its `extra` count; `tolerated_root_authentication` is reported alongside only for the
   record. An intermediate version of `c_apply.py` subtracted it a second time, which produced a
   spurious `FAIL` for `cjunosevolved` on this row and, after a first incorrect fix attempt (patching
   the recorded check without re-running), a second `FAIL` on **C3** (`extra=0, tolerated=1` →
   `-1 != 0`). Investigated with a live, ad hoc single-node re-restore of `cjunosevolved` from
   `/save-fix/Final` (`manager_restore.py`) plus a direct statement-set diff against the saved file:
   confirmed the *only* real extra statement is the documented root-authentication line — the
   restore itself was always correct. `c_apply.py` fixed to read `extra` at face value; this row and
   C3 were then **re-run live in full** (all four nodes drifted to B again, restored again through
   the real browser) for a clean, honestly reproduced result — nothing here is a patched or
   post-hoc-edited check.

## State left for C3

All four devices read **A**. Binding `save-fix/working`; `save-fix/Final` tree unchanged by this
apply (Apply only ever writes to devices).
