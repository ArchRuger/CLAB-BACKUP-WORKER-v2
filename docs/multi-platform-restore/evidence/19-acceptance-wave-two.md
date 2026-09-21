# Multi-platform restore, wave-two acceptance (ceos / cjunosevolved / vjunos-switch)

QA performed independently of the author, live against manager build 1.30.27 (working tree as
deployed; container started 2026-09-21T02:23:08Z, git HEAD `3c5d954d9ed1` with `app/git_progress.py`,
`app/inventory.py`, `app/restore.py`, `app/restore_drivers.py`, `app/restore_junos.py`, `app/runner.py`
and `app/static/restore.js` modified in the working tree — the build identity every evidence file
below embeds via `manager_restore.build_identity()`) on `http://127.0.0.1:8081`, lab `restore-square`
(`904a35a79dc341ce8a4638f83fc34185`). One operator at a time, through the manager's real API and
direct device sessions (`nodecli.py`; no `docker exec` fallback was needed this run because no check
below required reading a device while its own SSH was blocked). Assigned scope: **ceos,
cjunosevolved, vjunos-switch only**; `xrv9k` was never opened a session by this agent (every
`square_check.py` invocation used `--nodes ceos cjunosevolved vjunos-switch`; every preflight/restore
request named only the three assigned nodes, confirmed by `reachable: null`/absent for xrv9k in every
preflight response). The manager's own routine "Save progress" capture (check 4a) reads all four
bound nodes as it always does for any user — that is the product doing its normal job, not this agent
opening a session; see the note under check 4.

All evidence is under this directory, prefix `19-`. Raw device transcripts are under
`~/research/multi-platform-restore/raw/`, tag prefix `19-`, not committed. Scratch scripts are under
`/tmp/claude-1000/-home-clabllm-projects-clab-manager/a286c708-b3d0-4ce8-85af-d1412fb8ae33/scratchpad/qa3/`.
The one committed tool is `docs/multi-platform-restore/tools/failure_harness.py`.

## Summary table

| # | Check | Layer | Result | Evidence | Observation |
|---|---|---|---|---|---|
| T | `failure_harness.py`: `submit-cut`, `armed-cut`, `restart-confirming` | tool | Built; `submit-cut` exercised live (6 runs, see #1); `armed-cut` and `restart-confirming` implemented and embed `build_identity()`/readback but were **not invoked** this run | `tools/failure_harness.py` | No check below needed to arm-then-cut or restart the manager, and the assignment says the manager may only be restarted "if a check says so (none below does)" — so `restart-confirming` was written and reviewed for correctness but deliberately never run |
| 1 | B3 at application, per platform (3 runs) | product + device | **PASS** (clean on the first attempt, all three platforms) | `19-01-check1-{ceos,cjunosevolved,vjunos-switch}-{preflight,submit-cut,recovery}.json` | Drifted each node to B, reviewed (eligible), then `failure_harness.py submit-cut`: a tight `/proc/net/tcp` loop blocked the node's management address the instant the apply connection appeared (after the pre-restore backup had already succeeded) — `reached_applying_at_rel_s` 3.3–5.6 s, blocked within 8 ms of that. Every target ended `failed`, message **"Configuration was not changed. Connectivity: NoValidConnectionsError"** (`restore.py:607-608`) within ~15–20 s (never hung); job `failed`; iptables rule removed and confirmed absent (`iptables_clean_at_exit: true`) every time; independent readback showed B untouched, `pending_confirmation: false`, `own_sessions_left_pending: 0` (ceos) on all three; a follow-up preflight proved the lab was not left busy. Recovery restore of A then `verified` on all three |
| 2 | Rejected credentials, ceos only | product + device | **PASS at review; FAIL at submit — see Defect 1** | `19-02-check2-review-wrong-creds.json`, `19-02-check2-review-right-creds{,-on-B}.json`, `19-02-check2-submit-wrong-creds.json`, `19-02-check2-login-attempt-count.json`, `19-02-check2-recovery-restore-A.json` | Assigned a fresh profile (`QA-wrong-password-ceos`) via `POST /api/labs/{id}/profiles` then `PUT /api/labs/{id}/node` (the model has no direct password field; a profile is the manager's own way to change a node's effective login). Review: row `eligible:false`, `reachable:true`, reason exactly `"The node rejected the login credentials."` — correct, and distinguishable from "did not answer". Restored the right credentials, review passed (`eligible:true`). Set the wrong password again and **submitted a real restore**: target ended `failed`, but with message **"Pre-restore backup failed for this node; it was not changed."**, not the credentials wording — see Defect 1. Device untouched: readback still `B` (drifted for this test), `pending_confirmation:false`. Login-attempt count: cEOS's own `sudo lastb -F` (device layer, no manager code) showed exactly 3 failed attempts inside this job's own window (02:40:29–31), not a retry storm; 6 more appeared afterward from the manager's *background* readiness/telemetry polling of the still-wrong stored credential (stopped the moment the credentials were reverted) — informational, not part of the restore path's own behaviour. Restored the right credentials; a normal restore of A then `verified` |
| 3 | B6 at the API, both Junos images | product + device | **PASS** (a, b, c, both platforms) | `19-03-check3a-{evo,vjunos}-{review-foreign-pending,submit-refused,foreign-selfrevert}.json`, `19-03-check3b-{evo,vjunos}-{review-bystander,bystander-edit}.json`, `19-03-check3-double-submit-refused.json` | (a) A foreign `commit confirmed 2 comment QA-foreign-hold` on an unused port (et-0/0/7 / ge-0/0/7): review ineligible with `"Another change is waiting for confirmation on this node."`; submit HTTP 409, same reason, `restore_jobs`/`jobs` counts unchanged; entry 0 of `show system commit` still carried `QA-foreign-hold` and `rollback pending` right after the refused submit; the device rolled it back by itself (`by root via other`) at 02:46:45 (evo) / 02:49:42 (vjunos) with no manager intervention; readback after = A, 0 missing/0 extra. (b) A bystander's uncommitted `set system location building QA-BYSTANDER` left via `exit` → `yes`: review ineligible with `"Someone has uncommitted configuration changes open on this node. The restore was not started, so their work is not lost."`; submit 409, same reason, no job created; a fresh plain session's `show \| compare` afterward still showed the edit **unchanged and uncommitted**; active configuration stayed A throughout (0 missing/0 extra); cleaned with `rollback 0`. (c) Two identical POSTs (same `request_id`) against the still-pending foreign commit on vjunos-switch both answered 409 and created nothing (`restore_jobs` count unchanged both times) |
| 4 | Contention beyond backups (once) | product | **PASS**, both parts; the guard is shared, confirmed by the identical 409 wording from `operation_busy()` in both (a) and (b) | `19-04-check4b-contention.json`; save race described below (no separate file needed: the second, successful attempt's HTTP bodies are quoted here and the job was dismissed through the API) | (a) `POST .../git/save {push:false}` then, ~51 ms later, `POST .../restore` → 409 `"Wait for the active backup, Git save, restore or lab operation to finish."`; the save finished `committed` (local commit `d411072…`, not pushed) and was set aside with `POST /api/git/jobs/{id}/dismiss {"acknowledge":true}` → `status:"dismissed"`, "Existing commits are unchanged." Nothing was uploaded/pushed. (A first attempt with a ~6 s gap missed the window because the capture itself finished in ~3 s; that attempt's save ended `capture_incomplete` — 3/4 nodes captured, xrv9k's own SSH banner read failed once, unrelated device flakiness, not caused by this agent and not something requiring dismissal since no commit was made.) (b) Drifted cjunosevolved to B, submitted its restore, then at `backing_up` fired `POST /api/operations/preview {action:"redeploy", lab_id}` (review only, never confirmed) → 409 `"Wait for the current lab operation to finish."`, and a second restore for vjunos-switch → 409 `"Wait for the active backup, Git save, restore or lab operation to finish."`; the first restore finished `succeeded`/`verified` in 11 s |
| 5 | Real `verify_mismatch` (ceos) | product + device | **PASS** (1st attempt) | `19-05-check5-verify-mismatch.json` | Drifted to B, submitted A-over-B with an already-authenticated parallel `nodecli` session held open; the instant the target read `applied` (t=5.57 s) sent `configure`/`vlan 999`/`end` on that session. Target ended `verify_mismatch`, job `needs_attention`; `extra_statements:1`, `extra_sample:["vlan 999"]`, `missing_statements:0`; the `diff_sample` field contains only generic diff lines, no secret text. Cleaned up (`no vlan 999`); `show running-config diffs` empty; independent readback A, 0 missing/0 extra |
| 6 | B1 at the driver layer, both Junos images | driver (direct) | **PASS**, both cases, both platforms | `19-06-check6-driver-b1.json` | Scratch script imports `app.restore_junos` from `clab-backup-ui`, connects with `paramiko` exactly like `app.node_services.connect`. (a) A syntactically-balanced but nonsense candidate (`totally-bogus-statement-xyz;` inside `system {}`) → `RestoreError("The node rejected the saved configuration while loading it.")` on both images — a controlled message, no device text. (b) A candidate that loads (includes a synthetic `root-authentication` so `_ensure_root_authentication` does not short-circuit first) but assigns the same `/24` address to two unused interfaces (et-0/0/6 & et-0/0/7 / ge-0/0/6 & ge-0/0/7) → `RestoreError("The node failed the configuration check for the saved configuration.")` on both images — a genuine device-side `commit check` rejection, not the documented root-authentication shortcut. In all four cases: a fresh connection immediately reacquired `configure exclusive` cleanly (`exclusive_session_reacquired: true`, proving no lock was left behind), and readback before/after was `A`/`A`, `pending_confirmation:false` both times |
| Finish | All three nodes on A, right credentials, nothing pending, no un-uploaded save left pending, iptables clean, manager answering | product + device | **PASS** | `19-99-final-readback.json` (exit 0), `19-99-final-square-check.json` (`ok:true`) | `readback.py --expect A --saved …` exit 0 for all three (0 missing/0 extra each); cEOS `show running-config diffs` empty; ceos `profile_id:""`/`credential_source:"inventory"` (right credentials); no `restore_jobs`/`jobs` in a busy status; no `git_jobs` in `queued/capturing/exporting/pushing`; the one dismissed QA save and the one `capture_incomplete` QA save are both terminal, nothing pending upload; `sudo -n iptables -S OUTPUT \| grep 172.20.20` empty; manager answering, version `1.30.27`, container uptime continuous (never restarted by this agent); `square_check.py --nodes ceos cjunosevolved vjunos-switch`: `ok:true`, every edge/loopback 3/3, ceos `boot_id` unchanged, both Junos `System booted` timestamps unchanged from the session's start |

## Defects and findings, most severe first

1. **Defect: submitting a restore with rejected credentials reports a generic backup-failure
   message, not "the login was rejected", because the mandatory pre-restore backup always runs
   before the driver's own connection attempt and its failure masks the more specific classification.**
   Check 2's acceptance text asks for "target `failed`, message says the login was rejected" at
   submit time. What actually happens: `RestoreService.submit()` (`restore.py:398-450`) does call a
   live pre-check (`_live_refusal`, `restore.py:404`), but wraps it in `except Exception: refusal = ''`
   (`restore.py:436-438`) — **any** exception, including `paramiko.AuthenticationException`, is
   silently treated as "no refusal", by design ("An unreachable node does not [refuse]: it gets its
   own outcome in the job, and the driver repeats these refusals itself at the moment it would change
   a node", comment above line 420). That deferred classification lives in `_apply_one`
   (`restore.py:607`: `message = BAD_LOGIN if isinstance(exc, paramiko.AuthenticationException) else
   'Connectivity: ...'`) and is correct *when reached*. But `execute()` runs the mandatory
   pre-restore backup (`restore.py:509-525`, a separate Ansible/`Runner` connection using the same
   stored credentials) **before** `_apply_one` is ever called for any node. That backup also fails
   against the wrong password (confirmed live: the backup job's own node message was
   `"Failed to authenticate: Failed to authenticate: Bad authentication type; allowed types:
   ['publickey', 'keyboard-interactive']"`), and a failed pre-restore backup is reported with the
   fixed, generic string `"Pre-restore backup failed for this node; it was not changed."`
   (`restore.py:545`) — the specific reason from the backup job is never carried into the restore
   target's own message. A user restoring with a stale credential sees only "the backup failed",
   never learns the real cause, and has to go find the separate backup job to see why. Device
   untouched either way (confirmed by readback), and no hammering (confirmed via the device's own
   `lastb`), so this is a **diagnosability defect in the failure message, not a safety defect**.
   Live, reproducible finding along the way: cEOS 4.35.0F's SSH daemon answers a *wrong* password
   with `paramiko.BadAuthenticationType` (allowed types `['publickey', 'keyboard-interactive']`, no
   `'password'` offered) rather than a plain `AuthenticationException`, reproduced 8/8 times with raw
   `paramiko.SSHClient.connect()` outside any manager code; the *right* password authenticates
   immediately every time. This is harmless to the manager's own exception handling — paramiko's
   `BadAuthenticationType` is itself a subclass of `AuthenticationException`
   (confirmed: `issubclass(paramiko.ssh_exception.BadAuthenticationType, paramiko.AuthenticationException)
   == True`, paramiko 3.5.1), so both `_open()`'s no-retry branch (`restore.py:352-363`) and
   `_apply_one`'s `BAD_LOGIN` classification (`restore.py:607`) already treat it correctly *when that
   code path is reached* — it just never is reached here, per the paragraph above.

2. **Process note, not a product defect: another workflow track appears to have been active on the
   same manager/lab during part of this session.** `docs/multi-platform-restore/PICKUP.md` and
   `README.md` carry modification timestamps (02:38:11Z and 02:26:21Z respectively) that fall inside
   this session's own testing window (which ran from about 02:23Z to 03:01Z), and several other
   evidence files this agent did not create (`18-browser-disabled-row-legacy-save.json`,
   `40-xr-restore-A-over-B.json`, `50-all-four-browser-desktop.json`,
   `51-mixed-four-one-controlled-failure.json`, `52-mixed-result-in-the-browser.json`) exist with
   timestamps immediately before and during that window, and the manager container had been restarted
   only two minutes before this agent's first check (`02:23:08Z`). This is consistent with the XR and
   browser/UI tracks named in `PICKUP.md`'s "Work in flight" section running concurrently or just
   before, not with anything this agent did. None of this agent's own checks showed an unexplained or
   internally inconsistent result — every check's precondition (baseline state, review outcome) was
   verified immediately before acting on it — so there is no concrete evidence of actual interference
   with these results, but the "one operator at a time" assumption in the assignment is worth the
   lead's attention if it was not already accounted for.

3. **Informational, not a defect: one incidental xrv9k backup failure during check 4(a)'s first
   (mistimed) attempt.** `"Error reading SSH protocol banner"` on a single Ansible connection attempt
   to xrv9k, while ceos/cjunosevolved/vjunos-switch all captured successfully in the same job. This
   was the manager's own routine "Save progress" capture (bound to all four registered nodes, exactly
   as it would be for any real user of this lab) — this agent did not open a session to xrv9k itself.
   The failure produced no commit and needed no cleanup (`capture_incomplete` is already terminal).

4. **Informational, not a defect: a `QA-wrong-password-ceos` credential profile is left registered
   on the lab (unassigned, `profile_id` reverted to `""` on the node).** The manager has no route to
   delete a credential profile once created (`clab-backup-ui/app/main.py` has `POST
   /api/labs/{lab_id}/profiles` but no matching `DELETE`), so the profile created for check 2 (via the
   manager's own API, as instructed) cannot be removed through the API. It carries no password in any
   public response and is not bound to any node; only its label and username are visible via
   `GET /api/state`. Left in place because there is no product-facing way to remove it and this agent
   may not edit product source, configuration, store data, or the manager's runtime state directly.

## Layer definitions used above

- **product** — through the real manager API (`manager_restore.py`, `failure_harness.py`, or raw HTTP
  with the correct `Origin`), exactly what the browser would drive.
- **device** — raw CLI, independent of the manager and the driver: `nodecli.py` (SSH, published
  containerlab logins) and `readback.py`/`square_check.py` built on it.
- **driver (direct)** — `app.restore_junos` imported directly and driven over a `paramiko` connection
  opened the same way `app.node_services.connect` does, bypassing `RestoreService` entirely (check 6).

## Limitations

- Check 4(a)'s first attempt used a coarse (~6 s) gap between the two HTTP calls and missed the busy
  window because the capture itself finished in ~3 s; the second, tight (~50 ms) attempt landed
  correctly and is the one graded. Both attempts are referenced above rather than only keeping the
  successful one.
- Browser/UI-level verification was not performed in this task (the assigned scope and tool set were
  product/device only); noting the gap rather than claiming visual coverage. (Other evidence files in
  this directory not authored by this agent, e.g. `50-`/`51-`/`52-`, suggest a separate track covered
  browser checks around the same time; this agent did not verify or rely on them.)
- `failure_harness.py`'s `armed-cut` and `restart-confirming` subcommands were written to the same
  standard as `submit-cut` (build identity, readback before/after, guaranteed iptables cleanup) but
  were not exercised live this run, because no check in this wave required arming-then-cutting or
  restarting the manager; B4/B5 on all three platforms already have separate PASS evidence from the
  prior QA run (`evidence/17-*`).
- xrv9k was out of scope by assignment; the one incidental capture failure against it (Defect/finding
  3) surfaced only because the lab's Git binding registers all four nodes for "Save progress", not
  because this agent addressed it directly.
