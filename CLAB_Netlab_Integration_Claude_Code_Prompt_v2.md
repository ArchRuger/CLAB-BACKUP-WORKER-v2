# Claude Code implementation prompt: netlab network design and configuration integration

## Execution environment and standing authorization

You are running inside the owner's **isolated, totally unrestricted development VM**. **Claude Code's bypass-permissions mode is already enabled.** These are confirmed facts supplied by the owner, not unresolved prerequisites. This is not a read-only review, a restricted execution sandbox, or an assignment that requires approval before each development action.

You have standing authorization to use the VM fully for this implementation and its verification, including:

- Use root/sudo, shell commands, filesystem access, package managers, process management, services, and VM-local networking as needed; install or repair development and testing dependencies.
- Access Docker/containerlab directly for development and diagnostics; pull the required available/licensed images, build containers, refresh installed host helpers, and modify, rebuild, replace, or restart the actual running development version of the manager.
- Create, edit, deploy, stop, destroy, and redeploy project test labs; connect directly to the lab NOS instances; change their configurations; and induce controlled failures, disconnections, restarts, and rollback scenarios to prove recovery behavior.
- Run the complete automated, browser, integration, and live-device test workflows. Use the running application, inspect logs and packet captures, fix discovered defects, and retest rather than stopping at generated files or mocked evidence.
- Make the repository changes, version increments, commits, and working-branch pushes required by this prompt. Clean disposable VM artifacts when necessary, while preserving unrelated work and required recovery data.

**Proceed autonomously within this scope. Do not repeatedly request permission for these already-authorized actions, and do not limit implementation or testing merely because an action requires administrative access or temporarily disrupts the development deployment.** If an actual command fails, diagnose and repair the environment where appropriate; report a remaining blocker from observed evidence, not an assumed permission restriction.

Unrestricted VM access applies to **you as the development agent**, not to the shipped application's privileges. The manager container's restricted access, trusted host helpers, user review/confirmation, credential protection, concurrency guards, and rollback requirements remain product requirements. Exercise those controls during testing; do not remove them to make a test pass. Verify the final application under its intended runtime identities, not only through your administrative shell.

This authorization covers the development VM and its project lab devices, not production systems or unrelated external infrastructure. Unrestricted permissions do not mean unlimited RAM, CPU, or disk: retain the resource-aware testing, coordination, checkpointing, and data-preservation requirements below. Existing limits on force-pushing, merging, and unrelated changes remain in effect.

## Mission and scope

You are working on Containerlab Node Manager:

- Product repository: https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2
- Upstream capability source: https://github.com/ipspace/netlab
- Upstream documentation: https://netlab.tools/

Integrate netlab's addressing, network-design, and device-configuration capabilities into the existing product. This is an implementation assignment: investigate, design, implement, deploy on the development VM, test, correct defects, and checkpoint working increments. Do not stop after producing a proposal, proof of concept, backend skeleton, or UI containing nonfunctional controls.

The product must remain Containerlab Node Manager. It already handles lab creation, lifecycle, topology editing, discovery, readiness, terminals, packet capture, backup/restore, and Git progress in the way the owner wants. Add a coherent network-design and provisioning capability; do not replace those systems with netlab equivalents.

The intended experience is:

**Build or open a lab → define network intent → calculate addressing and routing → inspect generated configuration and compatibility → explicitly apply to selected devices → verify → retain/export the design and evidence.**

Network intent means the user's declared addressing, routing, VLAN/VRF, policy, and service settings. Generated configuration is a derived artifact, not a replacement source of truth for that intent.

## 1. Orchestration and agent routing

Fable 5.1 (`claude-fable-5-1`) is the main orchestrator throughout. It owns the architecture, delegation, integration decisions, development-VM coordination, acceptance criteria, and release checkpoints.

Use the best agent/model for the actual task, not the most expensive model for every task:

| Work | Preferred routing |
|---|---|
| Repository reconnaissance, locating call sites, collecting capability evidence, mechanical inventory work | Haiku, escalating when interpretation becomes substantive |
| Bounded backend/frontend implementation, fixtures, tests, documentation, packaging | Sonnet; select the installed supported version explicitly |
| Difficult network semantics, adapter design, configuration ownership/removal, candidate transactions, security review, consequential cross-module review | Opus 5.5 (`claude-opus-5-5`) when it is the best fit |
| Architecture synthesis, cross-workstream decisions, difficult unresolved integration failures, final acceptance | Fable 5.1 |
| Routine independent QA and regression execution | Sonnet, with targeted Opus/Fable escalation for diagnosis |

Parallelize independent research, implementation in disjoint files, and review when useful. Do not send every worker the entire repository or assign every worker Fable at maximum effort. Equally, do not force a weak model to struggle with a consequential problem just to save tokens. Raise effort or model only where the task warrants it.

Make routing real. Inspect the installed Claude Code version, available models, existing agent definitions, user/project settings, and environment overrides. Use supported agent frontmatter or invocation mechanisms. Check that global subagent overrides do not defeat named assignments; keep forced routing such as `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` disabled where supported. Do not invent configuration keys, model identifiers, or runtime verification commands.

Distinguish requested model from observed model in task metadata. A role name or the agent's assertion about itself is not proof of its effective model. When unavailable, use the best available substitute and record the substitution rather than pretending the requested model ran.

Pass the execution-environment authorization above to delegated agents whose work needs it. Use the full available VM/tool access through supported delegation mechanisms; do not give implementation or test agents an artificial read-only scope when their assigned task requires changes. Verify actual tool failures rather than assuming that a delegated process has identical permissions.

Only one coordinator may mutate the shared live lab at a time. Use disjoint working areas or worktrees for parallel edits; do not let agents fight over version files, deployment state, or the same device session.

## 2. Findings from the preliminary repository scan

These are starting observations, not permission to skip checking the current checkout:

- The manager was inspected on `main` at `1e72899cfa065301238f4d17d075d720aca11b35`; the advertised version was **1.30.42**.
- netlab was inspected on its default `dev` branch at `3cfe023094b6ed3351cce8a023b533cfec7a9a83`. Its README advertised release 26.09. Do not assume that a development checkout is the appropriate production dependency or that these revisions remain current.
- The manager uses FastAPI, encrypted persistent state, feature services with `install(app)` route registration, and a predominantly plain-JavaScript frontend. Its embedded topology editor is a separately built and committed TypeScript/React bundle. A lab VM does not need Node/npm to serve the product.
- The manager container has no Docker socket and no general-purpose privileged host shell. Host operations use structured requests through the restricted SSH gateway and exact helpers.
- `lab_operations.operation_busy` and existing guards coordinate operations, backups, Git progress, restores, and device cleanup. New provisioning must join that coordination, not create an independent conflicting execution path.
- `restore_drivers.py` specifies whole-active-configuration replacement. Its Junos, EOS, and IOS XR drivers use native transactions and timed recovery. That contract does NOT make arbitrary netlab module fragments safe restore inputs.
- The lab builder currently publishes topology and annotations. Its documentation explicitly excludes startup-configuration file creation. Publishing a new configuration bundle would require deliberate helper, validation, and recovery work.
- Git progress deliberately exports configuration artifacts and a manifest, not arbitrary topology files or unrelated checkout edits. Preserve that contract.
- The current inventory parser preserves concrete Junos kinds instead of treating every Junos device as cJunosEvolved. Preserve that distinction in the new adapter too.
- netlab's current `create` pipeline transforms topology and generates per-node configuration files without requiring deployment. Since release 26.01, rendering is not an Ansible-template-generation step. The inspected configuration output implementation creates ordered per-node/module artifacts under `node_files` and removes the previous `node_files` directory in its working directory.
- netlab's external provider supports explicit management addresses and endpoint `ifname` values. It is a promising compiler-only route for a lab whose lifecycle is managed elsewhere, but its suitability must be proven for the selected modules and exact devices.
- The inspected `vptx` profile targets `juniper_vjunosevolved`, not `juniper_cjunosevolved`. The inspected `iosxr` container profile targets `cisco_xrd`, not `cisco_xrv9k`. The vJunos-switch profile also defaults to a different image release than the owner's test image. Shared NOS lineage is not evidence of interchangeable interface maps, templates, transport, or feature support.
- The published module matrix does not expose EIGRP on the owner's four baseline platforms. That does not justify removing EIGRP from the integration's capability framework; it means the UI must correctly refuse unsupported targets and distinguish broader upstream support from support on this lab.
- The distribution name in netlab's `pyproject.toml` is `networklab`; the CLI is `netlab`; the Python namespace is `netsim`.
- The manager's CI lists many test files explicitly. Adding a new test file without registering it can leave it outside CI.

Do not repeat stale assumptions from an older prompt when the checkout proves otherwise. Record important differences and adjust the implementation, while preserving the boundaries below.

## 3. Nonnegotiable product boundaries

Preserve every existing capability and its behavioral tests. In particular preserve:

- Existing labs, topology YAML, annotations, unknown-but-valid Containerlab fields, custom kinds/images, environment settings, startup delays, management settings, port mappings, and user-selected interface names.
- The difference between **Edit map** and actual topology editing. Map edits must remain drawing-only. Adding network design must not permit accidental structural edits to deployed labs.
- Deployment review/confirmation, readiness, direct NOS connections, browser SSH, capture, backups, per-device downloads, snapshot restore, credentials, Git review/push, and Latest/checkpoint semantics.
- Encrypted state, scrubbed public responses/logs, exact-path host helpers, trusted roots, symlink/traversal protections, owner-scoped Git, preview tokens, and concurrency guards.
- Old workspaces and archives with no network-intent data. The feature is opt-in; no mass migration, renumbering, or automatic configuration changes.

Do not replace deployment with `netlab up`, destroy with `netlab down`, terminals with `netlab connect`, capture with `netlab capture`, or backup/Git workflows with netlab equivalents. Do not add Vagrant/libvirt management, a second topology editor, or a generic shell runner to the product.

Do not reintroduce the retired telemetry/Grafana feature or unsolicited usage reporting. Preserve the existing retirement/migration cleanup where required. Inspect and disable any upstream usage-statistics behavior in this integration through supported settings.

No broad framework migration, wholesale rewrite, or unrelated feature removal. Do not modify the student guide as part of this assignment. Update the relevant technical, architecture, maintenance, validation, and handoff documentation.

The execution-environment authorization above is explicit: Claude is in a totally unrestricted development VM with bypass permissions already enabled. The development environment may be rebuilt, packages installed, containers restarted, test configurations changed, and controlled failures induced as needed without repeated approval requests. These product boundaries constrain the shipped manager, not Claude's administrative development/testing access. They do not authorize weakening shipped security or skipping confirmation in the actual product.

Inspect disk/RAM/CPU before testing. Clean clearly disposable caches or stopped test artifacts when needed, but preserve required images, credentials, persistent product data, unrelated work, and recovery evidence.

## 4. Inspect reality before editing

Inspect Git status, branch, remote, upstream, recent history, open work, current version, and deployed-versus-source versions. Preserve unrelated uncommitted changes. Do not reset or overwrite them.

Read `CLAUDE.md`, the current relevant sections of `agent instructions.md`, and:

- `docs/ARCHITECTURE.md`, `docs/REPOSITORY-MAINTENANCE.md`, `docs/LAB-BUILDER.md`, `docs/GIT-PROGRESS.md`.
- The current UI contracts and relevant lab-builder/multi-platform-restore pickup and validation notes.
- `app/main.py`, `store.py`, `inventory.py`, `discovery.py`, `topology.py`, `layout.py`, `vm_files.py`, and `host_files.py` under `clab-backup-ui/`.
- `lab_operations.py`, `host_operations.py`, `runner.py`, `git_progress.py`, `host_git.py`, the restore service/driver/shell/compare modules, readiness and credential resolution.
- The relevant frontend scripts, `lab-builder/src/main.tsx`, deployment scripts, dependency files, release tools, and CI workflow.

Follow actual call paths; do not rely solely on documentation. Identify state mutation points, public serializers, review-token binding, archive validation, helper protocol/version checks, runtime credentials, and job interruption recovery.

Inspect the selected upstream revision's topology augmentation/addressing, module dependency processing, device inheritance/quirks, capabilities, templates, output modules, initial/config deployment paths, external provider, reports, and tests. Verify exact syntax and actual file layout instead of assuming pre-2026 examples still apply.

Run baseline Python, JavaScript, release, static, and relevant browser tests before modifying their behavior. Record pre-existing failures separately. Discover the actual VM paths, installed dependencies, resources, running services, and test-lab state rather than assuming a previous VM/path still exists. The unrestricted VM and enabled bypass-permissions mode are already confirmed; this inspection determines operational state, not whether ordinary development actions are authorized.

Create a persistent workstream directory such as `docs/netlab-integration/`, containing a pickup file, design decisions, compatibility evidence, feature checklist, and test results. Keep these useful for recovery, not as redundant documentation sprawl.

## 5. Integration architecture to validate and implement

### 5.1 Ownership and source of truth

Use three explicit layers:

1. **Containerlab topology and runtime identity:** existing manager/Containerlab remain authoritative for devices, images, physical links, deployment state, management connectivity, and lifecycle.
2. **Versioned network intent:** a manager-owned, portable data document records requested addressing, routing, services, policies, platform selections, and stable allocation/mapping decisions.
3. **Generated artifacts:** an immutable generation contains the normalized plan, ordered per-device configuration artifacts, warnings/capabilities, dependency identity, and provenance.

Do not make users maintain two independent physical topologies. Derive netlab's working topology from the existing Containerlab topology plus the intent document. Do not overwrite the original `.clab.yml` with a generated netlab provider file.

A sidecar such as `<lab>.network-intent.yml` is a possible persistence format, not a mandated filename. Choose a schema-versioned layout that fits existing imports, VM sync, downloads, and trusted publication. Avoid silently storing the only copy in browser storage or only in opaque runtime state.

Persist stable node/link identities and explicit endpoint mappings. Do not infer all interface names from link enumeration. Represent:

`manager node identity ↔ Containerlab node/kind/image ↔ netlab profile ↔ Containerlab endpoint ↔ actual NOS interface`

Deal explicitly with inherited topology defaults/kinds/groups, parallel links, different endpoint syntaxes, arbitrary port choices, unmanaged support nodes, and node renames. An unresolved mapping blocks generation/apply for affected targets rather than falling back to a guessed port.

Existing discovered addresses and credential precedence remain authoritative for actual connections. Design pools must never silently replace management addressing or SSH port mappings.

### 5.2 Reuse netlab instead of rebuilding it

Prefer a pinned `networklab` dependency behind a narrow adapter. Evaluate a manager-owned worker process and separate dependency environment before introducing a permanent service. Use a service only when it solves a demonstrated packaging, isolation, or execution problem.

Prefer supported generation commands/output contracts over broad imports of unstable internals. A bounded internal API is acceptable where necessary, but isolate it and protect it with version-specific contract tests. Do not scatter upstream internal calls throughout the application or copy its complete module/template tree into a fork.

Prototype a compiler-only external-provider path using explicit `ifname` and management metadata. Compare alternatives where provider-specific quirks demand it. Keep the lifecycle boundary regardless of the selected compiler route. Do not blindly map cJunosEvolved to vPTX or XRv9k to XRd.

Select a released, tested upstream version/commit, pin dependencies and trusted extensions, retain required license/notices, and document upgrades. Do not install a floating Git `dev` branch at application startup. Inspect upstream licensing and redistribution requirements rather than assuming the two projects have identical licenses.

Generation must run in a dedicated per-job working directory, with controlled HOME/environment, bounded resources, explicit input/output locations, timeouts, and cancellation. Never run it in the user's checkout, live topology folder, manager data root, or a shared `node_files` directory.

Use explicit output selection. Do not rely on default outputs, default Ansible inventory credentials, default images, or undocumented ordering. Prefer data-only JSON/YAML artifacts for interchange. Never accept or deserialize an uploaded pickle; upstream-generated private snapshots are not an import format.

A process/venv is dependency isolation, not a security sandbox. Accept data-only, validated intent and trusted engine code/templates. If an accepted feature can execute untrusted code, introduce a real security boundary before exposing it. Do not claim isolation merely because it runs in another process.

When the engine is missing, broken, or incompatible, show a precise feature-specific diagnostic. Existing deployment, terminal, backup, capture, and restore functionality must remain usable.

### 5.3 Capability model

Implement one shared capability model used by backend validation and UI. Track separately:

- What the selected netlab revision can model/render.
- What the exact platform/profile/NOS image can accept.
- What the manager integration has actually validated, and at what level.

Support statuses such as verified on image, generated/validated but not live-tested, unsupported, and blocked by a missing prerequisite. Do not flatten these to a single green checkmark.

Capture feature, address family, prerequisite modules, transport, relevant subfeatures, image/version, adapter version, and evidence. Resolve upstream inheritance and overrides correctly. Supplement upstream metadata with narrowly scoped integration-specific limitations; do not maintain a disconnected hand-written copy of the whole upstream matrix.

Never silently omit a requested feature, downgrade it to a different protocol, or label a rendered template as verified data-plane support. Unsupported targets must be rejected before any device mutation.

## 6. Functional coverage

The architecture and user-accessible intent model must accommodate the entire requested scope. Implement in dependency-ordered increments, not as one giant change. A feature can be unavailable on a particular image without being absent from the integration framework.

| Area | Required coverage |
|---|---|
| Addressing and routing design | IPv4 and IPv6 addressing plans; OSPFv2, OSPFv3, EIGRP, IS-IS, RIPv2, RIPng, BGP design |
| Interfaces and services | IPv4, IPv6, DHCP, DHCPv6, VLANs, VRFs, LLDP, BFD, static routes |
| Layer 2 and gateways | LACP, LAG, MLAG, link bonding, STP, VRRP, anycast gateways |
| Encapsulation and tunnels | VXLAN, GRE, WireGuard |
| Routing protocols and policies | OSPFv2/v3, EIGRP, IS-IS, BGP, RIPv2/RIPng, route maps/policies, IP prefix lists, AS-path filters/lists, redistribution, default origination |
| Service-provider features | MPLS, BGP-LU, VPNv4/VPNv6 L3VPN, 6PE, EVPN, SR-MPLS, SRv6 |

Treat protocol families and subfeatures correctly. OSPFv2/v3, RIPv2/RIPng, VPN address families, and MPLS-related features need not each correspond to separate upstream modules. Resolve the real upstream schema. “AS-path prefix lists” in the request means the appropriate platform-specific AS-path filtering/policy constructs, not IP prefix-list semantics applied to AS numbers.

Provide approachable guided controls for common workflows plus an advanced, schema-validated semantic intent editor for the long tail. A generic text box alone is not an adequate student UI; neither is implementing every conceivable subfeature as a bespoke form. Round-trip advanced supported fields without silently dropping them.

### Addressing and routing-plan requirements

Support automatic allocation and explicit assignments, dual stack and single stack, loopbacks, point-to-point links, LAN/shared segments, VLAN/VRF scopes, address-family selection, and unnumbered modes where supported.

Expose relevant routing parameters: router IDs, ASN assignments, iBGP/eBGP neighbors, route reflectors, OSPF areas/passive interfaces, IS-IS NET/levels, and the appropriate controls for other supported protocols. Resolve dependencies rather than making users manually calculate every peer and interface value.

Validate pool exhaustion, invalid prefixes, same-scope overlap, duplicate addresses, duplicate IDs, peer/AF mismatch, unreachable peering dependencies, invalid VLAN/VRF references, and unsupported combinations. Overlapping customer prefixes in separate VRFs can be legitimate; do not globally reject them.

Plans must be repeatable. The same semantic input, engine, profiles, and saved allocations must yield the same semantic result. Adding or reordering an unrelated node/link must not silently renumber existing devices. Preserve allocation assignments or explicitly show/review unavoidable renumbering. Separate volatile timestamps from deterministic artifact comparison.

Export a readable addressing/adjacency summary and machine-readable plan. Include exclusions and unresolved prerequisites. An advanced user should be able to inspect why an address, neighbor, policy, or module was generated.

## 7. Configuration generation, ownership, and safe apply

### 7.1 Immutable generation and review

A generated job should bind together input topology and intent hashes, stable target identities, engine/profile versions, ordered module artifacts, file hashes/sizes, warnings, and capability decisions. Preserve generation history within bounded storage limits.

Preview must identify exact targets, interfaces, additions, removals, protected settings, affected protocols, and likely disruption. Render a configuration preview and, where supported, a device-native candidate diff. Distinguish a generated text diff from an actual candidate-versus-running diff.

Bind an expiring review token to the exact generation, targets, input revisions, mapping, and relevant live baseline. Recheck drift before applying. Do not regenerate different bytes after the user approves and then apply those different bytes under the old approval.

Planning, previewing, and downloading must not configure devices, deploy/destroy a lab, install images, start services, alter Git history, or require Docker access. Test this property, including negative cases.

### 7.2 A separate provisioning contract

Create an explicit network-design provisioning service/driver contract. Reuse existing transport, credential resolution, backup, transaction, logging, and comparison primitives when appropriate, without silently changing the meaning of snapshot restore.

**Never submit netlab module fragments to a whole-configuration replacement API as though they were full backups.** File extensions do not establish replacement safety. Concatenating snippets does not automatically produce a complete or valid candidate.

For each supported platform, establish a native candidate/staging process that preserves the existing management baseline and unrelated user configuration. Identify the exact scope managed by the design: interfaces/units, addresses, protocol instances, policies, VLANs, VRFs, and dependent objects.

Persist ownership/provenance sufficient to remove or replace previously generated state. Changing an IP, removing a BGP peer, disabling a protocol, or deleting a VRF must not leave the old state behind. Conversely, never delete everything under `router bgp`, `protocols`, `interfaces`, or another broad hierarchy merely to simplify reconciliation.

Where managed and manual objects conflict, block with a useful explanation or require an explicit reviewed ownership decision. Do not claim that a generic line-based merge works across Junos, EOS, and IOS XR.

A full replacement route may be offered only with an explicit user choice, a genuine complete candidate, protected-management checks, and the existing replacement-grade safety contract. Do not make it the default workaround for ownership reconciliation.

### 7.3 Execution and recovery

Integrate with the current operation locks, backup and Git serialization, shutdown/lifespan handling, interrupted-job reconciliation, and public-output scrubbing. Extend the existing design rather than inventing a second queue framework.

Before device mutation, resolve current node identity, reachability, credentials, interface mapping, readiness, feature support, baseline drift, pending commits/sessions, and third-party candidate edits. Capture a usable pre-change backup with integrity metadata.

Use native transactions and timed recovery where supported. Preserve the existing IOS XR requirement that confirmation belongs to the session which armed its confirmed commit. Never confirm another user's pending change.

A fresh reconnect proves management survived; semantic read-back verifies the intended configuration. Add applicable control-plane/data-plane verification. Define which checks must pass before confirmation and size timers accordingly. Manage timers across multiple nodes deliberately; do not let later targets consume an earlier node's recovery window accidentally.

Support cancellation, disconnect, manager restart, worker timeout, partial failure, verification failure, repeated requests, and rollback. Persist per-node outcomes and distinguish confirmed, reverted, failed, interrupted, and unknown states. Reconcile unknown state instead of assuming success or blindly retrying.

Do not promise lab-wide atomicity. Separate per-device transaction guarantees from lab-level recovery behavior and document what happens after one device succeeds and another fails. A healthy-looking overall label must not conceal failed or unverified nodes.

Do not automatically replay a saved design during ordinary deploy/redeploy unless the user has explicitly enabled a separately reviewed behavior. Default to post-readiness, explicit provisioning through the new workflow.

## 8. Student-facing UI and persistence

Integrate into the existing lab workspace and builder conventions without a competing navigation system or editing the vendored editor bundle directly.

Provide clear states: no design, draft changed, generation in progress, validation failed, ready to review, applying, verification in progress, applied/verified, partial failure, and interrupted/needs review. Separate these from container readiness and existing saved-progress states.

A practical flow is:

1. Open **Network design** for a lab or draft.
2. Choose targets, addressing pools/manual assignments, protocols, and services.
3. Inspect the calculated address/adjacency plan and per-target compatibility.
4. Generate and review per-device configuration, removals, dependencies, and warnings.
5. Download/export or explicitly apply selected targets.
6. See live progress, verification, recovery actions, and the associated saved design.

Support both freshly built and already deployed labs. Generation need not require deployment; application requires valid current endpoints and readiness. Network design does not authorize structural topology changes on deployed labs.

Use plain explanations and progressive disclosure. Prevent duplicate submission. Keep errors and partial results visible rather than hiding them in transient toasts. Preserve drafts across ordinary navigation/reloads and protect against stale tabs overwriting newer edits. Escape all rendered values and retain CSP and accessibility conventions.

Persist network intent across workspace reload, manager restart, appropriate import/export, and supported VM synchronization. Define schema migrations and backward-compatible absence of new fields.

Add an explicit **Export/save network design** path that uses the established reviewed/owner-scoped Git mechanisms. It may have its own allowlisted artifact set, but must not change ordinary configuration Save progress into “commit every file in the workspace.” Preserve `working/latest`, checkpoint handling, user-selected subfolders, dirty-file isolation, and no nested `latest/latest` behavior.

Keep intent, generated configs, captured running backups, and restore-grade full candidates distinguishable in manifests and UI. Do not let a design export masquerade as a restorable backup. Validate imported paths, hashes, sizes, schemas, and artifact types.

If file publication requires additional trusted helper operations, implement bounded transactional publication, history/recovery, stale-version protection, same-release helper checks, and failure cleanup. Do not add a generic arbitrary-file write primitive.

## 9. Security and packaging requirements

Network-design YAML is not arbitrary executable netlab project content. Do not pass unrestricted uploaded keys/paths/options to the CLI.

Use allowlisted semantic inputs and trusted built-in extensions. Inspect and constrain topology includes, local/remote file references, plugin loading, custom templates/Jinja, hook/exec fields, provider options, tools, validation commands, arbitrary defaults/search paths, inventory transport overrides, and output destinations. Some trusted built-in plugins may be needed for requested features: allow them explicitly with constrained parameters, not by accepting arbitrary Python plugin names or paths.

Do not weaken the existing Containerlab topology contract while enforcing this new compiler boundary. Preserve existing topology fields, but do not automatically propagate executable Containerlab fields into the netlab compiler input.

Protect against YAML alias/resource bombs, excessive nesting, duplicate/conflicting keys, path traversal, symlink escape, shell argument injection, command injection through generated NOS text, cross-lab file access, and stale/mixed-generation artifacts. Use bounded input/output sizes and allowlisted argv; no browser-supplied command strings.

Route apply only to the current lab's selected device identities, not arbitrary addresses supplied by an uploaded design. Compile-only jobs must not initiate target-network connections. Detect and block unexpected network access or hidden lifecycle execution in tests.

Keep existing credentials authoritative. Do not substitute netlab's default passwords. Protocol authentication and WireGuard private keys need a deliberate secret-reference model: no plaintext private keys in intent exports, manifests, ordinary logs, Git, screenshots, or `/api/state`. Private execution artifacts must have restricted access and cleanup/retention rules.

Pin the engine and dependency set without casually upgrading the manager's existing Ansible/collections stack. Verify final image build, fresh install, upgrade, health checks, and offline generation after installation. Expose engine/version compatibility through relevant diagnostics. No workstation installation, global VM netlab installation, or Node build on the lab VM should be required merely to use this feature unless a demonstrated prerequisite is documented and integrated into installation.

## 10. Validation: real tests, not plausible output

### Baseline live lab

Use the owner's four-node square, exactly one of each baseline NOS image:

- `n24l/ceos:4.35.0F` — `arista_ceos`
- `n24l/cjunosevolved:26.2R1.7-EVO` — `juniper_cjunosevolved`
- `n24l/vjunos-switch:23.2R1.14` — `juniper_vjunosswitch`
- `n24l/cisco_xrv9k:24.3.1` — `cisco_xrv9k`

Discover and reuse the current acceptance-lab tooling where appropriate. Do not silently replace these with easier images or assume a differently tagged installed image is equivalent. Respect VM resource limits and keep image-specific work in manageable chunks. Do not boot several duplicate heavy test labs concurrently.

This square is an interoperability baseline, not proof of every requested topology. MLAG, same-platform redundancy, or a protocol unsupported by these images may require peers/capabilities absent from this lab. Record those live-test limitations precisely. Use generation/contract/negative tests for unavailable combinations without calling them live-verified. Additional live topologies must respect the owner's resource constraints and available licensed images.

### Automated tests

Cover schema and backward compatibility; topology inheritance and endpoint mapping; deterministic allocations and meaningful renumbering; IPv4/IPv6 pool edge cases; VRF-scoped overlap; capabilities and dependencies; per-module output order; stable provenance; unsupported combinations; and masked secrets.

Add pinned-engine integration fixtures that actually run the chosen compiler. Include the exact profile overrides/adapters and compare semantic results, not just whether an output file exists. Include topology permutations and explicit interface assignments so order-based mapping bugs surface.

Test job locking, duplicate submissions, review-token expiry/mismatch, drift, helper mismatch, timeouts, cancellation, partial file writes, interrupted jobs, restarts, rollback, and output redaction across streamed chunks.

Test complete workflows through the real FastAPI app using scratch state. Never point a test Store at live data. Add the new test files to the explicit CI lists.

### Live protocol verification

Prove IPv4/IPv6 addressing and reachability, applicable OSPFv2/OSPFv3 and IS-IS adjacency, eBGP/iBGP operation, selected advertised/learned prefixes and next hops, and withdrawal when generated state is removed.

Then validate feature families on compatible targets with appropriate assertions: VLAN/VRF isolation, DHCP leases where supported, BFD behavior, LAG members, gateway failover where the topology permits, tunnel establishment/traffic, EVPN routes and tenant reachability, MPLS/LU/VPN labels and routes, and segment-routing control/data-plane behavior.

Use both positive and negative reachability. A tenant isolation test is not complete because allowed traffic passes; disallowed traffic must also fail. Do not claim EIGRP on these four baseline platforms just because upstream supports it elsewhere.

For generated state, test create → apply → verify → reapply/no-op → modify → remove → verify cleanup, while unrelated manual configuration survives.

Exercise invalid syntax, pending third-party edits, SSH loss, one-device failure, manager restart after arming a change, and genuine timed rollback on each supported provisioning driver. Maintain recovery access and evidence.

### Browser and regressions

Run actual browser workflows for new design creation, advanced intent round-trip, invalid addressing, unsupported combinations, preview/download, selected apply, live progress, failures, reload/recovery, and artifact export. Capture useful screenshots and browser-console evidence.

Recheck existing deploy/build, VM discovery, readiness, terminals, map-only editing, capture, backups, individual/ZIP downloads, Latest/checkpoints, Git review/push, and snapshot restore. Preserve existing behavior assertions; do not delete difficult tests or weaken them to accommodate a regression.

Rebuild and use the actual running product, not just a fixture server. You are already authorized to modify the development deployment, refresh root-owned helpers, restart services and containers, and change test-device configurations to complete this validation. Execute the product's normal review/confirmation steps yourself through the UI/API test flow; Claude Code bypass permissions do not remove those product controls. Verify helper/runtime versions match and browser assets are from the new release. Clearly distinguish unit, integration, browser-fixture, and real-VM/device evidence.

## 11. Delivery sequence and checkpoints

Use these as milestones, splitting each into smaller independently safe chunks when necessary:

**A. Baseline and feasibility.** Establish repository/runtime truth, baseline tests, effective agent routing, capability evidence, and compiler-only proof using the actual topology mappings. Record architecture decisions. Do not enable unsafe application paths.

**B. Engine boundary and data model.** Pin/package the engine; implement validated intent, adapters, stable identity/allocation, capability responses, generation jobs, artifacts, and backward-compatible persistence. Prove no deployment or device writes occur during planning.

**C. First complete student workflow.** Deliver usable guided dual-stack design with OSPF/BGP, plan/configuration preview, download, persistence, and correct unsupported-target behavior. This is an initial vertical slice, not a reason to abandon the rest of the scope.

**D. Safe provisioning, platform by platform.** Implement and independently review candidate/ownership/recovery semantics; validate EOS, cJunosEvolved, vJunos-switch, and XRv9k in image-specific chunks. Select the implementation order from observed feasibility, not assumptions. Preserve whole-snapshot restore behavior.

**E. Requested feature families.** Extend IGPs/policies/services, L2/gateways, tunnels, and service-provider modules through the shared engine and capability framework. Provide usable common controls and validated advanced intent. Keep unsupported/image-limited cases explicit; no fake universal support.

**F. Persistence/export and release hardening.** Finish reviewed design-artifact export, import/VM sync where applicable, diagnostics, failure recovery, browser usability, packaging/install/upgrade, full regressions, and evidence-backed documentation. Perform this earlier where necessary to avoid an unusable vertical slice.

Every completed code-change chunk must be implemented, tested, documented, and checkpointed before beginning another substantial chunk:

1. Review the diff and fix discovered regressions.
2. Increment the current patch version by exactly **+0.0.1**, using `deploy/set-release.py`; do not hardcode a starting version from this prompt.
3. Update changelog, validation evidence, and concise pickup/handoff notes using the repository's conventions.
4. Run the required Python/JavaScript/static/release checks and relevant live/browser tests. Keep work incomplete or feature-gated rather than exposing broken functionality.
5. Commit only the intended coherent changes, push the working branch, and verify that the expected remote commit exists. No force-pushing or auto-merging into main without authorization.
6. Record commit/version, tests, effective routing, artifacts/evidence, known limitations, and the next exact action.

Distinguish a development checkpoint from final full-feature release acceptance. A checkpoint does not justify advertising untested capabilities. Do not mark a chunk fully validated when its required tests did not run.

Use the repository's current commands, including as applicable:

```bash
# From clab-backup-ui; use the actual prepared environment.
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m unittest discover -s tests -t tests
node --test tests/*.js

# From repository root.
python3 deploy/verify-release.py
git diff --check
```

Check changed scripts, built-editor asset consistency when touched, installation health, and CI results too. Do not blindly run `set-release.py` before deciding the actual next version.

## 12. Completion criteria and final report

This assignment is complete only when the integrated workflow is usable in the running product, existing features remain intact, the requested feature families are represented by a real capability-aware implementation, and the claimed levels of support are backed by evidence.

Do not equate “all feature names appear in a dropdown,” “netlab accepted YAML,” or “Ansible exited zero” with completion.

Maintain a feature-by-platform ledger with: requested capability, upstream support, adapter support, generation tests, live evidence, UI path, prerequisites, known limitation, and remaining work. Features absent from the baseline images may remain explicitly unsupported or not-live-verified; do not disguise an unimplemented integration feature as a platform limitation.

The final report must contain:

- What was implemented and how a user reaches it.
- The selected architecture and pinned engine/profile/dependency identities.
- The actual compatibility matrix for the four images, including the cJunosEvolved/vPTX and XRv9k/XRd distinctions.
- Configuration ownership, protection, removal, transaction, recovery, and partial-failure semantics.
- Validation evidence, pre-existing failures, unresolved blockers, and untested claims clearly separated.
- Versions, commits, verified remote checkpoints, and installation/upgrade implications.
- Existing-feature regression results and **Intentionally removed: None** for this integration; retired telemetry/Grafana remains retired.
- Exact recovery/pickup instructions when anything remains outstanding.

Begin with repository/runtime verification and focused parallel reconnaissance. Make concrete architecture decisions, then continue through implementation and evidence-driven testing. Claude Code bypass permissions are already enabled in this totally unrestricted development VM: use the available administrative, deployment, browser, and live-device capabilities to finish and verify the work. Do not repeatedly stop to ask permission for development-VM actions already authorized here. Protect existing user work, preserve the shipped product's security boundaries, and ship incremental, recoverable progress rather than a sweeping unverified rewrite.

## Reference locations for the preliminary scan

Re-check these at the current checkout or selected pinned release. The preliminary scan was a source/documentation review, not a live-VM validation.

Manager source at `1e72899cfa065301238f4d17d075d720aca11b35`:

- `README.md` — advertised release and product scope.
- `CLAUDE.md` — service composition, security/concurrency boundaries, frontend structure, CI registration and test commands.
- `docs/ARCHITECTURE.md` — module map and host/device access paths.
- `docs/LAB-BUILDER.md` — topology/annotations publication and current startup-config exclusion.
- `docs/GIT-PROGRESS.md` — configuration/manifest-only export contract.
- `clab-backup-ui/app/restore_drivers.py` — whole-configuration replacement contract and IOS XR held-session semantics.
- `clab-backup-ui/app/lab_operations.py` — `operation_busy`, helper client, output scrubbing, review/job integration.
- `clab-backup-ui/app/host_operations.py` — fixed-argv structured helper, path constraints and file limits.
- `clab-backup-ui/app/inventory.py` — concrete kinds, credential precedence and data-only inventory parsing.

Upstream source at `3cfe023094b6ed3351cce8a023b533cfec7a9a83`:

- `README.md` — requested capability list and advertised release.
- `pyproject.toml` — `networklab` package and `netlab` CLI.
- `netsim/cli/create.py` — transformation followed by selected output modules and plugin hooks.
- `netsim/outputs/config.py` — per-node/module rendering and working-directory cleanup behavior.
- `netsim/devices/vptx.yml`, `iosxr.yml`, `vjunos-switch.yml` — profile/kind/image/interface/transport distinctions.
- `netsim/ansible/templates/initial/junos.j2` — example generated hierarchical configuration fragment.

Upstream documentation checked during the scan:

```text
https://netlab.tools/release/26.01/
https://netlab.tools/netlab/create/
https://netlab.tools/netlab/initial/
https://netlab.tools/outputs/
https://netlab.tools/labs/external/
https://netlab.tools/platforms/
https://netlab.tools/module-reference/
https://netlab.tools/dev/transform/
```
