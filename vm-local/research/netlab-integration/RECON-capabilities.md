# netlab 26.09 capability recon

Engine under test: `~/research/netlab-integration/netlab-venv/bin/netlab` (networklab 26.09 from PyPI,
confirmed with `netlab version` -> `netlab version 26.09`). Source checked out at tag `release_26.09`
in `~/research/netlab-integration/netlab-src` (`git describe --tags` = `release_26.09`). All commands
below were actually run in `/tmp/netlab_out_test` or against the venv; all file citations were opened
and read. No `netlab up` was ever run. Raw command output is also saved under
`~/research/netlab-integration/out/*.txt` for anything long.

## 1. Modules and requested-capability mapping

### `netlab show --help` / `netlab show`

`netlab show <content>` supports: `attributes`, `defaults`, `devices`, `images`, `module-support`,
`modules`, `outputs`, `reports`, `providers`. Common flags: `--system`, `--format {table,text,yaml}`.

- `netlab show modules [--system] [-m MODULE] [--feature FEATURE] [--columns N]` — device list per
  module, or (`-m` + `--feature`) a table of which devices support a specific feature flag of that
  module, e.g. `netlab show modules --system -m bgp --feature import` or
  `-m gateway --feature protocol` (both actually run; output saved reasoning below).
- `netlab show attributes [-m MODULE] [match]` — the attribute schema (global/node/link/interface/vrf
  scopes) for the whole topology or one module.
- `netlab show module-support [-d DEVICE] [-m MODULE]` — module x device support matrix.

Full output of `netlab show modules --system` is saved at `out/show_modules.txt`; the module ->
supported-device lists (verbatim) are:

- `bfd`: arcos, arubacx, bird, cat8000v, crpd, csr, cumulus, dellos10, eos, frr, iol, ioll2, iosv,
  iosvl2, nxos, routeros7, sonic, srlinux, sros, srsim, vjunos-router, vjunos-switch, vmx, vptx, vsrx,
  vyos. **No iosxr.**
- `bgp`: (28 devices incl. eos, iosxr, vjunos-switch, vptx).
- `dhcp`: arcos, bird, cat8000v, csr, cumulus, dnsmasq, eos, iol, ioll2, iosv, iosvl2, kind, linux.
  **No iosxr, vjunos-switch, vptx.**
- `eigrp`: cat8000v, csr, iol, ioll2, iosv, iosvl2, nxos only. **No eos, iosxr, junos family.**
- `evpn`: incl. eos, iosxr, vjunos-switch, vptx.
- `gateway`: incl. eos, iosxr, vjunos-switch, vptx (and every other listed device except a couple).
- `isis`: incl. eos, iosxr, vjunos-switch, vptx.
- `lag`: arcos, arubacx, bird, cumulus, cumulus_nvue, dellos10, dnsmasq, eos, frr, ioll2, iosvl2, kind,
  linux, routeros7, vjunos-switch, vptx, vsrx, vyos. **No iosxr.**
- `mpls`: incl. eos, iosxr, vjunos-switch, vptx.
- `ospf`: incl. eos, iosxr, vjunos-switch, vptx (broadest IGP list).
- `ripv2`: cat8000v, csr, cumulus, eos, frr, iol, ioll2, iosv, iosvl2, openbsd, sros, srsim, vyos.
  **No iosxr, vjunos-switch, vptx.**
- `routing` (generic policy/ACL/static): incl. eos, iosxr, vjunos-switch, vptx.
- `sr` (SR-MPLS): arcos, cat8000v, cisco8000v, crpd, csr, eos, frr, iol, ioll2, iosxr, srlinux, sros,
  srsim, vjunos-router, vjunos-switch, vmx, vptx, vsrx.
- `srv6`: **arcos, cat8000v, frr, iol, ioll2, iosxr only.** No eos, no junos family (vjunos-switch,
  vptx, vjunos-router, vmx, vsrx all absent).
- `stp`: arcos, arubacx, cumulus, cumulus_nvue, dellos10, eos, frr, ioll2, iosvl2. **No iosxr, no
  junos family.**
- `vlan`: incl. eos, vjunos-switch, vptx. **No iosxr.**
- `vrf`: incl. eos, iosxr, vjunos-switch, vptx.
- `vxlan`: incl. eos, vjunos-switch, vptx. **No iosxr.**

There is **no separate `vrrp` module** — VRRP and anycast gateway are both inside the single `gateway`
module (`gateway.protocol: [anycast, vrrp]`, `gateway.vrrp.{group,preempt,priority}`,
`gateway.anycast.{mac,unicast}`; see `out/attr_gateway.txt`).

Cross-checked with the authoritative per-device command
`netlab show module-support --system -d <device>` (run for eos, vjunos-switch, vptx, iosxr; saved as
`out/modsup_eos.txt`, `out/modsup_vjunos-switch.txt`, `out/modsup_vptx.txt`, `out/modsup_iosxr.txt`) —
tables reproduced in §2.

### Requested-capability -> netlab mapping (verified in `netsim/modules/*.yml` / `netsim/defaults/attributes.yml` and `netlab show attributes`)

| Requested capability | netlab module / attribute | Evidence |
|---|---|---|
| IPv4/IPv6 addressing | Core `link.ipv4`/`link.ipv6`, `interface.ipv4`/`interface.ipv6`, `loopback.ipv4/ipv6`, `pool.ipv4/ipv6` — **not a module** | `netsim/defaults/attributes.yml:50-141` (see `link:` line 60-61, `interface:` line 96-97, `loopback:` line 138-139, `pool:` line 143-144) |
| OSPFv2 | `ospf` module, `af.ipv4` (default when an interface has an IPv4 address) | `out/attr_ospf.txt`; `docs/module/routing_protocols.md` §Address Families |
| OSPFv3 | Same `ospf` module, `af.ipv6` — no separate module | same as above; confirmed no `ospfv3` entry in `netlab show modules` |
| EIGRP | `eigrp` module, `af.{ipv4,ipv6}`, `as` | `out/attr_eigrp.txt` |
| IS-IS | `isis` module, `af.{ipv4,ipv6}`, `circuit_type`, `unnumbered.{ipv4,ipv6,network}` | `out/attr_isis.txt` |
| RIPv2 | `ripv2` module, `af.ipv4` | `out/attr_ripv2.txt` |
| RIPng | Same `ripv2` module, `af.ipv6` — no separate module | `out/attr_ripv2.txt` (has `af.ipv6: bool`) |
| BGP | `bgp` module (`as`, `router_id`, `activate`, `community`, `next_hop_self`, `rr*`, `confederation`, ...) | `out/attr_bgp.txt` |
| DHCP / DHCPv6 | `dhcp` module, `client.{ipv4,ipv6}`, `server`, `subnet.{ipv4,ipv6}` | `out/attr_dhcp.txt` |
| VLANs | `vlan` module (global VLAN objects, `mode: bridge/irb/route`, `access`/`native`/`trunk` link attrs) | `out/attr_vlan.txt`; `netsim/topology-defaults.yml`/attributes top listing lines 827-855 |
| VRFs | `vrf` module (`id`, `rd`, `import`/`export`, `loopback`) | `out/attr_vrf.txt`; top-level `vrf:` block, `out/show_attributes_top.txt:856-885` |
| LLDP | **Not a module.** Enabled unconditionally by the per-device `initial` Ansible template (global `lldp run`/`lldp`/`protocols lldp` statement), explicitly turned off only on the mgmt interface | see §6 templates |
| BFD | `bfd` module, `min_tx`/`min_rx`/`min_echo_rx`/`multiplier` (global/node/link) | `out/attr_bfd.txt` |
| Static routes | `routing.static` (global/VRF/node dict of `static_entry`: `ipv4`/`ipv6`/`nexthop`/`vrf`/`pool`/`prefix`/`include`) | `out/attr_routing.txt`; `out/show_attributes_top.txt:771-799` (`static_entry` type) |
| LACP | `lag` module, `lacp` (`off`/`slow`/`fast`), `lacp_mode` (`passive`/`active`), `lacp_system_id` | `out/attr_lag.txt` |
| LAG / link bonding | `lag` module, `link.mode` (`802.3ad`/`balance-xor`), `link.members`/`lag_member_linkattr` | `out/attr_lag.txt`; also a standalone `bonding` plugin exists (`netsim/extra/bonding/`) layered on the same module |
| MLAG | `lag` module, `link.mlag.{mac,peergroup}`, `node.mlag.mac` — plus a `mlag` plugin (`netsim/extra/mlag/vtep/`) for EVPN-VXLAN multihoming | `out/attr_lag.txt` |
| STP | `stp` module, `protocol` (`stp`/`rstp`/`mstp`/`pvrst`), `port_type`, `priority`, per-interface `enable`/`port_priority` | `out/attr_stp.txt` |
| VRRP | `gateway` module, `protocol: vrrp`, `vrrp.{group,preempt,priority}` | `out/attr_gateway.txt` |
| Anycast gateways | `gateway` module, `protocol: anycast`, `anycast.{mac,unicast}` | `out/attr_gateway.txt` |
| VXLAN | `vxlan` module, `flooding` (`static`/`evpn`), `domain`, `vlans`, `use_v6_vtep`, link `vtep` | `out/attr_vxlan.txt` |
| GRE | **Plugin, not core module**: `netsim/extra/tunnel/gre` (`tunnel.mode: gre`, `tunnel.af`, `tunnel.source`, `tunnel.vrf`) | `netsim/extra/tunnel/gre/defaults.yml`; templates only for eos, frr, ios, junos, openbsd, routeros7, vyos (`netsim/extra/tunnel/gre/*.j2`) — **no iosxr, no vjunos-switch/vptx-specific template** (junos.j2 there would in principle apply to any junos-family device, but no vjunos-switch/vptx-specific template exists and it was never validated live) |
| WireGuard | **Plugin, not core module**: `netsim/extra/tunnel/wireguard` (`tunnel.mode: wireguard`, `private_key`/`public_key`, `listen_port`, `allowed_ips`, `persistent_keepalive`) | `netsim/extra/tunnel/wireguard/defaults.yml`; templates only for frr, openbsd, routeros7, vyos — **no eos, iosxr, or junos-family device at all** |
| IPsec | **Absent.** `grep -rli ipsec netsim/ docs/` returns nothing. | direct grep, no hits |
| Route maps / policies | `routing.policy` (dict of `rp_entry`), `route_map.match`=[prefix,nexthop,aspath], `route_map.set`=[locpref,med,weight,prepend] | `out/attr_routing.txt` |
| IP prefix lists | `routing.prefix` (dict of `pfx_entry`) | `out/attr_routing.txt` |
| AS-path filters | `routing.aspath` (dict of `aspath_entry`) | `out/attr_routing.txt` |
| Redistribution | `<protocol>.import` (a list/dict of `{bgp,ospf,isis,eigrp,ripv2,static,connected}`, optionally `{policy: <routing.policy name>}`); type is `_r_import`/`r_proto` | `docs/module/routing_protocols.md` lines 213-272 (`(routing_import)=`); type def `netsim/defaults/attributes.yml:242`, `netsim/data/types.py:1095 must_be_r_proto` |
| Default origination | `bgp.originate` (adds a discard static route + advertises the prefix) for an explicit prefix; per-neighbor "originate default" is a **device feature flag** `bgp.features.session.default_originate`, not a topology attribute; a dedicated `bgp-originate` plugin also exists (`netsim/extra/bgp/originate/`) | `docs/module/bgp.md:329` (`module-bgp-originate`); `netsim/modules/bgp.yml:146` (`default_originate: Originate per-neighbor default route`) |
| MPLS | `mpls` module: `ldp` (`advertise`,`explicit_null`,`igp_sync`,`router_id`), `bgp` (labeled BGP), `vpn`, `6pe` | `out/attr_mpls.txt` |
| BGP-LU (labeled unicast) | `mpls.bgp` (`ipv4`/`ipv6`: `true_value: [ibgp, ebgp]`) | `out/attr_mpls.txt` |
| VPNv4/VPNv6 L3VPN | `mpls.vpn` (`ipv4`/`ipv6`: `true_value: [ibgp]`) | `out/attr_mpls.txt` |
| 6PE | `mpls.6pe` (`true_value: [ibgp]`, `valid_values: [ibgp, ebgp]`) | `out/attr_mpls.txt` |
| EVPN | `evpn` module: `transport` (`vxlan`/`mpls`/`sr`), `vrf.bundle` (`vlan_aware`/`vlan`/`port`/`port_vlan`), `vlan.rd/evi`, `vrf.transit_vni` | `out/attr_evpn.txt` |
| SR-MPLS | `sr` module: `protocol` (`isis`/`ospfv2`), `af.{ipv4,ipv6}`, `node_sid`, `srgb.{start,size,dyn_start,dyn_size}` | `out/attr_sr.txt` |
| SRv6 | `srv6` module: `igp` (`isis`/`ospf`), `locator`/`locator_pool`, `bgp.{ipv4,ipv6}`, `vpn.{ipv4,ipv6}`, `transit_only` | `out/attr_srv6.txt` |

## 2. Device features: eos, vjunos-switch, vptx, iosxr

### Inheritance mechanism

Device YAML files (`netsim/devices/*.yml`) may declare `parent: <device>`. Inheritance is resolved by
`process_child_device()` / `process_device_inheritance()` in `netsim/augment/devices.py:203-224`:
recursively resolves the parent first, takes a copy of the (already-resolved) parent Box, strips
`template`/`_meta_device`/`docname`/`docparent` from it, and merges it under the child with
`devices[dname] = p_data + devices[dname]` (Box `+` = deep-merge, child keys win), appending the
parent name to `_parents` and stripping null values. Both `iosxr.yml` (`parent: xr`) and
`vjunos-switch.yml`/`vptx.yml` (`parent: junos`) use this.

Per-node feature lookup then goes through `get_device_features()` in the same file
(`netsim/augment/devices.py:59-70`), which fetches the merged `features` Box (already flattened by the
inheritance pass above, further merged with any node-level `_features` override) and returns it. Module
code and the validator call `check_optional_features()` (`netsim/augment/devices.py:150-196`) to check
whether an attribute path is allowed for the device's feature tree.

**Refusal mechanism (error vs. warning):** `check_optional_features()` walks the feature tree; if the
device's feature value for the attribute is `False` (or the tree runs out and whitelist mode is on),
it calls `optional_features_error()` (`netsim/augment/devices.py:138-147`):
```python
log.error(f'Device {node.device} does not support {attribute} used in {path}',
          category=log.IncorrectAttr if category is None else category, module=module)
```
`log.error()` (`netsim/utils/log.py:223-...`) only treats it as a non-fatal, printed-and-continue
**warning** when `category is Warning` (the literal built-in class) — those lines go to `_WARNING_LOG`.
Any other category, including the default `log.IncorrectAttr` (a `Warning` *subclass*, not the literal
`Warning`), is appended to `_ERROR_LOG` instead. Every stage of the transform pipeline
(`netsim/augment/main.py`) calls `log.exit_on_error()` after each step; `exit_on_error()`
(`netsim/utils/log.py:424-427`) calls `log.fatal()` and aborts the whole `netlab create`/`netlab up`
run as soon as `_ERROR_LOG` is non-empty. **Net effect: using an attribute/feature a device does not
support is a hard fatal error that aborts topology creation before any output is written**, unless the
specific call site explicitly passes `category=Warning` (a few feature checks do this for softer
notices, e.g. some `remove_private_as` variants), in which case it is a genuine non-fatal warning.

### Module x device matrix (from `netlab show module-support --system -d <device>`, files saved in `out/modsup_*.txt`)

| module | eos | vjunos-switch | vptx | iosxr |
|---|---|---|---|---|
| bfd | x | x | x | |
| bgp | x | x | x | x |
| dhcp | x | | | |
| eigrp | | | | |
| evpn | x | x | x | x |
| gateway | x | x | x | x |
| isis | x | x | x | x |
| lag | x | x | x | |
| mpls | x | x | x | x |
| ospf | x | x | x | x |
| ripv2 | x | | | |
| routing | x | x | x | x |
| services | x | x | x | x |
| sr | x | x | x | x |
| srv6 | | | | x |
| stp | x | | | |
| vlan | x | x | x | |
| vrf | x | x | x | x |
| vxlan | x | x | x | |

### Key per-module feature flags (`features:` block in the device/parent YAML)

- **`bgp.features`** — declared once in `netsim/modules/bgp.yml:126-158` under three categories:
  `core` (`activate_af`, `advertise`, `local_as`, `vrf_local_as`, `local_as_ibgp`, `ipv6_lla`,
  `rfc8950`, `community`, `confederation`, `import`), `session` (`allowas_in`, `as_override`, `bfd`,
  `default_originate`, `description`, `gtsm`, `passive`, `password`, `remove_private_as`, `rs`,
  `rs_client`, `timers`, `tcp_ao`, `multihop`), `policy` (`_default_locpref`, `aggregate`,
  `bandwidth`). Per device, `xr.yml:31-45` sets `activate_af/advertise/aggregate/allowas_in/
  as_override/confederation/default_originate/gtsm/import:[ospf,isis,connected,static,vrf]/
  local_as/local_as_ibgp/multihop.vrf/passive/password/remove_private_as{valid:[...]}/rs_client/
  tcp_ao/timers/vrf_local_as: true`; `junos.yml:29-38` sets `activate_af/advertise/allowas_in/
  as_override/bfd/confederation/default_originate/import:[...]/local_as/local_as_ibgp/multihop.vrf/
  password/passive/remove_private_as.valid/timers/vrf_local_as: true` — junos.yml lacks `aggregate`,
  `gtsm`, `rs_client`, `tcp_ao`, and `bandwidth` but adds an explicit `bgp.bfd: true` flag that
  xr.yml does not set at the `bgp.features` level.
- **`gateway.features.protocol`** — `xr.yml:47-48`: `[vrrp]` only (no anycast on IOS XR);
  `junos.yml:39-40`: `[anycast, vrrp]`; `vptx.yml` explicitly overrides to `[anycast, vrrp]` (redundant
  with junos parent); `vjunos-switch.yml` does **not** override gateway features, so it inherits
  `[anycast, vrrp]` from `junos.yml`.
- **`ospf.features`** — `xr.yml:53-59`: `unnumbered/password/priority/timers/default: true`,
  `import:[bgp,isis,connected,static,vrf]`; `junos.yml:52-58`: `unnumbered/password/priority/timers/
  areas: true`, `import:[bgp,isis,connected,static,vrf]` (junos has `areas: true`, xr has
  `default: true` instead — different flags).
- **`isis.features`** — `xr.yml:49-52`: `circuit_type: True`, `unnumbered.{ipv4,ipv6,network}: True`,
  `import:[ospf,bgp,connected,static,vrf]`; `junos.yml:44-47`: `circuit_type: true`,
  `import:[bgp,ospf,connected,static,vrf]`, `unnumbered.{ipv4,ipv6}: true` (junos has no
  `unnumbered.network` flag).
- **`vlan.features`** — `vjunos-switch.yml:9-13` / `vptx.yml:14-18`: `model: l3-switch`,
  `svi_interface_name: irb.{vlan}`, `subif_name: "{ifname}.{vlan.access_id}"`, `native_routed: true`.
  IOS XR has no `vlan` in its module-support list at all (not even a `vlan.features` entry).
- **`lag.features`** — `vjunos-switch.yml:8`/`vptx.yml:12`: `passive: True` only (i.e. Junos LAG
  support here is limited to passive LACP mode per the feature flag); eos/xr have no `lag.features`
  override in the files read (eos gets full lag support via its own module presence; iosxr has no
  `lag` module support at all per §module x device table above).
- **`mpls.features`** — `xr.yml:60-63`: `ldp: true`, `vpn: true`, `6pe: true`;
  `iosxr.yml:31-34` (child) adds `srv6.{bgp,isis,vpn}: true` (SRv6 is an iosxr-specific addition, not
  inherited from `xr.yml`, which has no `srv6` key at all); `junos.yml:48-50`: `ldp: true`, `vpn: true`
  — **no `6pe` flag for Junos** (matches the `mpls` device list containing junos family without 6PE
  semantics active — 6PE is IOS-XR-only among the four devices studied).
- **`evpn.features`** (from `vjunos-switch.yml:15-20`/`vptx.yml:10-13`): `asymmetrical_irb: true`,
  `irb: true`, `multi_rt: true`, `bundle:[vlan_aware]`, `transport:[vxlan]` — i.e. Junos-family EVPN
  here is VXLAN-transport-only (`bundle` restricted to `vlan_aware`); `xr.yml:64-67`:
  `transport.{mpls,sr,cp_vxlan}: [ibgp]`, `asymmetrical_irb: False` — IOS XR EVPN supports MPLS, SR and
  VXLAN control-plane transport but explicitly **not** asymmetric IRB.
- **`sr.features`** (`xr.yml:68-70`): `af:[ipv4,ipv6]`, `protocol:[isis,ospfv2]`; `junos.yml:59-61`:
  `af:[ipv4,ipv6]`, `protocol:[isis]` only (no OSPFv2 SR on Junos family per this file).
- **`srv6.features`**: only on `iosxr.yml:31-34` (`bgp/isis/vpn: true`) among the four devices; not
  present at all on `junos.yml`, `eos.yml`, `xr.yml` (parent) — confirms `iosxr` is the only one of
  the four with any SRv6 support, and it is added at the child-device level, not inherited.
- **`routing.features`** — `xr.yml:71-91` and `junos.yml:64-83` both declare detailed
  `policy.{match,set,delete}` sub-flags (community standard/large/extended, locpref/med/prepend/weight,
  prefix, aspath) plus `static.{vrf,inter_vrf,discard}`/`static.{vrf,discard}` and
  `community.{standard,large}`; both use `caveats: caveats-iosxr` / `caveats: caveats-junos` markers on
  several sub-flags (aspath, community, prefix), meaning "supported but with device-specific caveats"
  rather than a plain boolean (see `netsim/augment/devices.py` `check_optional_features`, the `isinstance(features,str)` branch that treats a string feature value as a custom warning message).
- **`vrf.features`**: `xr.yml:92-95`: `bgp/isis/ospfv2/ospfv3: True`; `junos.yml:84-88`:
  `ospfv2/ospfv3/isis/bgp: True` — same four flags on both.
- **`initial.features`** (interface bring-up capability, not a routing module): `xr.yml:20-27`:
  `ipv4.unnumbered: True`, `ipv6.lla: True`, `min_mtu: 68`, `min_phy_mtu: 1500`, `max_mtu: 9216`,
  `collect: true`, `reload: true`; `junos.yml:20-25`: `ipv4.unnumbered: true`, `ipv6.lla: true`,
  `collect: true`, `reload: true` (no explicit MTU bounds at this level).

### Notable devices NOT supporting a feature (per `netlab show modules -m <module>` device lists / module-support tables above)

- `eigrp`, `ripv2`, `dhcp`, `stp`, `srv6` are **absent** on `vjunos-switch` and `vptx`.
- `dhcp`, `eigrp`, `ripv2`, `stp`, `vlan`, `vxlan`, `bfd`, `lag` are **absent** on `iosxr`.
- `eigrp`, `srv6` are **absent** on `eos`.

## 3. Python API / entry points

There is **no dedicated, documented "run the create pipeline in-process" public API**. What exists:

- `netsim/api/__init__.py` — despite the package name, this is explicitly scoped as **"Plugin API
  routines"** (its own comment) — `get_config_name()`, `node_config()`, `list_attribute()`, meant for
  plugin authors adding config snippets to a node, not for driving the whole transform.
- `netsim.augment.main.transform(topology: Box) -> None` (`netsim/augment/main.py:118-121`) is the
  real, internal, three-phase pipeline entry point: `transform_setup()` -> `transform_data()` ->
  `post_transform()`, each phase itself calling many `augment.*`/`modules.*`/`providers.*`/plugin
  hooks and `log.exit_on_error()` after most steps (confirmed by reading the whole file, lines 1-121).
  It mutates a `Box` topology object built by `netsim.utils.read` from a YAML file plus defaults; it
  is not decorated or exported as public and is not mentioned in `docs/`.
- `netsim/cli/create.py` is the actual, documented way to drive a create run: it is the module behind
  `netlab create`, exposing `run(cli_args: List[str]) -> None` and helper functions
  (`create_topology_parse()`, `http_fetch_content()`, `fix_git_repo_url()`). The package's own
  console-script entry point (`pyproject.toml`: `[project.scripts] netlab = "netsim.cli:main"`) is
  `netsim.cli.main()`. **All of these are CLI-argument-list driven, not object/keyword-argument
  driven**, i.e. the supported programmatic surface is "build an argv list and call `run()`/`main()`",
  not a typed function call.
- **The genuinely documented, supported, external integration surface is the `netlab api` HTTP server**
  (`docs/netlab/api.md`, verbatim read): `netlab api [--bind] [--port] [--auth-user] [--auth-password]
  [--tls-cert] [--tls-key]`. It exposes `GET /healthz`, `GET /templates`, `POST /jobs` (body has
  `action`, `workdir`/`workspaceRoot`, `topologyPath`/`topologyUrl`), `GET /jobs`, `GET /jobs/{id}`,
  `GET /jobs/{id}/log`, `POST /jobs/{id}/cancel`, `GET /status[/​{instance}]`. Doc says explicitly:
  *"The API uses the same Python CLI modules as `netlab`, so its behavior and output are consistent
  with the CLI commands."* `action` maps to `up`, `create`, `down`, `collect`, `status` — for our
  purposes only `action: create` (and read-only `status`) would ever be relevant, since `up`/`down`
  touch a real lab. Optional HTTP Basic Auth (`NETLAB_API_USER`/`NETLAB_API_PASSWORD`) and TLS
  (`NETLAB_API_TLS_CERT`/`NETLAB_API_TLS_KEY`) env vars or flags.

**Conclusion for the integration:** treat `netlab create` (subprocess) as the supported entry point;
there is no supported in-process Python call. `netsim.augment.main.transform` is internal and would
tie the manager to netlab's internal module layout across releases.

### Stable, data-only output formats

- `-o json[:modifier][=file]` / `-o yaml[:modifier][=file]` (`netsim/outputs/json.py`,
  `netsim/outputs/yaml.py`) dump the fully-transformed topology `Box`. Verified live:
  `netlab create -o yaml:nodefault=topo.yaml -o json:nodefault=topo.json topology.yml` succeeded and
  produced both files (documented modifiers: `nodefault` strips `defaults`, `noaddr` strips
  `addressing`; any other string is evaluated as a Python expression against the topology object,
  e.g. `yaml:nodes.r1.interfaces`, per `docs/outputs/yaml-or-json.md`).
- `-o report:<name>[=file]` (`netsim/outputs/report.py`) renders a Jinja2 report template.
  `netlab show reports` (no `--system` flag; run bare) lists three families — **HTML** reports
  (`addressing.html`, `addressing-link.html`, `addressing-node.html`, `bgp-asn.html` "needs Ansible",
  `bgp-neighbor.html`, `bgp.html`, `devices.html`, `isis-interfaces.html`, `isis-nodes.html`,
  `mgmt.html`, `ospf-areas.html`, `ospfv3.html`, `wiring.html`), **text** reports (`addressing`, `bgp`
  "needs Ansible", `devices`, `isis-nodes`, `mgmt`, `nodes`, `ospf-areas`, `ospfv3`, `wiring`), and
  **Markdown** reports (`addressing.md`, `bgp-asn.md`, `bgp-neighbor.md`, `bgp-neighbor-short.md`,
  `devices.md`, `isis-interfaces.md`, `isis-nodes.md`, `ospf-areas.md`, `ospfv3.md`, `wiring.md`).
- **Reports do NOT need a pickle snapshot when run as part of `netlab create`.** Verified live:
  `netlab create -o report:addressing topology.yml` (no `netlab.snapshot.pickle` present at all)
  printed a correct per-node/per-interface IPv4 addressing table straight from the in-memory transform.
  Likewise `netlab create -o report:bgp topology.yml` printed correct "AS Numbers" and "BGP Neighbors"
  tables purely from static topology data (no Ansible run, no live device, no snapshot file) —
  contradicting the "(needs Ansible)" caption in a plain two-router static-AS lab; the caption most
  likely applies to router-id/other data that in general comes from live facts, but the report degrades
  gracefully to static data when no facts are available.
- The **separate** `netlab report <name> [-t topology.yml] [--snapshot FILE]` command (`netlab report
  --help`) can also run straight off a `-t` topology file with **no snapshot pickle present at all** —
  verified live (`netlab report addressing -t topology.yml` with no `netlab.snapshot.pickle` in the
  directory produced the identical addressing table). The `--snapshot` flag / default
  `netlab.snapshot.pickle` file is only needed when you want to report on the topology as it was
  actually deployed (post-`netlab up`, with allocated ports etc.), not for a pure "transform + report"
  pass.

## 4. Usage statistics (`netsim/utils/stats.py`)

Read the entire file (244 lines) and every caller (`grep -rn stats\. netsim/cli/*.py netsim/*.py`):

- Storage: a single local JSON file, `~/.netlab/stats.json` by default
  (`get_filename()`: `get_const('stats_file','~/.netlab/stats.json')`, `os.path.expanduser`'d).
  Protected by a sibling `.lock` file via `filelock.FileLock` (`lock_stats()`).
- What is recorded:
  - Every `netlab <cmd>` invocation increments `cli.<cmd>.start` and (on successful completion)
    `cli.<cmd>.done` counters — called unconditionally from `netsim/cli/__init__.py:547,551`
    (`lab_commands()`, the dispatcher for every CLI command, `create` included).
  - `netlab up` **only** (call site `netsim/cli/up.py:416`, inside `up.py`'s post-transform flow) also
    calls `stats.update_topo_stats(topology)`, which additionally counts: primary/secondary
    `provider.<name>.use`, `device.<devtype>.use` (+ max concurrent count),
    `device.<devtype>.provider.<provider>`, `device.<devtype>.module.<module>` per module actually
    enabled on that device, `device.<devtype>.custom` (custom config template used) or
    `device.<devtype>.plugin.<plugin>` (built-in plugin config used), `module.<name>.use` (+ max),
    `plugin.<name>.use` (+ max). **`netlab create` alone does NOT call `update_topo_stats` — only the
    generic `cli.create.start`/`cli.create.done` counters fire** (confirmed: only one call site for
    `update_topo_stats` exists, in `netsim/cli/up.py`).
  - No hostnames, IP addresses, topology names, file paths, or credentials are recorded — only counts
    keyed by command name / provider name / device type / module name / plugin name.
- Network transmission: **none found.** `grep -rn "requests\.\(post\|put\)" netsim/` returns zero
  matches anywhere in the source tree; `stats.py` only ever reads/writes the local JSON file. The
  `netlab usage` subcommand (`netsim/cli/usage/__init__.py`) only offers `start`/`stop`/`clear`/`show`
  — there is no `send`/`upload`/`sync` action. The doc (`docs/netlab/usage.md`, read verbatim) and the
  `netlab usage start` hint text (`netsim/cli/usage/utils.py`) both state explicitly: *"The statistics
  are not shared with anyone."*
- Disable mechanism: **not an env var** — a persisted flag inside the same stats file. `netlab usage
  stop [-y]` (`usage_stop()` in `netsim/cli/usage/utils.py`) calls
  `stats.stats_change_data({'_disabled': True})`, which is honored by `write_stats()`
  (`netsim/utils/stats.py`: `if stats.get('_disabled',False) and not force: return`) — i.e. once
  disabled, no further counters are written (all subsequent `add_counter`/`write_stats` calls become
  no-ops) until `netlab usage start` clears the flag. `netlab usage clear [-y]` wipes the counters but
  preserves the current `_disabled` state. Confirmed no `NETLAB_*STAT*` env var exists anywhere
  (`grep -rn "NETLAB_.*STAT" netsim/` → no hits; the only `NETLAB_API_*` env vars found are for the
  unrelated `netlab api` HTTP server).
- `netlab create` triggers only the generic command counters described above; it does not, by itself,
  ever cause any network call.

## 5. Licensing

- `LICENSE.md` at the repo root is the plain MIT License text (verbatim, permission grant +
  "AS IS" disclaimer, copyright line: *"Copyright (c) 2020-2025 Ivan Pepelnjak, Jeroen van Bemmel,
  Stefano Sasso, Dan Partelly, Pete Crocker, Julien Dhaille, Jody Lemoine, and others"*). The word
  "MIT" does not appear in the file itself, but the text is the standard MIT License wording.
- `pyproject.toml` declares no `license`/license-classifier field and no separate license per
  component; `classifiers` only lists language/OS/topic entries, no `License ::` classifier. No
  `NOTICE`, `COPYING`, or `THIRD_PARTY*` file exists anywhere in the repo (`find . -iname "NOTICE*" -o
  -iname "COPYING*" -o -iname "THIRD*PARTY*"` → no hits) and no file carries an `SPDX-License-Identifier`
  header (`grep -rl "SPDX-License-Identifier"` → no hits). Templates, device YAML, and reports are all
  under the same top-level `LICENSE.md`; there is no separate license for `netsim/ansible/templates/`
  or `netsim/devices/`.
- `[project.scripts] netlab = "netsim.cli:main"`, package name `networklab`
  (`pyproject.toml`), console entry point confirmed by `netlab version` (`package location:
  .../site-packages/netsim`).
- **For the manager (MIT-licensed):** bundling `networklab` as a pip dependency in a Docker image is a
  same-license (MIT-to-MIT) situation with no additional NOTICE-file requirement found in the repo —
  the only MIT obligation is preserving the copyright/permission notice, satisfiable by keeping netlab's
  own `LICENSE.md`/site-packages metadata intact in the image (e.g. not stripping `dist-info`) or by
  reproducing the copyright line in the manager's own third-party notices. No stricter requirement
  (no NOTICE file, no source-distribution obligation, no copyleft) was found anywhere in the checkout.

## 6. Junos (vjunos-switch, vptx), IOS XR, and EOS: interface naming and management config

### Junos family — interface/unit naming

- `netsim/devices/junos.yml:8` sets `interface_name: ge-0/0/{ifindex}` (parent default, inherited by
  `vjunos-switch`); `netsim/devices/vptx.yml:5` overrides `interface_name: et-0/0/{ifindex}` (vPTX uses
  `et-` 100G-style names, matching the task's expectation).
- Junos interfaces are **always rewritten to include an explicit `.0` unit** by the
  `unit_0_trick()` quirk in `netsim/devices/junos.py:38-50`:
  ```python
  def unit_0_trick(intf: Box, round: str ='global') -> None:
    oldname = intf.ifname
    newname = oldname + ".0"
    ...
    intf.ifname = newname
    intf.junos_interface = oldname
    intf.junos_unit = '0'
  ```
  The file's own header comment (`netsim/devices/junos.py:3-6`) states the intent: *"Every interface is
  a subunit -> rename interface names from ge-0/0/0 to ge-0/0/0.0 (and so avoid using unit 0 on the
  initial template)"*. This confirms the task's expected `ge-0/0/0.0` / `et-0/0/0.0` naming.

### Junos family — initial template (`netsim/ansible/templates/initial/junos.j2`, 70 lines, used by both `vjunos-switch` and `vptx` — no per-device override found)

Verbatim (already dotted-unit interface names from the quirk above make the direct
`{{ l.ifname }} { family inet {...} } }` block, e.g. `ge-0/0/0.0 { family inet { address ...; } } }`,
valid Junos curly-config, since Junos auto-splits a dotted interface name into
physical-interface/unit):

```
{% include 'junos/hosts.j2' %}
...
interfaces {
{% for l in netlab_interfaces %}
  {{ l.ifname }} {
{% if l.name is defined %}
    description "{{ l.name }}...";
{% endif %}
{% if l.bandwidth is defined %} bandwidth {{ l.bandwidth * 1000 }}; {% endif %}
{% if l.shutdown|default(False) %} disable; {% endif %}
{% if 'ipv4' in l %}
      family inet { ... address {{ l.ipv4 }}; ... }
{% endif %}
{% if 'ipv6' in l %}
      family inet6 { ... address {{ l.ipv6 }}; ... }
{% endif %}
  }
{% endfor %}
}
{% include 'junos/lldp.j2' %}
```
It loops **only** over `netlab_interfaces` — the data-plane interface list, which explicitly excludes
the management interface (`mgmt`, a separate top-level Ansible var). **It never opens an
`fxp0`/`re0:mgmt-0` stanza and never sets an mgmt IP, root-authentication, or any `system` credential.**

`junos/hosts.j2` (14 lines, included first) is the *only* place `system { }` is emitted, and it
configures only `host-name` and, unless `services.dns._no_hosts` is set, a `static-host-mapping` block
mapping other lab nodes' names to their loopback/first-interface IPv4 — **no
`root-authentication`, no user accounts, no management-plane config of any kind.**

`junos/lldp.j2` (included last) enables LLDP on `interface all` but explicitly `disable`s it on the
management interface: `interface {{ mgmt.ifname|default('fxp0') }} { disable; }` — i.e. Junos LLDP
config **does** name the mgmt interface, but only to turn LLDP off there, never to touch addressing or
any other mgmt setting.

Default `mgmt_if` values: `junos.yml:10` → `fxp0` (inherited by `vjunos-switch`, which sets no
override); `vptx.yml:5` → `"re0:mgmt-0"` (explicit override) — both match the task's expectation
exactly.

A separate `junos/container_interfaces.j2` template exists (uses explicit `unit 0 { family inet {...}
} }` nesting instead of the dotted-name trick) but is **only** included by `initial/crpd.j2` and
`initial/csrx.j2` (`grep -rn container_interfaces netsim/` — two hits, neither is vjunos-switch/vptx),
so it is irrelevant to the four devices under study.

### IOS XR — initial template (`netsim/ansible/templates/initial/iosxr.j2`, 80 lines)

```
hostname {{ inventory_hostname }}
!
domain lookup disable
!
lldp
 no management enable
!
...
{% for l in netlab_interfaces %}
interface {{ l.ifname }}...
 no shutdown / shutdown
 [description, bandwidth, mtu, ipv4/ipv6 address]
!
{% endfor %}
```
`mgmt_if: MgmtEth0/RP0/CPU0/0` is the default for both the `xr` meta-parent (`xr.yml:4`) and
`iosxr.yml:3` (child override, same value) — matches the task's expectation exactly.

Critically, IOS XR's LLDP-on-mgmt suppression is done with a **global** command,
`lldp / no management enable`, **not** by opening an `interface MgmtEth0/RP0/CPU0/0` stanza — this
template never names or enters the management interface at all. The `{% for l in netlab_interfaces
%}` loop (data-plane only) is the only place any `interface <name>` stanza is opened. No
`username`/AAA/root-credential lines are emitted by this template — device credentials come from
`group_vars` (`ansible_become_password`, etc.) applied over the Ansible/NETCONF-style control channel,
not pushed as CLI config by this Jinja template.

### EOS — initial template (`netsim/ansible/templates/initial/eos.j2`, 114 lines)

```
hostname {{ inventory_hostname... }}
!
logging monitor debugging
aaa authorization exec default local
!
lldp run
{ip routing / no ip routing based on af.ipv4}
{ipv6 unicast-routing / no ipv6 unicast-routing based on af.ipv6}
!
[vrf block, hosts, interface-defaults mtu]
!
interface {{ mgmt.ifname|default('Management1') }}
 no lldp transmit
 no lldp receive
!
{% for l in netlab_interfaces %}
interface {{ l.ifname }}
 [no switchport, vrf, mtu, description, ipv4/ipv6 address, mac-address, no shutdown]
!
{% endfor %}
```
**This is the one template of the three that explicitly opens the management-interface stanza** —
`interface {{ mgmt.ifname|default('Management1') }}` — but the *only* two lines emitted inside it are
`no lldp transmit` / `no lldp receive`; no IP address, no VRF assignment, no shutdown state, no AAA or
credential line is ever written there. `aaa authorization exec default local` and
`logging monitor debugging` are global (not interface-scoped) statements unrelated to the mgmt
interface's network config.

Default `mgmt.ifname`: **not a single constant** — `netsim/devices/eos.yml:5` sets the top-level
(libvirt/vEOS) default `mgmt_if: Management1`, but the `clab:` provider-specific block
(`netsim/devices/eos.yml:187`, under the `clab:` key that also sets `kind: ceos`) overrides it to
`mgmt_if: Management0`. Since the manager only ever runs containerlab (`ceos` kind), the effective
default management interface name on the devices the manager will actually touch is
**`Management0`, not `Management1`** — this is the value that matters for the integration and differs
from the libvirt/vEOS default.

### Summary relevant to "never touch management configuration"

Of the three device families, only **EOS**'s `initial` template ever opens the management interface's
own configuration stanza — and even there, the only content is disabling LLDP transmit/receive on it,
nothing address- or credential-related. Junos disables LLDP on the mgmt interface via a named (but
still LLDP-only) stanza inside the global `protocols lldp` block. IOS XR disables it with a fully
global command that never names the mgmt interface at all. **None of the three initial templates set,
change, or remove a management IP address, VRF membership, or authentication/credential configuration
on the management interface** — all three leave management-plane addressing entirely to
containerlab/the box image's own bring-up (DHCP/`CLAB_MGMT_PASSTHROUGH`/etc.), matching the
integration's "never touch management configuration on real devices" requirement, with the caveat that
EOS's template does still issue two LLDP commands inside that interface's stanza and a from-scratch
integration must preserve (or deliberately choose to skip) that specific behavior.

## Files created

- `~/research/netlab-integration/RECON-capabilities.md` (this report)
- `~/research/netlab-integration/out/*.txt` — raw, verbatim command output backing every `out/...`
  citation above: `show_modules.txt`, `show_modules_help.txt`, `show_attributes_help.txt`,
  `show_module_support_help.txt`, `show_attributes_top.txt`, `attr_{bfd,bgp,dhcp,eigrp,evpn,gateway,
  isis,lag,mpls,ospf,ripv2,routing,sr,srv6,stp,vlan,vrf,vxlan}.txt`, `modsup_{eos,vjunos-switch,vptx,
  iosxr}.txt`.
