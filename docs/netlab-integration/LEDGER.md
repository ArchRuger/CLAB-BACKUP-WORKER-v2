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

Status of this table: chunk 1 (milestone B). Upstream support is the engine's module/feature data; the
adapter exposes every module of the intent schema; generation tests cover OSPF (v2 and v3, dual stack)
and BGP on all four images through the real engine (`test_network_design.py`, `test_design_adapter.py`);
no live evidence yet; no UI page yet (API only, milestone C brings the page).

| Capability | cEOS | cJunosEvolved | vJunos-switch | XRv9k | Adapter | Generation tests | Live | UI path | Limitation / remaining work |
|---|---|---|---|---|---|---|---|---|---|
| IPv4 / IPv6 addressing | upstream yes | yes | yes | yes | pools, families, explicit prefixes and addresses, ledger | real engine, dual stack, /31 p2p, reorder determinism, collision fix | none | API | apply not implemented (D) |
| OSPFv2 / OSPFv3 | yes | yes | yes | yes | module `ospf`, area, process, timers, per-link cost/passive/network type | real engine on the square | none | API | live adjacency proof (D) |
| BGP (iBGP, eBGP, RR) | yes | yes | yes | yes | module `bgp`, AS, rr, communities, sessions, activate | real engine on the square (iBGP full mesh, RR flag) | none | API | live session proof (D) |
| IS-IS | yes | yes | yes | yes | module `isis` | schema only | none | API | generation fixture, live |
| EIGRP | no | no | no | no | module `eigrp` in the schema; refused per device by the capability model | refusal test | n/a | API | upstream has EIGRP on Cisco IOS/NX-OS only; none of the four images |
| RIPv2 / RIPng | yes | no | no | no | module `ripv2` | schema only | none | API | cEOS only among the four |
| DHCP / DHCPv6 | yes | no | no | no | module `dhcp` | schema only | none | API | cEOS only among the four |
| VLANs | yes | yes | yes | no | module `vlan`, `vlans` objects, link access/trunk | schema only | none | API | XRv9k has no vlan module upstream |
| VRFs | yes | yes | yes | yes | module `vrf`, `vrfs` objects | schema only | none | API | |
| LLDP | initial template | initial | initial | initial | always on (no module) | rendered in every initial file | none | API | management LLDP lines filtered at apply (D) |
| BFD | yes | yes | yes | no | module `bfd` | schema only | none | API | XRv9k has no bfd module upstream |
| Static routes | yes | yes | yes | yes | `routing.static` | schema only | none | API | |
| LACP / LAG / MLAG | yes | yes (passive LACP flag) | yes (passive LACP flag) | no | module `lag`, `lacp`, `mlag` | schema only | none | API | MLAG needs same-platform peers absent from the square |
| STP | yes | no | no | no | module `stp` | schema only | none | API | cEOS only among the four |
| VRRP | yes | yes | yes | yes | `gateway.protocol: vrrp` | schema only | none | API | |
| Anycast gateway | yes | yes | yes | no | `gateway.protocol: anycast` | schema only | none | API | XR profile lacks anycast |
| VXLAN | yes | yes | yes | no | module `vxlan` | schema only | none | API | |
| GRE | yes (`tunnel.gre` flag) | no flag | no flag | no | plugin `tunnel.gre`: not accepted by the schema yet | capability test | none | none | plugin allowlist (E) |
| WireGuard | no | no | no | no | plugin `tunnel.wireguard`: no template for any of the four | capability test | n/a | none | upstream: FRR, VyOS, OpenBSD, RouterOS only |
| Route policies / prefix lists / AS-path filters | yes | yes | yes | yes | `routing.policy`, `routing.prefix`, `routing.aspath` | schema only | none | API | |
| Redistribution | yes | yes | yes | yes | `<protocol>.import` | schema only | none | API | |
| Default origination | yes | yes | yes | yes | `bgp.originate`; per-session flag | schema only | none | API | |
| MPLS LDP / BGP-LU / L3VPN / 6PE | yes / yes / yes / no 6PE flag on eos? (see data) | yes / yes / yes / no | yes / yes / yes / no | yes / yes / yes / yes | module `mpls` | schema only | none | API | 6PE flag: XR only among the four |
| EVPN | yes | yes | yes | yes | module `evpn` (needs bgp and vxlan or mpls) | prerequisite test | none | API | |
| SR-MPLS | yes | yes | yes | yes | module `sr` (needs isis or ospf) | prerequisite test | none | API | |
| SRv6 | no | no | no | yes | module `srv6` | capability test | none | API | XRv9k only among the four |
