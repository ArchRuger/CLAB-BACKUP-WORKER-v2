# B04 phase 2 and B06-after: Load through the manager on vSRX and vJunos-router, and the vSRX kind's manager paths, 2026-10-27

Live evidence through the running manager on `http://127.0.0.1:8081` (its real API with its own Origin, as the page
calls it): backups, the restore preflight, the restore with the acknowledgement, the job poll. Operator:
`clab-network-specialist` for the lead, sole operator of `camp-vsrx` and `parity` during the runs. The device itself
is judged independently: a separate `nodecli.py` SSH session, `readback.py`'s `statements()` comparator against
configuration A's statements captured before any drift (kept outside Git), the B04 marker statements, entry 0 of
`show system commit`, and the NOS boot time. Phase 1 (driver layer) is in the
[vSRX](b04-vsrx-restore-driver-2026-10-27.md) and [vJunos-router](b04-vjunosrouter-restore-driver-2026-10-27.md)
records; A and B are the same as there (vSRX: 7 missing and 9 extra statements between them; vJunos-router: 3 and 4).

- Nodes: `vsrx` 172.20.20.121, `n24l/juniper_vsrx:23.2R2.21` (exact image); `vrt` 172.20.20.112,
  `local/juniper_vjunos-router:26.2R1.7-nested`: **nested derivative, published image blocked on this host**.
- Builds: until 02:50:01 UTC image `sha256:3ecaf01c48a3…` (built from 796892c); from 02:50:01 image
  `sha256:64b479fc16aa…` (built from 973668e, the same registry and driver plus page fixes). The coordinator restarted
  the manager at 02:50:01. **No job of this pass was in flight then** (the last ended at 02:49:44, the next began at
  02:52:54; none is `interrupted`). Two off-manager activities spanned the restart: the vSRX reboot wait and the mixed
  run's watch of the foreign 2-minute window on ceos. Both nodes were read back afterwards: A, 0/0, nothing pending.
  Runs on the newer build: the expired timer (`bfa4c013`), vSRX back to A (`ea4fd711`) and the vJunos-router
  persistence Load and reboot.
- JSON: [part A](b04-phase2-parta-vsrx.json), [vSRX](b04-phase2-vsrx.json), [vJunos-router](b04-phase2-vrt.json).
  They hold public jobs, preflight diffs (the manager redacts the login hash) and booleans and counts from the
  devices; no configuration file.

## Part A: the vSRX kind through the manager (B06-after)

| Step | Result |
|---|---|
| 1 Sync from the VM | PASS: `kind` juniper_vsrx, `platform` empty -> `juniper_vsrx`, label "Junos (vSRX)", profile "vsrx published default" kept, `credential_source` profile, readiness Choose NOS -> Ready. The node stays **disabled** after sync: `prepare_lab` maps a previously unknown kind but never enables it (by design). It was enabled through the node's PUT (`enabled: true`, platform and profile unchanged) -> 200 |
| 2 Without the profile | `credential_source` **inventory**, not the kind default: the lab's containerlab `ansible-inventory.yml` carries a login, equal to the published default (compared, not printed). So the order stops at the inventory and the kind default is not reached on this lab. Test login: `reachable`, "SSH login accepted and the CLI answered"; Test logins: started 2, node `ready` |
| 2 Profile back | `credential_source` profile; Test login `reachable`; Test logins `ready`. The profile wins over the inventory |
| 3 Backup | PASS: job `790b5d73` succeeded (1/1), file `.set`, restore artifact `…-0145b03d.jcfg` (`junos-hierarchical`), download name `vSRX_vsrx_2026-10-27_02-37UTC.cfg` (Content-Disposition of the device route), ZIP `camp-vsrx_2026-10-27_02-37.zip` (the device file, topology, annotations, manifest) |
| 3 Console row | PASS: `console: false`, "vsrx has no serial console: its kind (juniper_vsrx) does not expose one. Open CLI is the way in." |
| 3 Capture | PASS (start only): the map's link is drawn `vsrx:eth1` (the YAML's own name), `capture_interface` eth1, the VM lists eth0, eth1, lo and tap1 for vsrx; launch on eth1 -> 200 "Wireshark session started on the VM", ended -> 200. The `ge-0/0/0` -> eth1 rule (`topology.PORT_RULES`) was not exercised: no map port is named ge-0/0/0. The viewer was not opened and packets were not inspected |
| 4 Save to Git | not bound, not tested (`binding: null`; vsrx listed in `supported_nodes`) |

## Part B: Load through the manager

| Step | vSRX outcome | job | vJunos-router outcome | job |
|---|---|---|---|---|
| A backup (restore artifact) | succeeded, `.jcfg` | `790b5d73` | succeeded, 5/5, vrt `.jcfg` | `0d12eefb` |
| 5 B -> A | PASS: preflight eligible, 16 pending changes; double submit returns the same job; backing_up -> applying -> confirming -> applied -> `verified`; manager read-back 0 missing / 0 extra, `persistence: saved`; independent 0/0, all B-only statements gone, nothing pending, no reboot | `c49dd700` | PASS: the same, 7 pending changes | `d7a93a64` |
| 6 A onto A | PASS: preflight 0 pending, `matches_saved`; `no_op: true`, verified, A unchanged | `9dea698d` | PASS: `no_op: true` (stage `matched`) | `2d696218` |
| 6 back to back (B -> A, then A -> A at once) | PASS: both verified, 0/0; a second submit while a load ran -> 409 "Wait for the active backup, Git save, restore or lab operation to finish." | `0dd47c21`, `1eef2479` | PASS: the same | `2234ea20`, `256d7dfe` |
| 6 persistence over `request system reboot` | PASS: last change a manager Load B -> A (`399c9383`); boot 01:55:51 -> 02:47:23; SSH after 162 s; 22 lines, 0 lost, 0 new; A 0/0 | `399c9383` | PASS: last change a manager Load B -> A; boot 02:10:37 -> 02:59:29; SSH after 923 s; 17 lines, 0 lost, 0 new; A 0/0 | `77e5c49b` |
| 8 expired timer | PASS, see below | `bfa4c013` | not run (vSRX only, as assigned) | |

**Selected-device job** (parity, vrt only, `e6f5ec77`): verified. The safety backup covered vrt alone. The other four
(vsw, cjunos, xrv9k, ceos) kept the same container id and start time, the same configuration hash (generated lines
excluded) and the same newest commit before and after.

**Mixed job** (parity, vrt + ceos, `61282b8f`): ceos was prepared like `mixed_failure.py` does it. Another user's
EOS session (`configure session`, a Loopback778 description) was opened before the submit. Its
`commit timer 00:02:00` was sent the moment ceos's target reached `backing_up`, before the driver connected
(`armed_before_victim_connected: true`). The job ended `partial`, "1/2 node(s) restored and verified; 1 did not
complete.":
vrt `verified` (0/0, A independently), ceos `failed` "Configuration was not changed: Another change on this node is
already pending confirmation; this restore was not started." The manager left the foreign change alone: pending
right after the job, gone by itself after its 2 minutes (Loopback778 inactive). The four peers were unchanged
afterwards. ceos had not been drifted, so it needed no recovery Load.

**Expired timer** (vsrx, `bfa4c013`, 2-minute window). The node was driven to B, then A was loaded. A host
`OUTPUT` REJECT on 172.20.20.121:22 (`failure_harness.py armed-cut`; the manager uses host networking) was put in
place 9.6 s after submit, at the confirmation reconnect, just after `armed` (9.4 s). The rule was removed at
179.6 s; it was gone at exit.

Timeline: 02:53:04 target `confirming`, "Configuration loaded; reconnecting to confirm." The device undid the
change itself (newest commit 02:55:05 `by root via other`, 121 s after arming). The manager kept retrying (11
attempts) and, 1 s after the block was lifted (02:55:55), reported `rolled_back`: "The change was not confirmed in
time and the device undid it. Checked: the configuration from before the restore is active." Job `failed`, "No
node was restored. Existing configurations were preserved by the safety backup." Independent read-back: B, 0/6 A
markers, nothing pending, no reboot. Then A was loaded again (`ea4fd711`, verified, 0/0).

**Arming on vrt (step 9)**, from the manager's own stage timeline (applying -> armed): 28.4, 23.1, 25.2, 24.3,
24.0, 25.9 s, and 26.7 s in the persistence Load. From armed to settled: 2.8 to 4.3 s. Phase 1's driver
layer measured 29 to 44 s. vSRX: 6.4 to 7.1 s. No stage timeout bit. The driver allows 90 s for the load and 180 s
for each of `commit check` and `commit confirmed`. The manager's window counts from `connecting`, not from the
device's `commit confirmed`, and it gives up (`uncertain`) only 90 s past it. With the smallest window (2 minutes)
and a 26 s arm, the device's own rollback falls about 26 s after the manager's deadline, inside that grace. An
arm above about 90 s, or a device rollback late by more than the rest of the grace, would end `uncertain` instead
of `rolled_back`. That is the safe direction, but it was not observed.

## Facts for DEVICES.md

| Capability | vSRX (exact image) | vJunos-router (nested derivative) |
|---|---|---|
| Kind mapped on sync, settings kept | PASS (stays disabled until enabled) | not re-run (already mapped) |
| Logins: profile > inventory | PASS | PASS (inventory, Test logins ready) |
| Kind default login reached through the manager | not reached (inventory login present) | not reached (inventory login present) |
| Backup with restore artifact, download and ZIP names | PASS | PASS (`vJunos-router_vrt_<stamp>UTC.cfg`, `.jcfg`) |
| Console row (none offered) | PASS | not checked |
| Capture start on the linked port | PASS (start only) | not checked |
| Git save | not tested (lab not bound) | not tested (lab not bound) |
| Load B -> A, verified with read-back | PASS | PASS |
| A onto A (`no_op`) | PASS | PASS |
| Back-to-back Loads, busy refusal | PASS | PASS |
| Persistence over `request system reboot` | PASS | PASS |
| Selected-device job, peers untouched | not applicable (one device) | PASS |
| Mixed job with a controlled failure (partial, truthful) | not run | PASS (ceos refused, vrt verified) |
| Expired timer -> `rolled_back` after read-back | PASS | not run |

## Unexpected

- During my first back-to-back attempt, my own tool's poll stopped early (it did not know the job status
  `backing_up`) and drove vsrx to B while a running job's safety backup was in progress. The driver then replaced
  B (`no_op: false`), verified, and A read back 0/0 (`a1bc2344`). It is not counted as the A-onto-A run. It does
  show that a change made between submit and apply is replaced and reported truthfully.
- The vSRX data link (ping 10.9.9.2 from vsrx) failed 30 s after SSH came back from the reboot and answered 3/3
  later. Forwarding comes up after management.
- The vSRX container's Docker health is `unhealthy` while the NOS answers SSH, `show version` and Loads.
- Wording: an A-onto-A target says "Configuration replaced and verified…" although `no_op` is true. After a timer
  rollback the job says "preserved by the safety backup", but the device's own timed recovery is what preserved
  them.

State left: vsrx and vrt on configuration A (0 missing / 0 extra against A, nothing pending), ceos's foreign change
gone, both labs running, no iptables rule left.
