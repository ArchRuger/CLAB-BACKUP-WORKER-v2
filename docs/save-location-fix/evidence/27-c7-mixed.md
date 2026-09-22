# C7 — Mixed four-device restore with one controlled failure — evidence

Build: `clab-backup:1.30.31` (image `3dfc4912c163`), commit `8ea56e0`. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`), bound to `save-fix/working`. Tool:
`docs/multi-platform-restore/tools/mixed_failure.py --folder /save-fix/Final` (reused as the lead
assigned, unmodified), raw record `27-c7-mixed.json`.

**Entry point note**: this row was driven through the manager's real REST API
(`manager_restore.py`'s `Manager.call`, the same `POST .../restore/preflight` and `POST .../restore`
the browser's own review dialog sends), not by clicking through the browser page. The timing this row
needs — arming a foreign `commit confirmed` on `xrv9k` at the exact moment the job reaches its last
node, then waiting out that foreign change's own 120 s window — is what `mixed_failure.py` already
does reliably; a browser click-through of the same scenario was not attempted, and this is recorded
as a gap rather than claimed as a browser check. C2-C5's entry points were all exercised through the
real browser page; this one was not.

## What happened, live

1. All four devices drifted to **B** (`lab/drift/<node>-B.cli`), confirmed with
   `docs/save-location-fix/tools/c_lib.py classify_all()` → `B` on all four.
2. A restore from `/save-fix/Final` (state A) submitted for all four nodes.
3. While the job was `applying` its first node, a second, independent SSH session armed a foreign
   `commit confirmed 120` on `xrv9k` (the last node in the job's own order) and stayed open, never
   confirming — a real, un-related change the manager did not initiate.
4. Job ended **`partial`**: `ceos`, `cjunosevolved`, `vjunos-switch` → `verified`, `missing_statements:
   0`, `extra_statements: 0` (the product's own comparison, independent of any QA tool). `xrv9k` →
   `failed`, message: *"Configuration was not changed: Another change on this node is already pending
   confirmation; this restore was not started."* — the driver refused rather than touching a pending
   change that was not its own.
5. After the foreign change's own 120 s window elapsed (never confirmed by anyone), `xrv9k` rolled
   itself back by itself: `pending_confirmation` went `true → false`, `active` stayed `B` throughout
   (the foreign change never became visible as a lasting configuration change, and the manager never
   touched it).
6. A recovery restore of `xrv9k` alone from the same folder then `succeeded`, `verified`, `no_op:
   false` (a real change was applied, since it was still on B).

## Independent verification

`pre_backup_job_id` = `6823c16d505a406c92f1d50bc81f0494`; `post_backup_job_id` =
`4aed57143a5a4ab2b25a9b8ff61e20f6`; job id `4fd996e5804f4ccc85e5a1150bc8881c`, `status: partial`.
Binding unchanged: `GET /api/labs/<id>/git` → `binding.repository.prefix == "save-fix/working"`,
checked after the whole sequence.

`docs/save-location-fix/tools/c_lib.py classify_all()` (this task's own, deployment-correct A/B/C
marker, not `readback.py`'s canned regexes) confirms, at the very end of this row, **all four devices
read A** — the three the main job replaced and the one the recovery restore replaced afterward.

### A recorded tooling limitation, not a product defect

`mixed_failure.py`'s own printed `summary.devices_agree: false` looks like a failure but is not one:
it is computed from `readback.py`'s canned `MARKERS`, which (as established in
`20-c-preparation.md`) do not match this redeployed lab's actual configuration, so `readback.py`
reports every genuinely-A node as `"active": "mixed"` here. The product-level evidence above (the
job's own `missing_statements`/`extra_statements`/`status` fields, and this task's own
`c_lib.classify_all()` re-check) is authoritative and confirms the restore was correct throughout;
`mixed_failure.py` was reused unmodified (out of this task's file scope) rather than patched.

## Result: PASS

| Check | Result |
|---|---|
| Three of four nodes replaced and verified in the mixed job | PASS (`missing_statements: 0`, `extra_statements: 0` on all three) |
| The fourth (xrv9k) refused with its real reason, job `partial` | PASS |
| Foreign change never touched by the manager, rolled back on its own | PASS |
| Recovery restore of the failed node alone succeeded | PASS |
| Binding and repository prefix unchanged throughout | PASS |
| All four devices independently read A at the end | PASS (`c_lib.classify_all()`) |

## State left for C8

All four devices read **A**. Binding `save-fix/working`.
