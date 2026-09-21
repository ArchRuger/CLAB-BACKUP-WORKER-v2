# cJunosEvolved 26.2R1.7-EVO — live facts for `restore_junos.py`

Independent live verification against `clab-restore-square-cjunosevolved` (172.20.20.102) in the
shared `restore-square` lab, 2026-09-20 ~23:09–23:33 UTC. Device access only, through
`docs/multi-platform-restore/tools/nodecli.py`'s `Session` class from scratch scripts — never through
the manager's own code, and never through the manager API. No other node in the square was touched.
Raw transcripts (may contain the lab's encrypted-password hash): `~/research/multi-platform-restore/raw/
2026920T23*-cjunosevolved-*.log` (outside Git). Every encrypted-password / hash value below is
`<redacted>`; the real value is only in the raw transcripts.

Scope: **live device investigation only.** No source, test or config file was edited. Findings and
recommended changes are reported here for the lead to act on in `restore_junos.py`.

## Lead's correction (2026-09-21), after the independent Opus review of this file

The observations below stand; two of the original conclusions did not, and the summary was rewritten.

- **The pending window is not "fragile".** In §4 the change "became permanent" after a `commit check`
  from another session, and `show system commit` then showed a new entry `by admin via cli`. That is
  the documented effect of `commit check` inside a pending window: **it confirms the pending commit.**
  The same was then shown deliberately on vJunos-switch (the marker `rollback pending` disappears at
  once and nothing rolls back after the window) and on this node by `tools/driver_junos_live.py`
  (`30-evo-driver-live.json`). The "timer silently re-armed" reading of §8 is a single observation
  with a confounding failed lock attempt and no controlled repeat; it is unexplained, not a finding.
- **There was a driver defect.** §4 proves that the plain `commit` the driver used to confirm with
  activates another session's uncommitted edit. Since 1.30.27 the driver confirms with `commit check`
  (which does not commit the shared candidate), arms every change under the job's token as a commit
  comment, refuses to start when the shared candidate holds somebody's uncommitted edits, and no
  longer falls back to a shared `configure` + `rollback 0` (§8 shows that discards their work).
- §2's "the synthesis source is exactly the admin user's password" is true for this single-login lab
  image only: the driver takes the first `encrypted-password` of the candidate, which in a multi-user
  configuration need not be a superuser's. Recorded as a limitation in the README.
- §6's "88 probes, 0 failures" came from a script whose output was not kept; read it as indicative.

## Summary verdict

The replace-and-confirm mechanism works on this platform (§3, §5). Settled here: the login lands in
the CLI and the driver's prompt patterns match (§1); `commit check` and `commit confirmed` reject a
configuration without `system root-authentication` while a bare `commit` only warns, so the driver's
synthesis is needed and works (§2); an unconfirmed change rolls back by itself, up to 35 s after the
nominal window, without a reboot (§5); a confirming plain `commit` activates foreign uncommitted edits
and `configure private` is refused while such edits exist (§4); `configure exclusive` is refused
while another session holds uncommitted edits, and `rollback 0` from a shared session discards them (§8).

## 1. Login landing and prompt handling

**Fact:** Login lands directly on the operational CLI prompt, not a shell: `admin@HOSTNAME> ` (hostname
is literally the string `HOSTNAME`, not replaced by the image). No `{master}` or other banner line
before the prompt was observed at any point in ~25 prompt transitions (op mode, config mode, or
`[edit]`). Configuration mode's prompt is `admin@HOSTNAME# ` preceded by a `[edit]` banner **line**,
which is on its own line above the prompt.

**Proving command:** raw landing text captured before any command was sent
(`nodecli.Session.log[0]`, saved in `...-01-landing.log`):
```
Last login: Sun Sep 20 23:09:03 2026 from 172.20.20.1
--- JUNOS 26.2R1.7-EVO Linux (none) 5.15.164-... #1 SMP PREEMPT ...
admin@HOSTNAME>
```
and `configure exclusive` → `...\n\n[edit]\nadmin@HOSTNAME# `.

**Verdict for the driver:** OK. `restore_junos.OPER = r'^[\w.\-]+@[\w.\-]+>\s*$'` and
`CONF = r'^[\w.\-]+@[\w.\-]+#\s*$'` both match the observed last line exactly (both regexes and
`nodecli`'s own prompt matcher only ever check the *last* line of buffered output, so the `[edit]`
banner line before the config prompt is irrelevant to matching). `reach_cli()`'s `SHELL` branch (root
shell before `cli`) was never exercised — this admin login never lands in a shell — so it remains
unproven live, but nothing here contradicts it.

## 2. Root authentication: when Evolved actually demands it

**Fact — saved A already carries a login password, but no `root-authentication`.** A real
`show configuration | no-more` capture of the live node (not the toy `cjunosevolved.cli` file, which
has no `system` stanza at all) includes a full `system` stanza with `login { user admin { ... encrypted-
password "<redacted>"; } }` and this device-inserted annotation:
```
services {
    ssh;
}
## Warning: missing mandatory statement(s): 'root-authentication'
}
```
This is only a **comment**, not an error, in plain `show configuration`.

**Fact — a plain `commit` of a config missing `root-authentication` succeeds.** Drifting the candidate
(et-0/0/0 description changed, `192.0.2.2/32` static route deleted, `B-ONLY` prefix-list and a
`198.51.100.0/24 discard` static route added) and running a bare `commit` (not `commit and-quit`, not
override) succeeded with no error:
```
commit
commit complete
```
(`...-03-drift-to-B.log`, 1.00s.)

**Fact — `commit check` on the same missing statement is a hard failure.** Loading the saved A
hierarchical text back with `load override terminal` (replacing B) and running `commit check` without
adding `root-authentication` failed exactly, with the per-mandatory-statement path Junos always uses:
```
commit check
[edit]
  'system'
    Missing mandatory statement: 'root-authentication'
[edit protocols]
  'ospf'
    warning: requires 'OSPF' license
error: configuration check-out failed: (missing mandatory statements)
```
(`...-04-load-override-A-check.log`, 0.11s.) So the rule is **`commit check` (and, proven next,
`commit confirmed`) reject a missing mandatory statement; a bare `commit` does not** — not a
boot-vs-later distinction as the driver's comment currently states.

**Fact — the driver's synthesis fix works.** Adding `set system root-authentication encrypted-password
"<the admin user's own hash, taken from the same saved-A candidate>"` (exactly what
`_ensure_root_authentication` does) made `commit check` pass:
```
commit check
configuration check succeeds
```
(0.24s, `...-05-root-auth-synthesis.log`.) The diff at that point showed only the added
`root-authentication` stanza (`show | compare`), confirming nothing else changed. Because the driver's
`SECRET_HASH` regex matches the **first** `encrypted-password "…"` in the candidate — here the admin
login's own hash — the synthesis source is exactly the admin user's password, as intended; on a real
saved backup (unlike the toy `cjunosevolved.cli` base-config file, which has no login stanza at all and
would raise `RestoreError` as documented) this hash is present, so synthesis is expected to succeed on
real restores.

**Verdict for the driver:** OK functionally (the code's order — `_ensure_root_authentication` before
`commit check`, and `commit check` before `commit confirmed` — is exactly what makes this pass live).
Needs a small **documentation fix**: the module docstring's "commits without it at boot but rejects any
later commit" should read "a bare `commit` tolerates the missing statement as a warning; `commit
check`/`commit confirmed` reject it" — this is a comment-only correction, not a behavioural change.

## 3. Replacement proof by independent readback

**Fact:** `show configuration | display set` after a full A→B→A cycle proves genuine replacement, not
a merge: the changed `et-0/0/0` description was restored to `"A to-ceos"`, the deleted `192.0.2.2/32`
static route came back, and both B-only statements (`prefix-list B-ONLY`, the `198.51.100.0/24 discard`
route) are gone. Confirmed twice independently (the exploratory cycle and the final clean cycle), e.g.
final verification (`...-26-final-verify.log`):
```
has B-ONLY: False   has A desc: True   has 192.0.2.2 route: True   has root-authentication: True
```
The last (`root-authentication: True`) is the synthesized statement, which — correctly — is now a
permanent part of the committed configuration, not a rollback candidate artifact.

**Verdict for the driver:** OK. `load override terminal` genuinely replaces (removes stale statements),
matching the module's design claim.

## 4. Pending view and confirmation

**Fact — `show system commit` while pending** (right after arming, `...-07-pending-view.log`):
```
0   2026-09-20 23:16:51 UTC by admin via cli commit confirmed, rollback in 2mins
    rollback pending
```

**Fact — `commit check` alone, run in `configure` from a fresh session while a confirm window was
pending, correlated with the change becoming permanent instead of rolling back.** In that one trial,
`commit check` returned a completely normal, side-effect-free-looking result:
```
commit check
configuration check succeeds
```
but ~24s after the window's nominal 2-minute expiry, `show system commit` showed a **new plain `commit`
entry, "by admin via cli"** (not the usual auto-rollback signature "by root via other"), and the running
configuration was still A, not B — the change was kept, unconfirmed, with no plain `commit` ever having
been issued by us (`...-08-commit-check-alone.log`, `...-09-after-wait-readback.log`). **This was one
trial; the mechanism is not fully isolated** — see the "needs change" note below and §8 for a second,
related trial (a failed `configure exclusive`/`configure private` attempt from another session also
seemed to interfere with a separate pending window, re-arming its timer once at `23:27:00` before it
correctly rolled back at `23:29:35`, `...-19` through `...-23-idle-watch.log`).

**Fact — when nothing touches the node during the window, it rolls back correctly (2/2 clean trials).**
Cycle 2 (`...-11` to `...-13`) and the pure idle-watch (`...-23-idle-watch.log`, polling every 8s for
150s with zero other commands) both rolled back exactly at the 2-minute mark (`+2s` and `+35s`
respectively), logged as **`by root via other`** (not `admin via cli`), and the running configuration
reverted to B in both cases.

**Fact — a plain confirming `commit` activates another session's uncommitted foreign edit.** With a
pending confirmed commit armed, a second session ran `set system location building FOREIGN-EDIT`
(uncommitted, then exited keeping it — `...-16-foreign-edit.log`). A third, fresh session then ran plain
`configure` → `commit` to confirm (mirroring the driver's `confirm_shell`). Result:
```
commit
commit complete
```
and the readback showed `FOREIGN-EDIT` was committed alongside the restore
(`has_foreign: True`, `...-17-confirm-plain.log`). The candidate is shared/global by default, so a
confirming commit necessarily commits whatever else is sitting in it too.

**Fact — `configure private` cannot be used to confirm while a foreign edit sits in the shared
candidate.** It fails outright and drops back to the operational prompt:
```
configure private
error: shared configuration database modified
```
(`...-21-private-confirm.log`). This is a different, shorter message than the `configure exclusive`
conflict in §8. Because it never enters configuration mode, there is no way from there to run `commit`
at all (both `show | compare` and `commit` typed afterwards, still at the operational prompt, correctly
gave `syntax error`/`unknown command` — no phantom commit happened here). **I could not test "does
`configure private` confirm without pulling in the foreign edit" as a private session actually entering
config mode alongside a foreign edit** — on this platform the precondition itself is refused, which is
itself the answer to the question asked, but it means the deeper mechanism (would a private commit ever
skip someone else's edits) is untested.

**Verdict for the driver:** *Needs a documented caution, no code defect.* The driver's own
`confirm_shell` always uses a fresh, non-exclusive, non-private `configure` + `commit` — proven correct
and matches what's described. The risk is entirely from **other** activity on the node during the
window: (a) `commit check` (or a failed lock attempt) from an unrelated session can turn the automatic
safety net off in a way that keeps the change instead of discarding it, and (b) a confirming commit will
also commit any other session's stray uncommitted edits, sight unseen. Recommend the operator-facing
docs say plainly: *do not use the CLI on a node with a manager-initiated restore pending confirmation.*

## 5. Automatic rollback

**Fact:** armed `commit confirmed 2` with nothing else touching the node rolled back on schedule twice:
- Cycle 2: armed `23:21:47`, rollback logged `23:23:49` (`+2:02`), `by root via other`.
- Idle-watch: armed `23:27:00` (a re-arm, see §4/§8), rollback logged `23:29:35` (from that re-arm,
  `+2:35`), `by root via other`.

**Fact — no reboot.** `show system uptime | match "System booted"` was identical (`2026-09-20
22:23:45 UTC`) before the first test and after every subsequent test, including after both rollbacks —
only the "ago" counter advanced. The NOS never restarted.

**Fact — B is genuinely restored, not just "unchanged".** After the cycle-2 rollback,
`show configuration | display set` showed `B-ONLY` present again and the description back to `"B changed
description"` — a real revert to the pre-restore state, matching the UI's "returned to its previous
configuration" wording.

**Verdict for the driver:** OK when nothing else touches the node during the window (see §4 for the
caution when something does).

## 6. Management continuity during apply and the pending window

**Fact:** a second script opened a fresh SSH connection to this node every 2s throughout cycle 1's
apply-and-wait window (~175s, spanning the `load override`/`commit confirmed` activation and the full
pending period): **88 probes, 0 failures, longest continuous-failure span 0.0s.** (heartbeat script
output, not committed — raw counts only, reported here.) Management access was never interrupted by the
replace, the confirm-timer arming, or (in that trial) whatever caused the timer not to roll back.

**Limitation:** this heartbeat run coincided with cycle 1 (the anomalous "kept, not rolled back" trial),
not with a clean, uninterrupted auto-rollback; it was not repeated for cycle 2/idle-watch. So continuity
specifically *during a genuine, un-interfered rollback event* was only checked by 8-second-interval
polling (idle-watch), which likewise saw no read failures, but that is a lower-resolution check than the
2-second heartbeat.

**Verdict for the driver:** OK as far as tested — no evidence of any management interruption in either
instrumented window.

## 7. Volume and timing

| Step | Value |
|---|---|
| Candidate body (hierarchical, no echo/prompt) | 1811 bytes |
| Candidate as echoed back by the device incl. header/prompt | 1858 bytes |
| `load override terminal` (send + Ctrl-D + read `[edit]`) | 1.51s (consistent across 5 runs) |
| `commit check` (fails, missing root-auth) | 0.11s |
| `commit check` (succeeds) | 0.24s–0.6s |
| `commit confirmed 2` | 1.09s |
| plain `commit` (incremental B, no override) | 1.00s |
| plain confirming `commit` | ~1s (not separately timed, same order as above) |

**Verdict for the driver:** OK — `LOAD_TIMEOUT = 90` and `COMMIT_TIMEOUT = 180` in `restore_junos.py`
are two orders of magnitude larger than anything observed; no timeout risk seen on this platform at this
candidate size.

## 8. Lock conflicts on the shared candidate

**Fact — `configure exclusive` while another session holds uncommitted edits (non-exclusive
`configure`):**
```
configure exclusive
Users currently editing the configuration:
  admin terminal pts/0 (pid 31745) on since 2026-09-20 23:25:28 UTC
      [edit]
error: configuration database modified
```
and the session drops back to the **operational** prompt (`...-14-point8-sessionB.log`).

**Fact — the driver's own fallback matches live behaviour.** Sending plain `configure` next (exactly
what `restore_junos.enter_config()` does on this failure) succeeds, with a warning:
```
configure
Entering configuration mode
Users currently editing the configuration:
  admin terminal pts/0 (pid 31745) on since 2026-09-20 23:25:28 UTC
      [edit]
The configuration has been changed but not committed
```

**Fact — `rollback 0` in the second session discards the first session's uncommitted edits.** After
`rollback 0` in session B, session A's own `show | compare` came back empty — the shared candidate,
including the other user's edit, was wiped:
```
rollback 0
load complete
```
then, back in session A: `show | compare` → empty diff.

**Verdict for the driver:** OK — this is exactly the fallback `enter_config()` already implements
(`configure exclusive` → on failure, plain `configure`), and it is safe *for the driver's own
correctness* because `rollback 0` (which the driver always runs next) discards anything foreign in the
candidate before loading the saved backup — so a stray foreign edit cannot silently merge into a
restore. It does mean a restore silently destroys another operator's unrelated uncommitted CLI session,
which is worth a one-line mention in the operator docs, not a code change (Junos's shared-candidate model
makes this unavoidable short of `configure private`, which the driver does not use and which, per §4, has
its own problems).

## What I could not run / open questions

- The root-shell prompt (`SHELL` regex, csh-shaped) was never exercised — this admin login never lands
  in a shell, so its exact prompt text is unproven live.
- The §4/§8 interference finding rests on one clear "kept instead of rolled back" trial and one "timer
  re-armed" trial, both coinciding with *some* other session touching configuration mode during the
  window; I have not isolated which specific action (bare `commit check`, or a failed
  `configure exclusive`/`configure private`) is the trigger, nor ruled out that both are symptoms of one
  underlying mechanism. A controlled repeat (one variable at a time) would need at least two more
  full 2.5-minute cycles than time allowed here.
- "`configure private` + `commit` confirming without touching a foreign edit" could not be observed
  directly: `configure private` itself refuses to start while the shared candidate holds another
  session's uncommitted edit, which pre-empts the scenario as asked.
- I did not attempt an interrupted-restore scenario (killing the manager process mid-sequence); only
  clean sessions and deliberate "leave it pending" tests were run.
- Node was left on configuration A (plus the synthesized `root-authentication`, which is a real,
  intended, permanent side effect of the restore, not leftover test debris) with nothing pending —
  verified by the final `show system commit` (`...-26-final-verify.log`) showing no `rollback pending`
  line and by `show configuration | display set` matching A. No other node in the square was touched;
  no manager API call was made; nothing was redeployed or restarted.
