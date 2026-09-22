# C3 — Apply `/save-fix/Broken` (direct manifest, no longer a legacy parent) from the Saved
versions row, all four nodes — evidence

Build: `clab-backup:1.30.31` (image `3dfc4912c163`), commit `8ea56e0`. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`), bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/c_apply.py --entry saved-versions --match Broken`, raw record
`22-c3-broken.json`. Screenshots `2x-c3-review.png`, `2x-c3-running.png`, `2x-c3-result.png`.

Starting state: all four devices on **A** (left there by C2). Note that `save-fix/Broken` in this
run is the direct-manifest folder built for section C (`docs/save-location-fix/evidence/20-c-preparation.md`)
— a different fixture from the legacy-parent `save-fix/Broken/latest` used for the B matrix; its
Saved versions caption is the exact path `save-fix/Broken` (no trailing `/latest`), confirming the
"direct manifest, not a legacy parent" distinction the review must draw correctly.

## Real browser path

Progress tab → Saved versions card → row **Broken** (caption `save-fix/Broken`) → **Apply to
running lab…**.

Review dialog: `Source: Broken · CLAB-MNGR-DEV-LLM › save-fix/Broken · saved 21 minutes ago ·
7c6fb16b92`. All four devices eligible and checked; ack ticked; **Replace configurations**.

`POST /restore` body's `source`: `{"type": "folder", "path": "/save-fix/Broken", "commit":
"7c6fb16b928b62a96461075..."}` (`7c6fb16b…`) — exact reviewed path and commit.

## Result: PASS (18/18 checks)

| Node | Job status | independent marker after | whole-config vs `save-fix/Broken` | boot identity |
|---|---|---|---|---|
| ceos | verified | **B** | missing 0 / extra 0 | unchanged (no reboot) |
| cjunosevolved | verified | **B** | missing 0 / extra 0 (root-authentication tolerated as documented) | unchanged |
| vjunos-switch | verified | **B** | missing 0 / extra 0 | unchanged |
| xrv9k | verified | **B** | missing 0 / extra 0 | unchanged |

Job `succeeded`; `pre_backup_job_id` = `b431c0ff44a548e5a306ce76a42e2a36`; `post_backup_job_id` =
`38003afff7b841ddadf6482ccae629d8`. Binding unchanged (`save-fix/working`). No page/console errors.

This row is where the `extra`-vs-`tolerated_root_authentication` scoring bug described in
`21-c2-final.md` was actually caught (a genuine `extra=0, tolerated=1` case the earlier, wrong
formula reported as `FAIL`); the fix and the honest live re-run of both C2 and C3 are recorded there.

## State left for C4

All four devices read **B**. Binding `save-fix/working`; `save-fix/Broken` tree unchanged by this
apply.
