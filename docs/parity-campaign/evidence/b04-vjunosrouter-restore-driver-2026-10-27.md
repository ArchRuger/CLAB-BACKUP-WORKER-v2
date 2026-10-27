# B04 phase 1 evidence: the Junos restore driver on vJunos-router (nested derivative), 2026-10-27

Live evidence, driver layer only: `clab-backup-ui/app/restore_junos.py` called directly (one paramiko client
per call, as the manager connects) against `clab-parity-vrt`. The manager's API, its backups and the Load
workflow were **not** used (that is phase 2). Operator: `clab-network-specialist` for the lead; nobody else
touched the node during the runs.

**Nested derivative.** Every result here is on `local/juniper_vjunos-router:26.2R1.7-nested`
(`sha256:c85d25f77631…ee540`, see [b03](b03-vsrx-boot-2026-10-27.md) §7), a local build of the published image
for this host: the published `n24l/juniper_vjunos-router:26.2R1.7` cannot boot under nested virtualization on
the development VM (an official limitation of the image's CPU mode). The NOS inside is the same release, but the
published image itself is **blocked on this host and not proven here**.

- Node: 172.20.20.112, kind `juniper_vjunosrouter`; the NOS reports `Model: vmx`, `Junos: 26.2R1.7`. Login: the
  published default (`admin` / `admin@123`). The `parity` lab was redeployed at 01:40 UTC; the NOS booted at
  01:42:14 and answered `show version` over SSH at 01:59:23 (a bounded 15 s loop).
- Driver source: unchanged since release 1.30.28. `b04-vrt-main.json` and `b04-vrt-fail.json` state
  `uncommitted_changes_to_the_driver: false`. `b04-vrt-reboot.json` states `true` because this task's edit (the
  docstring and `SUPPORTED_KINDS`, nothing the direct calls execute) was written while the reboot run was in
  progress; the run had imported the module before the edit.
- Independent judgement as in the [vSRX record](b04-vsrx-restore-driver-2026-10-27.md): `nodecli.py` session,
  `readback.py`'s `statements()` comparator, the product's comparator as a cross-check only.

Configuration A: the node as found (management, logins, `chassis fpc 0 pic 0 number-of-ports 12`) plus a
description on `ge-0/0/0`, a `lo0` address, a `system login message` and a discard static route. B: the
description and the message changed, the route deleted, a prefix list and another static route added (3 missing,
4 extra against A). Candidate: A's hierarchical form, 75 lines. The image ships with `system root-authentication`,
so the driver added none (`root_authentication: present` throughout).

| Step | Result | Evidence |
|---|---|---|
| 1 SSH, version, readiness | PASS: an ordinary CLI session answers `show version` (vmx, 26.2R1.7) | `b04-vrt-main.json` |
| 2 A established and captured | PASS: 0 errors; 75 hierarchical lines, 17 statements | `b04-vrt-main.json` |
| 3 B made | PASS: B active by the markers; 3 missing, 4 extra | `b04-vrt-main.json` |
| 4 B -> A through the driver | PASS: armed in 44.2 s (load, `commit check` and `commit confirmed` are slow on this image); entry 0 with the token and `rollback pending`; confirmed from a fresh connection in 3.6 s; nothing pending; A by the independent comparator (0 missing, 0 extra), B-only statements gone; the product's comparator agrees | `b04-vrt-main.json` |
| 4 refusals of the confirmation | PASS: a confirm with a token that is not pending is refused | `b04-vrt-main.json` |
| 5 Persistence across `request system reboot` | PASS: last change a confirmed driver restore (B -> A); boot time 01:42:14 -> 02:10:37; SSH back 989 s after the command; A exact afterwards (0 missing, 0 extra) | `b04-vrt-reboot.json` |
| 6 Back to back | PASS: A -> B -> A, each armed (about 29 s), confirmed and read back equal, 69.5 s for both | `b04-vrt-main.json` |
| 6 A onto A | PASS: `no_op`, armed and confirmed, A unchanged | `b04-vrt-main.json` |
| 7 Dropped exclusive session | PASS: nothing left in the candidate, nothing active | `b04-vrt-main.json` |
| 7 Foreign uncommitted edit | PASS: named by `blocked()`, apply refused, the edit kept uncommitted and never activated | `b04-vrt-main.json` |
| 7 Foreign pending `commit confirmed` | PASS: `pending()` is `True`; apply and confirm refused; it rolled back on its own timer (seen after 132 s); node on A | `b04-vrt-main.json` |
| 7 Empty, truncated, EOS text, display-set text | PASS: refused before any command; no commit added | `b04-vrt-fail.json` |
| 7 Balanced but invalid candidate | PASS: rejected at load, discarded, nothing left in the candidate | `b04-vrt-fail.json` |
| 7 Bad credentials, unreachable address | PASS: `AuthenticationException`; `NoValidConnectionsError` after 3.1 s | `b04-vrt-fail.json` |
| No reboot during steps 4, 6, 7 | PASS | `b04-vrt-main.json` |

The management-loss case (a candidate without `system services`) was run on vSRX only; on this node the timed
recovery was shown by the foreign confirmed commit that rolled back by itself. Timing note for phase 2: arming
takes 29 to 44 s here (the driver's `COMMIT_TIMEOUT` is 180 s), against about 7 s on vSRX.

State left: vrt on configuration A (the B04 A statements added to the node as found), nothing pending, no
foreign edits; the NOS last rebooted at 02:10:37.
