# Per-image capability and evidence matrix (campaign 2)

The six exact images of the 2026-10-27 instruction, their canonical kinds, and what the manager does with each,
with the evidence type per cell. Vocabulary: **PASS**, **FAIL**, **BLOCKED** (an external condition), **NOT TESTED**,
**NOT APPLICABLE** (only with a reason). Evidence kinds are kept apart: *static* (the registry), *unit*, *fixture*
(the real app on scripted VM answers), *live* (the development VM, exact image). A kind listed in a dropdown is not
support; a cell is PASS only with its evidence. The official defaults and their sources are in
[CAMPAIGN-2.md](CAMPAIGN-2.md); the acceptance list per chunk is in the ledger there.

## Identity

| Image (exact) | Kind | Aliases known to the manager | Login default (registry) | Registry status at 1.31.6 | Change in campaign 2 |
|---|---|---|---|---|---|
| `n24l/juniper_vjunos-router:26.2R1.7` | `juniper_vjunosrouter` | `vr-vjunosrouter`, `vjunosrouter` | admin / admin@123 | backups, downloads, saves, catalog, console; restore and design gated | restore and design after the live proof (B04, B05); supported kind as of 1.31.8 (B08, the host fact corrected) |
| `n24l/juniper_vsrx:23.2R2.21` | `juniper_vsrx` | `vr-vsrx`, `vsrx` | admin / admin@123 | absent | B02: registry, aliases, download name `vSRX`, save format, interface map `ge-0/0/N` = `eth(N+1)`, builder template, VM kind for diagnostics; restore, design and console gated until proven |
| `n24l/vjunos-switch:23.2R1.14` | `juniper_vjunosswitch` | `vr-vjunosswitch`, `vjunosswitch` | admin / admin@123 | full (restore proven live in 1.30.27–29; design; console) | regression only |
| `n24l/ceos:4.35.0F` | `arista_ceos` | `ceos`, `eos`, `arista.eos.eos` | admin / admin | full (restore, design) | regression only |
| `n24l/cjunosevolved:26.2R1.7-EVO` | `juniper_cjunosevolved` | `cjunosevolved`, `junos`, `junipernetworks.junos.junos` (generic fallback) | admin / admin@123 | full (restore, design) | regression only |
| `n24l/cisco_xrv9k:24.3.1` | `cisco_xrv9k` | `vr-xrv9k`, `iosxr`, `cisco.iosxr.iosxr` | clab / clab@123 | full (restore, design, console) | regression only |

## Exact-image qualification (live)

Filled from the evidence files under `evidence/` as each boot and pass happens. Columns: requested tag, resolved
digest, running container image id, NOS-reported version, containerlab version, manager build, host facts, result.

| Image | Requested tag | Digest (RepoDigest) | Running image id | NOS version | containerlab | Manager | Host | Result |
|---|---|---|---|---|---|---|---|---|
| vJunos-router | `n24l/juniper_vjunos-router:26.2R1.7` | `sha256:0d039c60…41bb` | `c85d25f77631` (the CPU-model rebuild; the published image id `35af1be9046e` never boots here) | Junos 26.2R1.7, Model vmx | 0.79.0 | 1.31.7 | VMware guest with nested KVM (24 vCPU, 72 GB) | **Published image: not bootable on this VMware guest**: the inner qemu 2.7 aborts (`kvm_put_msrs` assertion) under the launcher's `-cpu host` and relaunches every 5 s (`vjunous-router-test/rtr1`, 2026-10-27 10:53–10:59 UTC); the owner's Proxmox host (KVM, `host` CPU type) boots it. **Rebuild PASS**: `local/juniper_vjunos-router:26.2R1.7-nested` (one `sed` on `/launch.py`: the vJunos-switch IvyBridge model) boots in 12 min 25 s, FPC online 2.5 min later; B08 (`evidence/b08-vjunos-router-traffic-2026-10-27.md`): OSPF, eBGP, LLDP, IPv4/IPv6 transit, fragmentation, reassembly, DF, firewall counter, floods without PFE drops, zero interface errors. Image facts: ~98 Mbit/s cap (no VMX-BANDWIDTH license), `ge-` MTU 1514. |
| vSRX | `n24l/juniper_vsrx:23.2R2.21` | `sha256:fc9b9fa2…3051a` | `384db297beb1` (= the pulled image) | Junos 23.2R2.21, Model vSRX | 0.79.0 | 1.31.6 (lab outside the manager) | nested KVM VM | **PASS** boot: the launcher uses a fixed `-cpu SandyBridge,…,vmx=on` (2 vCPU, 4096 MB), `Startup complete` in 2 min 25 s, no relaunch; SSH `admin` with the published default; `ge-0/0/0` and FPC 0 online about 3.6 min after deploy (before that only `fxp0`); serial console answers on port 5000 (`FreeBSD/amd64 (vsrx) (ttyu0)` login after Enter); **Docker health is permanently `unhealthy`** (`/healthcheck.py: exec format error`, no `#!`), so container health must never gate this kind. `evidence/b03-vsrx-boot-2026-10-27.md` |
| vJunos-switch | `n24l/vjunos-switch:23.2R1.14` | `sha256:12832fcb…71d62` | `1b9ec888863e` | Junos 23.2R1.14 | 0.79.0 | 1.31.6 | nested KVM VM | PASS boot and SSH (B03a, `parity` redeployed with `--reconfigure` after the VM reboot; 17.6 min to SSH beside five other boots) |
| cEOS | `n24l/ceos:4.35.0F` | `sha256:47b25129…1007` | `dcddd2f9c2b2` | EOS 4.35.0F | 0.79.0 | 1.31.6 | container | PASS boot and SSH (B03a, under 5.4 min) |
| cJunosEvolved | `n24l/cjunosevolved:26.2R1.7-EVO` | `sha256:d1dfc8bc…9455` | `3b253da2d8cf` | Junos 26.2R1.7-EVO (hostname `HOSTNAME`: no CPTX_AUTO_CONFIG in `parity.clab.yaml`) | 0.79.0 | 1.31.6 | nested KVM VM | PASS boot and SSH (B03a, 17.2 min) |
| XRv9k | `n24l/cisco_xrv9k:24.3.1` | `sha256:1409cf12…9d2b` | `a22e6bba366d` | IOS XR 24.3.1 | 0.79.0 | 1.31.6 | nested KVM VM | PASS boot and SSH (B03a, 11.7 min) |

## Capabilities per image

Each cell: status, evidence kind, pointer. "registry" means the static registry has the entry and the unit tests
pin it; it is not a live result.

| Capability | vJunos-router | vSRX | vJunos-switch | cEOS | cJunosEvolved | XRv9k |
|---|---|---|---|---|---|---|
| Catalog entry, exact default image | PASS static (`BUILDER_TEMPLATES`) | PASS static (B02) | PASS static | PASS static | PASS static | PASS static |
| Kind identity on import and sync (static and script inventories, topology hints, aliases) | PASS unit (`test_junos_kinds.py`) | PASS unit (B02) + live (B04 phase 2: a lab imported while the kind was unknown mapped `juniper_vsrx` on Sync, the profile kept, the node left disabled until enabled) | PASS unit | PASS unit | PASS unit | PASS unit |
| Interface naming | PASS static+live (`ge-0/0/N`=`eth(N+1)`, C05 live) | PASS static (B02) + live (B03a: `eth1` is `ge-0/0/0`) | PASS live | PASS live | PASS live (`et-0/0/N`=`eth(N+4)`) | PASS live |
| Boot and readiness (real `show version`) | PASS live on the nested derivative only (C01) | PASS live (B03a, outside the manager; the manager's readiness on this kind is B06) | PASS live (C01) | PASS live (C01) | PASS live (C01) | PASS live (C01) |
| Default login | PASS live (C01, derivative) | PASS live (B03a direct SSH; through the manager the lab's generated inventory login comes first, `credential_source: inventory`; the profile wins over it, B04 phase 2) | PASS live | PASS live | PASS live | PASS live |
| Credential overrides (profile > inventory > kind default) | unit (`test_junos_kinds.py`, `test_nodes.py`) | unit in B02 | unit | unit | unit | unit |
| Browser SSH terminal | PASS live (C02/C03) | PASS live (A05/B06: `show version` in the browser terminal) | PASS live | PASS live | PASS live | PASS live |
| Serial console | PASS live (C04, derivative) | NOT OFFERED by design (the drawer says the kind exposes none, B04 phase 2); port 5000 answers live (B03a) but the C04 gate needs Docker health, which this image never reports | registered, NOT TESTED live (ACCEPTANCE R021) | NOT APPLICABLE (no qemu console) | NOT APPLICABLE | registered, NOT TESTED live |
| Logs, interfaces, diagnostics drawer | PASS live (C03) | PASS live (A05/B06: container facts, logs, interfaces by container name) | PASS live | PASS live | PASS live | PASS live |
| Backup (display set / running-config), download name | PASS live (C01: `vJunos-router_vrt_…cfg`) | PASS live (B04 phase 2: `vSRX_vsrx_2026-10-27_02-37UTC.cfg`) | PASS live | PASS live | PASS live | PASS live |
| Restore-grade artifact | PASS live (backup `0d12eefb` with the `.jcfg`, B04 phase 2) | PASS live (backup `790b5d73` with the `.jcfg`; download `vSRX_vsrx_…cfg`, ZIP `camp-vsrx_…zip`) | PASS | PASS | PASS | PASS |
| Save to Git, manifest identity | PASS live (C01 save) | NOT TESTED (the campaign lab is not bound to a repository; the format table has the kind: unit) | PASS | PASS | PASS | PASS |
| Load (whole-configuration replacement, timed recovery, readback, persistence) | PASS live on the CPU-model rebuild: direct driver (phase 1) and the manager path (phase 2: B→A `verified` `d7a93a64`, A onto A, back-to-back, reboot 923 s with 0 lines lost, selected-device `e6f5ec77`, mixed job `61282b8f` partial with a foreign EOS timer refused truthfully; arming 23–28 s) | PASS live, exact image: direct driver (phase 1) and the manager path (phase 2: `verified` `c49dd700`, A onto A, back-to-back, reboot 162 s, the expired timer read back `rolled_back` only after the previous configuration was read `bfa4c013`; arming 6–7 s) | PASS live (1.30.27–29) | PASS live | PASS live | PASS live |
| Forwarding plane (B08: OSPF, eBGP, LLDP, IPv4 and IPv6 transit, fragmentation, reassembly, DF, firewall counter, floods) | PASS live on the CPU-model rebuild (`camp-vrt-traffic`, 2026-10-27) | not run | not run | PASS live as the B08 peer (cEOS 4.35.0F: OSPF, eBGP, LLDP, transit) | not run | not run |
| Device start/stop/restart | PASS live (C05) | NOT TESTED | PASS live (known second-start limit) | PASS live | PASS live | PASS live |
| Lab deploy/apply/redeploy/destroy | PASS live (C05) | deploy PASS live outside the manager (B03a); manager path B06 | PASS | PASS | PASS | PASS |
| Capture | PASS live (C07, viewer) | PASS live from the host end with real packets (A05); a session on the vSRX end starts (B04 phase 2; the link is drawn as `eth1` because the lab was registered before the kind was known) | PASS | PASS | PASS | PASS |
| Topology / map integration, link state | PASS live (C06) | PASS live (T07 on `camp-topo`: added from the palette with its exact image, linked, applied; recreated by containerlab on a link change) | PASS | PASS | PASS | PASS |
| Network Design (netlab mapping, generation, apply, readback) | unsupported by design (`dc.resolve` → unsupported) until B05 | unsupported until B05 | PASS | PASS | PASS (stand-in profile) | PASS |

## Open blockers

- vJunos-router's published image does not boot on this VMware guest (the inner qemu aborts under `-cpu host`); the
  owner's Proxmox host (KVM, `host` CPU type) boots it, so the kind is supported as of 1.31.8 by the owner's decision.
  Every live result for this kind on this VM is on the CPU-model rebuild and says so; B08 found no functional
  difference in its forwarding plane. Two image facts for lab authors: pin `mtu: 1500` on links between `linux`
  nodes and the kind (its `ge-` interfaces run at 1514; containerlab's default veth MTU is 9500), and throughput is
  capped near 100 Mbit/s without a `VMX-BANDWIDTH` license.
