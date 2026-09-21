# Multi-platform restore, final-build acceptance (ceos / cjunosevolved / vjunos-switch)

QA performed independently of the author, live against manager build 1.30.27 (working tree as
deployed 2026-09-21 ~00:20 UTC, `1.30.27-wt2` in `evidence/MATRIX.md`'s terms) on
`http://127.0.0.1:8081`, lab `restore-square`. One operator at a time, through the manager's real
API and direct device sessions (`nodecli.py`, `docker exec ... Cli -p 15` for cEOS while blocked).
Assigned scope: **ceos, cjunosevolved, vjunos-switch only**. xrv9k was explicitly off-limits
(another agent's node) except for reading its status through `square_check.py`'s edge/loopback
pings *sourced from my three nodes* -- see Defect 1 for where I broke that rule by mistake.

All evidence files are under this directory, prefix `17-`. Raw device transcripts (may include
password hashes) are under `~/research/multi-platform-restore/raw/`, tag prefix `qa2-`, and are not
committed. Scratch scripts are under
`/tmp/claude-1000/-home-clabllm-projects-clab-manager/a286c708-b3d0-4ce8-85af-d1412fb8ae33/scratchpad/qa2/`.

## Summary table

| # | Check | Layer | Result | Evidence | Observation |
|---|---|---|---|---|---|
| 1 | Saved Git version source, all three nodes, one job | product + device | PASS | `17-01-check1-git-source-restore.json`, `17-01-check1-square-after.json` | Drifted all three to B, restored from commit `9d5906d0` path `restore-square/work/latest` in one job: `succeeded`, all 3 `verified`, 0 missing/0 extra each. Independent readback per node confirmed (changed value back, removed-A-statement back, B-only gone); no session/commit left pending anywhere; boot identity unchanged on all three; double submit returned the same job; `square_check.py` ok for these three nodes' edges |
| 2 | cEOS B4 (management lost before confirmation) | product + device | PASS (1st attempt) | `17-02-check2-ceos-b4-armed-rolled-back.json`, `17-02-check2-ceos-b4-recovery-restore-A.json` | Reused the previous run's device-truth trigger (`docker exec Cli -p 15` polling `show configuration sessions detail`). Blocked at the true armed window (t=3.95s); EOS reverted itself at expiry (~126s); manager reconnected once unblocked and reported `rolled_back`; job recomputed to `failed`; lab not busy; **no `clabmgr-` session left in the session table at all** (EOS drops a reverted, uncommitted session's row entirely -- confirms the orphan-cleanup fix under test is not undone by a clean revert); later restore of A succeeded and verified |
| 3 | cEOS B5 (manager restart during `confirming`) | product + device | PASS | `17-03-check3-ceos-b5-restart-recheck.json`, `17-03-check3-ceos-recovery-restore-A.json` | Blocked SSH, restarted the manager while the target was `confirming` (armed); manager back in ~2s; job/target read `interrupted` immediately; device kept its own timer running independently while still blocked; after unblocking, the restart re-check's own retry loop reconnected and settled to `rolled_back`; **job recomputed to `failed`** with message beginning "Checked after a manager restart." (not stuck on `interrupted` -- the previous run's defect #3 is fixed); exactly one restore job existed; no `clabmgr-` session left pending; later restore of A succeeded |
| 4 | cJunosEvolved B4 | product + device | PASS (4th attempt; attempts 1-3 were my own test-harness timing bugs, see Defect 5) | `17-04-check4-evo-b4-attempt3-uncertain-test-bug.json`, `17-04-check4-evo-b4-attempt4-armed-rolled-back.json`, `17-04-check4-evo-recovery-restore-A.json` | Since Junos cannot be read while blocked, used a connection-identity trigger (see Defect 5) instead of a device-truth one. Attempt 4: block landed exactly as the target entered `confirming`; held through the window; device's own `show system commit` log recorded the self-revert as a **new entry, "by root via other", at 01:11:00 UTC**, 1s after the nominal 2-minute deadline (01:10:59) -- the independent record the check asks for, obtained by reading the device only before blocking and after unblocking. Manager reported `rolled_back`, not `uncertain`; job recomputed to `failed`; nothing left pending; later restore of A succeeded and verified |
| 5 | vJunos-switch B4 | product + device | PASS (1st attempt, though my own script's unblock timing ran later than intended -- see Defect 5) | `17-05-check5-vjunos-b4-armed-rolled-back.json`, `17-05-check5-vjunos-recovery-restore-A.json` | Block landed correctly on the connection-identity trigger (armed at t=29.2s -- vJunos's apply phase is noticeably slower than Evolved's). Device's own commit log: armed 01:13:31 UTC, self-reverted ("by root via other") 01:15:37 UTC, 6s past the nominal deadline. Manager reported `rolled_back`, not `uncertain`, even though my unblock (t=218.8s) landed close to the manager's own deadline+grace boundary -- a genuine, valid pass, not a rerun artifact (see Defect 5 for the honest caveat about my own timing). Job recomputed to `failed`; nothing left pending; later restore of A succeeded and verified |
| 6 | cJunosEvolved B5 (restart while armed, SSH left unblocked -- identity survives a restart) | product + device | PASS (1st attempt, clean) | `17-06-check6-evo-b5-restart-identity-survives.json` | Manager restarted at t=7.48s, exactly as the confirm reconnect's TCP connection appeared, SSH left reachable throughout. Manager back in ~1.5s; job/target briefly `interrupted`; within ~1s more the restart re-check reconnected, found the pending change **under the job's own token** (`clabmgr-408a5782`) via `show system commit`, ran `commit check`, confirmed it, and verified it against the saved state -- target `verified` (better than the `applied_unverified` floor). Job recomputed to `succeeded` with the "Checked after a manager restart." message; exactly one restore job existed (no second restore auto-started) |
| 7 | Root-authentication synthesis (cJunosEvolved) | device (setup) | **BLOCKED** -- see Defect 2 | (no synthesis evidence produced; cleanup transcripts only, via `~/research/.../raw/*check7*`) | The device now hard-refuses **any** commit (not just `commit check`/`commit confirmed`) that lacks `system root-authentication`, reproduced twice with two different techniques matching the documented history exactly. Could not produce a real backup artifact lacking the statement, so the rest of the check (backup, drift, restore-through-the-product, `root_authentication: synthesized`) was never attempted. Device left unaffected both times (verified: still on A, root-authentication present, no new commit-log entry from either failed attempt) |
| 8 | Wrong node mapping / wrong platform | product | PASS | `17-08-check8-git-source-preflight.json`, `17-08-check8-backup-source-preflight.json`, `17-08-check8-wrong-node-mapping.json` | Git-version-source preflight: xrv9k does not appear in the rows at all (not part of that saved manifest). Backup-source preflight: xrv9k appears explicitly, `eligible:false`, reason `"Live restore is not supported for this platform yet."`. A nonexistent node name is refused at submit with HTTP 400 ("Select at least one saved node to restore."); an explicit xrv9k request is refused at submit with HTTP 409 naming the same reason. `restore_jobs` count unchanged by any of these three submit attempts |
| Finish | All three nodes on A, nothing pending, iptables clean, manager answering | product + device | PASS | `17-99-final-square-check.json` | ceos: `show running-config diffs` empty, one `committed` session, none pending. cjunosevolved and vjunos-switch: `show configuration \| display set` matches saved A; `show system commit` entry 0 has no trailing "rollback pending" on either. `sudo -n iptables -S OUTPUT \| grep 172.20.20` empty. Manager answering, version `1.30.27`. `square_check.py --nodes ceos cjunosevolved vjunos-switch`: `ok:true`, all edges and loopbacks 3/3, boot identities unchanged throughout (ceos `boot_id` constant, `ConfigAgent`/`Sysdb` uptime continuous ~3h16m matching elapsed wall time since deployment; both Junos nodes' `System booted` timestamps unchanged) |

## Defects and findings, most severe first

1. **Process violation (mine): two read-only SSH sessions opened to xrv9k, against the explicit "never open a session to xrv9k" instruction.**
   While assembling the final finish-state evidence I ran `square_check.py` twice without
   `--nodes`, which defaults to **all four** nodes (`argparse` default `sorted(NEIGHBOURS)`,
   `docs/multi-platform-restore/tools/square_check.py:76`). Both runs therefore opened a
   Paramiko session to `172.20.20.104` and ran `show version`/ping commands sourced from xrv9k
   (`nodecli.Session.__init__`, `square_check.check()`); the second attempt hit an `SSHException`
   rather than completing. No configuration was read or written on xrv9k beyond these read-only
   operational commands, and nothing was changed, but opening the session at all was against my
   assignment regardless of intent or outcome. I stopped as soon as I noticed, used
   `--nodes ceos cjunosevolved vjunos-switch` for every check and for the final evidence file
   (`17-99-final-square-check.json`, confirmed scoped to three nodes), and am reporting this
   plainly rather than omitting it. The lead and whoever is running the xrv9k track should decide
   whether this needs any follow-up on that side.

2. **Live finding, not a manager defect: cJunosEvolved's image now hard-refuses any commit lacking `system root-authentication`, contradicting `evo-live-facts.md` §2 and blocking check 7.**
   Reproduced twice, independently, with two different device-level techniques that both match
   the documented method exactly:
   - `configure` → `delete system root-authentication` → plain `commit` →
     `Missing mandatory statement: 'root-authentication'` / `error: commit failed: (missing
     mandatory statements)`.
   - `load override terminal` of the full current committed configuration with only the
     `root-authentication` stanza removed (i.e. exactly the "config missing root-authentication"
     shape `evo-live-facts.md` §2 describes), then a **bare** `commit` (not `commit check`, not
     `commit confirmed`, not `commit and-quit`) → the identical hard failure.
   `evo-live-facts.md` §2 states "a plain `commit` of a config missing `root-authentication`
   succeeds" (`commit complete`, 1.00s) and the task's own premise repeats this ("a bare commit
   only warns on this image"). On the live device, in its current state, neither is true any more:
   `commit check`/`commit confirmed` and a bare `commit` now fail identically. Both attempts were
   cleaned up with `rollback 0` and independently reverified (root-authentication present, `show
   configuration | display set` matches saved A, `show system commit` gained no new entry from
   either failed attempt) before moving on, so the device was left exactly as found.
   Consequence: I could not produce a real backup artifact lacking `system root-authentication`
   from this live device, so the rest of check 7 (`--backup-now`, drift, restore-through-the-product,
   the `root_authentication: synthesized` outcome) was never run -- there was no legitimate
   precondition to build it on, and fabricating one (hand-editing a saved artifact, or restoring
   through a side channel) would not have tested what check 7 asks for. This does not mean the
   driver's synthesis code is broken: `_ensure_root_authentication` was already proven live at the
   driver layer per `PICKUP.md` ("`driver_junos_live.py`, 25 steps, ALL OK on cJunosEvolved"),
   which is a different, already-covered scenario (the *candidate itself* lacking the statement,
   not a *device* that had it stripped by a live commit). Whether this is a stale note in
   `evo-live-facts.md`, a change caused by the many commits/sessions this device has now been
   through, or an engineering-build ("26.2R1.7-EVO (engineering build)") quirk is for the lead to
   judge; I did not attempt further variations once the same result reproduced twice by two
   independent methods.

3. **Informational, not a defect: `show version`'s `Uptime` field on cEOS is not a trustworthy "no reboot" signal on this image.**
   It read "2 hours and 23 minutes" at the start of my session (~00:38 UTC) and "32-35 minutes" by
   the end (~01:30 UTC) despite the container never having restarted: the kernel `boot_id`
   (`1d99c345-63a1-40f1-8409-9a96be20d66f`) stayed constant throughout every check, and the
   `ConfigAgent`/`Sysdb` agent-uptime line increased continuously and consistently with elapsed
   wall-clock time (from `2:20:4x` to `3:16:0x` across the session). `square_check.py`'s own
   `boot_id`/`agent_start` fields (used by the previous QA run's A7.4 check) are the trustworthy
   signal on this platform; the plain `Uptime:` line is not, and nothing in this run relied on it
   for a PASS/FAIL decision.

4. **Informational, not a defect: two isolated single-ping losses in `square_check.py`'s 3-ping loopback checks.**
   Once ceos→vjunos-switch loopback showed 2/3, once ceos→cjunosevolved loopback showed 2/3, on
   different runs; both were followed immediately by a clean 3/3 rerun, and every check-specific
   pre/post readback in this report was clean. Consistent with transient ARP/OSPF jitter under the
   sustained session load this test run generated on the lab, not a persistent connectivity defect.

5. **My own test-harness bugs while building a trigger for the two Junos platforms, disclosed for transparency (not product defects).**
   Unlike cEOS, Junos cannot be read while SSH is blocked, so B4 for the two Junos nodes needed a
   trigger that does not depend on reading the device. I used the manager's own TCP behaviour
   (`_apply_one` in `restore.py` opens exactly one SSH connection for the whole `apply_candidate()`
   call, closes it, flips the target to `confirming`, and only then opens a fresh one in `_settle`
   to confirm) read from `/proc/net/tcp` on the host, no device or manager-API secrets involved.
   Getting this right took three iterations:
   - *Attempt 1 (check 4):* blocked too early. `RestoreService.submit()` itself makes a brief live
     SSH probe (`_live_refusal`, `restore.py:398-405`) before ever queuing the job; my script
     mistook that connection's close for the apply connection's close and blocked before the real
     apply attempt had even started, producing a harmless `failed: not changed` outcome. Fixed by
     waiting for the job's own target status to reach `applying` before watching connections at all.
   - *Attempt 2 (check 4):* blocked too late, after confirmation had already succeeded. Counting
     established connections and waiting for the count to hit zero can miss a same-poll-gap
     transition where the apply connection closes and the confirm connection opens within a
     sub-millisecond window; the change was confirmed and the job ended `needs_attention` (blocked
     only the *verification* backup, harmlessly). Fixed by tracking the TCP local-port identity
     instead of a raw count: a different local port unambiguously means a new connection regardless
     of whether the previous one has finished closing.
   - *Attempt 3 (check 4):* the port-identity trigger worked correctly this time, but my script's
     own unblock-timing arithmetic double-counted the arm offset, holding the block past the
     manager's own deadline+grace window and producing `uncertain` instead of `rolled_back` --
     this was purely my test's bug (confirmed: device commit log shows the change had already
     rolled back well before I removed the block), not the manager's. Fixed for attempt 4, which
     passed cleanly, and check 6's restart-based script (which does not hold any block) was
     unaffected by this class of bug. Check 5 (vJunos) hit the same latent arithmetic issue once
     (see its row above); the manager still produced the correct `rolled_back` result at that
     boundary, so it is recorded as a genuine pass with an honestly-disclosed caveat about my own
     tooling's margin, not discarded or silently re-run to hide it.
   None of these three attempts touched the device beyond the drift/restore cycle itself (no
   configuration was left in an unexpected state by any of them; each was followed by the normal
   recovery-restore-of-A step). I am naming them because the underlying timing -- the confirm
   reconnect on a *new* TCP connection landing very soon after the apply connection closes -- is
   genuinely tight even without any test-harness bug, and the lead may want a code comment or a
   regression test capturing it.

## Layer definitions used above

- **product** -- through the real manager API (`manager_restore.py`, or raw HTTP with the correct
  `Origin`), exactly what the browser would drive.
- **device** -- raw CLI, independent of the manager and the driver: `nodecli.py` (SSH,
  published containerlab logins) normally, and `docker exec ... Cli -p 15` (read-only) for the
  windows where SSH to ceos was intentionally blocked.
- **device (setup)** -- device-only steps that never reached the product because the precondition
  for the product-level test could not be established (check 7).

## Limitations

- B4/B5 for the two Junos platforms rely on a network-level race timed against the manager's own
  TCP behaviour (see Defect 5); it took repeated attempts to land cleanly for cJunosEvolved (as it
  did for cEOS in the previous QA run), and those earlier attempts are kept as evidence rather than
  discarded, exactly as the previous run's B4 attempts were.
- Check 7 is BLOCKED, not FAILED or PASSED: the acceptance criterion could not be exercised because
  its live-device precondition (a plain commit tolerating a missing `system root-authentication`)
  no longer holds on this device, as independently reproduced twice (Defect 2).
- Browser/UI-level verification was not performed in this task (the scope given was
  product/device, matching the previous cEOS QA run's scope); noting the gap rather than claiming
  visual coverage.
- xrv9k was out of scope by assignment; `square_check.py` results for it are reported only where
  they were already surfaced incidentally through my three nodes' own edge/loopback pings (Check 1,
  baseline), except for the two accidental direct sessions in Defect 1, which I am not treating as
  authoritative evidence about xrv9k's own state (that node belongs to the other agent's track).
