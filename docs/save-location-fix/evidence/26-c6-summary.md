# C6 — Per-node summary across every C2-C5 restore, plus a final normal backup — evidence

Build: `clab-backup:1.30.31` (image `3dfc4912c163`), commit `8ea56e0`. Lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`). Source: the `pre_backup_job_id`/`post_backup_job_id`/`status`
fields already recorded in each row's own raw JSON (`21-`…`24-c5-history.json`); nothing here was
re-derived by re-running a restore.

## Every restore job: pre-restore backup, status, no reboot, binding/source unchanged

| Row | Source | Pre-restore backup | Post-restore backup | Job status | Binding after | `save-fix/*` source tree unchanged |
|---|---|---|---|---|---|---|
| C2 | `/save-fix/Final` | `c7de3ee05dda4a38b993015da60de8d8` | `c99464f889ef4e819a0b2fb39833c1b5` | succeeded | `save-fix/working` | yes (Apply never writes to the repository) |
| C3 | `/save-fix/Broken` | `b431c0ff44a548e5a306ce76a42e2a36` | `38003afff7b841ddadf6482ccae629d8` | succeeded | `save-fix/working` | yes |
| C4 | `/save-fix/working/latest` | `788cf5a07ae848e2a81117a9238033e7` | `53c865a6b4584e7ea5bb8d9dd05f3ece` | succeeded | `save-fix/working` | yes |
| C5-nested | `/save-fix/course/lab/reference/solution` | `91ee29391c2d4c6fbcddb68f151dc7a1` | `d141b7f16d9a404987f1ccca00e15209` | succeeded | `save-fix/working` | yes |
| C5-legacy | `/save-fix/Legacy/latest` (resolved from `save-fix/Legacy`) | `d821f46fb44347c2b9462d845a936e0a` | `5355a7ebe79840a198bc52ea9f19465a` | succeeded | `save-fix/working` | yes |
| C5-checkpoint | `/save-fix/working/checkpoints/state-B` | `886e5ee1deb64afaa408474afb40ac5c` | `df608dd68156476f8ce4dbb74efa1b9b` | succeeded | `save-fix/working` | yes |
| C5-baseline (no-op) | `/save-fix/working/baseline` | `2ce9cb7c398b4599bb48f7f675709be9` | `b032261cb61b4052b62effeab2e5b1e0` | succeeded (`no_op: true` every target) | `save-fix/working` | yes |
| C5-history | Git version, commit `967f894546` | `f2fe3ba1832a4ba7b7b87ef59752f3ba` | `e1d0a7268bcf40479ac2d394ec4121f7` | succeeded | `save-fix/working` | yes |
| C7 (mixed, API-driven) | `/save-fix/Final` | `6823c16d505a406c92f1d50bc81f0494` | `4aed57143a5a4ab2b25a9b8ff61e20f6` | **partial** (3 verified, 1 correctly refused) | `save-fix/working` | yes |

Every row's pre/post backup job `status: succeeded`; every restore job (except C7, by design) ended
`succeeded`; boot identity checked unchanged (no reboot) on every C2-C5 row's four nodes
individually — see each row's own `.md`/`.json`.

## Per-node status across the whole run

| Node | Restores it went through | Final independent marker | Management reachable | Data plane |
|---|---|---|---|---|
| ceos | C2, C3, C4, C5×5, C7 (verified), C8 (stale-review, alone) | **A** | reachable every time (nodecli SSH succeeded on every row, including a self-healing retry after one transient banner-read flake before C5-baseline) | not applicable — see below |
| cjunosevolved | C2, C3, C4, C5×5, C7 (verified) | **A** | reachable every time | not applicable |
| vjunos-switch | C2, C3, C4, C5×5, C7 (verified) | **A** | reachable every time (one transient SSH banner-read flake before C5-baseline, self-healed by `nodecli.py`'s own retry within seconds; `docker inspect` showed the container `healthy` throughout, no restart) | not applicable |
| xrv9k | C2, C3, C4, C5×5, C7 (failed then recovered) | **A** | reachable every time | not applicable |

### Data plane: a documented, pre-existing gap, not a regression

`docs/multi-platform-restore/tools/square_check.py` (all edges + the loopback mesh) fails on every
node in this deployment (`0/3` or `0/0` throughout — `29-c-square-final.json`), because this
`restore-square` instance is the bare containerlab day-0 configuration (no interface addressing
anywhere), not the fully-wired OSPF mesh the multi-platform-restore acceptance built its own instance
with — established in `20-c-preparation.md` "Deployment mismatch found and worked around" and true
*before* any restore in this section ran. Management-plane reachability (an SSH session against every
node, on every row) is the reachability evidence this deployment can actually offer; the data-plane
check is recorded as a known limitation, never claimed as a pass.

## No reboot, anywhere

Every C2-C5 row's own evidence (`boot identity unchanged` checks, 4 nodes × 8 rows = 32 checks, all
`ok`) and the final `29-c-square-final.json` boot fields (`ceos` `boot_id`
`cf6042b3-484d-4495-8eea-58392edd3d05` unchanged from the deployment's own start; `cjunosevolved`
booted `2026-09-22 12:58:58`; `vjunos-switch` booted `2026-09-22 12:53:06`; `xrv9k` uptime growing
monotonically) confirm no device was ever rebooted by any restore in this section.

## Final normal backup

`manager_restore.py --backup-now` after every other row in this section: job `9aac82fd71da4cfa904fb6a77b008338`,
**`status: succeeded`**, all four nodes `succeeded`. Binding `save-fix/working`, local checkout HEAD ==
`origin/main` == `6a5dbc3d5bdb0373cbc5166644eb71b8be53afbf`.
