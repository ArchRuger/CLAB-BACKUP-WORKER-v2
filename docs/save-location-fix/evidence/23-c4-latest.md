# C4 — Apply `/save-fix/working/latest` (Saved versions "Latest" row), all four nodes — the core
regression this release fixes — evidence

Build: `clab-backup:1.30.31` (image `3dfc4912c163`), commit `8ea56e0`. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`), bound to `save-fix/working`. Tool:
`docs/save-location-fix/tools/c_apply.py --entry saved-versions --match Latest`, raw record
`23-c4-latest.json`. Screenshots `2x-c4-review.png`, `2x-c4-running.png`, `2x-c4-result.png`.

Starting state: all four devices on **B** (left there by C3). `save-fix/working/latest` currently
holds state **C** (the last real Save progress in `20-c-preparation.md`).

## Real browser path

Progress tab → Saved versions card → **Latest** group → row → **Apply to running lab…**.

Review dialog: `Source: working · CLAB-MNGR-DEV-LLM › save-fix/working/latest · saved 22 minutes ago
· 7c6fb16b92`. Saved-versions row caption: `CLAB-MNGR-DEV-LLM › save-fix/working › latest`. All four
devices eligible and checked; ack ticked; **Replace configurations**.

## The exact wire path — proven, not assumed

`POST /restore` body's `source.path` = **`/save-fix/working/latest`** — one leading slash, the lab's
own `working` prefix, a single `latest` segment. **Not** `/save-fix/working/latest/latest` and not a
bare `latest` (which the pre-fix code would have resolved through the *lab's own* binding rather than
this exact folder — see `docs/save-location-fix/PICKUP.md` "The contract", rule 6-7). This is the
manifest-based selection fix (chunk 2) proven against the real running manager and a real device
restore, not just the API/Playwright proof from the B matrix.

## Result: PASS (18/18 checks)

| Node | Job status | independent marker after | whole-config vs `save-fix/working/latest` | boot identity |
|---|---|---|---|---|
| ceos | verified | **C** | missing 0 / extra 0 | unchanged (no reboot) |
| cjunosevolved | verified | **C** | missing 0 / extra 0 (root-authentication tolerated as documented) | unchanged |
| vjunos-switch | verified | **C** | missing 0 / extra 0 | unchanged |
| xrv9k | verified | **C** | missing 0 / extra 0 | unchanged |

Job `succeeded`; `pre_backup_job_id` = `788cf5a07ae848e2a81117a9238033e7`; `post_backup_job_id` =
`53c865a6b4584e7ea5bb8d9dd05f3ece`. Binding unchanged (`save-fix/working`, no `latest/latest`
anywhere in the destination line either). No page/console errors.

## State left for C5

All four devices read **C**. Binding `save-fix/working`; `save-fix/working/latest` tree unchanged by
this apply (Apply only ever writes to devices).
