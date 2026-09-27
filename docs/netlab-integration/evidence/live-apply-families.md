# Milestone E: feature families applied live through the deployed product (`restore-square`, 2026-09-27)

Baseline: the lab redeployed to containerlab's startup configurations, then the product's OSPF + BGP plan applied to
all four routers through the API (`ceos` 104 statements, `cjunosevolved` 74, `vjunos-switch` 84, `xrv9k` 82, all
`verified`), so the deployed product owns every design statement on every device. Each family below is a change of
the live lab's design through `PUT /api/labs/{id}/design`, a generation, and `POST …/apply` on all four routers
(`scratchpad/product_apply.py`), followed by an independent control-plane read-back with `nodecli.py`.

| Step | Design change | Review (per device: added / removed / stale / removals) | Job | Control plane |
|---|---|---|---|---|
| E1 IS-IS instead of OSPF | `modules: [isis, bgp]`, `isis: {area: 49.0001, type: level-2}` | ceos 22/22/22/…; cjunosevolved 15/13/13/`delete protocols ospf`, `delete protocols ospf3`; vjunos-switch 13/10/10/the same two; xrv9k 22/22/22/`no router ospf 1`, `no router ospfv3 1` | `succeeded`, all four `verified`, saved; ledger moved to the new plan (ceos 91, xrv9k 82 statements) | IS-IS L2 adjacencies: xrv9k 2 Up (ceos, vjunos-switch), vjunos-switch 2 Up, cjunosevolved 2 Up, ceos: xrv9k UP at once and cjunosevolved INIT for the first minute, UP on the recheck (`e1-isis-recheck`: 2 UP); all iBGP sessions (IPv4 and IPv6) Established on every router |
| E2 VRF and static routes | `modules: [isis, bgp, vrf, routing]`, `vrfs: {red: {loopback: true}}`, the two host links attached to `red`, a static `192.0.2.0/24` discard route on every router | ceos 25/5/5/5 (`no network 172.16.0.0/24` and the IPv6 twin under the BGP address families, `no isis network point-to-point` and the IS-IS lines on `Ethernet3`); vjunos-switch 39/5/5/4 (`delete policy-options route-filter-list … 172.16.1.0/24 exact`, `delete interfaces ge-0/0/2 unit 0 family iso`, `delete protocols isis interface ge-0/0/2.0`); cjunosevolved 1/0/0/0; xrv9k 2/0/0/0 | `succeeded`, all four `verified`, saved (ceos 111, xrv9k 84 statements owned) | ceos `show vrf`: `red` IPv4 and IPv6 on Et3 and Lo1, `192.0.2.0/24` static via Null0; vjunos-switch `red.inet.0` with `172.16.1.0/24` and `lo0.1`, `192.0.2.0/24 Static Discard`; xrv9k `192.0.2.0/24 directly connected, via Null0` |
| E3 policy, redistribution, default origination | `routing.prefix.p1` (172.16.0.0/16), `routing.policy.from_isis` (match p1), per router `isis.import: {connected: true}` and `bgp.import: {isis: {policy: from_isis}}`, `bgp.originate: [0.0.0.0/0]` on ceos | ceos 15/0/0/0; cjunosevolved 13/0/0/0; vjunos-switch 13/0/0/0; xrv9k 12/0/0/0 | `succeeded`, all four `verified`, saved (ceos 126, xrv9k 96 statements owned) | cEOS: `route-map from_isis-ipv4/ipv6 permit 10` matching `prefix-list p1-*`; XRv9k: `route-policy from_isis` with `if destination in p1 then pass`; vJunos-switch: `policy-statement from_isis` with the `p1-ipv4`/`p1-ipv6` route-filter-list terms, and `0.0.0.0/0 *[BGP/170] from 10.255.0.1` learned from ceos (the default origination) |
| E4 VLAN access ports, VRF removed, XRv9k without the vlan module | `modules: [isis, bgp, vlan, routing]`, `vlans: {red: {id: 100}, blue: {id: 200}}`, ceos's host port access `red`, vjunos-switch's host port access `blue`, `vrfs: {}`, `nodes.xrv9k.modules: [isis, bgp, routing]` | ceos 14/33/33/14 (the routed host port's description, addresses, RA and IS-IS lines removed; `vlan 100`, `switchport access vlan 100`, `interface Vlan100` added); vjunos-switch 13/42/42/10 (`delete routing-instances red`, `delete interfaces ge-0/0/2`, the VRF's policy statements and the community, `delete protocols router-advertisement interface ge-0/0/2.0`); cjunosevolved and xrv9k `no_op` | `succeeded`: ceos and vjunos-switch `verified`, the other two "Already matches the plan" | cEOS: `vlan 100 red` on Et3, `Vlan100 up, line protocol up, 172.16.0.1/24`, `show vrf` without `red`; vJunos-switch: VLAN `blue 200` on `ge-0/0/2.0`, `irb.200 up 172.16.1.3/24`, no `red` routing instance |
| E5 VLAN `red` stretched over VXLAN with EVPN between ceos and vjunos-switch | `modules: [isis, bgp, vlan, vxlan, evpn, routing]`, both host ports access `red`, cjunosevolved and xrv9k on their own lists `[isis, bgp, routing]` | ceos 12/5/5/5 (the `Vlan100` description and the two BGP `network` lines of the VLAN subnet stale; VXLAN and EVPN added); vjunos-switch 31/13/13/7; the other two `no_op` | **`partial`**: ceos `verified`; vjunos-switch `failed` — "Configuration was not changed: The node failed the configuration check for the generated configuration; nothing was applied." (its exclusive candidate rolled back, no session left) | cEOS: `show vxlan vni`: VNI 100100 ↔ VLAN 100 on Ethernet3 and Vxlan1, the EVPN session to 10.255.0.3 `Estab(NotNegotiated)` (the other end never got the family); vJunos-switch unchanged (`vtep up` is the image's default interface) |
| E6 back to the two VLANs (VXLAN and EVPN dropped) | E4's design again | ceos 5/12/12/4 (`no interface Vxlan1`, `no address-family evpn` and `no vlan 100` under `router bgp 65000`, the VLAN description); the other three `no_op` | `succeeded`, ceos `verified` | cEOS: no VNI, `vlan 100 red` on Et3 kept; vJunos-switch unchanged (`blue 200`, `irb.200 up`) |

Observations:

- OSPF was removed at the process level everywhere (the created-ancestor rule), and every interface's OSPF
  lines went with it; nothing of the addressing or BGP changed.
- Moving the host links into a VRF made the global BGP `network` statements and the IS-IS interface lines of those
  links stale: the review removed exactly those leaves (Junos: the route-filter-list entries by value, the `family
  iso` and the IS-IS interface) and added the VRF, its loopback and the VRF-scoped BGP address families.
- netlab renders per-family route-maps for every address family the node's BGP knows (`from_isis-vpnv4` matching
  `prefix-list p1-vpnv4` on cEOS): the devices accept them; they are owned like every other generated line.
- A literal default route (`0.0.0.0/0`) is a prefix to originate, never an address: the management-overlap
  guard exempts a zero-length prefix (fixed for this step; `tests/test_design_intent.py`).
- A first E4 attempt put both host ports in one VLAN `red`: netlab gives every access port of a VLAN the VLAN's
  subnet (one segment), and the plan was refused as overlapping. Two things followed: the overlap check now knows
  that access ports of one VLAN share its subnet on purpose (`test_design_adapter.py`), and this lab's two host
  segments are two VLANs (host1 does not bridge them).
- A device's `modules` list now replaces the design's list (netlab's rule): XRv9k, which has no vlan module, kept
  `isis, bgp, routing` and reviewed as a no-op while the two switches gained the VLANs.
- The review masks a Junos removal that mentions `community` (`delete policy-options community …`) in the display;
  the command sent is the real one.
- Why vJunos-switch refused (probed afterwards in a private candidate, `commit check` only, nothing committed:
  `scratchpad/junos_check_probe.py`): `Error in parsing bridge domains/vlans: … configuration check-out failed`
  (beside the usual license warnings). netlab's `vjunos-switch` EVPN/VXLAN rendering of the VLAN is not accepted by
  this image; the apply failed cleanly per device, the job says `partial`, and cEOS's side was removed again by the
  next apply (E6). EVPN/VXLAN therefore stays *generated, not live-tested* on this lab.
- The lab ends the milestone at E4's design (IS-IS + BGP with policy and default origination, a static discard route
  per router, VLAN `red` on cEOS's host port and `blue` on vJunos-switch's, XRv9k without the vlan module), every
  statement of it owned by the deployed product.

