# Feature-by-platform ledger

One row per requested capability and baseline image. *Upstream* is what netlab 26.09 renders on the mapped
profile (from the engine's own data, `clab-backup-ui/app/design_capability_data.json`); *adapter* is
whether this integration exposes it through the intent schema and the capability model; *generation
tests* names the automated evidence; *live* is what was proven on the exact image in this stream
(`docs/netlab-integration/evidence/`); *UI path* is where a student reaches it; *limitation* and
*remaining work* are honest. A row without live evidence is `generated_not_live_tested` at best; a
capability the upstream lacks on an image is `unsupported` there, which is a platform limit, never a
disguised gap of the integration.

Images: cEOS `n24l/ceos:4.35.0F` (`arista_ceos` → `eos`), cJunosEvolved `n24l/cjunosevolved:26.2R1.7-EVO`
(`juniper_cjunosevolved` → `vptx`, stand-in), vJunos-switch `n24l/vjunos-switch:23.2R1.14`
(`juniper_vjunosswitch` → `vjunos-switch`), XRv9k `n24l/cisco_xrv9k:24.3.1` (`cisco_xrv9k` → `iosxr`,
stand-in).

Status of this table: chunk 2 (milestone C). Upstream support is the engine's module/feature data; the
adapter exposes every module of the intent schema; generation tests cover OSPF (v2 and v3, dual stack)
and BGP on all four images through the real engine (`test_network_design.py`, `test_design_adapter.py`);
no live evidence yet; the Design tab (chunk 2) is the UI path for every row marked *Design tab*; apply is not offered yet.

Chunk 3 (milestone D) adds *Apply to devices…*: the rows below use the same per-kind columns to report
apply status (`live-proven` / `unit-tested only` / `not started live` / `implemented, unit-tested`), not
upstream or adapter support, which stays the meaning of the rows above. The provisioning transaction, the
review with conflicts and take-over, the ownership ledger and removals, and the interrupted-job recheck were
run on the four-node acceptance lab `restore-square` on 2026-09-27 and are recorded step by step in
`docs/netlab-integration/evidence/live-apply-{ceos,junos,iosxr}.md`; the apply UI (dialog, progress,
ownership and last-apply line) is implemented and unit-tested (`tests/test_network_design_ui.js`), and its
browser check on the deployed product is recorded in `docs/netlab-integration/evidence/browser-design-apply-ui.md`
(the review without applying, then an apply to cEOS from the real dialog).

| Capability | cEOS | cJunosEvolved | vJunos-switch | XRv9k | Adapter | Generation tests | Live | UI path | Limitation / remaining work |
|---|---|---|---|---|---|---|---|---|---|
| IPv4 / IPv6 addressing | upstream yes | yes | yes | yes | pools, families, explicit prefixes and addresses, ledger | real engine, dual stack, /31 p2p, reorder determinism, collision fix | none | Design tab | apply not implemented (D) |
| OSPFv2 / OSPFv3 | yes | yes | yes | yes | module `ospf`, area, process, timers, per-link cost/passive/network type | real engine on the square | none | Design tab | live adjacency proof (D) |
| BGP (iBGP, eBGP, RR) | yes | yes | yes | yes | module `bgp`, AS, rr, communities, sessions, activate | real engine on the square (iBGP full mesh, RR flag) | none | Design tab | live session proof (D) |
| IS-IS | yes | yes | yes | yes | module `isis` | schema only | none | Design tab | generation fixture, live |
| EIGRP | no | no | no | no | module `eigrp` in the schema; refused per device by the capability model | refusal test | n/a | Design tab | upstream has EIGRP on Cisco IOS/NX-OS only; none of the four images |
| RIPv2 / RIPng | yes | no | no | no | module `ripv2` | schema only | none | Design tab | cEOS only among the four |
| DHCP / DHCPv6 | yes | no | no | no | module `dhcp` | schema only | none | Design tab | cEOS only among the four |
| VLANs | yes | yes | yes | no | module `vlan`, `vlans` objects, link access/trunk | schema only | none | Design tab | XRv9k has no vlan module upstream |
| VRFs | yes | yes | yes | yes | module `vrf`, `vrfs` objects | schema only | none | Design tab | |
| LLDP | initial template | initial | initial | initial | always on (no module) | rendered in every initial file | none | Design tab | management LLDP lines filtered at apply (D) |
| BFD | yes | yes | yes | no | module `bfd` | schema only | none | Design tab | XRv9k has no bfd module upstream |
| Static routes | yes | yes | yes | yes | `routing.static` | schema only | none | Design tab | |
| LACP / LAG / MLAG | yes | yes (passive LACP flag) | yes (passive LACP flag) | no | module `lag`, `lacp`, `mlag` | schema only | none | Design tab | MLAG needs same-platform peers absent from the square |
| STP | yes | no | no | no | module `stp` | schema only | none | Design tab | cEOS only among the four |
| VRRP | yes | yes | yes | yes | `gateway.protocol: vrrp` | schema only | none | Design tab | |
| Anycast gateway | yes | yes | yes | no | `gateway.protocol: anycast` | schema only | none | Design tab | XR profile lacks anycast |
| VXLAN | yes | yes | yes | no | module `vxlan` | schema only | none | Design tab | |
| GRE | yes (`tunnel.gre` flag) | no flag | no flag | no | plugin `tunnel.gre`: not accepted by the schema yet | capability test | none | none | plugin allowlist (E) |
| WireGuard | no | no | no | no | plugin `tunnel.wireguard`: no template for any of the four | capability test | n/a | none | upstream: FRR, VyOS, OpenBSD, RouterOS only |
| Route policies / prefix lists / AS-path filters | yes | yes | yes | yes | `routing.policy`, `routing.prefix`, `routing.aspath` | schema only | none | Design tab | |
| Redistribution | yes | yes | yes | yes | `<protocol>.import` | schema only | none | Design tab | |
| Default origination | yes | yes | yes | yes | `bgp.originate`; per-session flag | schema only | none | Design tab | |
| MPLS LDP / BGP-LU / L3VPN / 6PE | yes / yes / yes / no 6PE flag on eos? (see data) | yes / yes / yes / no | yes / yes / yes / no | yes / yes / yes / yes | module `mpls` | schema only | none | Design tab | 6PE flag: XR only among the four |
| EVPN | yes | yes | yes | yes | module `evpn` (needs bgp and vxlan or mpls) | prerequisite test | none | Design tab | |
| SR-MPLS | yes | yes | yes | yes | module `sr` (needs isis or ospf) | prerequisite test | none | Design tab | |
| SRv6 | no | no | no | yes | module `srv6` | capability test | none | Design tab | XRv9k only among the four |
| Apply to devices: provisioning transaction (arm, confirm, read-back) | live-proven — 10 steps: create, no-op re-apply, manual-conflict + take-over, link renumber, BGP-peer removal, module drop, timer expiry, restart inside the recovery window, module drop again, re-create | live-proven — 5 steps: review, apply (both Junos devices at once), BGP-peer removal, module drop, re-create | live-proven — same run as cJunosEvolved | live-proven — create, no-op re-apply, module drop, re-add; a BGP AS identity change (drop `router bgp 65000` and add `router bgp 65100` in one commit) is refused by the device | `design_apply.py` + per-kind driver (`design_eos.py`, `design_junos.py`, `design_iosxr.py`), PROVISIONING.md §2 | `test_design_eos.py` (26), `test_design_junos.py` (27), `test_design_iosxr.py` (29), `test_design_apply.py` (39) | `evidence/live-apply-ceos.md` steps 1–10; `evidence/live-apply-junos.md` steps 1–5; `evidence/live-apply-iosxr.md` steps 1–5 | Design tab: plan card → *Apply to devices…* | the IOS XR AS-identity case needs two applies (drop, then re-add with the new AS); feature families beyond OSPF/BGP (VLAN, VRF, IS-IS, …) not yet applied live (E) |
| Apply to devices: review, conflicts and take-over | live-proven — a manual `interface Loopback99`, a manual BGP neighbour and a changed interface description conflict; *Take over these settings on this device* restores the design's line while the manual settings survive untouched | unit-tested only | unit-tested only | unit-tested only | `design_ownership.py` (conflicts, exclusive hierarchies, order-sensitive objects), PROVISIONING.md §3 | `test_design_ownership.py` (25), `test_design_apply.py::ConflictTakeoverTests` | `evidence/live-apply-ceos.md` steps 3, 3b | Design tab: review dialog, take-over checkbox | take-over proven live on cEOS only; the Junos and IOS XR conflict/take-over path is unit-tested, live pending (E) |
| Apply to devices: ownership ledger and removals (created-ancestor collapse) | live-proven — one `no neighbor X` when every line of a neighbour is stale; `no address-family` removes the family's relocated `network` statements by name first; link renumber, peer removal, module drop, re-create | live-proven — created ancestors limited to the device's own `show`-rendered blocks; peer removal, module drop, re-create | live-proven — same run as cJunosEvolved | live-proven — module drop (`no router bgp 65000`, `no router ospf 1`, `no router ospfv3 1`) | `design_ownership.py`, the lab's private `network_ownership` key, PROVISIONING.md §3 | `test_design_ownership.py` (25), `test_design_apply.py` (ledger persistence in the settle and restart paths) | `evidence/live-apply-ceos.md` steps 4–6, 9–10; `evidence/live-apply-junos.md` steps 3–5; `evidence/live-apply-iosxr.md` step 5 | Design tab: Advanced → *Owned settings* | ledger read-back for feature families beyond OSPF/BGP not yet live-tested (E) |
| Apply to devices: interrupted job, restart recheck | live-proven — the manager process killed right after arming: a new process 155 s later found the recovery timer expired and reported `rolled_back`; a second run killed and restarted inside the recovery window found the manager's own pending session, confirmed it, `write memory`, and verified | not started live | not started live | not started live (the held-session mechanism itself is unit-tested only) | `design_apply.py` restart reconciliation, PROVISIONING.md §4 step 4 | `test_design_apply.py::RestartReconciliationTests` | `evidence/live-apply-ceos.md` steps 7–8 | Design tab: apply jobs list, *Interrupted* status with the per-device read-back wording | proven live on cEOS only; Junos and IOS XR restart-inside-the-window not yet run live (E) |
| Apply to devices: apply UI (dialog, progress, ownership, last-apply line) | live-proven — `evidence/browser-design-apply-ui.md` (review, then an apply from the dialog) | implemented, unit-tested (the dialog is platform-independent) | implemented, unit-tested | implemented, unit-tested | `network-design.js` (`designApplyDeviceMarkup`, `designApplyProgressMarkup`, `designApplyOwnershipMarkup`, `designApplyLastLineMarkup`) | `test_network_design_ui.js` (39 total, 13 new for the apply dialog, progress, ownership and last-apply line) | pending — no browser check has run against the deployed product for the apply dialog | Design tab: plan card → *Apply to devices…*, apply jobs list, Advanced → Owned settings | needs a `check_design_live.py`-style pass on the dev VM before "pending" is lifted (E) |

Intentionally removed: none — every rule in PROVISIONING.md that changed after the live run (its §8) is a
fix folded back into the drivers and the ownership algebra, never a dropped capability. Still open for
milestone E/F, none of it started: live tests for feature families beyond OSPF/BGP (VLAN, VRF, IS-IS, …),
the `tunnel.gre` plugin and the rest of the plugin allowlist, a secret-reference model so protocol
passwords can enter the intent (`password` and key attributes are refused by name today), design export
through the student's Git save, VM sync of a generation's artifacts, and packaging/release of milestone D
itself.
