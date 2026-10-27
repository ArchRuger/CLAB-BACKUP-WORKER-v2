# B05 phase 1 evidence: Network design for vJunos-router and vSRX, the static half, 2026-10-27

Static, unit and real-engine generation evidence only. No device, lab, VM helper or manager instance was touched:
the live nodes `clab-parity-vrt` and `clab-camp-vsrx-vsrx` belonged to B04 during this pass and were not contacted.
Nothing here is a live-device validation; every capability of both kinds stays `generated_not_live_tested` until the
live apply and read-back of phase 2.

Engine: `networklab` 26.9 (`netlab version`: 26.09) in `clab-backup-ui/.venv`, offline.

## 1. What netlab 26.09 says about the two devices

Read from `.venv/lib/python3.12/site-packages/netsim/devices/` and the engine's resolved defaults.

| | `vjunos-router.yml` | `vsrx.yml` |
|---|---|---|
| Description | vJunos Router (similar to vMX) | Juniper vSRX 3.0, support level best-effort ("we don't test them on vSRX") |
| Parent | `vmx` (whose parent is `junos`) | `junos` |
| containerlab node kind in the profile | `juniper_vjunosrouter`, image `vrnetlab/juniper_vjunos-router:26.2R1.7` | `vr-vsrx` (the old name of `juniper_vsrx`), image `vrnetlab/juniper_vsrx:21.3R1.9` |
| Interfaces | `interface_name: ge-0/0/{ifindex}`; clab `eth{ifindex+1}` | inherited from `junos.yml`: `ge-0/0/{ifindex}`, `ifindex_offset 0`; clab `eth{ifindex+1}` |
| Management | `mgmt_if: fxp0` (from `junos.yml`) | `fxp0` |
| `netlab_device_type` | `vjunos-router` | `vsrx` |
| Profile `features:` block | evpn (irb, asymmetrical_irb, multi_rt, bundle vlan_aware, transport vxlan), tunnel.gre [vrf, ipv4], vlan (model router, `irb.{vlan}`, `{ifname}.{vlan.access_id}`, mixed_trunk, native_routed), vxlan | gateway.protocol [vrrp], lag.passive, tunnel.gre [vrf, ipv4], vlan (model router, `{ifname}.{vlan.access_id}`, mixed_trunk false, native_routed) |
| Modules (`netlab show module-support --system`) | bfd bgp evpn gateway isis mpls ospf routing services sr vlan vrf vxlan | bfd bgp gateway isis lag mpls ospf routing services sr vlan vrf |

Resolved for this integration's catalogue (`design_capabilities.resolve`, after the change):

- Both kinds, `generated_not_live_tested`: ipv4, ipv6, lldp, ospfv2, ospfv3, isis, bgp, bfd, static_routes, vrf, vlan,
  route_policy, prefix_list, aspath_filter, redistribution, default_originate, mpls_ldp, l3vpn, sr_mpls, vrrp, gre.
- vJunos-router only: evpn, vxlan (both shown `retired` by the product policy), anycast_gateway. vSRX only: lag, lacp.
- Both kinds, `unsupported` (engine): eigrp, ripv2, ripng, stp, srv6, dhcp, dhcpv6, mlag, bgp_lu, sixpe, wireguard;
  vJunos-router also lag, lacp; vSRX also evpn, vxlan, anycast_gateway.
- No `VALIDATION` entry and no `IMAGE_LIMITS` entry exists for either kind: nothing reads `verified_on_image`.
- GRE: both profiles declare `tunnel.gre`, so `PLUGIN_DEVICES['tunnel.gre']` now holds eos, vjunos-router and vsrx
  (vjunos-switch and vptx still declare none). GRE is not authorable in this schema version (plugins are refused);
  this only changes what the matrix shows. netlab's vjunos-router GRE template also writes
  `chassis fpc 0 pic 0 tunnel-services`.

## 2. The vSRX security zones: what the engine writes and what management depends on

- netlab 26.09 writes **no security zone and no security policy** for `vsrx` in any module this design accepts.
  The only zone template is `extra/firewall/zonebased/vsrx.j2` (the `firewall.zonebased` plugin: zones with
  `host-inbound-traffic system-services all; protocols all;`, `delete: policies;`, `default-policy deny-all`), and
  `design_intent` refuses plugins.
- What it does write for vsrx: `security { forwarding-options { family { iso { mode packet-based; } } } }` in the
  IS-IS fragment (`ansible/templates/isis/vsrx.j2`) and the same for `mpls` in the MPLS fragment
  (`ansible/templates/mpls/junos.j2`, guarded by `netlab_device_type == 'vsrx'`). Changing an SRX family's forwarding
  mode normally takes effect only after a reboot (documented Junos behaviour, not verified on this image).
- The live image boots with no zone at all and SSH works over `fxp0` (B03,
  [b03-vsrx-boot-2026-10-27.md](b03-vsrx-boot-2026-10-27.md) section 4): on the containerlab vSRX the management path
  is outside the zone model, so a zone-less design does not lose management there.
- What it does lose: on a flow-mode vSRX, traffic on a data port that is in no zone is dropped, the routing protocols
  included. A05 needed `set security zones security-zone trust interfaces ge-0/0/0 host-inbound-traffic
  system-services ping` before a ping to `ge-0/0/0` was answered
  ([a05-b06-vsrx-2026-10-27.md](a05-b06-vsrx-2026-10-27.md) step 6). An applied design therefore configures the
  addresses and protocols, but OSPF, IS-IS or BGP over vSRX data ports are expected not to come up until a zone
  admits them. This is a prediction for phase 2 to measure, not a recorded image limit.

The rule written into `design_provision.prepare_vsrx` (static, not proven live): the design never touches the
management path. Anything under `security` that names the management interface, and a `functional-zone management`
block, is left out; `delete:` tags are left out (they could wipe a zone's `host-inbound-traffic`); the ledger never
removes or replaces an unowned statement, so a person's `trust` zone keeps its `system-services`. In ownership, a
vSRX addition that binds an interface which an unowned statement already binds to another zone is a conflict
(`design_ownership.ZONE_BINDING`).

## 3. Capability data regeneration

The build tool listed only the four original devices in `PROFILE_DEVICES`; the two new profiles were already in
`module_support` but had no `device_features` block, which the feature-flag lookups read. The tool was changed to
list six devices (outside this worker's assigned paths; reported to the lead).

| Command (from `clab-backup-ui`) | Result |
|---|---|
| `PATH="$PWD/.venv/bin:$PATH" .venv/bin/python ../docs/netlab-integration/tools/build_capability_data.py <scratch>/cap-before.json`, then `cmp` with the committed JSON, before any change | exit 0, 8.6 s; `cmp` exit 0 (byte-identical: the tool is deterministic) |
| The same into `app/design_capability_data.json` after adding `vjunos-router` and `vsrx` to `PROFILE_DEVICES` | exit 0; `git diff --stat`: 331 insertions, 0 deletions (only the two new `device_features` entries) |
| The same into a scratch file again, then `cmp` (the dry-run check; the tool has no `--check` flag) | exit 0; `cmp` exit 0 |
| `test_design_capabilities.TestEngineDataContract.test_regeneration_matches_committed_json` | passed (netlab on PATH) |

## 4. Real-engine generation (tests, not a device)

A three-node lab (cEOS, vJunos-router `vrt`, vSRX `vsrx`, a triangle with `vsrx:eth2`) with modules ospf, isis,
bgp and mpls generates `initial, ospf, isis, bgp, mpls` for both new nodes. Data ports come out as `ge-0/0/N.0`,
LLDP is disabled on `fxp0`, `vsrx:eth2` is `ge-0/0/1`. Only the vsrx IS-IS and MPLS fragments carry
`mode packet-based`; nothing carries `security-zone`. `prepare()` leaves out only `host-name`,
`static-host-mapping` and the `delete:` tags. Two runs give byte-identical artifacts.
Pinned in `tests/test_design_families_routing.py` (`NewJunosKindsGenerationTests`).

## 5. What phase 2 needs

Phase 2 runs after B04 releases the two nodes and the manager is rebuilt from this tree. It applies the design
through the manager on `vrt` and `vsrx` (one operator, memory measured first) and reads back: the pre-change
backup, `configure exclusive`, `load merge`, `commit check`, `commit confirmed` with the session comment, the
confirmation over a fresh connection, a no-op re-apply, a removal of a stale owned statement, and a conflict
case (a second address on a port). On vSRX it also checks whether the protocols come up with no zone (expected: no),
and whether the iso and mpls packet-mode lines need a reboot. Only after that read-back may `VALIDATION` record
`verified_on_image` for a (kind, feature); a zone rule for the design, if one is needed, goes through design review
first.
