# B05 phase 2 evidence: Network design applied live on vJunos-router and vSRX through the manager, 2026-10-27

Live evidence through the running manager on `http://127.0.0.1:8081` (its real API with its own Origin and JSON
bodies, as the page calls it): save the design, generate the plan, preview the fragments, the review job, the apply
with the acknowledgement, the job poll, the ownership ledger, then **Load** back to the starting configuration.
Operator: `clab-network-specialist` for the lead, sole operator of `camp-vsrx` and of `parity`'s `vrt` and `vsw`
during the runs (03:18 to 03:34 UTC). The other three `parity` devices (cjunos, xrv9k, ceos) were excluded from the
design (`role: exclude`) and never contacted by it.

- Manager: release 1.31.6, image `clab-backup:1.31.6` `sha256:64b479fc16aa…` (built from 973668e, the B05 phase 1
  mapping included), container started 02:50:01 UTC, **no restart during this pass**. netlab 26.09 in the image.
- Nodes: `vsrx` 172.20.20.121, `n24l/juniper_vsrx:23.2R2.21` (**exact image**); `vrt` 172.20.20.112,
  `local/juniper_vjunos-router:26.2R1.7-nested` (**nested derivative**: the published image crash-loops on this host);
  `vsw` 172.20.20.111, `n24l/vjunos-switch:23.2R1.14` (a kind proven earlier, used as vrt's OSPF neighbour).
- Independent judgement: every device read-back is a fresh SSH session of a scratch reader built on
  `docs/multi-platform-restore/tools/nodecli.py` (no application code): `show configuration | display set` compared as
  statement sets against the snapshot taken before step 1 (kept outside Git: it holds password hashes), entry 0 of
  `show system commit`, `rollback pending`, and the operational commands named below. Every read-back session is also
  the proof that management stayed reachable after that apply.
- JSON: [b05-phase2-live-apply.json](b05-phase2-live-apply.json): the intents, the generation records, the review
  payloads (the API masks statements; no token is reused), the public apply and restore jobs with their timelines. No
  device configuration file, no password hash.
- Fresh backups before step 1 (restore artifacts, `junos-hierarchical`): parity vrt + vsw `58945148`, camp-vsrx vsrx
  `7efe6727`. Starting state as found: vrt 17 statements (configuration A of B04), vsrx 22 (configuration A), vsw 13.

## parity: OSPF area 0 between vrt and vsw over ge-0/0/0

Design: IPv4 only, `modules: [ospf, routing]`, `ospf.area 0.0.0.0`, cjunos/xrv9k/ceos excluded, vrt's loopback pinned
to its existing `192.0.2.112/32`, one static `198.51.100.0/24 discard` on vrt. Plan `6d17f192`: vrt `10.1.0.0/31`, vsw
`10.1.0.1/31`, vsw loopback `10.255.0.2/32`; files `initial, routing, ospf` per device. The review left out `host-name`,
`static-host-mapping` and the `delete: ospf` tag on both.

| Step | Outcome | Job | Device read-back (independent) |
|---|---|---|---|
| P1 review | both ready, 8 additions each, 0 conflicts. vrt's existing lo0 address equals the plan's, so it is **not** an addition and not owned | review `83a05ab3` | |
| P1 apply (5 min window) | `succeeded`, both `verified`, `persistence: saved`; double submit returned the same job; arm 30.1 s (vrt), 27.8 s (vsw), applied 40.0 / 38.1 s after queueing | apply `a80b400c`, pre-backup `a5eef7ea`, post `91b33197` | vrt +8 / -0, vsw +8 / -0, exactly the review's additions; entry 0 `commit confirmed, rollback in 5mins` with `clabdsg-768d28bf` / `clabdsg-5ece8be2`, nothing pending. **OSPF Full both ways** (`show ospf neighbor`: vrt sees 10.255.0.2, vsw sees 192.0.2.112), `10.255.0.2/32` and `192.0.2.112/32` as `OSPF/10` routes, `198.51.100.0/24 Static Discard` on vrt. Ledger: 8 statements each |
| P2 no-op re-apply | review: both `no_op`, 0 of everything, diff `[edit]`. First submit refused 409 *Wait for the active backup…* (another worker's backup of `link-basics`, job `4a4f4c3c`, under the global guard; the token stayed valid). Second submit `succeeded`: "Every selected device already matched the plan; nothing was changed.", no backup taken | apply `1028cee3` | both 0 / 0 against P1, entry 0 unchanged (no commit) |
| P3 stale removal (static dropped from the design) | review: vrt 1 stale, removal `delete routing-options static route 198.51.100.0/24 discard`, vsw `no_op`. Apply `succeeded`, vrt `verified`, vsw `no_op` | plan `778f7de1`, apply `519702d7`, pre `c9df846a`, post `a1cf8f1b` | vrt -1 (`198.51.100.0/24` gone from the configuration and from inet.0), the **manual** `192.0.2.200/32 discard` kept, OSPF still Full; vsw unchanged. Ledger vrt 7 |
| P4a manual second address on vrt `ge-0/0/0.0` (`10.77.0.1/30`, committed by hand), same plan | review: `no_op`, 0 conflicts: the plan adds nothing under that interface, so the manual address sits beside the owned one and is left alone | review `922dcba1` | vrt 25 statements, manual address present |
| P4b conflict: the design renumbers the link to `10.2.0.0/31` | review: vrt **1 conflict** (the manual `10.77.0.1/30`: an addition next to an unowned address under the same parent, `EXCLUSIVE`), stale `10.1.0.0/31`; vsw ready (its removal is the created `family inet` container). `applicable: [vsw]`. Apply with vrt in the token refused **409** "Conflicts with manual configuration on vrt. Resolve them or take the settings over in the review." Not taken over | plan `67747a3d`, review `08f1e0dd`, apply refused | vrt and vsw 0 / 0 against before the attempt; nothing committed |
| Load back (step 3) | preflight vrt 8 and vsw 8 pending changes; restore `succeeded`, both `verified`, `persistence: saved` | restore `19953f6b` from backup `58945148` | vrt 0 / 0 and vsw 0 / 0 against the snapshot before step 1; nothing pending; OSPF not running (as found) |

## camp-vsrx: vsrx with host1 (a linux support host)

Design `V1`: IPv4 only, `modules: [ospf, routing]`, vsrx loopback pinned to its existing `192.0.2.121/32`, the
host1 link pinned to `10.9.9.0/24` (vsrx gets the existing `10.9.9.1/24`, host1 `10.9.9.2/24`), static
`198.51.100.0/24 discard`. netlab treats the host link as a stub: OSPF on `ge-0/0/0.0` is **passive**, so netlab
cannot generate an active one-sided OSPF peer toward a host. host1 is listed "A support host is generated only, never
applied."

| Step | Outcome | Job | Device read-back (independent) |
|---|---|---|---|
| V1 review | ready, 8 additions, 0 conflicts; nothing under `security` in the diff | | |
| V1 apply | `succeeded`, `verified`, saved; arm 5.0 s, applied 8.4 s | apply `10f5552a`, pre `55cd2de9`, post `282b9372` | +8 / -0; zone `trust` still binds `ge-0/0/0.0` (`show security zones trust`); ping host1 3/3; OSPF interfaces up, ge-0/0/0.0 passive, 0 neighbours; static active. Ledger 8 |
| V2 no-op | `no_op`, job `succeeded`, nothing changed | apply `ea61782b` | 0 / 0, no commit |
| V3 IS-IS (OSPF dropped) | review: 9 added (incl. `set security forwarding-options family iso mode packet-based`), 4 stale, removals `delete routing-options router-id 192.0.2.121`, `delete protocols ospf`. Apply `succeeded`, `verified` | plan `5d529884`, apply `03033ede`, pre `6569e1fc`, post `1a0204ee` | +9 / -4 exactly; IS-IS interfaces passive (no Junos neighbour on this lab); `show security flow status`: **ISO forwarding mode: packet based** at once; boot time unchanged (02:47:23); ping 3/3 |
| V4 MPLS added | review: 1 addition (`… family mpls mode packet-based`). Apply `failed`: "Configuration was not changed: The node failed the configuration check … the device refused it on semantic grounds." | plan `4838daf6`, apply `ba0cb6bb`, pre `d27725c6` | 0 / 0, nothing pending. Independent `commit check` in a private candidate: **"MPLS mode packet-based not allowed when [security policies] are configured."** (configuration A has the `trust → trust` policy) |
| V5 MPLS after the policy was removed by hand | apply `succeeded`, `verified` | apply `b4e62a24`, pre `38247bf7`, post `0b8eef3d` | `show security flow status`: **Inet forwarding mode: packet based**, MPLS packet based, ISO packet based, at once, no reboot (boot time unchanged); management and ping fine |
| V6 Load A | preflight 18 pending; restore `succeeded`, `verified` | restore `a5539b64` from `7efe6727` | 22 statements, 0 / 0 against A; flow status back to inet flow, MPLS drop, ISO drop **without a reboot**; policy back |
| Zone measurement (by hand on A, outside the design) | see below | | |
| Final Load A | preflight 3 pending; `succeeded`, `verified` | restore `ce1f3d65` from `7efe6727` | 0 / 0 against A, nothing pending, flow inet/MPLS drop/ISO drop, ping 3/3, boot 02:47:23 (never rebooted) |

### The vSRX facts

- **Zone handling of the design.** netlab writes no zone; the preparer sends nothing under `security` for these
  modules except the packet-mode lines; the `trust` binding of `ge-0/0/0.0` and its `host-inbound-traffic
  system-services ping` were untouched by every apply (read back after V1, V3, V5).
- **A protocol on a port without an admitting zone does not come up** (measured by hand on configuration A with an
  active `ospf area 0 interface ge-0/0/0.0 interface-type p2p`, host1 sending 10 crafted OSPF hellos with scapy that list
  vsrx as a neighbour, `show ospf statistics` cleared before each case):
  (a) in `trust` with only `system-services ping`: vsrx sent hellos (seen on host1), **received 0**, no neighbour;
  (b) **in no zone**: received 0, no neighbour, and ping to host1 failed 3/3 lost;
  (c) `trust` plus `host-inbound-traffic protocols ospf`: received 10, neighbour 10.9.9.2 reached **ExStart** (as far
  as a crafted one-sided peer goes). So OSPF, IS-IS or BGP over a vSRX data port need a zone that admits the protocol;
  the design does not write one. The prediction of phase 1 is now a measured fact (flow mode).
- **Packet-mode lines, 23.2R2.21:** neither needs a reboot here. `family iso mode packet-based` took effect at commit
  (ISO packet based); `family mpls mode packet-based` is **refused while any security policy exists** and, without
  policies, switched **IPv4 to packet mode too** (the firewall stops inspecting IPv4: zones and policies no longer
  apply) at commit; removing the lines (the Load) returned all three modes at once. No reboot was requested in any
  output read and none was done. A private `commit check` of the iso line printed no warning either.

## VALIDATION entries added (`clab-backup-ui/app/design_capabilities.py`)

`verified_on_image`, evidence this file: vSRX `static_routes` (exact image); vJunos-router `ipv4`, `ospfv2`,
`static_routes` (reason names the nested derivative). Everything else stays `generated_not_live_tested`, among it:
vSRX `ospfv2` and `isis` (applied and read back, but passive on a host link: no adjacency through the design, and a
zone rule is missing), vSRX `ipv4` (its addresses already existed, the design wrote none), vSRX `mpls_ldp` (refused
with policies; turns IPv4 to packet mode without them), vJunos-router `isis`, `bgp`, IPv6, `lldp` and every other
module (not applied), vSRX and vJunos-router `lldp` (applied, `show lldp` not read). vJunos-switch `ipv4`/`ospfv2`
were also applied here but that kind has no VALIDATION entry at all; left as it is.

## Unexpected, and what the lead may want to decide

- **The ownership ledger is not reconciled by a Load.** After the final Loads the ledger still lists vrt 7, vsw 8 and
  vsrx 14 owned statements that are no longer on the devices (`GET …/design/ownership`); the page shows them as *Owned
  settings* until the next apply intersects them with the device. Harmless for removal (stale removal only touches
  statements present), untruthful on display.
- **vSRX MPLS turns the firewall off for IPv4** without a word in the review: the review lists one addition, nothing
  in *expected changes*. Candidates for design review: an `IMAGE_LIMITS` refusal of `mpls_ldp` on vSRX, or an expected
  change with that sentence; and a zone rule (or a stated limit) for routing protocols over vSRX data ports.
- The global busy guard refuses a design apply while any other lab's backup runs (one 409 in P2 from another worker).
- vSRX raises two minor licence alarms ("about to expire") at each commit time; unrelated to the design.
- The live manager's message for a refused commit check names the class only ("on semantic grounds"), by design; the
  real reason above came from an independent `commit check`.

## Not tested, and why

IS-IS, MPLS, BGP adjacencies on either new kind (no second Junos neighbour on vsrx's lab; vrt was given OSPF only);
IPv6 (IPv4-only designs); the take-over path, the expired timer and lost-SSH paths of a design apply on these kinds
(the restore paths of B04 cover the transaction layer, not the design apply); the browser dialog (API only); the
published vJunos-router image (does not boot on this host).
