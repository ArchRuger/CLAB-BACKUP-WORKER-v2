# Recon: netlab `external` provider as a compiler for the containerlab manager

Environment: `~/research/netlab-integration/netlab-venv/bin/netlab` (networklab 26.09, pip),
source at `~/research/netlab-integration/netlab-src` (git tag `release_26.09`). All work happened
under `~/research/netlab-integration/proto-external/`. **No `netlab up` was run anywhere** — every
command below is `netlab create` (compile-only) or `netlab show` (read-only introspection). Nothing
in `~/projects/`, `/srv/`, Docker or containerlab was touched.

All file/line citations are against `netlab-src` at tag `release_26.09`.

---

## Task 1 — device profiles

Source files read in full: `netsim/providers/external.py`, `netsim/providers/external.yml`,
`docs/labs/external.md`, `netsim/outputs/config.py`, `netsim/cli/create.py`,
`netsim/devices/{eos,vjunos-switch,vptx,iosxr,junos,xr,linux,_common}.{py,yml}`,
`netsim/topology-defaults.yml`.

### The mechanism that decides which attribute value applies (read this first)

`netsim/augment/devices.py:30-52`, `get_device_attribute(node, attr, defaults)`:

```python
def get_device_attribute(node, attr, defaults):
  devtype  = node.device
  provider = get_provider(node,defaults)          # node.provider or defaults.provider
  devdata = defaults.devices[devtype]
  if provider in devdata:
    if attr in devdata[provider]:                  # <-- only a TOP-LEVEL key match, e.g. "interface_name"
      pvalue = devdata[provider][attr]
      if not isinstance(pvalue,dict):
        return pvalue
  value = devdata.get(attr,None)                   # non-provider-specific value
  ...
  return value
```

This is looked up by attribute name `interface_name` (a flat string key), not by walking into a nested
`interface: {name: ...}` block. Every device profile below nests its clab-specific interface template
under `clab.interface.name` (a *different* key path than `interface_name`). Consequence, verified
empirically in Task 2: **under `provider: external`, the clab block is never consulted at all** — the
attribute lookup for `interface_name`/`mgmt_if`/`loopback_interface_name` always falls through to the
device's plain top-level value, which is the value used by the *libvirt* VM form of the device, not the
containerlab veth name. This is exactly why `docs/labs/external.md` insists on explicit `ifname:`.

### eos (`netsim/devices/eos.yml`)

- `interface_name: Ethernet{ifindex}` (line 4) — top-level, so this is what `external` uses.
- `mgmt_if: Management1` (line 5) — top-level; `clab.mgmt_if: Management0` (line 187) is clab-only and irrelevant under `external`.
- `loopback_interface_name: Loopback{ifindex}` (line 6).
- `role: router` (line 9).
- `netlab_device_type`: not set in `group_vars` → defaults to the device name `eos` (`augment/devices.py:305-306`).
- `features:` block (lines 21-171), verbatim key set: `initial` (`system_mtu`, `ipv4.unnumbered`, `ipv6.lla`/`use_ra`, `max_mtu: 9194`, `min_mtu: 68`, `ra`, `roles: [host, router, bridge]`, `mgmt_vrf`, `generate_mac: [ethernet]`, `normalize`, `collect`, `reload`, `config_mode: [netmiko]`), `bfd`, `bgp` (`activate_af`, `advertise`, `ipv6_lla`, `local_as[_ibgp]`, `vrf_local_as`, `import: [ospf,isis,ripv2,connected,static,vrf]`, `community.{standard,large,extended,2octet}`, `confederation`, `allowas_in`, `as_override`, `bfd`, `default_originate`, `gr`, `gtsm`, `passive`, `password`, `remove_private_as.valid`, `rs_client`, `tcp_ao: [libvirt,external]`, `timers`, `aggregate`, `bandwidth.{in,out}`, `multihop.vrf`), `dhcp`, `evpn`, `gateway`, `isis`, `lag` (incl. `mlag.peer` fixed vlan/ifindex/subnet), `mpls`, `ospf` (incl. the NSSA type-7 range caveat text), `ripv2`, `routing`, `services`, `sr`, `stp`, `tunnel`, `vlan`, `vrf`, `vxlan`.
- `external:` block (line 214-215): `image: none` — the *only* external-provider-specific setting for eos.
- `clab:` block (172-204) is a completely separate namespace: `clab.node.kind: ceos`, `clab.image: ceos:4.34.2F` (note: the owner's real image is `n24l/ceos:4.35.0F`, a different tag/registry), `clab.interface.name: et{ifindex}`, `clab.mgmt_if: Management0`, `clab.node.env.INTFTYPE: et`. **None of this is read when `provider: external`.**

### junos (`netsim/devices/junos.yml`) — meta/parent device, `_meta_device: True`

- `interface_name: ge-0/0/{ifindex}` (line 8), `mgmt_if: fxp0` (line 10), `loopback_interface_name: lo0.{ifindex}` (line 6), `ifindex_offset: 0` (line 7).
- `features:` (21-108): `initial` (`ipv4.unnumbered`, `ipv6.lla`, `collect`, `reload`), `bfd`, `bgp` (`activate_af`, `advertise`, `allowas_in`, `as_override`, `bfd`, `confederation`, `default_originate`, `import: [ospf,isis,connected,static,vrf]`, `local_as[_ibgp]`, `multihop.vrf`, `password`, `passive`, `remove_private_as.valid: ['on',all,replace]`, `timers`, `vrf_local_as`, `_default_locpref: false`), `gateway`, `isis`, `mpls`, `ospf`, `routing`, `services`, `sr`, `vrf`.
- `external: {image: none}` (110-111). `clab:` sets `features.initial.config_mode: [startup]` and `group_vars.netlab_ready: [ssh, ansible]` (113-118) — clab-only, not used by `external`.
- Every concrete Junos device (`vptx`, `vjunos-switch`, `vjunos-router`, `vsrx`, `crpd`, `vmx`) declares `parent: junos` and inherits this block, overriding only what differs.

### vjunos-switch (`netsim/devices/vjunos-switch.yml`)

- `parent: junos`, `interface_name: ge-0/0/{ifindex}` (line 4, same as parent — restated, not actually different). No `mgmt_if` override → inherits `fxp0` from junos.
- `group_vars.netlab_device_type: vjunos-switch` (line 6) — explicit override (needed because `ansible_network_os` stays generic `junos`).
- `features:` adds/overrides `evpn` (`asymmetrical_irb`, `irb`, `multi_rt`, `bundle: [vlan_aware]`, `transport: [vxlan]`), `lag.passive: True`, `vlan` (`model: l3-switch`, `svi_interface_name: irb.{vlan}`, `subif_name: "{ifname}.{vlan.access_id}"`, `native_routed`), `vxlan: true`.
- `clab:` (24-38): `image: vrnetlab/juniper_vjunos-switch:23.4R2-S2.1`, `node.kind: juniper_vjunosswitch`, `node.env.CLAB_MGMT_PASSTHROUGH: "true"`, `interface.name: eth{ifindex+1}`, `group_vars.ansible_user/ssh_pass: admin/admin@123`. No `external:` block at all for this device (only the inherited `junos.external.image: none` applies).
- **Real environment note**: the owner's `restore-square.clab.yml` shows the vjunos-switch containerlab endpoints already named `ge-0/0/0`, `ge-0/0/1`, `ge-0/0/2` — i.e. the *actual* deployed containerlab kind exposes the Junos-native interface name directly as the veth/link endpoint, not `eth{ifindex+1}` as netlab's own (older) `clab.interface.name` default says. This is irrelevant to `external` (which never reads `clab.*` anyway) but confirms that for this device the plain `interface_name: ge-0/0/{ifindex}` template netlab uses under `external` is exactly the name the running container also uses.

### vptx (`netsim/devices/vptx.yml`) — netlab's Juniper "PTX"/Junos Evolved profile

- `parent: junos`, `interface_name: et-0/0/{ifindex}` (line 4), `mgmt_if: "re0:mgmt-0"` (line 5) — a Junos-Evolved-style management-interface name, different from plain Junos `fxp0`.
- `group_vars.netlab_device_type: vptx` (line 7).
- `features:` overrides: `evpn` (`asymmetrical_irb`, `irb`, `multi_rt`, `bundle: [vlan_aware]`, `transport: [vxlan]`), `gateway.protocol: [anycast, vrrp]`, `lag.passive: True`, `vlan` (`model: l3-switch`, `svi_interface_name: irb.{vlan}`, `subif_name: "{ifname}.{vlan.access_id}"`, `native_routed`), `vxlan.requires: [evpn]`.
- `libvirt:` block: `image: juniper/vptx`, `pre_install: vptx`.
- `clab:` (34-48): `image: vrnetlab/juniper_vjunosevolved:25.2R1.8-EVO`, **`node.kind: juniper_vjunosevolved`**, `interface.name: eth{ifindex+1}`, `group_vars.ansible_user/ssh_pass: admin/admin@123`.
- **No `external:` block** for vptx at all (inherits only `junos.external.image: none`).

**Is there a profile for `cjunosevolved`?** No. `netsim/devices/` has no `cjunosevolved.py`/`.yml`. `vptx` is the closest available profile and is what the owner would have to use as a stand-in, but it is **not the same containerlab kind**: netlab's `vptx.clab.node.kind` is `juniper_vjunosevolved` (the vrnetlab-wrapped VM kind, image `vrnetlab/juniper_vjunosevolved:...`), while the owner's real node uses kind `juniper_cjunosevolved` (image `n24l/cjunosevolved:26.2R1.7-EVO`) — a **native container** implementation, not a VM-in-a-container. These are two different containerlab kinds with different lifecycle/boot semantics; only the *interface-naming convention* (`et-0/0/{ifindex}`, unit-suffixed to `.0` by the Junos quirk code, see below) and the general Junos config dialect carry over, which is exactly what matters for `provider: external` (no clab node/image is generated at all).

### iosxr (`netsim/devices/iosxr.yml`) and its parent xr (`netsim/devices/xr.yml`)

- `xr.yml` (meta device, `_meta_device: True`): `mgmt_if: MgmtEth0/RP0/CPU0/0` (line 6), `interface_name: GigabitEthernet0/0/0/{ifindex}` (line 7), `loopback_interface_name: Loopback{ifindex}` (line 8), `ifindex_offset: 0` (line 9). `features:` (20-128) is the full XR feature set: `initial` (`ipv4.unnumbered`, `ipv6.lla`, `min_mtu: 68`, `min_phy_mtu: 1500`, `max_mtu: 9216`, `collect`, `reload`), `bgp` (`activate_af`, `advertise`, `aggregate`, `allowas_in`, `as_override`, `confederation`, `default_originate`, `gtsm`, `import`, `local_as[_ibgp]`, `multihop.vrf`, `passive`, `password`, `remove_private_as.valid`+caveats, `rs_client`, `tcp_ao`, `timers`, `vrf_local_as`), `gateway.protocol: [vrrp]`, `isis`, `mpls`, `ospf`, `routing` (with `caveats-iosxr` markers on aspath/community/prefix), `services`, `sr`, `evpn` (`transport.{mpls,sr,cp_vxlan}: [ibgp]`, `asymmetrical_irb: False`), `vrf`. `external: {image: none}` (129-130). `clab.group_vars.netlab_ready: [ssh]`, `clab.node.env.CLAB_MGMT_VRF: management` — clab-only.
- `iosxr.yml` (parent `xr`): `mgmt_if: MgmtEth0/RP0/CPU0/0` (restated, line 4), `interface_name: GigabitEthernet0/0/0/{ifindex}` (line 5, restated), `loopback_interface_name: Loopback{ifindex}` (line 6), `ifindex_offset: 0` (line 7). Adds `features.srv6` (`bgp`, `isis`, `vpn`). `clab:` (21-40): **`node.kind: cisco_xrd`**, `runtime: docker`, `config_templates.netlab-config: /config/netlab/netlab-config.sh:sh`, `mgmt_if: MgmtEth0/RP0/CPU0/0` (clab-scoped, same value), `interface.name: Gi0-0-0-{ifindex}`, `features.initial.config_mode: [sh]`, `image: ios-xr/xrd-control-plane:25.2.1`, `group_vars.ansible_user/ssh_pass/become_password: clab/clab@123`.

**Is there a profile for `xrv9k`?** No. netlab's only Cisco-XR-family clab kind is `cisco_xrd` (containerized control-plane image, `ios-xr/xrd-control-plane:25.2.1`), which is **not** `cisco_xrv9k` (the owner's real node, image `n24l/cisco_xrv9k:24.3.1`, a full vrnetlab-wrapped XR VM). `iosxr` is the stand-in a user would pick. The interface-naming template (`GigabitEthernet0/0/0/{ifindex}`, `ifindex_offset: 0`) matches the owner's real endpoint form (`Gi0/0/0/0`, `Gi0/0/0/1` in the clab file expand to the same full IOS-XR name), so `external`'s naming is fine; what differs (and is irrelevant to `external`) is the `clab.node.kind`/`image`/`runtime` that would matter only if this profile were ever used with `provider: clab`.

### linux (`netsim/devices/linux.yml`)

- `interface_name: eth{ifindex}` (line 4), `mgmt_if: eth0` (line 7), `loopback_interface_name: lo{ifindex if ifindex else ""}` (line 6), `role: host` (line 8), `docparent: False`.
- `features:` `lag.passive: False`, `routing.static: true`, `initial` (`collect: false`, `reload: false`, `ipv4.unnumbered: peer`, `ipv6.lla`/`use_ra`, `roles: [host]`).
- `libvirt:` block for the VM form (`bento/ubuntu-24.04`).
- `clab:` (51-84): `image: python:3.13-alpine` (not the multitool image the manager uses), `node.kind: linux`, `node_config` special `:ns`/`:sh` delivery modes (irrelevant to `external`), `features.initial.roles: [host, bridge]`, `config_templates.hosts: /etc/hosts:shared`.
- `external: {image: none}` (85-86).

### `_common.py` (`netsim/devices/_common.py`)

Shared quirk helpers used by several device modules, not device-specific data: `check_indirect_static_routes` (flags static routes without a real next-hop interface), `check_tagged_vlan_1`, `requires_plugin` (errors if a device needs a plugin the topology hasn't loaded), `check_daemon_dataplane_config` (wires a `/etc/dataplane-wait.sh` gate for daemons whose control plane must wait on a separately-configured dataplane — a clab-only mechanism, sets `node.clab.cmd`/`config_templates`).

### `netsim/topology-defaults.yml`

Top-level file is a pure include manifest (lines 1-47): `provider: libvirt` is the *global* default provider (line 5; our topologies always set `provider: external` explicitly, overriding it). `_include: [defaults/*.yml, modules/*.yml]` (17-19), `providers._include: [providers/*.yml]` (23-25), `devices._include: [devices/*.yml]` (29-31), `daemons._include: [daemons/*.yml]` (33-35), `outputs._include: [outputs/*.yml]` (39-41), `tools._include: [tools/*.yml]` (45-47). The actual `devices`/`providers`/`outputs` content lives in the per-file YAMLs already covered above and in Tasks 2-3.

### How the `initial` template names the management interface

`netsim/ansible/templates/initial/eos.j2:34`: `interface {{ mgmt.ifname|default('Management1') }}` — uses the node's `mgmt.ifname` if set, otherwise falls back to the **hardcoded literal** `Management1` (not the device's `mgmt_if` default attribute — the fallback string is baked into the template itself). Junos/IOS-XR `initial` templates reference the mgmt interface only inside the `lldp`/`no management enable` disable blocks (`re0:mgmt-0` for vptx, `fxp0` for vjunos-switch, `MgmtEth0/RP0/CPU0/0` for IOS-XR — all taken from `mgmt.ifname`, which is populated from the device's `mgmt_if` attribute unless the topology sets `mgmt.ifname` explicitly on the node).

---

## Task 2 — netlab topology for the square, `provider: external`

### Real containerlab file (copied read-only, verbatim)

`/srv/containerlab-node-manager/projects/restore-square/restore-square.clab.yml`, copied to
`proto-external/restore-square.clab.yml.orig`:

```yaml
name: restore-square
mgmt:
  network: clab
  ipv4-subnet: 172.20.20.0/24
topology:
  defaults:
    env:
      TZ: UTC
  nodes:
    ceos:
      kind: arista_ceos
      image: n24l/ceos:4.35.0F
      mgmt-ipv4: 172.20.20.101
    cjunosevolved:
      kind: juniper_cjunosevolved
      image: n24l/cjunosevolved:26.2R1.7-EVO
      mgmt-ipv4: 172.20.20.102
    vjunos-switch:
      kind: juniper_vjunosswitch
      image: n24l/vjunos-switch:23.2R1.14
      mgmt-ipv4: 172.20.20.103
    xrv9k:
      kind: cisco_xrv9k
      image: n24l/cisco_xrv9k:24.3.1
      mgmt-ipv4: 172.20.20.104
    host1:
      kind: linux
      image: ghcr.io/srl-labs/network-multitool:latest
      mgmt-ipv4: 172.20.20.105
  links:
    - endpoints: ["ceos:eth1", "cjunosevolved:et-0/0/0"]
    - endpoints: ["cjunosevolved:et-0/0/1", "vjunos-switch:ge-0/0/0"]
    - endpoints: ["vjunos-switch:ge-0/0/1", "xrv9k:Gi0/0/0/0"]
    - endpoints: ["xrv9k:Gi0/0/0/1", "ceos:eth2"]
    - endpoints: ["host1:eth1", "vjunos-switch:ge-0/0/2"]
    - endpoints: ["host1:eth2", "ceos:eth3"]
```

`mgmt-ipv4` addresses were present for every node, so no invented addresses were needed. Interface
form note: the `ceos:eth1`/`eth2`/`eth3` endpoint names are the container-side veth names; the
NOS-side (EOS CLI) name is the offset-by-1 `Ethernet{N}` form, which is exactly netlab's default
`interface_name: Ethernet{ifindex}` template — confirmed by the rendered config below.

### netlab topology file written (`proto-external/square-v1.yml`, full contents)

```yaml
name: restore-square

provider: external

module: [ ospf, bgp ]

defaults:
  device: linux            # harmless global default; every node below sets its own device

bgp:
  as: 65000                 # single AS -> netlab auto-builds a full iBGP mesh over the 4 routers

ospf:
  area: 0.0.0.0

addressing:
  loopback:
    ipv4: 10.255.0.0/24
    ipv6: 2001:db8:ff::/48
  p2p:
    ipv4: 10.0.0.0/16
    ipv6: 2001:db8:1::/48
  lan:
    ipv4: 172.31.0.0/16
    ipv6: 2001:db8:2::/48

nodes:
  ceos:
    device: eos
    mgmt.ipv4: 172.20.20.101
  cjunosevolved:
    device: vptx
    mgmt.ipv4: 172.20.20.102
  vjunos-switch:
    device: vjunos-switch
    mgmt.ipv4: 172.20.20.103
  xrv9k:
    device: iosxr
    mgmt.ipv4: 172.20.20.104
  host1:
    device: linux
    module: []               # plain host: no OSPF/BGP daemon, just an addressed interface
    mgmt.ipv4: 172.20.20.105

links:
  # Square edges (order matches the real clab file exactly)
  - ceos:
      ifname: Ethernet1
    cjunosevolved:
      ifname: et-0/0/0
  - cjunosevolved:
      ifname: et-0/0/1
    vjunos-switch:
      ifname: ge-0/0/0
  - vjunos-switch:
      ifname: ge-0/0/1
    xrv9k:
      ifname: GigabitEthernet0/0/0/0
  - xrv9k:
      ifname: GigabitEthernet0/0/0/1
    ceos:
      ifname: Ethernet2
  # host1 stub links
  - host1:
      ifname: eth1
    vjunos-switch:
      ifname: ge-0/0/2
  - host1:
      ifname: eth2
    ceos:
      ifname: Ethernet3
```

Device stand-ins used (see Task 1): `ceos`→`eos` (exact clab-kind match), `cjunosevolved`→`vptx`
(**stand-in**, real kind `juniper_cjunosevolved` ≠ netlab's `juniper_vjunosevolved`),
`vjunos-switch`→`vjunos-switch` (exact match), `xrv9k`→`iosxr` (**stand-in**, real kind
`cisco_xrv9k` ≠ netlab's `cisco_xrd`), `host1`→`linux` (exact match, image differs — irrelevant
under `external`, which never emits an image).

**BGP design choice: single AS 65000, iBGP full mesh, not one AS per router.** All four routers are
already directly reachable over OSPF-learned loopbacks (area 0.0.0.0 carries the loopbacks and every
link), so an eBGP-per-edge design would add per-link AS numbers and AS-path/multihop handling for
exactly zero additional reachability — non-adjacent pairs (e.g. `ceos`↔`vjunos-switch`) still need
either extra eBGP multihop policy or a route-reflector-shaped design to reach each other, since eBGP
sessions in netlab's BGP module are only auto-built between directly connected interfaces. A single AS
with the OSPF underlay already in place lets netlab's `bgp` module auto-build the full iBGP mesh
(4 nodes → 6 sessions, trivial) with zero extra configuration, and demonstrates `next_hop_self`,
loopback-sourced sessions and community propagation exactly the way the module intends. This is the
simpler, more representative choice for a 4-node square with no route-reflector need.

### Command run

```
$ cd proto-external/run1   # topology.yml == square-v1.yml
$ export HOME=$(realpath ../scratch-home)      # scratch HOME, see Task 3(c)
$ netlab create -p external -o config -o yaml=transformed.yaml -o json=transformed.json topology.yml
[CONFIG]  ceos: normalize,initial,ospf,bgp
[CONFIG]  cjunosevolved: initial,ospf,bgp
[CONFIG]  vjunos-switch: initial,ospf,bgp
[CONFIG]  xrv9k: initial,ospf,bgp
[CONFIG]  host1: initial,routing
Created transformed topology dump in YAML format in transformed.yaml
Created transformed topology dump in JSON format in transformed.json
EXIT: 0
```

`-o` syntax (`netsim/cli/create.py:66`, `docs/outputs/yaml-or-json.md`): `-o <module>[:<option>][=<file>]`,
repeatable. `config` takes no options/output file (always writes under `./node_files/`); `yaml=<file>`
and `json=<file>` write the whole transformed topology to the named file (default stdout, `-`).

### Full file tree created (`find . -type f | sort`, run against `run1/`)

```
./node_files/ceos/bgp
./node_files/ceos/initial
./node_files/ceos/normalize
./node_files/ceos/ospf
./node_files/cjunosevolved/bgp
./node_files/cjunosevolved/initial
./node_files/cjunosevolved/ospf
./node_files/host1/initial
./node_files/host1/routing
./node_files/vjunos-switch/bgp
./node_files/vjunos-switch/initial
./node_files/vjunos-switch/ospf
./node_files/xrv9k/bgp
./node_files/xrv9k/initial
./node_files/xrv9k/ospf
./topology.yml
./transformed.json
./transformed.yaml
```

Under scratch `$HOME` (no `-p`/pre-existing state):

```
./scratch-home/.netlab/stats.json
./scratch-home/.netlab/stats.json.lock
./scratch-home/.netlab/topology-defaults.pickle
```

Naming/order rule (`netsim/outputs/config.py:88-105`): the per-node file list is
`['normalize'?] + ['initial'] + node.module + node.config`, each module producing one file at
`node_files/<node>/<module-name>` (no extension; `normalize` only appears when
`features.initial.normalize` is set — true for `eos`, which is why `ceos` alone gets a `normalize`
file). No `.cfg`/`.txt` extension is added by default; a `config_templates` entry can set one via the
`mode` suffix (`:sh`, `:cp_sh`, etc., not used by any of our four devices' `initial`/`ospf`/`bgp` config).

### Full rendered configuration — all four network nodes

**ceos** (`node_files/ceos/initial` + `ospf` + `bgp`, concatenated in generation order):

```
hostname ceos
!
logging monitor debugging
aaa authorization exec default local
!
lldp run
ip routing
ipv6 unicast-routing
!
!
ip host cjunosevolved 10.255.0.2 10.0.0.2 10.0.0.5
ip host host1 172.31.0.5 172.31.1.5
ip host vjunos-switch 10.255.0.3 10.0.0.6 10.0.0.9 172.31.0.3
ip host xrv9k 10.255.0.4 10.0.0.10 10.0.0.14
ipv6 host cjunosevolved 2001:db8:ff:2::1
ipv6 host host1 2001:db8:2::5
ipv6 host vjunos-switch 2001:db8:ff:3::1
ipv6 host xrv9k 2001:db8:ff:4::1
!
interface Management1
 no lldp transmit
 no lldp receive
!
interface Loopback0
 ip address 10.255.0.1/32
 ipv6 nd ra interval 5
 ipv6 address 2001:db8:ff:1::1/64
!
interface Ethernet1
 no switchport
 description ceos -> cjunosevolved
 ip address 10.0.0.1/30
 ipv6 nd ra interval 5
 ipv6 address 2001:db8:1::1/64
 mac-address caf0.0001.0001
!
 no shutdown
!
interface Ethernet2
 no switchport
 description ceos -> xrv9k
 ip address 10.0.0.13/30
 ipv6 nd ra interval 5
 ipv6 address 2001:db8:1:3::1/64
 mac-address caf0.0001.0002
!
 no shutdown
!
interface Ethernet3
 no switchport
 description ceos -> host1 [stub]
 ip address 172.31.1.1/24
 ipv6 nd ra interval 5
 ipv6 address 2001:db8:2:1::1/64
 mac-address caf0.0001.0003
!
 no shutdown
!
!
router ospf 1
 router-id 10.255.0.1
 tunnel routes
 interface unnumbered hello mask tx 0.0.0.0
 timers spf delay initial 100 200 500
 timers lsa rx min interval 100
 timers lsa tx delay initial 100 200 500


 passive-interface Ethernet3
!
interface Loopback0
! 
 ip ospf area 0.0.0.0
!
interface Ethernet1
! ceos -> cjunosevolved
 ip ospf area 0.0.0.0
 ip ospf network point-to-point
!
interface Ethernet2
! ceos -> xrv9k
 ip ospf area 0.0.0.0
 ip ospf network point-to-point
!
interface Ethernet3
! ceos -> host1
 ip ospf area 0.0.0.0
 ip ospf network point-to-point
!

!
! OSPFv3 configuration
!
interface Loopback0
! 
 ipv6 ospf 1 area 0.0.0.0
!
interface Ethernet1
! ceos -> cjunosevolved
 ipv6 ospf 1 area 0.0.0.0
 ipv6 ospf network point-to-point
!
interface Ethernet2
! ceos -> xrv9k
 ipv6 ospf 1 area 0.0.0.0
 ipv6 ospf network point-to-point
!
interface Ethernet3
! ceos -> host1
 ipv6 ospf 1 area 0.0.0.0
 ipv6 ospf network point-to-point
!
!
ipv6 router ospf 1
 router-id 10.255.0.1
 timers spf delay initial 100 200 500
 timers lsa rx min interval 100
 timers lsa tx delay initial 100 200 500


 passive-interface Ethernet3
!
route-map next-hop-self-ipv4 permit 10
   match route-type external
   set ip next-hop peer-address
!
route-map next-hop-self-ipv4 permit 20
!
route-map next-hop-self-ipv6 permit 10
   match route-type external
   set ipv6 next-hop peer-address
!
route-map next-hop-self-ipv6 permit 20
!
!
router bgp 65000
  bgp advertise-inactive
  bgp log-neighbor-changes
  no bgp default ipv4-unicast
  no bgp default ipv6-unicast
  router-id 10.255.0.1
!
  neighbor 10.255.0.2 remote-as 65000
  neighbor 10.255.0.2 description cjunosevolved
  neighbor 10.255.0.2 update-source Loopback0
  neighbor 10.255.0.2 send-community standard extended large 
!
  neighbor 2001:db8:ff:2::1 remote-as 65000
  neighbor 2001:db8:ff:2::1 description cjunosevolved
  neighbor 2001:db8:ff:2::1 update-source Loopback0
  neighbor 2001:db8:ff:2::1 send-community standard extended large 
!
  neighbor 10.255.0.3 remote-as 65000
  neighbor 10.255.0.3 description vjunos-switch
  neighbor 10.255.0.3 update-source Loopback0
  neighbor 10.255.0.3 send-community standard extended large 
!
  neighbor 2001:db8:ff:3::1 remote-as 65000
  neighbor 2001:db8:ff:3::1 description vjunos-switch
  neighbor 2001:db8:ff:3::1 update-source Loopback0
  neighbor 2001:db8:ff:3::1 send-community standard extended large 
!
  neighbor 10.255.0.4 remote-as 65000
  neighbor 10.255.0.4 description xrv9k
  neighbor 10.255.0.4 update-source Loopback0
  neighbor 10.255.0.4 send-community standard extended large 
!
  neighbor 2001:db8:ff:4::1 remote-as 65000
  neighbor 2001:db8:ff:4::1 description xrv9k
  neighbor 2001:db8:ff:4::1 update-source Loopback0
  neighbor 2001:db8:ff:4::1 send-community standard extended large 
!
!
 address-family ipv4

!
  network 10.255.0.1/32
  network 172.31.1.0/24
!
  neighbor 10.255.0.2 activate
  neighbor 10.255.0.2 route-map next-hop-self-ipv4 out
  neighbor 10.255.0.3 activate
  neighbor 10.255.0.3 route-map next-hop-self-ipv4 out
  neighbor 10.255.0.4 activate
  neighbor 10.255.0.4 route-map next-hop-self-ipv4 out
!
 address-family ipv6

!
  network 2001:db8:ff:1::/64
  network 2001:db8:2:1::/64
!
  neighbor 2001:db8:ff:2::1 activate
  neighbor 2001:db8:ff:2::1 route-map next-hop-self-ipv6 out
  neighbor 2001:db8:ff:3::1 activate
  neighbor 2001:db8:ff:3::1 route-map next-hop-self-ipv6 out
  neighbor 2001:db8:ff:4::1 activate
  neighbor 2001:db8:ff:4::1 route-map next-hop-self-ipv6 out
```

**cjunosevolved** (`initial` + `ospf` + `bgp`):

```
system {
  host-name cjunosevolved;
  static-host-mapping {
    ceos inet 10.255.0.1;
    vjunos-switch inet 10.255.0.3;
    xrv9k inet 10.255.0.4;
    host1 inet 172.31.0.5;
  }
}

interfaces {

  lo0.0 {

      family inet {
        address 10.255.0.2/32;
      }
      family inet6 {
        address 2001:db8:ff:2::1/64;
      }
  }
  et-0/0/0.0 {
    description "cjunosevolved -> ceos";

      family inet {
        address 10.0.0.2/30;
      }
      family inet6 {
        address 2001:db8:1::2/64;
      }
  }
  et-0/0/1.0 {
    description "cjunosevolved -> vjunos-switch";

      family inet {
        address 10.0.0.5/30;
      }
      family inet6 {
        address 2001:db8:1:1::1/64;
      }
  }
}
protocols {
  lldp {
    interface re0:mgmt-0 {
      disable;
    }
    interface all;
  }
  router-advertisement {
    interface et-0/0/0.0;
    interface et-0/0/1.0;
  }
}
routing-options {
  router-id 10.255.0.2
}
protocols {
  delete: ospf;
}

protocols {
  ospf {
    area 0.0.0.0 {
      interface lo0.0 {
      }
    }
    area 0.0.0.0 {
      interface et-0/0/0.0 {
        interface-type p2p;
      }
    }
    area 0.0.0.0 {
      interface et-0/0/1.0 {
        interface-type p2p;
      }
    }
  }
}

protocols {
  delete: ospf3;
}

protocols {
  ospf3 {
    area 0.0.0.0 {
      interface lo0.0 {
      }
    }
    area 0.0.0.0 {
      interface et-0/0/0.0 {
        interface-type p2p;
      }
    }
    area 0.0.0.0 {
      interface et-0/0/1.0 {
        interface-type p2p;
      }
    }
  }
}


routing-options {
  autonomous-system 65000;
  router-id 10.255.0.2
}


policy-options {
  delete: policy-statement next-hop-ebgp-ipv4;
  delete: policy-statement next-hop-all-ipv4;
  delete: policy-statement next-hop-ebgp-ipv6;
  delete: policy-statement next-hop-all-ipv6;

  delete: policy-statement bgp-default-redistribute;
  delete: route-filter-list bgp-default-announce-ipv4;
  delete: route-filter-list bgp-default-announce-ipv6;

  policy-statement bgp-final {
    term final-option {
      then {
        accept;
      }
    }
  }

  route-filter-list bgp-default-announce-ipv4 {
    10.255.0.2/32 exact;
  }
  route-filter-list bgp-default-announce-ipv6 {
    2001:db8:ff:2::/64 exact;
  }

  policy-statement bgp-default-redistribute {
    term advertise-ipv4 {
      from {
        route-filter-list bgp-default-announce-ipv4;
      }
      then {
        next policy;
      }
    }
    term advertise-ipv6 {
      from {
        route-filter-list bgp-default-announce-ipv6;
      }
      then {
        next policy;
      }
    }

    term redis_bgp {
      from protocol bgp;
      then {
        next policy;
      }
    }

    term default {
      then reject;
    }
  }


  policy-statement next-hop-ebgp-ipv4 {
    term next-hop-self-ipv4 {
      from {
        family inet;
        route-type external;
      }
      then {
        next-hop self;
      }
    }
  }
  policy-statement next-hop-all-ipv4 {
    term next-hop-self-ipv4 {
      from {
        family inet;
      }
      then {
        next-hop self;
      }
    }
  }
  policy-statement next-hop-ebgp-ipv6 {
    term next-hop-self-ipv6 {
      from {
        family inet6;
        route-type external;
      }
      then {
        next-hop self;
      }
    }
  }
  policy-statement next-hop-all-ipv6 {
    term next-hop-self-ipv6 {
      from {
        family inet6;
      }
      then {
        next-hop self;
      }
    }
  }

  policy-statement bgp-initial {
    term initial-cleanup {
      then {
        next policy;
      }
    }
  }

}
protocols {
  delete: bgp;
}
protocols {
  bgp {
    group ibgp-peers-ipv4 {
      type internal;
      export [ 
          next-hop-ebgp-ipv4 next-hop-ebgp-ipv6 bgp-default-redistribute bgp-final
        ];
      advertise-inactive;
      neighbor 10.255.0.1 {

        local-address 10.255.0.2;
        description ceos;
        family inet {
          unicast;
        }
      }
      neighbor 10.255.0.3 {

        local-address 10.255.0.2;
        description vjunos-switch;
        family inet {
          unicast;
        }
      }
      neighbor 10.255.0.4 {

        local-address 10.255.0.2;
        description xrv9k;
        family inet {
          unicast;
        }
      }
    }
    group ibgp-peers-ipv6 {
      type internal;
      export [ 
          next-hop-ebgp-ipv4 next-hop-ebgp-ipv6 bgp-default-redistribute bgp-final
        ];
      advertise-inactive;
      neighbor 2001:db8:ff:1::1 {

        local-address 2001:db8:ff:2::1;
        description ceos;
        family inet6 {
          unicast;
        }
      }
      neighbor 2001:db8:ff:3::1 {

        local-address 2001:db8:ff:2::1;
        description vjunos-switch;
        family inet6 {
          unicast;
        }
      }
      neighbor 2001:db8:ff:4::1 {

        local-address 2001:db8:ff:2::1;
        description xrv9k;
        family inet6 {
          unicast;
        }
      }
    }
    group ebgp-peers {
      export [ 
          bgp-default-redistribute bgp-final
        ];
      advertise-inactive;
    }
  }
}
```

**vjunos-switch** (`initial` + `ospf` + `bgp`):

```
system {
  host-name vjunos-switch;
  static-host-mapping {
    ceos inet 10.255.0.1;
    cjunosevolved inet 10.255.0.2;
    xrv9k inet 10.255.0.4;
    host1 inet 172.31.0.5;
  }
}

interfaces {

  lo0.0 {

      family inet {
        address 10.255.0.3/32;
      }
      family inet6 {
        address 2001:db8:ff:3::1/64;
      }
  }
  ge-0/0/0.0 {
    description "vjunos-switch -> cjunosevolved";

      family inet {
        address 10.0.0.6/30;
      }
      family inet6 {
        address 2001:db8:1:1::2/64;
      }
  }
  ge-0/0/1.0 {
    description "vjunos-switch -> xrv9k";

      family inet {
        address 10.0.0.9/30;
      }
      family inet6 {
        address 2001:db8:1:2::1/64;
      }
  }
  ge-0/0/2.0 {
    description "vjunos-switch -> host1 [stub]";

      family inet {
        address 172.31.0.3/24;
      }
      family inet6 {
        address 2001:db8:2::3/64;
      }
  }
}
protocols {
  lldp {
    interface fxp0 {
      disable;
    }
    interface all;
  }
  router-advertisement {
    interface ge-0/0/0.0;
    interface ge-0/0/1.0;
    interface ge-0/0/2.0;
  }
}
routing-options {
  router-id 10.255.0.3
}
protocols {
  delete: ospf;
}

protocols {
  ospf {
    area 0.0.0.0 {
      interface lo0.0 {
      }
    }
    area 0.0.0.0 {
      interface ge-0/0/0.0 {
        interface-type p2p;
      }
    }
    area 0.0.0.0 {
      interface ge-0/0/1.0 {
        interface-type p2p;
      }
    }
    area 0.0.0.0 {
      interface ge-0/0/2.0 {
        interface-type p2p;
        passive;
      }
    }
  }
}

protocols {
  delete: ospf3;
}

protocols {
  ospf3 {
    area 0.0.0.0 {
      interface lo0.0 {
      }
    }
    area 0.0.0.0 {
      interface ge-0/0/0.0 {
        interface-type p2p;
      }
    }
    area 0.0.0.0 {
      interface ge-0/0/1.0 {
        interface-type p2p;
      }
    }
    area 0.0.0.0 {
      interface ge-0/0/2.0 {
        interface-type p2p;
        passive;
      }
    }
  }
}


routing-options {
  autonomous-system 65000;
  router-id 10.255.0.3
}


policy-options {
  delete: policy-statement next-hop-ebgp-ipv4;
  delete: policy-statement next-hop-all-ipv4;
  delete: policy-statement next-hop-ebgp-ipv6;
  delete: policy-statement next-hop-all-ipv6;

  delete: policy-statement bgp-default-redistribute;
  delete: route-filter-list bgp-default-announce-ipv4;
  delete: route-filter-list bgp-default-announce-ipv6;

  policy-statement bgp-final {
    term final-option {
      then {
        accept;
      }
    }
  }

  route-filter-list bgp-default-announce-ipv4 {
    10.255.0.3/32 exact;
    172.31.0.0/24 exact;
  }
  route-filter-list bgp-default-announce-ipv6 {
    2001:db8:ff:3::/64 exact;
    2001:db8:2::/64 exact;
  }

  policy-statement bgp-default-redistribute {
    term advertise-ipv4 {
      from {
        route-filter-list bgp-default-announce-ipv4;
      }
      then {
        next policy;
      }
    }
    term advertise-ipv6 {
      from {
        route-filter-list bgp-default-announce-ipv6;
      }
      then {
        next policy;
      }
    }

    term redis_bgp {
      from protocol bgp;
      then {
        next policy;
      }
    }

    term default {
      then reject;
    }
  }


  policy-statement next-hop-ebgp-ipv4 {
    term next-hop-self-ipv4 {
      from {
        family inet;
        route-type external;
      }
      then {
        next-hop self;
      }
    }
  }
  policy-statement next-hop-all-ipv4 {
    term next-hop-self-ipv4 {
      from {
        family inet;
      }
      then {
        next-hop self;
      }
    }
  }
  policy-statement next-hop-ebgp-ipv6 {
    term next-hop-self-ipv6 {
      from {
        family inet6;
        route-type external;
      }
      then {
        next-hop self;
      }
    }
  }
  policy-statement next-hop-all-ipv6 {
    term next-hop-self-ipv6 {
      from {
        family inet6;
      }
      then {
        next-hop self;
      }
    }
  }

  policy-statement bgp-initial {
    term initial-cleanup {
      then {
        next policy;
      }
    }
  }

}
protocols {
  delete: bgp;
}
protocols {
  bgp {
    group ibgp-peers-ipv4 {
      type internal;
      export [ 
          next-hop-ebgp-ipv4 next-hop-ebgp-ipv6 bgp-default-redistribute bgp-final
        ];
      advertise-inactive;
      neighbor 10.255.0.1 {

        local-address 10.255.0.3;
        description ceos;
        family inet {
          unicast;
        }
      }
      neighbor 10.255.0.2 {

        local-address 10.255.0.3;
        description cjunosevolved;
        family inet {
          unicast;
        }
      }
      neighbor 10.255.0.4 {

        local-address 10.255.0.3;
        description xrv9k;
        family inet {
          unicast;
        }
      }
    }
    group ibgp-peers-ipv6 {
      type internal;
      export [ 
          next-hop-ebgp-ipv4 next-hop-ebgp-ipv6 bgp-default-redistribute bgp-final
        ];
      advertise-inactive;
      neighbor 2001:db8:ff:1::1 {

        local-address 2001:db8:ff:3::1;
        description ceos;
        family inet6 {
          unicast;
        }
      }
      neighbor 2001:db8:ff:2::1 {

        local-address 2001:db8:ff:3::1;
        description cjunosevolved;
        family inet6 {
          unicast;
        }
      }
      neighbor 2001:db8:ff:4::1 {

        local-address 2001:db8:ff:3::1;
        description xrv9k;
        family inet6 {
          unicast;
        }
      }
    }
    group ebgp-peers {
      export [ 
          bgp-default-redistribute bgp-final
        ];
      advertise-inactive;
    }
  }
}
```

**xrv9k** (`initial` + `ospf` + `bgp`):

```
hostname xrv9k
!
domain lookup disable
!
lldp
 no management enable
!
domain ipv4 host ceos 10.255.0.1
domain ipv4 host cjunosevolved 10.255.0.2
domain ipv4 host vjunos-switch 10.255.0.3
domain ipv4 host host1 172.31.0.5
domain ipv6 host ceos 2001:db8:ff:1::1
domain ipv6 host cjunosevolved 2001:db8:ff:2::1
domain ipv6 host vjunos-switch 2001:db8:ff:3::1
domain ipv6 host host1 2001:db8:2::5
!
interface Loopback0
 no shutdown
 ipv4 address 10.255.0.4 255.255.255.255
 ipv6 address 2001:db8:ff:4::1/64
!
interface GigabitEthernet0/0/0/0
 no shutdown
 description xrv9k -> vjunos-switch
 ipv4 address 10.0.0.10 255.255.255.252
 ipv6 address 2001:db8:1:2::2/64
 ipv6 nd ra-interval 5
!
interface GigabitEthernet0/0/0/1
 no shutdown
 description xrv9k -> ceos
 ipv4 address 10.0.0.14 255.255.255.252
 ipv6 address 2001:db8:1:3::2/64
 ipv6 nd ra-interval 5
!
!
router ospf 1
!
! These throttle timers are probably too aggressive for a production network but
! make labs run better ;)
!
 log adjacency changes
 timers throttle spf 10 20 100
 timers throttle lsa all 10 20 100
 router-id 10.255.0.4

 loopback stub-network enable
 area 0.0.0.0
  interface Loopback0
  interface GigabitEthernet0/0/0/0
   network point-to-point
  interface GigabitEthernet0/0/0/1
   network point-to-point

router ospfv3 1
!
! These throttle timers are probably too aggressive for a production network but
! make labs run better ;)
!
 log adjacency changes
 timers throttle spf 10 20 100
 timers throttle lsa all 10 20 100
 router-id 10.255.0.4

 area 0.0.0.0
  interface Loopback0
  interface GigabitEthernet0/0/0/0
   network point-to-point
  interface GigabitEthernet0/0/0/1
   network point-to-point

!
router bgp 65000
 bgp unsafe-ebgp-policy
 bgp scan-time 5
 bgp update-delay 5
 bgp router-id 10.255.0.4

!
 address-family ipv4 unicast
  bgp scan-time 5
!
!
  network 10.255.0.4/32
!
 address-family ipv6 unicast
  bgp scan-time 5
!
!
  network 2001:db8:ff:4::/64
!
 neighbor 10.255.0.1
  remote-as 65000
  description ceos
  update-source Loopback0
  address-family ipv4 unicast
   next-hop-self

!
 neighbor 10.255.0.2
  remote-as 65000
  description cjunosevolved
  update-source Loopback0
  address-family ipv4 unicast
   next-hop-self

!
 neighbor 10.255.0.3
  remote-as 65000
  description vjunos-switch
  update-source Loopback0
  address-family ipv4 unicast
   next-hop-self

!
 neighbor 2001:db8:ff:1::1
  remote-as 65000
  description ceos
  update-source Loopback0
  address-family ipv6 unicast
   next-hop-self

!
 neighbor 2001:db8:ff:2::1
  remote-as 65000
  description cjunosevolved
  update-source Loopback0
  address-family ipv6 unicast
   next-hop-self

!
 neighbor 2001:db8:ff:3::1
  remote-as 65000
  description vjunos-switch
  update-source Loopback0
  address-family ipv6 unicast
   next-hop-self
```

All four configs used exactly the `ifname:` values we specified — proof that the explicit
`ifname:` override on `provider: external` does control the literal interface name written into
every config template.

### The Junos "unit 0" trick (why `ifname: et-0/0/0` becomes `et-0/0/0.0` in the config)

`netsim/devices/junos.py:44-51` and `:58-66`:

```python
def unit_0_trick(intf, round='global'):
  oldname = intf.ifname
  newname = oldname + ".0"
  intf.ifname = newname
  intf.junos_interface = oldname
  intf.junos_unit = '0'
...
def fix_unit_0(node, topology):
  for intf in node.get('interfaces', []):
    if not '.' in intf.ifname:
        unit_0_trick(intf)
        ...
```

This runs as a `JUNOS.device_quirks` step (`class JUNOS(_Quirks)`, line 393-408) on every Junos-family
node, unconditionally. **You must specify `ifname: et-0/0/0` (no unit) in the topology; netlab appends
`.0` itself** before the `initial.j2`/`ospf`/`bgp` templates run (verified: `et-0/0/0.0` and
`ge-0/0/0.0` appear in the rendered output above, exactly once, with no double-suffixing).
`netsim/ansible/templates/initial/junos.j2:24` renders `{{ l.ifname }}` literally (`et-0/0/0.0 { ... }`
hierarchical/curly-brace form, not Junos "set" syntax) — so the *template* wants the `.0`-suffixed
name, but the *topology file's* `ifname:` attribute must be given without the suffix.

For IOS-XR, `netsim/ansible/templates/initial/iosxr.j2:21`: `interface {{ l.ifname }}` — no
abbreviation, so the topology's `ifname:` must be the **full** spelled-out name
(`GigabitEthernet0/0/0/0`), not the clab-style abbreviation `Gi0/0/0/0` seen in the containerlab
endpoint. For EOS, `netsim/ansible/templates/initial/eos.j2:38`: `interface {{ l.ifname }}` — again
the full name (`Ethernet1`), not the container veth name (`eth1`).

---

## Task 3 — precise answers, with citations

### (a) Does `-o config` render without Ansible?

**Yes.** `netsim/outputs/config.py` (`ConfigurationFiles.write`, lines 21-109) calls
`templates.create_config_file` (line 24-32) which calls `templates.render_config_template`
(`netsim/utils/templates.py:315-350`) which calls `templates.write_template` →
`get_jinja2_env_for_path` (`templates.py:46-51`):

```python
ENV = Environment(loader=FileSystemLoader(template_path),
        trim_blocks=True, lstrip_blocks=True,
        undefined=filters.j2_Undefined)
```

This is a plain `jinja2.Environment` (not `jinja2.sandbox.SandboxedEnvironment`), populated only with
netlab's own filter shims that emulate the subset of `ansible.utils`/`ansible.builtin` Jinja filters
the templates use (`add_j2_filters`, `templates.py:20-30`). No `ansible-playbook`, no Ansible Python
API, no inventory is touched by `-o config`. Templates live under
`netsim/ansible/templates/<module>/<device>.j2` (reused from the Ansible automation path) and
`netsim/templates/provider/<provider>/...` (provider-specific, e.g. the EOS `ceos-config.j2` used only
for `provider: clab`) — `-o config` under `provider: external` only ever resolves to the
`netsim/ansible/templates/...` tree, per `find_provider_template`
(`netsim/utils/templates.py`, called from `create_config_file`).

### (b) What does `-o config` delete/overwrite in the working directory?

`netsim/outputs/config.py:36-45`, verbatim:

```python
node_files = Path('node_files')
if node_files.exists():
  try:
    shutil.rmtree(node_files)
  except Exception as ex:
    log.error("Failed to remove directory 'node_files'", more_data=[str(ex)], module='config')
```

**Only `./node_files` (relative to cwd), and it is a full recursive delete-then-recreate, not a
per-file overwrite.** Verified empirically: planted `node_files/ceos/STRAY_FILE_SHOULD_BE_DELETED.txt`
and `node_files/STRAY_TOP_LEVEL.txt`, reran `netlab create -p external -o config topology.yml` — both
were gone afterward, only the five expected per-node subdirectories remained. A second check planted
`UNRELATED_FILE.txt` and `UNRELATED_DIR/keep.txt` directly in the run directory (not under
`node_files/`) — both survived the rerun untouched. No other output module deletes a directory first;
`yaml`/`json` outputs (`netsim/outputs/yaml.py:43`, `_files.open_output_file`) just open-and-truncate
the single named file.

### (c) Does `netlab create` write anything outside the cwd?

**Yes, into `$HOME` (never `/tmp`, never the installed package directory).** Two files, both under
`~/.netlab/` (`_files.get_userdir()`, not inspected in detail but confirmed by output paths):

1. `~/.netlab/stats.json` (+ `.json.lock`) — local usage-statistics counters, written on **every**
   CLI invocation including `--help`, via `stats.stats_counter_update('cli.<cmd>.start'/'done')`
   (`netsim/cli/__init__.py:547,551`). Content observed after one `create` run:
   ```json
   {
     "_created": 1790459487,
     "cli": {"create": {"start": {"cnt": 1, ...}, "done": {"cnt": 1, ...}}},
     "_id": "000018d8fd6b03164a8f",
     "_updated": 1790459489
   }
   ```
2. `~/.netlab/topology-defaults.pickle` — a cached, unpickled copy of the fully-merged
   `topology-defaults.yml` tree (`netsim/utils/read.py:86-152`, `PICKLED_YAML_FILES`), refreshed only
   when the package's YAML defaults are newer than the pickle's timestamp. Pure performance cache, not
   part of any given topology's output.

Neither file is deleted or truncated by `-o config`; both only grow/update. No file was ever written
under `/tmp` or under the installed `netsim` package directory in any run.

The **default value of `$HOME`** (when not overridden) is also consulted as an *input*:
`netsim/utils/read.py:20`, `USER_DEFAULTS = ['./topology-defaults.yml', '~/.netlab.yml',
'~/topology-defaults.yml']` — if either of those files exists they are silently merged into
**every** topology's defaults (see (g) below).

### (d) Does `netlab create` open any network connection?

**No, verified two ways.**

*Static*: the only `requests`/`urllib`/`socket` usage in the whole `netsim` package is in
`netsim/cli/create.py` (`import requests` at line 15, `import urllib.parse` at line 12) and
`netsim/cli/api.py` (`import urllib.parse` — unrelated to `create`). `requests.get()` is called
exactly once, inside `http_fetch_content()` (`create.py:80-127`), and `http_fetch_content` is called
from `run()` **only when** `'://' in args.topology` (`create.py:170-171`) — i.e. only if the topology
argument itself is a URL. Our runs always passed a local `topology.yml` path, so this code path never
executes. `netsim/utils/stats.py` (local usage stats) does not import any networking module at all —
it is pure local-file I/O guarded by `filelock.FileLock`.

*Dynamic*: ran `strace -f -e trace=network -o strace-network.log netlab create -p external -o config
-o yaml=... -o json=... topology.yml` (strace 6.8 available on this host). Full captured log:
```
69414 socket(AF_INET6, SOCK_STREAM|SOCK_CLOEXEC, IPPROTO_IP) = 3
69414 bind(3, {sa_family=AF_INET6, sin6_port=htons(0), sin6_flowinfo=htonl(0), inet_pton(AF_INET6, "::1", &sin6_addr), sin6_scope_id=0}, 28) = 0
69414 +++ exited with 0 +++
```
One `socket()` + `bind()` to `::1` port 0, **no `connect()`, no `send*()`, no `recv*()`, no DNS
lookup** — this is a local-loopback capability probe (common CPython/library idiom to test IPv6
availability), not outbound traffic. No other network syscall appears anywhere in the trace.

Usage-statistics collection (`netsim/utils/stats.py`) is **100% local** — `write_stats()`
(`stats.py:96-111`) only ever calls `stats.to_json(filename=stat_name)`; nothing in the module ever
transmits the file anywhere. The `netlab usage stop`/`start` command hints even say so explicitly
(`netsim/cli/usage/utils.py:38`: `'The statistics are not shared with anyone.'`). Disable with
`netlab usage stop` (sets `stats._disabled = True`, `usage/utils.py:22-32`); there is no
`NETLAB_...`-style environment variable for this, only the CLI subcommand.

### (e) Is a pickle snapshot produced even with explicit `-o` selections?

**No.** `netsim/cli/create.py:191-192`: the *default* output list
(`topology.defaults.netlab.create.output`, from `netsim/defaults/netlab.yml:8-14`:
`{config:, provider:, pickle:, tools:, ansible:}`) is only substituted when `args.output` is falsy,
i.e. **no `-o` flag was given at all**. When any `-o` is given, `args.output` is exactly the
user-supplied list and the loop at `create.py:202-211` only instantiates those named output modules.

Verified empirically:
- `netlab create -p external -o config -o yaml=... -o json=... topology.yml` → no
  `netlab.snapshot.pickle` anywhere in the tree.
- `netlab create -p external topology.yml` (no `-o` at all, same topology) →
  ```
  ./ansible.cfg
  ./external.txt
  ./hosts.yml
  ./netlab.snapshot.pickle
  ./topology.yml
  ```
  (plus `node_files/`), i.e. `pickle`, `provider` (→ `external.txt`, see below) and `ansible`
  (→ `hosts.yml`+`ansible.cfg`) all ran because none were suppressed.

`netsim/outputs/pickle.py` (`YAML.write`, lines 18-40 — the class is misleadingly named `YAML` in this
file) writes `netlab.snapshot.pickle` via plain `pickle.dump()`, gated only by being in the active
output-module list — confirms the mechanism.

The default-output `provider` module for `provider: external` renders `netsim/providers/external.yml`'s
`template: external.j2` into `config: external.txt` (`external.yml:5-6`) — a human-readable cabling
table. Its content for our topology, generated by the default run:
```
LAB TOPOLOGY SUMMARY

LAB NAME: restore-square

POINT-TO-POINT LINKS:

|-----------------|---------------|-------------|--------------------|------------------|
| Link Name       | Origin Device | Origin Port | Destination Device | Destination Port |
|-----------------|---------------|-------------|--------------------|------------------|
|                 | ceos          | Ethernet1   | cjunosevolved      | et-0/0/0         |
|                 | cjunosevolved | et-0/0/1    | vjunos-switch      | ge-0/0/0         |
|                 | vjunos-switch | ge-0/0/1    | xrv9k              | GigabitEthernet0/0/0/0 |
|                 | xrv9k         | GigabitEthernet0/0/0/1 | ceos               | Ethernet2        |
|                 | host1         | eth1        | vjunos-switch      | ge-0/0/2         |
|                 | host1         | eth2        | ceos               | Ethernet3        |
|-----------------|---------------|-------------|--------------------|------------------|
```
This confirms the same interface-naming outcome as the rendered configs, independently.

### (f) Exit code and stderr on a validation error

Test 1 — unsupported module (`eigrp` on `eos`, which has no `eigrp` feature block at all):
```yaml
provider: external
module: [ eigrp ]
nodes:
  ceos:
    device: eos
links:
- ceos
```
```
$ netlab create -p external -o config topology.yml
Errors encountered while processing topology.yml
IncorrectValue in modules: Device type eos (node ceos) does not support module eigrp
Fatal error in netlab: Cannot proceed beyond this point due to errors, exiting
EXIT: 1
```
All three lines went to **stderr** (stdout was empty, verified by redirecting the two streams
separately). Exit code is **1**.

Test 2 — attribute from a module not enabled on the node:
```yaml
provider: external
nodes:
  ceos:
    device: eos
    bgp.nonexistent_attribute: true
links:
- ceos
```
```
Errors encountered while processing topology2.yml
IncorrectAttr in nodes: nodes.ceos uses an attribute from module bgp which is not enabled in nodes.ceos
Fatal error in netlab: Cannot proceed beyond this point due to errors, exiting
EXIT: 1
```
Same contract: category-tagged single-line diagnostic(s), a final `Fatal error in netlab: ...`
banner, exit code 1, everything on stderr, no partial `node_files/` written (the process aborts
during `augment.main.transform`, before `-o config` output-module code ever runs —
`log.exit_on_error()` at `create.py:181` runs right after `transform()` and before the output loop).

### (g) Keys that read files, load code, or run commands — security allowlist input

| Key / CLI flag | What it does | Citation |
|---|---|---|
| `--defaults <file...>` (CLI) | Merges an arbitrary local YAML file into `topology.defaults`, with no path restriction. | `netsim/cli/__init__.py:145-147` (parses flag) → `netsim/cli/__init__.py:230` (`_read.load(args.topology, args.defaults, ...)`) → `netsim/utils/read.py:340-343` (`build_defaults_list` puts CLI `--defaults` first) |
| `-s/--set key=value` (CLI) | Sets **any** dotted topology key to a parsed scalar, via `topo[k] = v` — no allowlist of keys at all (can set `plugin`, `defaults.paths.plugin`, `defaults.netlab.create.plugin`, etc., see below). | `netsim/cli/__init__.py:150` (flag) → `netsim/utils/read.py:405,423-433` (`add_cli_args`) |
| `--plugin <name>` (CLI) or topology `plugin: [...]` | Loads and **executes** a Python file as a plugin (`importlib.util.exec_module`). Search path includes `.` (cwd) by default. | `netsim/cli/__init__.py:149` / topology key consumed in `netsim/augment/plugin.py`; loader: `netsim/augment/plugin.py:113-119` (`load_plugin_from_path`, `modspec.loader.exec_module(pymodule)`); search path default `netsim/defaults/paths.yml:9-13` = `[".", "topology:", "~/.netlab", "/etc/netlab"]`; dispatch `load_plugin`: `netsim/augment/plugin.py:172-181` |
| `defaults.paths.plugin` (topology or `-s`) | Overrides/extends the plugin search path list above — combined with `plugin:`, lets a topology point plugin loading at any readable directory. | `netsim/defaults/paths.yml:9-13`; consumed at `netsim/augment/plugin.py:174` |
| `defaults.netlab.create.plugin` (topology or `-s`) | A **second**, independent code-execution path: any plugin named here gets its `output`/`post_output` hook **executed during `netlab create`** even without a top-level `plugin:` list, as long as the plugin can be found on the plugin search path. | `netsim/cli/_hooks.py:25-51` (`cli_plugin_hooks`, called from `netsim/cli/create.py:196,213` for hooks `'output'`/`'post_output'`) |
| `defaults.netlab.<cmd>.<hook>` (topology or `-s`) | Runs a **shell command** (`run_command`, from `external_commands.py`) as a "CLI hook" — confirmed to exist in the framework, but **not wired into `netlab create`** (`create.py` never calls `run_cli_hooks`, only `cli_plugin_hooks`; shell hooks are used by other commands such as `up`/`down`). | `netsim/cli/_hooks.py:53-63` (`cli_shell_hooks`), `:65-68` (`run_cli_hooks`, unused by `create.py`) |
| `_include:` (any YAML value, topology or any included defaults file) | Recursively includes other YAML files by glob, honoring a leading `~/` as home-relative; no path restriction to "inside the project". | `netsim/utils/read.py:35-80` (`include_yaml`) |
| `defaults.sources.{list,extra,user,system}` (topology or `-s`) | Lets a topology fully replace or extend which default files get merged in (including pointing `user`/`system` defaults at arbitrary paths). | `netsim/utils/read.py:266-309` (`build_defaults_list`) |
| Implicit `./topology-defaults.yml`, `~/.netlab.yml`, `~/topology-defaults.yml` | **Always** auto-merged into every topology's defaults unless `defaults.sources.user`/`.list` is set — i.e. dropping one of these files in the working directory or home directory silently changes every subsequent `netlab create` run there. | `netsim/utils/read.py:20` (`USER_DEFAULTS`) |
| Any `NETLAB_*` environment variable | Auto-converted (`NETLAB_FOO_BAR=x` → `defaults.foo.bar = x`, YAML-parsed) and merged into `topology.defaults` on every run, unconditionally. | `netsim/utils/read.py:311-334` (`include_environment_defaults`), called from `read.py:378` |
| `config:` node attribute / `defaults.paths.custom.dirs` | Selects extra Jinja2 config templates by filename convention; search dirs include `topology:`, `.` (cwd), `~/.netlab`, `/etc/netlab`, `package:extra`. Template rendering is plain Jinja2 (not sandboxed, see (a)), so a template placed on this path can use any Jinja2 built-in (e.g. `{{ ''.__class__.__mro__ }}`-style introspection is not blocked by netlab itself). | `netsim/defaults/paths.yml:16-43` |
| `tools:` node/topology attribute | Same class of risk as `config:` — renders a topology-controlled `render`/`template` value for an external "tool" config directory (`netsim/outputs/tools.py:16-30`, `create_tool_config`); search path again includes cwd. | `netsim/outputs/tools.py`, `netsim/defaults/paths.yml` (`tools/*` dirs referenced via `_files.get_search_path`) |
| `-o 'yaml:<expr>'` / `-o 'json:<expr>'` (CLI output modifier, not a topology key) | The colon-suffix after `yaml`/`json` is passed to Python's `eval()` against the transformed-topology namespace. | `netsim/outputs/yaml.py:52` (`eval(fmt,cleantopo)`) — CLI-supplied, not topology-supplied, but worth allowlisting the `-o` string itself if it is ever passed through from an untrusted caller |
| `topology.message` (string or dict) | **Not** a code/file/exec risk — just an informational string `netlab` prints back to the user for certain actions; included here only because the task asked about a `message` key and it does exist. | `netsim/cli/__init__.py:389-395` |
| `_netlab_hooks`, `validate` (as an exec mechanism), `defaults.paths.validate` | `_netlab_hooks` does **not exist anywhere in the source** (grepped, zero hits) — not a real key. `defaults.paths.validate` (search path `topology:validate`, `validate`, `~/.netlab/validate`, `/etc/netlab/validate`, `package:validate`, `netsim/defaults/paths.yml:2-7`) is real but belongs to the `netlab validate` command family, not `netlab create`; not exercised in this recon. | `netsim/defaults/paths.yml:2-7`; absence of `_netlab_hooks` confirmed by `grep -rn "_netlab_hooks"` returning nothing |
| `includes:` (topology top-level key, **not** `_include`) | Explicitly rejected: `netlab` hard-errors if a topology sets a top-level `includes:` key at all. | `netsim/utils/read.py:352-357`: `if 'includes' in topology: ... log.fatal('The "includes" topology element shall not be used', ...)` |

**Bottom line for the allowlist**: for a compiler-only integration, the safe subset is: pass a
topology file path (validated to be inside an owner-controlled directory) and `-o config -o
yaml=<file> -o json=<file>` (or similar fixed, hardcoded `-o` list) with **no** `--defaults`,
`--plugin`, `-s`, or CLI-controlled `-o <expr>` ever forwarded from anything the student/lab author
supplies; the topology YAML the adapter *generates itself* should never contain `plugin:`,
`defaults.paths.*`, `defaults.sources.*`, `defaults.netlab.*`, `_include:`, `config:`/`tools:`
pointing outside a known template set, and `$HOME`/cwd for the subprocess should be a scratch
directory so the always-on `~/.netlab.yml`/`./topology-defaults.yml` auto-merge and the `NETLAB_*`
env-var auto-merge can't be abused by anything else running as the same user.

---

## Task 4 — reorder and 5th-link experiments

### Experiment A: swap two nodes' definition order + reorder/reverse one link

`proto-external/square-v2-reorder.yml` = `square-v1.yml` with (1) the `xrv9k` and `vjunos-switch`
node blocks swapped in the `nodes:` mapping, and (2) link #3 (`vjunos-switch↔xrv9k`) and link #4
(`xrv9k↔ceos`) swapped in list position, with link #4's two endpoints also written in reversed order
(`ceos:` first instead of `xrv9k:` first). All `ifname:` values were left untouched (same physical
mapping intended).

```
$ netlab create -p external -o config topology.yml     # run2, same command as run1
EXIT: 0
$ diff -ru run1/node_files run2/node_files
```

Full diff (`proto-external/diff-v1-v2.txt`, reproduced verbatim, only the substantive hunks — file
headers keep timestamps which differ trivially and are not semantically meaningful):

```diff
diff -ru run1/node_files/ceos/bgp run2/node_files/ceos/bgp
@@ -30,22 +30,22 @@
   neighbor 10.255.0.3 remote-as 65000
-  neighbor 10.255.0.3 description vjunos-switch
+  neighbor 10.255.0.3 description xrv9k
   neighbor 10.255.0.3 update-source Loopback0
   neighbor 10.255.0.3 send-community standard extended large 
 !
   neighbor 2001:db8:ff:3::1 remote-as 65000
-  neighbor 2001:db8:ff:3::1 description vjunos-switch
+  neighbor 2001:db8:ff:3::1 description xrv9k
...
   neighbor 10.255.0.4 remote-as 65000
-  neighbor 10.255.0.4 description xrv9k
+  neighbor 10.255.0.4 description vjunos-switch
...
   neighbor 2001:db8:ff:4::1 remote-as 65000
-  neighbor 2001:db8:ff:4::1 description xrv9k
+  neighbor 2001:db8:ff:4::1 description vjunos-switch

diff -ru run1/node_files/ceos/initial run2/node_files/ceos/initial
@@ -10,12 +10,12 @@
-ip host vjunos-switch 10.255.0.3 10.0.0.6 10.0.0.9 172.31.0.3
-ip host xrv9k 10.255.0.4 10.0.0.10 10.0.0.14
+ip host vjunos-switch 10.255.0.4 10.0.0.6 10.0.0.13 172.31.0.4
+ip host xrv9k 10.255.0.3 10.0.0.10 10.0.0.14
-ipv6 host vjunos-switch 2001:db8:ff:3::1
-ipv6 host xrv9k 2001:db8:ff:4::1
+ipv6 host vjunos-switch 2001:db8:ff:4::1
+ipv6 host xrv9k 2001:db8:ff:3::1
@@ -39,9 +39,9 @@
 interface Ethernet2
  description ceos -> xrv9k
- ip address 10.0.0.13/30
+ ip address 10.0.0.9/30
- ipv6 address 2001:db8:1:3::1/64
+ ipv6 address 2001:db8:1:2::1/64

diff -ru run1/node_files/vjunos-switch/initial run2/node_files/vjunos-switch/initial
@@ -13,10 +13,10 @@
   lo0.0 {
       family inet {
-        address 10.255.0.3/32;
+        address 10.255.0.4/32;
       }
       family inet6 {
-        address 2001:db8:ff:3::1/64;
+        address 2001:db8:ff:4::1/64;
       }
   }
@@ -33,20 +33,20 @@
     description "vjunos-switch -> xrv9k";
       family inet {
-        address 10.0.0.9/30;
+        address 10.0.0.13/30;
       }
       family inet6 {
-        address 2001:db8:1:2::1/64;
+        address 2001:db8:1:3::1/64;
       }
   }
   ge-0/0/2.0 {
       family inet {
-        address 172.31.0.3/24;
+        address 172.31.0.4/24;
       }
       family inet6 {
-        address 2001:db8:2::3/64;
+        address 2001:db8:2::4/64;
       }
   }

diff -ru run1/node_files/xrv9k/initial run2/node_files/xrv9k/initial
@@ -14,15 +14,15 @@
 interface Loopback0
- ipv4 address 10.255.0.4 255.255.255.255
- ipv6 address 2001:db8:ff:4::1/64
+ ipv4 address 10.255.0.3 255.255.255.255
+ ipv6 address 2001:db8:ff:3::1/64
!
-interface GigabitEthernet0/0/0/0
+interface GigabitEthernet0/0/0/1
- description xrv9k -> vjunos-switch
+ description xrv9k -> ceos
  ipv4 address 10.0.0.10 255.255.255.252
  ipv6 address 2001:db8:1:2::2/64
!
-interface GigabitEthernet0/0/0/1
+interface GigabitEthernet0/0/0/0
- description xrv9k -> ceos
+ description xrv9k -> vjunos-switch
  ipv4 address 10.0.0.14 255.255.255.252
  ipv6 address 2001:db8:1:3::2/64
```
(the `xrv9k/ospf`, `xrv9k/bgp`, `vjunos-switch/bgp`, `vjunos-switch/ospf`, `cjunosevolved/bgp`,
`cjunosevolved/initial`, `host1/initial`, `host1/routing` files show the same class of change —
router-ids and loopback/BGP-neighbor addresses for `vjunos-switch` and `xrv9k` swapped between
`10.255.0.3`↔`10.255.0.4`; full 442-line diff saved at `proto-external/diff-v1-v2.txt`).

**Finding: reordering nodes/links in the topology YAML renumbers addresses.** `vjunos-switch`
went from loopback `10.255.0.3` to `10.255.0.4`, and `xrv9k` from `10.255.0.4` to `10.255.0.3` —
purely because their order in the `nodes:` mapping (a Python dict, iterated in insertion order)
changed. Likewise the p2p `/30` subnet assigned to the `vjunos-switch↔xrv9k` link and the one
assigned to the `xrv9k↔ceos` link swapped (`10.0.0.9`↔`10.0.0.13`), because the *links list order*
changed. `ceos` and `cjunosevolved`, whose relative order was untouched, kept their original
addresses (`10.255.0.1`, `10.255.0.2`) throughout.

Importantly, **the physical correctness was preserved**: every interface still connects the same two
named neighbors, described correctly (`xrv9k -> vjunos-switch` still lands on the interface actually
wired to `vjunos-switch`, whichever `GigabitEthernet0/0/0/x` name that turns out to be) — reordering
does not corrupt the topology, it only **destabilizes which numeric address gets assigned to which
link/loopback**. For an adapter that must produce reproducible, diffable configs across regenerations,
this means either (a) always regenerate the topology YAML nodes/links in one fixed canonical order
(e.g. always alphabetical, or always the order in the source-of-truth clab file) or (b) pin every
address explicitly (`mgmt.ipv4` we already do; loopback/p2p addresses are not pinned in our topology
and are therefore reorder-sensitive).

### Experiment B: append a 5th link, leave everything else untouched

`proto-external/square-v3-addlink.yml` = `square-v1.yml` with one line appended at the very end of
`links:`, a new stub link on `cjunosevolved`:
```yaml
  - cjunosevolved:
      ifname: et-0/0/2
```
```
$ netlab create -p external -o config topology.yml     # run3
EXIT: 0
$ diff -ru run1/node_files/vjunos-switch run3/node_files/vjunos-switch   # 0 differences
$ diff -ru run1/node_files/xrv9k        run3/node_files/xrv9k            # 0 differences
$ diff -ru run1/node_files/ceos         run3/node_files/ceos
--- run1/node_files/ceos/initial
+++ run3/node_files/ceos/initial
@@ -8,7 +8,7 @@
-ip host cjunosevolved 10.255.0.2 10.0.0.2 10.0.0.5
+ip host cjunosevolved 10.255.0.2 10.0.0.2 10.0.0.5 172.31.2.2
$ diff -ru run1/node_files/host1        run3/node_files/host1
--- run1/node_files/host1/initial
+++ run3/node_files/host1/initial
@@ -32,6 +32,8 @@
 10.0.0.5 et-0-0-1.0.cjunosevolved
+172.31.2.2 et-0-0-2.0.cjunosevolved
+2001:db8:2:2::2 et-0-0-2.0.cjunosevolved
```

**Finding: a purely additive change at the end of the list does not renumber anything on untouched
nodes.** `vjunos-switch` and `xrv9k` are byte-for-byte identical between `run1` and `run3`. `ceos` and
`host1` only gained *new* lines in their `ip host`/`/etc/hosts` static-mapping tables recording
`cjunosevolved`'s new stub address — no existing address anywhere changed. This confirms address
allocation is sequential-and-stable under append, but not under reordering/insertion — the risk in
Experiment A is specifically about changing the **relative order** of existing entries, not about
topology size growing.

---

## Task 5 — error contract and `netlab show`

### Unsupported module/device combination

Already shown in full under Task 3(f) (`eigrp` on `eos`): `IncorrectValue in modules: Device type eos
(node ceos) does not support module eigrp`, exit code 1, stderr only.

### `netlab show --help`

```
$ netlab show --help
Fatal error in netlab: Unknown request, use 'netlab show' to display valid options
```
(`--help` is not accepted by the `show` dispatcher itself; running `netlab show` bare is the way to
list subcommands.)

### `netlab show` (bare — lists valid subcommands)

```
$ netlab show
Usage:

    netlab show <content> <parameters>

The 'netlab show' command can display the following system settings:

attributes     Supported lab topology and configuration module attributes
defaults       User/system defaults
devices        Devices supported by netlab
images         Default device images for all known virtualization providers
modules        netlab protocol- and technologies configuration modules
module-support Configuration module support by device
outputs        Output modules used by the "netlab create" command
reports        System report templates
providers      Supported virtualization provider and their status

Common parameters:

--system       Display system settings (ignore user defaults)
--format       Select output format (table, text, yaml)

Use 'netlab show <content> -h' for further usage guidelines
EXIT: 0
```

### `netlab show modules -m bgp`

```
$ netlab show modules -m bgp
EXIT: 0
```
Renders a Rich-formatted table titled "Devices and features supported by bgp module" — one row per
device supporting the module, one column per `features.bgp.*` flag (`activate_af`, `advertise`,
`local_as`, `vrf_local_as`, `local_as_ibgp`, ... continues across further tables for `ipv6_lla`,
`rfc8950`, `community`, `confederation`, `import`, and a separate "BGP session parameters" table for
`allowas_in`, `as_override`, `bfd`, `default_originate`, `description`, `gtsm`, `passive`, ...). `eos`,
`iosxr`, `vjunos-router`/`vjunos-switch`/`vptx`/`vmx`/`vsrx`/`crpd` (the Junos family) all show `x` in
every base column, consistent with the `features.bgp` blocks read verbatim in Task 1. Full captured
output at `proto-external/show-output/modules-bgp.txt` (342 lines).

### `netlab show attributes -m bgp`

(Exact syntax is `-m/--module`, not a bare positional `bgp` after `attributes` — `netlab show
attributes bgp` returns exit 1 with "Unknown request"; confirmed via `netlab show attributes --help`,
which documents `[-m MODULE] [match]` as separate parameters.)

```
$ netlab show attributes -m bgp
EXIT: 0

You can use the following bgp attributes:
==============================================================================

_inherit_community:
  localas_ibgp: ibgp
as_list:
  _keytype: int
  _subtype:
    members: {_required: true, _subtype: str, type: list}
    name: str
    rr: {_subtype: str, type: list}
  type: dict
global:
  activate: {ipv4: {_subtype: bgp_session_type, type: list}, ipv6: {_subtype: bgp_session_type, type: list}}
  advertise_loopback: bool
  advertise_roles: list
  as: asn
  as_list: dict
  community: {_value_to_dict: {ebgp: '{value}', ibgp: '{value}'}, ebgp: {...}, ibgp: {...}}
  confederation: {_keytype: asn, _subtype: {members: {_subtype: asn, type: list}}, type: dict}
  ebgp_role: str
  next_hop_self: bool
  replace_global_as: bool
  rr_cluster_id: {type: ipv4, use: id}
  rr_list: list
  rr_mesh: bool
  sessions: {ipv4: {...}, ipv6: {...}}
  ...
```
(126 lines total, full capture at `proto-external/show-output/attributes-bgp.txt`) — this is the
attribute-type schema (`type: str/int/bool/list/dict/asn/...`, `_required`, `_subtype`) netlab's
validator (`data/validate.py`, not separately audited here) checks every `bgp.*` node/topology
attribute against; it is the same schema whose enforcement produced the two error messages in Task
3(f)/5 above.

---

## Files created in this recon

- `~/research/netlab-integration/proto-external/square-v1.yml` — the netlab topology for the square (Task 2 deliverable).
- `~/research/netlab-integration/proto-external/square-v2-reorder.yml` — reorder-experiment variant (Task 4a).
- `~/research/netlab-integration/proto-external/square-v3-addlink.yml` — append-experiment variant (Task 4b).
- `~/research/netlab-integration/proto-external/restore-square.clab.yml.orig` — read-only copy of the real containerlab file.
- `~/research/netlab-integration/proto-external/run1/` — baseline `netlab create` run (topology.yml, node_files/, transformed.yaml, transformed.json).
- `~/research/netlab-integration/proto-external/run2/` — reorder-variant run.
- `~/research/netlab-integration/proto-external/run3/` — add-5th-link-variant run.
- `~/research/netlab-integration/proto-external/run-default/` — default-output-set run (no `-o`), showing `netlab.snapshot.pickle`, `external.txt`, `hosts.yml`, `ansible.cfg`.
- `~/research/netlab-integration/proto-external/run-error/` — the two validation-error transcripts (Task 3f/5).
- `~/research/netlab-integration/proto-external/run-strace/` — `strace -f -e trace=network` output and logs (Task 3d).
- `~/research/netlab-integration/proto-external/scratch-home/` — scratch `$HOME` used for every run (`.netlab/stats.json`, `.netlab/topology-defaults.pickle`).
- `~/research/netlab-integration/proto-external/show-output/` — captured `netlab show modules -m bgp` and `netlab show attributes -m bgp` output (Task 5).
- `~/research/netlab-integration/proto-external/diff-v1-v2.txt`, `diff-v1-v3-*.txt` — full diffs for Task 4.
- `~/research/netlab-integration/RECON-external-provider.md` — this report.

No file was written under `~/projects/`, `/srv/`, or any Docker/containerlab-managed location; no
`netlab up` was ever invoked.
