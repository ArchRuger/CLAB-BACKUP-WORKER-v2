# Network design

What the *Network design* capability is, where its data lives, what it touches (and what it never
touches), its API, and its security boundary. The student-facing page is described here as it
arrives; the work stream's records (decisions with evidence, the feature-by-platform ledger, tests)
are in [docs/netlab-integration/](netlab-integration/PICKUP.md).

## What it is

Network design adds *network intent* to a lab: the addressing pools, address families, routing
protocols, services and per-device or per-link settings a student wants on the lab's devices. Students
reach it through the lab's **Design** tab. The
manager calculates the addressing and adjacency plan and generates per-device configuration from
that intent with [netlab](https://netlab.tools) (the PyPI distribution `networklab`, pinned in
`clab-backup-ui/requirements.txt` and installed in the manager image; nothing has to be installed on
a workstation or on the lab VM). The flow is

*build or open a lab → define network intent → calculate addressing and routing → inspect the
generated configuration and each device's compatibility → explicitly apply to selected devices →
verify → keep and export the design and its evidence.*

The manager stays what it is. Deploying, destroying, terminals, capture, backups, *Save progress*
and *Apply to running lab* keep their behaviour; netlab is used as a compiler only, never as a lab
lifecycle tool (`netlab up`, `netlab down`, `netlab connect` are never run). The feature is opt-in:
a lab without a design behaves exactly as before, nothing is migrated, renumbered or configured on
its own, and a saved design is never replayed by a deploy or redeploy.

## Three layers, one owner each

| Layer | Owner | Where |
|---|---|---|
| Topology and runtime identity: devices, kinds, images, wiring, management addresses, deployment state | The lab (containerlab, discovery) | `definition_yaml` and `nodes` of the lab record, as before |
| Network intent: pools, families, modules, per-device and per-link settings, the allocation ledger, endpoint overrides | The student, through the design API | `network_design` on the lab record (encrypted state); exported as `<lab>.network-intent.yml` |
| Generations: the immutable result of one plan (inputs' digests, engine and adapter versions, profiles, compatibility, warnings, ordered per-device files with sizes and digests, the ledger the plan made) | The manager | `network_generations` on the lab record (the newest 20) and the files under `<data dir>/network-design/<lab id>/<generation id>/` |

The containerlab topology is never rewritten and no second physical topology is maintained: the
netlab topology is derived at generation time from the topology text plus the intent, in a private
working directory that is removed afterwards.

### Identity and endpoint mapping

Every generation decides identities explicitly and records them:

`manager node ↔ containerlab node, kind and image ↔ netlab device profile ↔ containerlab endpoint ↔ NOS interface`

- The profile comes from the capability model's table (`design_capabilities.PROFILES`): cEOS →
  `eos` (exact), vJunos-switch → `vjunos-switch` (exact), cJunosEvolved → `vptx` (a stand-in:
  netlab targets vJunos Evolved; the Junos Evolved lineage, `et-0/0/N` ports and `re0:mgmt-0` are
  shared, the image and containerlab kind are not), XRv9k → `iosxr` (a stand-in: netlab targets XRd;
  IOS XR, `GigabitEthernet0/0/0/N` and `MgmtEth0/RP0/CPU0/0` are shared, the image is not), `linux`
  → `linux` (a support host: generated only, never applied). Any other kind is left out of the
  design with that reason.
- Each link end is mapped from the kind's documented port rule (the same table the map uses:
  cEOS `ethN = EthernetN`, vJunos-switch `eth1 = ge-0/0/0`, cJunosEvolved `eth4 = et-0/0/0`, XRv9k
  `eth1 = Gi0/0/0/0`, spelled the way the NOS and netlab spell it), or from an explicit override in
  the intent (`interfaces`). An end that cannot be mapped is never guessed: its link is left out and
  both devices are marked *blocked* in the generation, so their files cannot be applied.
- Node ids, loopbacks, link prefixes and router ids of a successful plan are written into the
  intent's allocation ledger and passed to the engine as explicit assignments on the next plan, so
  adding, removing or reordering an unrelated node or link does not renumber existing devices. A
  renumbering that cannot be avoided is listed in the generation for review. *Renumber* (the
  `renumber` action) forgets the ledger explicitly; nothing forgets it by itself.
- netlab's pool allocator does not skip pinned prefixes. When a new link receives a prefix a pinned
  link owns, the manager assigns the first free prefix of the same size from the same pool and runs
  the engine a second time (`passes: 2` and `collision_fixes` in the generation); a plan that still
  overlaps fails instead of being shown.
- Every access link of a VLAN, and a trunk whose native VLAN it is, carries that VLAN's subnet: netlab copies
  the VLAN prefix onto the link and overrides any prefix pinned there. Such links are one segment, never a
  collision (two hosts on one VLAN plan normally). A pin cannot move a VLAN link, so when a VLAN subnet lands
  on a plain link the plain link is the one moved; when it lands on a fixed prefix (pinned, or explicit in
  the design) the plan fails at once and names the VLAN and the link.
- The adapter emits devices (routers first, then hosts, by name) and links (by key) in a sorted
  order, so the same semantic input yields byte-identical generated files whatever the order of the
  containerlab file.

## Capability model

`design_capabilities.py` answers, for a requested capability and a containerlab kind, three separate
questions that are never flattened into one mark:

1. **Engine support**: can the pinned netlab render it on the mapped profile? Read from the engine
   itself (`netlab show module-support`, `show attributes`, `show defaults devices.<d>.features`) by
   `docs/netlab-integration/tools/build_capability_data.py` into the committed
   `app/design_capability_data.json`; a contract test regenerates the file and fails on any
   difference, so an engine upgrade is a deliberate change.
2. **Image limits**: what the exact image refuses although the profile would render it
   (`IMAGE_LIMITS`, narrow and with a reason each).
3. **Validation level**: what this integration has proven, and how: `verified_on_image`,
   `generated_not_live_tested`, `unsupported`, `blocked_missing_prerequisite` (`VALIDATION`, each
   entry with its evidence file). A feature the engine supports with no evidence yet is
   `generated_not_live_tested`.

The requested catalogue (`FEATURES`) covers IPv4/IPv6 addressing, OSPFv2/v3, EIGRP, IS-IS, RIPv2/RIPng,
BGP, DHCP/DHCPv6, VLANs, VRFs, LLDP, BFD, static routes, LACP/LAG/MLAG, STP, VRRP, anycast gateways,
VXLAN, GRE, WireGuard, route policies, prefix lists, AS-path filters, redistribution, default
origination, MPLS/LDP, BGP-LU, L3VPN, 6PE, EVPN, SR-MPLS and SRv6. A generation resolves every feature
the intent asks for against every included device before the engine runs; an unsupported combination
fails the generation with the device and the reason named, and nothing is dropped or downgraded
silently. The ledger of what is verified where is [docs/netlab-integration/LEDGER.md](netlab-integration/LEDGER.md).

A product policy sits over the engine's answer: the capabilities of a module retired from authoring (next section)
read `retired` in the matrix the page shows (`with_policy`, `public_matrix`; the engine's answer stays in
`engine_level`), never "not supported"; `resolve()` itself stays the engine truth.

## Retired modules and the EVPN gate

EIGRP (`eigrp`), RIP (`ripv2`, which covers RIPv2 and RIPng) and VXLAN (netlab's `vxlan` module; a containerlab
link of type `vxlan` in a topology is a different thing and is unaffected) are retired from authoring, and EVPN
(`evpn`) is unavailable while under review (D10.1–D10.3 in the decisions record, with the evidence:
none of the four kinds runs EIGRP; RIP is cEOS-only and never tested here; VXLAN never worked end to end on the
acceptance lab; EVPN's only tested transport is VXLAN, and EVPN over MPLS has no generated or tested path and is
not offered by the Junos profiles). `design_intent.RETIRED` is the single source of truth (module → reason):

- They stay in the schema (`MODULES`), so a stored design that uses one still parses, validates, renders, exports,
  downloads and appears in its history and Git exports; `validate()` is unchanged, so its view shows no invented
  problems, and the context lists where it uses them (`retired_in_design`).
- The page offers only `AUTHORING_MODULES`. *Save* refuses (400, structured) a retired module that is new compared
  with the saved design (by path); keeping or removing an old use is always allowed. *Import* stores retired uses
  (a design's own export comes back after *Remove design* or on a fresh lab) and lists them (`imported_retired`). *Check*
  (validate) lists retired uses apart from the problems, marking the new ones.
- *Generate plan* refuses (409, nothing queued) a design that uses any of them; earlier plans, the design file
  and its export are kept.
- *Apply to devices…* (review and apply) refuses (409) a plan whose modules, per-device compatibility or generated files carry one,
  including plans generated before the retirement. Ownership is untouched: a new plan without the module removes
  the owned statements through the normal review and apply. Nothing changes a device by itself.

The exact API shapes are in `docs/uiux-email-2026-10-03/DESIGN-CONTRACT.md`.

## The intent document

`design_intent.py` defines schema 1: `families`, `addressing` (the pools `loopback`, `p2p`, `lan`,
`vrf_loopback`, `router_id` or a custom name; never `mgmt`), `modules` (from the supported list),
`targets`, per-module settings at the global level, `nodes` (role, loopback, the device's own module list, which replaces the design's for that device: netlab's rule, so a device that cannot carry a module is left out of it,
per-module settings, `vlans`, `vrfs`), `links` (prefix, pool, role, type, name, MTU, bandwidth,
unnumbered, per-module settings and per-endpoint addresses and settings), `vlans`, `vrfs`,
`interfaces` (endpoint overrides) and `allocations` (the ledger, written by the manager). Before anything else looks at a document, a recursive guard walks it: every key at every depth
must be a plain identifier-like name that does not start with `_` and is not a refused name, every
name the engine types as an identifier (a VRF, VLAN, address pool, named prefix or routing policy)
follows netlab's own rule of up to 16 characters (letters, digits and underscores, starting with a
letter or an underscore) so that a name the manager accepts never fails the plan later, every
string must be safe text (no control characters, quotes, braces, semicolons, backslashes or
backticks, because names and descriptions end up inside generated NOS text), and depth and size are
bounded. Then two layers of validation run on every save, validate and generate:

- the manager's own rules: shape and allowlisted keys at every level, prefixes and families, pool
  overlap (including with the lab's management network), duplicate addresses and ids, references to
  devices, links, pools, VLANs and VRFs that exist, bounded sizes;
- the engine's attribute schema for every module setting at the global, node, link and interface
  level, and for every VLAN and VRF object (whose `links`, `members`, `interfaces` and `nodes` keys are
  refused: wiring is designed on the lab topology, never inside an object), checked by a generic type
  checker over the schema shipped in the capability data (so the advanced fields round-trip without a
  hand-written copy), failing closed on anything the checker does not understand. Keys that run code, load files or belong to the manager (`config`, `plugin`,
  `defaults`, `validate`, `tools`, `_include`, `device`, `id`, `ifname`, `mgmt`, `password`, ...) are
  refused by name whatever the schema says.

Every problem is reported at once as a list of `{path, message}`. A save carries the revision it was
loaded from; a stale revision is refused (409) so an old tab cannot overwrite newer edits. The
revision covers the student's content, not the ledger.

## Feature families

Every family the assignment names is in the schema and the capability model; the ledger
`docs/netlab-integration/LEDGER.md` says per family and per image what is upstream support, what generates, what
was applied live, and what the limit is. As of this release, on the four acceptance images:

- **Proven live through the product** (generated, applied with *Apply to devices…*, read back on the device and
  in its control plane; `docs/netlab-integration/evidence/live-apply-families.md`): IPv4/IPv6 addressing, OSPFv2/v3,
  BGP (iBGP, eBGP, default origination), IS-IS (adjacencies on every link), VRFs (a VRF on the host links with its
  loopback and VRF-scoped BGP), static routes (a discard route per router), route policies and prefix lists,
  redistribution (IS-IS into BGP through a policy, connected into IS-IS), VLANs (an access port with its SVI on
  cEOS and vJunos-switch), and the removal of each of those again.
- **Generated with the real engine, not applied live on this lab** (the lab has no parallel links, no shared
  segment with two routers and no second VTEP pair): link aggregation (`lag.members`), VRRP and anycast gateways,
  STP, BFD. They are offered with the capability level *generated, not yet tested live*.
- **Retired from authoring** (see *Retired modules and the EVPN gate*): EIGRP, RIP, VXLAN; **unavailable (under review)**: EVPN.
- **Refused by the capability model per image, before the engine runs**: DHCP (cEOS only), VLANs, BFD, LAG, anycast
  (not on XRv9k), STP (cEOS only), SRv6 (XRv9k only); a plan that asks one of those of a device that cannot do it
  names the device and generates nothing.
- **Not yet in the schema**: the GRE and WireGuard plugins (`tunnel.*`), and protocol authentication (the
  secret-reference model): `password` and key attributes stay refused by name.

Two rules of the intent that the families rely on: a device's own `modules` list *replaces* the design's list
for that device (netlab's rule), which is how a device that cannot carry a module is left out of it while the
others keep it; and `links.<key>.lag.members` names the other member links of an aggregation carried by that
link (the member ports are then netlab's, by index, and never links of their own). A member link is never a
bundle itself and belongs to one aggregation only: validation refuses a cycle, a chain or a link claimed by two
bundles, and a design stored before that check fails to plan rather than leave those ports out.

## Generation

`design_engine.py` is the only module that runs netlab: `netlab create -p external -o config -o
yaml=transformed.yaml topology.yml`, fixed argv, in `<data dir>/network-design/work/<job>/` (mode
0700, removed afterwards) with `HOME` inside it, an environment of `PATH`, `HOME`, `LANG` and
`PYTHONDONTWRITEBYTECODE` only (netlab turns every `NETLAB_*` variable into a topology default),
stdin closed, its own process group, a 120 s wall-clock timeout with SIGTERM then SIGKILL, bounded
output, and netlab's own usage-statistics opt-out seeded into the private HOME. The runner reads
back the transformed topology (data only) and the per-device files in netlab's own order
(`normalize` for cEOS, `initial`, then the modules). No pickle is ever written, read or accepted.

`network_design.py` runs one generation at a time per manager on its own single worker: build the
netlab topology, resolve compatibility, run the engine, fix collisions with a second pass, check
overlaps, write the artifacts, the plan (`plan.json`: devices, interfaces with their containerlab
port, addresses, neighbours, protocol settings, BGP sessions, links) and the provenance
(`intent.json`, `topology.yml`, `mapping.json`, `transformed.json`), then record the generation.
A generation can be cancelled; a manager restart marks a running one `interrupted`. A plan is reported
generated only once its record is saved: if that save fails (a full disk), the plan is reported failed, its files
are removed and the allocation ledger stays as it was. The plans of a
removed lab are removed with it, *Start fresh* takes them along with the backups, and every stored
file is private to the manager user; engine lines kept in a record never carry a directory path. Generation needs
no deployment: a lab that is only built can be planned. It configures nothing: no device
connection, no host helper, no Docker, no Git change (tested, including negatively).

The generated files are netlab's merge fragments for a fresh device. They are shown and
downloadable as generated. Applying them is a separate provisioning contract (D4.3 and D4.4 in the
decisions record) that filters what must never be applied as generated (the management interface
stanza, `hostname`, AAA lines, MAC addresses, cEOS `normalize`, Junos `delete:` tags) and manages
removal through an ownership ledger; until that contract exists for a platform, its files are
preview and download only.

## The Design tab

Every lab has a **Design** tab (beside Topology, Devices and Progress). Top to bottom:

- **State and actions.** One line says where the design stands: *No design yet*, *Design saved, no plan yet*,
  *Unsaved changes* (in red when the browser could not keep the draft in its storage: save now), *Advanced JSON
  is not valid*, *Generating the plan…*, *Plan progress unknown* (the progress check failed and five retries failed too; reload
  or open the tab again), *The design has problems*, *Plan ready to review*, *Plan is older than the design*,
  *The last plan failed*, *The last plan was interrupted*, *No design saved (earlier plans kept)* after
  *Remove design*, *Design engine unavailable* (with the engine's diagnostic). These are the design's own words,
  never the devices' readiness or the saved-progress state. *Generate plan* (unsaved changes are saved first,
  and the page says so; text under Advanced that is not JSON blocks it), *Save design*, *Discard changes*
  (back to the saved design; shown while there are unsaved changes) and *More* (download the saved design
  file, import one, *Renumber* to forget the pinned allocations, *Remove design*; an item that cannot run now
  says why underneath: no saved design yet, a plan being generated, or unsaved changes for the download and
  the import). The *Renumber* and *Remove design* dialogs belong to the lab they were opened from: moving to
  another lab (the browser's Back, a link) closes them, and a confirmation that still arrives for another lab
  is refused with a message and changes nothing.
- **Design settings.** Address families; the loopback, point-to-point and shared-link pools with their allocation
  sizes; the protocols and services (OSPF, BGP, IS-IS, BFD, DHCP, VLANs, VRFs, link aggregation, spanning tree,
  first-hop gateway, MPLS, segment routing, SRv6, routing policies and static routes; EIGRP, RIP and VXLAN are
  retired and EVPN is unavailable, see *Retired modules and the EVPN gate*)
  with the common settings that appear when one is ticked (OSPF area, BGP AS number and the route reflectors as
  a checklist of the routers, IS-IS area and type, gateway protocol); a number typed as 0 or left blank is
  refused by name, never replaced by a default; a devices table with each device's kind, profile and role (router, host, excluded) and
  the reason when a device cannot take part. Under **Advanced**, the whole design as JSON for everything the
  controls do not cover (per-link settings, VLAN and VRF objects, interface overrides, module options), a *Check*
  button that lists every problem with its path, and the allocation ledger read-only. Problems are shown above
  the Advanced section, in view.
- **Plan.** The newest plan (or the one chosen under History, with *Back to newest plan*): its status, engine version and passes; errors when it failed; warnings; what it
  renumbered; the compatibility of every device in words; then per device the id, loopback, router id, the
  interfaces with their containerlab port, addresses, neighbours and protocol notes, the BGP sessions; and the
  links. A plan being generated can be cancelled.
- **Files.** The generated configuration fragments per device, in netlab's order, each viewable, and one ZIP
  download. They are not backups; what reaches a device goes through *Apply to devices…* below.
- **History.** Every plan of the lab, newest first; *View* on an earlier plan shows it, its files and its download
  in the cards above (marked as an earlier plan) until *Back to newest plan*. After *Remove design* the plans
  stay listed here for reference and are marked as belonging to a removed design.
- **Apply to devices…** on the plan card, and the last apply's outcome under it; the owned settings per device
  under Advanced. See the next section.

Unsaved edits are kept in the browser per lab and restored on reload while the saved design has not moved on; a
page that is behind the saved design is refused when it saves. The tab reads the design through
`GET /api/labs/{id}/design` and polls it while a plan is being generated.

## Applying a plan to devices

*Apply to devices…* puts a generated plan onto the running devices the student selects, through the same
direct node SSH the backups and *Apply to running lab* use, inside each NOS's own transaction with its own
timed recovery, and never as a whole-configuration replacement. The contract with every rule and its reason
is `docs/netlab-integration/PROVISIONING.md`; the live proofs on the four-node acceptance lab are
`docs/netlab-integration/evidence/live-apply-{ceos,junos,iosxr}.md`. In the page:

1. **Choose devices.** Every device the plan includes is offered; a support host, a blocked device or a kind
   without a driver is listed with the reason. Applying is available for cEOS, vJunos-switch, cJunosEvolved
   and XRv9k, the kinds proven live.
2. **Review.** The review runs as a job: the page starts it and follows each device's real stage (connecting,
   checking for unconfirmed changes, preparing, reading, trying the change, done, failed with a reason, or
   unreachable); closing the dialog does not cancel it, and a second review of the same lab attaches to the running
   one. The manager connects to each chosen device, runs the whole transaction and aborts it, then
   shows per device: the settings of the fragment it leaves out (hostname, logins, the management interface,
   name mappings, netlab's `delete:` tags: identity and reachability stay the containerlab deployment's), the
   device's own diff, the counts of added, removed and stale statements, the *expected changes* (an IOS XR
   port coming out of `shutdown`, EOS `ip routing` switched on), the removal commands it will send, and the
   *conflicts*: manual settings the plan would replace or remove. A device with conflicts cannot be applied to
   until the student ticks *Take over these settings on this device*, which re-runs the review; the overwritten
   settings then become the design's. A device that already matches is marked so and left alone. The review
   is bound to a single-use token (ten minutes) that carries the plan, the devices, their current
   configuration and the take-over choice. A plan older than the design or the topology cannot be applied:
   the button says to generate it again.
3. **Apply.** The recovery window (2–30 minutes, default 5) and an acknowledgement. The job first backs up
   every chosen device (visible in the backups as `design-pre`); a device whose backup fails is not touched.
   Then, per device: the configuration is read again and compared with the review (a change in between
   refuses that device: *Changed since the review*), the removals and the generated configuration are
   staged, the timed recovery is armed (EOS `commit timer`, Junos `commit confirmed`, IOS XR
   `commit confirmed minutes` on a session kept open), a fresh connection proves management still works,
   the manager confirms only its own pending change, reads the device back and saves (EOS `write memory`).
   A post-change backup (`design-post`) records the result.
4. **Outcomes** per device: *Applied and verified*, *Applied, read-back differs* (with what is missing or
   remaining), *Already matched*, *Not changed* (with the reason), *Undone by the device* (the recovery timer
   ran out before the manager could confirm, and the configuration from before was read back), *Outcome
   unknown* (the device must be looked at; the next review reads it back and settles what is owned),
   *Interrupted* (a manager restart: the device is read back at start-up; a pending change the manager can
   still confirm is confirmed, an IOS XR trial is left to the device's timer). The job is *Applied*, *Partly
   applied*, *Not applied* or *Needs attention*; a healthy label never hides a failed or unverified device.

**Ownership.** The manager owns exactly the statements its own commits added to a device, kept per device in
the lab's private ledger and shown under Advanced as *Owned settings*. The next apply removes only owned
statements the plan no longer wants (a changed link prefix, a removed BGP peer, a dropped protocol), at the
highest container it created when everything under it is its own (`no router ospf 1`, `delete protocols bgp`,
one `no neighbor X` on EOS); a container that also holds manual configuration is kept and said so. Manual
configuration beside the design survives every step; a manual change to an owned setting is a conflict, never
silently overwritten. Removing the design's protocols leaves the addressing of the initial module, removing
the design itself leaves the devices as they are: a later plan of the same lab still knows what it owns.

## Exporting a plan to Git

*Export plan to Git…* on the plan card saves a plan into the lab's Git repository through the same *Save
progress* pipeline as a configuration save, as its own checkpoint folder (`…/checkpoints/<name>`, default
`design-<plan id>`): the design file (`network-intent.yml`), `plan.json`, the netlab `topology.yml`, the endpoint
`mapping.json` and every generated device file (`<device>--<nn>-<module>.cfg`), with a manifest that names them
generated artifacts (`kind: network-design`). The rules of a save apply unchanged: the lab must be bound to a
repository, the job saves on the VM first and stops for the mandatory review, the upload is the reviewed retry, one
save at a time. A design export is never a backup and never a restore source: its manifest carries no device rows and
no restore artifact, so it yields no restore candidate and *Apply to running lab* never offers it.

The manifest's `lab_name` is the lab's name when the save was started; it labels the version and names its download.
Exports made by earlier managers say `mapping.json` there (a naming fault), and that frozen record is never
relabelled. A save started under such a manager and not yet saved on the VM when the manager is upgraded is
refused at its next run with *The plan changed since this export was started*; start the export again. A save that
the old manager was already writing to the VM stays pending instead (every retry repeats the refusal, and the VM
may already hold that save's commit): dismiss it, then start the export again. (Given a
save's recorded digest, `design_snapshot(..., bound=)` can rebuild that older form, but the save does not pass it yet.)

## API

All routes sit behind the same-origin guard; mutating requests carry a JSON body.

| Route | Purpose |
|---|---|
| `GET /api/design/engine` | Engine status from the installed distribution's metadata and the binary on PATH (no process is started): available, version, path, or a precise diagnostic |
| `GET /api/labs/{id}/design` | The intent, its problems, the summary, the generations, and the context: designable devices and links with their mapping, kinds, capability matrix, catalogue, engine status |
| `POST /api/labs/{id}/design/validate` | Problems of a candidate intent, without saving, and its retired uses apart (`retired`, each marked `new` when the saved design lacks it) |
| `PUT /api/labs/{id}/design` | Save the intent (`{intent, revision}`); 400 with the problems, 400 (structured) when it adds a retired module, 409 on a stale revision; the ledger in the body is ignored |
| `POST /api/labs/{id}/design/clear` | Remove the intent (`{revision}`); generations are kept |
| `POST /api/labs/{id}/design/renumber` | Forget the allocation ledger (`{revision}`) |
| `POST /api/labs/{id}/design/generate` | Queue a generation (`{revision}`); 409 while one runs or when the design uses a retired module (structured), 400 (structured: `message`, `problems`) when the intent has problems |
| `POST /api/labs/{id}/design/generations/{gid}/cancel` | Cancel a running generation |
| `GET /api/labs/{id}/design/generations/{gid}` | The generation record and its plan |
| `GET /api/labs/{id}/design/generations/{gid}/artifacts/{node}/{index}` | One generated file, verified against its recorded digest |
| `GET /api/labs/{id}/design/generations/{gid}/download` | A ZIP: the files (`nodes/<device>/<nn>-<module>.cfg`), the plan, the intent, the netlab topology, the mapping and a manifest of type `network-design-generation` (never a backup, never a restore candidate) |
| `GET /api/labs/{id}/design/export` | The intent as `<lab>.network-intent.yml` |
| `POST /api/labs/{id}/design/import` | An intent file (YAML or JSON, up to 512 KiB, no anchors) with the current `revision`; validated before it replaces the stored intent; retired modules are stored and listed (`imported_retired`), Generate and Apply refuse them; the ledger in the file is ignored |
| `POST /api/labs/{id}/design/generations/{gid}/review` | `{targets, takeover, request_id}`: starts a review job (the guards answer at once; 409 with `review_job_id` while one runs for the lab; 409 for a plan with a retired module) and returns `{review_job}` |
| `GET /api/labs/{id}/design/review-jobs`, `GET /api/labs/{id}/design/review-jobs/{job_id}` | The lab's kept review jobs; one job: per device its stage, timeline and a fixed reason, and once done the review (per device the report of the section above and the single-use `token`). Jobs are in memory: a restart forgets them (404, review again) |
| `POST /api/labs/{id}/design/apply` | `{token, confirm_minutes, request_id, takeover, acknowledged: true}`: the apply job; idempotent by `request_id`; 409 when the review expired, the plan changed or carries a retired module, conflicts are not taken over, a review of the lab is running or another operation is busy |
| `GET /api/labs/{id}/design/apply/jobs`, `GET /api/design/apply/jobs/{job_id}` | The lab's apply jobs, one job (public shape: per device status, stage, message, timeline, diff sample, read-back result; never the staged configuration) |
| `POST /api/labs/{id}/design/generations/{gid}/git` | `{request_id, checkpoint, note, push}`: a Git save of kind `design` for the plan (its own checkpoint folder; 409 while a save is pending, for a plan that is not generated, or without a repository binding); the job then follows `/api/git/jobs/{id}` and its reviewed retry |
| `GET /api/labs/{id}/design/ownership` | Per device the number of owned statements, the plan, the time and whether a read-back is pending, plus the statements themselves (masked) |

`/api/state` carries per lab a `design` summary (presence, revision, label, modules, whether a plan is
being generated, the newest generation's id and status, and whether it is stale) and the public apply jobs
as `design_jobs`; the intent, the generations and the ownership ledger never appear there.

## Security boundary

- Design YAML is never netlab project content: the manager builds the topology itself from an
  allowlist. `--defaults`, `-s`, `--plugin`, `-o <expression>`, `plugin`, `defaults.*`, `_include`,
  `config`, `tools`, `validate`, the auto-merged defaults files and `NETLAB_*` variables are all out
  of reach (fixed argv, private working directory and HOME, four-variable environment, keys refused
  by name).
- Compile-only jobs open no network connection (verified with `strace` against the engine and by
  tests that fail the generation on any socket) and never start `docker`, `containerlab`,
  `ansible-playbook`, `ssh` or `netlab up`.
- No pickle is read or accepted; uploads are bounded, parsed with `safe_load`, refused with
  anchors and aliases, and validated before anything is stored.
- Secrets have no place in the intent: `password` and key attributes are refused by name until the
  secret-reference model for protocol authentication exists; public views carry no engine output.
- Existing credentials stay authoritative for every connection; the design never sets a device
  password, user or management address.
- Applying goes over direct node SSH only (no helper, no VM path), inside the NOS's own transaction with its
  timed recovery armed, after a mandatory backup, behind a review token bound to the reviewed configuration,
  and it confirms only the manager's own pending change; the apply, the backups, the Git saves and the
  restores exclude each other through `operation_busy`. Job records and events carry counts, masked
  statements and controlled messages, never a staged configuration or raw device output.

## Engine and licence

netlab is MIT-licensed (copyright Ivan Pepelnjak and contributors); the manager keeps the package
metadata in its image. The pinned release is `networklab==26.9` (upstream tag `release_26.09`). An
upgrade is a deliberate change: bump the pin, regenerate `design_capability_data.json` with the
tool, run the contract tests, and revisit the ledger's evidence.
