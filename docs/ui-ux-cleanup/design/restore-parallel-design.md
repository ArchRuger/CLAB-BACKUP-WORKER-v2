# Restore concurrency investigation (E7)

Read-only analysis by the Opus reviewer (claude-opus-5-5), 2026-09-23; the lead's decisions follow the analysis.

The devices are restored one at a time because of one plain `for` loop in `RestoreService.execute`. No lock, per-device session rule or ordering rule requires it. A bounded per-node pool inside a job is safe if the job pool, the Runner, the two backups and the target `status` vocabulary stay as they are. I only read code and docs: no file edited, no test run, and nothing touched on the manager or the labs.

## 1. How a restore runs today (all in `clab-backup-ui/app/`)

**Job creation, `submit` (restore.py:424-487)**
- **Duplicate and idle check:** under the Store lock it checks for a duplicate request and calls `guard_idle` (425-433). The lock is then released.
- **Outside the lock:** it resolves the source (`resolve_source`, which calls the VM's Git helper, 201-262) and maps targets. Targets come out in name order: `sorted(candidates)` at :295. That is the only ordering; nothing orders nodes by dependency.
- **Probes:** it opens one SSH probe per node, one node after another, still outside the lock (447-457).
- **Job written:** under the lock again it re-checks the VM identity, duplicates and `guard_idle`, then appends the job with every target `status:'pending'` and `_candidates` (458-480).
- **Hand-off:** `self.pool.submit(self.execute, id)` (484). That pool is `ThreadPoolExecutor(max_workers=1)` (:115) and belongs to `RestoreService`, not to the Runner.

**`execute(job_id)` (500-596)**
1. **Preflight (511-532):** the job becomes `preflight`. Under the lock it takes a deep copy of the lab, checks the VM identity and that discovery is fresh. A node that is not running gets `ineligible` (529).
2. **Safety backup (535-551):** the job and every live target become `backing_up`. Then **one** Runner job: `runner.submit(..., source='restore-pre', node_names=live, progress_id=job_id)`. `_wait_backup` polls every 0.2 s, taking the lock only to copy the job (489-498). The Runner itself runs Ansible with `-f 5` (runner.py:294), so this backup is already parallel across nodes. `before[name]` is read from the stored file (549, 598-604).
3. **Apply: the sequential loop (556-566):**
   ```python
   for name in live:
       if self.stopping.is_set(): return
       ...
       self._apply_one(job_id, lab_id, node, creds, candidates[name], confirm_minutes, applied, before.get(name))
   ```
   Each node's `_apply_one` (610-667) runs completely, including its recovery window, before the next node is opened:
   - **Start:** target `applying` with `_token`, `_deadline` (617). The deadline is per node and starts at that node's own apply.
   - **Connect:** `_open` tries up to 3 times with a 3 s pause (374-389). If it fails: `failed`, "not changed" (627).
   - **Validate, load, arm:** `driver.apply_candidate(...)` (632) does all three inside the NOS's transaction. The driver calls `validate_candidate` itself first (restore_eos.py:131, restore_junos.py:179, restore_iosxr.py:371); the review has already checked it through `_unusable` (324-335).
     - `RestoreError`: `failed` (638).
     - `SessionLost` or any other error: whether a change was armed is unknown (armed=None).
   - **Connection handling:** the client is closed unless the driver sets `HOLDS_SESSION` and the apply succeeded (644-645).
   - **Armed:** target `confirming` with `diff_sample`, `no_op`, `_handle` (655), or `confirming` with "session lost" (648).
   - **`_settle` (669-731):** a retry loop, each pass a fresh connection through `_session` (391-398):
     - `driver.pending`; if the pending change carries our token: `driver.confirm`, then `capture`/compare (685-698).
     - Otherwise: `cleanup`, `capture`, then `applied`, `rolled_back`, `unchanged` or `uncertain` (699-710).
     - It retries every `retry_interval` (10 s) until `deadline + recovery_grace` (90 s) (726-728). On shutdown it returns `'stopping'` (728-731).
   - **Held session:** `driver.release(token)` in a `finally` (661-666).
   - **`_record_settled` (733-761):** writes `applied`, `rolled_back`, `failed` or `uncertain`, and appends to the `applied` list (740).
4. **Post-restore backup (572-582):** one Runner job over `applied`, then `_verify` (809-844) moves each `applied` target to `verified`, `verify_mismatch` or `applied_unverified`.
5. **`_finalize` (846-874):** computes the job status from the target statuses, under the lock.

**How results are written.** Everything goes through `update` (160-170) and `update_target` (172-181). Both take `store.lock` (an `RLock`, store.py:16), change the job document in place and call `store.save()`. `save()` encrypts and atomically replaces the **whole** state file (store.py:34-42). Events go through `Store.event`, also under the lock (store.py:105-110).

## 2. What a parallel design must protect

| Resource | Today | Evidence | What parallel needs |
|---|---|---|---|
| Store lock | Never held across SSH or Git I/O. Held only for dict changes, `save()` and short deep copies. | restore.py:161,173,185,425-433,458-480,503-519,590,607,770-779,799,811,847; `_scrubbed` 606-608 | Nothing structural. Each save re-encrypts the whole state, including every job's `_candidates` (full configurations). With N workers the saves queue behind one another, which caps write throughput but is still correct. |
| Job document writes | `update_target` changes one target's fields in place under the lock, so it is an atomic change of one target. `update()` and `_finalize` write job-level fields. `update()` rolls back to a snapshot taken under the same lock (163-169), which is atomic. | 160-181, 846-872 | Workers must only call `update_target(name, ...)`. Nothing may deep-copy the job, change it and write it back. `_verify` does deep-copy (811), which is fine only because it runs after all node tasks have finished. |
| `applied` list | A plain list passed by reference and appended in `_record_settled` (740). | 555, 740, 576 | Do not share it. After all node tasks finish, derive it from target statuses under the lock, in target order, so the post-backup node list is the same every run. |
| Restore job pool | `max_workers=1`: one restore job at a time across all labs. It also runs `_recheck_interrupted` (144). | 115, 484, 144 | **Keep at 1.** A second job, even on another lab, would have its pre-backup refused by the Runner's one-job rule (runner.py:158). Add a **separate** node pool. Submitting node tasks to the 1-worker pool that `execute` itself runs on would deadlock. |
| Runner | Its own 1-worker pool (runner.py:140). It refuses any job while another is queued or running (runner.py:158) and any non-restore backup while a restore is busy (runner.py:154). | runner.py:140-158 | Keep the pre- and post-backups as one Runner job each. Per-node backups would trip runner.py:158 and gain nothing: `-f 5` already parallelises them. Backup file names are under `backups/<lab>/history/<backup job id>/` (downloads.py:55-65), one folder per job, so there are no name collisions. |
| Per-device SSH | A new `paramiko.SSHClient` per `_open` / `_session`. The EOS and Junos drivers keep no module state. | 374-398 | Safe per thread. IOS XR rejecting rapid connections is a per-node limit (agent instructions 1.30.29 (5), README:46-47); parallel work across different nodes does not add connections to any one node. |
| IOS XR held session | The module-level `_HELD` dict, keyed by token. `pending()` finds our token by matching the peer `(ip, port)` (restore_iosxr.py:109-111, 520-536, 589-593). | xr-live-facts.md F4 (lines 770-782): the peer match is reliable only because at most one held session per node address exists at a time. | Still true with parallel nodes, as long as no two targets share `(address, port)`. Add a submit-time check that refuses, or runs one after another, targets with the same endpoint. Guard `_HELD` with a `threading.Lock` in the driver (a small security-reviewed change); the GIL alone is not a contract. |
| Operation guard | `operation_busy` is lab-scoped and uses `RESTORE_BUSY` at job level (lab_operations.py:28-39). `guard_idle` also blocks on any running backup (193-194). | | Unchanged. It is about jobs, not nodes. |
| Restart recovery | `__init__` turns a busy job into `interrupted`: targets in `IN_FLIGHT = ('applying','confirming')` are queued for read-back; `backing_up`, `pending`, `ready` and `preflight` become "interrupted before change". `start()` runs `_recheck_interrupted` on the 1-worker pool, one node after another. `rechecks[job]` counts down and the last one finalizes. | 52, 120-146, 763-807 | **Any new target status would fall through both lists** and stay non-final forever. So either keep the `status` vocabulary exactly as it is (recommended, §4), or classify every new value in both lists. Run rechecks on the node pool; the countdown is already under the lock (799-801). |
| Cancellation | No user cancel exists. Shutdown sets `stopping` and calls `pool.shutdown(cancel_futures=True)` (148-150). `execute` returns without finalizing (557, 568). `_settle` returns `'stopping'` and records nothing (728-735). | | Each node task checks `stopping` before `_open`. Shut down the node pool with `cancel_futures=True`: a cancelled task leaves its target `pending`, which the next start marks "interrupted before changed" (133). After joining, `execute` must return without `_verify`/`_finalize` if `stopping` is set. |
| Scrubbing | `scrub(..., store.state)` reads state under the lock. | 186, 591, 607 | Already thread-safe. |
| Existing tests | They patch `svc.pool.submit` and call `execute` synchronously (tests/test_restore.py:621-624). | | Keep a synchronous path when the worker count is 1 (the plain loop, or a pool that can be injected) so those tests keep their claims unchanged. |

## 3. Design

**Worker count.**
- **Setting:** `RestoreService(..., node_workers=None)`, which reads the environment variable `RESTORE_NODE_WORKERS`. `telemetry.py:114` and `capture.py:210` already read `os.environ` through a constructor argument.
- **Bounds:** clamp to 1..8. 1 means exactly today's behaviour.
- **Default:** 4, capped at `len(live)`. 4 is the proven acceptance lab (one node per image); 5 is the Ansible fork count the same devices already take at once for backups (runner.py:294).
- **Load:** the manager's cost is one thread and one SSH connection per worker. The real load is the device CPU during commits on a VM that also hosts XRv9k and vJunos.
- **Gate:** default to 1 until the live checks in §5 pass, then switch to 4 in a release.

**Pools.**
- `self.pool` stays at 1 worker and runs `execute` and the recheck scheduling.
- `self.node_pool = ThreadPoolExecutor(max_workers=node_workers, thread_name_prefix='restore-node')`.
- `close()` shuts down both.

**Per-node task.** `_node_task(job_id, lab_id, node, creds, cand, confirm_minutes, before, backed_up)`:
1. If `stopping`: return without writing anything; the target stays `pending`.
2. If the node is not in `backed_up`: `failed` with the backup reason. This is the existing branch at 560-564, moved into the task.
3. Otherwise `_apply_one(..., applied=None)`, with `_record_settled` as it is. Drop the `applied.append`; `applied is None` is already handled at 739.
4. Wrap everything in `try/except Exception`:
   - Target in `IN_FLIGHT`: run `_settle` once more, or record `uncertain` (never `failed`).
   - Target still `pending`: record `failed` with "not changed".
   - An exception must never reach `execute`. Today one would jump to `needs_attention` (589-596) and orphan the other nodes.

**`execute` step 3 becomes:**
```python
futures = {self.node_pool.submit(self._node_task, ...): name for name in live}
for f in as_completed(futures): f.result()   # results are already written by update_target
if self.stopping.is_set(): return
with self.store.lock:
    applied = [t['name'] for t in self.get_job(job_id)['targets'] if t['status'] == 'applied']
```

**Merging results.** The only writer is `update_target`, which changes one target in place under the lock. Add a small `stage_target(job_id, name, stage, **fields)` wrapper that sets `stage` and appends `timeline[stage] = time.time()` in the same locked write. Never `job['targets'] = ...`.

**Results arriving out of order.** Each target carries its own final state and a `timeline.settled` time. The job message keeps its phase text ("Applying the saved configuration") until all tasks finish. Add a job-level `progress: {settled: k, total: n}`, bumped inside the same locked write as a target's final state.

**What stays serialized, and why.**
- Restore jobs: one at a time (Runner rule at runner.py:158).
- The pre- and post-backups: one Runner job each (same rule; already parallel inside).
- The job-level phases: preflight, then backup, then apply, then verify. The post-backup must see every node settled, because `_verify` only reads `applied` targets (815).
- Several connections to **one** node: each node task works sequentially, and IOS XR rejects rapid connections.
- `_finalize` and `_verify`.
- Optional, separate change: the review and `submit` probes (348-369, 447-457) can use the same node pool. They are read-only and one connection per node.

**Failure isolation.**
- Each node has its own token (615), its own deadline (616) and its own `_settle` loop.
- `_settle` confirms only by token (689). One node's rollback or `uncertain` result cannot confirm or cancel another's.
- IOS XR `release(token)` is per token (661-666).
- Junos' "any `commit check` confirms" rule is per device (README:41-42); separate nodes do not interact.
- Nothing crosses nodes except the Store lock and the `stopping` event.
- With parallel nodes, a node whose management is lost holds only its own worker for up to window + 90 s. Today it delays **every later node's** arming by that much.

**Timeline to record.** A public target field `timeline` holding epoch floats (not underscore-prefixed, so `public_job` keeps it; it holds no secrets): `queued`, `backup_started`, `backup_done` (both job-wide, from the Runner job), `connecting`, `armed` (when `apply_candidate` returned), `verifying` (first fresh connection), `confirming` (just before `driver.confirm`), `settled`. Also `attempts` (count of `_settle` passes) and `worker`. Two nodes overlap when their `[connecting, settled]` intervals intersect; that check can be run on the job document alone.

## 4. Stage vocabulary for E6

**Target `status` values that exist today** (restore.py:473,529,537,562,617,627,638,648,655,737-760,790-797,819-839,131-134; restore.js:14-18):
`pending`, `backing_up`, `applying`, `confirming`, `applied`, `verified`, `applied_unverified`, `verify_mismatch`, `failed`, `rolled_back`, `uncertain`, `ineligible` (shown as "Skipped"), `interrupted`, and `rollback_expected` (only on jobs stored before 1.30.27).

**Recommendation:** keep `status` exactly as it is. `IN_FLIGHT`, the restart classification, `_verify`'s filter on `applied`, `_finalize`'s counts (853-856) and restore.js's sets (restore.js:6-23) all depend on it, and old stored jobs carry it. Add a separate `stage` field for E6:

| `stage` (new) | Set at | Status stays |
|---|---|---|
| `queued` | job created (473) | `pending` |
| `backing_up` | 537 | `backing_up` |
| `backed_up` / `failed` | after `_wait_backup` (548); a failed backup goes through 562 | `backing_up`, then `pending` / `failed` |
| `connecting` | before `_open` (624) | `applying` |
| `applying` (the driver validates, loads and arms in one call; the service cannot see the moment of arming) | before `apply_candidate` (632) | `applying` |
| `armed` | `apply_candidate` returned (655), with `no_op` | `confirming` |
| `verifying` (fresh connection, reading back) | each `_session(once)` pass (715) | `confirming` |
| `confirming` | in `once` just before `driver.confirm` (692); pass it as a callback in `_settle`, no driver change | `confirming` |
| `replaced` | `_record_settled('applied')` (737) | `applied` |
| `matched` | `applied` with `no_op` true, or preflight `matches_saved`. **A label, not a status**: `_finalize` must keep counting it as `verified` | `applied`, then `verified` |
| `skipped` | 529 | `ineligible` |
| `failed`, `rolled_back`, `uncertain` | 562, 627, 638, 751 / 743 / 758, 796 | the same |
| `checking` (post-backup) | 573 | `applied`, then the `_verify` results |

## 5. Risks and test plan

**Risks**
1. A new status value that is not classified in `IN_FLIGHT` or at :133 leaves a target in limbo after a restart. The `stage` field avoids this.
2. The IOS XR peer match (`pending`, restore_iosxr.py:530-534) conflates two targets that share `(address, port)`. Refuse such a job or run those targets one after another.
3. Deadlock if node tasks go to `self.pool`.
4. Device CPU contention on a loaded VM stretches commit times toward the driver timeouts. The 90 s grace covers a late rollback, not a slow arm.
5. `docs/multi-platform-restore/tools/mixed_failure.py` arms a foreign change "on the node applied last" (README:100). Under parallel nodes that timing assumption is gone; trigger on the target's `stage` instead.
6. README:14-16 and MATRIX.md C3 say "Nodes are applied one after another". The guide must change with the code (the lead writes the shared records).
7. `update_target` ignores `OSError` (180-181), so memory can run ahead of disk. That is existing behaviour, but with parallel nodes more in-flight targets can be wrong on disk after a crash.

**Unit tests** (`tests/test_restore.py`, fake drivers through `patch('app.restore.drivers.for_platform')`, as at :595-631):
- **Overlap:** a fake `apply_candidate` blocks on a `threading.Barrier(n)`, so the test fails unless n nodes are inside apply at once. Assert the `timeline` intervals intersect.
- **Worker bound:** with `node_workers=2` and 4 nodes, the observed concurrency never goes above 2 (counter under a lock).
- **Partial failure:**
  - Node A raises `RestoreError`, B gets `SessionLost` then reads back as rolled back, C holds a session and confirms, D raises an unexpected exception inside the task.
  - Expected: A `failed`, B `rolled_back`, C `verified`, D `uncertain`, job `needs_attention`.
  - Each token is confirmed only on its own node; `release` is called exactly once per holding node.
- **Out of order:** the fake apply for node order a, b, c sleeps 0.3/0.1/0.2 s. `settled` times are not in target order, yet the post-backup `node_names` is in target order and `_finalize` counts are right.
- **Stopping:** set `stopping` while two tasks are armed. Nothing is recorded for them (they stay `confirming`), queued tasks stay `pending`, and a new `RestoreService` over the same store puts them in `unchecked` / "interrupted before".
- **Restart recovery:** rechecks for several nodes run on the node pool, and `_finalize` runs exactly once (the `rechecks` countdown).
- **Store races:** 8 threads × 50 `stage_target` calls on different targets. No update lost, and the saved file decrypts to the same targets.
- **Existing tests:** the whole existing suite passes unchanged with `node_workers=1`, and with the default where it applies (the "rewrite, never delete" rule for tests).
- **Duplicate endpoint:** two targets with the same `(address, port)` are refused or run one after another.
- **CI:** the new cases go in the existing `test_restore.py` (already listed in CI); no new file, so the CI list does not change.

**Live, on `restore-square` (the lead assigns one operator; nothing was run here)**
- **All four at once:** cEOS, cJunosEvolved, vJunos-switch, XRv9k from one saved state with 4 workers. Evidence (`manager_restore.py` plus `readback.py --saved`) shows their `[armed, settled]` intervals overlapping, all `verified`, and the independent comparison at 0 missing / 0 extra.
- **Isolation under failure:** `failure_harness.py` cuts management on XRv9k after arming while the other three run in parallel. XR ends `rolled_back` (read back); the other three `verified`.
- **Foreign change:** the reworked `mixed_failure.py` arms a foreign change on one node mid-apply. The foreign change is left alone and that node ends "not changed".
- **Restart:** `interruption.py` restarts the manager with at least two nodes `confirming`. Both are read back, and XR undoes its change at `release`/timer.
- **Persistence:** `persistence_check.py` on cEOS after a parallel restore (the `write memory` still runs per node).
- **Rapid connections:** confirm on XRv9k that it still accepts the review probe and the arming connection while others run.
- **Load:** record apply and confirm durations against the one-at-a-time baseline to confirm that device load does not push commits toward the driver timeouts.

**Next action for the lead:** decide the default worker count (1 until the live checks pass, or 4 straight away) and whether the `stage`/`timeline` fields are the E6 contract. Then hand `restore.py` alone (plus the small `_HELD` lock in `restore_iosxr.py`, as a security-sensitive review item) to one builder, with the unit tests above as acceptance. Updating README:14-16 and the change log stays with the lead.

Key files:
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/restore.py`
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/restore_iosxr.py`
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/runner.py`
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/store.py`
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/lab_operations.py`
- `/home/clabllm/projects/clab-manager/clab-backup-ui/app/static/restore.js`
- `/home/clabllm/projects/clab-manager/docs/multi-platform-restore/README.md`
- `/home/clabllm/projects/clab-manager/docs/multi-platform-restore/evidence/xr-live-facts.md`
