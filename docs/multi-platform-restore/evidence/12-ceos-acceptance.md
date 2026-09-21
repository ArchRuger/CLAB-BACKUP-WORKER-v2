# ceos (Arista cEOS 4.35.0F) — Replace running configuration: acceptance results

QA performed independently of the author, live against manager build 1.30.27 on
`http://127.0.0.1:8081`, lab `restore-square`, node `clab-restore-square-ceos`
(172.20.20.101). All evidence files are under this directory, prefix `12-ceos-`.
Raw device transcripts (may include the local `admin` password hash) are under
`~/research/multi-platform-restore/raw/*qa-*` and are not committed.

## Summary table

| Check | Layer | Result | Evidence | Observation |
|---|---|---|---|---|
| A7(1) repeatability | product + device | PASS | 12-ceos-a7-1-restore-repeat.json, a7_1_readback (raw) | drift B -> restore A: description/prefix-list restored, vlan 777 & route gone, `show running-config diffs` empty, session `committed` not pending |
| A7(2) restore A while A active | product + device | PASS | 12-ceos-a7-2-noop-restore.json | `no_op:true`, empty diff, but EOS still armed a **new** timed-commit session and the manager confirmed it (session name changed, state `committed`) |
| A7(3) restore from a post-restore backup | product + device | PASS | 12-ceos-a7-3-restore-from-postrestore-backup.json | fresh `--backup-now` after a restore produces a usable `.eoscfg`; restoring from it also converges to A |
| A7(4) boot identity | device | PASS | 12-ceos-a7-4-boot-identity.json | Uptime strictly increasing (14→18→24→42→47→53 min) across the whole session; `boot_id` constant; ConfigAgent/Sysdb uptime tracks device uptime, never reset |
| B1 invalid candidate (bad syntax) | driver + device | PASS | 12-ceos-b1-invalid-candidate.json | `RestoreError("The node rejected the saved configuration while loading it.")`, no device text in the exception, running-config hash unchanged, no session left |
| B1 invalid candidate (semantic reject) | driver + device | PASS | 12-ceos-b1-invalid-candidate.json | Same controlled error; independently confirmed device said `% Subnet 10.0.12.0 overlaps with existing subnet 10.0.12.0 of interface Ethernet1`; hash unchanged, no session left |
| B2 truncated (no `end`) | driver | PASS | 12-ceos-b2-truncated-wrong-format.json | Refused by `validate_candidate` before `reach_cli` ever ran (spied: 0 calls) — zero CLI commands reached the device |
| B2 Junos-looking text | driver | PASS | 12-ceos-b2-truncated-wrong-format.json | Same: refused pre-connect, `reach_cli` never called |
| B2 empty text | driver | PASS | 12-ceos-b2-truncated-wrong-format.json | Same: refused pre-connect |
| B3 unreachable at preflight | product | PASS | 12-ceos-b3-preflight-unreachable.json | HTTP 200, ceos row `eligible:false`, reason `SSH probe failed: NoValidConnectionsError`; iptables rule removed and confirmed absent afterward |
| B4 loss of management before confirmation | product + device | PASS (after 5 attempts; 2 real defects surfaced along the way, see Defects) | 12-ceos-b4-attempt1..5-*.json, 12-ceos-b4-attempt5-event-log.json, 12-ceos-b4-recovery-restore-A.json | Attempt 5 hit the true window: session armed (`Session with pending commit timer`, counted down 0:01:59→0:00:04), EOS auto-reverted at expiry, manager reconnected only after the block was lifted and reported `rolled_back` with "Checked: the configuration from before the restore is active" — never before it could reconnect. Job ended (not hung), lab not left busy, single job only, device independently confirmed on B, boot_id/uptime intact. Recovery restore of A afterward succeeded and verified. |
| B5 manager restart during in-flight restore | product + device | PASS | 12-ceos-b5-manager-restart-rolled-back.json, 12-ceos-b5-event-log.json, 12-ceos-b5-recovery-restore-A.json | Manager restarted while target was `confirming` (armed); job/target immediately read `interrupted` on restart; device timer kept counting independently and reverted; after the block was lifted the restart re-check read the device back and settled the target to `rolled_back` (job-level status stayed `interrupted`, see Defects #3); exactly one restore job existed, lab not left busy, device independently on B, boot_id/uptime intact. Recovery restore of A afterward succeeded. |
| B6(a) foreign uncommitted session | product + device | PASS | 12-ceos-b6a-restore-with-foreign-session.json | `qa-foreign` (no timer) does not block a restore of A (matches saved state); afterward `qa-foreign` still listed `pending`, vlan 778 never activated |
| B6(b) foreign timed commit — preflight | product | PASS | 12-ceos-b6b-preflight-foreign-timer.json | ceos reported ineligible with exactly `"Another change is waiting for confirmation on this node."` |
| B6(b) foreign timed commit — submit | product | **FAIL (defect)** | 12-ceos-b6b-submit-not-refused-DEFECT.json, 12-ceos-b6b-job-final.json | `POST .../restore` returned **HTTP 200** and queued a job instead of HTTP 409; a real pre-restore backup ran; the job only failed later, at the driver's own foreign-pending check, when it tried to open a session. No device configuration was touched. See Defects #1. |
| B7 contention: restore then backup | product | PASS | 12-ceos-b7-contention.json | Immediate `POST .../jobs {operation:backup}` while a restore was running → HTTP 400 "Wait for the lab operation to finish."; restore completed `succeeded` |
| B7 contention: backup then restore | product | PASS | 12-ceos-b7-contention.json | Immediate restore submit while a backup was running → HTTP 409 "Wait for the active backup, Git save, restore or lab operation to finish."; backup completed `succeeded` |
| Finish state | product + device | PASS | 12-ceos-final-square-check.json | ceos on A, `show running-config diffs` empty, no pending session, no iptables rule left (`-P OUTPUT ACCEPT` only), manager answering (`version 1.30.27`), `square_check.py` overall `ok:true` for all four nodes (cjunosevolved/vjunos-switch/xrv9k healthy at this snapshot — out of my scope, reported not fixed) |

## Defects found (most severe first)

1. **Submit does not re-check a foreign pending commit/session; only preflight does — the documented HTTP 409 refusal does not happen (B6b).**
   `RestoreService.submit()` (`clab-backup-ui/app/restore.py:355-403`) computes eligibility via
   `map_targets()` (`restore.py:257-286`), which never performs a live SSH probe. The
   foreign-pending check (`self._pending(node, creds)`, `FOREIGN_PENDING` message "Another change
   is waiting for confirmation on this node.") exists **only** inside `preflight()`'s separate
   live-probe loop (`restore.py:317-333`). Consequence, reproduced live: with a foreign
   `commit timer` armed on ceos, `POST /api/labs/{lab_id}/restore/preflight` correctly refuses
   (HTTP 200, `eligible:false`), but `POST /api/labs/{lab_id}/restore` for the same node returns
   **HTTP 200** and queues the job. The job runs a full pre-restore backup, then fails only when
   the EOS driver's own `apply_shell()` foreign-pending check (`restore_eos.py:110-113`) refuses at
   the "applying" stage — so no configuration is actually touched, but the acceptance contract
   ("a submit must be refused (HTTP 409) with nothing changed") is violated at the API layer, and a
   needless backup job runs. A client that races preflight and submit, or that skips preflight, hits
   this. Evidence: `12-ceos-b6b-submit-not-refused-DEFECT.json` (submit_http: 200),
   `12-ceos-b6b-job-final.json` (job ends `failed` only after a real `pre_backup_job_id` ran).

2. **A connection lost between opening the restore session and arming its commit timer leaves an orphaned, un-timered pending session that nothing detects or cleans up.**
   Reproduced twice (B4 attempts 2 and 3, delays 0.5s/0.85s after the `applying` status appeared):
   the driver's `configure session <token>` / paste sequence started, but the SSH path broke before
   `commit timer` was sent. The device is left with a session in state `pending` **without** a
   "Session with pending commit timer" line (`show configuration sessions detail`). Two problems
   follow from this: (a) `restore_eos.pending_shell()` (`restore_eos.py:87-91`), used both by
   `apply_shell()`'s foreign-pending guard and by `_settle()`'s reconciliation, matches only
   `Session with pending commit timer: …` — it never sees this kind of orphaned session, so a later
   restore attempt is not warned about it and does not clean it up either; (b) nothing in
   `RestoreService` (not even the restart re-check) ever aborts a session it can identify as its own
   (the name is the job's own `clabmgr-<token>`) when that session turns out to hold no timer. I
   manually aborted both orphaned sessions (`clabmgr-b9e8bda5`, `clabmgr-0d1359af`) via `nodecli.py`
   since nothing else would have. EOS caps `Maximum number of pending sessions: 5`; repeated
   occurrences of this exact failure mode (a network blip between paste and arm) would accumulate
   stray sessions and could eventually exhaust that pool, at which point **every** future
   `configure session` on the node — the driver's and any human operator's — starts failing.
   Evidence: `12-ceos-b4-attempt2-orphaned-session-uncertain.json`,
   `12-ceos-b4-attempt3-orphaned-session-uncertain.json`.

3. **(Minor / confirm with lead) A restart-interrupted job's top-level `status` never leaves `interrupted`, even once `_recheck_interrupted` has settled every target to a definitive outcome.**
   `RestoreService._recheck_interrupted()` (`restore.py:634-662`) updates the *target* to
   `verified`/`rolled_back`/`uncertain` but never calls `_finalize()`, so the *job's* `status` field
   is permanently `interrupted` and its `message` stays the generic restart notice, even though the
   target-level message already has the definitive, correct answer. Not a safety issue (the message
   does point at the target), but a job that was interrupted can never again read `succeeded` or
   `failed` at the job level, which may be surprising in a job list/history view. Evidence:
   `12-ceos-b5-manager-restart-rolled-back.json` (`final_job.status == "interrupted"`,
   `final_job.targets[0].status == "rolled_back"`).

## Layer definitions used above

- **product** — through the real manager API (`manager_restore.py`, direct HTTP calls with the
  correct `Origin`), exactly what the browser would drive.
- **driver** — `app/restore_eos.py` functions called directly against the live node from a
  throwaway script using paramiko the same way `app/node_services.connect` does, bypassing
  `RestoreService` entirely.
- **device** — raw CLI, independent of the manager and the driver: `nodecli.py` (SSH,
  `admin`/`admin`) normally, and `docker exec … Cli -p 15 -c "show …"` (read-only) for the windows
  where SSH to ceos was intentionally blocked (B4/B5).

## Limitations

- B4/B5 rely on a black-box race (network-level SSH block timed against manager status polling and
  the device's own session state); the precise "armed but not yet confirmed" window is well under a
  second. It took 5 attempts across B4 to land in it cleanly; earlier attempts are kept as evidence
  because they surfaced defect #2, not discarded as noise.
  Browser/UI-level verification was not performed (no browser tooling was invoked in this task; the
  scope given was product/driver/device only) — noting the gap rather than claiming visual coverage.
- cjunosevolved, vjunos-switch and xrv9k were not touched (per the assignment) and are reported only
  as `square_check.py` saw them at the final snapshot; any further work on them belongs to the other
  agents already assigned to those nodes.
