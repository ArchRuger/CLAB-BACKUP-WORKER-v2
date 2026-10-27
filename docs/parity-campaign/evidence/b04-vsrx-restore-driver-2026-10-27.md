# B04 phase 1 evidence: the Junos restore driver on vSRX, 2026-10-27

Live evidence, driver layer only: `clab-backup-ui/app/restore_junos.py` called directly (one paramiko client
per call, as the manager connects) against `clab-camp-vsrx-vsrx`. The manager's API, its backups and the Load
workflow were **not** used (that is phase 2). Operator: `clab-network-specialist` for the lead; nobody else
touched the node during the runs.

- Node: 172.20.20.121, kind `juniper_vsrx`, image `n24l/juniper_vsrx:23.2R2.21`
  (`sha256:fc9b9fa21ef5…c33051a`, see [b03](b03-vsrx-boot-2026-10-27.md)); the NOS reports `Model: vSRX`,
  `Junos: 23.2R2.21`. Login: the published default (`admin` / `admin@123`).
- Driver source: unchanged since release 1.30.28 (`git log -- app/restore_junos.py app/restore_shell.py`); every
  JSON record states `uncommitted_changes_to_the_driver: false` at its run.
- Independent judgement: the active configuration is read through `docs/multi-platform-restore/tools/nodecli.py`
  (its own SSH session, no application code) and compared by `readback.py`'s own `statements()` comparator; the
  product's capture and `compare_junos` are a cross-check only. Markers per kind of drift (an A value B changes,
  an A statement B deletes, B-only stanzas) are judged on the full `display set` text.
- Runner: a scratch script modelled on `tools/driver_junos_live.py`, run with `clab-backup-ui/.venv/bin/python`.
  Raw candidates (which hold password hashes) stayed in the session's scratch directory, outside Git.

Configuration A: the node's configuration as found (with the other worker's `ge-0/0/0` 10.9.9.1/24 and `trust`
zone, kept as asked) plus a description on `ge-0/0/0`, a `lo0` address, a `system login message`, a discard
static route and a security policy `trust -> trust` (permit). Configuration B: the description and the login
message changed, the static route and the policy deleted, and B-only additions (a prefix list, another static
route, a security zone `B04-B-ONLY` and a deny policy into it). B differs from A by 7 missing and 9 extra
statements. The candidate is A's hierarchical form (`show configuration | no-more`, 102 lines), as the backup's
restore artifact captures it.

| Step | Result | Evidence |
|---|---|---|
| 1 SSH, version, readiness | PASS: an ordinary CLI session answers `show version` (vSRX, 23.2R2.21); NOS booted 01:14:22 | `b04-vsrx-main.json` |
| 2 A established and captured | PASS: A committed in a plain session, 0 errors; 102 hierarchical lines, 22 statements | `b04-vsrx-main.json` |
| 3 B made | PASS: B active by the markers; 7 missing and 9 extra against A | `b04-vsrx-main.json` |
| 4 B -> A through the driver | PASS: armed in 7.8 s; `show system commit` entry 0 `commit confirmed, rollback in 3mins`, the token, `rollback pending`; confirmed from a fresh connection (`commit check`); nothing pending; A by the independent comparator (0 missing, 0 extra), every B-only statement gone; the product's comparator agrees | `b04-vsrx-main.json` |
| 4 refusals of the confirmation | PASS: a confirm with a token that is not pending is refused on a quiet node | `b04-vsrx-main.json` |
| 5 Persistence across `request system reboot` | PASS: last change a confirmed driver restore (B -> A); reboot answered yes; the NOS's boot time changed (01:14:22 -> 01:55:51), SSH back 165 s after the command; A exact afterwards (0 missing, 0 extra), zones and policy as in A | `b04-vsrx-reboot.json` |
| 6 Back to back | PASS: A -> B -> A, each armed, confirmed and read back equal, 16.6 s for both | `b04-vsrx-main.json` |
| 6 A onto A | PASS: the device reports no change (`no_op`), still armed and confirmed like any change; A unchanged | `b04-vsrx-main.json` |
| 7 Dropped exclusive session | PASS: nothing left in the shared candidate, nothing of it active | `b04-vsrx-main.json` |
| 7 Foreign uncommitted edit | PASS: `blocked()` names it; apply refused; the edit stays uncommitted in the candidate and never activates | `b04-vsrx-main.json` |
| 7 Foreign pending `commit confirmed` | PASS: `pending()` is `True` (no identity); apply and confirm refused; the foreign change stays pending and rolls back on its own 2-minute timer (seen after 132 s); node on A | `b04-vsrx-main.json` |
| 7 Empty, truncated, EOS text, display-set text | PASS: each refused by `validate_candidate` before any command; no commit added (10 entries before and after) | `b04-vsrx-fail.json` |
| 7 Balanced but invalid candidate | PASS: the node rejects the load ("rejected … while loading"), candidate discarded, nothing left in the shared candidate | `b04-vsrx-fail.json` |
| 7 Bad credentials, unreachable address | PASS: `AuthenticationException` at login; `NoValidConnectionsError` after 3.1 s (172.20.20.250, unused) | `b04-vsrx-fail.json` |
| No reboot during steps 4, 6, 7 | PASS: boot time unchanged | `b04-vsrx-main.json` |

## vSRX-specific findings (step 8)

| Question | Answer | Evidence |
|---|---|---|
| Does `commit confirmed <m> comment <token>` behave as on the other Junos kinds? | Yes: the same `show system commit` view (entry 0, comment line, `rollback pending`), `commit check` confirms it without committing the shared candidate, and an unconfirmed change rolls back at its timer (foreign 2-minute change, and the 1-minute management-loss case below, undone 61 s after arming, entry `by root via other`) | `b04-vsrx-main.json`, `b04-vsrx-specific.json` |
| Does `load override` keep the `security` hierarchy consistent? | Yes: after each replacement `show security zones` and `show security policies` list exactly the target's zones and policies (B: `B04-B-ONLY` zone and `B04-B-deny`; A: `trust` and `B04-A-allow`, `B04-B-ONLY` gone). The parser's `'0'` entry in the JSON `policies` lists is an artifact of the "Scope Policy: 0" field, not a policy | `b04-vsrx-main.json` |
| Does management on `fxp0` survive a replacement without zones or host-inbound settings? | Yes: a candidate of A without the whole `security` hierarchy (29 lines fewer) was armed, a fresh connection worked and confirmed it; only the built-in `junos-host` zone remained. A was then restored, zones and policy back. `fxp0` lives in `mgmt_junos` (`system management-instance`) and is bound to no security zone, so zones never gate management on this image | `b04-vsrx-specific.json` |
| What must a vSRX candidate keep so management is not lost? | `system services ssh`, the `fxp0` unit 0 address (10.0.0.15/24, the vrnetlab forward target), `system management-instance` and the `mgmt_junos` default routes: the same as on every vrnetlab Junos kind. Proven by the negative: A without `system services` armed with a 1-minute timer, fresh connections failed from 7 s (`SSHException`), the node undid the change at 61 s, SSH answered again at 72 s, and A was read back (0 missing, 0 extra), nothing pending | `b04-vsrx-specific.json` |
| Does the driver need a vSRX-specific rule? | No. The timed recovery is the protection, as on every kind; a candidate check for management statements is not needed for a restore of the node's own saved configuration. Pinned by `test_vsrx_security_hierarchy_is_loaded_verbatim_and_no_zone_is_required` in `tests/test_restore_junos.py` | unit test |
| Timing | Arming about 7 s; confirmation under 1 s | `b04-vsrx-main.json` |

Not covered here: the manager's backup with a restore artifact, Load through the real workflow, mixed jobs
(phase 2), and a timer expiry while the manager waits (the manager's reconnect loop): only the driver and the
NOS were exercised. State left: vSRX on configuration A (the other worker's `ge-0/0/0` address and `trust` zone,
plus the B04 A statements), nothing pending, no foreign edits.
