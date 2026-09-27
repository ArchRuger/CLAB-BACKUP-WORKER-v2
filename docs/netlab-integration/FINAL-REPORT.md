# Network design: final report of the netlab integration (as of 1.30.47)

This is the report the assignment (`CLAB_Netlab_Integration_Claude_Code_Prompt_v2.md`, kept outside the
repository) asks for at completion. Every claim here points at the record that proves it; the records are
`docs/netlab-integration/` (PICKUP, DECISIONS, LEDGER, TESTS, PROVISIONING, `evidence/`), the guide
`docs/NETWORK-DESIGN.md`, the release history in `docs/CHANGELOG.md` and `clab-backup-ui/VALIDATION.md`.

## 1. What was implemented, and how a student reaches it

Every lab has a **Design** tab (Topology · Devices · Progress · **Design** · Tools · Advanced):

1. **Define the intent**: address families and pools, the protocols and services (OSPF, BGP, IS-IS, VRFs, VLANs,
   static routes, policies, gateways, LAG, VXLAN/EVPN, …), common settings as guided controls (OSPF area, BGP AS and
   route reflector, IS-IS area and level, gateway protocol; tables for VRFs, VLANs, per-link VRF/VLAN and static
   routes), everything else as validated JSON under *Advanced*, with every problem named by path.
2. **Generate the plan**: the pinned netlab engine runs inside the image, in a private job directory, touching no
   device, VM or Docker; the plan shows every device's ids, loopbacks, interfaces with their containerlab ports,
   neighbours, BGP sessions, the links, the compatibility of every device in words, what was renumbered, and the
   generated files per device (view, ZIP).
3. **Apply to devices…**: choose devices, review (the settings left out, the device's own diff, added/removed/stale
   statements, expected changes, removal commands, conflicts with an explicit take-over), acknowledge, apply. Each
   device is backed up first, changed inside its NOS's own transaction with the NOS's own timed recovery armed,
   confirmed only after a fresh connection proved management, read back and saved. Outcomes are per device;
   *Owned settings* under Advanced lists what the manager owns on each device.
4. **Keep it**: the design file (download, import), *Export plan to Git…* (the plan's files as a reviewed Git save
   in their own checkpoint folder), the history of plans.

Nothing else of the product changed for the student: backups, *Save progress*, *Apply to running lab*, terminals,
browser Wireshark, the lab builder and the map keep their behaviour and their tests (`VALIDATION.md` per release).

## 2. Architecture and pinned identities

- **Engine**: `networklab==26.9` (PyPI, tag `release_26.09`, MIT) installed in the manager image; run as
  `netlab create -p external -o config -o yaml=transformed.yaml topology.yml` with fixed argv, a fresh HOME and
  job directory under `<data>/network-design/work/`, a four-variable environment, statistics opt-out, no pickle,
  no plugins, no includes, no `netlab up/down/connect`. Offline generation inside the image is verified.
- **Modules** (`docs/ARCHITECTURE.md` module map): `design_intent` (schema 1, validation, allocation ledger),
  `design_adapter` (containerlab topology + intent → netlab topology with explicit profiles and endpoint mapping),
  `design_engine`, `design_capabilities` (+ generated data), `network_design` (service, jobs, artifacts, routes),
  `design_provision` (what may reach a device), `design_ownership` (the pure ownership algebra), `design_eos`,
  `design_junos`, `design_iosxr` (the merge transactions), `design_apply` (review token, apply job, ledger,
  routes), the Design tab in `network-design.js`, and the design export as a Git job of kind `design`.
- **Profiles per image**: `arista_ceos → eos`, `juniper_vjunosswitch → vjunos-switch`,
  `juniper_cjunosevolved → vptx` (declared stand-in), `cisco_xrv9k → iosxr` (declared stand-in), `linux → linux`
  host. Endpoint mapping from `topology.PORT_RULES` (cEOS ethN → EthernetN, vJunos eth1 → ge-0/0/0, cJunosEvolved
  eth4 → et-0/0/0, XRv9k eth1 → GigabitEthernet0/0/0/0) with per-link overrides.
- **Existing stack untouched**: Ansible and the vendor collections as pinned before; no Docker socket, no host
  metrics, no new helper on the VM; device access stays direct node SSH.

## 3. Compatibility matrix

`docs/netlab-integration/LEDGER.md` is the matrix: per capability and per image (cEOS 4.35.0F, cJunosEvolved
26.2R1.7-EVO as the vPTX stand-in, vJunos-switch 23.2R1.14, XRv9k 24.3.1 as the IOS XR stand-in): upstream
support, adapter support, generation tests, live evidence, UI path, limitation. In short:

- **Applied live through the deployed product and read back** (`evidence/live-apply-families.md`,
  `live-apply-{ceos,junos,iosxr,product}.md`): addressing (dual stack), OSPFv2/v3, BGP (iBGP, eBGP, default
  origination), IS-IS, VRFs, static routes, route policies and prefix lists, redistribution, VLANs — on all four
  images where the image has the module (VLANs: not XRv9k).
- **Generated, not applied on this lab**: LAG (no parallel links), VRRP/anycast (no shared segment with two
  routers), STP, BFD; VXLAN/EVPN applied on cEOS, refused by vJunos-switch's own commit check.
- **Refused per image before the engine runs**: EIGRP (none), RIPv2/DHCP/STP (cEOS only), VLAN/VXLAN/BFD/LAG/
  anycast (not XRv9k), SRv6 (XRv9k only), MPLS families as the capability data says.
- **Not in the schema**: plugins (GRE, WireGuard) and protocol authentication (D9.8, D9.9).

The cJunosEvolved/vPTX and XRv9k/XRd distinctions: the manager names the stand-in profile on every plan and
in the capability answers; the live proofs are on the two images that run in this lab, not on vPTX or XRd.

## 4. Ownership, protection, removal, transaction, recovery, partial failure

`docs/netlab-integration/PROVISIONING.md` is the contract (§1–§8). The short form:

- **Protection**: hostname, logins, AAA, the management interface and VRF, name mappings, MAC addresses, the
  netlab `normalize` file and Junos `delete:` tags never reach a device; the review lists what was left out.
- **Transaction**: EOS `configure session` + `copy terminal: session-config` + `commit timer`; Junos
  `configure exclusive` + `load merge terminal` + `commit confirmed`; IOS XR `configure exclusive` + line paste +
  `commit confirmed minutes` on a session kept open. A review is the same transaction, aborted.
- **Ownership**: `owned' = (owned ∩ after) ∪ (added ∩ after)` per device, with the created ancestors; stale =
  owned − desired ∩ before; conflicts = removed − owned plus exclusive hierarchies; removal at the highest
  owned-and-stale ancestor (one `no router ospf 1`, `delete protocols bgp`, `no neighbor X`), leaves otherwise; a
  container with manual children is kept and said so; a take-over is explicit and re-reviewed and removes what it
  covers.
- **Recovery and partial failure**: the pre-change backup is mandatory; `rolled_back` only after the previous
  configuration was read back, otherwise `uncertain` (settled by the next review's read-back); a manager restart
  rechecks in-flight devices and confirms only what it can still identify as its own; a job is `succeeded`,
  `partial`, `failed` or `needs_attention` from the per-device outcomes, never a healthy label over a failed device.

## 5. Validation evidence, pre-existing failures, blockers, untested claims

- Unit and real-engine suites per release in `VALIDATION.md`; live records under `evidence/`; browser records
  `evidence/browser-design-ui.md` and `evidence/browser-design-apply-ui.md`; the health check on the development
  VM: 61 PASS, 0 FAIL, 1 WARN (folder coverage) after the helper refresh.
- **Pre-existing**: the shell's 428 px width at phone size on every tab (recorded in 1.30.44), the engineer-access
  group state of the development VM (refreshed on 2026-09-27).
- **Unresolved**: vJunos-switch refuses netlab's EVPN/VXLAN VLAN rendering ("bridge domains/vlans"); IOS XR refuses
  a BGP AS change in one commit (two applies).
- **Untested claims**: none are advertised; every ledger row says what was generated only.

## 6. Versions, commits, checkpoints, installation and upgrade

| Release | Commit | Content |
|---|---|---|
| 1.30.43 | `b96cb89` | engine, intent, adapter, capabilities, generation jobs, routes (milestone B) |
| 1.30.44 | `64c954e` | the Design tab; the second and third risk-review passes (milestone C) |
| 1.30.45 | `7bb45af` | Apply to devices on all four platforms; the fourth review pass (milestone D) |
| 1.30.46 | `0439abb` | the feature families; guided tables (milestone E) |
| 1.30.47 | the commit that carries this report (`git log -1 -- docs/netlab-integration/FINAL-REPORT.md`) | the reviewed Git export of a plan, the engine health check, this report (milestone F) |

Branch `claude/netlab-integration`, pull request #55 against `main`; CI green on every push. Installation: the image
carries the engine; `deploy/install.sh` and `start-manager.sh` unchanged; after an upgrade the VM helpers are
refreshed with `setup-discovery.sh --update-helper`, `setup-operations.sh --lab-root …`, `setup-git.sh --refresh`
(`check-install.sh` reports the engine as its own item). No workstation or VM-side netlab installation is needed.

## 7. Existing features and removals

Every existing test kept its claim in every release (the full Python and browser suites per `VALIDATION.md`);
the four-node restore, the lab builder, the map, the Git save and browser Wireshark were exercised on the deployed
manager during this stream. **Intentionally removed: None.** The retired telemetry/Grafana stack stays retired.

## 8. Pickup

`docs/netlab-integration/PICKUP.md` states the exact next action (the two families outside the schema; the
optional VM-side sidecar; a fresh-VM install of the final release), the live harness and the acceptance lab facts.
