# Cisco IOS XRv9k 24.3.1 — live facts for `restore_iosxr.py`

Live verification against `xrv9k` (172.20.20.104) in the shared `restore-square` lab.
2026-09-20 ~23:09–23:57 UTC covered Parts 1–9 below (the driver's first version, inline-confirm
design). 2026-09-21 ~00:12–01:33 UTC (this rework, after an independent review) covers the
corrected §7, §9 (Part 4 rerun) and the new §§10–13: the `HOLDS_SESSION` design, the exact
`show configuration sessions` / `detail` shapes the parsers rest on, held-session confirm with a
concurrent fresh session, `release()`'s disconnect behaviour, and the no-op replace's real
behaviour. Device access only, through `docs/multi-platform-restore/tools/nodecli.py`'s `Session`
class from scratch scripts, and — for the Part 4 reruns only — through the finished
`app.restore_iosxr` driver connecting exactly like `app.node_services.connect`. Never through the
manager API (port 8081) and never through any other node in the square. Raw transcripts (contain
the lab's password hash) are under `~/research/multi-platform-restore/raw/*xrv9k*.log` (outside
Git); every hash shown below is `<redacted>`, the real value is only in the raw transcripts. The
node was left on configuration A with nothing pending at every checkpoint below and at the end of
this work (`show configuration sessions` empty, `show version | include uptime` continuous, i.e.
no reboot).

## Summary verdict (updated after the rework)

The whole-configuration replace, its native timed-recovery ARM, and the review diff all work
exactly as hoped in one native command. The real platform gap is still **confirmation is scoped to
the CLI session that armed it** (§7) — but the fix is no longer an inline confirm. §7's original
"only one concurrent session" claim was wrong: §2 already showed two sessions coexisting, and this
rework depended on it. `restore_iosxr.py` now sets `HOLDS_SESSION = True`: `apply_candidate()` arms
the trial and *stops*, leaving the channel open, in configuration mode, under the job's token in a
module-level table (`_HELD`); it never confirms before a fresh connection has proven management
survived. `confirm()` receives that fresh connection, reaches its CLI first, then sends the
confirming `commit` on the *held* channel — the only one that can make it stick. `release()` closes
the held channel without confirming, for the node's own timer to undo. This is proven end to end,
live, with the real driver, in the Part 4 rerun (§9) and §§11–13: apply while B is active leaves a
real, independently-observable outstanding trial while A is already active on the wire (§9a); a
genuinely fresh connection then confirms it (§9b, §11); releasing an armed trial without confirming
does not roll it back early — only the timer does, proven with timestamps (§9c, §12); a true no-op
replace is accepted and evidenced the same way but never creates an outstanding trial to confirm,
so the *service* never calls `confirm()` for it at all (§13); a trial armed by something other than
this driver is correctly reported as foreign, refused by `apply_candidate()`/`confirm()`, and left
to roll back on its own (§9e).

## 1. Save A / drift to B (task part a, b)

**Fact:** `show running-config` on the assigned base config (`lab/base-configs/xrv9k.cli`,
already deployed) begins with a timestamp line, `!! Building configuration...`,
`!! IOS XR Configuration 24.3.1`, `!! Last configuration change at ... by clab`, then real
configuration, and ends with a bare `end` line — matching the contract in `restore_drivers.py`
exactly.

**Proving command:** `nodecli.py xrv9k 'show running-config'` (`...-save-A.log`):
```
show running-config
Sun Sep 20 23:10:02.875 UTC
!! Building configuration...
!! IOS XR Configuration 24.3.1
!! Last configuration change at Sun Sep 20 22:27:46 2026 by clab
!
hostname xrv9k
...
end
```

**Drift to B:** changed `interface GigabitEthernet0/0/0/0`'s description, removed the
`192.0.2.4/32 Null0` static route, added `prefix-set B-ONLY` and `interface Loopback777` — all
three read back active after a plain `commit` (`...-verify-B.log`). This is the shape every
apply/no-op/compare test below starts from.

## 2. Whole-configuration replacement: `configure exclusive` and pasting hierarchy back in (part c)

**Fact — `configure exclusive` locks the whole configuration namespace, not just this session's
edits.** A second session cannot enter exclusive mode while the first holds it, and sees the
lock in the sessions table:
```
configure exclusive                                          (session 2)
Current Configuration Session  Line       User     Date                     Lock
00001000-000043a7-00000000     vty0       clab     Sun Sep 20 23:11:08 2026 *
Cannot enter exclusive mode. The Configuration Namespace is locked by another agent.
```
(`...-exclusive_test2.log` equivalent transcript; `show configuration sessions` from the second
session shows the same locked row.) `restore_iosxr.session_conflict()` -- called from `pending()`,
`blocked()` and the foreign-lock/trial check at the top of `apply_shell()` -- uses exactly this
command from EXEC mode before ever entering `configure exclusive` itself. (There is no
`pending_shell()` in this driver, unlike Junos/EOS: IOS XR's foreign-session check has to run
before the paste even starts, not after, so `session_conflict()` fills that role directly.)

**Fact — `!` is a comment, not "exit one level".** A naive line-by-line replay that sends every
`show running-config` line verbatim, including its `!` separators, silently drifts into the wrong
submode: after `grpc`'s own `vrf clab-mgmt` / `port 57400` / `no-tls` block, sending the *global*
`vrf clab-mgmt` line without first leaving `grpc` mode lands inside `grpc`'s own `vrf` subcommand
(itself named `vrf`), not the global VRF definition, and the next real line
(`description Containerlab management VRF...`) is then rejected as invalid in that context. Proven
by first reproducing the failure, then fixing it: `restore_iosxr._paste()` tracks the actual prompt
after every line (not the source text's `!` markers) and issues a plain `exit` only when the next
line's indentation needs one or more levels popped.

**Fact — plain `exit` pops exactly one level, matching indentation exactly**, confirmed with an
isolated three-level nest:
```
vrf clab-mgmt-test          -> (config-vrf)#
 address-family ipv4 unicast -> (config-vrf-af)#
exit                         -> (config-vrf)#
 address-family ipv6 unicast -> (config-vrf-af)#
exit                         -> (config-vrf)#
exit                         -> (config)#
interface Loopback778        -> (config-if)#
```
IOS XR also auto-pops on its own when the *current* mode has no matching command at all (e.g.
typing `interface X` from `(config-vrf)#` jumps straight to global and succeeds, since `vrf` mode
has no `interface` subcommand) — this only fails when the current mode has an unrelated command of
the *same name* (the `grpc`/`vrf` collision above), which is exactly why the driver always issues
its own explicit `exit`s rather than relying on that auto-pop.

**Fact — `root` does not work inside a prefix-set (and, by the same family, a route-policy or
if-block), only inside ordinary hierarchical submodes.** From `(config-pfx)#`, both `root` and
`show configuration changes diff` are rejected as invalid input; `exit` (or the construct's own
closing token) works correctly:
```
prefix-set TESTP-ROOT
 203.0.113.0/24 le 32
root
                                ^
% Invalid input detected at '^' marker.
```
vs.
```
prefix-set TESTP-EXIT
 203.0.113.0/24 le 32
exit                          -> (config)#
show configuration changes diff
+  prefix-set TESTP-EXIT
+    203.0.113.0/24 le 32
+  end-set
```
**Fact — a route-policy's own `exit` (leaving the *whole* route-policy, not an inner `if`) can
trigger a different, unexpected non-CLI prompt**, `Uncommitted changes found, commit them before
exiting(yes/no/cancel)? [cancel]:`, observed once when a fresh `route-policy NAME` block was left
with a second bare `exit` after already leaving its `if` block with a first `exit`. `end-policy`
(the literal token `show running-config` prints) does not have this problem — it always returns
cleanly to `(config)#`. Because of this asymmetry, `restore_iosxr.py` never uses a generic `exit`
to leave a prefix-set, route-policy or if-block at all: `CLOSERS = {'end-set', 'end-policy',
'endif'}` are sent as their own literal command, from inside the construct, exactly where
`show running-config` places them — proven for a combined prefix-set + route-policy + if/endif
candidate (`...-test_closers_combo.log`-equivalent): no rejections, and `show configuration
changes diff` shows the objects formed correctly (`+  prefix-set ...`, `+  route-policy ...
if ... then / pass / endif / end-policy`).

**Timing (part i, paste portion):** a clean 73-line whole-device paste of configuration A with the
fixed `_paste()` algorithm took 0.36–0.73s of device-observed wall time across five separate live
runs (measured inside the test script around the paste loop only).

## 3. Native replace + timed recovery in one command (part c)

**Fact:** `commit ?` in configuration mode lists `replace` and `confirmed` as independent
modifiers of the *same* `commit`, and they combine directly:
```
commit replace confirmed ?
  <30-65535>  Seconds until rollback unless there is a confirming commit
  minutes     Specify the rollback timer in the minutes
commit replace confirmed minutes ?
  <1-1024>    Minutes until rollback unless there is a confirming commit
```
`commit replace confirmed minutes <N>` (bounds: seconds 30–65535, minutes 1–1024) is therefore the
single native command giving both true whole-configuration replacement and a timed automatic
rollback — no `load`/`show commit changes diff`-plus-computed-replace workaround was needed.
`restore_iosxr.apply_shell()` always uses the `minutes` form with the caller's `confirm_minutes`.

**Fact — the confirmation is a raw, non-CLI prompt, not matched by the normal command dialog:**
```
commit replace confirmed minutes 2
This commit will replace or remove the entire running configuration. This
operation can be service affecting.
Do you wish to proceed? [no]:
```
There is no trailing prompt line after the colon; it must be read and answered with a raw
`send`/`expect`, never folded into `Shell.run()`'s echo/prompt trimming. `restore_iosxr.py` matches
this with `REPLACE_WARNING = re.compile(r'Do you wish to proceed\?\s*\[no\]:\s*$')` and
`shell.expect([REPLACE_WARNING, PROMPT], ...)`, answering `yes`.

## 4. Review diff before activation (part d)

**Fact — the right command is `show configuration changes diff` ("Show configuration changes to
be made during a replace operation"), not `show commit changes diff`.** The latter exists and is
valid, but only ever shows a plain-`commit`-style *merge* preview (only additions, never what a
replace would remove), which is the wrong preview for this feature — proven by running both after
the identical paste: `show commit changes diff` showed only the two changed/added lines (missing
the removal of the B-only prefix-set and Loopback777), while `show configuration changes diff`
correctly showed `-  interface Loopback777`, `-  prefix-set B-ONLY`, the changed description as
`#`, and the restored static route as `+`.

**Fact — a no-op replace diff is exactly the boilerplate header plus `end`, no `+`/`-`/`#` lines:**
```
show configuration changes diff
!! Building configuration...
!! IOS XR Configuration 24.3.1
end
```
`restore_iosxr._diff_has_changes()` checks for any line starting `+`, `-` or `#` after that header;
`no_op` is the negation.

## 5. Validation failures (part e)

**Fact — a syntactically bad line is rejected immediately and the paste continues** (this module
still aborts the whole candidate on any rejection, but the device itself does not stop):
```
this-is-not-a-real-command foo bar
                             ^
% Invalid input detected at '^' marker.
```
**Fact — redeclaring an existing prefix-set/route-policy is a `% WARNING`, not a rejection**, and
must not be treated as one:
```
prefix-set RESTORE-A
% WARNING: Policy object prefix-set RESTORE-A exists! Reconfiguring it via CLI will replace
current definition. Use abort to cancel.
```
`_is_rejected()` requires a line starting `% ` **and** the absence of the word `WARNING` in that
output.

**Fact — a semantic (commit-time-only) rejection was not reproduced live.** Duplicate IPv4
addresses across two different interfaces (a loopback and a loopback, and a loopback and a
physical `/31` peer), and a route-policy referencing an undefined `prefix-set`, were all accepted
by `commit` on this image without error. `show configuration failed` was `% No such configuration
item(s)` in every attempt (nothing ever landed in the failed buffer). **This is not proven live**;
`restore_iosxr.py` still checks the text returned after answering the replace-confirmed warning for
a `%`-rejection (the same `_is_rejected()` used everywhere else) so a real commit-time failure, if
one occurs on real hardware or another image, is still caught and aborted — but no live transcript
demonstrates that specific path succeeding.

**Fact — `abort` (not `end`) is the safe way to discard a candidate.** After `abort`,
`show configuration sessions` and `show configuration failed` are both empty; nothing is left
pending. A bare `end` while the candidate has *uncommitted* edits (before `commit replace` is ever
sent) instead raises its own non-CLI prompt, `Uncommitted changes found, commit them before
exiting(yes/no/cancel)? [cancel]:` — `restore_iosxr.py` never sends `end` while there might be
uncommitted state; on any failure before the replace-confirmed commit it sends `abort`, and after a
successful replace it does not need to leave configuration mode explicitly at all (the connection
is simply closed by the caller).

## 6. Timed recovery (part f)

**Fact:** armed `commit replace confirmed minutes 2` and never confirmed. `show running-config`
for the B-only artifacts was back after ~2 minutes (two independent trials: armed at 23:28:42,
reverted at 23:30:45; armed at 23:35:59, reverted at 23:39:02 — both 2–3 seconds past the nominal
2:00/3:00 windows, i.e. scheduling latency only). `show configuration commit list` records the
automatic revert as its own entry with `Client: Rollback`:
```
1    1000000006   clab   vty0:node0_RP0_CPU  Rollback   Sun Sep 20 23:30:45 2026
2    1000000005   clab   vty0:node0_RP0_CPU  CLI        Sun Sep 20 23:28:42 2026
```
`show version | include uptime` stayed continuous across every expiry (e.g. `1 hour 6 minutes` at
23:31, up from a ~22:25 boot) — **no reboot**, confirmed every time this was checked.
`restore_iosxr._last_commit_was_rollback()` uses exactly this `Client` field to tell
`confirm_shell()` that a change it finds nothing-pending-for was rolled back rather than confirmed.

## 7. Confirmation is scoped to the originating CLI session (part g) — the key finding, corrected

**Fact — a bare `commit` (or `commit confirmed` again) in the *same* session/channel that armed the
replace confirms it immediately and durably:**
```
commit
% Confirming commit for trial session.
```
after which `show configuration sessions` is empty and the change survives the window with no
further action (see also §8 for persistence).

**Fact — the identical command from a genuinely different, reconnected SSH session never confirms
it**, proven three separate ways, each from an independent `nodecli.py` process (i.e. a real new
TCP+SSH connection):
1. `configure` then bare `commit` → `No configuration changes to commit.` (worded identically to a
   genuine no-op; not a rejection, just never sees anything to confirm).
2. `configure` then `commit confirmed 90` (re-arming attempt) → the same `No configuration changes
   to commit.`
3. Staging an unrelated real change and trying to `commit` it while the other session's trial is
   outstanding → outright refused: `% Cannot commit because there is an unexpired trial/rollback
   session '00001000-00005b40-00000000'.` `end` afterwards prints `No changes will be saved because
   there is a concurrent trial configuration session.` (a plain informational line, not the
   scary y/n prompt, since nothing was actually staged in *this* session).
4. `configure exclusive` from the fresh session while the trial is outstanding is refused too:
   `Cannot enter exclusive mode. A trial commit is underway in another configuration session.`

This is genuinely tied to the originating CLI session's own identity, unlike Junos and EOS.

**Correction (2026-09-21 rework):** the original sentence above claiming these three probes reused
"the very same `vty0` line... since this image allows only one concurrent session" was wrong, and
the design built on it (confirming inline before `apply_candidate()` returns, so that a later
`confirm()` on a fresh connection was only ever a verification step) was rejected by an independent
review: it left no real timed-recovery window, because the change was already durable by the time
any reconnect could prove management survived. §2 already had the counter-evidence (a second
session coexisting while the first holds `configure exclusive`); this rework depended on it and
re-confirmed it under load: see the `xr-shapes-*` and `xr-trial-armed-open-*` raw transcripts (§10),
where two independent `nodecli.py` connections are open into the same device at once, one holding
an exclusive/trial session while the other probes `show configuration sessions`/`detail`, and again
throughout §§9, 12–13 with the real driver.

**New design: `HOLDS_SESSION = True`, never confirm inline.** `apply_candidate()` answers the
replace warning, gets positive evidence the trial is armed (§11), and *stops* — it never sends the
confirming `commit`. The channel and its paramiko client are kept open, in configuration mode,
under the job's token in a module-level table (`_HELD`), together with the client's peer address.
`confirm()` is later called by the service on a **fresh** connection: reaching that connection's own
CLI (`terminal length 0` etc.) is the proof management survived the replace; only then is the
confirming `commit` sent, on the *held* channel from `_HELD`, because that is the one whose identity
the node will actually honour. `release(token)` closes the held channel without confirming, for the
node's own timer to undo the change. Proven end to end with the real driver in §9 (Part 4 rerun)
and in detail in §§11–13.

## 8. Persistence (part h)

**Fact:** the confirming `commit` makes the configuration durable immediately; `show configuration
commit list` records it as a normal `CLI` commit indistinguishable in kind from any other. Unlike
the EOS image ("Autosave to startup-config on commit is disabled"), IOS XR has no separate
save-to-startup step here — there is no "startup-config" file to write, the commit database itself
is what persists. **Not live-tested:** actually rebooting/reloading the shared lab node to observe
survival across a reload (the shared-lab rules forbid restarting or redeploying any node); this is
inferred from the commit-database semantics above (`show configuration commit list` is described by
Cisco as the persistent commit history, not a volatile buffer) and is stated here as unproven by a
real reload.

## 9. Timing (part i)

Measured with `time.time()` around each phase of the actual `nodecli.Session`/driver calls, not
estimated:

| Phase | Observed |
|---|---|
| SSH connect + login + pagination setup (`terminal length 0`/`width`) | 0.3–0.6s |
| 73-line whole-device paste (fixed hierarchical algorithm) | 0.36–0.73s across 5 runs |
| `commit replace confirmed minutes N` round trip incl. the yes/no prompt | sub-second device time (test-harness numbers using fixed-duration polling reads were inflated to ~13s; the driver's `Shell.expect()` returns as soon as the pattern matches, not after a fixed sleep) |
| Same-session confirming `commit` | ~0.1–0.4s |
| End-to-end `apply_candidate()` (Part 4, real driver, real device) | 5.60s wall time including the full paste, diff, arm+confirm, and SSH channel setup/teardown |
| `confirm()` (Part 4, reconnect + verify) | 0.43s |
| Timed rollback actually firing after an unconfirmed arm | ~2–3s past the nominal window in both trials (2 min and 3 min windows) |
| (rework) `apply_candidate()` through the new `HOLDS_SESSION` path, full paste + arm + positive-evidence check, no confirm | 5.10–5.73s (`part4-official`/`part4-e-correct` events logs) |
| (rework) `confirm()` on a genuinely fresh connection (reach its CLI, then confirm on the held channel) | 0.64s |
| (rework) `release()` → natural rollback, arming channel never closed by us until after | 121.68–122.20s after `release()` was called, i.e. the nominal 2-minute window plus 1.7–2.2s scheduling latency, consistent with §6 |

Multi-line constructs proven to survive a paste: `prefix-set`/`end-set` (redeclared over an
existing one, and freshly created), `route-policy`/`if ... then`/`pass`/`endif`/`end-policy`
(nested two levels, including one where `if`/`pass` do not change the CLI prompt at all — see §11),
and the plain `!` comment lines throughout (correctly never sent as commands). Banner delimiters
(e.g. `banner motd ^C ... ^C`) are **still not live-tested**: not present in the assigned base
config, and this rework did not attempt one either (the risk of leaving the node in a genuinely
broken state while proving delimiter handling was judged not worth it against the 2-minute-window
rule). `restore_iosxr.validate_candidate()` now refuses any candidate containing a line matching
`^banner\b` instead of silently mis-pasting it (the previous version would have skipped the banner
body's blank/`!` lines as if they were comments, corrupting the paste); this is a refusal, not a
claim that banners are supported.

## 10. The exact `show configuration sessions` / `detail` shapes the parsers rest on

Captured with two independent `nodecli.py` connections open at once (S1 probes throughout, S2
opens/aborts the session under test), `~/research/multi-platform-restore/raw/20260921T0015*-xrv9k-
xr-shapes-*.log`. `show configuration sessions detail` is EXEC-only (`% Invalid input detected`
from inside configuration mode — proven when `show configuration sessions` was tried right after
`configure exclusive` in an early scratch attempt), so `session_conflict()` always calls it from the
operational prompt, before ever entering configuration mode (`apply_shell`) or after `reach_cli()`
alone (`pending`/`blocked`).

**Nothing open** — `show configuration sessions` prints nothing at all (no header row even).

**An open plain session** (S2 ran `configure`, no exclusive, no edits):
```
Current Configuration Session  Line       User     Date                     Lock
00001000-00007443-00000000     vty1       clab     Mon Sep 21 00:15:36 2026
```
```
  1) Session: 00001000-00007443-00000000  Mon Sep 21 00:15:36 2026
     Line: vty1                           Lock: None
     User: clab                           Client: CLI
     Process: config                      PID: 29763
     Node:                                Elapsed Time: unknown
```

**An exclusive lock, no trial** (S2 ran `configure exclusive`, no edits, no commit):
```
Current Configuration Session  Line       User     Date                     Lock
00001000-0000752d-00000000     vty1       clab     Mon Sep 21 00:15:38 2026 *
```
```
  1) Session: 00001000-0000752d-00000000  Mon Sep 21 00:15:38 2026
     Line: vty1                           Lock: Reserved
     User: clab                           Client: CLI
     Process: config                      PID: 29997
     Node:                                Elapsed Time: unknown
```
So the plain-vs-basic-table difference is exactly the trailing `*`, and `detail`'s difference is
`Lock: None` vs `Lock: Reserved` — `session_conflict()` uses the `detail` form (`LOCK_RESERVED`)
because the trial shape below turns out not to use the `*`/`Lock: Reserved` marker at all, so a
single consistent signal (the `detail` text) is needed for all three non-empty states.

**A trial outstanding** (S2 did a full, faithful paste of configuration A with one line changed,
then `commit replace confirmed minutes 2` and answered the warning — `full_paste_trial_shapes.py`,
`~/research/multi-platform-restore/raw/20260921T0058*-xrv9k-xr-fullpaste-trial-shape-main.log`):
```
Current Configuration Session  Line       User     Date                     Lock
00001000-00003595-00000000     vty0       clab     Mon Sep 21 00:58:15 2026
00001000-000035b1-00000000     vty0       clab     Mon Sep 21 00:58:16 2026
```
```
  1) Session: 00001000-00003595-00000000  Mon Sep 21 00:58:15 2026
     Line: vty0                           Lock: None
     User: clab                           Client: CLI
     Process: config                      PID: 13717
     Node:                                Elapsed Time: 5 sec.

  2) Session: 00001000-000035b1-00000000  Mon Sep 21 00:58:16 2026
     Line: vty0                           Lock: None
     User: clab                           Client: commit-confirm
     Process: cfgmgr_trial_co              PID: 13745
     Node:                                Elapsed Time: 4 sec.
```
**Fact:** once the replace is accepted, the exclusive lock is already released (both rows show
`Lock: None`) and a **second** session appears, `Client: commit-confirm` / `Process:
cfgmgr_trial_co...` (truncated in the device's own fixed-width output) — this is the one and only
reliable, EXEC-only signal that a trial (as opposed to a mere open or locked session) is
outstanding. `restore_iosxr.session_conflict()` returns `'trial'` when `Client: commit-confirm`
appears anywhere in `detail`, `'lock'` when `Lock: Reserved` appears (and no trial), `'plain'` when
the table is non-empty but neither, `''` when it is empty. `apply_shell()`'s own foreign-session
refusal only fires on `'trial'`/`'lock'` — a plain foreign session does **not** block a restore
(`configure exclusive` is granted right past it, proven in the same transcripts); the ordinary-
session/lock-without-trial cases are what the new `blocked()` reports instead (see "Part 2 note:
exact contract mapping" below).

**Fact — a dropped connection's session-table row lingers.** A script that is killed (SIGTERM via
`timeout`, or an uncaught exception) without sending `end`/`abort` first leaves its plain, unlocked
row in `show configuration sessions` for several minutes after the TCP connection is actually gone
(observed repeatedly across this rework's scratch scripts, e.g. `xr-rework-postwipe-check.log`
still showing a session from a script that had already exited ~9 minutes earlier, and again in
`xr-part4-e-retry` vs. the immediately following check). This is a real device quirk, not a driver
bug the driver's job is to fix: a leftover plain row correctly makes `blocked()` report "a
configuration session is open" (safe — a false block costs nothing but a retry; a false "not
blocked" could paste over someone's real work) until the device itself reaps it.

## 11. Positive evidence the trial is armed, without confirming

**Fact:** a successful `commit` (of any kind, including a whole-device replace) always resets the
*target* configuration buffer for that session to empty. `show configuration changes diff`
therefore compares "nothing" against the just-applied running configuration, and — because the
running configuration is never actually empty — always shows the entire thing as removable
(`-  hostname ...`, `-  interface ...`, one `-` line per top-level statement) immediately after a
replace is accepted, whether or not the replace itself changed anything. Proven in
`full_paste_trial_shapes.py`'s transcript: the pre-commit diff showed exactly the one staged change
(`#  interface Loopback0` / `#   description ...`); the *same command*, re-run on the *same channel*
0.2s after answering the replace warning, showed the full teardown-shaped diff instead. `apply_shell()`
uses this as its "positive evidence the trial is armed" check — `_diff_has_changes()` on that
post-commit diff must be true, or the caller could not actually tell the replace was accepted, and
raises `SessionLost` (proven with the fake device,
`test_apply_raises_session_lost_when_no_evidence_the_trial_armed`) rather than trust the mere
absence of a `%` rejection. This holds for a genuine no-op replace too (§13) — the target still
resets to empty even when it was already empty.

**Fact — nested `route-policy`/`if ... then`/`pass`/`endif`/`end-policy` where `if`/`pass` do not
change the CLI prompt at all.** Not separately re-proven live in this rework (§2/§9 already proved
the combined construct on the real device); modelled explicitly in the fake device
(`test_paste_nested_route_policy_if_endif_prompt_unchanged`) because the reworked `_paste()` tracks
submodes by prompt *change*, and an `if`/`pass` line that leaves the prompt exactly as it was (still
`(config-rpl)#`) never pushes its own stack entry — only `route-policy NAME` and (separately)
`end-policy` do. Blindly popping the stack on every `CLOSERS` token (`endif` included) therefore
transiently believes it has left the route-policy one line early; this never produces a wrong
command because `CLOSERS` tokens are always sent as their own literal text regardless of the
tracked stack, and the self-correcting reset (any time the real prompt comes back bare `(config)#`,
the tracked stack is forced to `[]`) fixes the bookkeeping the moment `end-policy` actually returns
there. `exit`/`root` are never sent to leave a prefix-set/route-policy/if-block, and no `exit` is
ever sent while the tracked stack is already empty (`test_exit_never_sent_at_bare_config_prompt`).

**Not re-proven live: the raw "Uncommitted changes...exit?" prompt from §5 firing during a real
paste.** §5 proved it can happen (once, leaving a fresh route-policy with a second bare `exit`); the
rework's own `_paste()` never sends a bare `exit` to leave a route-policy at all any more (CLOSERS
only), so reproducing the trigger live would need deliberately reintroducing the old bug. Instead
`_send_exit()` (used for every mode-popping `exit`, the only kind still sent) watches for that raw
prompt in its own `expect()` call, answers `cancel` (never blind `yes`, which would discard whatever
IOS XR considers uncommitted) and raises a controlled `RestoreError`; `apply_shell()`'s abort path
then aborts the candidate. Proven with the fake device only
(`test_uncommitted_exit_prompt_is_declined_and_raises`) — **not proven live**.

## 12. Held-session confirm with a concurrent fresh session; `release()`'s disconnect behaviour

**(a) A different channel cannot confirm someone else's trial** (unchanged fact from §7, re-proven
under the new design's own held-session bookkeeping with the fake device,
`test_confirm_uses_the_held_session_a_different_channel_cannot`): a bare `commit` from a channel
that is not the one that armed the trial answers `No configuration changes to commit.`, never the
confirming marker.

**(b) `confirm()` requires the fresh connection to answer before anything is sent on the held
channel.** Proven live in Part 4(b): `driver.confirm(client2, handle)` opens `client2` (freshly
connected by the caller, never touched before), reaches its CLI (`terminal length 0` etc. succeed),
and *only then* sends `commit` on the *held* channel from `apply_candidate()` — 0.64s end to end.
`test_confirm_requires_the_fresh_connection_to_answer_first` pins the ordering with the fake device.

**(c) `release(token)` closing the arming session does not roll the trial back early.** Proven live
in Part 4(c) with timestamps: `release()` called at t=0 (arm+0.00s), the configuration was still A
(the replace's effect) through t+113.4s, and was back to B (rolled back) by t+122.2s — i.e. within
the normal ~2–3s-over-nominal lateness of an *unreleased* trial (§6, §9). Whether the arming
channel is open or already closed makes no observable difference to *when* the rollback fires: it
is governed purely by the node's own timer, tied to the trial's own identity, not to the liveness of
the TCP connection that armed it. This was also true of the **foreign** trial in Part 4(e), armed
and then left running with its own arming session still open and untouched (never confirmed,
never released by us) — it rolled back at its own nominal time regardless.

**(d) `end` is safe on the held channel immediately after a successful confirm.** Proven live
(`full_paste_trial_shapes.py`): after the confirming `commit` answered
`% Confirming commit for trial session.`, `end` on the same channel returned cleanly with no
"Uncommitted changes...exit?" prompt (unlike §5's warning about a bare `exit`/`end` *before* a
replace is confirmed, when the candidate can still be seen as uncommitted). `confirm()` uses `end`
here, never `abort` (which is for discarding an uncommitted candidate, not for leaving a session
whose change is already durable).

## 13. The no-op replace does not create an outstanding trial

**Fact:** `commit replace confirmed minutes N` where the pasted candidate is byte-for-byte what is
already running still answers the replace warning and still shows the "positive evidence" pattern
of §11 (the target resets, so the post-commit diff still shows everything as removable) — but
`show configuration sessions detail` afterward shows only the plain `Client: CLI` session, **no**
second `Client: commit-confirm` row (`noop_pending_check.py`'s transcript; re-proven with the real
driver in the 2026-09-21 rework, `noop_lock_check.py`,
`~/research/.../xr-live2-noop-lockcheck-armed.log`):
```
  1) Session: 00001000-0000502f-00000000  Mon Sep 21 02:55:56 2026
     Line: vty0                           Lock: None
     User: clab                           Client: CLI
     Process: config                      PID: 20527
     Node:                                Elapsed Time: 5 sec.
```
`Lock: None` here, exactly like an ordinary plain session (§10): once the exclusive lock this same
session held moments earlier is released there is no text-level way to tell a genuine no-op's
lingering row apart from an ordinary open session; `session_conflict()` reports `'plain'` for it,
and clearing it is `release()`'s job (§14), not `pending()`'s. A bare `commit` on that
same (held) channel then answers `No configuration changes to commit.`, not the trial-confirming
marker, because there genuinely is no outstanding trial to confirm. `driver.pending()` correctly
returns `''` for this case, matching every other "nothing pending" case. **Design consequence:**
`restore.py`'s `_settle`/`once()` never calls `confirm()` for a true no-op restore at all — it sees
`pending()` is falsy, falls through to `capture()`+`compare()`, finds the configuration already
matches the desired state, and reports `applied` immediately; `release(token)` still runs
afterward and closes the held channel exactly as it does for a real change. Calling `confirm()`
directly and unconditionally (as an early version of this rerun's own scratch script did) raises
`RestoreError`, which is correct given that call was never one the real service would have made.
Task acceptance-check (d) ("apply A when A is active → no_op True, still armed and confirmed like
any change") holds at the level the manager and student ever observe — the job still ends up
`applied`/`verified`, having genuinely gone through `apply_candidate()`'s hold-and-evidence path and
`release()`'s cleanup — even though the *mechanism* by which that happens differs from a real
change (no confirming commit is ever needed or sent).

## Part 2 note: exact contract mapping (rework)

- `SUPPORTED_KINDS = ('cisco_xrv9k',)`, `RESTORE_FORMAT = 'iosxr-running-config'`,
  `HOLDS_SESSION = True`.
- `validate_candidate`: refuses empty text, text missing `!! IOS XR Configuration` in its first six
  lines, text whose last non-empty line is not `end`, or text containing a top-level `^banner\b`
  line — before any device is touched (proven by the "refused untouched" tests sending nothing to
  the fake device, and structurally identical for the real device since `apply_shell()` calls
  `validate_candidate()` before `reach_cli()`).
- `apply_candidate` / `apply_shell`: refuse untouched on a foreign trial/lock (`session_conflict()`,
  §10) → `configure exclusive` → hierarchical paste (§2, §11) → `show configuration changes diff`
  (the review diff) → `commit replace confirmed minutes <N>` (warning answered) → positive evidence
  the trial is armed (§11) → **stop, still in configuration mode, nothing confirmed** →
  `{'diff', 'no_op', 'confirm_minutes', 'handle': {'token': token}}`. The channel and its client are
  kept in `_HELD[token]` together with the client's peer address; the service does not close them.
- `confirm(fresh_client, handle)`: reaches the fresh connection's own CLI first (the proof
  management survived), looks up `_HELD[handle['token']]`; raises if the held session is gone;
  otherwise sends the confirming `commit` on the *held* channel and requires
  `'Confirming commit for trial session.'` in its answer; leaves configuration mode on the held
  channel with `end` (proven safe post-confirm, §5/§12); requires, from the fresh connection, that
  `session_conflict()` no longer reports a trial; releases the held session either way. See §12.
- `release(token)`: closes the held channel and client without confirming; never raises. See §12.
- `pending(client)`: `''` when `session_conflict()` reports nothing outstanding or a mere plain/lock
  session; the held token when it reports a trial *and* this process holds a session for the same
  peer address; `True` when it reports a trial this process does not hold. See §10, §13.
- `blocked(client)`: the two states `pending()` does not cover — a plain open session or an
  exclusive lock without a trial — as a single student-readable reason; `''` otherwise (including
  while a trial is outstanding: that is `pending()`'s job). See §10.
- `capture`: `show running-config` with the leading timestamp line and `!! Building
  configuration...` removed (`strip_generated_header`), proven in §1 and by the header-stripping
  unit tests.
- `compare`: `restore_compare.compare_indented` plus `ordered_blocks_differ()` against
  `IOSXR_ORDERED` (`route-policy`/`ipv4 access-list`/`ipv6 access-list`), mirroring
  `restore_eos.compare`. A pre-hashed `secret 10 $6$...` line round-trips byte-identical when pasted
  back verbatim (proven by the Part 4 zero-diff compare after a real restore), so unlike EOS's
  session diff there is no IOS XR-specific generated line left to exclude beyond the shared
  `!`/`end` filtering `compare_indented` already does.

## Part 4: live proof with the finished (`HOLDS_SESSION`) driver

Ran directly against the real node with `app.restore_iosxr`, connecting with paramiko exactly like
`app.node_services.connect` (own scratch scripts, never the manager on port 8081). Raw transcripts:
`~/research/multi-platform-restore/raw/20260921T0114*-xr-part4-official-events.log`,
`...T0121*-xr-part4-remainder2-events.log`, `...T0130*-xr-part4-e-correct-events.log`, plus the
plain `nodecli.py` checks before/after each part (`xr-part4-*check*.log`,
`xr-rework-candidateA.log`). Configuration A is `candidate_A.cli` (a saved `show running-config`
of the base config, matching the real restore-candidate shape byte-for-byte apart from the volatile
`Last configuration change` comment line, which `compare()` ignores like every other `!` line); "B"
is the same three-change drift as §1 (`GigabitEthernet0/0/0/0` description, the removed
`192.0.2.4/32 Null0` static, `prefix-set B-ONLY` + `interface Loopback777`).

**(a) Apply A over B; verify from an independent session that the trial is outstanding and A is
already active, while unconfirmed.** Drifted to B, then `apply_candidate(client, CANDIDATE_A,
confirm_minutes=2, token='part4-tok-1')` on a fresh connection: `no_op=False`,
`handle={'token': 'part4-tok-1'}`, 5.73s. Independently, from a *different* `nodecli.py` session:
`show configuration sessions` immediately showed **two** rows (the held CLI session plus a second
`Client: commit-confirm` row, exactly the shape proven in §10/§11) and `show running-config` already
showed configuration A in full (B-only artifacts gone, the static route back) — the replace had
already taken effect on the wire, only its confirmation was outstanding. `driver.pending(fresh
client)` returned `'part4-tok-1'` (our own token, matched by peer address, §10).

**(b) A fresh paramiko client + `confirm(fresh, handle)`.** `driver.confirm(client2, handle)` →
`{'confirmed': True}` in 0.64s. Independent readback: `compare(candidate_A, driver.capture(...))`
== `([], [])` (first attempt had a false positive from a scratch-script bug — a raw `nodecli.py`
capture that had not stripped the command echo/prompt the way `Shell.run()` does; refetched with
`driver.capture()` itself later in the same evidence chain, see the corrected compare in the
remainder run and again at the very end of this document) and `pending()` was `''`.

**(c) Drift to B again, apply, `release(token)` WITHOUT confirming.** `apply_candidate(...,
token='part4-tok-2')` while B was active: armed, unconfirmed (independent readback: A already on
the wire, same as (a)). `driver.release('part4-tok-2')` was called immediately (0.00s after arm);
`_HELD` was empty right after. Polling an *independent* connection every ~8-9s: the change was
**still A** through t+113.4s after `release()`, and had reverted to **B** by the t+122.2s poll —
i.e. release does not roll the change back early; only the node's own timer does, at the same
~120s-plus-a-couple-of-seconds lateness as §6, whether or not the arming channel is still open.
`show configuration commit list`'s newest entry was a `Rollback`; `show configuration sessions` was
empty afterward; uptime was continuous.

**(d) Apply A while A is already active.** After restoring A (a normal apply+confirm cycle),
`apply_candidate(..., token='part4-tok-4')` returned `no_op=True` with a normal `handle`. This is
where a genuine platform subtlety surfaced — see §13: a true no-op replace is accepted and evidenced
the same way as a real change (the positive-evidence check in `apply_shell()` passes, because the
target buffer still resets), but the device does **not** create an outstanding
`Client: commit-confirm` trial for it, so a bare `commit` on the held channel afterward answers
`No configuration changes to commit.`, not the trial-confirming marker. Calling `confirm()`
unconditionally in a test script therefore raises — this is not a defect: `pending()` correctly
reports `''` for this case (proven in `noop_pending_check.py`'s transcript), so the real service
(`restore.py`'s `_settle`/`once()`) never calls `confirm()` for a true no-op at all; it falls
straight through to `capture()`+`compare()`, sees the configuration already matches, and reports
`applied` — and `release(token)` still cleans up the held channel regardless, exactly as it does
for a real change. "Confirmed like any other change" is therefore true of the *outcome* (the
manager records the node as settled, correctly, without ever claiming a confirmation that did not
happen) even though the *mechanism* differs from a real change. §13 has the full transcript.

**(e) A foreign trial armed directly on the device (not through this driver).** The first two
attempts at this part armed the "foreign" trial with a bare one-line edit (`configure exclusive`;
`interface Loopback0`; `description X`; `commit replace confirmed`) **without** first loading the
rest of the configuration — a mistake, not a platform fact: `configure exclusive` does not clone
the running configuration into the target buffer the way EOS/Junos sessions do (see §2), so that
staged a replace of *nearly the entire box* (interfaces, VRFs, `grpc`, even the SSH server) down to
one interface. Every new SSH connection then failed with `SSHException('No existing session')` for
the whole ~2-minute trial window (`xr-part4-remainder2-events.log`, `xr-part4-e-retry-events.log`)
— an entirely expected consequence of removing the SSH server's own configuration from the active
trial, not a driver or platform defect, and not something the real driver can ever do (it always
pastes the full candidate). Redone correctly (`xr-part4-e-correct-events.log`) by calling
`app.restore_iosxr.apply_shell()` directly on a raw connection with a **full** paste of
`candidate_A.cli` with only the `Loopback0` description changed (armed outside `apply_candidate()`,
so nothing lands in this driver's own `_HELD` — a faithful simulation of a change armed by something
else): a fresh connection succeeded in 0.16s (no connectivity impact at all, confirming the above),
`pending(fresh)` correctly returned `True` (a trial exists, not held by us),
`apply_candidate(fresh, CANDIDATE_A, token=...)` correctly raised
`RestoreError('Another change on this node is already pending confirmation...')` without touching
anything, `confirm(fresh, {'token': 'should-not-arm-3'})` correctly raised (no held session of
ours) without sending a `commit`, and the foreign trial rolled back on its own at t+121.68s since
arm — the node read back as configuration A, `show configuration sessions` empty, nothing of ours
in `_HELD`.

**(f) `show version | include uptime`** was checked before, after and repeatedly during every part
above (via independent `nodecli.py` connections); it only ever increased, continuously, across the
whole rework session (about 2h27m at the start of Part 4 to about 3h9m at the end) — no reboot.

The node was left on configuration A with nothing pending: zero-diff `compare()` against
`candidate_A.cli` via `driver.capture()`, `show configuration sessions` empty, `_HELD` empty.

## 14. The second independent (Opus) review, 2026-09-21 continued: `release()`'s three shapes,
`confirm()`'s release ordering, the no-op test's contradiction, hardening (F1–F7)

Driver-only work (never through the manager, port 8081 untouched), against the same `xrv9k`
(172.20.20.104), 02:15–02:56 UTC. Scratch scripts under this session's own scratchpad
(`driver_iosxr_live2.py`, `noop_lock_check.py`, `integration_check.py`); raw transcripts under
`~/research/multi-platform-restore/raw/20260921T02*-xrv9k-*.log` (`xr-driver-live2*`,
`xr-live2-*`, `noop_lock_check` and the `xr-*-check*`/`xr-poll-rollback*` probes used while
recovering from two scripting mistakes described below). The node ends this section on
configuration A, nothing pending, no session row, uptime continuous (4h27m → 4h31m across this
section, no reboot).

### F1 — `release()` must leave configuration mode, not merely drop the connection

**The live fact the reviewer supplied** (transcript
`~/research/multi-platform-restore/raw/20260921T015540-xrv9k-mixed-foreign-trial.log`, captured
before this section's own work): typing `end` on the session that armed an outstanding
`commit confirmed` trial raises a raw, non-CLI prompt, not a normal command dialog:
```
end

You are exiting after a 'commit confirm' with an active rollback session.  If you exit the configuration awaiting confirmation will not be confirmed and the router will immediately rollback to the previous configuration.
Do you wish to exit? [no]:
```
That transcript stops there (never answered). This section answers it live, deliberately, both ways:

**Decision: answer `yes`.** `restore_iosxr._leave_held_configuration()` sends `end` on the held
channel before closing it and, if this exact raw prompt appears, answers `yes`. Proven live with
the real driver (`driver_iosxr_live2.py`, run recorded in `xr-driver-live2.json`):

- **(a) nothing outstanding** (a true no-op that never created a trial, §13): apply A onto A
  (`no_op: true`), `driver.pending()` empty while the token is still held (02:53:25Z), `release()`
  returns in **0.076s**, and an independent `show configuration sessions detail` right after (probe
  at 02:53:30Z, `xr-live2-noop-lockcheck-after` shows the same shape after the standalone
  `noop_lock_check.py` run too) is empty immediately — no raw prompt is engaged for this shape,
  matching `_leave_held_configuration`'s case (a): a plain `end` from a session with nothing
  outstanding returns straight to the operational prompt.
- **(b) a trial is still outstanding**: apply A over B under a token (armed, unconfirmed), then
  `release()` **without confirming**. `release()` itself returned in **0.736s** (02:53:50Z); an
  independent readback only **4.82s after `release()` returned** already showed **B active again**
  (02:53:55Z) and the session table empty — compare with §6/§9/§12(c)'s ~120–125s (the nominal
  2-minute window plus a couple of seconds of scheduling lateness) for the *previous*,
  never-confirmed-or-released design, and with the still-longer "several minutes" a merely dropped
  connection's row lingers for (§10). This is the acceptance check for F1: `release()` now answers
  the node's own "leaving now rolls back immediately" prompt with `yes` on purpose, so the previous
  configuration is active again in a handful of seconds (dominated by this proof's own paced
  reconnect, not the node), not minutes.
- **(c) the channel already dead**: `test_release_never_raises_when_the_held_channel_is_already_dead`
  (fake device; not separately proven live — a live equivalent would need killing the TCP
  connection out from under the driver mid-`release()`, which is exactly the scripting mistake
  §"Two mistakes" below made by accident twice, and every time `release()`/`confirm()`'s own
  `except Exception` swallowed the resulting `OSError`/`SessionLost` cleanly, so this shape is in
  fact incidentally proven live too, just not on purpose).

**Contract note for `restore_drivers.py`** (not edited here; this driver's owner should not touch
that file): the sentence "`release(token)` closes a held session without confirming, and the
service always calls it when the node is settled, so an unconfirmed change is left to the node's
own timer" is no longer exactly true for IOS XR. Suggested replacement sentence: *"`release(token)`
closes a held session without confirming; where the driver can, it leaves the node's configuration
cleanly first, which may itself trigger the node's own immediate rollback of a still-outstanding
trial rather than leaving it to the node's timer (IOS XR); otherwise an unconfirmed change is left
to the node's own timer."*

**Update (2026-09-21, independent follow-up review):** the lead has since adopted new wording along
these lines directly in `restore_drivers.py`'s own "``HOLDS_SESSION`` and ``release(token)``"
section (it now documents the immediate-IOS-XR-rollback behaviour itself). This entry is left
exactly as written above as the historical record of the finding, not rewritten to match.

**Limitations added by this follow-up (narrow independent review, 2026-09-21 continued):**
`_leave_held_configuration()` now also recognises the raw "Uncommitted changes found, commit them
before exiting(yes/no/cancel)? [cancel]:" prompt (§5) on the held channel's own `end` and leaves it
unanswered rather than sending `yes` or `no` (fake device only:
`test_release_when_end_raises_the_uncommitted_changes_prompt_never_sends_yes_or_no`). Two things
this does not prove:

- **Not proven:** whether `end` raises the raw "exiting after a commit confirm...rollback
  immediately" warning (F1(b) above) on a session whose own trial has already **expired** (rather
  than merely being open and counting down) was not tested, live or fake — every proof of that
  prompt in this document, and the new uncommitted-changes-prompt case just added, exercises `end`
  while the trial (or the uncommitted candidate) is still current. What the node answers to `end`
  once its own timer has already fired underneath a still-open session is unknown.
- The confirm path's own `end` immediately after a successful confirming commit (§12(d)) was
  captured through `full_paste_trial_shapes.py`,
  `~/research/multi-platform-restore/raw/20260921T0058*-xrv9k-xr-fullpaste-trial-shape-main.log`.

### F2 — `confirm()` must not release the held session on a fresh-connection failure

Proven live (`driver_iosxr_live2.json`, steps around 02:54:25Z): armed a real change (A over B)
under a token, then called `confirm()` with a fresh connection whose own channel was killed
(`channel.close()`) immediately after `invoke_shell()` returned, before `reach_cli()` could read
anything from it. `confirm()` raised `SessionLost` — `"The SSH session to the node closed before it
answered."` — and, checked immediately after with a *different* fresh connection,
`driver.pending()` still returned this token: the held session survived. A **second**, genuinely
good fresh connection then confirmed successfully in 4.34s, and an independent readback afterward
showed configuration A active with nothing pending. This is the fix: `confirm()` releases the held
session only once its own confirming `commit` has actually been attempted (success or failure);
a failure of the fresh connection itself, before that point, leaves the held session alone.

### F3 — the no-op replace creates no trial, but the session is still held and still needs releasing

Already covered above (F1 case (a)) and in the updated §13: the fake-device test this finding
named was rewritten (`test_apply_no_op_when_diff_has_no_changes_but_still_arms` →
`test_apply_no_op_is_accepted_and_evidenced_but_creates_no_trial` plus a new end-to-end test that
pins `pending(fresh) == ''` while held and an empty session table immediately after `release()`),
and the live proof above (`noop_lock_check.py`) shows the real `Lock: None` / `Client: CLI` text
this rests on.

### F4 — `pending()`'s peer-address ownership match: left as is

Not changed. `pending()` matches an outstanding trial to a held token by the node's peer address
(ip, port) because a fresh probing connection carries no token of its own. This is reliable given
an existing invariant, not a device fact: `RestoreService.guard_idle()`/`operation_busy()` (see
`app/lab_operations.py`) serialise every restore, backup and Git save **per lab**, and a running
lab node exists in exactly one lab, so at most one restore job — and therefore at most one held
IOS XR session — can be in flight for a given node's address at any time. Recording the arming
session's own id from `show configuration sessions detail` at arm time and matching on it instead
would add a second field to `_HELD` and a second command per `pending()` call for no live-observed
gain (no scenario in this session's testing, nor in the manager's own guards, produces two
concurrently held sessions for the same peer); left as is.

### F5 — narrow `except RestoreError` on failure/cleanup paths widened to `except Exception`

`_safe_abort()` now catches `Exception`, not only `RestoreError`, matching `_leave_held_configuration()`
and `_release_held()` (already broad): a failure path's own best-effort cleanup must never itself
raise, regardless of what kind of error a dead channel produces (this session hit exactly that:
`OSError('Socket is closed')` from a channel that was accidentally closed out from under the
driver — see "Two mistakes" below — and it needed to be swallowed the same way a `SessionLost`
would be).

### F6 — a reused token releases the previous held entry first

`apply_candidate()` now checks `if token in _HELD: _release_held(token)` before overwriting the
entry. Never expected from the real service (its tokens are per-attempt uuids); proven with the
fake device only (`test_release_replacing_a_reused_token_releases_the_previous_held_session_first`).

### F7 — the arming wait is bounded by the caller's own recovery window

`apply_shell()` now waits at most `_arm_timeout(confirm_minutes)` = `min(COMMIT_TIMEOUT,
confirm_minutes*60 - 30)` for the `commit replace confirmed` round trip (both the warning/`yes`
exchange and the post-commit positive-evidence diff), instead of the flat `COMMIT_TIMEOUT` (180s):
a commit slow enough to eat most of a short window must not be waited out to where "armed" is
reported with the trial already expired or about to expire. Proven with the fake device
(`test_arm_timeout_formula`, `test_apply_shell_bounds_the_arming_wait_by_the_confirm_window`); not
separately reproduced live — every live arm in this session and the original rework (§9) completed
in 0.9–6.4s, nowhere near either bound, so there was nothing live to time this against without
artificially stalling the device's own CLI, which risks exactly the kind of half-applied state the
2-minute-window rule exists to avoid.

### Integration point: the manager's Ansible capture vs. `driver.capture()`

Checked per the reviewer's request, read-only (`integration_check.py`, `driver.capture()` against
the live node, compared with the real restore-square backup artifact saved earlier tonight by the
running manager, `~/labs/CLAB-MNGR-DEV-LLM/restore-square/work/latest/xrv9k.xrcfg`): identical line
count once the volatile `!! Last configuration change ...` comment and the secret hash line are
excluded from both (74 vs. 75 raw lines; the one-line difference is exactly the leading
`!! Building configuration...` banner line, present in the Ansible/`network_cli` capture and
stripped by `strip_generated_header()`/`capture_shell()`), same maximum line length (117 in both —
no line wrapped or truncated by the Ansible terminal width), and the first differing line is that
same banner comment. **Result: no bug.** `restore_compare.indented_statements()` (used by both
`compare()` and, transitively, everything `restore.py` checks after a restore) already drops every
line starting with `!` — the banner line included — so this difference is invisible to every
comparison the product performs; the two captures agree on every line that matters. (`runner.py`'s
own `normalized()` is `M`odified on this branch by another owner and was read, not edited, per this
task's file scope.)

### Two scripting mistakes made and fixed while proving the above, and why the evidence above still stands

Both belong to this session's own `driver_iosxr_live*.py` proof scripts, not to `restore_iosxr.py`;
recorded here because they explain the extra `xr-*-check*`/`xr-poll-rollback*`/`xr-recover-check*`
transcripts and because the second one briefly left the node on a configuration that was neither
clean A nor clean B.

1. **A generic `call()` helper closed the connection after every driver call, including
   `apply_candidate()`.** Every other driver function closes its own channel before returning, but
   a `HOLDS_SESSION` driver's `apply_candidate()` deliberately keeps ownership of the connection
   (see `restore_drivers.py`) until `confirm()`/`release()` runs on it — closing it immediately, as
   the shared `call()` wrapper always did, silently killed the very session that had to answer the
   later confirming commit. This surfaced as `OSError('Socket is closed')` inside `confirm()`,
   twice, and was first (wrongly) suspected to be the node itself dropping a held session under
   connection load; both incidents rolled back cleanly on the node's own ~2-minute timer once
   noticed (confirmed by polling `show configuration sessions detail` to an empty table each time),
   proving nothing about the driver — the held channel was already gone before `confirm()` ever
   touched it. Fixed in the proof script (`apply_a()` now opens its own client and does not close it
   on success), not in `restore_iosxr.py` (whose own contract is unaffected: the driver never closed
   anything itself here, its caller did).
2. **A flawed "restore to A" bootstrap left B's artifacts merged into a captured "candidate A".**
   Recovering from mistake 1's first rollback, a bootstrap step replayed
   `lab/base-configs/xrv9k.cli` (a plain `configure`/`commit` merge, by design, for a *fresh* device)
   on top of an already-drifted-to-B node; it correctly restored A's specific field values but never
   removed B's own additions (`interface Loopback777`, `prefix-set B-ONLY`), since a merge commit
   only sets what it is told, it does not remove what it is not told about. The resulting
   `driver.capture()` was `A-with-B-leftovers`, and every following "apply A" in that run faithfully
   replaced the device with exactly that text — including the B leftovers — which is *correct*
   `commit replace` behaviour, not a driver defect: `is_a()` sanity checks failed because the test's
   own candidate was wrong, not because the replace was incomplete. Fixed by reversing the specific
   `drift/xrv9k-B.cli` changes by hand (`no interface Loopback777`, `no prefix-set B-ONLY`, restore
   the changed description and the removed static route) and re-capturing a clean candidate before
   the final, successful `driver_iosxr_live2.py` run reported above.
